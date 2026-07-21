"""
utils/plans.py — Source unique de vérité des paliers d'abonnement
=================================================================

Toute la définition des plans vit ICI : prix, quotas, capacités. Avant ce module,
la logique était disséminée (models.py, premium_api, admin_api, tracks_api), et
chaque ajout de palier obligeait à retrouver tous les `== 'pro'` du projet — avec
la garantie d'en oublier un, c'est-à-dire d'ouvrir une faille d'autorisation.

Règle : aucun code métier ne compare `subscription_plan` à une chaîne littérale.
On passe par les capacités (`user.can_*`) ou par `plan_rank()`.

Philosophie des paliers (voulue par LaProd — fidélité, pas agressivité) :

  FREE          Découverte. On teste les toplines, on uploade « pour voir ».

  PREMIUM       L'indépendant amateur. Plus de toplines, plus d'uploads, et surtout
                les outils de VENDEUR : fixer ses prix de droits, proposer ses beats
                en exclusivité, créer des codes promo et des campagnes.

  SEMI_PRO      L'habitué : produit tous les jours, chante, enchaîne les toplines.
                Contract builder en accès limité (1 contrat/mois).

  PRO_STRUCTURE Les structures déjà sur le marché : SMAC, festivals, clubs, labels.
                Contract builder illimité. Leur besoin n'est pas de faire de la
                musique, c'est de sécuriser juridiquement des dizaines d'intervenants
                sans payer des milliers d'euros de juriste. Le prix l'assume.

── Le quota d'upload est une CADENCE, pas un plafond de catalogue ────────────────
Le nombre de beats qu'un utilisateur garde en ligne est ILLIMITÉ, à tous les
paliers. Ce que le palier module, c'est le nombre de NOUVEAUX beats publiables par
jour (`upload_gain`). C'est volontaire : en limitant le débit quotidien, on pousse
doucement chacun à ne mettre en avant que ses meilleures productions, sans jamais
l'obliger à retirer quoi que ce soit. `upload_cap` est la petite réserve de jours
non utilisés qu'on peut accumuler (le créateur occasionnel ne « perd » pas ses
jours de pause), pas une limite de catalogue.

  débutant → occasionnel        → 1 beat/jour
  habitué  → 0,1 à 2 beats/jour  → 2 beats/jour
  pro      → produit chaque jour → 10 beats/jour
"""
from decimal import Decimal

# ── Identifiants de plan ─────────────────────────────────────────────────────

FREE          = 'free'
PREMIUM       = 'premium'
SEMI_PRO      = 'semi_pro'
PRO_STRUCTURE = 'pro_structure'

# Ordre croissant : sert à tous les tests « au moins ce palier ». Un rang, pas une
# liste de comparaisons — ajouter un palier n'oblige à toucher aucun appelant.
PLAN_ORDER = (FREE, PREMIUM, SEMI_PRO, PRO_STRUCTURE)

# Plans souscriptibles (FREE ne se paie pas).
PAID_PLANS = (PREMIUM, SEMI_PRO, PRO_STRUCTURE)

# Anciens identifiants → nouveaux. Conservé parce que des lignes en base, des
# métadonnées Stripe et des JWT peuvent encore porter les anciennes valeurs :
# normaliser à la lecture évite qu'un ancien 'pro' se retrouve silencieusement
# rétrogradé au rang de FREE (donc privé de ce qu'il a payé).
LEGACY_ALIASES = {
    'amateur': PREMIUM,
    'pro':     PRO_STRUCTURE,
}


def normalize(plan: str) -> str:
    """Ramène un identifiant de plan (même ancien) à sa valeur canonique."""
    if not plan:
        return FREE
    plan = str(plan).strip()
    plan = LEGACY_ALIASES.get(plan, plan)
    return plan if plan in PLAN_ORDER else FREE


def plan_rank(plan: str) -> int:
    """Rang du plan (FREE = 0). Permet `rank(user) >= rank(SEMI_PRO)`."""
    return PLAN_ORDER.index(normalize(plan))


# ── Définition des paliers ───────────────────────────────────────────────────

# Registres de langue. Ce n'est pas un détail cosmétique : c'est la façon dont
# on signale à quel type de client on parle.
#
#   TU   — l'indépendant, le particulier : artiste, beatmaker, ingénieur. C'est le
#          registre de la partie création/marketplace du site (home, track-detail,
#          commande mix/master, configuration de licence).
#   VOUS — la structure : SMAC, festival, club, label. C'est déjà le registre du
#          Contract Builder et du Contract Analyzer, c'est-à-dire exactement leurs
#          outils. On ne tutoie pas un régisseur de SMAC qui contractualise ses
#          intervenants — ça décrédibiliserait l'outil au moment précis où il doit
#          inspirer confiance.
TONE_TU   = 'tu'
TONE_VOUS = 'vous'


class Plan:
    """Un palier : à qui il s'adresse, sur quel ton, ce qu'il coûte, ce qu'il donne."""

    def __init__(self, key, label, price, tagline, audience, highlight, tone,
                 upload_cap, upload_gain, topline_cap, topline_gain,
                 contract_quota, features):
        self.key            = key
        self.label          = label
        self.price          = Decimal(str(price))   # EUR / 30 jours
        self.tagline        = tagline
        # Registre dans lequel TOUT le texte de ce palier est rédigé. Le front s'en
        # sert aussi pour ajuster le libellé du bouton d'action.
        self.tone           = tone
        # Typologie de clientèle : à qui ce palier parle, en une phrase. C'est ce
        # que l'utilisateur cherche vraiment sur une grille tarifaire — « est-ce
        # que c'est moi, ça ? » — bien avant de comparer les fonctionnalités.
        self.audience       = audience
        # L'argument massue du palier : celui qui, à lui seul, justifie le prix.
        self.highlight      = highlight
        # upload_gain = NOUVEAUX beats publiables par jour (la vraie limite du
        # palier). upload_cap = réserve de jours non consommés qu'on peut accumuler,
        # PAS un plafond de catalogue (le catalogue est illimité partout).
        self.upload_gain    = upload_gain
        self.upload_cap     = upload_cap
        self.topline_cap    = topline_cap
        self.topline_gain   = topline_gain          # par semaine
        # Contrats générables par mois via le contract builder.
        # None = illimité, 0 = pas d'accès.
        self.contract_quota = contract_quota
        self.features       = features              # argumentaire, affiché tel quel

    @property
    def uploads_per_day(self):
        """Cadence quotidienne d'upload — le chiffre à afficher à l'utilisateur."""
        return self.upload_gain


PLANS = {
    FREE: Plan(
        key=FREE, label='Découverte', price='0', tone=TONE_TU,
        tagline='Prends ton temps. Il n’y a pas de compte à rebours.',
        audience="Tu découvres la musique depuis ta chambre. Tu veux voir ce que ça "
                 "donne avant de t’engager — c’est exactement pour ça que ce palier "
                 "existe.",
        # NB : ne PAS promettre « tu ne seras jamais relancé » — un job de
        # re-engagement (utils/scheduled_tasks.run_reengagement_emails) écrit aux
        # utilisateurs inactifs. Un argument que le code contredit est un mensonge,
        # et il finira par se voir.
        highlight='Gratuit, sans carte bancaire, sans limite de durée. Tu montes d’un '
                  'palier le jour où tu en as besoin — pas parce qu’on t’y pousse.',
        upload_gain=1, upload_cap=3,   # 1 nouveau beat/jour, jusqu'à 3 en réserve
        topline_cap=5, topline_gain=5,
        contract_quota=0,
        features=[
            'Publie 1 nouveau beat par jour',
            'Ton catalogue en ligne reste illimité, à vie',
            'Enregistre des toplines pour te faire la main',
            'Achète des beats et télécharge tes licences',
        ],
    ),
    PREMIUM: Plan(
        key=PREMIUM, label='Premium', price='4.99', tone=TONE_TU,
        tagline='Le jour où tu commences à vendre pour de vrai.',
        audience="Tu es indépendant, tu produis régulièrement, et tes premiers "
                 "acheteurs arrivent. Tu ne veux pas d’un studio : tu veux maîtriser "
                 "ta boutique.",
        # L'argument le plus fort n'est pas un quota, c'est la souveraineté sur
        # ses prix — et le fait que LaProd ne se paie pas sur la remise du vendeur.
        highlight='Tes prix, tes droits, tes remises — tu décides de tout. LaProd '
                  'prélève 10 % du montant réellement encaissé : quand tu fais une '
                  'promo, notre commission baisse avec la tienne. Ta remise n’est '
                  'jamais taxée.',
        upload_gain=2, upload_cap=6,   # 2 nouveaux beats/jour
        topline_cap=50, topline_gain=50,
        contract_quota=0,
        features=[
            'Fixe toi-même le prix de CHACUN des droits de tes beats',
            'Propose tes beats en exclusivité — la vente la plus rémunératrice',
            'Crée tes codes promo et tes campagnes de mailing',
            'Publie 2 nouveaux beats par jour (catalogue illimité)',
            'Toplines : 50 crédits par semaine',
        ],
    ),
    SEMI_PRO: Plan(
        key=SEMI_PRO, label='Semi-Pro', price='12.99', tone=TONE_TU,
        tagline='Tu produis tous les jours. Le palier ne te freine plus.',
        audience="Tu produis à un rythme pro — jusqu’à une dizaine de beats par jour — "
                 "tu chantes, tu enchaînes les toplines. La musique n’est plus un loisir "
                 "du week-end, c’est ton métier.",
        # Argument recentré sur le débit quotidien (pas un plafond de catalogue) et
        # les toplines quasi illimitées : à ce rythme la plateforme ne te freine plus.
        highlight='Jusqu’à 10 nouveaux beats par jour et 200 toplines par semaine : à '
                  'ce rythme, la plateforme ne te freine plus. Ton catalogue reste '
                  'illimité — tu choisis simplement, chaque jour, tes meilleures sorties.',
        upload_gain=10, upload_cap=18,   # 10 nouveaux beats/jour
        topline_cap=200, topline_gain=200,
        contract_quota=1,
        features=[
            'Publie jusqu’à 10 nouveaux beats par jour (catalogue illimité)',
            'Toplines quasi illimitées : 200 crédits par semaine',
            'Badge Mastering Pro — tu peux facturer le mastering',
            'Contract Builder : 1 contrat par mois (largement suffisant hors structure)',
            'Tous les avantages Premium',
        ],
    ),
    PRO_STRUCTURE: Plan(
        # Seul palier au VOUS : on s'adresse à une structure, pas à un particulier.
        # C'est déjà le registre du Contract Builder — leur outil.
        key=PRO_STRUCTURE, label='Pro Structuré', price='49.99', tone=TONE_VOUS,
        tagline='Le juridique en deux clics, sans facture de cabinet.',
        audience="Vous êtes une structure : SMAC, festival, club, label. Vous faites "
                 "intervenir des dizaines d’artistes par saison, et chacun doit être "
                 "couvert. Vous avez un budget — mais pas celui d’un cabinet.",
        # L'argument massue, et le seul qui compte pour une structure : le ratio.
        # Un contrat rédigé par un juriste coûte 500 à 2 000 €. Un seul contrat
        # généré ici rembourse l'année d'abonnement.
        highlight='Un contrat rédigé par un juriste coûte entre 500 et 2 000 €. Ici, '
                  'le premier contrat que vous générez a déjà remboursé une année '
                  'd’abonnement — et les suivants sont illimités.',
        upload_gain=10, upload_cap=18,   # mêmes uploads que Semi-Pro : la valeur ici, c'est le juridique
        topline_cap=200, topline_gain=200,
        contract_quota=None,   # illimité
        features=[
            'Contract Builder ILLIMITÉ — tous types de contrats',
            'Sécurisez juridiquement chaque intervenant, artiste par artiste',
            'Vos contrats vous appartiennent : vous les gardez même si vous partez',
            'Facturable et déductible en tant que charge d’exploitation',
            'Tous les avantages Semi-Pro',
        ],
    ),
}


def get(plan: str) -> Plan:
    return PLANS[normalize(plan)]


def price_of(plan: str) -> Decimal:
    return get(plan).price


def label_of(plan: str) -> str:
    return get(plan).label


def public_catalog() -> list:
    """Grille tarifaire pour la page d'abonnement (front)."""
    return [{
        'key':            p.key,
        'label':          p.label,
        'price':          float(p.price),
        'tagline':        p.tagline,
        'audience':       p.audience,
        'highlight':      p.highlight,
        'tone':           p.tone,
        'features':        p.features,
        'uploads_per_day': p.uploads_per_day,   # cadence — la vraie limite du palier
        'upload_reserve':  p.upload_cap,         # réserve de jours accumulables
        'catalogue_limit': None,                 # None = illimité, à tous les paliers
        'topline_cap':     p.topline_cap,
        'contract_quota':  p.contract_quota,
    } for p in (PLANS[k] for k in PLAN_ORDER)]


# ── Tableau comparatif ────────────────────────────────────────────────────────

def _contract_cell(plan_key):
    """Cellule « Contract Builder » : dépend du quota, pas d'un simple oui/non."""
    quota = PLANS[plan_key].contract_quota
    if quota is None:
        return {'kind': 'text', 'text': 'Illimité'}
    if quota == 0:
        return {'kind': 'no'}
    return {'kind': 'text', 'text': f'{quota} / mois'}


def comparison_matrix() -> dict:
    """Matrice comparative des paliers, dérivée des MÊMES seuils que les capacités.

    Construite ici plutôt qu'en dur dans le front : une case cochée dans le tableau
    doit toujours correspondre à ce que l'API autorise réellement. Si les deux
    divergent, on ment au client — soit on lui vend un droit qu'il n'aura pas, soit
    on lui cache un droit qu'il a payé.
    """
    order = list(PLAN_ORDER)

    def bool_row(label, minimum, help_text=None):
        return {
            'label':     label,
            'help':      help_text,
            'cells':     [
                {'kind': 'yes' if plan_rank(k) >= plan_rank(minimum) else 'no'}
                for k in order
            ],
        }

    def text_row(label, value_fn, help_text=None):
        return {
            'label': label,
            'help':  help_text,
            'cells': [{'kind': 'text', 'text': value_fn(PLANS[k])} for k in order],
        }

    groups = [
        {
            'title': 'Création & catalogue',
            'rows': [
                text_row('Nouveaux beats par jour', lambda p: str(p.uploads_per_day),
                         'Le nombre de beats que tu peux publier chaque jour.'),
                text_row('Beats en ligne au total', lambda p: 'Illimité',
                         'Ton catalogue n’est jamais plafonné, à aucun palier.'),
                text_row('Toplines par semaine', lambda p: str(p.topline_cap)),
            ],
        },
        {
            'title': 'Outils de vente',
            'rows': [
                bool_row('Fixer le prix de chacun de tes droits', PREMIUM),
                bool_row('Proposer tes beats en exclusivité', PREMIUM),
                bool_row('Codes promo & campagnes de mailing', PREMIUM),
                bool_row('Ciblage des campagnes par affinité musicale', PREMIUM,
                         'Adresser les auditeurs dont les goûts collent à ton style, '
                         'même s’ils ne te connaissent pas encore.'),
                bool_row('Badge Mastering Pro', SEMI_PRO),
            ],
        },
        {
            'title': 'Contrats',
            'rows': [
                {
                    'label': 'Contract Builder',
                    'help':  'Générer des contrats prêts à signer, tous intervenants couverts.',
                    'cells': [_contract_cell(k) for k in order],
                },
                bool_row('Contrat de management + royalties chiffrées', PREMIUM,
                         'Formaliser un lien roster par un mandat et suivre la '
                         'cap-table de chaque titre. Le lien roster et le '
                         'rétroplanning partagé restent gratuits à tous les paliers.'),
            ],
        },
    ]

    return {
        'columns': [{
            'key':       p.key,
            'label':     p.label,
            'price':     float(p.price),
            'tone':      p.tone,
        } for p in (PLANS[k] for k in order)],
        'groups': groups,
    }
