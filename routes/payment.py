"""
Blueprint PAYMENT - Gestion des achats et paiements Stripe
Routes pour acheter des tracks, gérer les sessions Stripe et télécharger les achats
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, session, current_app, send_file
from flask_login import login_required, current_user
import stripe
import stripe._error as stripe_error
from datetime import datetime, timedelta
import uuid
from pathlib import Path

from extensions import db
from models import Track, Purchase, User, Topline, Contract, MixMasterRequest, Favorite, ListeningHistory
from config import PLATFORM_COMMISSION
from utils.ownership_authorizer import PurchaseOwnership, requires_ownership
from utils.payment_validator import validate_payment, TrackPriceCalculator
from utils.stripe_logger import (
    log_stripe_transaction,
    log_stripe_checkout_session_created,
    log_stripe_payment_intent_succeeded,
    log_stripe_error
)
from utils.path_validator import validate_static_path
from utils import notification_service, email_service
import config

# Import conditionnel pour la génération de contrats PDF
try:
    from utils.contract_generator import generate_contract_pdf
    CONTRACT_AVAILABLE = True
except ImportError:
    CONTRACT_AVAILABLE = False

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

payment_bp = Blueprint('payment', __name__)


# ============================================
# ROUTE 1 : INITIER L'ACHAT
# ============================================

@payment_bp.route('/buy/<int:track_id>/<format_type>', methods=['POST'])
@login_required
def buy(track_id, format_type):
    """Initier l'achat d'un track - Redirige vers la configuration du contrat"""
    
    track = db.get_or_404(Track, track_id)
    
    # Vérifier que l'utilisateur n'achète pas son propre track
    if current_user.id == track.composer_id:
        flash(" Vous ne pouvez pas acheter votre propre composition.", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))
    
    # Vérifier que le format existe
    if format_type == 'mp3' and not track.file_mp3:
        flash(" Format MP3 non disponible.", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))
    elif format_type == 'wav' and not track.file_wav:
        flash(" Format WAV non disponible.", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))
    elif format_type == 'stems' and not track.file_stems:
        flash(" Format STEMS non disponible.", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))
    
    # Rediriger vers la configuration du contrat
    return redirect(url_for('payment.contract_config', track_id=track_id, format_type=format_type))


# ============================================
# ROUTE 2 : CONFIGURATION DU CONTRAT
# ============================================

@payment_bp.route('/buy/<int:track_id>/<format_type>/contract', methods=['GET', 'POST'])
@login_required
def contract_config(track_id, format_type):
    """Configuration du contrat avant paiement"""
    
    track = db.get_or_404(Track, track_id)
    
    # Empêcher l'achat de son propre track
    if track.composer_id == current_user.id:
        flash('Vous ne pouvez pas acheter votre propre composition', 'danger')
        return redirect(url_for('main.index'))
    
    # Obtenir le prix du track selon le format
    track_prices = {
        'mp3': track.price_mp3,
        'wav': track.price_wav,
        'stems': track.price_stems
    }
    track_price = track_prices.get(format_type, track.price_mp3)
    
    if request.method == 'POST':
        # Récupérer les options du contrat
        is_exclusive = request.form.get('is_exclusive') == 'on'
        duration = request.form.get('duration_years_value', 1)
        territory = request.form.get('territory')
        
        mechanical_reproduction = request.form.get('mechanical_reproduction') == 'on'
        public_show = request.form.get('public_show') == 'on'
        arrangement = request.form.get('arrangement') == 'on'
        
        # Calculer le prix du contrat
        contract_price = 0
        
        if is_exclusive:
            contract_price += current_app.config.get('CONTRACT_EXCLUSIVE_PRICE', 150)
        
        # Durée
        if duration == 'lifetime':
            contract_price += current_app.config['CONTRACT_DURATIONS']['lifetime']
        else:
            years = str(int(duration))
            contract_price += current_app.config['CONTRACT_DURATIONS'].get(years, 5)
        
        # Territoire
        if territory == 'Europe':
            contract_price += current_app.config.get('CONTRACT_TERRITORY_EUROPE', 5)
        elif territory == 'Monde entier':
            contract_price += current_app.config.get('CONTRACT_TERRITORY_WORLD', 10)

        # Droits
        if mechanical_reproduction:
            contract_price += current_app.config.get('CONTRACT_MECHANICAL_REPRODUCTION_PRICE', 30)
        if public_show:
            contract_price += current_app.config.get('CONTRACT_PUBLIC_SHOW_PRICE', 40)
        if arrangement:
            contract_price += current_app.config.get('CONTRACT_ARRANGEMENT_PRICE', 10)
        
        # Sauvegarder les données dans la session
        session['contract_data'] = {
            'track_id': track_id,
            'format_type': format_type,
            'is_exclusive': is_exclusive,
            'duration': duration,
            'territory': territory,
            'mechanical_reproduction': mechanical_reproduction,
            'public_show': public_show,
            'arrangement': arrangement,
            'contract_price': contract_price,
            'track_price': track_price,
            'total_price': track_price + contract_price
        }
        
        # Rediriger vers la page de paiement
        return redirect(url_for('payment.checkout', track_id=track_id, format_type=format_type))
    
    return render_template('contract_config.html',
                         track=track,
                         format_type=format_type,
                         base_price=track_price,
                         sacem_composer=track.sacem_percentage_composer,
                         sacem_buyer=track.get_sacem_percentage_buyer(),
                         config=current_app.config)


# ============================================
# ROUTE 3 : CHECKOUT (Page avant Stripe)
# ============================================

@payment_bp.route('/checkout/<int:track_id>/<format_type>')
@login_required
def checkout(track_id, format_type):
    """Page de checkout avant redirection Stripe"""
    
    track = db.get_or_404(Track, track_id)
    
    # Récupérer les données du contrat depuis la session
    contract_data = session.get('contract_data', {})
    
    if not contract_data:
        flash('Session expirée. Veuillez reconfigurer votre contrat.', 'warning')
        return redirect(url_for('payment.contract_config', track_id=track_id, format_type=format_type))
    
    return render_template('checkout.html',
                         track=track,
                         format_type=format_type,
                         contract_data=contract_data)


# ============================================
# ROUTE 4 : CRÉER SESSION STRIPE CHECKOUT
# ============================================

@payment_bp.route('/buy/<int:track_id>/<format_type>/checkout', methods=['POST'])
@login_required
@validate_payment(TrackPriceCalculator, 'track')
def create_stripe_checkout(track_id, format_type, resource=None, validated_prices=None):
    """Crée une session Stripe Checkout avec toutes les infos du contrat"""

    # Le décorateur a déjà validé le prix et récupéré le track
    track = resource if resource else db.get_or_404(Track, track_id)

    # Vérifier que l'utilisateur n'achète pas son propre track
    if current_user.id == track.composer_id:
        flash(" Vous ne pouvez pas acheter votre propre composition.", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))

    try:
        #  SÉCURITÉ : Utiliser le prix validé par le décorateur
        # Le décorateur a déjà comparé le prix client avec le calcul serveur
        if validated_prices:
            total_price = validated_prices['total_price']
            base_price = validated_prices['base_price']
            contract_price = validated_prices['options_price']
        else:
            # Fallback (ne devrait jamais arriver avec le nouveau système)
            total_price_str = request.form.get('total_price')
            total_price = round(float(total_price_str), 2)
            base_price = total_price
            contract_price = 0
        
        # Récupérer les options du contrat depuis le formulaire
        # Les checkboxes envoient leur value si cochées, rien sinon
        is_exclusive = 'is_exclusive' in request.form
        duration_years = request.form.get('duration_years_value', '1')
        is_lifetime = 'is_lifetime' in request.form and request.form.get('is_lifetime') == '1'
        territory = request.form.get('territory', 'Monde entier')

        # Droits
        streaming = True
        mechanical_reproduction = 'mechanical_reproduction' in request.form
        public_show = 'public_show' in request.form
        arrangement = 'arrangement' in request.form
        
        # Informations de facturation
        buyer_address = request.form.get('buyer_address', '')
        buyer_email = request.form.get('buyer_email', current_user.email)
        
        # Créer les métadonnées pour Stripe
        metadata = {
            'track_id': track_id,
            'track_title': track.title,
            'composer_id': track.composer_id,
            'composer_username': track.composer_user.username,
            'buyer_id': current_user.id,
            'buyer_username': current_user.username,
            'format_type': format_type,
            'is_exclusive': str(is_exclusive),
            'duration_years': duration_years,
            'is_lifetime': str(is_lifetime),
            'territory': territory,
            'streaming': 'true',
            'mechanical_reproduction': str(mechanical_reproduction),
            'public_show': str(public_show),
            'arrangement': str(arrangement),
            'buyer_address': buyer_address,
            'buyer_email': buyer_email,
        }
        
        # Créer la session Stripe Checkout
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': round(total_price * 100),
                    'product_data': {
                        'name': f"{track.title} - {format_type.upper()}",
                        'description': f"Licence d'exploitation musicale par {track.composer_user.username}",
                        'images': [request.url_root.rstrip('/') + url_for('static', filename=track.image_file)],
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.url_root.rstrip('/') + url_for('payment.success') + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.url_root.rstrip('/') + url_for('main.track_detail', track_id=track_id),
            metadata=metadata,
            customer_email=buyer_email,
        )

        #  LOG: Checkout session créée
        log_stripe_checkout_session_created(
            session_id=checkout_session.id,
            amount=round(total_price * 100),
            resource_type='track',
            resource_id=track_id,
            track_title=track.title,
            format_type=format_type,
            composer_id=track.composer_id,
            buyer_id=current_user.id
        )

        return redirect(checkout_session.url, code=303)
        
    except Exception as e:
        current_app.logger.error(f"Erreur creation session Stripe: {e}", exc_info=True)
        #  LOG: Erreur création checkout
        log_stripe_error(
            operation='checkout_session_creation',
            error_message=str(e),
            resource_type='track',
            resource_id=track_id
        )

        flash(f" Erreur lors de la création de la session de paiement: {str(e)}", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))


# ============================================
# ROUTE 5 : PAYMENT SUCCESS
# ============================================

@payment_bp.route('/payment/success')
@login_required
def success():
    """Page de confirmation après paiement réussi - Crée l'achat et génère le contrat"""
    
    session_id = request.args.get('session_id')
    
    if not session_id:
        flash(" Session de paiement introuvable.", 'danger')
        return redirect(url_for('main.index'))
    
    try:
        # Récupérer la session Stripe
        stripe_session = stripe.checkout.Session.retrieve(session_id)
        
        if stripe_session.payment_status != 'paid':
            flash(" Le paiement n'a pas été complété.", 'danger')
            return redirect(url_for('main.index'))
        
        # Vérifier si l'achat existe déjà (éviter doublons)
        existing_purchase = db.session.query(Purchase).filter_by(
            stripe_payment_intent_id=stripe_session.payment_intent
        ).first()
        
        if existing_purchase:
            return render_template('payment_success.html', 
                                 track=existing_purchase.track, 
                                 purchase=existing_purchase)
        
        # Récupérer les métadonnées
        metadata = stripe_session.metadata
        track_id = int(metadata['track_id'])
        format_type = metadata['format_type']
        
        track = db.get_or_404(Track, track_id)
        
        # Calculer le prix payé
        amount_total = round(stripe_session.amount_total / 100, 2)
        
        # Calculer la répartition des prix
        if format_type == 'mp3':
            track_price = track.price_mp3
        elif format_type == 'wav':
            track_price = track.price_wav
        elif format_type == 'stems':
            track_price = track.price_stems
        else:
            track_price = amount_total
        
        contract_price = round(amount_total - track_price, 2)
        platform_fee = round(amount_total * PLATFORM_COMMISSION, 2)
        composer_revenue = round(amount_total - platform_fee, 2)
        
        # CRÉER L'ACHAT
        purchase = Purchase(
            track_id=track_id,
            buyer_id=current_user.id,
            format_purchased=format_type,
            price_paid=amount_total,
            buyer_name=current_user.username,
            track_price=track_price,
            contract_price=contract_price,
            platform_fee=platform_fee,
            composer_revenue=composer_revenue,
            stripe_payment_intent_id=stripe_session.payment_intent
        )
        
        db.session.add(purchase)
        db.session.flush()

        # Créditer le wallet du compositeur (pending 7 jours)
        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)

        #  LOG: Payment Intent succeeded (achat track)
        log_stripe_payment_intent_succeeded(
            payment_intent_id=stripe_session.payment_intent,
            amount=stripe_session.amount_total,
            resource_type='track',
            resource_id=track_id,
            purchase_id=purchase.id,
            track_title=track.title,
            format_type=format_type,
            composer_id=track.composer_id,
            buyer_id=current_user.id
        )

        # Générer le contrat PDF
        if CONTRACT_AVAILABLE:
            try:
                duration_years = metadata.get('duration_years', '1')
                is_lifetime = metadata.get('is_lifetime') == 'True'
                
                start_date = datetime.now()
                
                if is_lifetime or duration_years == '999':
                    end_date_str = "À vie + 70 ans après le décès du compositeur"
                    duration_text = "À vie + 70 ans"
                else:
                    years = int(duration_years)
                    end_date = start_date + timedelta(days=365 * years)
                    end_date_str = end_date.strftime('%d/%m/%Y')
                    duration_text = f"{years} an{'s' if years > 1 else ''}"
                
                composer = track.composer_user
                client = current_user
                
                contract_data = {
                    'track_title': track.title,
                    'composer_name': composer.username,
                    'composer_address': metadata.get('composer_address', ''),
                    'composer_email': composer.email,
                    'composer_credit': f"Prod. par {composer.username}",
                    'composer_signature': composer.signature or composer.username,
                    'client_name': client.username,
                    'client_address': metadata.get('buyer_address', ''),
                    'client_email': metadata.get('buyer_email', client.email),
                    'client_signature': client.signature or client.username,
                    'is_exclusive': metadata.get('is_exclusive') == 'True',
                    'start_date': start_date.strftime('%d/%m/%Y'),
                    'end_date': end_date_str,
                    'duration_text': duration_text,
                    'territory': metadata.get('territory', 'Monde entier'),
                    'mechanical_reproduction': metadata.get('mechanical_reproduction') == 'True',
                    'public_show': metadata.get('public_show') == 'True',
                    'streaming': True,
                    'arrangement': metadata.get('arrangement') == 'True',
                    'price': int(amount_total),
                    'sacem_percentage_composer': track.sacem_percentage_composer,
                    'sacem_percentage_buyer': track.get_sacem_percentage_buyer(),
                    'platform_commission': 10,
                    'signature_place': 'En ligne',
                    'signature_date': start_date.strftime('%d/%m/%Y')
                }
                
                contract_filename = f"contrat_{purchase.id}_{uuid.uuid4().hex[:8]}.pdf"
                contracts_folder = config.CONTRACTS_FOLDER
                contract_path = contracts_folder / contract_filename

                contracts_folder.mkdir(parents=True, exist_ok=True)
                generate_contract_pdf(str(contract_path), contract_data)
                
                purchase.contract_file = f'contracts/{contract_filename}'
                current_app.logger.info(f"Contrat généré: {contract_filename}")
                
            except Exception as e:
                current_app.logger.error(f"Erreur generation contrat: {e}", exc_info=True)

        # Notification added for seller
        notification_service.notify_purchase_confirmed(purchase=purchase)

        # Notification added for buyer
        notification_service.notify_sale_completed(purchase=purchase)

        #Mails après les notifications
        try:
            email_service.send_purchase_confirmation_email(purchase)
            email_service.send_sale_notification_email(purchase)
        except Exception as e:
            current_app.logger.error(f"Erreur envoi emails: {e}", exc_info=True)
    
        db.session.commit()



        flash(f" Achat confirmé ! Vous pouvez maintenant télécharger votre fichier.", 'success')
        
        return render_template('payment_success.html', track=track, purchase=purchase)
        
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe: {e}", exc_info=True)

        #  LOG: Erreur Stripe lors du success callback
        log_stripe_error(
            operation='payment_success_callback',
            error_message=str(e),
            resource_type='track',
            session_id=session_id
        )

        flash(f"Erreur lors de la vérification du paiement: {str(e)}", 'danger')
        return redirect(url_for('main.index'))
    except Exception as e:
        current_app.logger.error(f"Erreur traitement paiement: {e}", exc_info=True)

        #  LOG: Erreur générale lors du success callback
        log_stripe_error(
            operation='purchase_creation',
            error_message=str(e),
            resource_type='track',
            session_id=session_id
        )

        flash(f"Erreur lors du traitement de votre achat: {str(e)}", 'danger')
        return redirect(url_for('main.index'))


# ============================================
# ROUTE 6 : MES ACHATS
# ============================================

@payment_bp.route('/my-purchases')
@login_required
def my_purchases():
    """Redirige vers la page transactions avec l'onglet achats actif"""
    try:

        return redirect(url_for('payment.transactions') + '#purchases')
    except Exception as e:
        current_app.logger.warning(f'Rediction vers payment.transactions() impossible: {e}', exc_info=True)
        flash(f'accès impossible à vos achats', 'warning')
        return redirect(url_for('main.index'))


# ============================================
# ROUTE 7 : MES VENTES
# ============================================

@payment_bp.route('/my-sales')
@login_required
def my_sales():
    """Redirige vers la page transactions avec l'onglet ventes actif"""
    try:
        return redirect(url_for('payment.transactions') + '#sales')
    except Exception as e:
        current_app.logger.warning(f'Redirection vers payment.transactions() impossible: {e}', exc_info=True)
        flash(f'accès impossible à vos ventes', 'warning')
        return redirect(url_for('main.index'))



# ============================================
# ROUTE 8 : TÉLÉCHARGER ACHAT
# ============================================

@payment_bp.route('/download/purchase/<int:purchase_id>')
@login_required
@requires_ownership(PurchaseOwnership)
def download_purchase(purchase_id, purchase=None):
    """Télécharger le fichier acheté (MP3, WAV ou STEMS)"""

    # cherché via ownership_authorizer.py
    # purchase = Purchase.query.get_or_404(purchase_id)

    # # Vérifier les permissions
    # if current_user.id != purchase.buyer_id and not current_user.is_admin:
    #     abort(403)

    #  SÉCURITÉ: Vérifier que le paiement a bien été effectué auprès de Stripe
    # (protection légère contre manipulation BDD)
    if purchase.stripe_payment_intent_id:
        try:
            payment_intent = stripe.PaymentIntent.retrieve(purchase.stripe_payment_intent_id)
            if payment_intent.status != 'succeeded':
                flash(f" Le paiement n'a pas été confirmé (statut: {payment_intent.status}).", 'danger')
                return redirect(url_for('payment.my_purchases'))
        except stripe._error.StripeError as e:
            # Log l'erreur mais autorise le téléchargement (ne pas bloquer si Stripe API down)
            current_app.logger.error(f"Erreur verification Stripe pour purchase #{purchase_id}: {e}", exc_info=True)


    track = purchase.track
    
    # Déterminer le fichier à télécharger
    if purchase.format_purchased == 'mp3':
        file_path = track.file_mp3
    elif purchase.format_purchased == 'wav':
        file_path = track.file_wav
    elif purchase.format_purchased == 'stems':
        file_path = track.file_stems
    else:
        abort(404)
    
    if not file_path:
        flash(" Fichier non disponible.", 'danger')
        return redirect(url_for('payment.my_purchases'))

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        full_path = validate_static_path(file_path)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: purchase #{purchase_id}, path: {file_path}")
        flash(" Fichier introuvable sur le serveur.", 'danger')
        return redirect(url_for('payment.my_purchases'))
    
    # Nom du fichier pour le téléchargement
    clean_title = track.title.replace(' ', '_').lower()
    extension = file_path.rsplit('.', 1)[-1]
    download_name = f"{clean_title}_{purchase.format_purchased}.{extension}"
    
    return send_file(
        full_path,
        as_attachment=True,
        download_name=download_name
    )


# ============================================
# ROUTE 9 : TÉLÉCHARGER CONTRAT
# ============================================

@payment_bp.route('/download/contract/<int:purchase_id>')
@login_required
@requires_ownership(PurchaseOwnership)
def download_contract(purchase_id, purchase=None):
    """Télécharger le contrat PDF d'un achat"""
    

    
    # OUTDATED: Ownership decorator implemented; before was:
    # purchase = Purchase.query.get_or_404(purchase_id)
    # Vérifier les permissions (acheteur, vendeur ou admin)
    # if not (current_user.id == purchase.buyer_id or 
    #         current_user.id == purchase.track.composer_id or 
    #         current_user.is_admin):
    #     abort(403)
    
    if not purchase.contract_file:
        current_app.logger.warning(f"Tentative telechargement contrat inexistant pour purchase #{purchase_id}")
        flash("Contrat non disponible.", 'danger')
        return redirect(request.referrer or url_for('main.index'))

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        full_path = validate_static_path(purchase.contract_file)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: contract purchase #{purchase_id}, path: {purchase.contract_file}")
        flash("Contrat introuvable sur le serveur.", 'danger')
        return redirect(request.referrer or url_for('main.index'))
    
    # Nom du fichier pour le téléchargement
    clean_title = purchase.track.title.replace(' ', '_').lower()
    download_name = f"contrat_{clean_title}_{purchase.id}.pdf"
    
    return send_file(
        full_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/pdf'
    )


# ============================================
# ROUTE 10 : PAGE TRANSACTIONS COMPLÈTE
# ============================================

@payment_bp.route('/transactions')
@login_required
def transactions():
    """
    Page complète des transactions de l'utilisateur avec tous les historiques:
    - Achats de tracks
    - Ventes de tracks (pour beatmakers)
    - Toplines réalisées
    - Contrats signés
    - Mix/Master demandés
    - Favoris
    - Historique d'écoute (10 derniers tracks)
    """

    # ========== ACHATS ==========
    purchases = db.session.query(Purchase).filter_by(buyer_id=current_user.id).order_by(Purchase.created_at.desc()).all()

    # ========== VENTES ==========
    sales = db.session.query(Purchase).join(Track).filter(Track.composer_id == current_user.id).order_by(Purchase.created_at.desc()).all()
    total_revenue = sum(sale.composer_revenue for sale in sales)

    # ========== TOPLINES ==========
    # Toplines créées par l'utilisateur
    my_toplines = db.session.query(Topline).filter_by(artist_id=current_user.id).order_by(Topline.created_at.desc()).all()

    # ========== CONTRATS ==========
    # Contrats en tant qu'acheteur (client)
    contracts_as_buyer = db.session.query(Contract).filter_by(client_id=current_user.id).order_by(Contract.created_at.desc()).all()

    # Contrats en tant que vendeur (compositeur)
    contracts_as_seller = db.session.query(Contract).filter_by(composer_id=current_user.id).order_by(Contract.created_at.desc()).all()

    # ========== MIX/MASTER ==========
    # Demandes en tant qu'artiste
    mixmaster_requests_as_artist = db.session.query(MixMasterRequest).filter_by(artist_id=current_user.id).order_by(MixMasterRequest.created_at.desc()).all()

    # Demandes en tant qu'engineer
    mixmaster_requests_as_engineer = db.session.query(MixMasterRequest).filter_by(engineer_id=current_user.id).order_by(MixMasterRequest.created_at.desc()).all()

    # ========== FAVORIS ==========
    favorites = db.session.query(Favorite).filter_by(user_id=current_user.id).order_by(Favorite.created_at.desc()).all()

    # ========== HISTORIQUE D'ÉCOUTE (10 derniers tracks uniques) ==========
    # Récupérer l'historique en dédupliquant les tracks
    # On garde la dernière écoute pour chaque track unique
    listening_history_raw = (
        db.session.query(ListeningHistory).filter_by(user_id=current_user.id)
        .order_by(ListeningHistory.listened_at.desc())
        .all()
    )

    # Dédupliquer par track_id en gardant seulement la première occurrence (la plus récente)
    seen_tracks = set()
    listening_history = []
    for entry in listening_history_raw:
        if entry.track_id not in seen_tracks:
            seen_tracks.add(entry.track_id)
            listening_history.append(entry)
            if len(listening_history) >= 10:
                break

    return render_template(
        'transactions.html',
        purchases=purchases,
        sales=sales,
        total_revenue=total_revenue,
        my_toplines=my_toplines,
        contracts_as_buyer=contracts_as_buyer,
        contracts_as_seller=contracts_as_seller,
        mixmaster_requests_as_artist=mixmaster_requests_as_artist,
        mixmaster_requests_as_engineer=mixmaster_requests_as_engineer,
        favorites=favorites,
        listening_history=listening_history,
        now=datetime.now()
    )


# ============================================
# NOUVEAUX DASHBOARDS MÉTIERS
# ============================================

@payment_bp.route('/dashboard/artist')
@login_required
def artist_dashboard():
    """
    Dashboard Espace Artiste - Pour les interprètes/acheteurs
    Contenu : Favoris, Historique d'écoute, Toplines créées
    """
    if not current_user.is_artist:
        flash('Accès réservé aux artistes.', 'danger')
        return redirect(url_for('main.index'))

    # ========== FAVORIS ==========
    favorites = db.session.query(Favorite).filter_by(user_id=current_user.id)\
        .order_by(Favorite.created_at.desc()).all()

    # ========== HISTORIQUE D'ÉCOUTE (10 derniers tracks uniques) ==========
    listening_history_raw = (
        db.session.query(ListeningHistory).filter_by(user_id=current_user.id)
        .order_by(ListeningHistory.listened_at.desc())
        .all()
    )

    # Dédupliquer par track_id
    seen_tracks = set()
    listening_history = []
    for entry in listening_history_raw:
        if entry.track_id not in seen_tracks:
            seen_tracks.add(entry.track_id)
            listening_history.append(entry)
            if len(listening_history) >= 10:
                break

    # ========== TOPLINES CRÉÉES ==========
    my_toplines = db.session.query(Topline).filter_by(artist_id=current_user.id)\
        .order_by(Topline.created_at.desc()).all()

    return render_template(
        'dashboard_artist.html',
        favorites=favorites,
        listening_history=listening_history,
        my_toplines=my_toplines
    )


@payment_bp.route('/purchases')
@login_required
def purchases():
    """
    Page Achats en cours - Pour tous les utilisateurs
    Contenu : Beats achetés + Mix/Master en cours (en tant qu'artiste)
    """
    # ========== ACHATS DE BEATS ==========
    purchases_list = db.session.query(Purchase).filter_by(buyer_id=current_user.id)\
        .order_by(Purchase.created_at.desc()).all()

    # ========== DEMANDES MIX/MASTER (en tant qu'artiste) ==========
    my_requests = db.session.query(MixMasterRequest).filter_by(artist_id=current_user.id)\
        .order_by(MixMasterRequest.created_at.desc()).all()

    # Pour l'artiste : ajouter l'arborescence des fichiers de chaque archive
    requests_with_files = []
    for req in my_requests:
        req_data = {
            'request': req,
            'archive_tree': None
        }
        if req.original_file:
            from pathlib import Path
            archive_path = Path(current_app.root_path) / req.original_file
            if archive_path.exists():
                from utils.archive_utils import get_archive_file_tree
                req_data['archive_tree'] = get_archive_file_tree(str(archive_path))
        requests_with_files.append(req_data)

    return render_template(
        'purchases.html',
        purchases=purchases_list,
        my_requests=my_requests,
        requests_with_files=requests_with_files,
        now=datetime.now()
    )


@payment_bp.route('/dashboard/beatmaker')
@login_required
def beatmaker_dashboard():
    """
    Dashboard Espace Beatmaker - Pour les producteurs de beats
    Contenu : Stats revenus, Ventes, Beats uploadés avec formats disponibles
    """
    if not current_user.is_beatmaker:
        flash('Accès réservé aux beatmakers.', 'danger')
        return redirect(url_for('main.index'))

    # ========== VENTES ==========
    sales = db.session.query(Purchase).join(Track)\
        .filter(Track.composer_id == current_user.id)\
        .order_by(Purchase.created_at.desc()).all()

    # ========== STATS ==========
    total_revenue = sum(sale.composer_revenue for sale in sales)
    total_sales_count = len(sales)

    # ========== BEATS UPLOADÉS (avec formats disponibles) ==========
    my_tracks = db.session.query(Track).filter_by(composer_id=current_user.id)\
        .order_by(Track.created_at.desc()).all()

    # Compter les tracks approuvés et en attente
    tracks_approved = sum(1 for t in my_tracks if t.is_approved)
    tracks_pending = sum(1 for t in my_tracks if not t.is_approved)

    return render_template(
        'dashboard_beatmaker.html',
        sales=sales,
        total_revenue=total_revenue,
        total_sales_count=total_sales_count,
        my_tracks=my_tracks,
        tracks_approved=tracks_approved,
        tracks_pending=tracks_pending
    )


# ============================================
# WEBHOOK STRIPE
# ============================================

@payment_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """
    Webhook Stripe pour gérer les événements de paiement
    Cette route reçoit les notifications de Stripe (paiements, remboursements, etc.)
    """
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

    if not webhook_secret:
        current_app.logger.warning("STRIPE_WEBHOOK_SECRET n'est pas configuré")
        return {'status': 'error', 'message': 'Webhook secret not configured'}, 500

    try:
        # Vérifier la signature du webhook
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        # Payload invalide
        current_app.logger.error("Webhook: Invalid payload")
        return {'status': 'error', 'message': 'Invalid payload'}, 400
    except stripe.error.SignatureVerificationError:
        # Signature invalide
        current_app.logger.error("Webhook: Invalid signature")
        return {'status': 'error', 'message': 'Invalid signature'}, 400

    # Gérer les événements
    event_type = event['type']
    current_app.logger.info(f"Webhook reçu: {event_type}")

    # Événements liés aux Payment Intents
    if event_type == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        current_app.logger.info(f"Payment Intent succeeded: {payment_intent['id']}")
        #  LOG: Webhook event received
        log_stripe_transaction(
            operation='webhook_payment_intent_succeeded',
            resource_type='webhook',
            resource_id=payment_intent['id'],
            amount=payment_intent.get('amount'),
            stripe_payment_intent_id=payment_intent['id']
        )
        # Déjà géré côté serveur dans success_callback et download_processed

    elif event_type == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        current_app.logger.warning(f"Payment Intent failed: {payment_intent['id']}")
        #  LOG: Webhook payment failed
        log_stripe_error(
            operation='webhook_payment_intent_failed',
            error_message=payment_intent.get('last_payment_error', {}).get('message', 'Unknown error'),
            resource_type='webhook',
            resource_id=payment_intent['id']
        )
        # Potentiellement envoyer un email à l'utilisateur

    elif event_type == 'charge.succeeded':
        charge = event['data']['object']
        current_app.logger.info(f"Charge succeeded: {charge['id']}")
        #  LOG: Webhook charge succeeded
        log_stripe_transaction(
            operation='webhook_charge_succeeded',
            resource_type='webhook',
            resource_id=charge['id'],
            amount=charge.get('amount'),
            stripe_charge_id=charge['id']
        )

    elif event_type == 'charge.captured':
        charge = event['data']['object']
        current_app.logger.info(f"Charge captured: {charge['id']}")
        #  LOG: Webhook charge captured
        log_stripe_transaction(
            operation='webhook_charge_captured',
            resource_type='webhook',
            resource_id=charge['id'],
            amount=charge.get('amount'),
            stripe_charge_id=charge['id']
        )

    elif event_type == 'transfer.created':
        transfer = event['data']['object']
        current_app.logger.info(f"Transfer created: {transfer['id']}")
        #  LOG: Webhook transfer created
        log_stripe_transaction(
            operation='webhook_transfer_created',
            resource_type='webhook',
            resource_id=transfer['id'],
            amount=transfer.get('amount'),
            stripe_transfer_id=transfer['id'],
            destination=transfer.get('destination')
        )

    elif event_type == 'checkout.session.completed':
        session = event['data']['object']
        current_app.logger.info(f"Checkout session completed: {session['id']}")
        #  LOG: Webhook checkout completed
        log_stripe_transaction(
            operation='webhook_checkout_completed',
            resource_type='webhook',
            resource_id=session['id'],
            amount=session.get('amount_total'),
            stripe_session_id=session['id']
        )
        # Déjà géré dans success_callback

    else:
        current_app.logger.info(f"Événement non géré: {event_type}")

    return {'status': 'success'}, 200