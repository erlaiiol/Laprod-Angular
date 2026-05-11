"""
CUD Mixmaster — Actions artiste (commander, annuler, révision, valider/télécharger).
La commande crée une session Stripe Checkout et renvoie checkout_url.
L'URL de succès Stripe pointe vers la page Angular /mix/payment-success.
"""
from flask import Blueprint, request, current_app, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy import select
from extensions import db, csrf, limiter
from models import User, MixMasterRequest
from serializers import ok, err as ser_err
from helpers import sanitize_html
from utils.notification_service import notify_mixmaster_status_changed, notify_mixmaster_request_received_and_sent
from utils import email_service
from utils.stripe_logger import (
    log_stripe_checkout_session_created, log_stripe_transaction, log_stripe_error,
)
from utils.archive_utils import get_archive_file_tree
from utils.payment_validator import MixMasterRequestPriceCalculator
import stripe
import stripe._error as stripe_error
from datetime import datetime
from pathlib import Path
import config

try:
    from utils.file_validator import validate_stems_archive, validate_audio_file
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

cud_mixmaster_artist_api_bp = Blueprint(
    'cud_mixmaster_artist_api', __name__, url_prefix='/api/mixmaster-artist'
)

MAX_FILE_SIZE = 500 * 1024 * 1024


def _check_size(f) -> bool:
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size <= MAX_FILE_SIZE


def _allowed(filename: str, exts: set) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in exts


def _get_order_for_artist(order_id: int, user_id: int) -> MixMasterRequest | None:
    order = db.session.get(MixMasterRequest, order_id)
    if not order or order.artist_id != user_id:
        return None
    return order


# ─── Passer une commande (multipart) ─────────────────────────────────────────

@cud_mixmaster_artist_api_bp.route('/order/<int:engineer_id>', methods=['POST'])
@limiter.limit('10 per hour')
@jwt_required()
@csrf.exempt
def create_order(engineer_id):
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
    user_id  = int(get_jwt_identity())
    user     = db.get_or_404(User, user_id)
    engineer = db.get_or_404(User, engineer_id)

    if user_id == engineer_id:
        return ser_err('Vous ne pouvez pas commander un mix/master à vous-même.', status=403)

    if not engineer.is_mixmaster_engineer:
        return ser_err("Cet ingénieur n'est pas certifié.")

    active_count = MixMasterRequest.get_active_requests_count(engineer_id)
    if active_count >= 5:
        return ser_err(f'{engineer.username} a déjà 5 mix en cours.', level='warning')

    if not VALIDATION_AVAILABLE:
        return ser_err('Validation sécurité indisponible.', status=500)

    # ── Fichiers ─────────────────────────────────────────────────────────────
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

    # ── Champs de formulaire ─────────────────────────────────────────────────
    def bval(key): return request.form.get(key, '0') == '1'

    title                = sanitize_html(request.form.get('title', '').strip()) or f'Mix/Master #{user_id}'
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

    # Appliquer services obligatoires selon le palier minimum de l'engineer.
    # Paliers : 35% = nettoyage, 55% = nettoyage+mastering, 80% = nettoyage+effets,
    #           100% = nettoyage+effets+mastering, 160% = tout+artistique.
    if engineer.mixmaster_reference_price and engineer.mixmaster_price_min:
        min_pct = (engineer.mixmaster_price_min / engineer.mixmaster_reference_price) * 100
        if min_pct >= 35:
            service_cleaning = True
        if 55 <= min_pct < 80:
            service_mastering = True              # palier 55% = cleaning + mastering
        if min_pct >= 80:
            service_effects = True               # palier 80% = cleaning + effects (sans mastering)
        if min_pct >= 100:
            service_mastering = True             # palier 100% = cleaning + effects + mastering
        if min_pct >= 160 and engineer.is_certified_producer_arranger:
            service_artistic = True              # palier 160% = tout + artistique

    if not any([service_cleaning, service_effects, service_artistic, service_mastering]):
        return ser_err('Sélectionnez au moins un service.', level='warning')

    # ── Calcul du prix ───────────────────────────────────────────────────────
    calculator = MixMasterRequestPriceCalculator()
    base_price, options_price, total_price = calculator.calculate_total(
        resource=engineer,
        options={'has_separated_stems': has_separated_stems},
        service_cleaning=service_cleaning,
        service_effects=service_effects,
        service_artistic=service_artistic,
        service_mastering=service_mastering,
    )

    # ── Sauvegarde des fichiers ──────────────────────────────────────────────
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    config.MIXMASTER_UPLOADS_FOLDER.mkdir(parents=True, exist_ok=True)

    stems_name   = f'{user_id}_{ts}_stems_{secure_filename(stems_file.filename)}'
    ref_name     = f'{user_id}_{ts}_ref_{secure_filename(reference_file.filename)}'
    stems_disk   = config.MIXMASTER_UPLOADS_FOLDER / stems_name
    ref_disk     = config.MIXMASTER_UPLOADS_FOLDER / ref_name
    stems_file.save(stems_disk)
    reference_file.save(ref_disk)
    stems_web = Path('db_assets', 'mixmaster', 'uploads', stems_name).as_posix()
    ref_web   = Path('db_assets', 'mixmaster', 'uploads', ref_name).as_posix()

    archive_file_tree = get_archive_file_tree(str(stems_disk))

    # ── Session Stripe Checkout ──────────────────────────────────────────────
    metadata = {
        'type':              'mixmaster',
        'artist_id':         str(user_id),
        'artist_username':   user.username,
        'artist_email':      user.email,
        'engineer_id':       str(engineer_id),
        'engineer_username': engineer.username,
        'stems_file':        stems_web,
        'reference_file':    ref_web,
        'archive_file_tree': str(archive_file_tree)[:500] if archive_file_tree else '',
        'service_cleaning':  str(service_cleaning),
        'service_effects':   str(service_effects),
        'service_artistic':  str(service_artistic),
        'service_mastering': str(service_mastering),
        'has_separated_stems': str(has_separated_stems),
        'artist_message':    (artist_message or '')[:2000],
        'brief_vocals':      (brief_vocals or '')[:500],
        'brief_backing_vocals': (brief_backing_vocals or '')[:500],
        'brief_ambiance':    (brief_ambiance or '')[:500],
        'brief_bass':        (brief_bass or '')[:500],
        'brief_energy_style': (brief_energy_style or '')[:500],
        'brief_references':  (brief_references or '')[:500],
        'brief_instruments': (brief_instruments or '')[:500],
        'brief_percussion':  (brief_percussion or '')[:500],
        'brief_effects_brief': (brief_effects or '')[:500],
        'brief_structure':   (brief_structure or '')[:500],
        'title':             title[:50],
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
                            'Effets' if service_effects else '',
                            'Artistique' if service_artistic else '',
                            'Mastering' if service_mastering else '',
                        ])),
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            payment_intent_data={
                'capture_method': 'automatic',  # Débit immédiat ; la plateforme gère les reversements par paliers
                'metadata': metadata,
            },
            success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}' if success_url else request.url_root.rstrip('/') + '/mix/payment-success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=cancel_url or request.url_root.rstrip('/') + f'/mix/order/{engineer_id}',
            customer_email=user.email,
            metadata=metadata,
        )

        log_stripe_checkout_session_created(
            session_id=checkout_session.id,
            amount=int(total_price * 100),
            resource_type='mixmaster',
            resource_id='pending',
            engineer_id=engineer_id,
            artist_id=user_id,
        )

        return ok({'checkout_url': checkout_session.url})

    except stripe_error.StripeError as e:
        log_stripe_error(operation='create_mixmaster_checkout', error_message=str(e),
                         resource_type='mixmaster', engineer_id=engineer_id, artist_id=user_id)
        for p in [stems_disk, ref_disk]:
            if p.exists(): p.unlink()
        return ser_err(f'Erreur Stripe : {str(e)}', status=502)


# ─── Annuler une demande ──────────────────────────────────────────────────────

@cud_mixmaster_artist_api_bp.route('/cancel/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def cancel_order(order_id):
    """Annule la demande avant acceptation par l'ingénieur. Rembourse l'artiste via Stripe Refund."""
    user_id = int(get_jwt_identity())
    order   = _get_order_for_artist(order_id, user_id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'awaiting_acceptance':
        return ser_err('Cette demande ne peut plus être annulée.', level='warning')

    # capture_method=automatic : le paiement est already succeeded → remboursement par Refund
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


# ─── Demander une révision ────────────────────────────────────────────────────

@cud_mixmaster_artist_api_bp.route('/revision/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def request_revision(order_id):
    """L'artiste demande une révision. Crédite wallet de l'ingénieur (10% net)."""
    user_id = int(get_jwt_identity())
    order   = _get_order_for_artist(order_id, user_id)
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
        order.status                  = 'revision1'
        order.revision1_message       = revision_message
        order.revision1_requested_at  = datetime.now()
        order.stripe_payment_status   = 'partially_captured'
    else:
        order.status                  = 'revision2'
        order.revision2_message       = revision_message
        order.revision2_requested_at  = datetime.now()

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


# ─── Refuser la livraison (remboursement partiel) ────────────────────────────

@cud_mixmaster_artist_api_bp.route('/reject-delivery/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def reject_delivery(order_id):
    """
    L'artiste refuse la livraison après écoute des previews (avant toute validation).
    L'ingénieur conserve les acomptes déjà crédités dans son wallet.
    Remboursement partiel Stripe (solde brut restant) :
      - 0 révision  → 70% du total remboursé
      - 1 révision  → 60% du total remboursé
      - 2 révisions → 50% du total remboursé
    Aucun remboursement possible si status = 'completed' (artiste a déjà validé).
    """
    user_id = int(get_jwt_identity())
    order   = _get_order_for_artist(order_id, user_id)
    if not order:
        return ser_err('Commande introuvable ou accès refusé.', status=404)

    if order.status != 'delivered':
        return ser_err('Cette commande ne peut pas être refusée dans son état actuel.', level='warning')

    if order.stripe_payment_status != 'deposit_captured':
        return ser_err('Statut de paiement incorrect.', level='warning')

    refund_amount = order.get_refund_amount()  # toujours > 0 : 70/60/50% selon révisions

    try:
        stripe.Refund.create(
            payment_intent=order.stripe_payment_intent_id,
            amount=int(round(refund_amount * 100)),  # centimes
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


# ─── Valider et télécharger ───────────────────────────────────────────────────

@cud_mixmaster_artist_api_bp.route('/approve/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def approve_and_download(order_id):
    """
    L'artiste valide la livraison.
    Crédite le wallet engineer pour le solde final.
    Renvoie l'URL de téléchargement du fichier final.
    """
    user_id = int(get_jwt_identity())
    order   = _get_order_for_artist(order_id, user_id)
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
def download_file(order_id):
    """Téléchargement sécurisé du fichier final (JWT + artist ownership + status completed)."""
    user_id = int(get_jwt_identity())
    order   = _get_order_for_artist(order_id, user_id)
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
