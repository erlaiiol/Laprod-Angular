"""
Blueprint CAMPAIGN API — campagnes de mailing des vendeurs (Premium)

Vendeur (Premium) :
  GET    /api/campaigns                   → mes campagnes + quota + stats
  GET    /api/campaigns/context           → audiences, créneaux proposés, codes promo
  POST   /api/campaigns                   → créer un brouillon
  PATCH  /api/campaigns/<id>              → modifier un brouillon
  POST   /api/campaigns/<id>/schedule     → planifier sur un créneau validé
  POST   /api/campaigns/<id>/cancel       → annuler avant l'envoi
  DELETE /api/campaigns/<id>              → supprimer un brouillon
  POST   /api/campaigns/<id>/checkout     → Super Premium : payer la diffusion totale

Destinataire :
  GET    /api/campaigns/marketing-preferences   → mon consentement
  PUT    /api/campaigns/marketing-preferences   → l'activer / le retirer
  POST   /api/campaigns/unsubscribe             → désinscription par token (public)
"""
from datetime import datetime

import stripe
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import select

from extensions import db, csrf
from models import (
    MarketingCampaign, CampaignRecipient, CampaignSegment, CampaignStatus,
    PromoCode, PromoCodeScope, User,
)
from serializers import ok, err, campaign as campaign_dto
from utils.auth_helpers import require_user
from utils.money import to_money, to_cents, from_cents
from utils.email_service import verify_unsubscribe_token
from utils.campaign_service import (
    CampaignError, audience_preview, audience_size, quota_status, suggest_slots,
    validate_slot, campaign_stats, suggest_templates, SUPER_PREMIUM_PRICE_EUR,
)

campaign_api_bp = Blueprint('campaign_api', __name__, url_prefix='/api/campaigns')

SUBJECT_MAX = 120
BODY_MAX    = 2000


# ── Habilitations ────────────────────────────────────────────────────────────

def _require_seller_premium(user):
    """Les campagnes sont réservées aux vendeurs Premium. Autorisation SERVEUR :
    le front masque l'onglet, mais c'est ce test qui protège l'endpoint."""
    if not (user.is_beatmaker or user.is_mixmaster_engineer):
        return err('Les campagnes sont réservées aux beatmakers et ingénieurs Mix/Master certifiés.',
                   code='NOT_A_SELLER', status=403)
    if not user.is_premium_active:
        return err('Les campagnes de mailing sont réservées aux membres Premium.',
                   code='PREMIUM_REQUIRED', status=403)
    return None


def _own_campaign(campaign_id, user):
    campaign = db.session.get(MarketingCampaign, campaign_id)
    if not campaign or campaign.owner_id != user.id:
        return None, err('Campagne introuvable.', code='NOT_FOUND', status=404)
    return campaign, None


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_payload(data, user, campaign=None):
    subject = (data.get('subject') or '').strip()
    body    = (data.get('body') or '').strip()
    segment = (data.get('segment') or CampaignSegment.BUYERS.value).strip()

    if not (3 <= len(subject) <= SUBJECT_MAX):
        return None, f'Le sujet doit faire entre 3 et {SUBJECT_MAX} caractères.'
    if not (10 <= len(body) <= BODY_MAX):
        return None, f'Le message doit faire entre 10 et {BODY_MAX} caractères.'
    if segment not in [s.value for s in CampaignSegment]:
        return None, 'Segment invalide.'

    # Code promo : facultatif, mais s'il est fourni il doit appartenir au vendeur
    # ET être encore vivant — mettre en avant un code expiré dans un mail, c'est
    # envoyer des gens vers une promo qui ne marchera pas.
    promo_id = data.get('promo_code_id')
    promo = None
    if promo_id:
        promo = db.session.get(PromoCode, int(promo_id))
        if not promo or promo.owner_id != user.id:
            return None, 'Code promo introuvable.'
        if not promo.is_active or promo.is_expired or promo.is_exhausted:
            return None, "Ce code promo n'est plus valide : il n'a aucun intérêt en campagne."

    return {
        'subject':       subject,
        'body':          body,
        'segment':       segment,
        'promo_code_id': promo.id if promo else None,
    }, None


# ── GET /api/campaigns ───────────────────────────────────────────────────────

@campaign_api_bp.route('', methods=['GET'])
@jwt_required()
@require_user
def list_campaigns(current_user):
    """Mes campagnes. Lisible même sans Premium actif : un Premium expiré doit
    pouvoir consulter ses résultats passés et annuler une campagne planifiée."""
    campaigns = (
        MarketingCampaign.query.filter_by(owner_id=current_user.id)
        .order_by(MarketingCampaign.created_at.desc()).all()
    )
    return ok({
        'campaigns': [campaign_dto(c, campaign_stats(c)) for c in campaigns],
        'quota':     _quota_dto(current_user.id),
        'can_create': bool(
            (current_user.is_beatmaker or current_user.is_mixmaster_engineer)
            and current_user.is_premium_active
        ),
    })


def _quota_dto(owner_id):
    q = quota_status(owner_id)
    return {
        'used':            q['used'],
        'max':             q['max'],
        'remaining':       q['remaining'],
        'cooldown_days':   q['cooldown_days'],
        'next_allowed_at': q['next_allowed_at'].isoformat() if q['next_allowed_at'] else None,
    }


# ── GET /api/campaigns/context ───────────────────────────────────────────────

@campaign_api_bp.route('/context', methods=['GET'])
@jwt_required()
@require_user
def campaign_context(current_user):
    """Tout ce dont l'écran de composition a besoin : taille de chaque audience,
    créneaux d'envoi proposés, codes promo utilisables."""
    gate = _require_seller_premium(current_user)
    if gate:
        return gate

    promos = PromoCode.query.filter_by(owner_id=current_user.id, is_active=True).all()
    usable = [p for p in promos if not p.is_expired and not p.is_exhausted]

    return ok({
        'audiences':   audience_preview(current_user.id),
        'slots':       [s.isoformat() for s in suggest_slots(current_user.id)],
        'quota':       _quota_dto(current_user.id),
        'promo_codes': [
            {'id': p.id, 'code': p.code, 'percent': p.percent, 'scope': p.scope}
            for p in usable
        ],
        # Brouillons pré-remplis d'après l'activité récente : un clic pour démarrer.
        'templates':   suggest_templates(current_user.id),
        'super_premium_price': float(to_money(SUPER_PREMIUM_PRICE_EUR)),
    })


# ── POST /api/campaigns ──────────────────────────────────────────────────────

@campaign_api_bp.route('', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def create_campaign(current_user):
    gate = _require_seller_premium(current_user)
    if gate:
        return gate

    payload, error = _validate_payload(request.get_json() or {}, current_user)
    if error:
        return err(error, code='CAMPAIGN_INVALID', status=400)

    campaign = MarketingCampaign(
        owner_id=current_user.id,
        status=CampaignStatus.DRAFT.value,
        **payload,
    )
    db.session.add(campaign)
    db.session.commit()
    return ok({'campaign': campaign_dto(campaign, campaign_stats(campaign))},
              message='Brouillon enregistré.', status=201)


# ── PATCH /api/campaigns/<id> ────────────────────────────────────────────────

@campaign_api_bp.route('/<int:campaign_id>', methods=['PATCH'])
@csrf.exempt
@jwt_required()
@require_user
def update_campaign(campaign_id, current_user):
    campaign, error = _own_campaign(campaign_id, current_user)
    if error:
        return error

    gate = _require_seller_premium(current_user)
    if gate:
        return gate

    # Une campagne partie est un fait : son contenu ne se réécrit pas a posteriori,
    # sinon les statistiques ne veulent plus rien dire.
    if not campaign.is_editable:
        return err('Cette campagne a déjà été envoyée et ne peut plus être modifiée.',
                   code='CAMPAIGN_LOCKED', status=409)

    payload, error = _validate_payload(request.get_json() or {}, current_user, campaign)
    if error:
        return err(error, code='CAMPAIGN_INVALID', status=400)

    # Changer de segment après paiement : on ne rembourse pas silencieusement.
    if campaign.is_paid and payload['segment'] != CampaignSegment.ALL.value:
        return err(
            'Cette campagne a été payée pour une diffusion à toute la plateforme. '
            'Contactez le support pour changer de segment.',
            code='CAMPAIGN_PAID_SEGMENT', status=409,
        )

    for field, value in payload.items():
        setattr(campaign, field, value)
    db.session.commit()
    return ok({'campaign': campaign_dto(campaign, campaign_stats(campaign))},
              message='Campagne mise à jour.')


# ── POST /api/campaigns/<id>/schedule ────────────────────────────────────────

@campaign_api_bp.route('/<int:campaign_id>/schedule', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def schedule_campaign(campaign_id, current_user):
    """Planifie l'envoi sur un créneau. Rien ne part ici : c'est le job de
    dispatch qui envoie, à l'heure dite."""
    campaign, error = _own_campaign(campaign_id, current_user)
    if error:
        return error

    gate = _require_seller_premium(current_user)
    if gate:
        return gate

    # FAILED est replanifiable : une campagne dont le dispatch a échoué (SMTP
    # indisponible, incident) n'a atteint personne. L'interdire ferait perdre au
    # vendeur les 19,99 € d'une diffusion Super Premium payée mais jamais partie —
    # le paiement reste attaché à la campagne, il rejoue simplement un créneau.
    if campaign.status not in (CampaignStatus.DRAFT.value,
                               CampaignStatus.SCHEDULED.value,
                               CampaignStatus.FAILED.value):
        return err('Cette campagne a déjà été envoyée.', code='CAMPAIGN_LOCKED', status=409)

    # Le segment « toute la plateforme » est le seul payant : sans paiement
    # encaissé, il n'est pas planifiable. Contrôle serveur, pas UI.
    if campaign.requires_payment and not campaign.is_paid:
        return err(
            'La diffusion à toute la plateforme nécessite un paiement unique.',
            code='PAYMENT_REQUIRED', status=402,
        )

    raw = (request.get_json() or {}).get('scheduled_for')
    try:
        scheduled_for = datetime.fromisoformat(str(raw).replace('Z', '+00:00')).replace(tzinfo=None)
    except (TypeError, ValueError):
        return err('Créneau invalide.', code='SLOT_INVALID', status=400)

    try:
        validate_slot(current_user.id, scheduled_for, campaign=campaign)
    except CampaignError as e:
        return err(e.message, code=e.code, status=400)

    size = audience_size(current_user.id, campaign.segment)
    if size == 0:
        return err(
            "Personne n'est joignable dans ce segment : vos destinataires potentiels "
            "n'ont pas accepté de recevoir d'offres. Essayez un autre segment.",
            code='EMPTY_AUDIENCE', status=400,
        )

    # Rejeu d'une campagne échouée : on purge les tentatives NON abouties
    # (sent_at IS NULL). Sans ça, le garde anti-doublon du dispatch les verrait
    # comme « déjà traitées » et ces destinataires ne recevraient jamais rien.
    # Les lignes réellement envoyées sont conservées : elles empêchent, elles, un
    # second envoi aux personnes déjà servies.
    if campaign.status == CampaignStatus.FAILED.value:
        CampaignRecipient.query.filter(
            CampaignRecipient.campaign_id == campaign.id,
            CampaignRecipient.sent_at.is_(None),
        ).delete(synchronize_session=False)

    campaign.scheduled_for = scheduled_for
    campaign.status = CampaignStatus.SCHEDULED.value
    db.session.commit()

    return ok(
        {'campaign': campaign_dto(campaign, campaign_stats(campaign)), 'audience_size': size},
        message=f'Campagne planifiée pour le {scheduled_for.strftime("%d/%m/%Y à %H h")} '
                f'— environ {size} destinataires.',
    )


# ── POST /api/campaigns/<id>/cancel ──────────────────────────────────────────

@campaign_api_bp.route('/<int:campaign_id>/cancel', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def cancel_campaign(campaign_id, current_user):
    campaign, error = _own_campaign(campaign_id, current_user)
    if error:
        return error

    if campaign.status != CampaignStatus.SCHEDULED.value:
        return err('Seule une campagne planifiée peut être annulée.',
                   code='CAMPAIGN_NOT_SCHEDULED', status=409)

    # Retour en brouillon plutôt que « annulée » : le vendeur récupère son
    # travail, et son crédit Super Premium éventuel reste attaché à la campagne.
    campaign.status = CampaignStatus.DRAFT.value
    campaign.scheduled_for = None
    db.session.commit()
    return ok({'campaign': campaign_dto(campaign, campaign_stats(campaign))},
              message='Campagne annulée et remise en brouillon.', level='info')


# ── DELETE /api/campaigns/<id> ───────────────────────────────────────────────

@campaign_api_bp.route('/<int:campaign_id>', methods=['DELETE'])
@csrf.exempt
@jwt_required()
@require_user
def delete_campaign(campaign_id, current_user):
    campaign, error = _own_campaign(campaign_id, current_user)
    if error:
        return error

    # Une campagne envoyée est une pièce d'audit (qui a mailé qui, et quand) :
    # on ne l'efface pas, elle est la preuve du respect du consentement.
    if campaign.status in (CampaignStatus.SENT.value, CampaignStatus.SENDING.value):
        return err('Une campagne envoyée ne peut pas être supprimée.',
                   code='CAMPAIGN_LOCKED', status=409)

    db.session.delete(campaign)
    db.session.commit()
    return ok({'deleted': True}, message='Campagne supprimée.')


# ── POST /api/campaigns/<id>/checkout — Super Premium ────────────────────────

@campaign_api_bp.route('/<int:campaign_id>/checkout', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def create_super_premium_checkout(campaign_id, current_user):
    """Paiement unique débloquant la diffusion à TOUTE la plateforme pour CETTE
    campagne. Le prix est fixé côté serveur : le client n'envoie aucun montant.

    Deux garde-fous contre un double-clic / double-onglet, qui créeraient sinon
    deux sessions Stripe payables séparément pour la même campagne (la seconde
    resterait encaissée sans jamais débloquer quoi que ce soit) :
      - verrou de ligne (FOR UPDATE) sur `is_paid` avant de contacter Stripe ;
      - idempotency_key Stripe déterministe par campagne : deux appels tant que
        la campagne n'est pas payée renvoient LA MÊME session au lieu d'en
        recréer une (le cache Stripe expire avec la session, ~24h).
    """
    campaign = db.session.execute(
        select(MarketingCampaign)
        .where(MarketingCampaign.id == campaign_id)
        .with_for_update()
    ).scalar_one_or_none()
    if not campaign or campaign.owner_id != current_user.id:
        return err('Campagne introuvable.', code='NOT_FOUND', status=404)

    gate = _require_seller_premium(current_user)
    if gate:
        return gate

    if not campaign.requires_payment:
        return err('Cette campagne ne nécessite pas de paiement.',
                   code='NO_PAYMENT_NEEDED', status=400)
    if campaign.is_paid:
        return err('Cette campagne est déjà payée.', code='ALREADY_PAID', status=409)

    price = to_money(SUPER_PREMIUM_PRICE_EUR)
    frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:4200')

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': to_cents(price),
                    'product_data': {
                        'name': 'Campagne — diffusion à toute la plateforme',
                        'description': f'Campagne « {campaign.subject} »',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{frontend_url}/campagnes?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{frontend_url}/campagnes',
            customer_email=current_user.email,
            metadata={
                'type':        'campaign_super_premium',
                'campaign_id': str(campaign.id),
                'owner_id':    str(current_user.id),
            },
            idempotency_key=f'campaign-{campaign.id}-super-premium-checkout',
        )
        return ok({'checkout_url': session.url, 'price': float(price)})
    except stripe.StripeError as e:
        current_app.logger.error(f'Stripe checkout campagne #{campaign.id} : {e}', exc_info=True)
        return err(f'Erreur Stripe : {e}', code='STRIPE_ERROR', status=500)


@campaign_api_bp.route('/verify', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def verify_super_premium(current_user):
    """Confirme le paiement Super Premium après retour de Stripe."""
    session_id = (request.get_json() or {}).get('session_id', '').strip()
    if not session_id:
        return err('session_id requis.', code='MISSING_SESSION', status=400)

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status != 'paid':
            return err('Paiement non confirmé.', code='PAYMENT_NOT_SUCCEEDED', status=400)

        meta = session.metadata or {}
        if meta.get('type') != 'campaign_super_premium':
            return err('Session invalide.', code='INVALID_SESSION', status=400)
        if int(meta.get('owner_id', -1)) != current_user.id:
            return err('Cette session ne vous appartient pas.', code='UNAUTHORIZED', status=403)

        campaign = db.session.get(MarketingCampaign, int(meta.get('campaign_id', 0)))
        if not campaign or campaign.owner_id != current_user.id:
            return err('Campagne introuvable.', code='NOT_FOUND', status=404)

        # Idempotence : un rechargement de la page de retour ne doit pas
        # ré-enregistrer le paiement.
        if campaign.is_paid:
            return ok({'campaign': campaign_dto(campaign, campaign_stats(campaign))},
                      message='Paiement déjà enregistré.', level='info')

        # Le montant est relu de Stripe EN CENTIMES (entier) et converti par
        # from_cents : `amount_total / 100` serait une division flottante — soit
        # exactement ce que utils/money.py existe pour interdire.
        amount_paid = from_cents(session.amount_total)
        expected    = to_money(SUPER_PREMIUM_PRICE_EUR)

        # Défense en profondeur : on ne débloque une diffusion à toute la plateforme
        # que si le montant réellement encaissé couvre le prix. Un écart signifie
        # que la session ne correspond pas à ce qu'on croit vendre.
        if amount_paid < expected:
            current_app.logger.error(
                f'Campagne #{campaign.id} — montant encaissé {amount_paid}€ '
                f'inférieur au prix attendu {expected}€ (session {session_id})'
            )
            return err('Le montant payé ne correspond pas au prix de la diffusion.',
                       code='AMOUNT_MISMATCH', status=400)

        campaign.stripe_payment_intent_id = session.payment_intent
        campaign.amount_paid = amount_paid
        db.session.commit()

        return ok({'campaign': campaign_dto(campaign, campaign_stats(campaign))},
                  message='Paiement confirmé — vous pouvez planifier votre diffusion totale.')

    except stripe.StripeError as e:
        current_app.logger.error(f'Vérif Stripe campagne : {e}', exc_info=True)
        return err(f'Erreur Stripe : {e}', code='STRIPE_ERROR', status=500)


# ── Consentement du destinataire ─────────────────────────────────────────────

@campaign_api_bp.route('/marketing-preferences', methods=['GET'])
@jwt_required()
@require_user
def get_marketing_preferences(current_user):
    return ok({
        'marketing_opt_in': current_user.marketing_opt_in,
        'email_verified':   current_user.email_verified,
    })


@campaign_api_bp.route('/marketing-preferences', methods=['PUT'])
@csrf.exempt
@jwt_required()
@require_user
def set_marketing_preferences(current_user):
    """Active ou retire le consentement. L'horodatage est la preuve du
    consentement — il n'est posé qu'à l'activation, jamais reconstitué."""
    opt_in = bool((request.get_json() or {}).get('marketing_opt_in', False))

    current_user.marketing_opt_in = opt_in
    current_user.marketing_opt_in_at = datetime.now() if opt_in else None
    db.session.commit()

    return ok(
        {'marketing_opt_in': opt_in},
        message='Vous recevrez les offres des artistes que vous suivez.' if opt_in
                else 'Vous ne recevrez plus aucune offre commerciale.',
    )


@campaign_api_bp.route('/unsubscribe', methods=['POST'])
@csrf.exempt
def unsubscribe():
    """Désinscription par token signé — PUBLIC, sans authentification.

    Exiger une connexion pour se désinscrire reviendrait à rendre la
    désinscription plus difficile que l'inscription : c'est précisément ce que
    la loi interdit (art. L.34-5 CPCE, « moyen simple et gratuit »).
    """
    token = (request.get_json() or {}).get('token', '').strip()
    user_id = verify_unsubscribe_token(token)
    if not user_id:
        return err('Lien de désinscription invalide ou expiré.',
                   code='INVALID_TOKEN', status=400)

    user = db.session.get(User, user_id)
    if not user:
        return err('Utilisateur introuvable.', code='NOT_FOUND', status=404)

    user.marketing_opt_in = False
    user.marketing_opt_in_at = None
    db.session.commit()

    current_app.logger.info(f'Désinscription marketing — user #{user.id}')
    return ok({'unsubscribed': True},
              message='Vous ne recevrez plus d\'offres commerciales. C\'est immédiat.')
