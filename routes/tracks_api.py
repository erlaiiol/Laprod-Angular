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
import hashlib
import shutil
import config
import random
import uuid as _uuid
import json

from extensions import db, limiter, csrf, redis_client
from models import Track, Tag, Category, User, Topline, TrackView, SimilarArtist, Purchase
from helpers import generate_track_image
from utils.image_variants import generate_variants, delete_variants
from serializers import ok, err, track_card, track_detail, topline as ser_topline, playlist_stats_for_tracks
from utils.auth_helpers import require_user
from utils.search import (
    LIKE_ESCAPE,
    escape_like,
    normalize_search_term,
    extract_bpm,
    fuzzy_name_matches,
    split_search_words,
)
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

        # Licences actives de l'utilisateur connecté pour ce track (par format)
        owned_licenses: dict = {}
        if current_user_id:
            user_purchases = db.session.query(Purchase).filter(
                Purchase.track_id == track_id,
                Purchase.buyer_id == current_user_id,
                Purchase.license_status == 'active',
            ).all()
            for p in user_purchases:
                owned_licenses[p.format_purchased] = {
                    'purchase_id':  p.id,
                    'is_lifetime':  p.is_lifetime,
                    'duration_years': p.duration_years,
                    'expires_at':   p.expires_at.isoformat() if p.expires_at else None,
                    'license_status': p.license_status,
                }

        # Métriques de preuve sociale — calculées à la volée (légères)
        sales_count = db.session.query(func.count(Purchase.id)).filter(
            Purchase.track_id == track_id,
            Purchase.license_status == 'active',
        ).scalar() or 0

        unique_listeners = db.session.query(
            func.count(func.distinct(TrackView.ip_hash))
        ).filter(TrackView.track_id == track_id).scalar() or 0

        toplines_count = db.session.query(func.count(Topline.id)).filter(
            Topline.track_id == track_id,
            Topline.is_published == True,  # noqa: E712
        ).scalar() or 0

        track_data = track_detail(track)
        track_data['toplines']        = [ser_topline(tl) for tl in published_toplines]
        track_data['my_toplines']     = [ser_topline(tl) for tl in my_toplines]
        track_data['contract_prices'] = _resolve_contract_prices(track)
        track_data['owned_licenses']  = owned_licenses
        track_data['sales_count']     = sales_count
        track_data['unique_listeners'] = unique_listeners
        track_data['toplines_count']  = toplines_count

        return ok({'track': track_data})

    except Exception as e:
        current_app.logger.warning(f'erreur API get_track(): {e}')
        return err('Erreur lors de la récupération du track', status=500)


# ── GET /tracks/stats/platform ────────────────────────────────────────────────

@tracks_api_bp.route('/stats/platform', methods=['GET'])
def get_platform_stats():
    """Métriques globales de la plateforme pour la landing page (cachées Redis 1h)."""
    cache_key = 'platform:stats'
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return ok(json.loads(cached))
    except Exception:
        pass

    try:
        beats_count = db.session.query(func.count(Track.id)).filter(
            Track.is_approved == True  # noqa: E712
        ).scalar() or 0

        artists_count = db.session.query(func.count(User.id)).filter(
            User.is_artist == True  # noqa: E712
        ).scalar() or 0

        licenses_sold = db.session.query(func.count(Purchase.id)).filter(
            Purchase.license_status == 'active'
        ).scalar() or 0

        toplines_count = db.session.query(func.count(Topline.id)).filter(
            Topline.is_published == True  # noqa: E712
        ).scalar() or 0

        stats = {
            'beats_count':    beats_count,
            'artists_count':  artists_count,
            'licenses_sold':  licenses_sold,
            'toplines_count': toplines_count,
        }

        try:
            redis_client.setex(cache_key, 3600, json.dumps(stats))
        except Exception:
            pass

        return ok(stats)

    except Exception as e:
        current_app.logger.warning(f'erreur get_platform_stats(): {e}')
        return err('Erreur stats plateforme', status=500)


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

    track_query = select(Track).options(
        selectinload(Track.tags).selectinload(Tag.category_obj),
        selectinload(Track.composer_user),
        selectinload(Track.similar_artists),
    )

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
        tags_param     = request.args.get('tags', '').strip()
        tag_category   = request.args.get('tag_category', '').strip()

        # Conserver la version brute pour les helpers avant l'escape SQL LIKE
        search_raw = search
        search = escape_like(search)

        if search:
            # ── Recherche BPM pure : '140', '140bpm', '140 bpm' ─────────────
            # Quand toute la saisie est un nombre (intention BPM), on applique
            # UNIQUEMENT la plage ±7 — pas de conditions textuelles qui feraient
            # remonter des beats hors-BPM portant "140" dans un tag ou un titre.
            bpm_val = extract_bpm(search_raw)
            if bpm_val:
                track_query = track_query.where(Track.bpm.between(bpm_val - 7, bpm_val + 7))

            else:
                # ── Recherche textuelle générale ──────────────────────────────
                search_conditions = [
                    Track.title.ilike(f'%{search}%', escape=LIKE_ESCAPE),
                    Track.composer_user.has(User.username.ilike(f'%{search}%', escape=LIKE_ESCAPE)),
                    Track.style.ilike(f'%{search}%', escape=LIKE_ESCAPE),
                    Track.key.ilike(f'%{search}%', escape=LIKE_ESCAPE),
                    Track.tags.any(Tag.name.ilike(f'%{search}%', escape=LIKE_ESCAPE)),
                    Track.similar_artists.any(
                        SimilarArtist.name.ilike(f'%{search}%', escape=LIKE_ESCAPE)
                    ),
                ]

                # Mot-par-mot + fuzzy — délégués à utils.search
                # normalize_search_term() ne retire pas les '_' (caractère \w),
                # les mots doivent donc être échappés eux aussi.
                words = split_search_words(search_raw)
                if words:
                    for word in words:
                        esc_word = escape_like(word)
                        search_conditions.append(
                            Track.tags.any(Tag.name.ilike(f'%{esc_word}%', escape=LIKE_ESCAPE))
                        )
                        search_conditions.append(
                            Track.similar_artists.any(
                                SimilarArtist.name.ilike(f'%{esc_word}%', escape=LIKE_ESCAPE)
                            )
                        )

                    all_tag_names    = db.session.execute(select(Tag.name)).scalars().all()
                    all_artist_names = db.session.execute(select(SimilarArtist.name)).scalars().all()

                    fuzzy_tags    = fuzzy_name_matches(words, all_tag_names)
                    fuzzy_artists = fuzzy_name_matches(words, all_artist_names)

                    if fuzzy_tags:
                        search_conditions.append(Track.tags.any(Tag.name.in_(fuzzy_tags)))
                    if fuzzy_artists:
                        search_conditions.append(
                            Track.similar_artists.any(SimilarArtist.name.in_(fuzzy_artists))
                        )

                track_query = track_query.where(or_(*search_conditions))

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

        if tag_category:
            track_query = track_query.where(
                Track.tags.any(
                    Tag.category_obj.has(Category.name == tag_category)
                )
            )

        similar_artists_param = request.args.get('similar_artist_ids', '').strip()
        if similar_artists_param:
            artist_names = [n.strip() for n in similar_artists_param.split(',') if n.strip()]
            if artist_names:
                track_query = track_query.where(
                    Track.similar_artists.any(SimilarArtist.name.in_(artist_names))
                )

        sort = request.args.get('sort', 'recent')

        # Un filtre actif (recherche/BPM/tags/...) restreint le catalogue à un
        # sous-ensemble ; le classement de préférence, lui, reste valable sur ce
        # sous-ensemble (cf. _paginated_reco_response ci-dessous).
        has_active_filters = bool(
            search or bpm_min is not None or bpm_max is not None
            or keys_param or styles_param or tags_param
            or tag_category or similar_artists_param
        )

        # ── Recommandations personnalisées — cache-first ──────────────────────
        # Chemin rapide : lecture d'une liste d'IDs pré-calculés, triée par ordre
        # de préférence décroissant (TTL 30 min). Le calcul tourne en fond (RQ) et
        # peut se terminer entre deux requêtes de pagination du même utilisateur —
        # sans garde-fou, la page 2 basculerait sur un ordre totalement différent
        # de celui vu en page 1. Le snapshot "fallback" (TTL courte) fige donc
        # l'ordre pour toute la session de pagination en cours ; les recos
        # fraîches ne s'appliquent qu'au prochain chargement, une fois ce
        # snapshot expiré.
        #
        # Ce cache couvre tout le catalogue, sans tenir compte des filtres actifs
        # (recalculer le classement par combinaison de filtres n'aurait pas de
        # sens pour un score de goût global). Un filtre ne doit donc jamais
        # écarter la personnalisation : on restreint la liste triée au
        # sous-ensemble qui matche le filtre, EN CONSERVANT son ordre — le rang
        # dans le cache fait office de score. Coûte une requête ID-only
        # supplémentaire, seulement quand un filtre est actif.
        if sort == 'recommended' and user_id and redis_client:
            result_key   = f'laprod:reco:result:{user_id}'
            fallback_key = f'laprod:reco:fallback:{user_id}'

            def _paginated_reco_response(all_ids: list[int], personalized: bool):
                if has_active_filters:
                    matching_ids = set(
                        db.session.execute(track_query.with_only_columns(Track.id)).scalars().all()
                    )
                    all_ids = [tid for tid in all_ids if tid in matching_ids]

                total = len(all_ids)
                page_ids = all_ids[(page - 1) * per_page: page * per_page]
                if page_ids:
                    id_rank = {tid: idx for idx, tid in enumerate(page_ids)}
                    rows = db.session.execute(
                        select(Track).options(
                            selectinload(Track.tags).selectinload(Tag.category_obj),
                            selectinload(Track.composer_user),
                            selectinload(Track.similar_artists),
                        ).where(Track.id.in_(page_ids))
                    ).scalars().all()
                    tracks = sorted(rows, key=lambda t: id_rank.get(t.id, 999))
                else:
                    tracks = []
                pl_counts, pl_images = playlist_stats_for_tracks([t.id for t in tracks])
                return ok({
                    'tracks': [track_card(t, pl_counts, pl_images) for t in tracks],
                    'pagination': {
                        'page':        page,
                        'per_page':    per_page,
                        'total':       total,
                        'pages':       max(1, (total + per_page - 1) // per_page),
                    },
                    'personalized': personalized,
                })

            try:
                fallback_cached = redis_client.get(fallback_key)
                if fallback_cached:
                    return _paginated_reco_response(json.loads(fallback_cached), personalized=False)

                cached = redis_client.get(result_key)
                if cached:
                    return _paginated_reco_response(json.loads(cached), personalized=True)
            except Exception as exc:
                current_app.logger.warning(f'[reco] Lecture cache échouée : {exc}')

            # Rien en cache : figer un snapshot "recent" (TTL 5 min) pour stabiliser
            # toute la pagination de cette session, puis enqueue le calcul perso —
            # qui alimentera laprod:reco:result: pour la prochaine visite. Basé sur
            # tout le catalogue (pas track_query, qui porte les filtres de CETTE
            # requête) pour rester réutilisable par n'importe quelle combinaison de
            # filtres tant que le snapshot vit.
            fallback_ids = None
            try:
                base_ids_query = select(Track.id)
                if not is_admin:
                    base_ids_query = base_ids_query.where(
                        Track.is_approved.is_(True),
                        Track.is_exclusive_sold.is_(False),
                    )
                fallback_ids = db.session.execute(
                    base_ids_query.order_by(Track.created_at.desc())
                ).scalars().all()
                redis_client.setex(fallback_key, 300, json.dumps(fallback_ids))
            except Exception as exc:
                current_app.logger.warning(f'[reco] Snapshot fallback échoué : {exc}')
                fallback_ids = None

            try:
                q = Queue(connection=redis_client)
                q.enqueue('tasks.recommendation.compute_recommendations', user_id, job_timeout=60)
            except Exception as exc:
                current_app.logger.debug(f'[reco] Impossible d\'enqueuer : {exc}')

            if fallback_ids is not None:
                return _paginated_reco_response(fallback_ids, personalized=False)

        # ── Tri récent (défaut) + fallback recommandation ─────────────────────
        tracks = db.session.execute(
            track_query.order_by(Track.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).scalars().all()
        count_query = track_query.with_only_columns(func.count()).order_by(None)
        total = db.session.execute(count_query).scalar()

        pl_counts, pl_images = playlist_stats_for_tracks([t.id for t in tracks])
        return ok({
            'tracks': [track_card(t, pl_counts, pl_images) for t in tracks],
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

def _approved_track_count():
    """Nombre de tracks approuvés, caché 60 s (voir get_random_track)."""
    cache_key = 'tracks:approved_count'
    try:
        cached = redis_client.get(cache_key)
        if cached is not None:
            return int(cached)
    except Exception:
        pass

    total = db.session.query(func.count(Track.id)).filter(
        Track.is_approved.is_(True)
    ).scalar() or 0

    try:
        redis_client.setex(cache_key, 60, total)
    except Exception:
        pass

    return total


@tracks_api_bp.route('/random', methods=['GET'])
@limiter.limit('60 per minute')
def get_random_track():
    """
    Récupérer un track approuvé aléatoire (pour l'autoplay du player).
    Optionnel : exclude_id=<int> pour éviter de rejouer le track actuel.
    → GET /tracks/random?exclude_id=42
    """
    exclude_id = request.args.get('exclude_id', type=int)

    try:
        total = _approved_track_count()
        if not total:
            return err('Aucun track disponible', level='info', status=404)

        query = select(Track).options(
            selectinload(Track.tags), selectinload(Track.composer_user)
        ).where(Track.is_approved.is_(True))

        if exclude_id:
            query = query.where(Track.id != exclude_id)

        # OFFSET aléatoire plutôt qu'ORDER BY random() : ce dernier triait la table
        # entière à CHAQUE appel. Sur un endpoint public, une requête HTTP triviale
        # coûtait donc un scan complet — l'amplification rêvée pour saturer la DB.
        query = query.order_by(Track.id).offset(random.randrange(total)).limit(1)

        track = db.session.execute(query).scalar_one_or_none()

        # exclude_id retire une ligne du jeu filtré : l'offset tiré sur le total
        # peut alors dépasser d'un cran. On retombe sur la première ligne.
        if not track:
            track = db.session.execute(query.offset(0)).scalar_one_or_none()

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
      - file_mp3   : fichier MP3  (optionnel — au moins un de mp3/wav/stems requis)
      - file_wav   : fichier WAV  (optionnel)
      - file_image : image de couverture (optionnel)
      - file_stems : archive ZIP/RAR stems (optionnel)
                     Si stems sans mp3/wav : extrait automatiquement *_current.* (fallback *_master.*)
      - title, bpm, key, style, price_mp3, price_wav, price_stems
      - sacem_percentage_composer, tag_ids
    """
    can_upload, quota_message = current_user.can_upload_track()
    if not can_upload:
        current_app.logger.debug('post_track() l`utilisateur ne peut pas upload (manque de token ?)')
        return err('erreur : upload impossible(manque de token ?)', status=403)

    # Beats exclusifs réservés aux abonnés LaProd+ (amateur ou pro)
    exclusive_price_raw = request.form.get('contract_price_exclusive')
    if exclusive_price_raw is not None and not current_user.is_premium_active:
        return err("L'option de licence exclusive est réservée aux abonnés LaProd+.", status=403)

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

        for _label, _val in (('MP3', price_mp3), ('WAV', price_wav), ('Stems', price_stems)):
            if not (0.50 <= _val <= 999.99):
                return err(f'Le prix {_label} doit être entre 0.50€ et 999.99€', level='warning')

        try:
            sacem_percentage_composer = int(request.form.get('sacem_percentage_composer', 50))
            if sacem_percentage_composer > 85 or sacem_percentage_composer < 0:
                return err('Le pourcentage SACEM doit être entre 0 et 85%', level='warning')
        except ValueError:
            return err('Pourcentage SACEM invalide', level='warning')

        # ── Attestations légales (droits voisins / samples) ────────────────────
        # Condition à la cession des droits voisins de producteur de phonogramme
        # dans le contrat de licence généré à la vente (cf. utils/contract_generator.py).
        phonogram_producer_attested = request.form.get('phonogram_producer_attested') == '1'
        if not phonogram_producer_attested:
            return err(
                "Vous devez attester être le producteur du phonogramme de ce fichier "
                "(ou détenir les droits nécessaires) pour pouvoir le publier.",
                level='warning',
            )

        has_third_party_samples  = request.form.get('has_third_party_samples') == '1'
        sample_clearance_details = request.form.get('sample_clearance_details', '').strip()
        if has_third_party_samples and not sample_clearance_details:
            return err(
                'Merci de décrire le statut de clearance des samples/interpolations utilisés.',
                level='warning',
            )

        file_mp3   = request.files.get('file_mp3')
        file_wav   = request.files.get('file_wav')
        file_image = request.files.get('file_image')
        file_stems = request.files.get('file_stems')

        has_mp3   = bool(file_mp3   and file_mp3.filename   != '')
        has_wav   = bool(file_wav   and file_wav.filename   != '')
        has_stems = bool(file_stems and file_stems.filename != '')

        if not (has_mp3 or has_wav or has_stems):
            return err('Au moins un fichier audio est requis (MP3, WAV ou archive stems)', level='warning')

        if not VALIDATION_AVAILABLE:
            return err('Service de validation non disponible', status=500)

        # ── Validation du fichier primaire et calcul du hash ──────────────────
        file_hash = None

        if has_mp3:
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

        if has_wav:
            is_valid, error_message = validate_specific_audio_format(file_wav, 'wav')
            if not is_valid:
                return err(f'WAV invalide: {error_message}', status=400)
            if not has_mp3:
                # WAV est la source primaire — hash depuis le WAV
                try:
                    file_hash = Track.compute_file_hash(file_wav)
                    if Track.hash_exists(file_hash):
                        return err('Ce beat a déjà été uploadé', status=409)
                except Exception as e:
                    current_app.logger.error(f'Erreur vérification doublon: {e}')
                    return err('Erreur de vérification du fichier', status=500)

        if has_stems:
            stems_only = not has_mp3 and not has_wav
            is_valid, error_message = validate_stems_archive(file_stems, require_primary=stems_only)
            if not is_valid:
                return err(f'Archive stems invalide : {error_message}', status=400, level='warning')
            if stems_only:
                # Stems seuls — hash depuis l'archive (la task extraira le fichier primaire)
                try:
                    file_hash = Track.compute_file_hash(file_stems)
                    if Track.hash_exists(file_hash):
                        return err('Ce beat a déjà été uploadé', status=409)
                except Exception as e:
                    current_app.logger.error(f'Erreur vérification doublon: {e}')
                    return err('Erreur de vérification du fichier', status=500)

        if file_image and file_image.filename != '':
            is_valid, error_message = validate_image_file(file_image)
            if not is_valid:
                return err(f'Image invalide: {error_message}', status=400)

        unique_id = str(_uuid.uuid4())[:8]

        try:
            safe_title = secure_filename(title)[:30]
            safe_title = FileValidator.validate_filename(safe_title)
        except ValueError as e:
            return err(f'Nom de track invalide: {str(e)}', status=400)

        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

        preview_filename  = f"{safe_title}_{unique_id}_preview.mp3"
        preview_disk_path = config.UPLOAD_FOLDER / preview_filename

        # ── Sauvegarde MP3 ────────────────────────────────────────────────────
        mp3_filename = None
        mp3_disk_path = None
        if has_mp3:
            mp3_filename  = f"{safe_title}_{unique_id}_full.mp3"
            mp3_disk_path = config.UPLOAD_FOLDER / mp3_filename
            file_mp3.save(mp3_disk_path)

        # ── Sauvegarde WAV ────────────────────────────────────────────────────
        wav_filename = None
        wav_disk_path = None
        if has_wav:
            wav_filename  = f"{safe_title}_{unique_id}_full.wav"
            wav_disk_path = config.UPLOAD_FOLDER / wav_filename
            file_wav.save(wav_disk_path)

        # ── Sauvegarde stems ──────────────────────────────────────────────────
        stems_filename  = None
        stems_disk_path = None
        if has_stems:
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

        artist_ids_str = request.form.get('similar_artist_ids', '')
        artist_ids = []
        if artist_ids_str:
            try:
                artist_ids = [int(x) for x in artist_ids_str.split(',') if x.strip().isdigit()]
            except Exception as e:
                current_app.logger.warning(f'Erreur parsing similar_artist_ids: {e}')

        playlist_ids_str = request.form.get('playlist_ids', '')
        playlist_ids = []
        if playlist_ids_str:
            try:
                playlist_ids = [int(pid) for pid in playlist_ids_str.split(',') if pid.strip().isdigit()]
            except Exception as e:
                current_app.logger.warning(f'Erreur parsing playlist_ids: {e}')

        job_id = str(_uuid.uuid4())

        job_payload = {
            'job_id':                    job_id,
            'user_id':                   current_user.id,
            'safe_title':                safe_title,
            'unique_id':                 unique_id,
            'title':                     title,
            'bpm':                       bpm,
            'key':                       key,
            'style':                     style,
            'price_mp3':                 price_mp3,
            'price_wav':                 price_wav,
            'price_stems':               price_stems,
            'sacem_percentage_composer': sacem_percentage_composer,
            'phonogram_producer_attested': phonogram_producer_attested,
            'has_third_party_samples':     has_third_party_samples,
            'sample_clearance_details':    sample_clearance_details,
            'file_hash':                 file_hash,
            # Chemins des fichiers uploadés (None si non fourni)
            'mp3_disk_path':    str(mp3_disk_path)    if mp3_disk_path    else None,
            'mp3_filename':     mp3_filename,
            'wav_disk_path':    str(wav_disk_path)    if wav_disk_path    else None,
            'wav_filename':     wav_filename,
            'stems_disk_path':  str(stems_disk_path)  if stems_disk_path  else None,
            'stems_filename':   stems_filename,
            'preview_disk_path': str(preview_disk_path),
            'preview_filename':  preview_filename,
            'image_filename':   image_filename if (file_image and file_image.filename != '') else None,
            'image_disk_path':  str(image_disk_path)  if (file_image and file_image.filename != '') else None,
            'tag_ids':          tag_ids,
            'artist_ids':       artist_ids,
            'playlist_ids':     playlist_ids,
            **{field: request.form.get(field, type=int) for field in _CONTRACT_PRICE_FIELDS},
        }

        redis_client.hset(f"job:{job_id}", mapping={
            'status':  'queued',
            'user_id': str(current_user.id),
        })
        redis_client.expire(f"job:{job_id}", 7200)

        q = Queue(connection=redis_client)
        process_job = q.enqueue('tasks.track_processing.process_track_data', job_payload, job_timeout=720)

        auto_flags = ('auto_bpm', 'auto_key', 'auto_style')
        # Pour stems-only, le fichier primaire n'est pas encore disponible (extrait par la task).
        # L'analyse auto est ignorée dans ce cas — on a mp3 ou wav dispo sinon.
        auto_primary_path = str(mp3_disk_path) if mp3_disk_path else (str(wav_disk_path) if wav_disk_path else None)
        if auto_primary_path and any(request.form.get(f, '0') == '1' for f in auto_flags):
            try:
                q.enqueue(
                    'tasks.audio_analysis.analyze_track',
                    {
                        'job_id':    job_id,
                        'user_id':   current_user.id,
                        # mp3_disk_path ou wav_disk_path selon le mode — la task résout le reste
                        'mp3_path':  auto_primary_path,
                        'auto_bpm':  request.form.get('auto_bpm',   '0') == '1',
                        'auto_key':  request.form.get('auto_key',   '0') == '1',
                        'auto_style': request.form.get('auto_style', '0') == '1',
                    },
                    job_timeout=300,
                    depends_on=process_job,
                )
            except Exception as analysis_err:
                # L'upload continue normalement — seule la détection auto est ignorée
                current_app.logger.warning(f'Impossible d\'enqueuer l\'analyse audio (Redis corrompu ?): {analysis_err}')
                redis_client.hset(f"job:{job_id}", mapping={'auto_analysis_failed': '1'})

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

    # Beats exclusifs réservés aux abonnés LaProd+
    exclusive_price_raw = request.form.get('contract_price_exclusive')
    if exclusive_price_raw is not None and not current_user.is_premium_active:
        from utils.crud_helpers import EntityForbidden
        raise EntityForbidden("L'option de licence exclusive est réservée aux abonnés LaProd+.")

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

    for _label, _val in (('MP3', price_mp3), ('WAV', price_wav), ('Stems', price_stems)):
        if not (0.50 <= _val <= 999.99):
            return err(f'Le prix {_label} doit être entre 0.50€ et 999.99€', level='warning')

    # ── Attestations légales (droits voisins / samples) ────────────────────────
    # Champs optionnels ici : une édition de métadonnées ne doit pas forcer une
    # re-déclaration. phonogram_producer_attested est write-once : on ignore
    # toute tentative de le repasser à False une fois attesté.
    phonogram_raw = request.form.get('phonogram_producer_attested')
    if phonogram_raw is not None and phonogram_raw == '1' and not track.phonogram_producer_attested:
        track.phonogram_producer_attested = True

    has_samples_raw = request.form.get('has_third_party_samples')
    if has_samples_raw is not None:
        has_samples = has_samples_raw == '1'
        details = request.form.get('sample_clearance_details', '').strip()
        if has_samples and not details:
            return err(
                'Merci de décrire le statut de clearance des samples/interpolations utilisés.',
                level='warning',
            )
        track.has_third_party_samples  = has_samples
        track.sample_clearance_details = details or None

    safe_title = secure_filename(title)[:30]
    uid        = str(_uuid.uuid4())[:8]

    file_image = request.files.get('file_image')
    if file_image and file_image.filename != '':
        from utils.file_validator import validate_image_file
        is_valid, error_message = validate_image_file(file_image)
        if not is_valid:
            return err(f'Image invalide: {error_message}', status=400)

        original_filename = secure_filename(file_image.filename)
        extension         = Path(original_filename).suffix.lower()
        new_img_filename  = f"{safe_title}_{uid}{extension}"

        tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
        tracks_img_folder.mkdir(parents=True, exist_ok=True)
        new_img_path = tracks_img_folder / new_img_filename

        try:
            file_image.save(new_img_path)
        except Exception as e:
            current_app.logger.error(f'Erreur sauvegarde image: {e}')
            return err("Erreur lors du téléchargement de l'image", status=500)
        generate_variants(new_img_path)

        if track.image_file and 'default_track' not in track.image_file:
            old_img_path = Path(current_app.root_path) / 'db_assets' / track.image_file
            if old_img_path.exists():
                old_img_path.unlink()
            delete_variants(old_img_path)

        track.image_file = f'images/tracks/{new_img_filename}'

    # ── Fichiers audio (mp3 / wav / stems) ────────────────────────────────────
    primary_audio_for_preview = None
    _AUDIO_FIELDS = [
        ('file_mp3',   '.mp3',          'file_mp3'),
        ('file_wav',   '.wav',          'file_wav'),
        ('file_stems', ('.zip', '.rar'), 'file_stems'),
    ]
    for field_key, accept_ext, attr_name in _AUDIO_FIELDS:
        uploaded = request.files.get(field_key)
        if not (uploaded and uploaded.filename != ''):
            continue

        orig_name = secure_filename(uploaded.filename)
        ext       = Path(orig_name).suffix.lower()
        valid_exts = (accept_ext,) if isinstance(accept_ext, str) else accept_ext
        if ext not in valid_exts:
            return err(f'Format {field_key} invalide (attendu : {"/".join(valid_exts)})', level='warning')

        new_name = f"{safe_title}_{uid}{ext}"
        new_path = config.UPLOAD_FOLDER / new_name
        try:
            uploaded.save(new_path)
        except Exception as e:
            current_app.logger.error(f'Erreur sauvegarde {field_key}: {e}')
            return err(f"Erreur lors de l'upload {field_key}.", status=500)

        old_val = getattr(track, attr_name, None)
        if old_val:
            old_path = config.UPLOAD_FOLDER / old_val
            if old_path.exists():
                try:
                    old_path.unlink()
                except Exception:
                    pass

        setattr(track, attr_name, new_name)

        if field_key in ('file_mp3', 'file_wav'):
            if primary_audio_for_preview is None or field_key == 'file_mp3':
                primary_audio_for_preview = str(new_path)

    tag_ids_str = request.form.get('tag_ids', '')
    if tag_ids_str:
        try:
            tag_ids    = [int(tid) for tid in tag_ids_str.split(',') if tid.strip().isdigit()]
            track.tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        except Exception as e:
            current_app.logger.warning(f'Erreur parsing tag_ids: {e}')
    else:
        track.tags = []

    artist_ids_str = request.form.get('similar_artist_ids', '')
    if artist_ids_str:
        try:
            artist_ids = [int(x) for x in artist_ids_str.split(',') if x.strip().isdigit()]
            track.similar_artists = db.session.query(SimilarArtist).filter(SimilarArtist.id.in_(artist_ids)).all()
        except Exception as e:
            current_app.logger.warning(f'Erreur parsing similar_artist_ids: {e}')
    else:
        track.similar_artists = []

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

    # ── Régénération preview (async via RQ) ────────────────────────────────────
    if request.form.get('regenerate_preview') == '1' and primary_audio_for_preview:
        try:
            # Queue vient de l'import module (haut du fichier) : un import local
            # ici masquerait le patch des tests et divergerait des autres enqueues.
            new_preview_name = f"preview_{safe_title}_{uid}.mp3"
            new_preview_path = config.UPLOAD_FOLDER / new_preview_name
            q = Queue(connection=redis_client)
            q.enqueue(
                'tasks.track_processing.regenerate_preview',
                track.id,
                primary_audio_for_preview,
                str(new_preview_path),
                new_preview_name,
                job_timeout=300,
            )
        except Exception as e:
            current_app.logger.error(f'Erreur enqueue regenerate_preview (track {track.id}): {e}')

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
        delete_variants(image_path)

    db.session.delete(track)
    db.session.commit()

    current_app.logger.info(f'Track #{track_id} "{title}" supprimé par user #{current_user.id}')
    return ok(message=f'Track "{title}" supprimé avec succès', level='info')


# ── Validation de suggestion IA ──────────────────────────────────────────────

@tracks_api_bp.route('/<int:track_id>/validate-suggestion', methods=['PATCH'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def validate_ai_suggestion(track_id, current_user):
    """Marque le track comme validé (is_ai_suggested = False)."""
    track = get_or_404(Track, track_id, 'Track introuvable.')
    require_ownership(track, 'composer_id', current_user)
    track.is_ai_suggested = False
    return ok({'id': track.id}, message='Suggestions validées.', level='info')


# ── Enregistrement d'une vue ──────────────────────────────────────────────────
# Fire-and-forget depuis Angular au chargement du player ou de track-detail.
# Déduplique par ip_hash + track_id sur une fenêtre de 24 h pour les vues uniques.

@tracks_api_bp.route('/track/<int:track_id>/view', methods=['POST'])
@csrf.exempt
@limiter.limit('60 per minute')
def record_track_view(track_id):
    track = db.session.get(Track, track_id)
    if not track:
        return err('Track introuvable', status=404)

    source = (request.get_json(silent=True) or {}).get('source', 'player')
    if source not in ('player', 'detail'):
        source = 'player'

    # IP hash — on ne stocke jamais l'IP brute.
    # request.remote_addr et NON X-Forwarded-For : ce header est fourni par le
    # client, et on en lisait la valeur la plus à gauche — donc celle qu'il
    # choisit. Le faire tourner suffisait à contourner la dédup 24 h ci-dessous :
    # INSERT illimités dans TrackView (disque) et compteurs de vues gonflables.
    # ProxyFix (app.py) renseigne déjà remote_addr avec l'IP réelle derrière nginx.
    raw_ip = request.remote_addr or ''
    ip_hash = hashlib.sha256(raw_ip.encode()).hexdigest()[:32]

    # Récupération optionnelle du user connecté (JWT non obligatoire)
    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity:
            user_id = int(identity)
    except Exception:
        pass

    # Déduplification : une seule vue par (track, ip_hash) dans les dernières 24 h
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(hours=24)
    already = db.session.query(TrackView).filter(
        TrackView.track_id == track_id,
        TrackView.ip_hash  == ip_hash,
        TrackView.created_at >= cutoff,
    ).first()

    if not already:
        db.session.add(TrackView(
            track_id=track_id,
            user_id=user_id,
            ip_hash=ip_hash,
            source=source,
        ))
        db.session.commit()

    return ok()


# ── Stats de vues par track (beatmaker dashboard) ─────────────────────────────
# Retourne total_views + unique_views pour chaque track du beatmaker connecté.
# Agrégation en deux requêtes groupées — pas de N+1.

@tracks_api_bp.route('/my/view-stats', methods=['GET'])
@jwt_required()
@require_user
def my_view_stats(current_user):
    track_ids = [
        row[0] for row in
        db.session.query(Track.id).filter_by(composer_id=current_user.id).all()
    ]
    if not track_ids:
        return ok({'stats': []})

    totals = dict(
        db.session.query(TrackView.track_id, func.count(TrackView.id))
        .filter(TrackView.track_id.in_(track_ids))
        .group_by(TrackView.track_id)
        .all()
    )
    # Vue unique = ip_hash distinct par track
    uniques = dict(
        db.session.query(TrackView.track_id, func.count(TrackView.ip_hash.distinct()))
        .filter(TrackView.track_id.in_(track_ids))
        .group_by(TrackView.track_id)
        .all()
    )

    stats = [
        {
            'track_id':    tid,
            'total_views':  totals.get(tid, 0),
            'unique_views': uniques.get(tid, 0),
        }
        for tid in track_ids
    ]
    return ok({'stats': stats})
