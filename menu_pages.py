"""
menu_pages.py — Páginas de menú del PDF de eventos (Campobravo)

Dibuja cada página de menú sobre su imagen base (assets/*.png, sin platos)
y escribe encima los platos y el precio que manda la app.

Uso desde generate_pdf.py:
    from menu_pages import draw_menu_page
    draw_menu_page(c, W, H, "campobravo", textos_dict, precio)
"""
import os
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import simpleSplit

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

pdfmetrics.registerFont(TTFont("FunnelSans", os.path.join(ASSETS, "FunnelSans-Regular.ttf")))

BLANCO = colors.HexColor("#EEEEEE")     # mismo blanco que "1 Agua o Gaseosa"
DORADO = colors.HexColor("#E8BF72")     # mismo dorado que el precio del diseño
FUENTE_PLATO  = "FunnelSans"
FUENTE_PRECIO = "PlayfairBold"          # ya registrada en generate_pdf.py
TAM_MAX, TAM_MIN = 21, 12               # la letra se achica si el texto no entra
INTERLINEA = 1.3
ANCHO_MAX = 520                          # ancho útil dentro del marco

# Posiciones medidas sobre el diseño, en unidades de la página (794 x 1123),
# contadas desde ARRIBA: (inicio, fin) del espacio vacío debajo de cada título.
LAYOUT = {
    "campobravo": {
        "imagen": "menu_campobravo.png",
        "huecos": {
            "entrada":      (305, 437),
            "principales":  (461, 528),
            "guarniciones": (548, 621),
            "postre":       (639, 785),
        },
        "precio": 928,
    },
    "bravisimo": {
        "imagen": "menu_bravisimo.png",
        "huecos": {
            "entrada":     (376, 444),
            "principales": (468, 689),
            "postre":      (707, 780),
        },
        "precio": 860,
    },
    "infantil": {
        "imagen": "menu_infantil.png",
        "huecos": {
            "principal": (497, 565),
            "postre":    (584, 657),
        },
        "precio": 737,
    },
    "personalizado": {
        "imagen": "menu_personalizado.png",
        "huecos": {
            "entrada":   (389, 460),
            "principal": (485, 705),
            "postre":    (724, 827),
            "bebida":    (856, 912),   # debajo de "1 Agua o Gaseosa"
        },
        "precio": 950,
    },
}

# Contenido por defecto (solo se usa si la app no manda nada)
DEFAULTS = {
    "campobravo": {
        "entrada": "Provoleta Bravísima o Chorizo y Morcilla",
        "principales": "Ojo de Bife o Bife de Chorizo",
        "guarniciones": "",
        "postre": "Marquise de Chocolate",
    },
    "bravisimo": {
        "entrada": "Empanada",
        "principales": "Lomo Grillado o Risotto de Langostinos",
        "postre": "Flan Casero",
    },
    "infantil": {
        "principal": "Milanesa con Puré o Papas Fritas",
        "postre": "Flan Casero",
    },
    "personalizado": {"entrada": "", "principal": "", "postre": "", "bebida": ""},
}


def _fmt(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _ajustar(texto, alto_disponible):
    """Devuelve (lineas, tamaño) para que el texto entre en el hueco."""
    renglones = [r.strip() for r in str(texto or "").splitlines() if r.strip()]
    if not renglones:
        return [], TAM_MAX
    tam = TAM_MAX
    while True:
        lineas = []
        for r in renglones:
            lineas += simpleSplit(r, FUENTE_PLATO, tam, ANCHO_MAX)
        if len(lineas) * tam * INTERLINEA <= alto_disponible or tam <= TAM_MIN:
            return lineas, tam
        tam -= 1


def _escribir_hueco(c, H, texto, hueco, W):
    arriba, abajo = hueco
    alto = (abajo - arriba) - 12          # margen para no pegarse a los títulos
    lineas, tam = _ajustar(texto, alto)
    if not lineas:
        return
    paso = tam * INTERLINEA
    alto_bloque = len(lineas) * paso
    centro = (arriba + abajo) / 2
    y = centro - alto_bloque / 2 + tam * 0.95   # primera línea base (desde arriba)
    c.setFont(FUENTE_PLATO, tam)
    c.setFillColor(BLANCO)
    for linea in lineas:
        c.drawCentredString(W / 2, H - y, linea)
        y += paso


def draw_menu_page(c, W, H, menu, textos=None, precio=None):
    cfg = LAYOUT[menu]
    textos = {**DEFAULTS[menu], **(textos or {})}
    c.drawImage(os.path.join(ASSETS, cfg["imagen"]), 0, 0, W, H)
    for clave, hueco in cfg["huecos"].items():
        _escribir_hueco(c, H, textos.get(clave, ""), hueco, W)
    if precio:
        c.setFont(FUENTE_PRECIO, 28)
        c.setFillColor(DORADO)
        c.drawCentredString(W / 2, H - cfg["precio"], f"Precio por Persona: {_fmt(precio)}")
