"""
Blueprint PROMO API — codes promo pilotés par les vendeurs

Gestion (réservée aux comptes Premium) :
  GET    /api/promo-codes                      → mes codes
  POST   /api/promo-codes                      → créer un code
  PATCH  /api/promo-codes/<id>                 → modifier (périmètre, limites, activation)
  DELETE /api/promo-codes/<id>                 → supprimer (ou désactiver si déjà utilisé)
  GET    /api/promo-codes/context              → mes beats + prestations remisables (pickers)
  PUT    /api/promo-codes/track/<track_id>     → codes appliqués à un beat (upload-track)

Acheteur (tout utilisateur connecté) :
  POST   /api/promo-codes/preview              → valider un code et calculer la remise
"""
import re
from datetime import datetime

from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required

from extensions import db, csrf, limiter
from models import (
    PromoCode, PromoCodeScope, PromoCodeRedemption, Track, User,
    MIXMASTER_SERVICE_KEYS, promo_code_service,
)
from serializers import ok, err, promo_code as promo_code_dto
from utils.auth_helpers import require_user
from utils.money import ALLOWED_DISCOUNT_PERCENTS
from utils.promo_service import PromoError, apply_to_track, apply_to_mixmaster
from utils.track_pricing import normalize_track_options, compute_track_gross, VALID_FORMATS
from utils.image_variants import variant_or_original

promo_api_bp = Blueprint('promo_api', __name__, url_prefix='/api/promo-codes')

CODE_MIN_LEN = 4
CODE_MAX_LEN = 15
CODE_PATTERN = re.compile(r'[A-Z0-9]+')  # ASCII strict — cf. _validate_code_text
MAX_CODES_PER_USER = 50  # garde-fou anti-spam : personne n'a besoin de 500 codes


# ── Habilitations ────────────────────────────────────────────────────────────

def allowed_service_keys(user):
    """Prestations mix/master que CET ingénieur a le droit de remiser.

    On ne peut pas remiser une prestation qu'on n'est pas habilité à vendre :
    un code « -50 % sur l'intervention artistique » créé par quelqu'un qui n'est
    pas producteur/arrangeur certifié n'aurait aucun sens et laisserait croire à
    l'acheteur qu'il peut commander cette prestation.
    """
    keys = []
    if user.is_mixmaster_engineer:
        keys += ['cleaning', 'effects', 'stems']
    if user.is_certified_master_engineer:
        keys.append('mastering')
    if user.is_certified_producer_arranger:
        keys.append('artistic')
    return [k for k in MIXMASTER_SERVICE_KEYS if k in keys]


def _require_premium(user):
    """Les codes promo sont réservés aux vendeurs (beatmakers et ingénieurs
    Mix/Master certifiés) Premium. Autorisation côté serveur : le front masque
    l'UI, mais c'est CE test qui protège réellement l'endpoint."""
    if not (user.is_beatmaker or user.is_mixmaster_engineer):
        return err(
            'Les codes promo sont réservés aux beatmakers et ingénieurs Mix/Master certifiés.',
            code='NOT_A_SELLER', status=403,
        )
    if not user.is_premium_active:
        return err(
            'Les codes promo sont réservés aux membres Premium.',
            code='PREMIUM_REQUIRED', status=403,
        )
    return None


# ── Validation du payload ────────────────────────────────────────────────────

def _parse_expires_at(raw):
    # Obligatoire : un code promo sans échéance est une remise perpétuelle qu'on
    # oublie d'éteindre. Le champ reste nullable en base pour les codes créés
    # avant cette règle — on ne réécrit pas l'historique, on ferme l'entrée.
    if not raw:
        return None, "Une date d'expiration est obligatoire."
    try:
        # Accepte 'YYYY-MM-DD' comme l'ISO complet envoyé par le front.
        value = datetime.fromisoformat(str(raw).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None, "Date d'expiration invalide."
    if value <= datetime.now():
        return None, "La date d'expiration doit être dans le futur."
    return value, None


def _validate_common(data, user, promo=None):
    """Champs communs création/édition. Renvoie (payload, error_message)."""
    scope = (data.get('scope') or PromoCodeScope.TRACK.value).strip()
    if promo is not None:
        scope = promo.scope  # le périmètre d'un code existant n'est pas mutable
    if scope not in (PromoCodeScope.TRACK.value, PromoCodeScope.MIXMASTER.value):
        return None, 'Type de code promo invalide.'

    if scope == PromoCodeScope.MIXMASTER.value and not allowed_service_keys(user):
        return None, "Vous n'êtes pas habilité à proposer des prestations mix/master."

    try:
        percent = int(data.get('percent'))
    except (TypeError, ValueError):
        return None, 'Pourcentage de remise invalide.'
    if percent not in ALLOWED_DISCOUNT_PERCENTS:
        return None, f"Remise invalide. Valeurs autorisées : {', '.join(map(str, ALLOWED_DISCOUNT_PERCENTS))} %."

    expires_at, date_error = _parse_expires_at(data.get('expires_at'))
    if date_error:
        return None, date_error

    max_redemptions = data.get('max_redemptions')
    if max_redemptions in ('', None):
        max_redemptions = None
    else:
        try:
            max_redemptions = int(max_redemptions)
        except (TypeError, ValueError):
            return None, "Nombre d'utilisations invalide."
        if max_redemptions < 1:
            return None, "Le nombre d'utilisations doit être d'au moins 1."
        # Un quota déjà dépassé rendrait le code immédiatement épuisé.
        if promo is not None and max_redemptions < (promo.redemption_count or 0):
            return None, (
                f"Ce code a déjà été utilisé {promo.redemption_count} fois : "
                f"le quota ne peut pas être inférieur."
            )

    return {
        'scope':           scope,
        'percent':         percent,
        'expires_at':      expires_at,
        'max_redemptions': max_redemptions,
        'once_per_user':   bool(data.get('once_per_user', False)),
        'applies_to_all':  bool(data.get('applies_to_all', False)),
    }, None


def _validate_code_text(raw, user, promo_id=None):
    code = PromoCode.normalize_code(raw)
    if not (CODE_MIN_LEN <= len(code) <= CODE_MAX_LEN):
        return None, f'Le code doit faire entre {CODE_MIN_LEN} et {CODE_MAX_LEN} caractères.'

    # ASCII strict, et non str.isalnum() : isalnum() accepte tout l'Unicode, donc
    # « SUMMЕR30 » avec un Е cyrillique — visuellement identique à « SUMMER30 »,
    # mais une chaîne différente. Un vendeur pourrait forger le sosie du code d'un
    # concurrent, ou tromper un acheteur qui recopie un code vu ailleurs.
    if not CODE_PATTERN.fullmatch(code):
        return None, 'Le code ne peut contenir que des lettres (A-Z) et des chiffres.'

    # Unicité par vendeur : on ne bloque que sur SES propres codes. « SUMMER30 »
    # peut exister chez cent autres vendeurs sans le moindre conflit.
    query = PromoCode.query.filter_by(owner_id=user.id, code=code)
    if promo_id is not None:
        query = query.filter(PromoCode.id != promo_id)
    if query.first():
        return None, 'Vous avez déjà un code promo portant ce nom.'
    return code, None


# ── Périmètre (beats / prestations) ──────────────────────────────────────────

def _set_targets(promo, data, user):
    """Écrit le périmètre du code. Renvoie un message d'erreur ou None."""
    if promo.applies_to_all:
        # Le périmètre explicite devient sans objet : on le purge pour qu'un
        # basculement ultérieur vers « sélection » ne ressuscite pas une liste
        # obsolète, invisible pour le vendeur.
        promo.tracks = []
        db.session.execute(
            promo_code_service.delete().where(promo_code_service.c.promo_code_id == promo.id)
        )
        return None

    if promo.scope == PromoCodeScope.TRACK.value:
        raw_ids = data.get('track_ids') or []
        try:
            track_ids = {int(t) for t in raw_ids}
        except (TypeError, ValueError):
            return 'Liste de beats invalide.'
        if not track_ids:
            return 'Sélectionnez au moins un beat, ou activez « Tous mes beats ».'

        # On ne récupère QUE les beats du vendeur : un id forgé pointant sur le
        # beat d'un tiers ne peut pas entrer dans le périmètre.
        tracks = Track.query.filter(
            Track.id.in_(track_ids), Track.composer_id == user.id,
        ).all()
        if len(tracks) != len(track_ids):
            return "Certains beats sélectionnés ne vous appartiennent pas."
        promo.tracks = tracks
        return None

    # scope mixmaster
    raw_keys = data.get('service_keys') or []
    keys = {str(k) for k in raw_keys}
    permitted = set(allowed_service_keys(user))
    if not keys:
        return 'Sélectionnez au moins une prestation, ou activez « Toutes mes prestations ».'
    if not keys.issubset(permitted):
        return "Vous n'êtes pas habilité à remiser certaines des prestations sélectionnées."

    db.session.execute(
        promo_code_service.delete().where(promo_code_service.c.promo_code_id == promo.id)
    )
    for key in keys:
        db.session.execute(
            promo_code_service.insert().values(promo_code_id=promo.id, service_key=key)
        )
    return None


# ── GET /api/promo-codes ─────────────────────────────────────────────────────

@promo_api_bp.route('', methods=['GET'])
@jwt_required()
@require_user
def list_promo_codes(current_user):
    """Mes codes promo. Accessible même sans Premium : un Premium expiré doit
    pouvoir consulter et désactiver ses codes existants, pas se retrouver
    enfermé dehors avec des remises actives qu'il ne peut plus piloter."""
    codes = (
        PromoCode.query.filter_by(owner_id=current_user.id)
        .order_by(PromoCode.created_at.desc()).all()
    )
    return ok({
        'promo_codes': [promo_code_dto(c) for c in codes],
        'can_create':  bool(
            (current_user.is_beatmaker or current_user.is_mixmaster_engineer)
            and current_user.is_premium_active
        ),
    })


# ── GET /api/promo-codes/context ─────────────────────────────────────────────

@promo_api_bp.route('/context', methods=['GET'])
@jwt_required()
@require_user
def promo_context(current_user):
    """Tout ce dont le formulaire de création a besoin : les beats du vendeur et
    les prestations qu'il est habilité à remiser."""
    tracks = (
        Track.query.filter_by(composer_id=current_user.id)
        .order_by(Track.created_at.desc()).all()
    )
    return ok({
        'tracks': [{
            'id':        t.id,
            'title':     t.title,
            'cover_url': variant_or_original(t.image_file, 'thumb'),
            'price_mp3': float(t.price_mp3) if t.price_mp3 is not None else None,
        } for t in tracks],
        'service_keys':      allowed_service_keys(current_user),
        'allowed_percents':  list(ALLOWED_DISCOUNT_PERCENTS),
        'is_premium':        current_user.is_premium_active,
    })


# ── POST /api/promo-codes ────────────────────────────────────────────────────

@promo_api_bp.route('', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def create_promo_code(current_user):
    gate = _require_premium(current_user)
    if gate:
        return gate

    if PromoCode.query.filter_by(owner_id=current_user.id).count() >= MAX_CODES_PER_USER:
        return err(
            f'Vous avez atteint la limite de {MAX_CODES_PER_USER} codes promo.',
            code='PROMO_LIMIT_REACHED', status=400,
        )

    data = request.get_json() or {}

    payload, error = _validate_common(data, current_user)
    if error:
        return err(error, code='PROMO_INVALID', status=400)

    code, error = _validate_code_text(data.get('code'), current_user)
    if error:
        return err(error, code='PROMO_CODE_INVALID', status=400)

    promo = PromoCode(owner_id=current_user.id, code=code, **payload)
    db.session.add(promo)
    db.session.flush()  # besoin de promo.id pour écrire le périmètre

    error = _set_targets(promo, data, current_user)
    if error:
        db.session.rollback()
        return err(error, code='PROMO_TARGETS_INVALID', status=400)

    db.session.commit()
    return ok({'promo_code': promo_code_dto(promo)}, message='Code promo créé.', status=201)


# ── PATCH /api/promo-codes/<id> ──────────────────────────────────────────────

@promo_api_bp.route('/<int:promo_id>', methods=['PATCH'])
@csrf.exempt
@jwt_required()
@require_user
def update_promo_code(promo_id, current_user):
    promo = db.session.get(PromoCode, promo_id)
    if not promo or promo.owner_id != current_user.id:
        return err('Code promo introuvable.', code='NOT_FOUND', status=404)

    data = request.get_json() or {}

    # Désactivation/réactivation seule : autorisée sans Premium (cf. list_promo_codes).
    if set(data.keys()) == {'is_active'}:
        promo.is_active = bool(data['is_active'])
        db.session.commit()
        return ok({'promo_code': promo_code_dto(promo)},
                  message='Code promo mis à jour.')

    gate = _require_premium(current_user)
    if gate:
        return gate

    payload, error = _validate_common(data, current_user, promo=promo)
    if error:
        return err(error, code='PROMO_INVALID', status=400)

    if 'code' in data:
        code, error = _validate_code_text(data.get('code'), current_user, promo_id=promo.id)
        if error:
            return err(error, code='PROMO_CODE_INVALID', status=400)
        promo.code = code

    for field, value in payload.items():
        if field == 'scope':
            continue
        setattr(promo, field, value)
    if 'is_active' in data:
        promo.is_active = bool(data['is_active'])

    error = _set_targets(promo, data, current_user)
    if error:
        db.session.rollback()
        return err(error, code='PROMO_TARGETS_INVALID', status=400)

    db.session.commit()
    return ok({'promo_code': promo_code_dto(promo)}, message='Code promo mis à jour.')


# ── DELETE /api/promo-codes/<id> ─────────────────────────────────────────────

@promo_api_bp.route('/<int:promo_id>', methods=['DELETE'])
@csrf.exempt
@jwt_required()
@require_user
def delete_promo_code(promo_id, current_user):
    """Supprime le code. S'il a déjà servi, on le DÉSACTIVE au lieu de le
    supprimer : les redemptions sont des pièces comptables rattachées à des
    paiements Stripe réels, les effacer casserait la réconciliation."""
    promo = db.session.get(PromoCode, promo_id)
    if not promo or promo.owner_id != current_user.id:
        return err('Code promo introuvable.', code='NOT_FOUND', status=404)

    has_redemptions = db.session.query(
        PromoCodeRedemption.query.filter_by(promo_code_id=promo.id).exists()
    ).scalar()

    if has_redemptions:
        promo.is_active = False
        db.session.commit()
        return ok(
            {'promo_code': promo_code_dto(promo), 'deleted': False},
            message='Ce code a déjà été utilisé : il a été désactivé et conservé dans votre historique.',
            level='info',
        )

    db.session.delete(promo)
    db.session.commit()
    return ok({'deleted': True}, message='Code promo supprimé.')


# ── PUT /api/promo-codes/track/<track_id> ────────────────────────────────────

@promo_api_bp.route('/track/<int:track_id>', methods=['PUT'])
@csrf.exempt
@jwt_required()
@require_user
def set_track_promo_codes(track_id, current_user):
    """Codes promo applicables à UN beat — utilisé par upload-track / edit-track.

    Corps : { "promo_code_ids": [1, 4] }
    Les codes « tous mes beats » ne sont pas listés ici : ils s'appliquent déjà
    et ne sont pas rattachables beat par beat.
    """
    track = db.session.get(Track, track_id)
    if not track or track.composer_id != current_user.id:
        return err('Beat introuvable.', code='NOT_FOUND', status=404)

    data = request.get_json() or {}
    try:
        wanted_ids = {int(i) for i in (data.get('promo_code_ids') or [])}
    except (TypeError, ValueError):
        return err('Liste de codes promo invalide.', code='PROMO_INVALID', status=400)

    # Uniquement MES codes, scope track, non « tous » — un id forgé ne peut pas
    # rattacher le beat au code d'un autre vendeur.
    selectable = PromoCode.query.filter_by(
        owner_id=current_user.id,
        scope=PromoCodeScope.TRACK.value,
        applies_to_all=False,
    ).all()
    selectable_by_id = {p.id: p for p in selectable}

    if not wanted_ids.issubset(selectable_by_id.keys()):
        return err('Certains codes promo sélectionnés sont invalides.',
                   code='PROMO_INVALID', status=400)

    for promo in selectable:
        covered = any(t.id == track.id for t in promo.tracks)
        if promo.id in wanted_ids and not covered:
            promo.tracks.append(track)
        elif promo.id not in wanted_ids and covered:
            promo.tracks = [t for t in promo.tracks if t.id != track.id]

    db.session.commit()
    return ok({'promo_code_ids': sorted(wanted_ids)}, message='Codes promo mis à jour.')


# ── POST /api/promo-codes/preview ────────────────────────────────────────────

@promo_api_bp.route('/preview', methods=['POST'])
@csrf.exempt
@limiter.limit('20 per minute;150 per hour')
@jwt_required()
@require_user
def preview_promo_code(current_user):
    """Valide un code saisi par un ACHETEUR et renvoie la remise chiffrée.

    RATE LIMITÉ : cet endpoint est un oracle « ce code existe-t-il ? ». Sans
    plafond, on énumère par force brute les codes d'un vendeur (les humains
    choisissent SUMMER30, NOEL50, PROMO10…) et on s'offre des remises jamais
    diffusées. 20/min laisse passer la faute de frappe, pas le dictionnaire.

    Aucune consommation ici : le quota n'est décrémenté qu'au paiement réussi.
    Le calcul passe par utils.promo_service, exactement comme le checkout — ce
    qui est affiché ici est ce qui sera encaissé.

    Corps (beat)      : { scope:'track', code, track_id, format_type, ...options }
    Corps (mix/master): { scope:'mixmaster', code, engineer_id, service_*, has_separated_stems }
    """
    data = request.get_json() or {}
    code = data.get('code')
    scope = (data.get('scope') or PromoCodeScope.TRACK.value).strip()

    if not code:
        return err('Saisissez un code promo.', code='PROMO_NOT_FOUND', status=400)

    try:
        if scope == PromoCodeScope.TRACK.value:
            result = _preview_track(data, code, current_user)
        elif scope == PromoCodeScope.MIXMASTER.value:
            result = _preview_mixmaster(data, code, current_user)
        else:
            return err('Type de code promo invalide.', code='PROMO_INVALID', status=400)
    except PromoError as e:
        return err(e.message, code=e.code, status=400)
    except ValueError as e:
        return err(str(e), code='PRICE_CALC_ERROR', status=400)

    if isinstance(result, tuple):  # (response, ) d'erreur remontée par le helper
        return result[0]

    return ok({
        'code':     result['code'],
        'percent':  result['percent'],
        'gross':    float(result['gross']),
        'discount': float(result['discount']),
        'net':      float(result['net']),
    }, message=f"Code promo appliqué : -{result['percent']} %.")


def _preview_track(data, code, buyer):
    track = db.session.get(Track, data.get('track_id') or 0)
    if not track:
        return (err('Beat introuvable.', code='NOT_FOUND', status=404),)

    format_type = data.get('format_type', 'mp3')
    if format_type not in VALID_FORMATS:
        return (err('Format invalide.', code='INVALID_FORMAT', status=400),)

    options, error = normalize_track_options(data)
    if error:
        return (err('Options de licence invalides.', code=error, status=400),)

    gross = compute_track_gross(track, options, format_type)
    return apply_to_track(code, track, buyer.id, gross)


def _preview_mixmaster(data, code, buyer):
    from utils.payment_validator import MixMasterRequestPriceCalculator

    engineer = db.session.get(User, data.get('engineer_id') or 0)
    if not engineer:
        return (err('Ingénieur introuvable.', code='NOT_FOUND', status=404),)

    services = {
        'service_cleaning':  bool(data.get('service_cleaning')),
        'service_effects':   bool(data.get('service_effects')),
        'service_artistic':  bool(data.get('service_artistic')),
        'service_mastering': bool(data.get('service_mastering')),
    }
    has_stems = bool(data.get('has_separated_stems'))

    calculator = MixMasterRequestPriceCalculator()
    _base, _opts, gross = calculator.calculate_total(
        resource=engineer,
        options={'has_separated_stems': has_stems},
        **services,
    )

    selected_keys = [k for k, flag in (
        ('cleaning',  services['service_cleaning']),
        ('effects',   services['service_effects']),
        ('artistic',  services['service_artistic']),
        ('mastering', services['service_mastering']),
        ('stems',     has_stems),
    ) if flag]

    return apply_to_mixmaster(code, engineer, buyer.id, gross, selected_keys)
