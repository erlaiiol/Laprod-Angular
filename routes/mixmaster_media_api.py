"""
Mixmaster Media API — Accès protégé aux fichiers audio et archives des commandes.

Seuls l'artiste et l'engineer de la commande peuvent accéder aux fichiers.
Les fichiers ne sont pas servis via /static/ (accès public) mais via cet endpoint
qui vérifie le JWT et l'appartenance avant de renvoyer le fichier.
"""
from flask import Blueprint, jsonify, current_app, abort, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db, csrf
from models import MixMasterRequest
from pathlib import Path

mixmaster_media_api_bp = Blueprint(
    'mixmaster_media_api', __name__, url_prefix='/api/mixmaster-media'
)

ALLOWED_TYPES = {
    'reference':    'reference_file',
    'original':     'original_file',
    'preview':      'processed_file_preview',
    'preview_full': 'processed_file_preview_full',
}


@mixmaster_media_api_bp.route('/<int:order_id>/<string:media_type>', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_media(order_id: int, media_type: str):
    """
    Sert le fichier audio/archive d'une commande de mixage.
    Accessible uniquement à l'artiste ou à l'engineer de la commande.

    media_type : 'reference' | 'original'
    """
    if media_type not in ALLOWED_TYPES:
        return jsonify({'success': False, 'feedback': {
            'level': 'error', 'message': 'Type de média invalide.'
        }}), 400

    user_id = int(get_jwt_identity())

    order = db.session.get(MixMasterRequest, order_id)
    if not order:
        abort(404)

    # Vérification appartenance : artiste OU engineer de la commande
    if order.artist_id != user_id and order.engineer_id != user_id:
        return jsonify({'success': False, 'feedback': {
            'level': 'error', 'message': 'Accès refusé.'
        }}), 403

    field_name = ALLOWED_TYPES[media_type]
    relative_path = getattr(order, field_name, None)

    if not relative_path:
        return jsonify({'success': False, 'feedback': {
            'level': 'error', 'message': 'Fichier non disponible.'
        }}), 404

    # Le chemin en DB est relatif à la racine Flask (ex: static/mixmaster/uploads/...)
    file_path = Path(current_app.root_path) / relative_path

    if not file_path.exists():
        current_app.logger.warning(
            f'Fichier manquant order #{order_id} {media_type}: {file_path}'
        )
        return jsonify({'success': False, 'feedback': {
            'level': 'error', 'message': 'Fichier introuvable sur le serveur.'
        }}), 404

    is_attachment = media_type == 'original'
    return send_file(
        file_path,
        as_attachment=is_attachment,
        download_name=file_path.name if is_attachment else None,
    )
