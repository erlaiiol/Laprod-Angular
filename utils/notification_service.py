"""
Service de notifications in-app pour LaProd
Crée des notifications visibles dans l'interface utilisateur
"""
from flask import current_app
from extensions import db
from models import Notification, User

# ── URLs Angular (SPA) — pas de url_for() Flask ──────────────────────────────
_URL_ARTIST_ORDERS  = '/dashboard/artist'     # onglet mixmaster
_URL_ENGINEER_DASH  = '/dashboard/engineer'   # onglet commandes
_URL_WALLET         = '/dashboard/wallet'
_URL_MY_PURCHASES   = '/dashboard/artist'


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
            link=_URL_MY_PURCHASES
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
        link=_URL_MY_PURCHASES
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
        link=_URL_WALLET
    )


def notify_exclusive_sold(track, purchase):
    """Notifie le compositeur que son track vient d'être vendu en exclusivité."""
    create_notification(
        user_id=track.composer_id,
        notif_type='track_exclusive_sold',
        title='Contrat exclusif signé !',
        message=(
            f'Votre track « {track.title} » a été acheté en exclusivité '
            f'par {purchase.buyer_user.username}. '
            f'Il est maintenant retiré de la vente.'
        ),
        link='/dashboard'
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
        link=f'/track/{track.id}'
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
        link=f'/profile/{track.composer_user.username}'
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
        link=_URL_ENGINEER_DASH
    )

    create_notification(
        user_id=mixmaster_request.artist_id,
        notif_type='mixmaster_request_sent',
        title='Demande de mixage envoyée avec succès',
        message=f'Votre demande de mixage a été envoyée à {mixmaster_request.engineer.username}. Montant débité : {mixmaster_request.total_price}€.',
        link=_URL_ARTIST_ORDERS
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

    # Message 'refunded' dépend du scénario (old_status)
    deposit_net = round(float(mixmaster_request.deposit_amount) * 0.90, 2)
    final_net   = round(float(mixmaster_request.get_final_transfer_amount()), 2)
    refund_amt  = round(float(mixmaster_request.get_refund_amount()), 2)

    if old_status == 'awaiting_acceptance':
        # Annulation artiste ou rejet ingénieur → remboursement total
        artist_refunded_msg  = f"Remboursement intégral de {mixmaster_request.total_price:.2f}€ en cours."
        engineer_refund_msg  = f"Demande de {artist.username} remboursée intégralement. Aucun montant versé."
    elif old_status == 'delivered':
        # Refus de livraison → remboursement partiel
        artist_refunded_msg  = f"Livraison refusée. Remboursement partiel de {refund_amt:.2f}€ en cours (l'ingénieur conserve ses acomptes)."
        engineer_refund_msg  = f"{artist.username} a refusé votre livraison. Vous conservez vos acomptes déjà crédités ({mixmaster_request.total_price - refund_amt:.2f}€)."
    else:
        artist_refunded_msg  = f"Commande annulée. Remboursement de {refund_amt:.2f}€ en cours."
        engineer_refund_msg  = f"Commande de {artist.username} annulée."

    status_messages = {
        'artist': {
            'accepted':    f"{engineer.username} a accepté votre demande ! Mixage en cours. Deadline : 7 jours.",
            'rejected':    f"{engineer.username} a refusé votre demande. Remboursement intégral de {mixmaster_request.total_price:.2f}€ en cours.",
            'processing':  "Votre mixage est en cours de traitement.",
            'delivered':   f"Votre mixage est prêt ! Écoutez les previews puis validez ou demandez une révision.",
            'revision1':   f"Révision 1 demandée à {engineer.username}.",
            'revision2':   f"Révision 2 demandée à {engineer.username}.",
            'completed':   f"Mixage validé ! Téléchargez votre fichier final. Aucun remboursement possible après validation.",
            'refunded':    artist_refunded_msg,
        },
        'engineer': {
            'accepted':    f"Vous avez accepté la demande de {artist.username}. 7 jours pour livrer.",
            'rejected':    f"Vous avez refusé la demande de {artist.username}. Artiste remboursé intégralement.",
            'processing':  f"Mixage en cours pour {artist.username}.",
            'delivered':   f"Mixage livré à {artist.username}. {deposit_net:.2f}€ ajoutés à vos gains (dispo dans 7j).",
            'revision1':   f"{artist.username} demande la révision 1. +{round(float(mixmaster_request.get_revision_transfer_amount()),2):.2f}€ ajoutés à vos gains.",
            'revision2':   f"{artist.username} demande la révision 2. +{round(float(mixmaster_request.get_revision_transfer_amount()),2):.2f}€ ajoutés à vos gains.",
            'completed':   f"Mixage validé par {artist.username}. Solde final de {final_net:.2f}€ ajouté à vos gains (dispo dans 7j).",
            'refunded':    engineer_refund_msg,
        }
    }

    status_title = {
        'artist': {
            'accepted':   "Mixage accepté",
            'rejected':   "Mixage refusé — remboursé",
            'processing': "Mixage en cours",
            'delivered':  "Mixage reçu — à valider",
            'revision1':  "Révision 1 en cours",
            'revision2':  "Révision 2 en cours",
            'completed':  "Téléchargement disponible",
            'refunded':   "Livraison refusée",
        },
        'engineer': {
            'accepted':   "Nouvelle commande acceptée",
            'rejected':   "Commande refusée",
            'processing': "Mixage en cours",
            'delivered':  "Mixage livré",
            'revision1':  "Révision 1 demandée",
            'revision2':  "Révision 2 demandée",
            'completed':  "Mixage validé — gains crédités",
            'refunded':   "Commande remboursée",
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
        link=_URL_ARTIST_ORDERS
    )

    engineer_link = _URL_WALLET if new_status in ('delivered', 'completed') else _URL_ENGINEER_DASH
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
        link=f'/track/{track.id}'
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
        link = '/dashboard/beatmaker'
    else:
        token_count = user.topline_tokens
        message = f'Vos tokens de topline ont été rechargés ! Vous avez {token_count} tokens disponibles.'
        link = '/'

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


def notify_stripe_connect_reminder(user_id):
    """
    Rappel hebdomadaire pour les beatmakers/mix engineers qui n'ont pas encore
    configuré leur compte Stripe Connect. Dédupliqué : ne crée pas de notif si
    une notification non lue de ce type existe déjà depuis moins de 7 jours.
    Doit être suivi d'un db.session.commit() par l'appelant.
    """
    from datetime import datetime, timedelta
    recent_cutoff = datetime.now() - timedelta(days=7)
    already_pending = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.type    == 'stripe_connect_setup',
        Notification.is_read == False,
        Notification.created_at >= recent_cutoff,
    ).first()
    if already_pending:
        return None

    return create_notification(
        user_id=user_id,
        notif_type='stripe_connect_setup',
        title='Rappel : compte de paiement non configuré',
        message=(
            'Vous n\'avez pas encore connecté votre compte Stripe. '
            'Sans cela, vos gains de ventes ne pourront pas vous être versés. '
            'Rendez-vous dans votre Wallet pour finaliser en 2 minutes.'
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


def notify_plan_changed(user, new_plan, old_plan, expires_at=None, granted_by_admin=False):
    """
    Notifie l'utilisateur d'un changement de son plan d'abonnement.

    Args:
        user: Instance User
        new_plan: Nouveau plan ('free' | 'amateur' | 'pro')
        old_plan: Ancien plan
        expires_at: Date d'expiration (datetime) si applicable
        granted_by_admin: True si l'action vient d'un admin
    """
    plan_labels = {'free': 'Free', 'amateur': 'LaProd+ Amateur', 'pro': 'LaProd+ Pro'}
    new_label = plan_labels.get(new_plan, new_plan)

    if new_plan == 'free':
        title   = 'Abonnement désactivé'
        message = 'Votre abonnement LaProd+ a été désactivé. Vous repassez en plan Free.'
    else:
        expires_str = expires_at.strftime('%d/%m/%Y') if expires_at else ''
        title   = f'Plan {new_label} activé !'
        message = (
            f'Votre plan {new_label} est actif jusqu\'au {expires_str}.'
            if expires_str else f'Votre plan {new_label} est maintenant actif.'
        )
        if granted_by_admin:
            message += ' Ce plan vous a été accordé par l\'équipe LaProd.'

    create_notification(
        user_id=user.id,
        notif_type='plan_changed',
        title=title,
        message=message,
        link='/premium',
    )


def notify_role_changed(user, role: str, granted: bool):
    role_labels = {
        'beatmaker': 'Beatmaker',
        'artist': 'Artiste',
        'engineer': 'Mix/Master Engineer',
        'master': 'Certified Master Engineer',
        'producer_arranger': 'Certified Producteur/Arrangeur',
    }
    label = role_labels.get(role, role)
    if granted:
        title   = f'Rôle {label} accordé'
        message = f'L\'équipe LaProd vous a accordé le rôle {label}. Rendez-vous sur votre profil pour le configurer.'
    else:
        title   = f'Rôle {label} retiré'
        message = f'Le rôle {label} a été retiré de votre compte par l\'équipe LaProd.'

    create_notification(
        user_id=user.id,
        notif_type='role_changed',
        title=title,
        message=message,
        link='/profile/' + user.username,
    )


def notify_audio_analysis_done(user, track, suggestions: dict):
    parts = []
    if 'bpm' in suggestions:
        parts.append(f"BPM : {suggestions['bpm']}")
    if 'key' in suggestions:
        parts.append(f"Gamme : {suggestions['key']}")
    if 'style' in suggestions:
        parts.append(f"Style : {suggestions['style']}")

    summary = ' · '.join(parts)
    create_notification(
        user_id=user.id,
        notif_type='audio_analysis',
        title='Analyse audio terminée',
        message=f"Suggestions pour « {track.title} » — {summary}. Validez ou modifiez depuis votre tableau de bord.",
        link='/dashboard',
    )


def notify_tokens_added(user, token_type: str, amount: int):
    label = 'upload' if token_type == 'track' else 'topline'
    create_notification(
        user_id=user.id,
        notif_type='tokens_added',
        title=f'{amount} token(s) {label} ajouté(s)',
        message=f'L\'équipe LaProd vous a crédité {amount} token(s) d\'upload {label}.',
        link='/dashboard',
    )


# ============================================
# NOTIFICATIONS — CYCLE DE VIE DES LICENCES
# ============================================

def notify_expiry_approaching(purchase, days: int):
    """Rappel d'expiration pour l'artiste (90/30/7/1 jours avant)."""
    track_title = purchase.track.title if purchase.track else f'Track #{purchase.track_id}'
    if days <= 1:
        urgency = 'demain !'
    elif days <= 7:
        urgency = f'dans {days} jour{"s" if days > 1 else ""} !'
    elif days <= 30:
        urgency = f'dans {days} jours'
    else:
        urgency = f'dans {days} jours'

    create_notification(
        user_id=purchase.buyer_id,
        notif_type=f'license_expiry_{days}d',
        title=f'Votre licence expire {urgency}',
        message=(
            f'Votre licence pour « {track_title} » expire {urgency}. '
            f'Renouvelez-la pour conserver vos droits d\'exploitation.'
        ),
        link=f'/licenses',
    )


def notify_sole_licensee_monthly(purchase):
    """Notification mensuelle : l'artiste est l'unique licencié actif."""
    track_title = purchase.track.title if purchase.track else f'Track #{purchase.track_id}'
    create_notification(
        user_id=purchase.buyer_id,
        notif_type='license_sole_monthly',
        title='Vous êtes toujours le seul licencié',
        message=(
            f'Vous êtes toujours le seul titulaire d\'une licence pour « {track_title} ». '
            f'Cette composition n\'a pas été vendue à d\'autres artistes ce mois-ci.'
        ),
        link=f'/licenses',
    )


def notify_renewal_confirmed(purchase):
    """Confirmation de renouvellement — artiste et compositeur."""
    track_title = purchase.track.title if purchase.track else f'Track #{purchase.track_id}'

    # Artiste
    create_notification(
        user_id=purchase.buyer_id,
        notif_type='license_renewed',
        title='Licence renouvelée avec succès',
        message=f'Votre licence pour « {track_title} » a été renouvelée. Vos droits sont prolongés.',
        link=f'/licenses',
    )

    # Compositeur
    if purchase.track and purchase.track.composer_id:
        create_notification(
            user_id=purchase.track.composer_id,
            notif_type='license_renewed',
            title='Un artiste a renouvelé sa licence',
            message=f'La licence de « {track_title} » a été renouvelée par {purchase.buyer_name}.',
            link='/dashboard/beatmaker',
        )


def notify_license_expired(purchase):
    """Notification d'expiration définitive — artiste."""
    track_title = purchase.track.title if purchase.track else f'Track #{purchase.track_id}'
    create_notification(
        user_id=purchase.buyer_id,
        notif_type='license_expired',
        title='Votre licence a expiré',
        message=(
            f'Votre licence pour « {track_title} » est expirée. '
            f'Vous pouvez la renouveler depuis votre espace licences.'
        ),
        link=f'/licenses',
    )


def notify_exclusive_license_expired(track, purchase):
    """Notification d'expiration d'une exclusivité — artiste + compositeur."""
    track_title = track.title

    # Artiste
    create_notification(
        user_id=purchase.buyer_id,
        notif_type='license_expired',
        title='Votre licence exclusive a expiré',
        message=(
            f'Votre licence exclusive pour « {track_title} » est expirée. '
            f'Cette composition est de nouveau disponible à la vente. '
            f'Vous pouvez renouveler votre licence depuis votre espace licences.'
        ),
        link=f'/licenses',
    )

    # Compositeur
    if track.composer_id:
        create_notification(
            user_id=track.composer_id,
            notif_type='track_exclusive_expired',
            title='Licence exclusive expirée — track de nouveau disponible',
            message=(
                f'La licence exclusive de « {track_title} » accordée à {purchase.buyer_name} '
                f'est expirée. Votre track est de nouveau disponible à la vente.'
            ),
            link='/dashboard/beatmaker',
        )

