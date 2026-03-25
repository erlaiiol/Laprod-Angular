"""
Blueprint CONTRACTS - Gestion des contrats d'exploitation musicale
Routes pour créer et gérer les contrats entre compositeurs et clients
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from datetime import datetime
from pathlib import Path

from extensions import db, limiter
from models import Track, User, Contract
from helpers import admin_required
from utils.ownership_authorizer import ContractOwnership, requires_ownership

# Import conditionnel pour la génération de contrats PDF
try:
    from utils.contract_generator import generate_contract_pdf
    CONTRACT_PDF_AVAILABLE = True
except ImportError:
    CONTRACT_PDF_AVAILABLE = False
    # Note: L'absence de contract_generator sera loggée si on tente de générer un PDF

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

contracts_bp = Blueprint('contracts', __name__, url_prefix='/contract')


# ============================================
# FONCTION HELPER : CALCUL PRIX CONTRAT
# ============================================

def calculate_contract_price(is_exclusive, mechanical_reproduction, 
                             public_show, streaming, arrangement):
    """
    Calcule le prix du contrat selon les droits sélectionnés
    SANS synchronization
    
    Grille de prix :
    - Licence exclusive : +150€
    - Reproduction mécanique : +50€
    - Diffusion publique : +20€
    - Streaming : +10€
    - Arrangement : +10€
    
    Prix maximum possible : 240€
    """
    price = 0
    
    if is_exclusive:
        price += 150
    
    if mechanical_reproduction:
        price += 50
    
    if public_show:
        price += 20
    
    if streaming:
        price += 10
    
    if arrangement:
        price += 10
    
    return price


# ============================================
# ROUTE 1 : AFFICHER LE FORMULAIRE
# ============================================

@contracts_bp.route('/admin/manual', methods=['GET'])
@login_required
@admin_required
def admin_manual_contract():
    """
    [ADMIN ONLY] Formulaire de création manuelle de contrat

    Permet à l'admin de créer manuellement un contrat pour corriger une erreur
    ou aider un utilisateur qui a rencontré un problème lors de l'achat.

    Étapes :
    1. Récupère toutes les tracks disponibles
    2. Récupère tous les utilisateurs
    3. Affiche le template avec ces données
    """

    # Récupérer toutes les tracks (approuvées et non-approuvées pour flexibilité admin)
    tracks = db.session.query(Track).order_by(Track.created_at.desc()).all()

    # Récupérer tous les utilisateurs actifs
    users = db.session.query(User).filter_by(account_status='active').order_by(User.username).all()

    # Afficher le template HTML et lui passer les variables
    return render_template('admin_manual_contract.html', tracks=tracks, users=users)


# ============================================
# ROUTE 2 : CRÉER LE CONTRAT
# ============================================

@contracts_bp.route('/create', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def create():
    """
    Crée un contrat d'autorisation d'exploitation

    Modes:
    - Normal: utilisateur crée via le flow d'achat (validation stricte du prix)
    - Admin: admin crée manuellement (bypass validation prix, accès total)
    """

    try:
        # Détection du mode admin
        is_admin_manual = request.form.get('admin_manual') == '1'

        if is_admin_manual and not current_user.is_admin:
            flash('Accès non autorisé', 'error')
            return redirect(url_for('main.index'))

        # ===== ÉTAPE 1 : RÉCUPÉRATION DES DONNÉES =====
        current_app.logger.info(f"Récupération des données du formulaire... (Mode: {'ADMIN' if is_admin_manual else 'NORMAL'})")

        # Références
        track_id = request.form.get('track_id', type=int)
        composer_id = request.form.get('composer_id', type=int)
        client_id = request.form.get('client_id', type=int)
        
        # Informations compositeur
        composer_address = request.form.get('composer_address', '').strip()
        composer_email = request.form.get('composer_email', '').strip()
        composer_credit = request.form.get('composer_credit', '').strip()
        
        # Informations interprète
        client_address = request.form.get('client_address', '').strip()
        client_email = request.form.get('client_email', '').strip()
        
        # Licence
        is_exclusive = request.form.get('is_exclusive') == 'on'

        # Durée et territoire
        territory = request.form.get('territory')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        duration_text = request.form.get('duration_text', '').strip()

        # Rémunération
        if is_admin_manual:
            # Mode admin: récupérer le prix saisi + pourcentage SACEM modifiable
            price_submitted = request.form.get('total_price', type=float)
            if price_submitted:
                price_submitted = int(price_submitted)  # Convertir en int
            percentage = request.form.get('percentage', type=int)  # Admin peut modifier le %
        else:
            # Mode normal: prix calculé automatiquement
            price_submitted = request.form.get('price', type=int)
            percentage = request.form.get('percentage', type=int)

        # Autorisations (4 droits - SANS synchronization)
        mechanical_reproduction = request.form.get('mechanical_reproduction') == 'on'
        public_show = request.form.get('public_show') == 'on'
        streaming = request.form.get('streaming') == 'on'
        arrangement = request.form.get('arrangement') == 'on'
        
        # Signature
        signature_place = request.form.get('signature_place', '').strip()
        signature_date = request.form.get('signature_date', '').strip()
        
        current_app.logger.debug(f"Données récupérées : Track #{track_id}, Prix: {price_submitted}€")
        
        # ===== ÉTAPE 2 : VALIDATION DE BASE =====
        current_app.logger.debug("Validation des données...")

        # Redirection selon le mode
        redirect_url = url_for('contracts.admin_manual_contract') if is_admin_manual else url_for('contracts.new')

        # Champs obligatoires (adapter selon le mode)
        if is_admin_manual:
            # En mode admin, composer_credit n'est pas requis
            required_fields = [track_id, composer_id, client_id, territory, start_date, end_date, price_submitted]
        else:
            required_fields = [track_id, composer_id, client_id, composer_email, composer_credit,
                             client_email, territory, start_date, end_date]

        if not all(required_fields):
            flash('Tous les champs obligatoires doivent être remplis.', 'error')
            return redirect(redirect_url)

        # Vérifier que compositeur ≠ interprète
        if composer_id == client_id:
            flash('Le compositeur et l\'interprète ne peuvent pas être la même personne.', 'error')
            return redirect(redirect_url)

        # Validation du pourcentage SACEM (max 85%)
        if percentage and percentage > 85:
            flash('Le pourcentage SACEM compositeur ne peut pas dépasser 85% (minimum 15% pour l\'acheteur).', 'error')
            return redirect(redirect_url)

        if percentage and percentage < 0:
            flash('Le pourcentage SACEM doit être entre 0 et 85%.', 'error')
            return redirect(redirect_url)

        # ===== ÉTAPE 3 : VALIDATION DU PRIX (SÉCURITÉ) =====
        current_app.logger.debug("Validation du prix...")

        if is_admin_manual:
            # Mode admin: bypass validation, accepter le prix saisi
            price = price_submitted
            current_app.logger.debug(f"[ADMIN] Prix manuel accepté: {price}€")
        else:
            # Mode normal: validation stricte du prix
            # Recalculer le prix côté serveur
            calculated_price = calculate_contract_price(
                is_exclusive,
                mechanical_reproduction,
                public_show,
                streaming,
                arrangement
            )

            current_app.logger.info(f"Prix calculé : {calculated_price}€, Prix soumis : {price_submitted}€")

            # Vérifier que le prix soumis correspond
            if price_submitted != calculated_price:
                current_app.logger.warning(
                    f"ALERTE : Prix manipulé ! "
                    f"Attendu: {calculated_price}€, Reçu: {price_submitted}€"
                )
                flash(
                    f'Erreur de calcul du prix. '
                    f'Prix attendu : {calculated_price}€, reçu : {price_submitted}€. '
                    f'Veuillez réessayer.',
                    'error'
                )
                return redirect(redirect_url)

            # Vérifier qu'au moins une autorisation est cochée
            if calculated_price == 0:
                flash('Vous devez sélectionner au moins une autorisation.', 'error')
                return redirect(redirect_url)

            # Utiliser le prix calculé (sécurisé)
            price = calculated_price
        
        current_app.logger.info(f"Prix validé : {price}€")
        
        # ===== ÉTAPE 4 : VALIDATION DES OBJETS =====
        current_app.logger.debug("Validation des objets en base de données...")
        
        track = db.session.get(Track, track_id)
        composer = db.session.get(User, composer_id)
        client = db.session.get(User, client_id)
        
        if not track:
            flash('Track introuvable.', 'error')
            return redirect(url_for('contracts.new'))
        
        if not composer or not client:
            flash('Compositeur ou interprète introuvable.', 'error')
            return redirect(url_for('contracts.new'))
        
        current_app.logger.debug("Objets validés")
        
        # ===== ÉTAPE 5 : RÉCUPÉRER LES POURCENTAGES SACEM =====
        # Stocker les pourcentages SACEM du track dans le contrat
        sacem_percentage_composer = track.sacem_percentage_composer
        sacem_percentage_buyer = track.get_sacem_percentage_buyer()
        
        # ===== ÉTAPE 6 : CRÉATION DU CONTRAT =====
        current_app.logger.info("Création du contrat en base de données...")
        
        new_contract = Contract(
            track_id=track_id,
            composer_id=composer_id,
            client_id=client_id,
            composer_address=composer_address or None,
            composer_email=composer_email,
            composer_credit=composer_credit,
            client_address=client_address or None,
            client_email=client_email,
            is_exclusive=is_exclusive,
            territory=territory,
            start_date=start_date,
            end_date=end_date,
            duration_text=duration_text or None,
            price=price,
            percentage=percentage,
            mechanical_reproduction=mechanical_reproduction,
            public_show=public_show,
            streaming=streaming,
            arrangement=arrangement,
            signature_place=signature_place or None,
            signature_date=signature_date or None,
            sacem_percentage_composer=sacem_percentage_composer,
            sacem_percentage_buyer=sacem_percentage_buyer
        )
        
        db.session.add(new_contract)
        db.session.flush()
        
        current_app.logger.info(f"Contrat créé avec ID: {new_contract.id}")
        
        # ===== ÉTAPE 7 : GÉNÉRATION DU PDF =====
        if CONTRACT_PDF_AVAILABLE:
            current_app.logger.info("Génération du PDF...")

            contracts_folder = current_app.config['CONTRACTS_FOLDER']
            filename = f"contract_{new_contract.id}_{track.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            output_path = contracts_folder / filename

            # Créer le dossier si nécessaire
            contracts_folder.mkdir(parents=True, exist_ok=True)
            
            # Préparer les données pour le générateur de PDF
            contract_data = {
                'track_title': track.title,
                'composer_name': composer.username,
                'composer_address': composer_address or '___________________________',
                'composer_email': composer_email,
                'composer_credit': composer_credit,
                'composer_signature': composer.signature or composer.username,
                'client_name': client.username,
                'client_address': client_address or '___________________________',
                'client_email': client_email,
                'client_signature': client.signature or client.username,
                'is_exclusive': is_exclusive,
                'start_date': start_date,
                'end_date': end_date,
                'duration_text': duration_text or '___________________________',
                'territory': territory,
                'mechanical_reproduction': mechanical_reproduction,
                'public_show': public_show,
                'streaming': streaming,
                'arrangement': arrangement,
                'price': price,
                'percentage': percentage,
                'signature_place': signature_place or '___________________',
                'signature_date': signature_date or datetime.now().strftime('%d/%m/%Y')
            }
            
            try:
                # Appeler le générateur de PDF (reportlab accepte string ou Path)
                generate_contract_pdf(str(output_path), contract_data)

                current_app.logger.info(f"PDF généré : {filename}")

                # Sauvegarder le nom du fichier dans la BDD
                new_contract.contract_file = f'contracts/{filename}'
                
            except Exception as e:
                current_app.logger.warning(f"Erreur génération PDF: {e}", exc_info=True)
                # Ne pas bloquer la création du contrat si le PDF échoue
        else:
            current_app.logger.warning("Module contract_generator non disponible, PDF non généré")

        # ===== ÉTAPE 8 : SAUVEGARDE FINALE =====
        db.session.commit()
        
        current_app.logger.info(f"Contrat #{new_contract.id} créé avec succès pour {price}€ !")
        
        flash(f'Contrat #{new_contract.id} créé avec succès pour {price}€ !', 'success')
        return redirect(url_for('contracts.success', contract_id=new_contract.id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur creation contrat: {str(e)}", exc_info=True)
        if output_path.exists():
            output_path.unlink()

        # Message d'erreur détaillé
        if 'database is locked' in str(e):
            error_msg = (
                "La base de données est temporairement occupée. "
                "Veuillez réessayer dans quelques secondes."
            )
        elif 'has no column' in str(e):
            error_msg = (
                "Erreur de structure de base de données. "
                "Veuillez contacter l'administrateur pour recréer la table Contract."
            )
        else:
            error_msg = f'Erreur lors de la création du contrat : {str(e)}'
        
        flash(error_msg, 'error')
        return redirect(url_for('contracts.new'))


# ============================================
# ROUTE 3 : PAGE DE SUCCÈS
# ============================================

@contracts_bp.route('/<int:contract_id>/success')
@login_required
@requires_ownership(ContractOwnership)
def success(contract_id, contract=None):
    """
    Page affichée après la création réussie d'un contrat
    """
    
    # Afficher la page de succès
    return render_template('contract_success.html', contract=contract)


# ============================================
# ROUTE 4 : ACHETER UN CONTRAT (redirect vers payment)
# ============================================

@contracts_bp.route('/buy/<int:track_id>', methods=['POST'])
@login_required
def buy_contract(track_id):
    """
    Initialise l'achat d'un contrat
    Redirige vers le système de paiement avec configuration du contrat
    """
    track = db.get_or_404(Track, track_id)
    
    # Vérifier que l'utilisateur n'achète pas son propre track
    if current_user.id == track.composer_id:
        flash("Vous ne pouvez pas acheter votre propre composition.", 'danger')
        return redirect(url_for('main.track_detail', track_id=track_id))
    
    # Récupérer le format depuis le formulaire
    format_type = request.form.get('format_type', 'mp3')
    
    # Rediriger vers le système de paiement
    return redirect(url_for('payment.contract_config', track_id=track_id, format_type=format_type))