from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import redis_client, csrf

job_status_api = Blueprint('job_status_api', __name__, url_prefix='/api/job_status')

@job_status_api.route('/<job_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_job_status(job_id):
    """
    Endpoint pour récupérer le statut d'un job de processing de track.
    Le job_id est généré lors de la soumission du track et stocké dans Redis.
    
    Retourne un JSON avec le statut actuel du job (en file d'attente, en cours, terminé, ou erreur).
    """

    job_key = f"job:{job_id}"
    if not redis_client.exists(job_key):
        return jsonify({'error': 'Job not found'}), 404
    
    job_data = redis_client.hgetall(job_key)
    # Convertir les bytes en str
    
    if job_data.get('user_id') != str(get_jwt_identity()):
        return jsonify({'error' : 'Forbidden'}), 403

    return jsonify({
        'success': True,
        'data': {
            'status':        job_data.get('status', 'unknown'),
            'track_id':      job_data.get('track_id') or None,
            'error_message': job_data.get('error_message') or None,
        }
    })