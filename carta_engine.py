"""
carta_engine.py
----------------
Motor de lectura y reescritura de precios para el PDF de la Carta
(distinto del cotizador de eventos). Pensado para vivir junto a
generate_pdf.py en el repo campobravo-pdf (Render).

Dependencias nuevas a agregar a requirements.txt:
    pymupdf
    pillow

Uso típico (ver carta_routes.py):
    items = extract_carta_items(pdf_bytes)
    new_pdf_bytes = apply_prices_to_carta(pdf_bytes, price_map)
"""

import re
import math
import io
from PIL import Image
import fitz  # pymupdf

DIGIT_CHARS = set("0123456789$")
PRICE_RE = re.compile(r'\$\s?\d[\d.]*')

# Fuentes que NUNCA se tocan automáticamente (ej: el cubierto usa Copperplate).
EXCLUDED_FONTS = {"Copperplate"}

# Tamaño de letra por debajo del cual consideramos que es texto de
# descripción (no un título de sección ni un ítem con precio).
HEADER_MIN_SIZE = 15.0


# ---------------------------------------------------------------------
# 1) EXTRACCIÓN — para la pantalla "Actualizar base de la carta"
# ---------------------------------------------------------------------

def extract_carta_items(pdf_bytes):
    """
    Lee un PDF de carta (una o más páginas) y devuelve una propuesta de
    agrupamiento en secciones. Esto es una PROPUESTA: el frontend debe
    mostrarla para revisión humana antes de guardar en Firestore, porque
    hay layouts (ej. una sección partida en dos columnas sin repetir el
    título) que no se detectan de forma 100% confiable.

    Cada ítem incluye un "locator" (page/bbox/font/size) que es la
    posición EXACTA del precio en el PDF base. Ese locator es lo que hay
    que guardar en Firestore junto al ítem: es lo que después usa
    apply_prices_by_locator() para saber dónde escribir el precio nuevo,
    sin depender de volver a matchear por nombre de texto (frágil).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    sections = []  # [{name, items: [{name, price, locator}]}]
    warnings = []

    for page_index, page in enumerate(doc):
        raw = page.get_text("rawdict")
        page_width = page.rect.width
        entries = []  # {kind, text, price, x0, y0, column, locator}

        for block in raw["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["font"] in EXCLUDED_FONTS:
                        continue
                    chars = span.get("chars", [])
                    text = "".join(c["c"] for c in chars).strip()
                    if not text:
                        continue
                    size = span["size"]
                    x0, y0 = span["bbox"][0], span["bbox"][1]
                    column = 0 if x0 < page_width / 2 else 1

                    if size >= HEADER_MIN_SIZE:
                        entries.append({
                            "kind": "header", "text": text,
                            "x0": x0, "y0": y0, "column": column,
                        })
                    else:
                        m = PRICE_RE.search(text)
                        if m:
                            price = int(re.sub(r'[^\d]', '', m.group()))
                            name = (text[:m.start()] + text[m.end():]).strip(" -·")
                            match_chars = chars[m.start():m.end()]
                            bbox = [
                                min(c["bbox"][0] for c in match_chars),
                                min(c["bbox"][1] for c in match_chars),
                                max(c["bbox"][2] for c in match_chars),
                                max(c["bbox"][3] for c in match_chars),
                            ]
                            entries.append({
                                "kind": "item", "text": name or text,
                                "price": price,
                                "x0": x0, "y0": y0, "column": column,
                                "locator": {
                                    "page": page_index,
                                    "bbox": bbox,
                                    "font": span["font"],
                                    "size": round(span["size"], 1),
                                },
                            })

        # orden de lectura: columna izquierda de arriba a abajo, luego derecha
        entries.sort(key=lambda e: (e["column"], e["y0"]))

        current_section = None
        for e in entries:
            if e["kind"] == "header":
                current_section = {"name": e["text"], "items": [], "page": page_index}
                sections.append(current_section)
            else:
                if current_section is None:
                    warnings.append(f"Ítem sin sección detectada: {e['text']} (revisar manualmente)")
                    current_section = {"name": "Sin sección (revisar)", "items": [], "page": page_index}
                    sections.append(current_section)
                current_section["items"].append({
                    "name": e["text"], "price": e["price"], "locator": e["locator"],
                })

    return {"sections": sections, "warnings": warnings}


# ---------------------------------------------------------------------
# 2) REESCRITURA — para la pantalla "Ajustar precios"
# ---------------------------------------------------------------------

def _build_glyph_atlas(page, dpi=600):
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    raw = page.get_text("rawdict")
    atlas = {}
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars", [])
                key = (span["font"], round(span["size"], 1))
                for i, c in enumerate(chars):
                    ch = c["c"]
                    if ch in DIGIT_CHARS:
                        adv = None
                        if i + 1 < len(chars):
                            adv = chars[i + 1]["origin"][0] - c["origin"][0]
                        atlas.setdefault(key, {}).setdefault(ch, []).append({
                            "bbox": c["bbox"], "adv": adv
                        })
    return img, zoom, atlas


def _pick_sample(atlas, key, ch):
    samples = atlas.get(key, {}).get(ch)
    if not samples:
        return None
    with_adv = [s for s in samples if s["adv"] and s["adv"] > 0]
    return (with_adv or samples)[0]


def _crop_glyph_tight(img, zoom, bbox, bg_rgb, pad_pt=0.15, thresh=18):
    x0, y0, x1, y1 = bbox
    x0 -= pad_pt; y0 -= pad_pt; x1 += pad_pt; y1 += pad_pt
    box = (int(x0 * zoom), int(y0 * zoom), math.ceil(x1 * zoom), math.ceil(y1 * zoom))
    crop = img.crop(box)
    px = crop.load()
    w, h = crop.size

    def is_bg(p):
        return (abs(p[0] - bg_rgb[0]) < thresh and
                abs(p[1] - bg_rgb[1]) < thresh and
                abs(p[2] - bg_rgb[2]) < thresh)

    def col_is_bg(x):
        return all(is_bg(px[x, y]) for y in range(h))

    def row_is_bg(y):
        return all(is_bg(px[x, y]) for x in range(w))

    left, right, top, bottom = 0, w, 0, h
    while left < right - 1 and col_is_bg(left):
        left += 1
    while right > left + 1 and col_is_bg(right - 1):
        right -= 1
    while top < bottom - 1 and row_is_bg(top):
        top += 1
    while bottom > top + 1 and row_is_bg(bottom - 1):
        bottom -= 1

    trimmed = crop.crop((left, top, right, bottom))
    tx0 = x0 + left / zoom
    ty0 = y0 + top / zoom
    tx1 = x0 + right / zoom
    ty1 = y0 + bottom / zoom
    return trimmed, (tx0, ty0, tx1, ty1)


def apply_prices_by_locator(pdf_bytes, edits):
    """
    Forma robusta (recomendada) de reescribir precios: cada edit ya trae
    la posición exacta del precio (guardada en Firestore cuando se
    confirmó la carta la primera vez), en vez de tener que re-adivinar
    a qué ítem corresponde cada texto.

    edits: lista de dicts:
        {"page": 0, "bbox": [x0,y0,x1,y1], "font": "...", "size": 13.1, "new_price": 41000}
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    by_page = {}
    for e in edits:
        by_page.setdefault(e["page"], []).append(e)

    for page_index, page_edits in by_page.items():
        page = doc[page_index]
        src_img, zoom, atlas = _build_glyph_atlas(page, dpi=600)
        pix_bg = page.get_pixmap()
        bg = pix_bg.pixel(5, 5)
        bg_color = tuple(c / 255 for c in bg[:3])

        for e in page_edits:
            key = (e["font"], round(e["size"], 1))
            new_text = f"${int(e['new_price'])}"
            bbox = fitz.Rect(*e["bbox"])

            total_w = 0
            glyphs_to_draw = []
            for ch in new_text:
                sample = _pick_sample(atlas, key, ch)
                if not sample:
                    continue
                gb = sample["bbox"]
                adv = sample["adv"] or (gb[2] - gb[0]) * 1.15
                glyphs_to_draw.append((ch, sample, adv))
                total_w += adv

            cover_w = max(bbox.width, total_w) + 2
            cover = fitz.Rect(bbox.x0 - 1, bbox.y0 - 0.3, bbox.x0 + cover_w, bbox.y1 + 0.3)
            page.draw_rect(cover, color=None, fill=bg_color, overlay=True)

            cur_x = bbox.x0
            y0 = bbox.y0
            for ch, sample, adv in glyphs_to_draw:
                trimmed_img, (tx0, ty0, tx1, ty1) = _crop_glyph_tight(src_img, zoom, sample["bbox"], bg)
                if trimmed_img.size[0] == 0 or trimmed_img.size[1] == 0:
                    cur_x += adv
                    continue
                buf = io.BytesIO()
                trimmed_img.save(buf, format="PNG")
                gb = sample["bbox"]
                y_shift = ty0 - gb[1]
                rect = fitz.Rect(cur_x, y0 + y_shift, cur_x + (tx1 - tx0), y0 + y_shift + (ty1 - ty0))
                page.insert_image(rect, stream=buf.getvalue())
                cur_x += adv

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def apply_prices_to_carta(pdf_bytes, price_map):
    """
    price_map: dict {"NOMBRE DEL ÍTEM (tal cual aparece en el PDF, en mayúsculas)": nuevo_precio_int}
    Devuelve los bytes del PDF nuevo con los precios reemplazados.
    Los ítems cuyo nombre no aparezca en price_map quedan sin tocar.
    Los campos con fuente en EXCLUDED_FONTS (cubierto) nunca se tocan.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    not_found = set(price_map.keys())

    for page in doc:
        src_img, zoom, atlas = _build_glyph_atlas(page, dpi=600)
        raw = page.get_text("rawdict")

        pix_bg = page.get_pixmap()
        bg = pix_bg.pixel(5, 5)
        bg_color = tuple(c / 255 for c in bg[:3])

        edits = []
        for block in raw["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["font"] in EXCLUDED_FONTS:
                        continue
                    chars = span.get("chars", [])
                    text = "".join(c["c"] for c in chars)
                    for m in PRICE_RE.finditer(text):
                        name_guess = (text[:m.start()] + text[m.end():]).strip(" -·").upper()
                        matched_key = None
                        for k in price_map:
                            if k.upper() in name_guess or name_guess in k.upper():
                                matched_key = k
                                break
                        if matched_key is None:
                            continue
                        not_found.discard(matched_key)

                        start, end = m.span()
                        match_chars = chars[start:end]
                        x0 = min(c["bbox"][0] for c in match_chars)
                        y0 = min(c["bbox"][1] for c in match_chars)
                        x1 = max(c["bbox"][2] for c in match_chars)
                        y1 = max(c["bbox"][3] for c in match_chars)
                        new_num = int(price_map[matched_key])
                        edits.append({
                            "bbox": fitz.Rect(x0, y0, x1, y1),
                            "new_text": f"${new_num}",
                            "key": (span["font"], round(span["size"], 1)),
                        })

        for e in edits:
            key = e["key"]
            total_w = 0
            glyphs_to_draw = []
            for ch in e["new_text"]:
                sample = _pick_sample(atlas, key, ch)
                if not sample:
                    continue
                gb = sample["bbox"]
                adv = sample["adv"] or (gb[2] - gb[0]) * 1.15
                glyphs_to_draw.append((ch, sample, adv))
                total_w += adv

            cover_w = max(e["bbox"].width, total_w) + 2
            cover = fitz.Rect(e["bbox"].x0 - 1, e["bbox"].y0 - 0.3,
                               e["bbox"].x0 + cover_w, e["bbox"].y1 + 0.3)
            page.draw_rect(cover, color=None, fill=bg_color, overlay=True)

            cur_x = e["bbox"].x0
            y0 = e["bbox"].y0
            for ch, sample, adv in glyphs_to_draw:
                trimmed_img, (tx0, ty0, tx1, ty1) = _crop_glyph_tight(
                    src_img, zoom, sample["bbox"], bg
                )
                if trimmed_img.size[0] == 0 or trimmed_img.size[1] == 0:
                    cur_x += adv
                    continue
                buf = io.BytesIO()
                trimmed_img.save(buf, format="PNG")
                gb = sample["bbox"]
                y_shift = ty0 - gb[1]
                rect = fitz.Rect(cur_x, y0 + y_shift,
                                  cur_x + (tx1 - tx0), y0 + y_shift + (ty1 - ty0))
                page.insert_image(rect, stream=buf.getvalue())
                cur_x += adv

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), sorted(not_found)
