"""
Blueprint Streaming Service — Sert les fichiers audio/PDF de façon sécurisée.

GET  /stream/tracks/<track_id>/preview           → Preview watermarquée (public, rate-limité)
GET  /stream/tracks/<track_id>/download/<format> → Fichier acheté MP3/WAV/Stems (JWT + achat vérifié)
GET  /stream/toplines/<topline_id>               → Audio topline (publié = public, non publié = propriétaire)
GET  /stream/contracts/<purchase_id>             → PDF contrat (JWT + acheteur ou compositeur)
"""
from flask import Blueprint, current_app, send_file, jsonify, abort
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity, jwt_required
from pathlib import Path
from sqlalchemy import select

from extensions import db, limiter
from models import Track, Topline, Purchase


streaming_bp = Blueprint('streaming', __name__, url_prefix='/stream')


# ── Formats acceptés ──────────────────────────────────────────────────────────

_FORMAT_FIELD = {
    'mp3':   'file_mp3',
    'wav':   'file_wav',
    'stems': 'file_stems',
}

_FORMAT_MIME = {
    'mp3':   'audio/mpeg',
    'wav':   'audio/wav',
    'stems': 'application/zip',
}


# ── Helper interne ────────────────────────────────────────────────────────────

def _send(relative_path: str, mimetype: str,
          as_attachment: bool = False, download_name: str | None = None):
    """
    Résout le chemin relatif depuis la racine Flask et sert le fichier.
    conditional=True active le support Range (seek WaveSurfer / lecture partielle).
    """
    path = Path(current_app.root_path) / relative_path
    if not path.exists():
        abort(404)
    return send_file(
        path,
        mimetype=mimetype,
        conditional=True,
        as_attachment=as_attachment,
        download_name=download_name,
    )


def _safe_filename(name: str) -> str:
    """Supprime les caractères dangereux pour un nom de fichier."""
    return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()


# ── 1. Preview track (public, rate-limité) ────────────────────────────────────

@streaming_bp.route('/tracks/<int:track_id>/preview', methods=['GET'])
@limiter.limit('120 per minute')
def stream_track_preview(track_id):
    """
    Sert la preview watermarquée d'un track approuvé.
    Aucune authentification requise — fichier déjà watermarqué côté upload.
    """
    track = db.session.get(Track, track_id)
    if not track or not track.is_approved:
        abort(404)
    if not track.audio_file:
        abort(404)
    return _send(track.audio_file, 'audio/mpeg')


# ── 2. Download fichier acheté (MP3 / WAV / Stems) ────────────────────────────

@streaming_bp.route('/tracks/<int:track_id>/download/<format>', methods=['GET'])
@jwt_required()
def download_track_file(track_id, format):
    """
    Télécharge le fichier complet après vérification de l'achat.
    format : 'mp3' | 'wav' | 'stems'
    """
    if format not in _FORMAT_FIELD:
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': f"Format invalide : {format}"}
        }), 400

    user_id = int(get_jwt_identity())

    track = db.session.get(Track, track_id)
    if not track:
        abort(404)

    # Le compositeur peut télécharger ses propres fichiers sans achat
    is_composer = (track.composer_id == user_id)

    if not is_composer:
        purchase = db.session.execute(
            select(Purchase).where(
                Purchase.track_id         == track_id,
                Purchase.buyer_id         == user_id,
                Purchase.format_purchased == format,
            )
        ).scalar_one_or_none()

        if not purchase:
            return jsonify({
                'success': False,
                'feedback': {
                    'level': 'error',
                    'message': "Accès non autorisé. Achetez ce fichier d'abord."
                }
            }), 403

    file_path = getattr(track, _FORMAT_FIELD[format])
    if not file_path:
        return jsonify({
            'success': False,
            'feedback': {'level': 'warning', 'message': 'Fichier non disponible.'}
        }), 404

    ext = 'zip' if format == 'stems' else format
    download_name = f"{_safe_filename(track.title)}.{ext}"

    return _send(file_path, _FORMAT_MIME[format], as_attachment=True, download_name=download_name)


# ── 3. Stream topline ─────────────────────────────────────────────────────────

@streaming_bp.route('/toplines/<int:topline_id>', methods=['GET'])
def stream_topline(topline_id):
    """
    Sert l'audio d'une topline.
    - Publiée  → public
    - Non publiée → propriétaire uniquement (JWT requis)
    """
    topline = db.session.get(Topline, topline_id)
    if not topline:
        abort(404)

    if not topline.is_published:
        try:
            verify_jwt_in_request()
            current_user_id = int(get_jwt_identity())
        except Exception:
            abort(403)
        if topline.artist_id != current_user_id:
            abort(403)

    if not topline.audio_file:
        abort(404)

    return _send(topline.audio_file, 'audio/mpeg')


# ── 4. Télécharger contrat PDF ────────────────────────────────────────────────

@streaming_bp.route('/contracts/<int:purchase_id>', methods=['GET'])
@jwt_required()
def download_contract(purchase_id):
    """
    Télécharge le PDF du contrat lié à un achat.
    Accessible uniquement par l'acheteur ou le compositeur.
    """
    user_id = int(get_jwt_identity())

    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        abort(404)

    track = db.session.get(Track, purchase.track_id)
    if not track:
        abort(404)

    if purchase.buyer_id != user_id and track.composer_id != user_id:
        abort(403)

    if not purchase.contract_file:
        return jsonify({
            'success': False,
            'feedback': {'level': 'warning', 'message': 'Contrat non encore généré.'}
        }), 404

    download_name = f"contrat_{_safe_filename(track.title)}_{purchase.format_purchased}.pdf"

    return _send(purchase.contract_file, 'application/pdf', as_attachment=True, download_name=download_name)
