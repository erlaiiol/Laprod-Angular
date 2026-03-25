"""
Routes pour le module Mix/Master
"""
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, send_file, jsonify, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from extensions import db, limiter
from models import User, MixMasterRequest
from helpers import admin_required, sanitize_html
from utils import email_service
from utils.archive_utils import get_archive_file_tree, check_file_naming_convention
from utils.notification_service import notify_mixmaster_request_received_and_sent, notify_mixmaster_status_changed
from utils.ownership_authorizer import MixMasterArtistBuyerOwnership, MixMasterEngineerSellerOwnership, requires_ownership
from utils.payment_validator import validate_payment, MixMasterRequestPriceCalculator
from utils.stripe_validator import verify_stripe_payment_for_capture, verify_stripe_payment_for_download, verify_stripe_payment_for_refund
from utils.stripe_logger import (
    log_stripe_transaction,
    log_stripe_checkout_session_created,
    log_stripe_payment_intent_created,
    log_stripe_payment_intent_captured,
    log_stripe_payment_intent_succeeded,
    log_stripe_refund_created,
    log_stripe_transfer_reversal_created,
    log_stripe_error
)
import os
import stripe
import stripe._error as stripe_error
from datetime import datetime, timedelta
from pydub import AudioSegment
from pydub import scipy_effects
import io
from pathlib import Path
import config

# Imports pour validation MIME type
try:
    from utils.file_validator import validate_archive_file, validate_audio_file
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

mixmaster_bp = Blueprint('mixmaster', __name__, url_prefix='/mixmaster')

# Configuration sécurité
# Note: Stripe API key est configurée dans extensions.py via init_extensions()
ALLOWED_AUDIO_EXTENSIONS = {'wav', 'mp3', 'zip', 'rar'}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


def generate_telephone_preview(audio_segment):
    """
    Génère une preview 'téléphone' : basses coupées à 60Hz, aigus coupés à 13kHz.
    L'artiste peut écouter le titre en entier mais en qualité dégradée,
    pour vérifier les effets/constructions sans pouvoir voler le fichier final.

    Args:
        audio_segment: AudioSegment (pydub) du fichier complet

    Returns:
        AudioSegment: Version filtrée (entière, qualité réduite)
    """
    # Hi-pass 120Hz : coupe les sub-basses (kick, 808, etc.)
    filtered = audio_segment.high_pass_filter(120)
    # Lo-pass 10kHz : coupe les aigus (air, brillance, cymbales hautes)
    filtered = filtered.low_pass_filter(10000)
    return filtered


def allowed_file(filename, allowed_extensions):
    """Vérifie si l'extension du fichier est autorisée"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def validate_file_size(file):
    """Vérifie la taille du fichier"""
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)  # Retourner au début
    return size <= MAX_FILE_SIZE


@mixmaster_bp.route('/engineers')
@login_required
def engineers_list():
    """Page listant tous les engineers certifiés"""
    engineers = db.session.query(User).filter_by(is_mixmaster_engineer=True).all()
    return render_template('mixmaster_engineers.html', engineers=engineers)


@mixmaster_bp.route('/upload/<int:engineer_id>', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
@login_required
@validate_payment(MixMasterRequestPriceCalculator, 'mixmaster', 'engineer_id')
def upload_to_engineer(engineer_id, resource=None, validated_prices=None):
    """Page d'upload de fichier vers un engineer spécifique"""
    # Si le décorateur a été appliqué, resource contient l'engineer
    # Sinon (GET request), on le récupère manuellement
    engineer = resource if resource else db.get_or_404(User, engineer_id)

    if not engineer.is_mixmaster_engineer:
        flash('Cet utilisateur n\'est pas un mix/master engineer certifié.', 'danger')
        return redirect(url_for('mixmaster.engineers_list'))

    # Vérifier si l'engineer a atteint sa limite de 5 mix/master en cours
    active_count = MixMasterRequest.get_active_requests_count(engineer_id)
    if active_count >= 5:
        flash(f'{engineer.username} a déjà 5 mix/master en cours. Veuillez attendre qu\'il termine l\'un d\'eux.', 'warning')
        return redirect(url_for('mixmaster.engineers_list'))

    if request.method == 'POST':
        # Récupérer toutes les données du formulaire au début pour pouvoir les renvoyer en cas d'erreur
        # Note: Les checkboxes avec value="xxx" envoient leur value, pas 'on'
        # On vérifie simplement la présence de la clé dans request.form
        #  SÉCURITÉ : Nettoyer tous les champs de texte libre pour éviter XSS
        form_data = {
            'title': request.form.get('title', '').strip(),
            'service_cleaning': 'service_cleaning' in request.form,
            'service_effects': 'service_effects' in request.form,
            'service_artistic': 'service_artistic' in request.form,
            'service_mastering': 'service_mastering' in request.form,
            'has_separated_stems': 'has_separated_stems' in request.form,
            'artist_message': sanitize_html(request.form.get('artist_message', '').strip()),
            'brief_vocals': sanitize_html(request.form.get('brief_vocals', '').strip()),
            'brief_backing_vocals': sanitize_html(request.form.get('brief_backing_vocals', '').strip()),
            'brief_ambiance': sanitize_html(request.form.get('brief_ambiance', '').strip()),
            'brief_bass': sanitize_html(request.form.get('brief_bass', '').strip()),
            'brief_energy_style': sanitize_html(request.form.get('brief_energy_style', '').strip()),
            'brief_references': sanitize_html(request.form.get('brief_references', '').strip()),
            'brief_instruments': sanitize_html(request.form.get('brief_instruments', '').strip()),
            'brief_percussion': sanitize_html(request.form.get('brief_percussion', '').strip()),
            'brief_effects': sanitize_html(request.form.get('brief_effects', '').strip()),
            'brief_structure': sanitize_html(request.form.get('brief_structure', '').strip())
        }

        def _rerender():
            return render_template('mixmaster_upload.html', engineer=engineer, form_data=form_data)

        # Vérifier que les 2 fichiers ont été envoyés
        if 'stems_file' not in request.files or 'reference_file' not in request.files:
            flash('Vous devez envoyer les 2 fichiers : piste par piste (.zip) et maquette/référence.', 'danger')
            return _rerender()

        stems_file = request.files['stems_file']
        reference_file = request.files['reference_file']

        if stems_file.filename == '' or reference_file.filename == '':
            flash('Les 2 fichiers sont requis.', 'danger')
            return _rerender()

        # ============================================
        # VALIDATION SÉCURISÉE DES FICHIERS
        # ============================================

        #  SÉCURITÉ CRITIQUE: python-magic est OBLIGATOIRE pour éviter les uploads malveillants
        if not VALIDATION_AVAILABLE:
            flash('Erreur serveur: validation de sécurité non disponible. Contactez l\'administrateur.', 'error')
            current_app.logger.error('CRITIQUE: Validation mime-type via python-magic indisponible')
            abort(500)

        # Vérifier l'extension du fichier piste par piste
        if not allowed_file(stems_file.filename, {'zip', 'rar'}):
            flash('Le fichier piste par piste doit être au format .zip ou .rar', 'danger')
            return _rerender()

        # 1. Valider le MIME type de l'archive stems (ZIP/RAR)
        is_valid, error_message = validate_archive_file(stems_file)
        if not is_valid:
            flash(f' Archive stems invalide : {error_message}', 'danger')
            return _rerender()

        # Vérifier l'extension de la maquette
        if not allowed_file(reference_file.filename, {'wav', 'mp3'}):
            flash('La maquette doit être au format .wav ou .mp3', 'danger')
            return _rerender()

        # 2. Valider le MIME type du fichier de référence (audio)
        is_valid, error_message = validate_audio_file(reference_file)
        if not is_valid:
            flash(f' Fichier de référence invalide : {error_message}', 'danger')
            return _rerender()

        # Vérifier la taille des fichiers
        if not validate_file_size(stems_file) or not validate_file_size(reference_file):
            flash('Un des fichiers est trop volumineux. Maximum 500MB par fichier.', 'danger')
            return _rerender()

        # Récupérer les services sélectionnés depuis form_data
        service_cleaning = form_data['service_cleaning']
        service_effects = form_data['service_effects']
        service_artistic = form_data['service_artistic']
        service_mastering = form_data['service_mastering']
        has_separated_stems = form_data['has_separated_stems']
        artist_message = form_data['artist_message']

        # Récupérer le briefing détaillé (tous facultatifs)
        brief_vocals = form_data['brief_vocals'] or None
        brief_backing_vocals = form_data['brief_backing_vocals'] or None
        brief_ambiance = form_data['brief_ambiance'] or None
        brief_bass = form_data['brief_bass'] or None
        brief_energy_style = form_data['brief_energy_style'] or None
        brief_references = form_data['brief_references'] or None
        brief_instruments = form_data['brief_instruments'] or None
        brief_percussion = form_data['brief_percussion'] or None
        brief_effects = form_data['brief_effects'] or None
        brief_structure = form_data['brief_structure'] or None

        # Calculer les services obligatoires basés sur le prix minimum
        price_max = engineer.mixmaster_reference_price or 100
        price_min = engineer.mixmaster_price_min or 20
        min_percent = (price_min / price_max) * 100

        mandatory_cleaning = min_percent >= 20
        mandatory_effects = min_percent >= 50
        mandatory_mastering = min_percent >= 65

        # Appliquer les services obligatoires (forcer à True s'ils sont obligatoires)
        service_cleaning = service_cleaning or mandatory_cleaning
        service_effects = service_effects or mandatory_effects
        service_mastering = service_mastering or mandatory_mastering

        # Vérifier qu'au moins un service est sélectionné (devrait toujours être vrai maintenant)
        if not any([service_cleaning, service_effects, service_artistic, service_mastering]):
            flash('Vous devez sélectionner au moins un service.', 'danger')
            return _rerender()

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Utiliser le dossier défini dans config.py
        config.MIXMASTER_UPLOADS_FOLDER.mkdir(parents=True, exist_ok=True)

        # Sauvegarder le fichier piste par piste
        stems_filename = secure_filename(stems_file.filename)
        unique_stems_filename = f"{current_user.id}_{timestamp}_stems_{stems_filename}"
        stems_disk_path = config.MIXMASTER_UPLOADS_FOLDER / unique_stems_filename
        stems_file.save(stems_disk_path)

        # Chemin web relatif pour la BDD (as_posix() force les / même sur Windows)
        stems_web_path = Path('static', 'mixmaster', 'uploads', unique_stems_filename).as_posix()

        # Sauvegarder la maquette
        reference_filename = secure_filename(reference_file.filename)
        unique_reference_filename = f"{current_user.id}_{timestamp}_ref_{reference_filename}"
        reference_disk_path = config.MIXMASTER_UPLOADS_FOLDER / unique_reference_filename
        reference_file.save(reference_disk_path)

        # Chemin web relatif pour la BDD (as_posix() force les / même sur Windows)
        reference_web_path = Path('static', 'mixmaster', 'uploads', unique_reference_filename).as_posix()

        # Extraire l'arborescence des fichiers de l'archive
        archive_file_tree = get_archive_file_tree(str(stems_disk_path))

        #  SÉCURITÉ : Utiliser le prix validé par le décorateur
        # Le décorateur a déjà comparé le prix client avec le calcul serveur
        if validated_prices:
            # Prix validé par @validate_payment (POST avec total_price)
            total_price = validated_prices['total_price']
            base_price = validated_prices['base_price']
            options_price = validated_prices['options_price']
        else:
            # Fallback si pas de prix client (ne devrait jamais arriver avec le nouveau système)
            from utils.payment_validator import MixMasterRequestPriceCalculator
            calculator = MixMasterRequestPriceCalculator()
            base_price, options_price, total_price = calculator.calculate_total(
                resource=engineer,
                options={'has_separated_stems': has_separated_stems},
                service_cleaning=service_cleaning,
                service_effects=service_effects,
                service_artistic=service_artistic,
                service_mastering=service_mastering
            )

        # Créer les métadonnées pour Stripe Checkout
        metadata = {
            'type': 'mixmaster',
            'artist_id': str(current_user.id),
            'artist_username': current_user.username,
            'artist_email': current_user.email,
            'engineer_id': str(engineer_id),
            'engineer_username': engineer.username,
            'stems_file': stems_web_path,
            'reference_file': reference_web_path,
            'archive_file_tree': str(archive_file_tree)[:500] if archive_file_tree else '',  # Limité pour Stripe
            'service_cleaning': str(service_cleaning),
            'service_effects': str(service_effects),
            'service_artistic': str(service_artistic),
            'service_mastering': str(service_mastering),
            'has_separated_stems': str(has_separated_stems),
            'artist_message': (artist_message or '')[:500],  # Limité
            'brief_vocals': (brief_vocals or '')[:500],
            'brief_backing_vocals': (brief_backing_vocals or '')[:500],
            'brief_ambiance': (brief_ambiance or '')[:500],
            'brief_bass': (brief_bass or '')[:500],
            'brief_energy_style': (brief_energy_style or '')[:500],
            'brief_references': (brief_references or '')[:500],
            'brief_instruments': (brief_instruments or '')[:500],
            'brief_percussion': (brief_percussion or '')[:500],
            'brief_effects_brief': (brief_effects or '')[:500],
            'brief_structure': (brief_structure or '')[:500],
        }

        # Créer une session Stripe Checkout
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'unit_amount': int(total_price * 100),
                        'product_data': {
                            'name': f'Mix/Master par {engineer.username}',
                            'description': f'Services: {"Nettoyage, " if service_cleaning else ""}{"Effets, " if service_effects else ""}{"Artistique, " if service_artistic else ""}{"Mastering" if service_mastering else ""}',
                            'images': [request.url_root.rstrip('/') + url_for('static', filename=engineer.profile_image)],
                        },
                    },
                    'quantity': 1,
                }],
                mode='payment',
                payment_intent_data={
                    'capture_method': 'manual',  #  Capture manuelle !
                    'metadata': metadata,
                },
                success_url=request.url_root.rstrip('/') + url_for('mixmaster.payment_success') + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=request.url_root.rstrip('/') + url_for('mixmaster.upload_to_engineer', engineer_id=engineer_id),
                customer_email=current_user.email,
                metadata=metadata,
            )

            #  LOG: Checkout session créée
            log_stripe_checkout_session_created(
                session_id=checkout_session.id,
                amount=int(total_price * 100),
                resource_type='mixmaster',
                resource_id='pending',
                engineer_id=engineer_id,
                artist_id=current_user.id
            )

            return redirect(checkout_session.url, code=303)

        except stripe_error.StripeError as e:
            #  LOG: Erreur création checkout session
            log_stripe_error(
                operation='checkout_session_creation',
                error_message=str(e),
                resource_type='mixmaster',
                engineer_id=engineer_id,
                artist_id=current_user.id
            )

            # Supprimer les fichiers en cas d'erreur
            if stems_disk_path.exists():
                stems_disk_path.unlink()
            if reference_disk_path.exists():
                reference_disk_path.unlink()

            flash(f'Erreur lors de la création de la session de paiement: {str(e)}', 'danger')
            current_app.logger.error(f'Erreur creation checkout session: {str(e)}', exc_info=True)
            return _rerender()


    return render_template('mixmaster_upload.html', engineer=engineer)


@mixmaster_bp.route('/payment-success')
def payment_success():
    """Callback après succès du paiement Stripe Checkout"""
    session_id = request.args.get('session_id')

    if not session_id:
        flash('Session de paiement invalide.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    try:
        # Récupérer la session Stripe Checkout
        checkout_session = stripe.checkout.Session.retrieve(session_id)

        # Récupérer le Payment Intent
        payment_intent_id = checkout_session.payment_intent
        if not payment_intent_id:
            flash('Aucun Payment Intent trouvé.', 'danger')
            return redirect(url_for('mixmaster.dashboard'))

        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

        # Vérifier que le paiement est bien autorisé (avec capture manuelle, status = 'requires_capture')
        if payment_intent.status not in ['requires_capture', 'succeeded']:
            flash(f'Le paiement n\'a pas été confirmé (statut: {payment_intent.status}).', 'warning')
            return redirect(url_for('mixmaster.dashboard'))

        # Extraire les métadonnées
        metadata = payment_intent.metadata

        # Vérifier que c'est bien le bon utilisateur
        if int(metadata.get('artist_id')) != current_user.id:
            flash('Erreur: cette commande ne vous appartient pas.', 'danger')
            return redirect(url_for('mixmaster.dashboard'))

        # Vérifier si une demande n'existe pas déjà avec ce Payment Intent
        existing_request = db.session.query(MixMasterRequest).filter_by(
            stripe_payment_intent_id=payment_intent_id
        ).first()

        if existing_request:
            flash('Cette demande a déjà été créée.', 'info')
            return redirect(url_for('mixmaster.dashboard'))

        # Créer la demande MixMaster avec toutes les données de metadata
        mixmaster_request = MixMasterRequest(
            artist_id=int(metadata.get('artist_id')),
            engineer_id=int(metadata.get('engineer_id')),
            original_file=metadata.get('stems_file'),
            reference_file=metadata.get('reference_file'),
            service_cleaning=metadata.get('service_cleaning') == 'True',
            service_effects=metadata.get('service_effects') == 'True',
            service_artistic=metadata.get('service_artistic') == 'True',
            service_mastering=metadata.get('service_mastering') == 'True',
            has_separated_stems=metadata.get('has_separated_stems') == 'True',
            artist_message=metadata.get('artist_message', ''),
            brief_vocals=metadata.get('brief_vocals', ''),
            brief_backing_vocals=metadata.get('brief_backing_vocals', ''),
            brief_ambiance=metadata.get('brief_ambiance', ''),
            brief_bass=metadata.get('brief_bass', ''),
            brief_energy_style=metadata.get('brief_energy_style', ''),
            brief_references=metadata.get('brief_references', ''),
            brief_instruments=metadata.get('brief_instruments', ''),
            brief_percussion=metadata.get('brief_percussion', ''),
            status='awaiting_acceptance',
            stripe_payment_intent_id=payment_intent_id,
            stripe_payment_status='authorized'
        )

        # Calculer les prix et récupérer l'engineer
        engineer = db.session.get(User, mixmaster_request.engineer_id)
        mixmaster_request.total_price = mixmaster_request.calculate_service_price(engineer.mixmaster_reference_price)
        mixmaster_request.deposit_amount = round(mixmaster_request.total_price * 0.30, 2)
        mixmaster_request.remaining_amount = round(mixmaster_request.total_price - mixmaster_request.deposit_amount, 2)
        mixmaster_request.platform_fee = round(mixmaster_request.total_price * 0.10, 2)  # 10% commission plateforme
        mixmaster_request.engineer_revenue = round(mixmaster_request.total_price - mixmaster_request.platform_fee, 2)  # 90% pour l'engineer

        # Générer l'arborescence complète du fichier archive (non tronquée)
        stems_disk_path = Path(current_app.root_path) / mixmaster_request.original_file
        if stems_disk_path.exists():
            mixmaster_request.archive_file_tree = get_archive_file_tree(str(stems_disk_path))

        db.session.add(mixmaster_request)
        db.session.commit()

        #  LOG: Payment Intent autorisé (requires_capture)
        log_stripe_payment_intent_created(
            payment_intent_id=payment_intent_id,
            amount=payment_intent.amount,
            resource_type='mixmaster',
            resource_id=mixmaster_request.id,
            engineer_id=mixmaster_request.engineer_id,
            artist_id=mixmaster_request.artist_id,
            status='authorized'
        )

        # Notifications in-app (ajoutées en session, commitées ensuite)
        notify_mixmaster_request_received_and_sent(mixmaster_request)
        db.session.commit()

        flash('Paiement autorisé avec succès ! Votre demande a été envoyée à l\'engineer. Les fonds sont bloqués jusqu\'à la livraison.', 'success')
        return redirect(url_for('mixmaster.dashboard'))

    except stripe_error.StripeError as e:
        #  LOG: Erreur Stripe
        log_stripe_error(
            operation='payment_success_callback',
            error_message=str(e),
            resource_type='mixmaster',
            session_id=session_id
        )
        flash(f'Erreur lors de la récupération du paiement: {str(e)}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))
    except Exception as e:
        #  LOG: Erreur générale
        log_stripe_error(
            operation='mixmaster_request_creation',
            error_message=str(e),
            resource_type='mixmaster',
            session_id=session_id
        )
        flash(f'Erreur lors de la création de la demande: {str(e)}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard pour voir ses demandes (artiste) ou ses commandes (engineer)"""
    # Demandes en tant qu'artiste
    my_requests = db.session.query(MixMasterRequest).filter_by(artist_id=current_user.id).order_by(MixMasterRequest.created_at.desc()).all()

    # Commandes en tant qu'engineer
    my_orders = db.session.query(MixMasterRequest).filter_by(engineer_id=current_user.id).order_by(MixMasterRequest.created_at.desc()).all()

    # Compteur de mix en cours (pour l'engineer)
    active_count = 0
    if current_user.is_mixmaster_engineer:
        active_count = MixMasterRequest.get_active_requests_count(current_user.id)

    # Pour l'artiste : ajouter l'arborescence des fichiers de chaque archive
    requests_with_files = []
    for req in my_requests:
        req_data = {
            'request': req,
            'archive_tree': None
        }
        if req.original_file:
            archive_path = Path(current_app.root_path) / req.original_file
            if archive_path.exists():
                req_data['archive_tree'] = get_archive_file_tree(str(archive_path))
        requests_with_files.append(req_data)

    return render_template('mixmaster_dashboard.html',
                         my_requests=my_requests,
                         requests_with_files=requests_with_files,
                         my_orders=my_orders,
                         active_count=active_count)


@mixmaster_bp.route('/dashboard/engineer')
@login_required
def mix_engineer_dashboard():
    """
    Dashboard Espace Mix/Master Engineer
    Contenu : Demandes reçues (groupées par statut), Stats revenus, Historique
    """
    if not current_user.is_mix_engineer:
        flash('Accès réservé aux ingénieurs mix/master.', 'danger')
        return redirect(url_for('main.index'))

    # ========== DEMANDES REÇUES (en tant qu'engineer) ==========
    my_orders = db.session.query(MixMasterRequest).filter_by(engineer_id=current_user.id)\
        .order_by(MixMasterRequest.created_at.desc()).all()

    # Grouper les demandes par statut
    orders_by_status = {
        'awaiting_acceptance': [o for o in my_orders if o.status == 'awaiting_acceptance'],
        'accepted': [o for o in my_orders if o.status == 'accepted'],
        'processing': [o for o in my_orders if o.status == 'processing'],
        'delivered': [o for o in my_orders if o.status == 'delivered'],
        'revision1': [o for o in my_orders if o.status == 'revision1'],
        'revision2': [o for o in my_orders if o.status == 'revision2'],
        'completed': [o for o in my_orders if o.status == 'completed'],
        'rejected': [o for o in my_orders if o.status == 'rejected'],
        'refunded': [o for o in my_orders if o.status == 'refunded'],
    }

    # ========== STATS ==========
    # Revenus totaux (somme des engineer_revenue pour les demandes completed)
    completed_orders = [order for order in my_orders if order.status == 'completed']
    total_revenue = sum(order.engineer_revenue for order in completed_orders)
    total_completed_count = len(completed_orders)

    # Compteur de mix en cours
    active_count = 0
    if current_user.is_mixmaster_engineer:
        active_count = MixMasterRequest.get_active_requests_count(current_user.id)

    return render_template(
        'dashboard_mix_engineer.html',
        my_orders=my_orders,
        orders_by_status=orders_by_status,
        total_revenue=total_revenue,
        total_completed_count=total_completed_count,
        active_count=active_count
    )


@mixmaster_bp.route('/accept/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterEngineerSellerOwnership)
def accept_request(request_id, request_obj=None):
    """L'engineer accepte une demande de mix/master"""
    # Vérifier le statut
    if request_obj.status != 'awaiting_acceptance':
        flash('Cette demande a déjà été traitée.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Vérifier la limite de 5 mix en cours
    if not MixMasterRequest.can_accept_more_requests(current_user.id):
        flash('Vous avez déjà 5 mix/master en cours. Vous devez en terminer un avant d\'en accepter un nouveau.', 'warning')
        return redirect(url_for('mixmaster.dashboard'))

    # Accepter la demande (PAS de paiement, juste activation de la deadline)
    request_obj.status = 'accepted'
    request_obj.accepted_at = datetime.now()
    request_obj.deadline = datetime.now() + timedelta(days=7)  # 7 jours pour livrer

    # Notifier AVANT le commit : create_notification ajoute en session sans commit
    notify_mixmaster_status_changed(request_obj, 'awaiting_acceptance', 'accepted')

    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(request_obj, 'awaiting_acceptance', 'accepted')

    except Exception as e:
        current_app.logger.warning(f"Erreur lors de l'envoi de l'email d'acceptation: {e}", exc_info=True)


    flash('Demande acceptée! Vous avez 7 jours pour livrer le mix/master.', 'success')
    return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/reject/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterEngineerSellerOwnership)
def reject_request(request_id, request_obj=None):
    """L'engineer refuse une demande de mix/master"""

    # Vérifier le statut
    if request_obj.status != 'awaiting_acceptance':
        flash('Cette demande a déjà été traitée.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Supprimer le fichier original
    original_file_path = Path(current_app.root_path) / request_obj.original_file
    if original_file_path.exists():
        original_file_path.unlink()

    request_obj.status = 'rejected'
    request_obj.rejected_at = datetime.now()

    notify_mixmaster_status_changed(request_obj, 'awaiting_acceptance', 'rejected')

    try:
        email_service.send_mixmaster_status_update_email(request_obj, 'awaiting_acceptance', 'rejected')

    except Exception as e:
        current_app.logger.warning(f"Erreur lors de l'envoi de l'email de refus: {e}", exc_info=True)

    db.session.commit()

    flash('Demande refusée. Le fichier a été supprimé.', 'info')
    return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/cancel/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterArtistBuyerOwnership)
def cancel_request(request_id, request_obj=None):
    """L'artiste annule sa demande de mix/master (avant acceptation engineer)"""

    # Vérifier le statut - l'artiste ne peut annuler que si l'engineer n'a pas encore accepté
    if request_obj.status != 'awaiting_acceptance':
        flash('Cette demande ne peut plus être annulée car l\'engineer l\'a déjà acceptée.', 'danger')
        return redirect(url_for('payment.transactions'))

    # Annuler le Payment Intent Stripe si existant
    if request_obj.stripe_payment_intent_id:
        try:
            # Annuler le Payment Intent pour libérer les fonds bloqués
            if request_obj.stripe_payment_status in ['authorized', 'requires_payment_method', 'requires_confirmation']:
                stripe.PaymentIntent.cancel(request_obj.stripe_payment_intent_id)
                request_obj.stripe_payment_status = 'canceled'

                #  LOG: Payment Intent annulé
                log_stripe_transaction(
                    operation='payment_intent_canceled',
                    resource_type='mixmaster',
                    resource_id=request_id,
                    stripe_payment_intent_id=request_obj.stripe_payment_intent_id,
                    reason='artist_cancellation_before_acceptance'
                )
        except stripe_error.StripeError as e:
            #  LOG: Erreur annulation
            log_stripe_error(
                operation='payment_intent_cancel',
                error_message=str(e),
                resource_type='mixmaster',
                resource_id=request_id
            )
            flash(f'Erreur lors de l\'annulation du paiement: {str(e)}', 'danger')
            return redirect(url_for('payment.transactions'))

    # Supprimer les fichiers
    if request_obj.original_file:
        original_file_path = Path(current_app.root_path) / request_obj.original_file
        if original_file_path.exists():
            original_file_path.unlink()

    if request_obj.reference_file:
        reference_file_path = Path(current_app.root_path) / request_obj.reference_file
        if reference_file_path.exists():
            reference_file_path.unlink()

    # Mettre à jour le statut
    request_obj.status = 'refunded'
    request_obj.rejected_at = datetime.now()

    notify_mixmaster_status_changed(request_obj, 'awaiting_acceptance', 'refunded')

    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(request_obj, 'awaiting_acceptance', 'refunded')

    except Exception as e:
        current_app.logger.warning(f"Erreur lors de l'envoi de l'email d'annulation: {e}", exc_info=True)

    # NOTE: Avec PaymentIntent.cancel(), les fonds sont libérés SANS FRAIS Stripe
    # car le paiement n'a jamais été capturé (statut: authorized)
    flash('Votre demande a été annulée et vos fonds ont été libérés (aucun frais).', 'success')
    return redirect(url_for('payment.transactions'))

@mixmaster_bp.route('/request_revision/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterArtistBuyerOwnership)
def request_revision(request_id, request_obj=None):
    """
    L'artiste demande une révision du mix/master.
    Pattern lazy : les fonds (9% net) sont crédités dans le wallet de l'engineer
    et le Transfer Stripe vers son compte Connect sera créé lors du retrait.
    """
    if request_obj.stripe_payment_status != 'deposit_captured':
        flash('Statut de paiement incorrect pour une révision.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    can_revise, reason = request_obj.can_request_revision()
    if not can_revise:
        flash(f'Impossible de demander une révision : {reason}', 'warning')
        return redirect(url_for('mixmaster.dashboard'))

    revision_message = request.form.get('revision_message', '').strip()
    if not revision_message:
        flash('Veuillez préciser les modifications souhaitées.', 'warning')
        return redirect(url_for('mixmaster.dashboard'))

    # ========== MISE À JOUR ==========
    old_status = request_obj.status
    request_obj.revision_count += 1
    revision_transfer_amount = request_obj.get_revision_transfer_amount()

    from utils.wallet_service import credit_wallet_for_mixmaster_revision
    credit_wallet_for_mixmaster_revision(request_obj)

    if request_obj.revision_count == 1:
        request_obj.status = 'revision1'
        request_obj.revision1_message = revision_message
        request_obj.revision1_requested_at = datetime.now()
        request_obj.stripe_payment_status = 'partially_captured'
    else:
        request_obj.status = 'revision2'
        request_obj.revision2_message = revision_message
        request_obj.revision2_requested_at = datetime.now()

    notify_mixmaster_status_changed(request_obj, old_status, request_obj.status)
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(request_obj, old_status, request_obj.status)
    except Exception as e:
        current_app.logger.warning(f"Erreur email révision #{request_id}: {e}", exc_info=True)

    flash(
        f'Révision {request_obj.revision_count}/2 demandée. '
        f'{revision_transfer_amount}€ ajoutés aux gains de {request_obj.engineer.username} (disponible dans 7 jours).',
        'success'
    )
    return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/deliver_revision/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterEngineerSellerOwnership)
def deliver_revision(request_id, request_obj=None):
    """
    L'engineer livre le fichier révisé.
    Pas de nouveau paiement Stripe (déjà transféré lors de request_revision).
    """
    if request_obj.status not in ['revision1', 'revision2']:
        flash('Aucune révision en attente.', 'warning')
        return redirect(url_for('mixmaster.dashboard'))

    if 'processed_file' not in request.files:
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    file = request.files['processed_file']
    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    if not VALIDATION_AVAILABLE:
        current_app.logger.error('CRITIQUE: Validation mime-type indisponible')
        abort(500)

    if not allowed_file(file.filename, {'wav', 'mp3'}):
        flash('Format non autorisé. Utilisez .wav ou .mp3', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    is_valid, error_message = validate_audio_file(file)
    if not is_valid:
        flash(f'Fichier invalide : {error_message}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    if not validate_file_size(file):
        flash('Fichier trop volumineux. Maximum 500MB.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Sauvegarde
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_filename = f"rev{request_obj.revision_count}_{request_id}_{timestamp}_{filename}"

    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    file_disk_path = config.MIXMASTER_PROCESSED_FOLDER / unique_filename
    file.save(file_disk_path)
    filepath = Path('static', 'mixmaster', 'processed', unique_filename).as_posix()

    # Génération des previews
    try:
        audio = AudioSegment.from_file(file_disk_path)
        duration_ms = len(audio)
        audio_format = filename.rsplit('.', 1)[1].lower()

        config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)

        preview_half = audio[:duration_ms // 2]
        preview_filename = f"preview_rev{request_obj.revision_count}_{request_id}_{timestamp}_{filename}"
        preview_disk_path = config.MIXMASTER_PREVIEWS_FOLDER / preview_filename
        preview_half.export(preview_disk_path, format=audio_format)
        preview_filepath = Path('static', 'mixmaster', 'previews', preview_filename).as_posix()

        preview_full = generate_telephone_preview(audio)
        preview_full_filename = f"preview_full_rev{request_obj.revision_count}_{request_id}_{timestamp}_{filename}"
        preview_full_disk_path = config.MIXMASTER_PREVIEWS_FOLDER / preview_full_filename
        preview_full.export(preview_full_disk_path, format=audio_format)
        preview_full_filepath = Path('static', 'mixmaster', 'previews', preview_full_filename).as_posix()

    except Exception as e:
        current_app.logger.error(f'Erreur preview révision #{request_id}: {e}', exc_info=True)
        if file_disk_path.exists():
            file_disk_path.unlink()
        flash(f'Erreur traitement audio : {str(e)}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Mise à jour du modèle
    old_status = request_obj.status

    if request_obj.revision_count == 1:
        request_obj.processed_file_revision1 = filepath
        request_obj.revision1_delivered_at = datetime.now()
    else:
        request_obj.processed_file_revision2 = filepath
        request_obj.revision2_delivered_at = datetime.now()

    request_obj.processed_file = filepath
    request_obj.processed_file_preview = preview_filepath
    request_obj.processed_file_preview_full = preview_full_filepath
    request_obj.status = 'delivered'
    request_obj.delivered_at = datetime.now()

    notify_mixmaster_status_changed(request_obj, old_status, 'delivered')
    db.session.commit()

    try:
        email_service.send_mixmaster_status_update_email(request_obj, old_status, 'delivered')
    except Exception as e:
        current_app.logger.warning(f"Erreur email livraison révision #{request_id}: {e}", exc_info=True)

    flash(
        f'Révision {request_obj.revision_count} livrée ! '
        f'{request_obj.artist.username} a été notifié.',
        'success'
    )
    return redirect(url_for('mixmaster.dashboard'))




@mixmaster_bp.route('/upload_processed/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterEngineerSellerOwnership)
@verify_stripe_payment_for_capture()
def upload_processed(request_id, request_obj=None, payment_intent_verified=None):
    """L'engineer upload le fichier traité (version preview coupée)"""
    # OUTDATED Decorator requires ownership
    # request_obj = MixMasterRequest.query.get_or_404(request_id)

    # # Vérifier que c'est bien l'engineer de cette demande
    # if request_obj.engineer_id != current_user.id:
    #     flash('Accès non autorisé.', 'danger')
    #     return redirect(url_for('mixmaster.dashboard'))

    # Vérifier le statut
    if request_obj.status not in ['accepted', 'processing']:
        flash('Cette demande ne peut plus être modifiée.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Vérifier qu'un fichier a été envoyé
    if 'processed_file' not in request.files:
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    file = request.files['processed_file']

    if file.filename == '':
        flash('Aucun fichier sélectionné.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # ============================================
    # VALIDATION SÉCURISÉE DU FICHIER
    # ============================================

    #  SÉCURITÉ CRITIQUE: python-magic est OBLIGATOIRE
    if not VALIDATION_AVAILABLE:
        flash('Erreur serveur: validation de sécurité non disponible. Contactez l\'administrateur.', 'error')
        current_app.logger.error('CRITIQUE: Validation mime-type via python-magic indisponible')
        abort(500)

    # Vérifier l'extension
    if not allowed_file(file.filename, {'wav', 'mp3'}):
        flash('Format non autorisé. Utilisez .wav ou .mp3', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Valider le MIME type du fichier traité (audio)
    is_valid, error_message = validate_audio_file(file)
    if not is_valid:
        flash(f' Fichier invalide : {error_message}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Vérifier la taille du fichier
    if not validate_file_size(file):
        flash('Fichier trop volumineux. Maximum 500MB.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Sauvegarder le fichier complet (non accessible directement)
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_filename = f"processed_{request_id}_{timestamp}_{filename}"

    # Utiliser le dossier défini dans config.py
    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)

    file_disk_path = config.MIXMASTER_PROCESSED_FOLDER / unique_filename
    file.save(file_disk_path)

    # Chemin web pour la BDD (as_posix() force les / même sur Windows)
    filepath = Path('static', 'mixmaster', 'processed', unique_filename).as_posix()

    # Créer les versions preview
    try:
        audio = AudioSegment.from_file(file_disk_path)
        duration_ms = len(audio)
        half_duration = duration_ms // 2
        audio_format = filename.rsplit('.', 1)[1].lower()

        config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)

        # PREVIEW 1 : Première moitié, qualité originale (permet de juger la qualité réelle)
        preview_half = audio[:half_duration]
        preview_filename = f"preview_{request_id}_{timestamp}_{filename}"
        preview_disk_path = config.MIXMASTER_PREVIEWS_FOLDER / preview_filename
        preview_half.export(preview_disk_path, format=audio_format)
        preview_filepath = Path('static', 'mixmaster', 'previews', preview_filename).as_posix()

        # PREVIEW 2 : Version entière, qualité réduite "téléphone" (hi-pass 60Hz + lo-pass 13kHz)
        # Permet à l'artiste de vérifier les effets/constructions sur toute la durée
        preview_full = generate_telephone_preview(audio)
        preview_full_filename = f"preview_full_{request_id}_{timestamp}_{filename}"
        preview_full_disk_path = config.MIXMASTER_PREVIEWS_FOLDER / preview_full_filename
        preview_full.export(preview_full_disk_path, format=audio_format)
        preview_full_filepath = Path('static', 'mixmaster', 'previews', preview_full_filename).as_posix()

        # NOUVELLE LOGIQUE: Capturer 100% du montant, transférer seulement 30%
        # Les 70% restants sont gardés sur le compte plateforme
        # jusqu'au téléchargement final ou remboursement
        try:
            #  SÉCURITÉ: Le décorateur @verify_stripe_payment_for_capture a déjà vérifié:
            # - Payment Intent existe
            # - Status = 'requires_capture'
            # - Montant correct
            # - Status BDD = 'authorized'

            # Capturer le MONTANT TOTAL (100%)
            # Les fonds arrivent sur le compte de la plateforme (moins frais Stripe)
            capture = stripe.PaymentIntent.capture(
                request_obj.stripe_payment_intent_id
                # Pas de amount_to_capture = capture totale
            )

            #  LOG: Payment Intent capturé (100% du montant total)
            log_stripe_payment_intent_captured(
                payment_intent_id=request_obj.stripe_payment_intent_id,
                amount=capture.amount,
                resource_type='mixmaster',
                resource_id=request_id,
                engineer_id=request_obj.engineer_id,
                artist_id=request_obj.artist_id,
                capture_type='full_capture_100_percent'
            )

            # Créditer le wallet de l'engineer (acompte 30% - 10% commission = 27%)
            # Le Transfer Stripe vers Connect sera créé au moment du retrait (lazy)
            from utils.wallet_service import credit_wallet_for_mixmaster_deposit
            credit_wallet_for_mixmaster_deposit(request_obj)

            # Mettre à jour la base de données
            request_obj.processed_file = filepath
            request_obj.processed_file_preview = preview_filepath
            request_obj.processed_file_preview_full = preview_full_filepath
            request_obj.status = 'delivered'
            request_obj.delivered_at = datetime.now()
            # Nouveau statut: montant total capturé, acompte transféré
            request_obj.stripe_payment_status = 'deposit_captured'

            notify_mixmaster_status_changed(request_obj, 'accepted', 'delivered')

            db.session.commit()

            try:
                email_service.send_mixmaster_status_update_email(request_obj, 'accepted', 'delivered')

            except Exception as e:
                current_app.logger.warning(f"Erreur lors de l'envoi de l'email de livraison: {e}", exc_info=True)

            deposit_engineer_amount = round(float(request_obj.deposit_amount) * 0.90, 2)
            flash(f'Fichier livré ! Montant total de {request_obj.total_price}€ capturé. Votre acompte de {deposit_engineer_amount}€ sera disponible dans 7 jours dans vos gains.', 'success')

        except stripe_error.StripeError as e:
            current_app.logger.error(f'Erreur capture paiement demande #{request_id}: {str(e)}', exc_info=True)
            flash(f'Erreur de capture de l\'acompte: {str(e)}', 'danger')
            # Supprimer les fichiers en cas d'erreur de paiement
            if file_disk_path.exists():
                file_disk_path.unlink()
            if preview_disk_path.exists():
                preview_disk_path.unlink()
            if preview_full_disk_path.exists():
                preview_full_disk_path.unlink()

    except Exception as e:
        current_app.logger.error(f'Erreur traitement audio pydub pour demande #{request_id}: {str(e)}', exc_info=True)
        flash(f'Erreur lors du traitement du fichier: {str(e)}', 'danger')
        # Supprimer le fichier en cas d'erreur
        if file_disk_path.exists():
            file_disk_path.unlink()

    return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/approve/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterArtistBuyerOwnership)
def approve_request(request_id, request_obj=None):
    """Redirection vers la page de confirmation de téléchargement"""
    return redirect(url_for('mixmaster.download_confirmation', request_id=request_id))




@mixmaster_bp.route('/download/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterArtistBuyerOwnership)
@verify_stripe_payment_for_download()
def download_processed(request_id, request_obj=None, payment_intent_verified=None, deposit_transfer_verified=None):
    """Télécharger le fichier complet (paiement final 70%)"""
    # request_obj = MixMasterRequest.query.get_or_404(request_id)

    # # Vérifier que c'est bien l'artiste de cette demande
    # if request_obj.artist_id != current_user.id:
    #     flash('Accès non autorisé.', 'danger')
    #     return redirect(url_for('mixmaster.dashboard'))

    # Vérifier que la demande a été livrée (acompte déjà payé)
    if request_obj.status not in ['delivered', 'completed']:
        flash('Le fichier n\'a pas encore été livré.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    #  SÉCURITÉ: Le décorateur @verify_stripe_payment_for_download a déjà vérifié:
    # - Payment Intent existe
    # - Status = 'succeeded'
    # - Montant capturé correct
    # - Transfer initial de 30% effectué et non annulé
    # - Montant du transfer correct

    # Défense en profondeur: vérifier aussi le statut local
    if request_obj.stripe_payment_status != 'deposit_captured':
        flash('Le statut du paiement en base de données est incorrect.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Vérifier que le fichier existe
    processed_file_path = Path(current_app.root_path) / request_obj.processed_file
    if not processed_file_path.exists():
        flash('Fichier introuvable.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Créditer le wallet de l'engineer pour le solde final (montant dynamique selon révisions)
    try:
        final_engineer_amount = request_obj.get_final_transfer_amount()
        from utils.wallet_service import credit_wallet_for_mixmaster_final
        credit_wallet_for_mixmaster_final(request_obj)

        # Mettre à jour la base de données
        request_obj.status = 'completed'
        request_obj.completed_at = datetime.now()
        request_obj.stripe_payment_status = 'fully_transferred'

        notify_mixmaster_status_changed(request_obj, 'delivered', 'completed')

        db.session.commit()

        try:
            email_service.send_mixmaster_status_update_email(request_obj, 'delivered', 'completed')
        except Exception as e:
            current_app.logger.warning(f"Erreur lors de l'envoi de l'email de complétion: {e}", exc_info=True)

        log_stripe_payment_intent_succeeded(
            payment_intent_id=request_obj.stripe_payment_intent_id,
            amount=payment_intent_verified.amount,
            resource_type='mixmaster',
            resource_id=request_id,
            engineer_id=request_obj.engineer_id,
            artist_id=request_obj.artist_id,
            completion_type='full_transfer_100_percent'
        )

        flash(f'Solde final de {final_engineer_amount}€ ajouté à vos gains (disponible dans 7 jours). Téléchargement en cours...', 'success')

        # Télécharger le fichier
        return send_file(processed_file_path, as_attachment=True)

    except stripe_error.StripeError as e:
        #  LOG: Erreur lors du transfer final
        log_stripe_error(
            operation='final_transfer_70_percent',
            error_message=str(e),
            resource_type='mixmaster',
            resource_id=request_id
        )
        flash(f'Erreur de paiement final: {str(e)}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))
    except Exception as e:
        #  LOG: Erreur générale
        log_stripe_error(
            operation='download_processed',
            error_message=str(e),
            resource_type='mixmaster',
            resource_id=request_id
        )
        flash(f'Erreur: {str(e)}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/reject_delivery/<int:request_id>', methods=['POST'])
@login_required
@requires_ownership(MixMasterArtistBuyerOwnership)
@verify_stripe_payment_for_refund()
def reject_delivery(request_id, request_obj=None, payment_intent_verified=None, deposit_transfer_verified=None):
    """L'artiste refuse le mix/master livré et demande un remboursement des 70%"""
    # OUTDATED
    # request_obj = MixMasterRequest.query.get_or_404(request_id)

    # # Vérifier que c'est bien l'artiste de cette demande
    # if request_obj.artist_id != current_user.id:
    #     flash('Accès non autorisé.', 'danger')
    #     return redirect(url_for('mixmaster.dashboard'))

    # Vérifier le statut - l'artiste peut refuser seulement si livré mais pas encore téléchargé
    if request_obj.status != 'delivered':
        flash('Cette demande ne peut plus être refusée.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    #  SÉCURITÉ: Le décorateur @verify_stripe_payment_for_refund a déjà vérifié:
    # - Payment Intent existe
    # - Status = 'succeeded'
    # - Montant capturé correct
    # - Transfer initial effectué et non annulé

    # Défense en profondeur: vérifier le statut local
    if request_obj.stripe_payment_status != 'deposit_captured':
        flash('Le statut du paiement en base de données est incorrect.', 'danger')
        return redirect(url_for('mixmaster.dashboard'))

    # Rembourser l'artiste (montant dynamique selon révisions)
    try:
        refund_amount = request_obj.get_refund_amount()
        gross_refund_pct = 70 - (request_obj.revision_count * 10)

        refund = stripe.Refund.create(
            payment_intent=request_obj.stripe_payment_intent_id,
            amount=int(refund_amount * 100),
            reason='requested_by_customer',
            metadata={
                'type': 'mixmaster_rejection',
                'request_id': str(request_id),
                'revision_count': str(request_obj.revision_count),
                'refund_gross_percent': str(gross_refund_pct),
                'engineer_keeps_net': str(
                    round(
                        request_obj.deposit_amount * 0.90
                        + request_obj.revision_count * request_obj.get_revision_transfer_amount(),
                        2
                    )
                ),
                'platform_keeps': str(round(request_obj.total_price * 0.10, 2))
            }
        )

        log_stripe_refund_created(
            refund_id=refund.id,
            amount=refund.amount,
            payment_intent_id=request_obj.stripe_payment_intent_id,
            resource_type='mixmaster',
            resource_id=request_id,
            reason='artist_rejected_delivery',
            engineer_id=request_obj.engineer_id,
            artist_id=request_obj.artist_id
        )

        request_obj.stripe_refund_id = refund.id
        request_obj.status = 'refunded'
        request_obj.rejected_at = datetime.now()
        request_obj.stripe_payment_status = 'partially_refunded'

        notify_mixmaster_status_changed(request_obj, 'delivered', 'refunded')

        db.session.commit()

        try:
            email_service.send_mixmaster_status_update_email(request_obj, 'delivered', 'refunded')
        except Exception as e:
            current_app.logger.warning(f"Erreur lors de l'envoi de l'email d'annulation: {e}", exc_info=True)

        engineer_net_received = round(
            request_obj.deposit_amount * 0.90
            + request_obj.revision_count * request_obj.get_revision_transfer_amount(),
            2
        )
        flash(
            f'Mix/Master refusé. Remboursement de {refund_amount}€ effectué. '
            f'L\'engineer conserve {engineer_net_received}€ (acompte + révisions). '
            f'Commission plateforme : {round(request_obj.total_price * 0.10, 2)}€.',
            'info'
        )
        return redirect(url_for('mixmaster.dashboard'))

    except stripe_error.StripeError as e:
        #  LOG: Erreur lors du refund
        log_stripe_error(
            operation='refund_70_percent',
            error_message=str(e),
            resource_type='mixmaster',
            resource_id=request_id
        )
        flash(f'Erreur lors du remboursement: {str(e)}', 'danger')
        return redirect(url_for('mixmaster.dashboard'))


@mixmaster_bp.route('/check_expired')
def check_expired_requests():
    """Tâche CRON pour vérifier les demandes expirées et annuler les Payment Intents"""
    expired_requests = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.deadline < datetime.now(),
        MixMasterRequest.status.in_(['accepted', 'processing'])
    ).all()

    canceled_count = 0

    for req in expired_requests:
        try:
            # Annuler le Payment Intent (au lieu de rembourser)
            # Cela libère les fonds bloqués sans aucun prélèvement
            if req.stripe_payment_intent_id and req.stripe_payment_status in ['authorized', 'requires_payment_method', 'requires_confirmation']:
                stripe.PaymentIntent.cancel(req.stripe_payment_intent_id)

                #  LOG: Payment Intent annulé (CRON - expiration deadline)
                log_stripe_transaction(
                    operation='payment_intent_canceled',
                    resource_type='mixmaster',
                    resource_id=req.id,
                    stripe_payment_intent_id=req.stripe_payment_intent_id,
                    reason='deadline_expired_cron',
                    user_id=req.artist_id
                )

                req.stripe_payment_status = 'canceled'
                req.status = 'refunded'  # On garde ce statut pour la cohérence avec l'ancien système
                db.session.commit()

                canceled_count += 1

        except stripe_error.StripeError as e:
            current_app.logger.error(f"Erreur annulation demande #{req.id}: {str(e)}", exc_info=True)

    return jsonify({
        'success': True,
        'canceled_count': canceled_count
    })
