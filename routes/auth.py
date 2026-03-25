"""
Blueprint Authentication - Login, Register, Logout
"""
import re
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from email_validator import validate_email, EmailNotValidError
import os
from datetime import datetime
from pathlib import Path
import config
from utils.file_validator import validate_image_file

from extensions import db, limiter, oauth
from models import User, PriceChangeRequest
from helpers import sanitize_html
from utils import email_service, notification_service

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

auth_bp = Blueprint('auth', __name__)

# ============================================
# ROUTE 1 : OAUTH LOGIN ROUTE
# ============================================

@auth_bp.route('/login/google')
def login_google():
    """Redirige vers Google OAuth (à implémenter)"""
    redirect_uri = url_for('auth.callback_google', _external=True)
    current_app.logger.info(f"login_google() (Oauth) redirect_uri passé à google: {redirect_uri}")
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route('/callback')
def callback_google():
    try:
        token = oauth.google.authorize_access_token()
        resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info = resp.json()

        google_id = user_info.get('sub')
        email = user_info.get('email')
        given_name = user_info.get('given_name')
        picture = user_info.get('picture')
        email_verified = user_info.get('email_verified', False)

        # ===== CAS 1 : Chercher par Google ID =====
        user = db.session.query(User).filter_by(google_id=google_id).first()

        if user:
            # ===== CAS 1A : User EXISTE DÉJÀ (google_id connu) =====
            # Simple login + mise à jour photo si changée
            
            if picture and user.profile_picture_url != picture:
                user.profile_picture_url = picture
                db.session.commit()
            
            login_user(user, remember=True)
            
            # Vérifications du statut
            if user.account_status == 'deleted':
                flash(' Compte supprimé.', 'danger')
                logout_user()
                return redirect(url_for('auth.login'))

            # Vérifier si profil complet (username obligatoire, signature recommandée)
            if not user.username:
                flash('️ Complétez votre profil pour continuer.', 'info')
                return redirect(url_for('auth.complete_profile'))

            if not user.user_type_selected:
                flash('️ Sélectionnez votre type de profil.', 'info')
                return redirect(url_for('auth.select_user_type'))

            flash(f' Bienvenue {user.username} !', 'success')
            return redirect(url_for('main.index'))
        
        else:
            # ===== CAS 2 : User N'EXISTE PAS (google_id inconnu) =====
            # Chercher par email pour éviter doublon
            
            user_by_email = db.session.query(User).filter_by(email=email).first()
            
            if user_by_email:
                # ===== CAS 2A : Email existe DÉJÀ =====
                
                if user_by_email.oauth_provider is None:
                    # Compte classique → LIER avec Google
                    user_by_email.google_id = google_id
                    user_by_email.oauth_provider = 'google'
                    user_by_email.profile_picture_url = picture
                    user_by_email.email_verified = user_by_email.email_verified or email_verified
                    if user_by_email.email_verified:
                        user_by_email.account_status = 'active'
                    db.session.commit()
                    
                    login_user(user_by_email, remember=True)
                    flash(f' Votre compte a été lié à Google !', 'success')
                    
                    if not user_by_email.user_type_selected:
                        return redirect(url_for('auth.select_user_type'))
                    
                    return redirect(url_for('main.index'))
                
                else:
                    # Déjà lié à un AUTRE OAuth (Facebook, etc.)
                    flash(f' Cet email est déjà lié à un compte {user_by_email.oauth_provider.capitalize()}.', 'warning')
                    return redirect(url_for('auth.login'))
            
            else:
                # ===== CAS 2B : NOUVEAU compte (email + google_id inconnus) =====
                new_user = User(
                    email=email,
                    username=None,  # Sera complété dans complete_profile
                    google_id=google_id,
                    oauth_provider='google',
                    profile_picture_url=picture,
                    email_verified=email_verified,
                    account_status='pending_completion'  # Force complétion profil
                )
                db.session.add(new_user)
                db.session.commit()
                db.session.refresh(new_user)

                login_user(new_user, remember=True)

                # Stocker le nom Google dans la session pour pré-remplir la signature
                if given_name:
                    # Sanitiser : strip, limiter longueur, supprimer caractères spéciaux
                    safe_name = re.sub(r'[^\w\s\-\']', '', given_name.strip())[:100]
                    session['suggested_signature'] = safe_name

                flash(' Compte créé avec Google ! Complétez votre profil.', 'success')
                return redirect(url_for('auth.complete_profile'))
        
    except Exception as e:
        # Logger l'erreur OAuth complète
        current_app.logger.error(
            f"Erreur OAuth Google: {type(e).__name__}: {str(e)}",
            exc_info=True
        )

        flash('Échec de la connexion Google. Réessayez ou contactez le support.', 'danger')
        return redirect(url_for('auth.login'))



@auth_bp.route('/complete-profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    """
    Compléter le profil après inscription OAuth
    Demande username + signature légale
    """
    # Si l'utilisateur a déjà un username (avec ou sans signature pour compatibilité), rediriger
    # Note: signature est devenue obligatoire mais on garde une compatibilité avec anciens comptes
    if current_user.username:
        if not current_user.user_type_selected:
            return redirect(url_for('auth.select_user_type'))
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        signature = request.form.get('signature', '').strip()
        accept_terms = request.form.get('accept_terms')

        # ===== VALIDATION USERNAME =====
        if not username or len(username) < 3 or len(username) > 20:
            flash(' Nom d\'utilisateur : 3-20 caractères requis.', 'danger')
            return redirect(url_for('auth.complete_profile'))

        # Vérifier unicité du username
        existing_user = db.session.query(User).filter_by(username=username).first()
        if existing_user and existing_user.id != current_user.id:
            flash(' Nom d\'utilisateur déjà pris.', 'danger')
            return redirect(url_for('auth.complete_profile'))

        # ===== VALIDATION SIGNATURE =====
        if not signature or len(signature) < 3:
            flash(' Signature légale requise (minimum 3 caractères).', 'danger')
            return redirect(url_for('auth.complete_profile'))

        # ===== VALIDATION CGU =====
        if not accept_terms:
            flash(' Vous devez accepter les conditions d\'utilisation.', 'danger')
            return redirect(url_for('auth.complete_profile'))

        # ===== COMPLÉTER LE PROFIL =====
        current_user.complete_profile(username, signature)
        db.session.commit()

        # Nettoyer la session (supprimer le nom suggéré)
        session.pop('suggested_signature', None)

        flash(f' Bienvenue {username} ! Sélectionnez maintenant votre type de profil.', 'success')
        return redirect(url_for('auth.select_user_type'))

    # GET : Afficher le formulaire avec nom suggéré si disponible
    suggested_name = session.get('suggested_signature', '')
    return render_template('complete_profile.html', suggested_name=suggested_name)
        

# Login route

@auth_bp.route('/login', methods=['GET', 'POST'])
# Changer limiter en prod
@limiter.limit("7 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    
    if request.method == 'POST':
        identifier = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False) == 'on'

        user = db.session.query(User).filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if user and user.oauth_provider:
            if not user.password_hash:
                return render_template('login.html',
                    show_set_password_link=True,
                    set_password_email=user.email
                )
        
        if user and user.check_password(password):
            if not user.email_verified:
                flash('Veuillez vérifier votre email avant de vous connecter. '
                '<a href="#" onclick="document.getElementById(\'resend-form\').submit(); return false;" class="alert-link">Renvoyer l\'email de vérification</a>', 
                'warning')

                return redirect(url_for('auth.login'))
            if user.account_status != 'active':
                flash('Compte désactivé.', 'danger')
                return redirect(url_for('auth.login'))

            login_user(user, remember=remember)
            flash(f'Bienvenue {user.username} !', 'success')

            # Rediriger vers sélection de type si pas encore fait
            if not user.user_type_selected:
                return redirect(url_for('auth.select_user_type'))

            return redirect(request.args.get('next') or url_for('main.index'))
        else:
            flash('Identifiants incorrects.', 'danger')
    
    return render_template('login.html')

@auth_bp.route('/resend-verification', methods=['POST'])
@limiter.limit("2 per hour")  # Max 2 par heure pour éviter spam
def resend_verification():
    """Renvoie l'email de vérification"""
    from utils import email_service
    from datetime import datetime, timedelta
    
    username = request.form.get('username')
    if not username:
        flash('Nom d\'utilisateur requis.', 'danger')
        return redirect(url_for('auth.login'))
    
    user = db.session.query(User).filter_by(username=username).first()
    
    if not user:
        flash('Utilisateur introuvable.', 'danger')
        return redirect(url_for('auth.login'))
    
    if user.email_verified:
        flash('Email déjà vérifié !', 'info')
        return redirect(url_for('auth.login'))
    
    # Vérifier si un email a été envoyé dans les 10 dernières minutes
    # (Tu peux ajouter un champ last_verification_email_sent dans le modèle User)
    # Pour l'instant, on envoie directement
    
    try:
        email_service.send_verification_email(user)
        flash('Email de vérification renvoyé ! Vérifiez votre boîte mail.', 'success')
    except Exception as e:
        current_app.logger.error(f"Erreur envoi email: {e}")
        flash('Erreur lors de l\'envoi. Réessayez plus tard.', 'danger')
    
    return redirect(url_for('auth.login'))


# register route

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        signature = request.form.get('signature')  # NOUVEAU

        if not password:
            flash('Le mot de passe est requis.', 'danger')
            return redirect(url_for('auth.register'))
        
        checks = [
            re.search(r"[a-z]", password),
            re.search(r"[A-Z]", password),
            re.search(r"[0-9]", password),
        ]

        try:
            email = validate_email(email).email
        except EmailNotValidError as e:
            flash(str(e), 'danger')
            return redirect(url_for('auth.register'))
        
        # Validations
        if len(username) < 3 or len(username) > 20:
            flash('Username trop court (min 3 caractères, max 20).', 'danger')
            return redirect(url_for('auth.register'))

        if not re.match(r'^[\w]+$', username):
                flash('Nom d\'utilisateur : lettres, chiffres et underscore uniquement.', 'danger')
                return redirect(url_for('auth.register'))
        
        if len(password) < 9:
            flash('Mot de passe trop court (min 9 caractères).', 'danger')
            return redirect(url_for('auth.register'))
        
        if not password == password_confirm:
            flash('Les mots de passe ne correspondent pas.', 'danger')
            return redirect(url_for('auth.register'))
        
        
        if not all(checks):
            flash('Mot de passe non conforme. Il doit contenir au moins une minuscule, une majuscule et un chiffre.', 'danger')
            return redirect(url_for('auth.register'))
        
        # Validation CGU
        accept_terms = request.form.get('accept_terms')
        if not accept_terms:
            flash('Vous devez accepter les conditions d\'utilisation.', 'danger')
            return redirect(url_for('auth.register'))

        # NOUVEAU : Validation de la signature
        if not signature or len(signature.strip()) == 0:
            flash('La signature est obligatoire.', 'danger')
            return redirect(url_for('auth.register'))
        
        if db.session.query(User).filter_by(username=username).first():
            flash('Username déjà pris.', 'danger')
            return redirect(url_for('auth.register'))
        
        if db.session.query(User).filter_by(email=email).first():
            flash('Email déjà utilisé.', 'danger')
            return redirect(url_for('auth.register'))
        
        new_user = User(
            username=username,
            email=email,
            signature=signature.strip(),
            terms_accepted_at=datetime.now()
        )
        new_user.set_password(password)

        try:
            db.session.add(new_user)
            db.session.commit()

            if not email_service.send_verification_email(new_user):
                flash('Erreur lors de l\'envoi de l\'email de vérification. Contactez le support.', 'danger')
                current_app.logger.error(f"Échec envoi email vérification pour user #{new_user.id}, {new_user.email}")
                return redirect(url_for('auth.register'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur création utilisateur : {e}", exc_info=True)
            flash('Erreur lors de la création du compte. Réessayez plus tard.', 'danger')
            return redirect(url_for('auth.register'))
        
        flash('Compté créé ! Un email de vérification a été envoyé à votre adresse. Veuillez valider votre inscription depuis votre boîte de réception pour vous connecter. Pensez à vérifier les spams.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('register.html')

@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    """Vérification de l'email via le token passé dans le lien"""

    email = email_service.verify_email_token(token)
    if not email:
        flash('Lien de vérification invalide ou expiré.', 'danger')
        return redirect(url_for('auth.login'))

    user = db.session.query(User).filter_by(email=email).first()
    if not user:
        flash('Utilisateur introuvable.', 'danger')
        return redirect(url_for('auth.register'))

    if user.email_verified:
        flash('Email déjà vérifié. Connectez-vous.', 'info')
        return redirect(url_for('auth.login'))

    user.email_verified = True
    user.account_status = 'active'
    db.session.commit()
    flash(' Email vérifié avec succès ! Vous pouvez maintenant vous connecter.', 'success')
    return render_template('verify_email_result.html', status='success', message="Votre adresse email a été vérifiée avec succès. Vous pouvez maintenant vous connecter.")

# logout route
@auth_bp.route('/logout')
@login_required
def logout():
    """Déconnexion"""
    logout_user()
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('main.index'))

# ============================================
# ROUTE 2 : ÉDITER PROFIL
# ============================================

@auth_bp.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Éditer son profil utilisateur"""
    if request.method == 'POST':
        #  SÉCURITÉ : Nettoyer la bio pour éviter XSS
        bio = sanitize_html(request.form.get('bio', '').strip())
        instagram = request.form.get('instagram', '').strip()
        twitter = request.form.get('twitter', '').strip()
        youtube = request.form.get('youtube', '').strip()
        soundcloud = request.form.get('soundcloud', '').strip()
        signature = request.form.get('signature', '').strip()

        # Récupérer les rôles
        is_artist = 'is_artist' in request.form
        is_beatmaker = 'is_beatmaker' in request.form
        is_mix_engineer = 'is_mix_engineer' in request.form

        # Détecter si l'utilisateur vient de cocher mix_engineer pour la première fois
        newly_mix_engineer = is_mix_engineer and not current_user.is_mix_engineer

        current_user.bio = bio if bio else None
        current_user.instagram = instagram if instagram else None
        current_user.twitter = twitter if twitter else None
        current_user.youtube = youtube if youtube else None
        current_user.soundcloud = soundcloud if soundcloud else None
        current_user.signature = signature if signature else None

        # Mettre à jour les rôles
        current_user.is_artist = is_artist
        current_user.is_beatmaker = is_beatmaker
        current_user.is_mix_engineer = is_mix_engineer

        # ===== GESTION DEMANDE CERTIFICATION PRODUCTEUR/ARRANGEUR =====
        if current_user.is_mixmaster_engineer:
            request_producer_arranger = request.form.get('request_producer_arranger')
            if request_producer_arranger and not current_user.is_certified_producer_arranger and not current_user.producer_arranger_request_submitted:
                current_user.producer_arranger_request_submitted = True
                flash(' Demande de certification Producteur/Arrangeur envoyée à l\'admin !', 'success')

        # ===== GESTION MODIFICATION PRIX MIX/MASTER ENGINEER =====
        # Si l'utilisateur est un engineer certifié et modifie ses prix
        if current_user.is_mixmaster_engineer:
            mixmaster_reference_price = request.form.get('mixmaster_reference_price', '').strip()
            mixmaster_price_min = request.form.get('mixmaster_price_min', '').strip()

            # Si au moins un prix est renseigné, valider et créer une nouvelle demande
            if mixmaster_reference_price or mixmaster_price_min:
                try:
                    # Valider que les deux sont fournis
                    if not (mixmaster_reference_price and mixmaster_price_min):
                        flash('Vous devez fournir à la fois le prix minimum et le prix de référence.', 'danger')
                        return redirect(url_for('auth.edit_profile'))

                    reference_price = float(mixmaster_reference_price)
                    price_min = float(mixmaster_price_min)

                    # Validation prix de référence
                    if reference_price < 10 or reference_price > 500:
                        flash('Le prix de référence doit être entre 10€ et 500€.', 'danger')
                        return redirect(url_for('auth.edit_profile'))

                    # Validation prix minimum (doit être au moins 35% du prix référence pour couvrir le service de base)
                    min_required = round(reference_price * 0.35)
                    if price_min < min_required:
                        flash(f'Le prix minimum doit être au moins {min_required}€ (35% du prix de référence pour couvrir le service "Nettoyage et équilibre").', 'danger')
                        return redirect(url_for('auth.edit_profile'))

                    # Vérifier que prix_min <= 65% du prix référence
                    if price_min > reference_price * 0.65:
                        max_allowed_min = round(reference_price * 0.65, 2)
                        flash(f'Le prix minimum ne peut pas dépasser 65% du prix de référence ({max_allowed_min}€).', 'danger')
                        return redirect(url_for('auth.edit_profile'))

                    # Arrondir les prix
                    reference_price = round(reference_price)
                    price_min = round(price_min)

                    # Vérifier si les prix ont vraiment changé
                    if reference_price != current_user.mixmaster_reference_price or price_min != current_user.mixmaster_price_min:
                        # CAS SPÉCIAL : Premier paramétrage de prix (old_price NULL)
                        # Dans ce cas, on définit les prix directement sans passer par validation admin
                        if current_user.mixmaster_reference_price is None or current_user.mixmaster_price_min is None:
                            current_user.mixmaster_reference_price = reference_price
                            current_user.mixmaster_price_min = price_min
                            flash(
                                f' Profil mis à jour ! Vos prix ont été définis : {price_min}€ - {reference_price}€ (référence)',
                                'success'
                            )
                        else:
                            # Prix déjà existants : créer une demande de modification
                            price_change_request = PriceChangeRequest(
                                engineer_id=current_user.id,
                                old_reference_price=current_user.mixmaster_reference_price,
                                old_price_min=current_user.mixmaster_price_min,
                                new_reference_price=reference_price,
                                new_price_min=price_min,
                                status='pending'
                            )
                            db.session.add(price_change_request)

                            flash(
                                f' Profil mis à jour ! Une demande de modification de prix ({price_min}€ - {reference_price}€ réf.) '
                                f'a été envoyée à l\'admin. Vos prix actuels restent actifs jusqu\'à validation.',
                                'success'
                            )

                except (ValueError, TypeError):
                    flash('Prix invalides. Veuillez entrer des nombres valides.', 'danger')
                    return redirect(url_for('auth.edit_profile'))

        # ===== GESTION IMAGE DE PROFIL =====
        profile_picture = request.files.get('profile_picture')
        if profile_picture and profile_picture.filename:
            is_valid, error_msg = validate_image_file(profile_picture)
            if not is_valid:
                flash(f'Image invalide : {error_msg}', 'danger')
                return redirect(url_for('auth.edit_profile'))

            # Déterminer l'extension depuis le nom de fichier original
            original_ext = Path(secure_filename(profile_picture.filename)).suffix.lower()
            allowed_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            if original_ext not in allowed_exts:
                original_ext = '.jpg'  # fallback sûr

            # Générer un nom de fichier unique
            filename = f"user_{current_user.id}_{uuid.uuid4().hex[:12]}{original_ext}"

            # Créer le dossier si nécessaire
            profiles_folder = config.PROFILES_FOLDER
            profiles_folder.mkdir(parents=True, exist_ok=True)

            # Supprimer l'ancienne image locale si ce n'est pas la photo par défaut
            old_image = current_user.profile_image
            if old_image and old_image != 'images/default_profile.png' and old_image.startswith('images/profiles/'):
                old_path = config.IMAGES_FOLDER.parent / old_image
                if old_path.exists():
                    try:
                        old_path.unlink()
                    except OSError:
                        pass

            # Sauvegarder le nouveau fichier
            profile_picture.seek(0)
            save_path = profiles_folder / filename
            profile_picture.save(str(save_path))

            current_user.profile_image = f"images/profiles/{filename}"

        db.session.commit()

        # Si l'utilisateur vient de cocher mix_engineer et n'a pas encore soumis d'échantillon
        if newly_mix_engineer and not current_user.mixmaster_sample_submitted:
            flash('Profil mis à jour ! Soumettez un échantillon pour être certifié Mix/Master Engineer.', 'success')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        flash(' Profil mis à jour avec succès !', 'success')
        return redirect(url_for('main.profile', username=current_user.username))

    return render_template('edit_profile.html')


# ============================================
# ROUTE 3 : SÉCURITÉ DU COMPTE
# ============================================

@auth_bp.route('/edit-profile/security', methods=['GET', 'POST'])
@login_required
def edit_profile_security():
    """Page de sécurité du compte : username, email, mot de passe"""
    if request.method == 'POST':

        # ============================
        # CAS SPÉCIAL : OAuth sans mot de passe → définir un premier mot de passe
        # ============================
        set_password = request.form.get('set_password', '')
        set_password_confirm = request.form.get('set_password_confirm', '')

        if set_password and current_user.oauth_provider and not current_user.password_hash:
            if len(set_password) < 9:
                flash('Mot de passe trop court (minimum 9 caractères).', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            if set_password != set_password_confirm:
                flash('Les mots de passe ne correspondent pas.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            checks = [
                re.search(r"[a-z]", set_password),
                re.search(r"[A-Z]", set_password),
                re.search(r"[0-9]", set_password),
            ]
            if not all(checks):
                flash('Le mot de passe doit contenir au moins une minuscule, une majuscule et un chiffre.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            current_user.set_password(set_password)
            db.session.commit()
            flash('Mot de passe défini ! Vous pouvez maintenant modifier vos paramètres de sécurité.', 'success')
            email_service.send_email(
                subject='Mot de passe défini pour votre compte LaProd',
                recipients=[current_user.email],
                text_body=f"Bonjour {current_user.username},\n\nUn mot de passe a été défini pour votre compte LaProd lié à {current_user.oauth_provider.capitalize()}.\n\nSi vous n'êtes pas à l'origine de cette action, veuillez contacter notre support immédiatement.\n\nL'équipe LaProd",
                html_body=f"""<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #16213e; padding: 30px; border-radius: 8px;">
                                <h2 style="color: #e94560;">Mot de passe défini pour votre compte LaProd</h2>
                                <p style="color: #b0b0b0;">Bonjour {current_user.username},</p>
                                <p style="color: #b0b0b0;">Un mot de passe a été défini pour votre compte LaProd lié à {current_user.oauth_provider.capitalize()}.</p>
                                <p style="color: #b0b0b0;">Si vous n'êtes pas à l'origine de cette action, veuillez contacter notre support immédiatement.</p>
                                <p style="color: #8899aa; font-size: 13px;">L'équipe LaProd</p>
                            </div>""")
            
            notification_service.send_notification(
                user_id=current_user.id,
                title='Mot de passe défini',
                message='Un mot de passe a été défini pour votre compte. Si ce n\'était pas vous, contactez le support.',
                type='system'
            )
            
            return redirect(url_for('auth.edit_profile_security'))

        # ============================
        # ÉTAPE 1 : Vérifier l'identité (mot de passe actuel)
        # ============================
        current_password = request.form.get('current_password', '')

        # Bloquer les comptes OAuth sans mot de passe
        if current_user.oauth_provider and not current_user.password_hash:
            flash('Vous devez d\'abord définir un mot de passe.', 'warning')
            return redirect(url_for('auth.edit_profile_security'))

        if not current_user.check_password(current_password):
            flash('Mot de passe actuel incorrect.', 'danger')
            return redirect(url_for('auth.edit_profile_security'))

        has_changes = False

        # ============================
        # ÉTAPE 2 : Changement username
        # ============================
        new_username = request.form.get('new_username', '').strip()
        if new_username and new_username != current_user.username:
            if len(new_username) < 3 or len(new_username) > 20:
                flash('Nom d\'utilisateur : 3-20 caractères requis.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            if not re.match(r'^[\w]+$', new_username):
                flash('Nom d\'utilisateur : lettres, chiffres et underscore uniquement.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            if db.session.query(User).filter_by(username=new_username).first():
                flash('Ce nom d\'utilisateur est déjà pris.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            current_user.username = new_username
            has_changes = True

        # ============================
        # ÉTAPE 3 : Changement mot de passe
        # ============================
        new_password = request.form.get('new_password', '')
        new_password_confirm = request.form.get('new_password_confirm', '')

        if new_password:
            if len(new_password) < 9:
                flash('Nouveau mot de passe trop court (minimum 9 caractères).', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            if new_password != new_password_confirm:
                flash('Les nouveaux mots de passe ne correspondent pas.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            checks = [
                re.search(r"[a-z]", new_password),
                re.search(r"[A-Z]", new_password),
                re.search(r"[0-9]", new_password),
            ]
            if not all(checks):
                flash('Le mot de passe doit contenir au moins une minuscule, une majuscule et un chiffre.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            current_user.set_password(new_password)
            has_changes = True

        # ============================
        # ÉTAPE 4 : Changement email (le plus délicat)
        # ============================
        new_email = request.form.get('new_email', '').strip()
        if new_email and new_email.lower() != current_user.email.lower():
            try:
                new_email = validate_email(new_email).email
            except EmailNotValidError:
                flash('Adresse email invalide.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            if db.session.query(User).filter_by(email=new_email).first():
                flash('Cet email est déjà utilisé par un autre compte.', 'danger')
                return redirect(url_for('auth.edit_profile_security'))

            # NE PAS changer l'email immédiatement
            email_service.send_email_change_verification_email(user=current_user, new_email=new_email)

            flash('Un email de vérification a été envoyé à votre nouvelle adresse. Le changement sera effectif après confirmation.', 'info')
            has_changes = True

        # ============================
        # ÉTAPE 5 : Sauvegarder
        # ============================
        if has_changes:
            db.session.commit()
            flash('Modifications enregistrées avec succès !', 'success')
        else:
            flash('Aucune modification détectée.', 'info')

        return redirect(url_for('main.profile', username=current_user.username))

    return render_template('edit_profile_security.html')


# ====================================================================================================
# Changement d'EMAIL : Confirmation via lien dans l'email (Les infos commit via le lien de l'email)
# ====================================================================================================

@auth_bp.route('/confirm-email-change/<token>')
def confirm_email_change(token):
    """Confirme le changement d'email après clic sur le lien de vérification"""
    result = email_service.verify_email_change_token(token)

    user_id, new_email = result if result else (None, None)

    user = db.session.get(User, user_id) if user_id else None

    if not result:
        flash('Lien de confirmation invalide ou expiré.', 'danger')
        return redirect(url_for('main.index'))

    # Vérifier que l'email n'est pas déjà pris (entre-temps)
    if db.session.query(User).filter_by(email=new_email).first():
        flash('Cette adresse email est déjà utilisée par un autre compte.', 'danger')
        return redirect(url_for('main.index'))

    user.email = new_email
    user.email_verified = True
    db.session.commit()

    flash(f'Adresse email mise à jour vers {new_email} !', 'success')
    return render_template('verify_email_change.html')


# ===============================================================================================
# MOT DE PASSE OUBLIÉ : Demande de réinitialisation + Réinitialisation via lien dans l'email
# ===============================================================================================

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Page de demande de réinitialisation du mot de passe"""
    if request.method == 'POST' :
        email = request.form.get('email', '').strip()

        try:
            user = db.session.query(User).filter_by(email=email).first()
            if user:
                email_service.send_password_reset_email(user)
            # Afficher un message générique pour éviter de révéler l'existence du compte
            flash('Si un compte avec cet email existe, un lien de réinitialisation a été envoyé.', 'info')
            return redirect(url_for('auth.login'))
        except Exception as e:
            current_app.logger.error(f"Erreur lors de l'envoi de l'email de réinitialisation pour {email}: {e}", exc_info=True)
            flash('Une erreur est survenue. Réessayez plus tard.', 'danger')
            return redirect(url_for('auth.forgot_password'))
        
    return render_template('forgot_password.html')

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_via_email(token):
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        new_password_confirm = request.form.get('new_password_confirm')

        checks = [
            re.search(r"[a-z]", new_password),
            re.search(r"[A-Z]", new_password),
            re.search(r"[0-9]", new_password),
        ]

        if len(new_password) < 9:
            flash('Nouveau mot de passe trop court (min 9 caractères).', 'danger')
            return redirect(url_for('auth.reset_password_via_email', token=token))

        if not all(checks):
            flash('Le nouveau mot de passe doit contenir au moins une minuscule, une majuscule et un chiffre.', 'danger')
            return redirect(url_for('auth.reset_password_via_email', token=token))
        
        if new_password != new_password_confirm:
            flash('Les nouveaux mots de passe ne correspondent pas.', 'danger')
            return redirect(url_for('auth.reset_password_via_email', token=token))
        
        try:
            user_id = email_service.verify_password_reset_token(token)
            if not user_id:
                flash('Lien de réinitialisation invalide ou expiré.', 'danger')
                return redirect(url_for('auth.forgot_password'))
            
            user_to_update = db.session.get(User, user_id)

            if not user_to_update:
                flash('Lien de réinitialisation invalide ou expiré.', 'danger')
                return redirect(url_for('auth.forgot_password'))

            user_to_update.set_password(new_password)
            db.session.commit()
            flash(' Mot de passe mis à jour avec succès ! Vous pouvez maintenant vous connecter.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur lors de la réinitialisation du mot de passe pour l'utilisateur #{user_to_update.id}: {e}", exc_info=True)
            flash('Une erreur est survenue lors de la mise à jour du mot de passe. Réessayez plus tard.', 'danger')
            return redirect(url_for('auth.reset_password_via_email', token=token))
        
    return render_template('reset_password.html')

# ============================================
# SÉLECTION DES TYPES D'UTILISATEUR
# ============================================

@auth_bp.route('/select-user-type', methods=['GET', 'POST'])
@login_required
def select_user_type():
    """Page de sélection des types d'utilisateur (obligatoire après inscription)"""
    if request.method == 'POST':
        is_artist = 'is_artist' in request.form
        is_beatmaker = 'is_beatmaker' in request.form
        is_mix_engineer = 'is_mix_engineer' in request.form

        # Au moins un rôle doit être sélectionné
        if not (is_artist or is_beatmaker or is_mix_engineer):
            flash('Vous devez sélectionner au moins un rôle.', 'danger')
            return redirect(url_for('auth.select_user_type'))

        # Mettre à jour l'utilisateur
        current_user.is_artist = is_artist
        current_user.is_beatmaker = is_beatmaker
        current_user.is_mix_engineer = is_mix_engineer
        current_user.user_type_selected = True

        db.session.commit()

        # Si mix/master engineer sélectionné, rediriger vers page de soumission échantillon
        if is_mix_engineer:
            flash('Profil mis à jour ! Soumettez un échantillon pour être certifié.', 'success')
            return redirect(url_for('auth.submit_mixmaster_sample'))
        else:
            flash('Profil mis à jour avec succès !', 'success')
            return redirect(url_for('main.index'))

    return render_template('select_user_type.html')


# ============================================
# SOUMISSION ÉCHANTILLON MIX/MASTER
# ============================================

@auth_bp.route('/submit-mixmaster-sample', methods=['GET', 'POST'])
@login_required
def submit_mixmaster_sample():
    """Page de soumission d'échantillon pour devenir mix/master engineer certifié"""

    # Vérifier que l'utilisateur a sélectionné le rôle mix/master engineer
    if not current_user.is_mix_engineer:
        flash('Vous devez sélectionner le rôle "Mix/Master Engineer" pour accéder à cette page.', 'danger')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        mixmaster_reference_price = request.form.get('mixmaster_reference_price')
        mixmaster_price_min = request.form.get('mixmaster_price_min')
        mixmaster_bio = request.form.get('mixmaster_bio', '').strip()

        # Validation du prix de référence
        try:
            reference_price = float(mixmaster_reference_price)
            if reference_price < 10 or reference_price > 500:
                flash('Le prix de référence doit être entre 10€ et 500€.', 'danger')
                return redirect(url_for('auth.submit_mixmaster_sample'))
        except (ValueError, TypeError):
            flash('Prix de référence invalide.', 'danger')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        # Validation du prix minimum
        try:
            price_min = float(mixmaster_price_min)
            min_required = round(reference_price * 0.20)
            if price_min < min_required:
                flash(f'Le prix minimum doit être au moins {min_required}€ (20% du prix de référence).', 'danger')
                return redirect(url_for('auth.submit_mixmaster_sample'))
            # Vérifier que le prix min <= 65% du prix référence
            if price_min > reference_price * 0.65:
                max_allowed_min = round(reference_price * 0.65, 2)
                flash(f'Le prix minimum ne peut pas dépasser 65% du prix de référence ({max_allowed_min}€).', 'danger')
                return redirect(url_for('auth.submit_mixmaster_sample'))
        except (ValueError, TypeError):
            flash('Prix minimum invalide.', 'danger')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        # Validation des fichiers
        if 'sample_raw' not in request.files or 'sample_processed' not in request.files:
            flash('Vous devez envoyer les 2 fichiers audio.', 'danger')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        sample_raw_file = request.files['sample_raw']
        sample_processed_file = request.files['sample_processed']

        if sample_raw_file.filename == '' or sample_processed_file.filename == '':
            flash('Les 2 fichiers sont requis.', 'danger')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        # Vérifier les extensions
        allowed_extensions = {'wav', 'mp3'}

        def allowed_file(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

        if not allowed_file(sample_raw_file.filename) or not allowed_file(sample_processed_file.filename):
            flash('Format non autorisé. Utilisez .wav ou .mp3', 'danger')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        # Vérifier la taille des fichiers (max 50MB)
        MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

        def validate_file_size(file):
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            return size <= MAX_FILE_SIZE

        if not validate_file_size(sample_raw_file) or not validate_file_size(sample_processed_file):
            flash('Un des fichiers est trop volumineux. Maximum 50MB par fichier.', 'danger')
            return redirect(url_for('auth.submit_mixmaster_sample'))

        # Sauvegarder les fichiers
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Utiliser le dossier défini dans config.py
        config.MIXMASTER_SAMPLES_FOLDER.mkdir(parents=True, exist_ok=True)

        # Fichier brut
        raw_filename = secure_filename(sample_raw_file.filename)
        unique_raw_filename = f"{current_user.id}_{timestamp}_raw_{raw_filename}"
        raw_disk_path = config.MIXMASTER_SAMPLES_FOLDER / unique_raw_filename
        sample_raw_file.save(raw_disk_path)

        # Chemin web pour la BDD (as_posix() force les / même sur Windows)
        raw_web_path = Path('static', 'mixmaster', 'samples', unique_raw_filename).as_posix()

        # Fichier traité
        processed_filename = secure_filename(sample_processed_file.filename)
        unique_processed_filename = f"{current_user.id}_{timestamp}_processed_{processed_filename}"
        processed_disk_path = config.MIXMASTER_SAMPLES_FOLDER / unique_processed_filename
        sample_processed_file.save(processed_disk_path)

        # Chemin web pour la BDD (as_posix() force les / même sur Windows)
        processed_web_path = Path('static', 'mixmaster', 'samples', unique_processed_filename).as_posix()

        # Mettre à jour l'utilisateur (stocker chemins web en BDD)
        current_user.mixmaster_reference_price = reference_price
        current_user.mixmaster_price_min = price_min
        current_user.mixmaster_bio = mixmaster_bio
        current_user.mixmaster_sample_raw = raw_web_path
        current_user.mixmaster_sample_processed = processed_web_path
        current_user.mixmaster_sample_submitted = True

        db.session.commit()

        flash('Échantillon soumis avec succès ! Notre équipe va évaluer votre travail.', 'success')
        return redirect(url_for('main.index'))

    return render_template('submit_mixmaster_sample.html')