"""
Service de notifications in-app pour LaProd
Crée des notifications visibles dans l'interface utilisateur
"""
from flask import current_app, url_for
from extensions import db
from models import Notification, User


# ============================================
# CRÉATION DE NOTIFICATIONS
# ============================================

def create_notification(user_id, notif_type, title, message, link=None):
    """
    Crée une notification in-app pour un utilisateur

    Args:
        user_id: ID de l'utilisateur destinataire
        notif_type: Type de notification (purchase, sale, track_approved, etc.)
        title: Titre court de la notification
        message: Message détaillé
        link: URL vers la ressource (optionnel)

    Returns:
        Notification: Instance créée

    Example:
        create_notification(
            user_id=user.id,
            notif_type='purchase',
            title='Achat confirmé',
            message='Votre achat de "Beat1" a été confirmé',
            link=url_for('payment.my_purchases')
        )
    """
    try:
        notification = Notification(
            user_id=user_id,
            type=notif_type,
            title=title,
            message=message,
            link=link
        )
        db.session.add(notification)
        # Pas de commit ici : la route appelante gère la transaction
        # La notification sera commitée avec le reste (achat, token, etc.)

        current_app.logger.info(
            f"Notification créée: type={notif_type}, user_id={user_id}, title={title}"
        )

        return notification

    except Exception as e:
        current_app.logger.error(f"Erreur création notification: {e}", exc_info=True)
        return None


def get_unread_count(user_id):
    """
    Compte les notifications non lues d'un utilisateur

    Args:
        user_id: ID de l'utilisateur

    Returns:
        int: Nombre de notifications non lues

    Example:
        unread_count = get_unread_count(current_user.id)
        # Afficher badge avec ce nombre
    """
    return db.session.query(Notification).filter_by(
        user_id=user_id,
        is_read=False
    ).count()


def mark_all_as_read(user_id):
    """
    Marque toutes les notifications d'un utilisateur comme lues

    Args:
        user_id: ID de l'utilisateur

    Returns:
        int: Nombre de notifications marquées comme lues
    """
    try:
        from datetime import datetime

        notifications = db.session.query(Notification).filter_by(
            user_id=user_id,
            is_read=False
        ).all()

        count = len(notifications)

        for notif in notifications:
            notif.is_read = True
            notif.read_at = datetime.now()

        current_app.logger.info(f"Marqué {count} notifications comme lues pour user #{user_id}")
        return count

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur marquage notifications: {e}", exc_info=True)
        return 0


def get_recent_notifications(user_id, limit=10, include_read=False):
    """
    Récupère les notifications récentes d'un utilisateur

    Args:
        user_id: ID de l'utilisateur
        limit: Nombre maximum de notifications
        include_read: Inclure les notifications lues (défaut: False)

    Returns:
        list[Notification]: Liste des notifications
    """
    query = db.session.query(Notification).filter_by(user_id=user_id)

    if not include_read:
        query = query.filter_by(is_read=False)

    return query.order_by(Notification.created_at.desc()).limit(limit).all()


# ============================================
# NOTIFICATIONS SPÉCIFIQUES - ACHATS/VENTES
# ============================================

def notify_purchase_confirmed(purchase):
    """
    Notifie l'acheteur que son achat de beat est confirmé

    Args:
        purchase: Instance Purchase
    """
    track = purchase.track

    create_notification(
        user_id=purchase.buyer_id,
        notif_type='purchase',
        title='Achat confirmé',
        message=f'Votre achat de "{track.title}" ({purchase.format_purchased}) a été confirmé. Vous pouvez maintenant le télécharger.',
        link=url_for('payment.my_purchases')
    )


def notify_sale_completed(purchase):
    """
    Notifie le compositeur qu'une vente de beat a été réalisée.
    Les fonds sont créditées dans son wallet (disponibles après 7 jours).
    """
    track = purchase.track

    create_notification(
        user_id=track.composer_id,
        notif_type='Beat - Vente',
        title='Vente confirmée !',
        message=f'"{track.title}" acheté par {purchase.buyer_user.username}. {purchase.composer_revenue}€ ajoutés à vos gains (disponibles dans 7 jours).',
        link=url_for('wallet.mes_gains')
    )


# ============================================
# NOTIFICATIONS SPÉCIFIQUES - MODÉRATION
# ============================================

def notify_track_approved(track):
    """
    Notifie le compositeur que son track a été approuvé

    Args:
        track: Instance Track
    """
    create_notification(
        user_id=track.composer_id,
        notif_type='track_approved',
        title='Track approuvé !',
        message=f'Votre track "{track.title}" a été approuvé et est maintenant visible sur LaProd.',
        link=url_for('main.track_detail', track_id=track.id)
    )


def notify_track_rejected(track, reason=''):
    """
    Notifie le compositeur que son track a été rejeté

    Args:
        track: Instance Track
        reason: Raison du rejet (optionnel)
    """
    message = f'Votre track "{track.title}" n\'a pas été approuvé.'
    if reason:
        message += f' Raison : {reason}'

    create_notification(
        user_id=track.composer_id,
        notif_type='track_rejected',
        title='Track non approuvé',
        message=message,
        link=url_for('main.profile', username=track.composer_user.username)
    )


# ============================================
# NOTIFICATIONS SPÉCIFIQUES - MIXMASTER
# ============================================

def notify_mixmaster_request_received_and_sent(mixmaster_request):
    """
    Notifie l'engineer (demande reçue) et l'artiste (demande envoyée, somme bloquée)

    Args:
        mixmaster_request: Instance MixMasterRequest
    """
    artist = mixmaster_request.artist

    create_notification(
        user_id=mixmaster_request.engineer_id,
        notif_type='mixmaster_request_received',
        title='Nouvelle demande de mixage reçue',
        message=f'{artist.username} vous a envoyé une demande de mixage pour {mixmaster_request.total_price}€.',
        link=url_for('mixmaster.dashboard')
    )

    create_notification(
        user_id=mixmaster_request.artist_id,
        notif_type='mixmaster_request_sent',
        title='Demande de mixage envoyée avec succès',
        message=f'Votre demande de mixage a été envoyée à {mixmaster_request.engineer.username}, somme bloquée: {mixmaster_request.total_price}€',
        link=url_for('payment.purchases')
    )

def notify_mixmaster_status_changed(mixmaster_request, old_status, new_status):
    """
    Notifie l'artiste d'un changement de statut de sa demande

    Args:
        mixmaster_request: Instance MixMasterRequest
        old_status: Ancien statut
        new_status: Nouveau statut
    """
    engineer = mixmaster_request.engineer
    artist = mixmaster_request.artist

    status_messages = {
        'artist': {
            'accepted': f"{engineer.username} a accepté votre demande ! Le mixage est en cours. 1 semaine avant livraison ou vous serez remboursé automatiquement",
            'rejected': f"{engineer.username} a refusé votre demande. Vous avez été remboursé automatiquement.",
            'processing': "Votre mixage est en cours de traitement.",
            'delivered': f"Votre mixage est prêt ! Écoutez la preview et validez. Acompte de 30% versé: {mixmaster_request.deposit_amount:.2f}€",
            'completed': f"Mixage terminé ! Téléchargez votre fichier final. Paiement final envoyé: {mixmaster_request.total_price:.2f}€. Plus de remboursement automatique possible. Contactez le support en cas de problème.",
            'refunded': f"Délai dépassé ou annulation. Vous êtes en cours de remboursement intégral. {mixmaster_request.total_price:.2f}€. Contactez le support en cas de problème.",
        },
        'engineer': {
            'accepted': f"Vous avez accepté la demande de {artist.username}. 1 semaine pour livrer.",
            'rejected': f"Vous avez refusé la demande de {artist.username}. Artiste remboursé automatiquement.",
            'processing':  f"Mixage en cours pour {artist.username}.",
            'delivered': f"Mixage livré à {artist.username}. Acompte de {round(float(mixmaster_request.deposit_amount)*0.90,2)}€ ajouté à vos gains (dispo dans 7j).",
            'completed': f"Mixage validé par {artist.username}. Solde de {round(float(mixmaster_request.remaining_amount)*0.90,2)}€ ajouté à vos gains (dispo dans 7j).",
            'refunded': f"Demande de {artist.username} remboursée (délai dépassé ou annulation). Contactez le support en cas de problème.",
        }
    }

    status_title = {
        'artist': {
            'accepted': "Mixage accepté",
            'rejected': "Mixage refusé",
            'processing': "Mixage en cours",
            'delivered': f"Mixage reçu",
            'completed': f"Téléchargement disponible",
            'refunded': f"Mixage annulé",
        },
        'engineer': {
            'accepted': "1 semaine pour mixer",
            'rejected': "Mixage refusé",
            'processing': "Mix",
            'delivered': f"Mixage envoyé",
            'completed': f"Mixage validé",
            'refunded': f"Mixage annulé",
        }
    }


    def get_status_message(role):
        return status_messages.get(role, {}).get(new_status, 'Statut mis à jour')
    
    def get_status_title(role):
        return status_title.get(role, {}).get(new_status, 'Mix')


    create_notification(
        user_id=mixmaster_request.artist_id,
        notif_type='Statut de votre mixage mis à jour',
        title=get_status_title('artist'),
        message=get_status_message('artist'),
        link=url_for('payment.purchases')
    )
    
    # Pour 'delivered' et 'completed', pointer l'engineer vers ses gains
    engineer_link = (
        url_for('wallet.mes_gains')
        if new_status in ('delivered', 'completed')
        else url_for('mixmaster.dashboard')
    )
    create_notification(
        user_id=mixmaster_request.engineer_id,
        notif_type='Statut de votre mixage mis à jour',
        title=get_status_title('engineer'),
        message=get_status_message('engineer'),
        link=engineer_link
    )

# ============================================
# NOTIFICATIONS SPÉCIFIQUES - TOPLINES
# ============================================

def notify_topline_submitted(topline):
    """
    Notifie le compositeur qu'une topline a été soumise sur son track

    Args:
        topline: Instance Topline
    """
    track = topline.track
    artist = topline.artist_user

    create_notification(
        user_id=track.composer_id,
        notif_type='topline_submitted',
        title='Nouvelle topline sur votre track',
        message=f'{artist.username} a soumis une topline sur "{track.title}".',
        link=url_for('main.track_detail', track_id=track.id)
    )


# ============================================
# NOTIFICATIONS SPÉCIFIQUES - TOKENS
# ============================================

def notify_tokens_recharged(user, token_type='upload'):
    """
    Notifie l'utilisateur du rechargement de ses tokens

    Args:
        user: Instance User
        token_type: 'upload' ou 'topline'
    """
    if token_type == 'upload':
        token_count = user.upload_track_tokens
        message = f'Vos tokens d\'upload ont été rechargés ! Vous avez {token_count} tokens disponibles.'
        link = url_for('tracks.add_track')
    else:
        token_count = user.topline_tokens
        message = f'Vos tokens de topline ont été rechargés ! Vous avez {token_count} tokens disponibles.'
        link = url_for('main.index')

    create_notification(
        user_id=user.id,
        notif_type='tokens_recharged',
        title='Tokens rechargés',
        message=message,
        link=link
    )


def notify_stripe_connect_setup(user_id):
    """
    Notification persistante invitant l'utilisateur à créer son compte Stripe Connect.
    Appelée une seule fois lors de la première sélection de rôle (beatmaker ou mix engineer).
    """
    create_notification(
        user_id=user_id,
        notif_type='stripe_connect_setup',
        title='Configurez votre compte de paiement',
        message=(
            'Pour recevoir vos gains, connectez votre compte Stripe depuis votre Wallet. '
            'Vous pouvez le faire à tout moment — vos revenus seront disponibles dès que votre compte sera activé.'
        ),
        link='/wallet',
    )


def notify_tokens_low(user, token_type='upload'):
    """
    Notifie l'utilisateur que ses tokens sont bientôt épuisés

    Args:
        user: Instance User
        token_type: 'upload' ou 'topline'
    """
    if token_type == 'upload':
        token_count = user.upload_track_tokens
        message = f'Il vous reste seulement {token_count} token(s) d\'upload.'
    else:
        token_count = user.topline_tokens
        message = f'Il vous reste seulement {token_count} token(s) de topline.'

    create_notification(
        user_id=user.id,
        notif_type='tokens_recharged',
        title='Tokens bientôt épuisés',
        message=message,
        link=None
    )
