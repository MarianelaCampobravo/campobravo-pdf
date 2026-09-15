"""
carta_routes.py
----------------
Endpoints nuevos para la Carta Digital. Pensados para Flask, igual que
/generate-pdf ya existente en server.py.
"""

import io
import os
import base64
import requests
from flask import request, jsonify, send_file

from carta_engine import extract_carta_items, apply_prices_by_locator



GITHUB_OWNER = "MarianelaCampobravo"
GITHUB_REPO = "campobravo-pdf"
GITHUB_BRANCH = "main"
CARTA_BASE_PATH = "carta_base/base.pdf"


def _github_headers():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN no configurado")
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def upload_pdf_to_github(pdf_bytes):
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{CARTA_BASE_PATH}"
    headers = _github_headers()
    resp = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=20)
    sha = resp.json().get("sha") if resp.status_code == 200 else None

    payload = {
        "message": "Actualizar carta base",
        "content": base64.b64encode(pdf_bytes).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    put_resp = requests.put(api_url, headers=headers, json=payload, timeout=30)
    if put_resp.status_code not in (200, 201):
        raise RuntimeError(f"GitHub API error {put_resp.status_code}: {put_resp.text}")

    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{CARTA_BASE_PATH}"


def register_carta_routes(app):

    @app.route("/carta/extract", methods=["POST"])
    def carta_extract():
        if "file" not in request.files:
            return jsonify({"error": "falta el archivo 'file'"}), 400
        pdf_bytes = request.files["file"].read()
        try:
            result = extract_carta_items(pdf_bytes)
        except Exception as ex:
            return jsonify({"error": f"no se pudo leer el PDF: {ex}"}), 400
        return jsonify(result)

    @app.route("/carta/generate", methods=["POST"])
    def carta_generate():
        data = request.get_json(force=True)
        pdf_url = data.get("pdf_url")
        edits = data.get("edits", [])
        if not pdf_url:
            return jsonify({"error": "falta 'pdf_url'"}), 400
        if not edits:
            return jsonify({"error": "no llegaron precios para aplicar ('edits' vacío)"}), 400

        resp = requests.get(pdf_url, timeout=20)
        if resp.status_code != 200:
            return jsonify({"error": f"no se pudo descargar el PDF base ({resp.status_code})"}), 400

        try:
            new_pdf_bytes = apply_prices_by_locator(resp.content, edits)
        except Exception as ex:
            return jsonify({"error": f"error generando el PDF: {ex}"}), 500

        return send_file(
            io.BytesIO(new_pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="carta_actualizada.pdf",
        )


    @app.route("/carta/upload-base", methods=["POST"])
    def carta_upload_base():
        if "file" not in request.files:
            return jsonify({"error": "falta el archivo 'file'"}), 400
        pdf_bytes = request.files["file"].read()
        try:
            raw_url = upload_pdf_to_github(pdf_bytes)
        except Exception as ex:
            return jsonify({"error": f"no se pudo subir el PDF a GitHub: {ex}"}), 500
        return jsonify({"pdf_url": raw_url})
