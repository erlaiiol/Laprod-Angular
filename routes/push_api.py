"""
Blueprint PUSH API — jetons d'appareil et préférence de notifications push (mobile natif).

  POST /api/push/register     → enregistre/réactive le jeton FCM de l'appareil courant
  POST /api/push/unregister   → désactive un jeton (logout, désactivation du réglage)
  GET  /api/push/preference   → mon consentement push
  PUT  /api/push/preference   → l'activer / le retirer

Voir docs/roadmap.md § Chantier 2 pour la spécification complète.
"""
from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from extensions import db, csrf
from serializers import ok, err
from utils.auth_helpers import require_user
from utils.crud_helpers import commit_or_rollback, handle_route_exceptions
from utils import push_service

push_api_bp = Blueprint('push_api', __name__, url_prefix='/api/push')

_ALLOWED_PLATFORMS = {'android', 'ios'}


@push_api_bp.route('/register', methods=['POST'])
@csrf.exempt
@jwt_required()
@handle_route_exceptions
@require_user
@commit_or_rollback
def register(current_user):
    data     = request.get_json() or {}
    token    = (data.get('token') or '').strip()
    platform = (data.get('platform') or '').strip().lower()

    if not token or platform not in _ALLOWED_PLATFORMS:
        return err('Jeton ou plateforme invalide.', code='INVALID_DEVICE_TOKEN', status=400)

    push_service.register_token(current_user.id, token, platform)
    db.session.commit()

    return ok(message='Appareil enregistré.')


@push_api_bp.route('/unregister', methods=['POST'])
@csrf.exempt
@jwt_required()
@handle_route_exceptions
@require_user
@commit_or_rollback
def unregister(current_user):
    token = (request.get_json() or {}).get('token', '').strip()
    if not token:
        return err('Jeton manquant.', code='INVALID_DEVICE_TOKEN', status=400)

    push_service.deactivate_token(current_user.id, token)
    db.session.commit()

    return ok(message='Appareil désinscrit.')


@push_api_bp.route('/preference', methods=['GET'])
@jwt_required()
@require_user
def get_preference(current_user):
    return ok({'push_opt_in': current_user.push_opt_in})


@push_api_bp.route('/preference', methods=['PUT'])
@csrf.exempt
@jwt_required()
@handle_route_exceptions
@require_user
@commit_or_rollback
def set_preference(current_user):
    """Active ou retire le consentement. L'horodatage est la preuve du
    consentement — il n'est posé qu'à l'activation, jamais reconstitué
    (même règle que campaign_api.py::set_marketing_preferences).

    Le retrait désactive aussi tous les jetons de l'utilisateur : un push ne
    doit plus jamais être tenté vers cet utilisateur tant qu'il ne réactive
    pas explicitement le réglage, même si un jeton restait techniquement valide.
    """
    enabled = bool((request.get_json() or {}).get('enabled', False))

    current_user.push_opt_in    = enabled
    current_user.push_opt_in_at = datetime.now() if enabled else None
    if not enabled:
        push_service.deactivate_all_tokens(current_user.id)
    db.session.commit()

    return ok(
        {'push_opt_in': enabled},
        message='Notifications push activées.' if enabled else 'Notifications push désactivées.',
    )
