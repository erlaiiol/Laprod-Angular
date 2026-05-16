"""
Blueprint MIXMASTER API — tous les endpoints mix/master

mixmaster_api_bp         /api/mixmaster          — GET publics + JWT
cud_mixmaster_artist_api_bp  /api/mixmaster-artist  — Actions artiste (commander, révision, valider)
cud_mixmaster_engineer_api_bp /api/mixmaster-engineer — Actions ingénieur (accept, upload, livraison)
"""
from flask import Blueprint, request, current_app, send_file
from flask_jwt_extended import jwt_required
from werkzeug.utils import secure_filename
from sqlalchemy import select
from extensions import db, csrf, limiter
from models import User, MixMasterRequest
from serializers import ok, err as ser_err, mix_engineer, mix_order_full as ser_order_full
from helpers import sanitize_html
from utils.auth_helpers import require_user
from utils.notification_service import notify_mixmaster_status_changed, notify_mixmaster_request_received_and_sent
from utils import email_service
from utils.stripe_logger import (
    log_stripe_checkout_session_created, log_stripe_payment_intent_captured,
    log_stripe_transaction, log_stripe_error,
)
from utils.archive_utils import get_archive_file_tree
from utils.payment_validator import MixMasterRequestPriceCalculator
import stripe
import stripe._error as stripe_error
from datetime import datetime, timedelta
from pathlib import Path
from pydub import AudioSegment
from pydub import scipy_effects
import config

try:
    from utils.file_validator import validate_stems_archive, validate_audio_file
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

# ─── Blueprints ───────────────────────────────────────────────────────────────

mixmaster_api_bp               = Blueprint('mixmaster_api',               __name__, url_prefix='/api/mixmaster')
cud_mixmaster_artist_api_bp    = Blueprint('cud_mixmaster_artist_api',    __name__, url_prefix='/api/mixmaster-artist')
cud_mixmaster_engineer_api_bp  = Blueprint('cud_mixmaster_engineer_api',  __name__, url_prefix='/api/mixmaster-engineer')

# ─── Helpers partagés ─────────────────────────────────────────────────────────

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB


def _check_size(f) -> bool:
    f.seek(0, 2); size = f.tell(); f.seek(0)
    return size <= MAX_FILE_SIZE


def _allowed(filename: str, exts: set) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in exts


def _get_order_for_artist(order_id: int, user_id: int) -> MixMasterRequest | None:
    order = db.session.get(MixMasterRequest, order_id)
    return order if order and order.artist_id == user_id else None


def _get_order_for_engineer(order_id: int, user_id: int) -> MixMasterRequest | None:
    order = db.session.get(MixMasterRequest, order_id)
    return order if order and order.engineer_id == user_id else None


def _generate_telephone_preview(audio_segment: AudioSegment) -> AudioSegment:
    filtered = audio_segment.high_pass_filter(120)
    return filtered.low_pass_filter(10000)


# =============================================================================
# GET — mixmaster_api_bp (/api/mixmaster)
# =============================================================================

@mixmaster_api_bp.route('/engineers', methods=['GET'])
@csrf.exempt
def get_engineers():
    """Liste des ingénieurs certifiés (public)."""
    engineers = db.session.scalars(
        select(User).where(User.is_mixmaster_engineer == True).order_by(User.username)
    ).all()
    return ok({'engineers': [mix_engineer(e) for e in engineers]})


@mixmaster_api_bp.route('/engineers/<int:engineer_id>', methods=['GET'])
@csrf.exempt
def get_engineer(engineer_id):
    """Détail d'un ingénieur (public)."""
    eng = db.get_or_404(User, engineer_id)
    if not eng.is_mixmaster_engineer:
        return ser_err('Ingénieur introuvable.', status=404)
    return ok({'engineer': mix_engineer(eng)})


@mixmaster_api_bp.route('/my-requests', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_my_requests(current_user):
    """Demandes de mix/master de l'artiste connecté."""
    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.artist_id == current_user.id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()
    return ok({'requests': [ser_order_full(o, 'artist') for o in orders]})


@mixmaster_api_bp.route('/my-orders', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_my_orders(current_user):
    """Commandes de mix/master reçues par l'ingénieur connecté."""
    if not current_user.is_mix_engineer:
        return ser_err('Accès refusé.', status=403)

    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.engineer_id == current_user.id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()
    return ok({'orders': [ser_order_full(o, 'engineer') for o in orders]})


@mixmaster_api_bp.route('/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_order(order_id, current_user):
    """Détail complet d'une commande (artiste ou ingénieur concerné)."""
    order = db.get_or_404(MixMasterRequest, order_id)
    if order.artist_id != current_user.id and order.engineer_id != current_user.id:
        return ser_err('Accès refusé.', status=403)
    return ok({'order': ser_order_full(order)})


# =============================================================================
# CUD ARTISTE — cud_mixmaster_artist_api_bp (/api/mixmaster-artist)
# =============================================================================

@cud_mixmaster_artist_api_bp.route('/order/<int:engineer_id>', methods=['POST'])
@limiter.limit('10 per hour')
@jwt_required()
@csrf.exempt
@require_user
def create_order(engineer_id, current_user):
    """
    Crée une demande de mix/master + session Stripe Checkout.
    Renvoie { checkout_url } pour redirection côté Angular.

    Form-data attendu :
      stems_file       : .zip ou .rar  (pistes séparées)
      reference_file   : .wav ou .mp3  (maquette)
      title            : str
      service_cleaning / service_effects / service_artistic / service_mastering : '1'|'0'
      has_separated_stems : '1'|'0'
      artist_message, brief_* : str (facultatifs)
      success_url      : URL complète de la page Angular de retour Stripe
      cancel_url       : URL complète de la page Angular en cas d'annulation
    """
    engineer = db.get_or_404(User, engineer_id)

    if current_user.id == engineer_id:
        return ser_err('Vous ne pouvez pas commander un mix/master à vous-même.', status=403)

    if not engineer.is_mixmaster_engineer:
        return ser_err("Cet ingénieur n'est pas certifié.")

    active_count = MixMasterRequest.get_active_requests_count(engineer_id)
    if active_count >= 5:
        return ser_err(f'{engineer.username} a déjà 5 mix en cours.', level='warning')

    if not VALIDATION_AVAILABLE:
        return ser_err('Validation sécurité indisponible.', status=500)

    stems_file     = request.files.get('stems_file')
    reference_file = request.files.get('reference_file')

    if not stems_file or not reference_file or stems_file.filename == '' or reference_file.filename == '':
        return ser_err('Les 2 fichiers sont requis (pistes et maquette).', level='warning')

    if not _allowed(stems_file.filename, {'zip', 'rar'}):
        return ser_err('Les pistes séparées doivent être en .zip ou .rar.', level='warning', status=422)

    is_valid, validation_err = validate_stems_archive(stems_file)
    if not is_valid:
        return ser_err(f'Archive invalide : {validation_err}', level='warning', status=422)

    if not _allowed(reference_file.filename, {'wav', 'mp3'}):
        return ser_err('La maquette doit être en .wav ou .mp3.', level='warning', status=422)

    is_valid, validation_err = validate_audio_file(reference_file)
    if not is_valid:
        return ser_err(f'Maquette invalide : {validation_err}', level='warning', status=422)

    if not _check_size(stems_file) or not _check_size(reference_file):
        return ser_err('Fichier trop volumineux (max 500 MB).', level='warning', status=422)

    def bval(key): return request.form.get(key, '0') == '1'

    title                = sanitize_html(request.form.get('title', '').strip()) or f'Mix/Master #{current_user.id}'
    service_cleaning     = bval('service_cleaning')
    service_effects      = bval('service_effects')
    service_artistic     = bval('service_artistic')
    service_mastering    = bval('service_mastering')
    has_separated_stems  = bval('has_separated_stems')
    artist_message       = sanitize_html(request.form.get('artist_message', '').strip()) or None
    brief_vocals         = sanitize_html(request.form.get('brief_vocals', '').strip()) or None
    brief_backing_vocals = sanitize_html(request.form.get('brief_backing_vocals', '').strip()) or None
    brief_ambiance       = sanitize_html(request.form.get('brief_ambiance', '').strip()) or None
    brief_bass           = sanitize_html(request.form.get('brief_bass', '').strip()) or None
    brief_energy_style   = sanitize_html(request.form.get('brief_energy_style', '').strip()) or None
    brief_references     = sanitize_html(request.form.get('brief_references', '').strip()) or None
    brief_instruments    = sanitize_html(request.form.get('brief_instruments', '').strip()) or None
    brief_percussion     = sanitize_html(request.form.get('brief_percussion', '').strip()) or None
    brief_effects        = sanitize_html(request.form.get('brief_effects', '').strip()) or None
    brief_structure      = sanitize_html(request.form.get('brief_structure', '').strip()) or None
    success_url          = request.form.get('success_url', '')
    cancel_url           = request.form.get('cancel_url', '')

    if engineer.mixmaster_reference_price and engineer.mixmaster_price_min:
        min_pct = (engineer.mixmaster_price_min / engineer.mixmaster_reference_price) * 100
        if min_pct >= 35:  service_cleaning  = True
        if 55 <= min_pct < 80: service_mastering = True
        if min_pct >= 80:  service_effects   = True
        if min_pct >= 100: service_mastering = True
        if min_pct >= 160 and engineer.is_certified_producer_arranger:
            service_artistic = True

    if not any([service_cleaning, service_effects, service_artistic, service_mastering]):
        return ser_err('Sélectionnez au moins un service.', level='warning')

    calculator = MixMasterRequestPriceCalculator()
    base_price, options_price, total_price = calculator.calculate_total(
        resource=engineer,
        options={'has_separated_stems': has_separated_stems},
        service_cleaning=service_cleaning,
        service_effects=service_effects,
        service_artistic=service_artistic,
        service_mastering=service_mastering,
    )

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    config.MIXMASTER_UPLOADS_FOLDER.mkdir(parents=True, exist_ok=True)

    stems_name = f'{current_user.id}_{ts}_stems_{secure_filename(stems_file.filename)}'
    ref_name   = f'{current_user.id}_{ts}_ref_{secure_filename(reference_file.filename)}'
    stems_disk = config.MIXMASTER_UPLOADS_FOLDER / stems_name
    ref_disk   = config.MIXMASTER_UPLOADS_FOLDER / ref_name
    stems_file.save(stems_disk)
    reference_file.save(ref_disk)
    stems_web = Path('db_assets', 'mixmaster', 'uploads', stems_name).as_posix()
    ref_web   = Path('db_assets', 'mixmaster', 'uploads', ref_name).as_posix()

    archive_file_tree = get_archive_file_tree(str(stems_disk))

    metadata = {
        'type':               'mixmaster',
        'artist_id':          str(current_user.id),
        'artist_username':    current_user.username,
        'artist_email':       current_user.email,
        'engineer_id':        str(engineer_id),
        'engineer_username':  engineer.username,
        'stems_file':         stems_web,
        'reference_file':     ref_web,
        'archive_file_tree':  str(archive_file_tree)[:500] if archive_file_tree else '',
        'service_cleaning':   str(service_cleaning),
        'service_effects':    str(service_effects),
        'service_artistic':   str(service_artistic),
        'service_mastering':  str(service_mastering),
        'has_separated_stems': str(has_separated_stems),
        'artist_message':     (artist_message or '')[:2000],
        'brief_vocals':       (brief_vocals or '')[:500],
        'brief_backing_vocals': (brief_backing_vocals or '')[:500],
        'brief_ambiance':     (brief_ambiance or '')[:500],
        'brief_bass':         (brief_bass or '')[:500],
        'brief_energy_style': (brief_energy_style or '')[:500],
        'brief_references':   (brief_references or '')[:500],
        'brief_instruments':  (brief_instruments or '')[:500],
        'brief_percussion':   (brief_percussion or '')[:500],
        'brief_effects_brief': (brief_effects or '')[:500],
        'brief_structure':    (brief_structure or '')[:500],
        'title':              title[:50],
    }

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': int(total_price * 100),
                    'product_data': {
                        'name': f'Mix/Master par {engineer.username}',
                        'description': ', '.join(filter(None, [
                            'Nettoyage' if service_cleaning else '',
                            'Effets'    if service_effects  else '',
                            'Artistique' if service_artistic else '',
                            'Mastering' if service_mastering else '',
                        ])),
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            payment_intent_data={
                'capture_method': 'automatic',
                'metadata': metadata,
            },
            success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}' if success_url else request.url_root.rstrip('/') + '/mix/payment-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=cancel_url or request.url_root.rstrip('/') + f'/mix/order/{engineer_id}',
            customer_email=current_user.email,
            metadata=metadata,
        )

        log_stripe_checkout_session_created(
            session_id=checkout_session.id,
            amount=int(total_price * 100),
            resource_type='mixmaster',
            resource_id='pending',
            engineer_id=engineer_id,
            artist_id=current_user.id,
        )

        return ok({'checkout_url': checkout_session.url})

    except stripe_error.StripeError as e:
        log_stripe_error(operation='create_mixmaster_checkout', error_message=str(e),
                         resource_type='mixmaster', engineer_id=engineer_id, artist_id=current_user.id)
        for p in [stems_disk, ref_disk]:
            if p.exists(): p.unlink()
        return ser_err(f'Erreur Stripe : {str(e)}', status=502)


@cud_mixmaster_artist_api_bp.route('/cancel/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def cancel_order(order_id, current_user):
    """Annule la demande avant acceptation par l'ingénieur. Rembourse l'artiste via Stripe Refund."""
    order = _get_order_for_artist(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'awaiting_acceptance':
        return ser_err('Cette demande ne peut plus être annulée.', level='warning')

    if order.stripe_payment_intent_id and order.stripe_payment_status == 'captured':
        try:
            stripe.Refund.create(
                payment_intent=order.stripe_payment_intent_id,
                reason='requested_by_customer',
            )
            order.stripe_payment_status = 'refunded'
            log_stripe_transaction(
                operation='refund_artist_cancel', resource_type='mixmaster',
                resource_id=order_id, stripe_payment_intent_id=order.stripe_payment_intent_id,
                reason='artist_cancellation_before_acceptance',
            )
        except stripe_error.StripeError as e:
            log_stripe_error(operation='cancel_mixmaster', error_message=str(e),
                             resource_type='mixmaster', resource_id=order_id)
            return ser_err(f'Erreur Stripe : {str(e)}', status=502)

    for f_path in [order.original_file, order.reference_file]:
        if f_path:
            p = Path(current_app.root_path) / f_path
            if p.exists(): p.unlink()

    order.status      = 'refunded'
    order.rejected_at = datetime.now()
    notify_mixmaster_status_changed(order, 'awaiting_acceptance', 'refunded')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, 'awaiting_acceptance', 'refunded')
    except Exception as e:
        current_app.logger.warning(f'Email cancel #{order_id}: {e}')

    return ok(message='Demande annulée. Vos fonds ont été libérés.')


@cud_mixmaster_artist_api_bp.route('/revision/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def request_revision(order_id, current_user):
    """L'artiste demande une révision. Crédite wallet de l'ingénieur (10% net)."""
    order = _get_order_for_artist(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.stripe_payment_status != 'deposit_captured':
        return ser_err('Statut de paiement incorrect pour une révision.', level='warning')

    can_rev, reason = order.can_request_revision()
    if not can_rev:
        return ser_err(reason, level='warning')

    data = request.get_json() or {}
    revision_message = (data.get('revision_message') or '').strip()
    if not revision_message:
        return ser_err('Précisez les modifications souhaitées.', level='warning')

    old_status = order.status
    order.revision_count += 1
    revision_amount = order.get_revision_transfer_amount()

    from utils.wallet_service import credit_wallet_for_mixmaster_revision
    credit_wallet_for_mixmaster_revision(order)

    if order.revision_count == 1:
        order.status                 = 'revision1'
        order.revision1_message      = revision_message
        order.revision1_requested_at = datetime.now()
        order.stripe_payment_status  = 'partially_captured'
    else:
        order.status                 = 'revision2'
        order.revision2_message      = revision_message
        order.revision2_requested_at = datetime.now()

    notify_mixmaster_status_changed(order, old_status, order.status)
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, old_status, order.status)
    except Exception as e:
        current_app.logger.warning(f'Email revision #{order_id}: {e}')

    return ok(
        {'status': order.status, 'revision_count': order.revision_count},
        message=f"Révision {order.revision_count}/2 demandée. {revision_amount}€ ajoutés aux gains de l'ingénieur.",
    )


@cud_mixmaster_artist_api_bp.route('/reject-delivery/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def reject_delivery(order_id, current_user):
    """
    L'artiste refuse la livraison après écoute des previews.
    Remboursement partiel Stripe (solde brut restant) :
      - 0 révision  → 70% du total remboursé
      - 1 révision  → 60% du total remboursé
      - 2 révisions → 50% du total remboursé
    """
    order = _get_order_for_artist(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'delivered':
        return ser_err('Cette commande ne peut pas être refusée dans son état actuel.', level='warning')

    if order.stripe_payment_status != 'deposit_captured':
        return ser_err('Statut de paiement incorrect.', level='warning')

    refund_amount = order.get_refund_amount()

    try:
        stripe.Refund.create(
            payment_intent=order.stripe_payment_intent_id,
            amount=int(round(refund_amount * 100)),
            reason='requested_by_customer',
        )
        log_stripe_transaction(
            operation='partial_refund_artist_reject_delivery',
            resource_type='mixmaster',
            resource_id=order_id,
            stripe_payment_intent_id=order.stripe_payment_intent_id,
            reason=f'artist_rejected_delivery_after_{order.revision_count}_revisions',
        )
    except stripe_error.StripeError as e:
        log_stripe_error(operation='reject_delivery_refund', error_message=str(e),
                         resource_type='mixmaster', resource_id=order_id)
        return ser_err(f'Erreur Stripe : {str(e)}', status=502)

    order.status                = 'refunded'
    order.stripe_payment_status = 'partially_refunded'
    order.rejected_at           = datetime.now()

    notify_mixmaster_status_changed(order, 'delivered', 'refunded')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, 'delivered', 'refunded')
    except Exception as e:
        current_app.logger.warning(f'Email reject_delivery #{order_id}: {e}')

    return ok(
        {'refund_amount': refund_amount},
        message=f'Livraison refusée. Vous serez remboursé de {refund_amount:.2f}€ (solde restant après {order.revision_count} révision(s)).',
        level='info',
    )


@cud_mixmaster_artist_api_bp.route('/approve/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def approve_and_download(order_id, current_user):
    """
    L'artiste valide la livraison.
    Crédite le wallet engineer pour le solde final.
    Renvoie l'URL de téléchargement du fichier final.
    """
    order = _get_order_for_artist(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status not in ('delivered', 'completed'):
        return ser_err("Le fichier n'a pas encore été livré.", level='warning')

    if order.stripe_payment_status != 'deposit_captured':
        return ser_err('Statut de paiement incorrect.', level='warning')

    if not order.processed_file:
        return ser_err('Fichier traité introuvable.', status=404)

    processed_path = Path(current_app.root_path) / order.processed_file
    if not processed_path.exists():
        return ser_err('Fichier introuvable sur le serveur.', status=404)

    try:
        final_amount = order.get_final_transfer_amount()

        from utils.wallet_service import credit_wallet_for_mixmaster_final
        credit_wallet_for_mixmaster_final(order)

        order.status                = 'completed'
        order.completed_at          = datetime.now()
        order.stripe_payment_status = 'fully_transferred'

        notify_mixmaster_status_changed(order, 'delivered', 'completed')
        db.session.commit()

        try:
            email_service.send_mixmaster_status_update_email(order, 'delivered', 'completed')
        except Exception as e:
            current_app.logger.warning(f'Email completed #{order_id}: {e}')

        return ok(
            {'status': order.status, 'download_url': f'/mixmaster-artist/download/{order_id}'},
            message=f"Validation réussie ! Solde de {final_amount}€ crédité à l'ingénieur.",
        )

    except Exception as e:
        current_app.logger.error(f'approve_and_download #{order_id}: {e}', exc_info=True)
        return ser_err('Erreur serveur.', status=500)


@cud_mixmaster_artist_api_bp.route('/download/<int:order_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_file(order_id, current_user):
    """Téléchargement sécurisé du fichier final (JWT + artist ownership + status completed)."""
    order = _get_order_for_artist(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'completed':
        return ser_err("La commande n'est pas encore terminée.", level='warning')

    if not order.processed_file:
        return ser_err('Fichier introuvable.', status=404)

    processed_path = Path(current_app.root_path) / order.processed_file
    if not processed_path.exists():
        return ser_err('Fichier introuvable sur le serveur.', status=404)

    return send_file(processed_path, as_attachment=True)


# =============================================================================
# CUD INGÉNIEUR — cud_mixmaster_engineer_api_bp (/api/mixmaster-engineer)
# =============================================================================

@cud_mixmaster_engineer_api_bp.route('/accept/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def accept_order(order_id, current_user):
    order = _get_order_for_engineer(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'awaiting_acceptance':
        return ser_err('Cette commande a déjà été traitée.', level='warning')

    if not MixMasterRequest.can_accept_more_requests(current_user.id):
        return ser_err('Vous avez déjà 5 mix/master en cours.', level='warning')

    order.status      = 'accepted'
    order.accepted_at = datetime.now()
    order.deadline    = datetime.now() + timedelta(days=7)

    notify_mixmaster_status_changed(order, 'awaiting_acceptance', 'accepted')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, 'awaiting_acceptance', 'accepted')
    except Exception as e:
        current_app.logger.warning(f'Email accept #{order_id}: {e}')

    return ok(
        {'status': order.status, 'deadline': order.deadline.isoformat()},
        message='Demande acceptée ! Vous avez 7 jours pour livrer.',
    )


@cud_mixmaster_engineer_api_bp.route('/reject/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def reject_order(order_id, current_user):
    order = _get_order_for_engineer(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'awaiting_acceptance':
        return ser_err('Cette commande a déjà été traitée.', level='warning')

    if order.stripe_payment_intent_id and order.stripe_payment_status == 'captured':
        try:
            stripe.Refund.create(
                payment_intent=order.stripe_payment_intent_id,
                reason='requested_by_customer',
            )
            order.stripe_payment_status = 'refunded'
            log_stripe_transaction(
                operation='refund_engineer_reject', resource_type='mixmaster',
                resource_id=order_id, stripe_payment_intent_id=order.stripe_payment_intent_id,
                reason='engineer_rejection',
            )
        except stripe_error.StripeError as e:
            log_stripe_error(operation='reject_mixmaster_refund', error_message=str(e),
                             resource_type='mixmaster', resource_id=order_id)
            return ser_err(f'Erreur remboursement Stripe : {str(e)}', status=502)

    for f_path in [order.original_file, order.reference_file]:
        if f_path:
            p = Path(current_app.root_path) / f_path
            if p.exists(): p.unlink()

    order.status      = 'rejected'
    order.rejected_at = datetime.now()

    notify_mixmaster_status_changed(order, 'awaiting_acceptance', 'rejected')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, 'awaiting_acceptance', 'rejected')
    except Exception as e:
        current_app.logger.warning(f'Email reject #{order_id}: {e}')

    return ok(message="Demande refusée. L'artiste a été remboursé intégralement.", level='info')


@cud_mixmaster_engineer_api_bp.route('/upload/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def upload_processed(order_id, current_user):
    """L'ingénieur livre le fichier traité. Capture Stripe 100% + acompte wallet."""
    order = _get_order_for_engineer(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status not in ('accepted', 'processing'):
        return ser_err('Cette commande ne peut plus être modifiée.', level='warning')

    if not VALIDATION_AVAILABLE:
        return ser_err('Validation sécurité indisponible.', status=500)

    file = request.files.get('processed_file')
    if not file or file.filename == '':
        return ser_err('Aucun fichier sélectionné.', level='warning')

    if not _allowed(file.filename, {'wav', 'mp3'}):
        return ser_err('Format non autorisé (.wav ou .mp3).', level='warning', status=422)

    is_valid, validation_err = validate_audio_file(file)
    if not is_valid:
        return ser_err(f'Fichier invalide : {validation_err}', level='warning', status=422)

    if not _check_size(file):
        return ser_err('Fichier trop volumineux (max 500 MB).', level='warning', status=422)

    filename  = secure_filename(file.filename)
    ts        = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique    = f'processed_{order_id}_{ts}_{filename}'

    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    disk_path = config.MIXMASTER_PROCESSED_FOLDER / unique
    file.save(disk_path)
    filepath  = Path('db_assets', 'mixmaster', 'processed', unique).as_posix()

    try:
        audio        = AudioSegment.from_file(disk_path)
        duration_ms  = len(audio)
        audio_format = filename.rsplit('.', 1)[1].lower()

        config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)

        preview_half      = audio[:duration_ms // 2]
        preview_name      = f'preview_{order_id}_{ts}_{filename}'
        preview_disk      = config.MIXMASTER_PREVIEWS_FOLDER / preview_name
        preview_half.export(preview_disk, format=audio_format)
        preview_path      = Path('db_assets', 'mixmaster', 'previews', preview_name).as_posix()

        preview_full_deg  = _generate_telephone_preview(audio)
        preview_full_name = f'preview_full_{order_id}_{ts}_{filename}'
        preview_full_disk = config.MIXMASTER_PREVIEWS_FOLDER / preview_full_name
        preview_full_deg.export(preview_full_disk, format=audio_format)
        preview_full_path = Path('db_assets', 'mixmaster', 'previews', preview_full_name).as_posix()

    except Exception as e:
        current_app.logger.error(f'Erreur pydub upload #{order_id}: {e}', exc_info=True)
        if disk_path.exists(): disk_path.unlink()
        return ser_err(f'Erreur traitement audio : {str(e)}', status=500)

    if not order.stripe_payment_intent_id or order.stripe_payment_status != 'captured':
        current_app.logger.error(f'Stripe status incorrect pour #{order_id}: {order.stripe_payment_status}')
        return ser_err('Statut de paiement incorrect.')

    try:
        log_stripe_payment_intent_captured(
            payment_intent_id=order.stripe_payment_intent_id,
            amount=int(float(order.total_price) * 100),
            resource_type='mixmaster',
            resource_id=order_id,
            engineer_id=order.engineer_id,
            artist_id=order.artist_id,
            capture_type='delivery_deposit_30_percent',
        )

        from utils.wallet_service import credit_wallet_for_mixmaster_deposit
        credit_wallet_for_mixmaster_deposit(order)

        order.processed_file              = filepath
        order.processed_file_preview      = preview_path
        order.processed_file_preview_full = preview_full_path
        order.status                      = 'delivered'
        order.delivered_at                = datetime.now()
        order.stripe_payment_status       = 'deposit_captured'

        notify_mixmaster_status_changed(order, 'accepted', 'delivered')
        db.session.commit()

        try:
            email_service.send_mixmaster_status_update_email(order, 'accepted', 'delivered')
        except Exception as e:
            current_app.logger.warning(f'Email delivered #{order_id}: {e}')

        deposit_net = round(float(order.deposit_amount) * 0.90, 2)
        return ok(
            {'status': order.status},
            message=f'Livraison effectuée ! Acompte de {deposit_net}€ crédité dans vos gains (disponible dans 7 jours).',
        )

    except Exception as e:
        current_app.logger.error(f'credit_wallet delivery #{order_id}: {e}', exc_info=True)
        for p in [disk_path, preview_disk, preview_full_disk]:
            if p.exists(): p.unlink()
        return ser_err('Erreur lors de la livraison.', status=500)


@cud_mixmaster_engineer_api_bp.route('/deliver-revision/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def deliver_revision(order_id, current_user):
    """L'ingénieur livre le fichier révisé (pas de nouveau paiement Stripe)."""
    order = _get_order_for_engineer(order_id, current_user.id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status not in ('revision1', 'revision2'):
        return ser_err('Aucune révision en attente.', level='warning')

    if not VALIDATION_AVAILABLE:
        return ser_err('Validation sécurité indisponible.', status=500)

    file = request.files.get('processed_file')
    if not file or file.filename == '':
        return ser_err('Aucun fichier sélectionné.', level='warning')

    if not _allowed(file.filename, {'wav', 'mp3'}):
        return ser_err('Format non autorisé (.wav ou .mp3).', level='warning', status=422)

    is_valid, validation_err = validate_audio_file(file)
    if not is_valid:
        return ser_err(f'Fichier invalide : {validation_err}', level='warning', status=422)

    if not _check_size(file):
        return ser_err('Fichier trop volumineux (max 500 MB).', level='warning', status=422)

    filename  = secure_filename(file.filename)
    ts        = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique    = f'rev{order.revision_count}_{order_id}_{ts}_{filename}'

    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    disk_path = config.MIXMASTER_PROCESSED_FOLDER / unique
    file.save(disk_path)
    filepath  = Path('db_assets', 'mixmaster', 'processed', unique).as_posix()

    try:
        audio        = AudioSegment.from_file(disk_path)
        duration_ms  = len(audio)
        audio_format = filename.rsplit('.', 1)[1].lower()

        config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)

        preview_half   = audio[:duration_ms // 2]
        prev_name      = f'preview_rev{order.revision_count}_{order_id}_{ts}_{filename}'
        prev_disk      = config.MIXMASTER_PREVIEWS_FOLDER / prev_name
        preview_half.export(prev_disk, format=audio_format)
        prev_path      = Path('db_assets', 'mixmaster', 'previews', prev_name).as_posix()

        prev_full_deg  = _generate_telephone_preview(audio)
        prev_full_name = f'preview_full_rev{order.revision_count}_{order_id}_{ts}_{filename}'
        prev_full_disk = config.MIXMASTER_PREVIEWS_FOLDER / prev_full_name
        prev_full_deg.export(prev_full_disk, format=audio_format)
        prev_full_path = Path('db_assets', 'mixmaster', 'previews', prev_full_name).as_posix()

    except Exception as e:
        current_app.logger.error(f'Erreur pydub revision #{order_id}: {e}', exc_info=True)
        if disk_path.exists(): disk_path.unlink()
        return ser_err(f'Erreur traitement audio : {str(e)}', status=500)

    old_status = order.status

    if order.revision_count == 1:
        order.processed_file_revision1 = filepath
        order.revision1_delivered_at   = datetime.now()
    else:
        order.processed_file_revision2 = filepath
        order.revision2_delivered_at   = datetime.now()

    order.processed_file              = filepath
    order.processed_file_preview      = prev_path
    order.processed_file_preview_full = prev_full_path
    order.status                      = 'delivered'
    order.delivered_at                = datetime.now()
    order.stripe_payment_status       = 'deposit_captured'

    notify_mixmaster_status_changed(order, old_status, 'delivered')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, old_status, 'delivered')
    except Exception as e:
        current_app.logger.warning(f'Email revision delivered #{order_id}: {e}')

    return ok({'status': order.status}, message=f'Révision {order.revision_count} livrée !')
