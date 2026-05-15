from flask import Blueprint
from flask_jwt_extended import jwt_required
from extensions import redis_client, csrf
from serializers import ok, err
from utils.auth_helpers import require_user

job_status_api = Blueprint('job_status_api', __name__, url_prefix='/api/job_status')

@job_status_api.route('/<job_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_job_status(job_id, current_user):
    """
    Endpoint pour récupérer le statut d'un job de processing de track.
    Le job_id est généré lors de la soumission du track et stocké dans Redis.

    Retourne un JSON avec le statut actuel du job (en file d'attente, en cours, terminé, ou erreur).
    """
    job_key = f"job:{job_id}"
    if not redis_client.exists(job_key):
        return err('Job not found', status=404)

    job_data = redis_client.hgetall(job_key)

    if job_data.get('user_id') != str(current_user.id):
        return err('Forbidden', status=403)

    return ok({
        'status':        job_data.get('status', 'unknown'),
        'track_id':      job_data.get('track_id') or None,
        'topline_id':    job_data.get('topline_id') or None,
        'error_message': job_data.get('error_message') or None,
    })
