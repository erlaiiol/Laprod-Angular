"""
utils/campaign_service.py — Campagnes de mailing des vendeurs
=============================================================

Point d'entrée unique pour : construire une audience, valider un créneau
d'envoi, dispatcher, mesurer.

Trois principes non négociables, dans cet ordre :

  1. CONSENTEMENT. Aucune audience ne se construit sans passer par
     User.can_receive_marketing (opt-in + email vérifié). Un vendeur ne voit
     jamais une adresse email : il choisit un segment, le serveur résout les
     destinataires. Les emails ne quittent jamais le backend.

  2. RYTHME. Une campagne n'est jamais envoyée dans la foulée : elle est
     planifiée sur un créneau validé, avec un quota et un délai de carence
     entre deux campagnes. C'est ce qui empêche un vendeur de mitrailler sa base.

  3. FRÉQUENCE SUBIE. Le quota par vendeur ne suffit pas : avec 200 vendeurs,
     un utilisateur pourrait recevoir 400 mails/mois tout en respectant chaque
     quota individuel. Un plafond GLOBAL par destinataire (tous vendeurs
     confondus) est donc appliqué au dispatch — c'est lui qui protège
     réellement la base et la réputation d'expédition du domaine.
"""
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_, select

from extensions import db
from models import (
    User, Track, Purchase, Favorite, ListeningHistory, MixMasterRequest,
    MarketingCampaign, CampaignRecipient, CampaignSegment, CampaignStatus,
    PromoCode, PromoCodeRedemption,
)

# ── Règles de rythme ─────────────────────────────────────────────────────────

MAX_CAMPAIGNS_PER_30_DAYS = 2    # par vendeur
MIN_DAYS_BETWEEN_CAMPAIGNS = 10  # carence : interdit d'enchaîner les 2 du mois

# Plafond subi par un destinataire, TOUS vendeurs confondus.
MAX_EMAILS_PER_RECIPIENT_PER_30_DAYS = 4

# Fenêtres d'envoi autorisées : mardi/mercredi/jeudi, 10h–19h. Pas de week-end
# (taux d'ouverture au plancher), pas de lundi (boîte saturée), pas de nuit
# (un mail à 3h du matin se fait supprimer sans être lu).
ALLOWED_WEEKDAYS = (1, 2, 3)  # 0 = lundi … 6 = dimanche
ALLOWED_HOUR_MIN = 10
ALLOWED_HOUR_MAX = 19

# Délai minimum entre la planification et l'envoi : laisse au vendeur le temps
# de relire, corriger ou annuler. Une campagne partie ne se rattrape pas.
MIN_HOURS_BEFORE_SEND = 24
MAX_DAYS_AHEAD = 60

# Fenêtre d'activité retenue pour le segment « auditeurs récents ».
LISTENER_WINDOW_DAYS = 90

SUPER_PREMIUM_PRICE_EUR = '19.99'  # une campagne à diffusion totale


class CampaignError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


# ── Audiences ────────────────────────────────────────────────────────────────

def _owner_track_ids(owner_id):
    return select(Track.id).where(Track.composer_id == owner_id).scalar_subquery()


def audience_query(owner_id, segment):
    """Requête des destinataires d'un segment. Toujours filtrée par le consentement.

    Renvoie une Query SQLAlchemy sur User — jamais une liste d'emails.
    """
    q = User.query.filter(
        User.can_receive_marketing,          # opt-in + email vérifié
        User.id != owner_id,                 # on ne se maile pas soi-même
        User.account_status == 'active',
    )

    if segment == CampaignSegment.ALL.value:
        return q

    track_ids = _owner_track_ids(owner_id)

    if segment == CampaignSegment.BUYERS.value:
        # Acheteurs de beats du vendeur OU clients mix/master de l'ingénieur :
        # dans les deux cas une relation commerciale existe déjà.
        beat_buyers = select(Purchase.buyer_id).where(Purchase.track_id.in_(track_ids))
        mix_clients = select(MixMasterRequest.artist_id).where(
            MixMasterRequest.engineer_id == owner_id,
        )
        return q.filter(or_(User.id.in_(beat_buyers), User.id.in_(mix_clients)))

    if segment == CampaignSegment.FAVORITES.value:
        fav_users = select(Favorite.user_id).where(Favorite.track_id.in_(track_ids))
        return q.filter(User.id.in_(fav_users))

    if segment == CampaignSegment.LISTENERS.value:
        since = datetime.now() - timedelta(days=LISTENER_WINDOW_DAYS)
        listeners = select(ListeningHistory.user_id).where(
            ListeningHistory.track_id.in_(track_ids),
            ListeningHistory.listened_at >= since,
        )
        return q.filter(User.id.in_(listeners))

    if segment == CampaignSegment.AFFINITY.value:
        return q.filter(User.id.in_(_affinity_candidate_ids(owner_id)))

    raise CampaignError('INVALID_SEGMENT', 'Segment inconnu.')


# ── Affinité musicale (réutilise les signaux de l'algo de reco) ───────────────

# Un « match » = une écoute aboutie ou une mise en favori sur un beat au style/tag
# du vendeur. On exige plusieurs matchs pour écarter le hasard d'une écoute isolée.
AFFINITY_MIN_HITS = 3
AFFINITY_MIN_COMPLETION = 0.30   # même seuil de « signal positif » que la reco


def seller_style_signature(owner_id):
    """Signature stylistique d'un vendeur : (tag_ids, styles) de son catalogue.

    C'est le même matériau que le vecteur de recommandation (tags + styles), mais
    agrégé côté VENDEUR : « voici ce que produit cette personne ». On matche ensuite
    les auditeurs dont les goûts pointent vers cette signature.
    """
    from models import Track, track_tag

    approved = select(Track.id).where(
        Track.composer_id == owner_id, Track.is_approved.is_(True),
    )
    tag_ids = set(db.session.execute(
        select(track_tag.c.tag_id).where(track_tag.c.track_id.in_(approved)).distinct()
    ).scalars().all())
    styles = set(db.session.execute(
        select(Track.style).where(
            Track.composer_id == owner_id,
            Track.is_approved.is_(True),
            Track.style.isnot(None),
        ).distinct()
    ).scalars().all())
    return tag_ids, styles


def _affinity_candidate_ids(owner_id):
    """IDs des utilisateurs consentants dont les goûts collent au style du vendeur,
    SANS déjà le connaître (les contacts directs sont couverts par les autres
    segments). Renvoie un set — potentiellement vide.

    La requête est bornée au pool consentant dès le départ : on ne scanne jamais
    l'historique d'écoute de toute la plateforme, seulement celui des gens qu'on
    a le droit de contacter.
    """
    from models import Track, track_tag, Favorite, ListenEvent
    from sqlalchemy import func, union_all

    tag_ids, styles = seller_style_signature(owner_id)
    if not tag_ids and not styles:
        return set()   # vendeur sans catalogue qualifié : aucune affinité calculable

    # Beats (tous vendeurs confondus) qui partagent la signature du vendeur.
    style_match = Track.style.in_(styles) if styles else None
    tag_match = (
        Track.id.in_(select(track_tag.c.track_id).where(track_tag.c.tag_id.in_(tag_ids)))
        if tag_ids else None
    )
    conditions = [c for c in (style_match, tag_match) if c is not None]
    matching_tracks = select(Track.id).where(
        Track.is_approved.is_(True), or_(*conditions),
    )

    consenting = select(User.id).where(
        User.can_receive_marketing, User.account_status == 'active', User.id != owner_id,
    )

    # Engagements positifs (écoute aboutie OU favori) sur ces beats, par les seuls
    # utilisateurs consentants — c'est ce qui borne le coût de la requête.
    listens = select(ListenEvent.user_id.label('uid'), ListenEvent.track_id.label('tid')).where(
        ListenEvent.track_id.in_(matching_tracks),
        ListenEvent.completion_ratio >= AFFINITY_MIN_COMPLETION,
        ListenEvent.user_id.in_(consenting),
    )
    favs = select(Favorite.user_id.label('uid'), Favorite.track_id.label('tid')).where(
        Favorite.track_id.in_(matching_tracks),
        Favorite.user_id.in_(consenting),
    )
    engaged = union_all(listens, favs).subquery()

    candidates = set(db.session.execute(
        select(engaged.c.uid)
        .group_by(engaged.c.uid)
        .having(func.count(func.distinct(engaged.c.tid)) >= AFFINITY_MIN_HITS)
    ).scalars().all())

    if not candidates:
        return set()

    # Retirer les contacts DIRECTS : ils sont déjà atteignables via buyers/favorites/
    # listeners. L'affinité ne doit remonter que des prospects réellement nouveaux —
    # sinon le vendeur croit toucher du monde neuf alors qu'il se re-maile ses fans.
    own_tracks = select(Track.id).where(Track.composer_id == owner_id)
    direct = set()
    direct |= set(db.session.execute(
        select(Favorite.user_id).where(Favorite.track_id.in_(own_tracks))
    ).scalars().all())
    direct |= set(db.session.execute(
        select(ListenEvent.user_id).where(ListenEvent.track_id.in_(own_tracks))
    ).scalars().all())

    return candidates - direct


def audience_size(owner_id, segment):
    return audience_query(owner_id, segment).count()


def audience_preview(owner_id):
    """Taille de chaque segment — alimente l'écran de composition."""
    return {
        seg.value: audience_size(owner_id, seg.value)
        for seg in CampaignSegment
    }


# ── Rythme ───────────────────────────────────────────────────────────────────

def _recent_campaigns(owner_id):
    """Campagnes engagées (planifiées ou parties) sur les 30 derniers jours.

    Les brouillons ne comptent pas : écrire n'est pas envoyer. Les campagnes
    planifiées comptent, sinon on pourrait en programmer dix d'avance.
    """
    since = datetime.now() - timedelta(days=30)
    return MarketingCampaign.query.filter(
        MarketingCampaign.owner_id == owner_id,
        MarketingCampaign.status.in_([
            CampaignStatus.SCHEDULED.value,
            CampaignStatus.SENDING.value,
            CampaignStatus.SENT.value,
        ]),
        MarketingCampaign.created_at >= since,
    ).all()


def quota_status(owner_id):
    """État du quota du vendeur, pour l'afficher sans avoir à échouer d'abord."""
    recent = _recent_campaigns(owner_id)
    used = len(recent)

    last_dt = None
    for c in recent:
        ref = c.sent_at or c.scheduled_for or c.created_at
        if ref and (last_dt is None or ref > last_dt):
            last_dt = ref

    next_allowed = None
    if last_dt:
        next_allowed = last_dt + timedelta(days=MIN_DAYS_BETWEEN_CAMPAIGNS)
        if next_allowed <= datetime.now():
            next_allowed = None

    return {
        'used':              used,
        'max':               MAX_CAMPAIGNS_PER_30_DAYS,
        'remaining':         max(0, MAX_CAMPAIGNS_PER_30_DAYS - used),
        'next_allowed_at':   next_allowed,
        'cooldown_days':     MIN_DAYS_BETWEEN_CAMPAIGNS,
    }


def suggest_slots(owner_id, count=5):
    """Prochains créneaux valides — le vendeur choisit dans une liste, il ne
    tape pas une date au hasard pour se la faire refuser."""
    status = quota_status(owner_id)
    earliest = datetime.now() + timedelta(hours=MIN_HOURS_BEFORE_SEND)
    if status['next_allowed_at'] and status['next_allowed_at'] > earliest:
        earliest = status['next_allowed_at']

    slots = []
    # Arrondi à l'heure SUPÉRIEURE : tronquer les minutes ferait reculer le curseur
    # sous `earliest`, et on proposerait un créneau que validate_slot refuserait
    # ensuite pour SLOT_TOO_SOON. Le serveur ne doit jamais proposer un créneau
    # qu'il rejettera.
    cursor = earliest.replace(minute=0, second=0, microsecond=0)
    if cursor < earliest:
        cursor += timedelta(hours=1)
    limit = datetime.now() + timedelta(days=MAX_DAYS_AHEAD)

    while len(slots) < count and cursor <= limit:
        if cursor.weekday() in ALLOWED_WEEKDAYS and ALLOWED_HOUR_MIN <= cursor.hour <= ALLOWED_HOUR_MAX:
            slots.append(cursor)
            cursor += timedelta(days=1)          # un seul créneau proposé par jour
            cursor = cursor.replace(hour=ALLOWED_HOUR_MIN)
        else:
            cursor += timedelta(hours=1)
    return slots


def validate_slot(owner_id, scheduled_for, campaign=None):
    """Le créneau demandé est-il envoyable ? Lève CampaignError sinon."""
    now = datetime.now()

    if scheduled_for < now + timedelta(hours=MIN_HOURS_BEFORE_SEND):
        raise CampaignError(
            'SLOT_TOO_SOON',
            f'Planifiez votre campagne au moins {MIN_HOURS_BEFORE_SEND} h à l\'avance '
            f'— ce délai vous laisse le temps de la relire ou de l\'annuler.',
        )
    if scheduled_for > now + timedelta(days=MAX_DAYS_AHEAD):
        raise CampaignError('SLOT_TOO_FAR',
                            f'Vous ne pouvez pas planifier au-delà de {MAX_DAYS_AHEAD} jours.')
    if scheduled_for.weekday() not in ALLOWED_WEEKDAYS:
        raise CampaignError('SLOT_BAD_DAY',
                            'Les campagnes ne partent que le mardi, mercredi ou jeudi.')
    if not (ALLOWED_HOUR_MIN <= scheduled_for.hour <= ALLOWED_HOUR_MAX):
        raise CampaignError('SLOT_BAD_HOUR',
                            f'Les campagnes ne partent qu\'entre {ALLOWED_HOUR_MIN} h et {ALLOWED_HOUR_MAX} h.')

    status = quota_status(owner_id)

    # La campagne en cours de replanification ne doit pas se compter elle-même.
    already_counted = campaign is not None and campaign.status in (
        CampaignStatus.SCHEDULED.value, CampaignStatus.SENDING.value, CampaignStatus.SENT.value,
    )
    if not already_counted and status['remaining'] <= 0:
        raise CampaignError(
            'QUOTA_REACHED',
            f'Vous avez atteint votre limite de {MAX_CAMPAIGNS_PER_30_DAYS} campagnes '
            f'sur 30 jours. Cette limite protège vos abonnés — et votre taux de lecture.',
        )
    if not already_counted and status['next_allowed_at'] and scheduled_for < status['next_allowed_at']:
        raise CampaignError(
            'COOLDOWN',
            f'Laissez {MIN_DAYS_BETWEEN_CAMPAIGNS} jours entre deux campagnes. '
            f'Prochaine date possible : {status["next_allowed_at"].strftime("%d/%m/%Y à %H h")}.',
        )
    return True


# ── Plafond de fréquence subie ───────────────────────────────────────────────

def _recently_mailed_user_ids():
    """Utilisateurs ayant déjà atteint leur plafond de mails marketing sur 30 j.

    Sans ce filtre, chaque vendeur respecte son quota mais l'utilisateur subit la
    somme de tous les vendeurs.
    """
    since = datetime.now() - timedelta(days=30)
    rows = (
        db.session.query(CampaignRecipient.user_id)
        .filter(CampaignRecipient.sent_at.isnot(None),
                CampaignRecipient.sent_at >= since)
        .group_by(CampaignRecipient.user_id)
        .having(db.func.count(CampaignRecipient.id) >= MAX_EMAILS_PER_RECIPIENT_PER_30_DAYS)
        .all()
    )
    return {r[0] for r in rows}


# ── Dispatch ─────────────────────────────────────────────────────────────────

def dispatch(campaign):
    """Envoie une campagne planifiée. Idempotent au niveau du destinataire.

    Appelé par le job APScheduler, jamais directement par une route HTTP : un
    envoi de masse dans le cycle requête/réponse ferait timeout et, pire,
    pourrait repartir de zéro sur un retry.
    """
    from utils.email_service import send_campaign_email

    if campaign.status not in (CampaignStatus.SCHEDULED.value, CampaignStatus.SENDING.value):
        return 0

    campaign.status = CampaignStatus.SENDING.value
    db.session.commit()

    # Audience recalculée AU MOMENT de l'envoi : entre la planification et le
    # dispatch, des utilisateurs ont pu se désinscrire. C'est leur choix le plus
    # récent qui fait foi, pas une liste figée il y a 3 jours.
    recipients = audience_query(campaign.owner_id, campaign.segment).all()
    saturated = _recently_mailed_user_ids()

    sent = failed = skipped = 0

    for user in recipients:
        if user.id in saturated:
            # Plafond de fréquence atteint (tous vendeurs confondus) : on le passe.
            skipped += 1
            continue

        # Garde-fou en base contre un double envoi (retry du job).
        exists = CampaignRecipient.query.filter_by(
            campaign_id=campaign.id, user_id=user.id,
        ).first()
        if exists:
            continue

        recipient = CampaignRecipient(campaign_id=campaign.id, user_id=user.id)
        db.session.add(recipient)
        try:
            send_campaign_email(campaign, user)
            recipient.sent_at = datetime.now()
            sent += 1
        except Exception as exc:  # un email qui casse ne doit pas tuer la campagne
            recipient.error = str(exc)[:200]
            failed += 1
            current_app.logger.error(
                f'Campagne #{campaign.id} — échec envoi user #{user.id}: {exc}',
            )

    # recipient_count = les destinataires RÉELLEMENT adressés (envois + échecs),
    # pas la taille brute du segment : compter ceux qu'on a volontairement écartés
    # ferait croire au vendeur qu'il a touché des gens qui n'ont rien reçu.
    campaign.recipient_count = sent + failed
    campaign.sent_count      = sent
    campaign.failed_count    = failed
    campaign.sent_at         = datetime.now()
    campaign.status = CampaignStatus.SENT.value if sent else CampaignStatus.FAILED.value
    db.session.commit()

    current_app.logger.info(
        f'Campagne #{campaign.id} ({campaign.segment}) — {sent} envoyés, {failed} échecs, '
        f'{skipped} ignorés (plafond de fréquence)',
    )
    return sent


def dispatch_due_campaigns():
    """Job : envoie les campagnes dont le créneau est arrivé."""
    due = MarketingCampaign.query.filter(
        MarketingCampaign.status == CampaignStatus.SCHEDULED.value,
        MarketingCampaign.scheduled_for <= datetime.now(),
    ).all()
    for campaign in due:
        try:
            dispatch(campaign)
        except Exception as exc:
            db.session.rollback()
            campaign.status = CampaignStatus.FAILED.value
            db.session.commit()
            current_app.logger.error(f'Campagne #{campaign.id} échouée : {exc}', exc_info=True)
    return len(due)


# ── Statistiques ─────────────────────────────────────────────────────────────

def campaign_stats(campaign):
    """Mesure honnête d'une campagne.

    On ne prétend pas mesurer les ouvertures : ça demande un pixel espion, un
    consentement supplémentaire, et c'est de toute façon faussé par les clients
    mail qui préchargent les images. On mesure ce qui compte vraiment et qu'on
    sait établir : combien de destinataires ont effectivement utilisé le code
    promo mis en avant, et combien de chiffre d'affaires ça a produit.
    """
    stats = {
        'recipient_count': campaign.recipient_count,
        'sent_count':      campaign.sent_count,
        'failed_count':    campaign.failed_count,
        'conversions':     0,
        'revenue':         0.0,
        'discount_given':  0.0,
    }
    if not (campaign.promo_code_id and campaign.sent_at):
        return stats

    recipient_ids = select(CampaignRecipient.user_id).where(
        CampaignRecipient.campaign_id == campaign.id,
        CampaignRecipient.sent_at.isnot(None),
    ).scalar_subquery()

    redemptions = PromoCodeRedemption.query.filter(
        PromoCodeRedemption.promo_code_id == campaign.promo_code_id,
        PromoCodeRedemption.user_id.in_(recipient_ids),
        PromoCodeRedemption.created_at >= campaign.sent_at,
    ).all()

    stats['conversions']    = len(redemptions)
    stats['revenue']        = float(sum(r.net_amount for r in redemptions))
    stats['discount_given'] = float(sum(r.discount_amount for r in redemptions))
    return stats


# ── Mails-types suggérés d'après l'activité récente ───────────────────────────
# On ne laisse pas le vendeur face à une page blanche : on lui propose des
# brouillons pré-remplis, ancrés dans ce qu'il vient RÉELLEMENT de faire (un beat
# publié, un code promo créé…). Un clic remplit le formulaire, il complète au besoin.
# Tout est au tutoiement : le destinataire est un artiste/auditeur, pas une structure.

TEMPLATE_LOOKBACK_DAYS = 21   # « récent » = trois dernières semaines


def suggest_templates(owner_id):
    """Liste de brouillons de campagne dérivés de l'activité récente du vendeur.

    Chaque template : id, label (puce cliquable), subject, body, segment suggéré,
    promo_code_id éventuel. Renvoyés du plus pertinent au plus générique.
    """
    since = datetime.now() - timedelta(days=TEMPLATE_LOOKBACK_DAYS)
    templates = []

    # 1) Beat récemment publié → « nouveau son ».
    last_beat = (
        Track.query
        .filter(Track.composer_id == owner_id, Track.is_approved.is_(True),
                Track.created_at >= since)
        .order_by(Track.created_at.desc())
        .first()
    )
    if last_beat:
        templates.append({
            'id':      'new_beat',
            'label':   'Nouveau beat',
            'icon':    'music-note-beamed',
            'subject': f'Nouveau son : {last_beat.title}',
            'body': (
                f"J'ai posé un nouveau beat, « {last_beat.title} ».\n\n"
                "Je pense qu'il peut coller à ce que tu cherches — jette-y une oreille, "
                "et dis-moi ce que tu en penses.\n\n"
                "À très vite."
            ),
            'segment':       CampaignSegment.FAVORITES.value,
            'promo_code_id': None,
        })

    # 2) Code promo actif récemment créé → « profite de ma promo ».
    last_promo = (
        PromoCode.query
        .filter(PromoCode.owner_id == owner_id, PromoCode.is_active.is_(True),
                PromoCode.created_at >= since)
        .order_by(PromoCode.created_at.desc())
        .first()
    )
    if last_promo and not last_promo.is_expired and not last_promo.is_exhausted:
        deadline = (f" jusqu'au {last_promo.expires_at.strftime('%d/%m')}"
                    if last_promo.expires_at else '')
        templates.append({
            'id':      'promo',
            'label':   f'Code promo {last_promo.code}',
            'icon':    'tag',
            'subject': f'-{last_promo.percent} % avec le code {last_promo.code}',
            'body': (
                f"Petite attention : le code {last_promo.code} te donne "
                f"-{last_promo.percent} %{deadline}.\n\n"
                "C'est le moment de récupérer le son que tu avais repéré. À toi de jouer !"
            ),
            'segment':       CampaignSegment.BUYERS.value,
            'promo_code_id': last_promo.id,
        })

    # 3) Toujours disponible : reprise de contact générique (page blanche évitée
    #    même quand il n'y a pas d'activité récente).
    templates.append({
        'id':      'catchup',
        'label':   'Reprendre contact',
        'icon':    'chat-heart',
        'subject': 'Du nouveau de mon côté',
        'body': (
            "Ça fait un moment ! Je continue de produire et j'aimerais te tenir au "
            "courant de mes dernières sorties.\n\n"
            "Passe faire un tour quand tu veux — il y a sûrement de quoi te plaire."
        ),
        'segment':       CampaignSegment.LISTENERS.value,
        'promo_code_id': None,
    })

    return templates
