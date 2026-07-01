"""
Service d'envoi d'emails pour LaProd
Gère l'envoi d'emails de vérification, notifications, et factures
"""
from flask import current_app, render_template


def _fe(path: str = '') -> str:
    """Construit une URL absolue vers le frontend Angular.
    Remplace url_for() — l'app est API-only, les routes Flask n'existent plus."""
    base = current_app.config.get('FRONTEND_URL', 'https://laprod.net')
    return f"{base.rstrip('/')}/{path.lstrip('/')}"
import extensions
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
import html as html_module
import os

from utils.invoice_generator import (
    generate_track_purchase_invoice,
    generate_track_sale_statement,
    generate_mixmaster_invoice,
    generate_mixmaster_earnings_statement,
)

# Instance globale de Flask-Mail (initialisée dans app.py)
mail = extensions.mail


# ============================================
# GÉNÉRATION DE TOKENS SÉCURISÉS
# ============================================

def generate_verification_token(email):
    """
    Génère un token de vérification d'email sécurisé

    Args:
        email: Adresse email à vérifier

    Returns:
        str: Token signé et sérialisé

    Example:
        token = generate_verification_token('user@example.com')
        # eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    """
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='email-verification-salt')


def verify_email_token(token, expiration=3600):
    """
    Vérifie un token de vérification d'email

    Args:
        token: Token à vérifier
        expiration: Durée de validité en secondes (défaut: 1h)

    Returns:
        str | None: Email si valide, None sinon

    Example:
        email = verify_email_token(token)
        if email:
            user.email_verified = True
    """
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(
            token,
            salt='email-verification-salt',
            max_age=expiration
        )
        return email
    except SignatureExpired:
        current_app.logger.warning(f"Token de vérification expiré")
        return None
    except BadSignature:
        current_app.logger.warning(f"Token de vérification invalide")
        return None


# ============================================
# ENVOI D'EMAILS
# ============================================

def send_email(subject, recipients, text_body, html_body, attachments=None):
    """
    Envoie un email avec support HTML + texte + pièces jointes

    Args:
        subject: Sujet de l'email
        recipients: Liste d'adresses email (ou string unique)
        text_body: Version texte brut de l'email
        html_body: Version HTML de l'email
        attachments: Liste de tuples (filename, content_type, data)

    Returns:
        bool: True si envoyé, False sinon

    Example:
        send_email(
            'Bienvenue sur LaProd',
            ['user@example.com'],
            'Bienvenue !',
            '<h1>Bienvenue !</h1>'
        )
    """
    try:
        # Normaliser recipients en liste
        if isinstance(recipients, str):
            recipients = [recipients]

        msg = Message(
            subject=subject,
            sender=current_app.config['MAIL_DEFAULT_SENDER'],
            recipients=recipients
        )
        msg.body = text_body
        msg.html = html_body

        # Ajouter les pièces jointes si présentes
        if attachments:
            for filename, content_type, data in attachments:
                msg.attach(filename, content_type, data)

        mail.send(msg)
        current_app.logger.info(f"Email envoyé: {subject} → {recipients}")
        return True

    except Exception as e:
        current_app.logger.error(f"Erreur envoi email: {e}", exc_info=True)
        return False


# ============================================
# EMAILS SPÉCIFIQUES - VÉRIFICATION
# ============================================

def send_verification_email(user):
    """
    Envoie un email de vérification à un nouvel utilisateur

    Args:
        user: Instance User (avec email)

    Returns:
        bool: True si envoyé, False sinon

    Example:
        # Dans routes/auth.py après inscription
        send_verification_email(new_user)
    """
    token = generate_verification_token(user.email)
    verification_url = _fe(f'verify-email?token={token}')

    # Texte brut
    text_body = f"""
Bonjour {user.username or 'nouvel utilisateur'},

Bienvenue sur LaProd !

Pour activer votre compte, veuillez cliquer sur ce lien :
{verification_url}

Ce lien expire dans 1 heure.

Si vous n'avez pas créé de compte sur LaProd, ignorez cet email.

---
L'équipe LaProd
https://laprod.net
"""

    # HTML
    html_body = render_template(
        'emails/verify_email.html',
        user=user,
        verification_url=verification_url
    )

    return send_email(
        subject='Vérifiez votre adresse email - LaProd',
        recipients=[user.email],
        text_body=text_body,
        html_body=html_body
    )


# ============================================
# EMAILS SPÉCIFIQUES - CHANGEMENT D'EMAIL
# ============================================

def generate_email_change_token(user_id, new_email):
    """génère un token pour changer l'email de l'utilisateur"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        return serializer.dumps({'user_id': user_id, 'new_email': new_email}, salt='email-change-salt')
    except Exception:
        current_app.logger.error("Erreur lors de la génération du token de changement d'email")
        return None

def verify_email_change_token(token, expiration=3600):
    """vérifie le token de changement d'email et retourne les données si le token est validé"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try :
        data = serializer.loads(token, salt='email-change-salt', max_age=expiration)
        return data['user_id'], data['new_email']
    except SignatureExpired:
        current_app.logger.warning(f"Token de changement d'email expiré")
        return None
    except (BadSignature, KeyError):
        current_app.logger.warning(f"Token de changement d'email invalide")
        return None
    
def send_email_change_verification_email(user, new_email):
    """Envoie un email de vérification pour le changement d'email"""
    token = generate_email_change_token(user.id, new_email)
    verification_url = _fe(f'/confirm-email-change?token={token}')
    html_body = render_template(
        'emails/confirm_email_change.html',
        user=user,
        verification_url=verification_url,
        new_email=new_email
    )
    text_body = f"""
Bonjour {user.username},
Vous avez demandé à changer votre adresse email pour {new_email}.
Pour confirmer ce changement, veuillez cliquer sur ce lien :
{verification_url}
Ce lien expire dans 1 heure.
Si vous n'avez pas demandé ce changement, ignorez cet email.
---
L'équipe LaProd
"""
    
    return send_email(
        subject='Vérification de changement d\'email - LaProd',
        recipients=[new_email],
        text_body=text_body,
        html_body=html_body
    )


    # ============================================
    # EMAILS SPÉCIFIQUES - RÉINITIALISATION DE MOT DE PASSE
    # ============================================
    
def generate_password_reset_token(user_id):
    """génère un token pour réinitialiser le mot de passe de l'utilisateur"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        return serializer.dumps({'user_id': user_id}, salt='password-reset-salt')
    except Exception:
        current_app.logger.error("Erreur lors de la génération du token de réinitialisation de mot de passe")
        return None


def send_password_reset_email(user):
    """
    Envoie un email de réinitialisation de mot de passe

    Args:
        user: Instance User
        reset_token: Token de réinitialisation

    Returns:
        bool: True si envoyé
    """
    reset_token = generate_password_reset_token(user.id)

    reset_url = _fe(f'/reset-password?token={reset_token}')

    text_body = f"""
Bonjour {user.username},

Vous avez demandé une réinitialisation de votre mot de passe.

Cliquez sur ce lien pour réinitialiser votre mot de passe :
{reset_url}

Ce lien expire dans 30 minutes.

Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/password_reset.html',
        user=user,
        reset_url=reset_url
    )

    return send_email(
        subject='Réinitialisation de mot de passe - LaProd',
        recipients=[user.email],
        text_body=text_body,
        html_body=html_body
    )

def verify_password_reset_token(token, expiration=1800):
    """vérifie le token de réinitialisation de mot de passe et retourne l'user_id si validé"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(token, salt='password-reset-salt', max_age=expiration)
        return data['user_id']
    except SignatureExpired:
        current_app.logger.warning(f"Token de réinitialisation de mot de passe expiré")
        return None
    except (BadSignature, KeyError):
        current_app.logger.warning(f"Token de réinitialisation de mot de passe invalide")
        return None


# ============================================
# EMAILS SPÉCIFIQUES - TRANSACTIONS
# ============================================

def send_purchase_confirmation_email(purchase):
    """
    Envoie un email de confirmation d'achat avec facture

    Args:
        purchase: Instance Purchase

    Returns:
        bool: True si envoyé
    """
    track = purchase.track
    buyer = purchase.buyer_user
    composer = purchase.track.composer_user

    text_body = f"""
Bonjour {buyer.username},

Votre achat a été confirmé !

Track : {track.title}
Artiste : {composer.username}
Format : {purchase.format_purchased.upper()}
Prix payé : {purchase.price_paid}€

Vous pouvez télécharger votre fichier depuis votre espace "Mes achats" :
{_fe('/dashboard')}

Merci pour votre confiance !

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/purchase_confirmation.html',
        purchase=purchase,
        track=track,
        buyer=buyer,
        composer=composer
    )

    attachments = []
    try:
        pdf = generate_track_purchase_invoice(purchase)
        attachments = [(f"facture_laprod_{purchase.id}.pdf", 'application/pdf', pdf)]
    except Exception as e:
        current_app.logger.error(f"Erreur génération facture achat #{purchase.id}: {e}")

    return send_email(
        subject=f'Achat confirmé - {track.title} - LaProd',
        recipients=[buyer.email],
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )


def send_sale_notification_email(purchase):
    """
    Notifie le compositeur d'une vente

    Args:
        purchase: Instance Purchase

    Returns:
        bool: True si envoyé
    """
    track = purchase.track
    composer = track.composer_user
    buyer = purchase.buyer_user

    text_body = f"""
Bonjour {composer.username},

Bonne nouvelle ! Votre track a été acheté.

Track : {track.title}
Acheteur : {buyer.username}
Format : {purchase.format_purchased.upper()}
Votre revenu : {purchase.composer_revenue}€

Ce montant a été ajouté à vos gains sur LaProd et sera disponible au retrait dans 7 jours.
Pour retirer vos gains, rendez-vous dans "Mes gains" et configurez votre compte Stripe Connect si ce n'est pas déjà fait.

Voir mes gains :
{url_for('wallet.mes_gains', _external=True)}

Félicitations !

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/sale_notification.html',
        purchase=purchase,
        track=track,
        composer=composer,
        buyer=buyer
    )

    attachments = []
    try:
        pdf = generate_track_sale_statement(purchase)
        attachments = [(f"releve_vente_laprod_{purchase.id}.pdf", 'application/pdf', pdf)]
    except Exception as e:
        current_app.logger.error(f"Erreur génération relevé vente #{purchase.id}: {e}")

    return send_email(
        subject=f'Vente confirmée - {track.title} - LaProd',
        recipients=[composer.email],
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )


def send_exclusive_sold_email(track, purchase):
    """Notifie le compositeur par email qu'un contrat exclusif a été signé."""
    composer = track.composer_user

    text_body = f"""
Bonjour {composer.username},

Votre track a été vendu en exclusivité.

Track       : {track.title}
Acheteur    : {purchase.buyer_user.username}
Montant reçu: {purchase.composer_revenue}€

Ce track est maintenant retiré de la vente sur LaProd.
Vous pouvez consulter vos revenus dans votre espace "Mes gains".

---
L'équipe LaProd
"""

    return send_email(
        subject=f'Contrat exclusif signé — {track.title} — LaProd',
        recipients=[composer.email],
        text_body=text_body,
        html_body=text_body,
    )


# ============================================
# EMAILS SPÉCIFIQUES - MIXMASTER
# ============================================

def send_mixmaster_request_notification(mixmaster_request):
    """
    Notifie l'engineer d'une nouvelle demande de mixage

    Args:
        mixmaster_request: Instance MixMasterRequest

    Returns:
        bool: True si envoyé
    """
    engineer = mixmaster_request.engineer
    artist = mixmaster_request.artist

    text_body = f"""
Bonjour {engineer.username},

Vous avez reçu une nouvelle demande de mixage/mastering !

Artiste : {artist.username}
Prix : {mixmaster_request.total_price}€
Services demandés : {', '.join([
    'Nettoyage' if mixmaster_request.service_cleaning else '',
    'Effets' if mixmaster_request.service_effects else '',
    'Artistique' if mixmaster_request.service_artistic else '',
    'Mastering' if mixmaster_request.service_mastering else ''
])}

Consultez la demande :
{url_for('mixmaster.dashboard', _external=True)}

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/mixmaster_request.html',
        mixmaster_request=mixmaster_request,
        engineer=engineer,
        artist=artist
    )

    attachments = []
    try:
        pdf = generate_mixmaster_invoice(mixmaster_request)
        attachments = [(f"facture_mixmaster_laprod_{mixmaster_request.id}.pdf", 'application/pdf', pdf)]
    except Exception as e:
        current_app.logger.error(f"Erreur génération facture mixmaster #{mixmaster_request.id}: {e}")

    return send_email(
        subject=f'Nouvelle demande de mixage - LaProd',
        recipients=[engineer.email],
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )


def send_mixmaster_status_update_email(mixmaster_request, old_status, new_status):
    """
    Notifie l'artiste et l'engineer d'un changement de statut

    Args:
        mixmaster_request: Instance MixMasterRequest
        old_status: Ancien statut
        new_status: Nouveau statut

    Returns:
        bool: True si envoyé
    """
    artist = mixmaster_request.artist
    engineer = mixmaster_request.engineer

    # Messages pour l'artiste
    artist_messages = {
        'awaiting_acceptance': 'Votre demande a été envoyée à l\'engineer. En attente de son acceptation.',
        'accepted': 'Votre demande a été acceptée ! Le mixage va commencer.',
        'rejected': 'Votre demande a été refusée. Vous avez été remboursé.',
        'processing': 'Votre mixage est en cours de traitement.',
        'delivered': 'Votre mixage est prêt ! Écoutez la preview et validez.',
        'revision1': f'Votre demande de révision 1 a été envoyée à {engineer.username}. L\'acompte passe à 40%.',
        'revision2': f'Votre demande de révision 2 (dernière) a été envoyée à {engineer.username}. L\'acompte passe à 50%.',
        'completed': 'Mixage terminé ! Téléchargez votre fichier final.',
        'refunded': 'Délai dépassé. Vous avez été remboursé intégralement.'
    }

    deposit_net = (mixmaster_request.deposit_amount   * Decimal('0.90')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    final_net   = (mixmaster_request.remaining_amount * Decimal('0.90')).quantize(Decimal('0.01'), ROUND_HALF_UP)

    # Messages pour l'engineer
    engineer_messages = {
        'awaiting_acceptance': f'{artist.username} vous a envoyé une demande de mix/master.',
        'accepted': f'Vous avez accepté la demande de {artist.username}. Vous avez 7 jours pour livrer.',
        'rejected': f'Vous avez refusé la demande de {artist.username}.',
        'delivered': f'Fichier livré à {artist.username}. Acompte de {deposit_net}€ ajouté à vos gains (disponible dans 7 jours).',
        'revision1': f'{artist.username} demande une révision. Consultez ses instructions et livrez dans les 7 jours.',
        'revision2': f'{artist.username} demande une 2ème révision (dernière). Consultez ses instructions et livrez dans les 7 jours.',
        'completed': f'{artist.username} a validé votre mix/master. Solde de {final_net}€ ajouté à vos gains (disponible dans 7 jours).',
        'refunded': f'La demande de {artist.username} a été annulée (délai dépassé).'
    }

    status_labels = {
        'awaiting_acceptance': 'En attente',
        'accepted': 'Acceptée',
        'rejected': 'Refusée',
        'processing': 'En cours',
        'delivered': 'Livrée',
        'revision1': 'Révision 1 demandée',
        'revision2': 'Révision 2 demandée',
        'completed': 'Terminée',
        'refunded': 'Remboursée'
    }

    # Extraire le dernier message de révision pour l'afficher dans l'email engineer
    revision_message = ''
    if new_status in ['revision1', 'revision2'] and mixmaster_request.artist_message:
        parts = mixmaster_request.artist_message.split('---REVISION_')
        if len(parts) > 1:
            last_part = parts[-1]
            # Retirer le header "N|dd/mm/yyyy HH:MM---\n"
            if '---\n' in last_part:
                revision_message = last_part.split('---\n', 1)[1].strip()

    artist_message = artist_messages.get(new_status, 'Statut mis à jour')
    status_label = status_labels.get(new_status, new_status)

    # Email à l'artiste
    artist_text = f"""
Bonjour {artist.username},

{artist_message}

Engineer : {engineer.username}
Demande #{mixmaster_request.id}

Consultez votre demande :
{url_for('mixmaster.dashboard', _external=True)}

---
L'équipe LaProd
"""

    artist_html = render_template(
        'emails/mixmaster_status_update.html',
        mixmaster_request=mixmaster_request,
        recipient_name=artist.username,
        artist=artist,
        engineer=engineer,
        old_status=old_status,
        new_status=new_status,
        message=artist_message,
        status_label=status_label,
        is_engineer=False,
        revision_message=revision_message
    )

    # Pièce jointe artiste : facture récapitulative si le contrat est terminé
    artist_attachments = []
    if new_status == 'completed':
        try:
            pdf = generate_mixmaster_invoice(mixmaster_request)
            artist_attachments = [(f"facture_finale_mixmaster_{mixmaster_request.id}.pdf", 'application/pdf', pdf)]
        except Exception as e:
            current_app.logger.error(f"Erreur facture finale artiste mixmaster #{mixmaster_request.id}: {e}")

    send_email(
        subject=f'Mix/Master #{mixmaster_request.id} - {status_label} - LaProd',
        recipients=[artist.email],
        text_body=artist_text,
        html_body=artist_html,
        attachments=artist_attachments,
    )

    # Email à l'engineer (pour les statuts pertinents)
    engineer_message = engineer_messages.get(new_status)
    if engineer_message:
        engineer_text = f"""
Bonjour {engineer.username},

{engineer_message}

Artiste : {artist.username}
Commande #{mixmaster_request.id}
{f'''
Instructions de révision :
{revision_message}
''' if revision_message else ''}
Consultez vos commandes :
{url_for('mixmaster.dashboard', _external=True)}

---
L'équipe LaProd
"""

        engineer_html = render_template(
            'emails/mixmaster_status_update.html',
            mixmaster_request=mixmaster_request,
            recipient_name=engineer.username,
            artist=artist,
            engineer=engineer,
            old_status=old_status,
            new_status=new_status,
            message=engineer_message,
            status_label=status_label,
            is_engineer=True,
            revision_message=revision_message
        )

        # Pièce jointe ingénieur : relevé de gains à chaque étape de versement
        _stage_map = {
            'delivered': 'deposit',
            'revision1': 'revision1',
            'revision2': 'revision2',
            'completed': 'final',
        }
        engineer_attachments = []
        if new_status in _stage_map:
            try:
                stage = _stage_map[new_status]
                pdf = generate_mixmaster_earnings_statement(mixmaster_request, stage)
                engineer_attachments = [(
                    f"releve_gains_{stage}_{mixmaster_request.id}.pdf",
                    'application/pdf',
                    pdf,
                )]
            except Exception as e:
                current_app.logger.error(
                    f"Erreur relevé gains ingénieur mixmaster #{mixmaster_request.id}: {e}"
                )

        send_email(
            subject=f'Mix/Master #{mixmaster_request.id} - {status_label} - LaProd',
            recipients=[engineer.email],
            text_body=engineer_text,
            html_body=engineer_html,
            attachments=engineer_attachments,
        )

    return True


# ============================================
# EMAILS SPÉCIFIQUES - MODÉRATION
# ============================================

def send_track_approved_email(track):
    """
    Notifie le compositeur que son track a été approuvé

    Args:
        track: Instance Track

    Returns:
        bool: True si envoyé
    """
    composer = track.composer_user

    text_body = f"""
Bonjour {composer.username},

Votre track "{track.title}" a été approuvé !

Il est maintenant visible sur LaProd et disponible à l'achat.

Voir mon track :
{url_for('main.track_detail', track_id=track.id, _external=True)}

Bonne chance pour vos ventes !

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/track_approved.html',
        track=track,
        composer=composer
    )

    return send_email(
        subject=f'Track approuvé - {track.title} - LaProd',
        recipients=[composer.email],
        text_body=text_body,
        html_body=html_body
    )


def send_track_rejected_email(track, reason=''):
    """
    Notifie le compositeur que son track a été rejeté

    Args:
        track: Instance Track
        reason: Raison du rejet (optionnel)

    Returns:
        bool: True si envoyé
    """
    composer = track.composer_user

    reason_text = f"\n\nRaison : {reason}" if reason else ""

    text_body = f"""
Bonjour {composer.username},

Votre track "{track.title}" n'a pas été approuvé.{reason_text}

Vous pouvez modifier et re-soumettre votre track.

Contactez-nous si vous avez des questions :
contact@laprod.net

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/track_rejected.html',
        track=track,
        composer=composer,
        reason=reason
    )

    return send_email(
        subject=f'Track non approuvé - {track.title} - LaProd',
        recipients=[composer.email],
        text_body=text_body,
        html_body=html_body
    )


# ============================================
# EMAILS SPÉCIFIQUES - TOKENS/QUOTAS
# ============================================

def send_wallet_warning_email(user):
    """
    Avertit un vendeur (beatmaker/mix engineer) qu'il a des fonds en attente
    depuis plus de 3 mois sans avoir configuré son compte Stripe Connect.
    Rappel : les fonds expirent après 2 ans (CGU).

    Args:
        user: Instance User

    Returns:
        bool: True si envoyé
    """
    wallet_url = url_for('wallet.mes_gains', _external=True)
    connect_url = url_for('stripe_connect.setup', _external=True)
    cgu_url = url_for('main.terms_of_service', _external=True)

    text_body = f"""
Bonjour {user.username},

Vous avez des gains en attente sur LaProd depuis plus de 3 mois, mais votre compte Stripe Connect n'est pas encore configuré.

Pour recevoir vos revenus sur votre compte bancaire, vous devez configurer votre compte Stripe Connect.
Sans action de votre part, vos fonds expireront après 2 ans (voir nos CGU).

Voir mes gains :
{wallet_url}

Configurer mon compte Stripe :
{connect_url}

Conditions générales (délais et expiration) :
{cgu_url}

---
L'équipe LaProd
"""

    html_body = f"""
<p>Bonjour {user.username},</p>
<p>Vous avez des gains en attente sur LaProd depuis plus de 3 mois, mais votre compte Stripe Connect n'est pas encore configuré.</p>
<p>Sans configuration, <strong>vos fonds expireront après 2 ans</strong> (<a href="{cgu_url}">voir CGU</a>).</p>
<p>
  <a href="{wallet_url}" style="background:#198754;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;">Voir mes gains</a>
  &nbsp;
  <a href="{connect_url}" style="background:#0d6efd;color:#fff;padding:8px 16px;border-radius:4px;text-decoration:none;">Configurer Stripe Connect</a>
</p>
<p style="color:#6c757d;font-size:0.9em;">L'équipe LaProd</p>
"""

    return send_email(
        subject='Action requise : configurez votre compte pour recevoir vos gains - LaProd',
        recipients=[user.email],
        text_body=text_body,
        html_body=html_body
    )


# ============================================
# EMAILS SPÉCIFIQUES - SUPPORT / CONTACT
# ============================================

def send_contact_support_email(user, subject, message, ref=''):
    """
    Envoie un message de support à contact@laprod.net
    et envoie un accusé de réception à l'utilisateur.

    Args:
        user: Instance User (expéditeur)
        subject: Sujet choisi par l'utilisateur
        message: Corps du message
        ref: Référence contextuelle (ex: "purchase_42")

    Returns:
        bool: True si les deux emails ont été envoyés
    """
    # Échapper les champs utilisateur pour le corps HTML (anti-injection)
    safe_username = html_module.escape(user.username)
    safe_subject  = html_module.escape(subject)
    safe_ref      = html_module.escape(ref or '—')
    safe_message  = html_module.escape(message).replace('\n', '<br>')

    support_text = (
        f"Utilisateur : {user.username} (#{user.id})\n"
        f"Email       : {user.email}\n"
        f"Référence   : {ref or '—'}\n\n"
        f"--- Message ---\n{message}"
    )
    support_html = (
        f"<strong>Utilisateur :</strong> {safe_username} (#{user.id})<br>"
        f"<strong>Email :</strong> {user.email}<br>"
        f"<strong>Référence :</strong> {safe_ref}<br><br>"
        f"<strong>--- Message ---</strong><br>{safe_message}"
    )

    ok1 = send_email(
        subject=f"[Support LaProd] {safe_subject}",
        recipients=['contact@laprod.net'],
        text_body=support_text,
        html_body=support_html,
    )

    confirm_text = (
        f"Bonjour {user.username},\n\n"
        f"Nous avons bien reçu votre message concernant :\n"
        f"« {subject} »\n\n"
        f"Notre équipe vous répondra dans les plus brefs délais.\n\n"
        f"---\n"
        f"L'équipe LaProd"
    )

    ok2 = send_email(
        subject="Votre message a été reçu — LaProd Support",
        recipients=[user.email],
        text_body=confirm_text,
        html_body=confirm_text.replace('\n', '<br>'),
    )

    return ok1 and ok2


def send_tokens_recharged_email(user, token_type='upload'):
    """
    Notifie l'utilisateur du rechargement de ses tokens

    Args:
        user: Instance User
        token_type: 'upload' ou 'topline'

    Returns:
        bool: True si envoyé
    """
    if token_type == 'upload':
        token_count = user.upload_track_tokens
        message = f"Vos tokens d'upload ont été rechargés ! Vous avez maintenant {token_count} tokens."
    else:
        token_count = user.topline_tokens
        message = f"Vos tokens de topline ont été rechargés ! Vous avez maintenant {token_count} tokens."

    text_body = f"""
Bonjour {user.username},

{message}

Profitez-en pour uploader vos créations !

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/tokens_recharged.html',
        user=user,
        token_type=token_type,
        token_count=token_count,
        message=message
    )

    return send_email(
        subject=f'Tokens rechargés - LaProd',
        recipients=[user.email],
        text_body=text_body,
        html_body=html_body
    )


def send_plan_changed_email(user, new_plan, expires_at=None, granted_by_admin=False):
    """
    Notifie l'utilisateur par email d'un changement de plan d'abonnement.

    Args:
        user: Instance User
        new_plan: Nouveau plan ('free' | 'amateur' | 'pro')
        expires_at: Date d'expiration (datetime) si applicable
        granted_by_admin: True si accordé manuellement par un admin
    """
    plan_labels = {'free': 'Free', 'amateur': 'LaProd+ Amateur', 'pro': 'LaProd+ Pro'}
    new_label   = plan_labels.get(new_plan, new_plan)
    expires_str = expires_at.strftime('%d/%m/%Y') if expires_at else ''

    if new_plan == 'free':
        subject   = 'Votre abonnement LaProd+ a été désactivé'
        text_body = f"""Bonjour {user.username},

Votre abonnement LaProd+ a été désactivé. Vous repassez en plan Free.

Vous pouvez vous réabonner à tout moment sur laprod.fr/premium.

---
L'équipe LaProd
"""
    else:
        admin_note = '\nCe plan vous a été accordé par l\'équipe LaProd.' if granted_by_admin else ''
        subject   = f'Votre plan {new_label} est actif !'
        text_body = f"""Bonjour {user.username},

Votre plan {new_label} est maintenant actif.{admin_note}
{"Valable jusqu'au : " + expires_str + '.' if expires_str else ''}

Profitez de toutes vos fonctionnalités sur laprod.fr.

---
L'équipe LaProd
"""

    html_body = render_template(
        'emails/plan_changed.html',
        user=user,
        new_plan=new_plan,
        new_label=new_label,
        expires_str=expires_str,
        granted_by_admin=granted_by_admin,
    )

    return send_email(
        subject=subject,
        recipients=[user.email],
        text_body=text_body,
        html_body=html_body,
    )


def send_audio_analysis_email(user, track, suggestions: dict):
    parts = []
    if 'bpm' in suggestions:
        parts.append(f"BPM détecté : {suggestions['bpm']}")
    if 'key' in suggestions:
        parts.append(f"Gamme détectée : {suggestions['key']}")
    if 'style' in suggestions:
        parts.append(f"Style suggéré : {suggestions['style']}")

    summary = '\n'.join(f'  • {p}' for p in parts)
    subject   = f'Analyse audio terminée — {track.title}'
    text_body = f"""Bonjour {user.username},

L'analyse audio de votre beat « {track.title} » est terminée.

Suggestions :
{summary}

Connectez-vous à votre tableau de bord pour valider ou modifier ces valeurs.

---
L'équipe LaProd
"""
    return send_email(
        subject=subject,
        recipients=[user.email],
        text_body=text_body,
    )


# ============================================
# EMAILS — CYCLE DE VIE DES LICENCES
# ============================================

def send_expiry_reminder_email(purchase, days_remaining: int):
    """Rappel d'expiration de licence (90 / 30 / 7 / 1 jours avant)."""
    buyer = purchase.buyer_user
    track = purchase.track
    track_title = track.title if track else f'Track #{purchase.track_id}'

    if days_remaining <= 1:
        urgency_line = "Votre licence expire demain !"
        urgency_subject = "expire demain"
    elif days_remaining <= 7:
        urgency_line = f"Votre licence expire dans {days_remaining} jours !"
        urgency_subject = f"expire dans {days_remaining} jours"
    else:
        urgency_line = f"Votre licence expire dans {days_remaining} jours."
        urgency_subject = f"expire dans {days_remaining} jours"

    expires_str = purchase.expires_at.strftime('%d/%m/%Y') if purchase.expires_at else '—'

    text_body = f"""Bonjour {buyer.username},

{urgency_line}

Track      : {track_title}
Format     : {purchase.format_purchased.upper() if purchase.format_purchased else '—'}
Expiration : {expires_str}

Pour conserver vos droits d'exploitation, renouvelez votre licence dès maintenant depuis votre espace :
{_fe('/licenses')}

Sans renouvellement, vos droits contractuels cesseront à la date d'expiration.
Vos enregistrements réalisés pendant la période de licence restent valides.

---
L'équipe LaProd
"""

    return send_email(
        subject=f'Votre licence {urgency_subject} — {track_title} — LaProd',
        recipients=[buyer.email],
        text_body=text_body,
    )


def send_sole_licensee_email(purchase):
    """Notification mensuelle : l'artiste est l'unique licencié actif."""
    buyer = purchase.buyer_user
    track = purchase.track
    track_title = track.title if track else f'Track #{purchase.track_id}'

    text_body = f"""Bonjour {buyer.username},

Ce mois-ci encore, vous êtes le seul titulaire d'une licence pour :

Track : {track_title}

Cette composition n'a pas été vendue à d'autres artistes. Vous bénéficiez d'une situation avantageuse — pensez à renouveler votre licence avant son expiration pour maintenir cet avantage.

Retrouvez le détail de vos licences ici :
{_fe('/licenses')}

---
L'équipe LaProd
"""

    return send_email(
        subject=f'Vous êtes le seul licencié — {track_title} — LaProd',
        recipients=[buyer.email],
        text_body=text_body,
    )


def send_renewal_confirmation_email(purchase):
    """Confirmation de renouvellement de licence (artiste)."""
    buyer = purchase.buyer_user
    track = purchase.track
    track_title = track.title if track else f'Track #{purchase.track_id}'

    expires_str = purchase.expires_at.strftime('%d/%m/%Y') if purchase.expires_at else 'à vie'
    duration_line = f"Nouvelle échéance : {expires_str}"

    text_body = f"""Bonjour {buyer.username},

Votre licence a été renouvelée avec succès !

Track    : {track_title}
Format   : {purchase.format_purchased.upper() if purchase.format_purchased else '—'}
{duration_line}

Vos droits d'exploitation sont prolongés. Vous pouvez consulter et télécharger votre nouveau contrat depuis votre espace licences :
{_fe('/licenses')}

Merci pour votre confiance !

---
L'équipe LaProd
"""

    attachments = []
    if purchase.contract_file:
        try:
            contract_path = purchase.contract_file
            if not contract_path.startswith('/'):
                contract_path = os.path.join(
                    current_app.config.get('UPLOAD_FOLDER', 'uploads'),
                    contract_path,
                )
            if os.path.exists(contract_path):
                with open(contract_path, 'rb') as f:
                    attachments = [(
                        f"contrat_renouvellement_{purchase.id}.pdf",
                        'application/pdf',
                        f.read(),
                    )]
        except Exception as e:
            current_app.logger.error(f"Erreur attach contrat renouvellement #{purchase.id}: {e}")

    return send_email(
        subject=f'Licence renouvelée — {track_title} — LaProd',
        recipients=[buyer.email],
        text_body=text_body,
        attachments=attachments,
    )
