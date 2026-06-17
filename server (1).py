from flask import Flask, request, jsonify
from flask_cors import CORS
import base64, os, sys

app = Flask(__name__)
CORS(app)

sys.path.insert(0, os.path.dirname(__file__))

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.get_json()
        from generate_pdf import make_pdf
        pdf_bytes = make_pdf(data)
        b64 = base64.b64encode(pdf_bytes).decode()
        return jsonify({'pdf': b64})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/', methods=['GET'])
def index():
    return jsonify({'status': 'Campobravo PDF Server running'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
