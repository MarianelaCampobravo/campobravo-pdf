"""
carta_routes.py
----------------
Endpoints nuevos para la Carta Digital. Pensados para Flask, igual que
/generate-pdf ya existente en server.py.
"""

import io
import requests
from flask import request, jsonify, send_file

from carta_engine import extract_carta_items, apply_prices_by_locator


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
