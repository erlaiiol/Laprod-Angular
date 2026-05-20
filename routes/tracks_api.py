"""
Blueprint TRACKS API — GET + CUD endpoints

GET    /api/tracks/track/<track_id>  → détail d'un track (JWT optionnel)
GET    /api/tracks/tracks            → liste paginée avec filtres (JWT optionnel)
GET    /api/tracks/random            → track aléatoire approuvé (public)
POST   /api/tracks/post              → Upload beat + traitement async (jwt_required)
PUT    /api/tracks/put/<track_id>    → Modifier un track (propriétaire)
DELETE /api/tracks/delete/<track_id> → Supprimer un track (propriétaire)
"""
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, verify_jwt_in_request, get_jwt_identity
from werkzeug.utils import secure_filename
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload
import shutil
import config
import uuid as _uuid

from extensions import db, limiter, csrf, redis_client
from models import Track, Tag, Category, User, Topline
from helpers import generate_track_image
from serializers import ok, err, track_card, track_detail, topline as ser_topline
from utils.auth_helpers import require_user
from utils.crud_helpers import (
    get_or_404, require_ownership,
    handle_route_exceptions, commit_or_rollback,
)

from rq import Queue

# Imports pour watermarking et validation
try:
    from utils.audio_processing import apply_watermark_and_trim, convert_to_mp3
    WATERMARK_AVAILABLE = True
except ImportError:
    WATERMARK_AVAILABLE = False

try:
    from utils.file_validator import validate_specific_audio_format, validate_stems_archive, validate_image_file, FileValidator
    VALIDATION_AVAILABLE = True
except ImportError as e:
    import logging
    logging.getLogger(__name__).critical(f'[tracks_api] file_validator indisponible — upload désactivé: {e}')
    VALIDATION_AVAILABLE = False

tracks_api_bp = Blueprint('tracks_api', __name__, url_prefix='/api/tracks')

_CONTRACT_PRICE_FIELDS = [
    'contract_price_exclusive',
    'contract_price_duration_3y',
    'contract_price_duration_5y',
    'contract_price_duration_10y',
    'contract_price_lifetime',
    'contract_price_mechanical',
    'contract_price_public_show',
    'contract_price_arrangement',
    'contract_price_territory_eu',
    'contract_price_territory_world',
]


def _resolve_contract_prices(track) -> dict:
    """Résout les prix de contrat : valeur track si définie, sinon défaut config."""
    cfg = current_app.config
    dur = cfg.get('CONTRACT_DURATIONS', {})

    def _r(attr, default):
        val = getattr(track, attr, None)
        return val if val is not None else default

    return {
        'exclusive':       _r('contract_price_exclusive',       cfg.get('CONTRACT_EXCLUSIVE_PRICE', 150)),
        'duration_3y':     _r('contract_price_duration_3y',     dur.get('3', 5)),
        'duration_5y':     _r('contract_price_duration_5y',     dur.get('5', 10)),
        'duration_10y':    _r('contract_price_duration_10y',    dur.get('10', 15)),
        'lifetime':        _r('contract_price_lifetime',        dur.get('lifetime', 50)),
        'mechanical':      _r('contract_price_mechanical',      cfg.get('CONTRACT_MECHANICAL_REPRODUCTION_PRICE', 30)),
        'public_show':     _r('contract_price_public_show',     cfg.get('CONTRACT_PUBLIC_SHOW_PRICE', 40)),
        'arrangement':     _r('contract_price_arrangement',     cfg.get('CONTRACT_ARRANGEMENT_PRICE', 10)),
        'territory_eu':    _r('contract_price_territory_eu',    cfg.get('CONTRACT_TERRITORY_EUROPE', 5)),
        'territory_world': _r('contract_price_territory_world', cfg.get('CONTRACT_TERRITORY_WORLD', 10)),
    }


# ── GET /tracks/track/<track_id> ──────────────────────────────────────────────

@tracks_api_bp.route('/track/<int:track_id>', methods=['GET'])
def get_track(track_id):
    """
    Récupérer les informations complètes d'un track (page track_detail).
    Inclut : composer_user, tags, toplines publiées + toplines de l'utilisateur connecté.
    """
    try:
        track = db.session.execute(
            select(Track)
            .options(
                selectinload(Track.tags).selectinload(Tag.category_obj),
                selectinload(Track.composer_user),
                selectinload(Track.toplines).selectinload(Topline.artist_user),
            )
            .where(Track.id == track_id)
        ).scalar_one_or_none()

        if not track:
            return err('Track introuvable', level='warning', status=404)

        # Identité JWT optionnelle (non bloquante)
        current_user_id = None
        try:
            verify_jwt_in_request(optional=True)
            raw = get_jwt_identity()
            current_user_id = int(raw) if raw else None
        except Exception:
            pass

        published_toplines = [tl for tl in track.toplines if tl.is_published]
        my_toplines = (
            [tl for tl in track.toplines if tl.artist_id == current_user_id]
            if current_user_id else []
        )

        track_data = track_detail(track)
        track_data['toplines']        = [ser_topline(tl) for tl in published_toplines]
        track_data['my_toplines']     = [ser_topline(tl) for tl in my_toplines]
        track_data['contract_prices'] = _resolve_contract_prices(track)

        return ok({'track': track_data})

    except Exception as e:
        current_app.logger.warning(f'erreur API get_track(): {e}')
        return err('Erreur lors de la récupération du track', status=500)


# ── GET /tracks/tracks ────────────────────────────────────────────────────────

@tracks_api_bp.route('/tracks', methods=['GET'])
def get_tracks():
    """
    Récupérer la liste des tracks avec filtres et pagination.
    Utilisé par le front Angular pour la page d'accueil.
    """
    page     = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 100)

    user_id  = None
    is_admin = False

    track_query = select(Track).options(selectinload(Track.tags), selectinload(Track.composer_user))

    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
        if user_id:
            user_id  = int(user_id)
            user     = db.session.get(User, user_id)
            is_admin = user.is_admin if user else False
    except Exception as e:
        current_app.logger.debug(f'pas de jwt valide pour get_tracks(): {e}')

    if not is_admin:
        track_query = track_query.where(
            Track.is_approved.is_(True),
            Track.is_exclusive_sold.is_(False),
        )

    try:
        search       = request.args.get('search', '').strip()[:50]
        bpm_min      = request.args.get('bpm_min', type=int)
        bpm_max      = request.args.get('bpm_max', type=int)
        keys_param   = request.args.get('keys', '').strip()
        styles_param = request.args.get('styles', '').strip()
        tags_param   = request.args.get('tags', '').strip()

        # Échapper les caractères spéciaux SQL LIKE
        search = search.replace('%', '\\%').replace('_', '\\_')

        if search:
            track_query = track_query.where(
                or_(
                    Track.title.ilike(f'%{search}%'),
                    Track.composer_user.has(User.username.ilike(f'%{search}%'))
                )
            )

        if bpm_min is not None:
            track_query = track_query.where(Track.bpm >= bpm_min)
        if bpm_max is not None:
            track_query = track_query.where(Track.bpm <= bpm_max)

        if keys_param:
            keys_list = [k.strip() for k in keys_param.split(',') if k.strip()]
            if keys_list:
                track_query = track_query.where(Track.key.in_(keys_list))

        if styles_param:
            styles_list = [s.strip() for s in styles_param.split(',') if s.strip()]
            if styles_list:
                track_query = track_query.where(Track.style.in_(styles_list))

        if tags_param:
            tags_list = [t.strip() for t in tags_param.split(',') if t.strip()]
            if tags_list:
                track_query = track_query.where(
                    Track.tags.any(Tag.name.in_(tags_list))
                )

        tracks = db.session.execute(
            track_query.order_by(Track.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).scalars().all()

        count_query = track_query.with_only_columns(func.count()).order_by(None)
        total = db.session.execute(count_query).scalar()

        return ok({
            'tracks': [track_card(t) for t in tracks],
            'pagination': {
                'page':     page,
                'per_page': per_page,
                'total':    total,
                'pages':    max(1, (total + per_page - 1) // per_page),
            },
        })

    except Exception as e:
        current_app.logger.warning(f'Erreur api get_tracks(): {e}')
        return err('Erreur lors de la récupération des tracks', status=500)


# ── GET /tracks/random ────────────────────────────────────────────────────────

@tracks_api_bp.route('/random', methods=['GET'])
def get_random_track():
    """
    Récupérer un track approuvé aléatoire (pour l'autoplay du player).
    Optionnel : exclude_id=<int> pour éviter de rejouer le track actuel.
    → GET /tracks/random?exclude_id=42
    """
    exclude_id = request.args.get('exclude_id', type=int)

    try:
        query = select(Track).options(
            selectinload(Track.tags), selectinload(Track.composer_user)
        ).where(Track.is_approved.is_(True))

        if exclude_id:
            query = query.where(Track.id != exclude_id)

        track = db.session.execute(
            query.order_by(func.random()).limit(1)
        ).scalar_one_or_none()

        if not track:
            return err('Aucun track disponible', level='info', status=404)

        return ok({'track': track_card(track)})

    except Exception as e:
        current_app.logger.warning(f'Erreur api get_random_track(): {e}')
        return err('Erreur lors de la récupération du track aléatoire', status=500)


# ── POST /tracks/post ─────────────────────────────────────────────────────────

@tracks_api_bp.route('/post', methods=['POST'])
@jwt_required()
@csrf.exempt
@limiter.limit("20 per hour")
@require_user
def post_track(current_user):
    """
    Upload beat + traitement audio async (RQ worker).

    FormData :
      - file_mp3   : fichier MP3 (obligatoire)
      - file_wav   : fichier WAV (optionnel)
      - file_image : image de couverture (optionnel)
      - file_stems : archive stems zip (optionnel, premium)
      - title, bpm, key, style, price_mp3, price_wav, price_stems
      - sacem_percentage_composer, tag_ids
    """
    can_upload, quota_message = current_user.can_upload_track()
    if not can_upload:
        current_app.logger.debug('post_track() l`utilisateur ne peut pas upload (manque de token ?)')
        return err('erreur : upload impossible(manque de token ?)', status=403)

    try:
        title   = request.form.get('title', '').strip()
        bpm_str = request.form.get('bpm', '').strip()
        key     = request.form.get('key', '').strip()
        style   = request.form.get('style', '').strip()

        if not title:
            return err('Le titre est obligatoire', level='warning')
        if not bpm_str:
            return err('Le BPM est obligatoire', level='warning')

        try:
            bpm = int(bpm_str)
            if bpm < 60 or bpm > 200:
                return err('le BPM doit être compris entre 60 et 200', level='warning')
        except ValueError:
            return err('le BPM doit être un nombre entier', level='warning')

        try:
            price_mp3   = float(request.form.get('price_mp3', 9.99))
            price_wav   = float(request.form.get('price_wav', 19.99))
            price_stems = float(request.form.get('price_stems', 49.99))
        except ValueError:
            return err('Prix invalides', level='warning')

        try:
            sacem_percentage_composer = int(request.form.get('sacem_percentage_composer', 50))
            if sacem_percentage_composer > 85 or sacem_percentage_composer < 0:
                return err('Le pourcentage SACEM doit être entre 0 et 85%', level='warning')
        except ValueError:
            return err('Pourcentage SACEM invalide', level='warning')

        file_mp3   = request.files.get('file_mp3')
        file_wav   = request.files.get('file_wav')
        file_image = request.files.get('file_image')
        file_stems = request.files.get('file_stems') if current_user.is_premium else None

        if not file_mp3 or file_mp3.filename == '':
            return err('Le fichier MP3 est obligatoire', level='warning')

        if not VALIDATION_AVAILABLE:
            return err('Service de validation non disponible', status=500)

        is_valid, error_message = validate_specific_audio_format(file_mp3, 'mp3')
        if not is_valid:
            return err(f'MP3 invalide: {error_message}', status=400)

        try:
            file_hash = Track.compute_file_hash(file_mp3)
            if Track.hash_exists(file_hash):
                return err('Ce beat a déjà été uploadé', status=409)
        except Exception as e:
            current_app.logger.error(f'Erreur vérification doublon: {e}')
            return err('Erreur de vérification du fichier', status=500)

        if file_wav and file_wav.filename != '':
            is_valid, error_message = validate_specific_audio_format(file_wav, 'wav')
            if not is_valid:
                return err(f'WAV invalide: {error_message}', status=400)

        if file_image and file_image.filename != '':
            is_valid, error_message = validate_image_file(file_image)
            if not is_valid:
                return err(f'Image invalide: {error_message}', status=400)

        if file_stems and file_stems.filename != '' and current_user.is_premium:
            is_valid, error_message = validate_stems_archive(file_stems)
            if not is_valid:
                return err(f'Archive stems invalide: {error_message}', status=400)

        unique_id = str(_uuid.uuid4())[:8]

        try:
            safe_title = secure_filename(title)[:30]
            safe_title = FileValidator.validate_filename(safe_title)
        except ValueError as e:
            return err(f'Nom de track invalide: {str(e)}', status=400)

        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

        mp3_filename  = f"{safe_title}_{unique_id}_full.mp3"
        mp3_disk_path = config.UPLOAD_FOLDER / mp3_filename
        file_mp3.save(mp3_disk_path)

        preview_filename  = f"{safe_title}_{unique_id}_preview.mp3"
        preview_disk_path = config.UPLOAD_FOLDER / preview_filename

        wav_filename = None
        if file_wav and file_wav.filename != '':
            wav_filename  = f"{safe_title}_{unique_id}_full.wav"
            wav_disk_path = config.UPLOAD_FOLDER / wav_filename
            file_wav.save(wav_disk_path)

        stems_filename = None
        if file_stems and file_stems.filename != '':
            stems_filename  = f"{safe_title}_{unique_id}_stems.zip"
            stems_disk_path = config.UPLOAD_FOLDER / stems_filename
            file_stems.save(stems_disk_path)

        if file_image and file_image.filename != '':
            original_filename = secure_filename(file_image.filename)
            extension         = Path(original_filename).suffix.lower()
            image_filename    = f"{safe_title}_{unique_id}{extension}"
            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            image_disk_path   = tracks_img_folder / image_filename
            file_image.save(image_disk_path)
        else:
            image_filename    = f"{safe_title}_{unique_id}.png"
            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            image_disk_path   = tracks_img_folder / image_filename

        tag_ids_str = request.form.get('tag_ids', '')
        tag_ids = []
        if tag_ids_str:
            try:
                tag_ids = [int(tid) for tid in tag_ids_str.split(',') if tid.strip().isdigit()]
            except Exception as e:
                current_app.logger.warning(f'Erreur parsing tag_ids: {e}')

        job_id = str(_uuid.uuid4())

        job_payload = {
            'job_id':                    job_id,
            'user_id':                   current_user.id,
            'title':                     title,
            'bpm':                       bpm,
            'key':                       key,
            'style':                     style,
            'price_mp3':                 price_mp3,
            'price_wav':                 price_wav,
            'price_stems':               price_stems,
            'sacem_percentage_composer': sacem_percentage_composer,
            'file_hash':                 file_hash,
            'mp3_disk_path':             str(mp3_disk_path),
            'mp3_filename':              mp3_filename,
            'preview_disk_path':         str(preview_disk_path),
            'preview_filename':          preview_filename,
            'wav_filename':              wav_filename,
            'stems_filename':            stems_filename,
            'image_filename':            image_filename if (file_image and file_image.filename != '') else None,
            'image_disk_path':           str(image_disk_path) if (file_image and file_image.filename != '') else None,
            'tag_ids':                   tag_ids,
            **{field: request.form.get(field, type=int) for field in _CONTRACT_PRICE_FIELDS},
        }

        redis_client.hset(f"job:{job_id}", mapping={
            'status':  'queued',
            'user_id': str(current_user.id),
        })
        redis_client.expire(f"job:{job_id}", 7200)

        q = Queue(connection=redis_client)
        q.enqueue('tasks.track_processing.process_track_data', job_payload, job_timeout=720)

        return ok({
            'job_id':    job_id,
            'title':     title,
            'image_url': f'/db_assets/images/tracks/{image_filename}' if image_filename else None,
        }, message='Beat soumis — traitement en cours.', status=202, level='info')

    except Exception as e:
        current_app.logger.error(f'Erreur upload track: {e}', exc_info=True)
        return err('Erreur interne du serveur. Contactez le support.', status=500)


# ── PUT /tracks/put/<track_id> ────────────────────────────────────────────────

@tracks_api_bp.route('/put/<int:track_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@limiter.limit("30 per hour")
@handle_route_exceptions
@require_user
@commit_or_rollback
def put_track(track_id, current_user):
    """Modifier un track existant (propriétaire ou admin)."""
    track = get_or_404(Track, track_id, 'Track introuvable.')
    require_ownership(track, 'composer_id', current_user)

    title   = request.form.get('title', '').strip()
    bpm_str = request.form.get('bpm', '').strip()
    key     = request.form.get('key', '').strip()
    style   = request.form.get('style', '').strip()

    if not title:
        return err('Le titre est obligatoire', level='warning')
    if not bpm_str:
        return err('Le BPM est obligatoire', level='warning')

    try:
        bpm = int(bpm_str)
        if bpm < 60 or bpm > 200:
            return err('Le BPM doit être entre 60 et 200', level='warning')
    except ValueError:
        return err('Le BPM doit être un nombre entier', level='warning')

    try:
        price_mp3   = float(request.form.get('price_mp3',   track.price_mp3))
        price_wav   = float(request.form.get('price_wav',   track.price_wav))
        price_stems = float(request.form.get('price_stems', track.price_stems or 0))
    except ValueError:
        return err('Prix invalides', level='warning')

    file_image = request.files.get('file_image')
    if file_image and file_image.filename != '':
        from utils.file_validator import validate_image_file
        is_valid, error_message = validate_image_file(file_image)
        if not is_valid:
            return err(f'Image invalide: {error_message}', status=400)

        original_filename = secure_filename(file_image.filename)
        extension         = Path(original_filename).suffix.lower()
        safe_title        = secure_filename(title)[:30]
        new_img_filename  = f"{safe_title}_{str(_uuid.uuid4())[:8]}{extension}"

        tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
        tracks_img_folder.mkdir(parents=True, exist_ok=True)
        new_img_path = tracks_img_folder / new_img_filename

        try:
            file_image.save(new_img_path)
        except Exception as e:
            current_app.logger.error(f'Erreur sauvegarde image: {e}')
            return err("Erreur lors du téléchargement de l'image", status=500)

        if track.image_file and 'default_track' not in track.image_file:
            old_img_path = Path(current_app.root_path) / 'db_assets' / track.image_file
            if old_img_path.exists():
                old_img_path.unlink()

        track.image_file = f'images/tracks/{new_img_filename}'

    tag_ids_str = request.form.get('tag_ids', '')
    if tag_ids_str:
        try:
            tag_ids    = [int(tid) for tid in tag_ids_str.split(',') if tid.strip().isdigit()]
            track.tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        except Exception as e:
            current_app.logger.warning(f'Erreur parsing tag_ids: {e}')
    else:
        track.tags = []

    track.title     = title
    track.bpm       = bpm
    track.key       = key
    track.style     = style
    track.price_mp3 = price_mp3
    track.price_wav = price_wav
    if track.file_stems:
        track.price_stems = price_stems

    for field in _CONTRACT_PRICE_FIELDS:
        raw = request.form.get(field)
        if raw is not None:
            try:
                val = int(raw)
            except ValueError:
                return err(f'{field} doit être un entier', level='warning')
            if val < 0 or val > 9999:
                return err(f'{field} doit être entre 0 et 9999', level='warning')
            setattr(track, field, val)

    db.session.commit()

    return ok({
        'track': {
            'id':          track.id,
            'title':       track.title,
            'bpm':         track.bpm,
            'key':         track.key,
            'style':       track.style,
            'price_mp3':   track.price_mp3,
            'price_wav':   track.price_wav,
            'price_stems': track.price_stems,
            'is_approved': track.is_approved,
            'image_file':  track.image_file,
            'contract_prices': _resolve_contract_prices(track),
            'tags': [
                {'name': tag.name, 'category': tag.category_obj.name if tag.category_obj else 'other'}
                for tag in track.tags
            ],
        }
    }, message='Track mis à jour avec succès', level='info')


# ── DELETE /tracks/delete/<track_id> ──────────────────────────────────────────

@tracks_api_bp.route('/delete/<int:track_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def delete_track(track_id, current_user):
    """Supprimer un track et ses fichiers associés (propriétaire ou admin)."""
    track = get_or_404(Track, track_id, 'Track introuvable.')
    require_ownership(track, 'composer_id', current_user)

    # Bloquer si le track a déjà été acheté (intégrité contrats)
    from models import Purchase
    purchase_count = db.session.query(Purchase).filter_by(track_id=track.id).count()
    if purchase_count > 0:
        return err(
            f'Impossible de supprimer ce track : il a été acheté {purchase_count} fois. '
            f'Les acheteurs doivent pouvoir accéder à leurs fichiers et contrats.',
            status=403,
        )

    title = track.title

    for filename in [track.audio_file, track.file_mp3, track.file_wav, track.file_stems]:
        if filename:
            file_path = config.UPLOAD_FOLDER / filename
            if file_path.exists():
                file_path.unlink()

    if track.image_file and 'default_track' not in track.image_file:
        image_path = Path(current_app.root_path) / 'db_assets' / track.image_file
        if image_path.exists():
            image_path.unlink()

    db.session.delete(track)
    db.session.commit()

    current_app.logger.info(f'Track #{track_id} "{title}" supprimé par user #{current_user.id}')
    return ok(message=f'Track "{title}" supprimé avec succès', level='info')
