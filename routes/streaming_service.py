"""
Blueprint Streaming Service — Sert les fichiers audio/PDF de façon sécurisée.

GET  /api/stream/tracks/<track_id>/preview           → Preview watermarquée (public, rate-limité)
GET  /api/stream/tracks/<track_id>/download/<format> → Fichier acheté MP3/WAV/Stems (JWT + achat vérifié)
GET  /api/stream/toplines/<topline_id>               → Audio topline (publié = public, non publié = propriétaire)
GET  /api/stream/contracts/<purchase_id>             → PDF contrat (JWT + acheteur ou compositeur)
"""
from flask import Blueprint, current_app, send_file, abort, make_response
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity, jwt_required
from flask_jwt_extended.exceptions import JWTExtendedException
from pathlib import Path
from sqlalchemy import select

from extensions import db, limiter
from models import Track, Topline, Purchase, User
from serializers import err
from utils.auth_helpers import require_user


streaming_bp = Blueprint('streaming', __name__, url_prefix='/api/stream')


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
    Sert un fichier depuis db_assets/ après vérification sécurité (path traversal).

    En production (USE_X_ACCEL_REDIRECT=true), retourne un header X-Accel-Redirect
    pour que nginx serve le fichier directement — le worker Gunicorn est libéré
    immédiatement au lieu de bloquer pendant toute la durée du stream.

    En dev (défaut), utilise send_file() avec conditional=True (Range requests,
    seek WaveSurfer).
    """
    db_assets_root = (Path(current_app.root_path) / 'db_assets').resolve()
    path = (Path(current_app.root_path) / relative_path).resolve()

    if not path.is_relative_to(db_assets_root):
        current_app.logger.warning(
            "[SECURITY] Path traversal bloqué — relative_path=%r résolu en %s",
            relative_path, path,
        )
        abort(403)

    if not path.exists():
        abort(404)

    if current_app.config.get('USE_X_ACCEL_REDIRECT'):
        # Chemin interne nginx : /_protected/<chemin relatif depuis db_assets/>
        accel_path = '/_protected/' + path.relative_to(db_assets_root).as_posix()
        response = make_response()
        response.headers['X-Accel-Redirect'] = accel_path
        response.headers['Content-Type'] = mimetype
        if as_attachment and download_name:
            safe_name = download_name.encode('utf-8').decode('latin-1', errors='replace')
            response.headers['Content-Disposition'] = (
                f"attachment; filename*=UTF-8''{download_name}"
            )
        return response

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

    try:
        return _send(f'db_assets/audio/{track.audio_file}', 'audio/mpeg')
    except FileNotFoundError:
        current_app.logger.error(f"Fichier de preview introuvable pour track {track_id}", exc_info=True)
        abort(404)


# ── 2. Stream MP3 complet (authentifié, rate-limité, pas d'attachment) ──────────

@streaming_bp.route('/tracks/<int:track_id>/full', methods=['GET'])
@limiter.limit('60 per minute')
@jwt_required()
@require_user
def stream_track_full(track_id, current_user):
    """
    Sert le MP3 complet d'un track approuvé en streaming pur (sans attachment).
    Requiert un compte — évite l'accès anonyme au fichier payant identique à /download/mp3.
    Le téléchargement avec contrat reste réservé à /download/<format> (achat vérifié).
    """
    track = db.session.get(Track, track_id)
    if not track or not track.is_approved:
        abort(404)
    if not track.file_mp3:
        abort(404)

    return _send(f'db_assets/audio/{track.file_mp3}', 'audio/mpeg')


# ── 3. Download fichier acheté (MP3 / WAV / Stems) ────────────────────────────

@streaming_bp.route('/tracks/<int:track_id>/download/<format>', methods=['GET'])
@jwt_required()
@require_user
def download_track_file(track_id, format, current_user):
    """
    Télécharge le fichier complet après vérification de l'achat.
    format : 'mp3' | 'wav' | 'stems'
    """
    if format not in _FORMAT_FIELD:
        return err(f"Format invalide : {format}")

    track = db.session.get(Track, track_id)
    if not track:
        abort(404)

    # Le compositeur peut télécharger ses propres fichiers sans achat
    is_composer = (track.composer_id == current_user.id)

    if not is_composer:
        purchase = db.session.execute(
            select(Purchase).where(
                Purchase.track_id         == track_id,
                Purchase.buyer_id         == current_user.id,
                Purchase.format_purchased == format,
            )
        ).scalar_one_or_none()

        if not purchase:
            return err("Accès non autorisé. Achetez ce fichier d'abord.", status=403)

    file_path = getattr(track, _FORMAT_FIELD[format])
    if not file_path:
        return err('Fichier non disponible.', level='warning', status=404)

    ext = 'zip' if format == 'stems' else format
    download_name = f"{_safe_filename(track.title)}.{ext}"

    return _send(f'db_assets/audio/{file_path}', _FORMAT_MIME[format], as_attachment=True, download_name=download_name)


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
            current_user    = db.session.get(User, current_user_id)
        except (JWTExtendedException, ValueError, TypeError):
            abort(403)
        is_owner = topline.artist_id == current_user_id
        is_admin = current_user and getattr(current_user, 'is_admin', False)
        if not is_owner and not is_admin:
            abort(403)

    if not topline.audio_file:
        abort(404)

    mime = 'audio/wav' if topline.audio_file.endswith('.wav') else 'audio/mpeg'
    return _send(f'db_assets/{topline.audio_file}', mime)


# ── 4. Télécharger contrat PDF ────────────────────────────────────────────────

@streaming_bp.route('/contracts/<int:purchase_id>', methods=['GET'])
@jwt_required()
@require_user
def download_contract(purchase_id, current_user):
    """
    Télécharge le PDF du contrat lié à un achat.
    Accessible uniquement par l'acheteur ou le compositeur.
    """
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        abort(404)

    track = db.session.get(Track, purchase.track_id)
    if not track:
        abort(404)

    if purchase.buyer_id != current_user.id and track.composer_id != current_user.id:
        abort(403)

    if not purchase.contract_file:
        return err('Contrat non encore généré.', level='warning', status=404)

    download_name = f"contrat_{_safe_filename(track.title)}_{purchase.format_purchased}.pdf"

    return _send(f'db_assets/contracts/{purchase.contract_file}', 'application/pdf', as_attachment=True, download_name=download_name)
