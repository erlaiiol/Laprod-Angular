"""
CUD Mixmaster — Actions ingénieur (accept, reject, upload processed, deliver revision)
Toutes les routes requièrent JWT + rôle mix_engineer + ownership de la commande.
"""
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy import select
from extensions import db, csrf
from models import User, MixMasterRequest
from utils.notification_service import notify_mixmaster_status_changed
from utils import email_service
from utils.stripe_validator import verify_stripe_payment_for_capture
from utils.stripe_logger import (
    log_stripe_payment_intent_captured, log_stripe_error,
)
import stripe
import stripe._error as stripe_error
from datetime import datetime, timedelta
from pathlib import Path
from pydub import AudioSegment
from pydub import scipy_effects
import config

try:
    from utils.file_validator import validate_audio_file
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

cud_mixmaster_engineer_api_bp = Blueprint(
    'cud_mixmaster_engineer_api', __name__, url_prefix='/mixmaster-engineer'
)

ALLOWED_AUDIO_EXTENSIONS = {'wav', 'mp3'}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB


def _allowed_audio(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS


def _check_size(f) -> bool:
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    return size <= MAX_FILE_SIZE


def _get_order_for_engineer(order_id: int, user_id: int) -> MixMasterRequest | None:
    order = db.session.get(MixMasterRequest, order_id)
    if not order or order.engineer_id != user_id:
        return None
    return order


def _generate_telephone_preview(audio_segment: AudioSegment) -> AudioSegment:
    filtered = audio_segment.high_pass_filter(120)
    filtered = filtered.low_pass_filter(10000)
    return filtered


# ─── Accept ───────────────────────────────────────────────────────────────────

@cud_mixmaster_engineer_api_bp.route('/accept/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def accept_order(order_id):
    user_id = int(get_jwt_identity())
    order = _get_order_for_engineer(order_id, user_id)
    if not order:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Commande introuvable ou accès refusé.'}}), 404

    if order.status != 'awaiting_acceptance':
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Cette commande a déjà été traitée.'}}), 400

    if not MixMasterRequest.can_accept_more_requests(user_id):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Vous avez déjà 5 mix/master en cours.'}}), 400

    order.status      = 'accepted'
    order.accepted_at = datetime.now()
    order.deadline    = datetime.now() + timedelta(days=7)

    notify_mixmaster_status_changed(order, 'awaiting_acceptance', 'accepted')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, 'awaiting_acceptance', 'accepted')
    except Exception as e:
        current_app.logger.warning(f'Email accept #{order_id}: {e}')

    return jsonify({
        'success': True,
        'feedback': {'level': 'success', 'message': 'Demande acceptée ! Vous avez 7 jours pour livrer.'},
        'data': {'status': order.status, 'deadline': order.deadline.isoformat()},
    }), 200


# ─── Reject ───────────────────────────────────────────────────────────────────

@cud_mixmaster_engineer_api_bp.route('/reject/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def reject_order(order_id):
    user_id = int(get_jwt_identity())
    order = _get_order_for_engineer(order_id, user_id)
    if not order:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Commande introuvable ou accès refusé.'}}), 404

    if order.status != 'awaiting_acceptance':
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Cette commande a déjà été traitée.'}}), 400

    # Supprimer le fichier original
    if order.original_file:
        original_path = Path(current_app.root_path) / order.original_file
        if original_path.exists():
            original_path.unlink()

    order.status      = 'rejected'
    order.rejected_at = datetime.now()

    notify_mixmaster_status_changed(order, 'awaiting_acceptance', 'rejected')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, 'awaiting_acceptance', 'rejected')
    except Exception as e:
        current_app.logger.warning(f'Email reject #{order_id}: {e}')

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': 'Demande refusée.'},
    }), 200


# ─── Upload processed (livraison initiale) ────────────────────────────────────

@cud_mixmaster_engineer_api_bp.route('/upload/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def upload_processed(order_id):
    """L'ingénieur livre le fichier traité. Capture Stripe 100% + acompte wallet."""
    user_id = int(get_jwt_identity())
    order   = _get_order_for_engineer(order_id, user_id)
    if not order:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Commande introuvable ou accès refusé.'}}), 404

    if order.status not in ('accepted', 'processing'):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Cette commande ne peut plus être modifiée.'}}), 400

    if not VALIDATION_AVAILABLE:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Validation sécurité indisponible.'}}), 500

    file = request.files.get('processed_file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Aucun fichier sélectionné.'}}), 400

    if not _allowed_audio(file.filename):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Format non autorisé (.wav ou .mp3).'}}), 422

    is_valid, err = validate_audio_file(file)
    if not is_valid:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': f'Fichier invalide : {err}'}}), 422

    if not _check_size(file):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Fichier trop volumineux (max 500 MB).'}}), 422

    # ── Sauvegarde ──────────────────────────────────────────────────────────
    filename = secure_filename(file.filename)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique   = f'processed_{order_id}_{ts}_{filename}'

    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    disk_path = config.MIXMASTER_PROCESSED_FOLDER / unique
    file.save(disk_path)
    filepath = Path('static', 'mixmaster', 'processed', unique).as_posix()

    # ── Génération des previews (pydub) ─────────────────────────────────────
    try:
        audio        = AudioSegment.from_file(disk_path)
        duration_ms  = len(audio)
        audio_format = filename.rsplit('.', 1)[1].lower()

        config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)

        preview_half          = audio[:duration_ms // 2]
        preview_name          = f'preview_{order_id}_{ts}_{filename}'
        preview_disk          = config.MIXMASTER_PREVIEWS_FOLDER / preview_name
        preview_half.export(preview_disk, format=audio_format)
        preview_path          = Path('static', 'mixmaster', 'previews', preview_name).as_posix()

        preview_full_deg      = _generate_telephone_preview(audio)
        preview_full_name     = f'preview_full_{order_id}_{ts}_{filename}'
        preview_full_disk     = config.MIXMASTER_PREVIEWS_FOLDER / preview_full_name
        preview_full_deg.export(preview_full_disk, format=audio_format)
        preview_full_path     = Path('static', 'mixmaster', 'previews', preview_full_name).as_posix()

    except Exception as e:
        current_app.logger.error(f'Erreur pydub upload #{order_id}: {e}', exc_info=True)
        if disk_path.exists():
            disk_path.unlink()
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Erreur traitement audio : {str(e)}'}}), 500

    # ── Capture Stripe 100% ─────────────────────────────────────────────────
    if not order.stripe_payment_intent_id or order.stripe_payment_status != 'authorized':
        current_app.logger.error(f'Stripe status incorrect pour #{order_id}: {order.stripe_payment_status}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Statut de paiement incorrect.'}}), 400

    try:
        capture = stripe.PaymentIntent.capture(order.stripe_payment_intent_id)

        log_stripe_payment_intent_captured(
            payment_intent_id=order.stripe_payment_intent_id,
            amount=capture.amount,
            resource_type='mixmaster',
            resource_id=order_id,
            engineer_id=order.engineer_id,
            artist_id=order.artist_id,
            capture_type='full_capture_100_percent',
        )

        from utils.wallet_service import credit_wallet_for_mixmaster_deposit
        credit_wallet_for_mixmaster_deposit(order)

        order.processed_file                = filepath
        order.processed_file_preview        = preview_path
        order.processed_file_preview_full   = preview_full_path
        order.status                        = 'delivered'
        order.delivered_at                  = datetime.now()
        order.stripe_payment_status         = 'deposit_captured'

        notify_mixmaster_status_changed(order, 'accepted', 'delivered')
        db.session.commit()

        try:
            email_service.send_mixmaster_status_update_email(order, 'accepted', 'delivered')
        except Exception as e:
            current_app.logger.warning(f'Email delivered #{order_id}: {e}')

        deposit_net = round(float(order.deposit_amount) * 0.90, 2)
        return jsonify({
            'success': True,
            'feedback': {'level': 'success', 'message': f'Livraison effectuée ! Acompte de {deposit_net}€ crédité dans vos gains (disponible dans 7 jours).'},
            'data': {'status': order.status},
        }), 200

    except stripe_error.StripeError as e:
        log_stripe_error(operation='capture_for_delivery', error_message=str(e),
                         resource_type='mixmaster', resource_id=order_id)
        for p in [disk_path, preview_disk, preview_full_disk]:
            if p.exists():
                p.unlink()
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Erreur Stripe : {str(e)}'}}), 502


# ─── Deliver revision ─────────────────────────────────────────────────────────

@cud_mixmaster_engineer_api_bp.route('/deliver-revision/<int:order_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def deliver_revision(order_id):
    """L'ingénieur livre le fichier révisé (pas de nouveau paiement Stripe)."""
    user_id = int(get_jwt_identity())
    order   = _get_order_for_engineer(order_id, user_id)
    if not order:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Commande introuvable ou accès refusé.'}}), 404

    if order.status not in ('revision1', 'revision2'):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Aucune révision en attente.'}}), 400

    if not VALIDATION_AVAILABLE:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Validation sécurité indisponible.'}}), 500

    file = request.files.get('processed_file')
    if not file or file.filename == '':
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Aucun fichier sélectionné.'}}), 400

    if not _allowed_audio(file.filename):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Format non autorisé (.wav ou .mp3).'}}), 422

    is_valid, err = validate_audio_file(file)
    if not is_valid:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': f'Fichier invalide : {err}'}}), 422

    if not _check_size(file):
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Fichier trop volumineux (max 500 MB).'}}), 422

    filename = secure_filename(file.filename)
    ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique   = f'rev{order.revision_count}_{order_id}_{ts}_{filename}'

    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    disk_path = config.MIXMASTER_PROCESSED_FOLDER / unique
    file.save(disk_path)
    filepath = Path('static', 'mixmaster', 'processed', unique).as_posix()

    try:
        audio        = AudioSegment.from_file(disk_path)
        duration_ms  = len(audio)
        audio_format = filename.rsplit('.', 1)[1].lower()

        config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)

        preview_half     = audio[:duration_ms // 2]
        prev_name        = f'preview_rev{order.revision_count}_{order_id}_{ts}_{filename}'
        prev_disk        = config.MIXMASTER_PREVIEWS_FOLDER / prev_name
        preview_half.export(prev_disk, format=audio_format)
        prev_path        = Path('static', 'mixmaster', 'previews', prev_name).as_posix()

        prev_full_deg    = _generate_telephone_preview(audio)
        prev_full_name   = f'preview_full_rev{order.revision_count}_{order_id}_{ts}_{filename}'
        prev_full_disk   = config.MIXMASTER_PREVIEWS_FOLDER / prev_full_name
        prev_full_deg.export(prev_full_disk, format=audio_format)
        prev_full_path   = Path('static', 'mixmaster', 'previews', prev_full_name).as_posix()

    except Exception as e:
        current_app.logger.error(f'Erreur pydub revision #{order_id}: {e}', exc_info=True)
        if disk_path.exists():
            disk_path.unlink()
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Erreur traitement audio : {str(e)}'}}), 500

    old_status = order.status

    if order.revision_count == 1:
        order.processed_file_revision1  = filepath
        order.revision1_delivered_at    = datetime.now()
    else:
        order.processed_file_revision2  = filepath
        order.revision2_delivered_at    = datetime.now()

    order.processed_file              = filepath
    order.processed_file_preview      = prev_path
    order.processed_file_preview_full = prev_full_path
    order.status                      = 'delivered'
    order.delivered_at                = datetime.now()

    notify_mixmaster_status_changed(order, old_status, 'delivered')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(order, old_status, 'delivered')
    except Exception as e:
        current_app.logger.warning(f'Email revision delivered #{order_id}: {e}')

    return jsonify({
        'success': True,
        'feedback': {'level': 'success', 'message': f'Révision {order.revision_count} livrée !'},
        'data': {'status': order.status},
    }), 200
