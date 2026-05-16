from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import csrf
from utils.contract_analyzer import analyze_contract

contract_analyzer_api_bp = Blueprint(
    'contract_analyzer_api', __name__, url_prefix='/api/contract-analyzer'
)

MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 Mo


@contract_analyzer_api_bp.route('/analyze', methods=['POST'])
@jwt_required()
@csrf.exempt
def analyze():
    if 'contract_pdf' not in request.files:
        return jsonify(success=False, feedback={'level': 'error', 'message': 'Aucun fichier reçu.'}), 400

    f = request.files['contract_pdf']

    if not f.filename or not f.filename.lower().endswith('.pdf'):
        return jsonify(success=False, feedback={'level': 'error', 'message': 'Le fichier doit être un PDF.'}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_PDF_BYTES:
        return jsonify(success=False, feedback={'level': 'error', 'message': 'Fichier trop volumineux (max 10 Mo).'}), 400

    try:
        analysis = analyze_contract(file_bytes)
    except ValueError as exc:
        return jsonify(success=False, feedback={'level': 'error', 'message': str(exc)}), 400
    except EnvironmentError as exc:
        return jsonify(success=False, feedback={'level': 'error', 'message': str(exc)}), 503
    except Exception as exc:
        return jsonify(success=False, feedback={'level': 'error', 'message': f'Erreur lors de l\'analyse : {exc}'}), 500

    return jsonify(success=True, data={'analysis': analysis})
