"""
Seed data for the contract builder: groups, clauses, tooltips, legal references
and example quasi-legal French texts.

Called by the `flask seed-contract-builder` CLI command in app.py.
"""

from models import ContractClause, ContractClauseGroup, ClauseTypeEnum
from extensions import db


def run_seed() -> None:
    """Insert all contract builder groups and clauses. No-op if data already exists."""
    if db.session.query(ContractClauseGroup).count() > 0:
        return

    def _g(name, description=None, tooltip=None, sort_order=0):
        g = ContractClauseGroup(
            name=name, description=description, tooltip=tooltip, sort_order=sort_order
        )
        db.session.add(g)
        db.session.flush()
        return g

    def _c(group, name, ctype, tooltip_short=None, tooltip_long=None,
           legal_ref=None, options=None, default_value=None,
           required=False, enabled_by_default=True, sort_order=0, example=None):
        db.session.add(ContractClause(
            group_id              = group.id,
            name                  = name,
            clause_type           = ClauseTypeEnum(ctype),
            tooltip_short         = tooltip_short,
            tooltip_long          = tooltip_long,
            legal_reference       = legal_ref,
            options               = options,
            default_value         = default_value,
            is_required           = required,
            is_enabled_by_default = enabled_by_default,
            sort_order            = sort_order,
            example_text          = example,
        ))

    # ── 0 — Préambule ─────────────────────────────────────────────────────────
    g = _g("Préambule", tooltip="Contexte, volonté des parties, historique de collaboration.", sort_order=0)
    _c(g, "Contexte et volonté des parties", "textarea", sort_order=0,
       tooltip_short="Décrivez le contexte général du contrat et les intentions communes.",
       tooltip_long="Le préambule expose la volonté des parties et peut servir à interpréter le contrat en cas de litige. Il n'est pas juridiquement contraignant en lui-même mais oriente l'interprétation des clauses.",
       example=(
           "[Contractant 1], en qualité de [Rôle 1], ci-après dénommé(e) « le [Rôle 1] », "
           "et [Contractant 2], en qualité de [Rôle 2], ci-après dénommé(e) « le [Rôle 2] », "
           "ont convenu, d'un commun accord, de formaliser les conditions d'exploitation de "
           "l'œuvre musicale intitulée [l'Œuvre], aux fins et dans les limites définies par "
           "le présent contrat. Les parties déclarent avoir pris connaissance de l'ensemble "
           "des dispositions ci-après et en accepter les termes sans réserve."
       ))
    _c(g, "Historique de collaboration", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez si une collaboration antérieure existe entre les parties.")

    # ── 1 — Définitions ───────────────────────────────────────────────────────
    g = _g("Définitions contractuelles", tooltip="Définissez les termes clés utilisés dans le contrat pour éviter toute ambiguïté.", sort_order=1)
    _c(g, "Glossaire des termes", "textarea", sort_order=0, enabled_by_default=False,
       tooltip_short="Définissez les termes clés : Œuvre, Master, Net Receipts, Streaming, DSP, Territoire, UGC...",
       tooltip_long="Les définitions contractuelles évitent les ambiguïtés d'interprétation. Chaque terme utilisé dans le contrat doit être défini précisément. Exemple : « Streaming : toute diffusion de l'Œuvre en flux continu via des plateformes numériques. »",
       example=(
           "Aux fins du présent contrat, les termes ci-après auront la signification suivante : "
           "« Œuvre » désigne la composition musicale intitulée « [titre] », dont les droits d'auteur appartiennent à l'Auteur ; "
           "« Exploitation » désigne tout acte de reproduction, de représentation, de distribution ou de mise à disposition "
           "au public de l'Œuvre ; "
           "« Net Receipts » désigne les sommes effectivement encaissées par l'Éditeur après déduction des remises accordées "
           "aux distributeurs et des taxes applicables ; "
           "« Streaming » désigne la mise à disposition à la demande de l'Œuvre sur les plateformes de musique dématérialisée."
       ))

    # ── 2 — Objet ─────────────────────────────────────────────────────────────
    g = _g("Objet du contrat", tooltip="Nature juridique du contrat et finalité de l'accord.", sort_order=2)
    _c(g, "Nature juridique", "select", sort_order=0, required=True,
       options=["Licence", "Cession", "Mandat", "Édition", "Distribution", "Coproduction", "Contrat d'artiste", "Synchronisation"],
       tooltip_short="Quelle est la nature juridique de cet accord ?",
       tooltip_long="La qualification juridique du contrat détermine les droits et obligations de chaque partie. Une licence permet l'exploitation sans transfert de propriété, une cession transfère définitivement les droits.",
       legal_ref="Art. L131-3 CPI")
    _c(g, "Finalité et description", "textarea", sort_order=1,
       tooltip_short="Décrivez précisément l'objet et les finalités commerciales du contrat.",
       example=(
           "Le présent contrat a pour objet de définir les conditions dans lesquelles "
           "[Contractant 1], en qualité de [Rôle 1], concède à [Contractant 2], en qualité "
           "de [Rôle 2], le droit d'exploiter l'œuvre musicale intitulée [l'Œuvre], dans les "
           "limites territoriales, pour la durée et selon les modalités précisées aux articles "
           "suivants. Cette exploitation s'inscrit dans le cadre du développement de la "
           "carrière artistique de [Contractant 1] et de la promotion de [l'Œuvre] sur "
           "l'ensemble des marchés couverts par le présent accord."
       ))

    # ── 3 — Désignation des œuvres ────────────────────────────────────────────
    g = _g("Désignation des œuvres", tooltip="Identification précise de l'œuvre musicale concernée.", sort_order=3)
    _c(g, "Titre de l'œuvre", "text", sort_order=0, required=True,
       tooltip_short="Titre exact de la composition musicale.",
       example="ex : « Nuit Électrique » — titre tel qu'il sera commercialisé")
    _c(g, "Description de l'œuvre", "textarea", sort_order=1,
       tooltip_short="Description artistique, genre, durée, caractéristiques de l'œuvre.",
       example=(
           "L'œuvre faisant l'objet du présent contrat est une composition musicale originale "
           "intitulée [l'Œuvre], créée en [année de création], d'une durée de [durée de l'œuvre], "
           "dont les droits d'auteur appartiennent à [Contractant 1]. Elle est identifiée par "
           "le code ISRC [ISRC] et livrée sous format WAV 24 bits / 44,1 kHz, accompagnée des "
           "stems multipistes, du visuel de pochette haute résolution et des métadonnées "
           "complètes conformes aux standards DDEX."
       ))
    _c(g, "Code ISWC", "text", sort_order=2, enabled_by_default=False,
       tooltip_short="Identifiant international de l'œuvre musicale (composition).",
       tooltip_long="L'ISWC (International Standard Musical Work Code, ISO 15707) identifie de manière unique une composition musicale. Obtenez-le auprès de la SACEM.",
       legal_ref="ISO 15707",
       example="ex : T-123.456.789-0 (à obtenir auprès de la SACEM après dépôt)")
    _c(g, "Code ISRC", "text", sort_order=3, enabled_by_default=False,
       tooltip_short="Identifiant international de l'enregistrement sonore.",
       tooltip_long="L'ISRC (International Standard Recording Code, ISO 3901) identifie l'enregistrement sonore, distinct de la composition. Obtenez-le via le SCPP ou l'IFPI.",
       legal_ref="ISO 3901",
       example="ex : FRZ012345678 (code à 12 caractères attribué par le producteur phonographique)")
    _c(g, "Code UPC/EAN", "text", sort_order=4, enabled_by_default=False,
       tooltip_short="Code barre produit pour la distribution physique et numérique.")
    _c(g, "Versions concernées", "multi_toggle", sort_order=5,
       options=["Version originale", "Remix", "Version instrumentale", "Version acoustique", "Stems / pistes séparées", "Autres versions"],
       tooltip_short="Quelles versions de l'œuvre sont incluses dans ce contrat ?")
    _c(g, "Fichiers et éléments livrés", "textarea", sort_order=6, enabled_by_default=False,
       tooltip_short="Listez les fichiers audio, partitions, stems concernés par le contrat.")

    # ── 4 — Nature des droits ─────────────────────────────────────────────────
    g = _g("Nature des droits concédés", tooltip="Droits d'exploitation accordés ou cédés par le présent contrat.", sort_order=4)
    _c(g, "Droit de reproduction", "toggle", sort_order=0,
       tooltip_short="Droit de fabriquer des copies physiques ou numériques.",
       tooltip_long="Le droit de reproduction couvre la fabrication de tout exemplaire de l'œuvre sur tout support.",
       legal_ref="Art. L122-3 CPI")
    _c(g, "Droit de représentation", "toggle", sort_order=1,
       tooltip_short="Droit de communiquer l'œuvre au public (concerts, diffusion, streaming).",
       legal_ref="Art. L122-2 CPI")
    _c(g, "Droit de distribution", "toggle", sort_order=2,
       tooltip_short="Droit de commercialiser l'œuvre (vente, location, prêt).")
    _c(g, "Mise à disposition / Streaming", "toggle", sort_order=3,
       tooltip_short="Droit de rendre l'œuvre accessible en ligne à la demande (streaming, téléchargement).",
       legal_ref="Art. L122-2-1 CPI")
    _c(g, "Droit d'adaptation / arrangement", "toggle", sort_order=4, enabled_by_default=False,
       tooltip_short="Droit de modifier, arranger, adapter ou remixer l'œuvre.",
       legal_ref="Art. L122-4 CPI")
    _c(g, "Exploitation dérivée — NFT, IA, Métavers", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="Droit d'exploiter l'œuvre dans les nouveaux environnements numériques (NFT, IA, Métavers).",
       tooltip_long="Ces droits émergents doivent être explicitement mentionnés car non couverts par les droits classiques. Précisez les conditions d'exploitation et les modalités de rémunération.")

    # ── 5 — Modalités d'exploitation ─────────────────────────────────────────
    g = _g("Modalités d'exploitation", tooltip="Supports et canaux d'exploitation autorisés.", sort_order=5)
    _c(g, "Supports autorisés", "multi_toggle", sort_order=0,
       options=["Vinyle", "CD", "Cassette", "Téléchargement numérique", "Streaming", "Réseaux sociaux",
                "Télévision / Radio", "Cinéma", "Jeux vidéo", "Applications mobiles", "Concerts virtuels / Live streaming"],
       tooltip_short="Sur quels supports l'œuvre peut-elle être exploitée ?")
    _c(g, "Précisions sur les modalités", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisions sur les conditions ou restrictions d'exploitation.")

    # ── 6 — Territoire ────────────────────────────────────────────────────────
    g = _g("Territoire", tooltip="Délimitation géographique de l'exploitation autorisée.", sort_order=6)
    _c(g, "Territoire d'exploitation", "territory", sort_order=0, required=True,
       options=["France", "Union européenne", "Monde entier", "Autre"],
       tooltip_short="Sur quel territoire l'œuvre peut-elle être exploitée ?",
       tooltip_long="Le territoire délimite géographiquement les droits. Une exploitation numérique (streaming mondial) peut dépasser la territorialité prévue : soyez précis.",
       legal_ref="Art. L131-3 CPI")
    _c(g, "Précisions territoriales", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez les pays inclus ou exclus, ou les règles en cas d'exploitation transfrontalière.")

    # ── 7 — Durée ─────────────────────────────────────────────────────────────
    g = _g("Durée", tooltip="Durée de validité du contrat et modalités de reconduction.", sort_order=7)
    _c(g, "Durée du contrat", "duration", sort_order=0, required=True,
       tooltip_short="Durée totale de validité du contrat.",
       tooltip_long="En droit français, les cessions de droits à durée indéterminée sont limitées à la durée légale de protection (70 ans post mortem). Précisez une durée fixe ou liée à la durée légale.",
       legal_ref="Art. L123-1 CPI")
    _c(g, "Date de prise d'effet", "date", sort_order=1, required=True,
       tooltip_short="Date à partir de laquelle le contrat prend effet.")
    _c(g, "Renouvellement tacite", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Le contrat se renouvelle-t-il automatiquement à échéance ?",
       tooltip_long="Précisez les conditions du renouvellement tacite : délai de préavis pour s'y opposer, durée de chaque reconduction.")
    _c(g, "Clause de sunset (non-exploitation)", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Clause permettant la réversion des droits en cas de non-exploitation.",
       tooltip_long="La clause de sunset prévoit que les droits retournent automatiquement au titulaire si l'exploitant cesse d'exploiter l'œuvre pendant une durée déterminée.",
       legal_ref="Art. L132-17 CPI",
       example=(
           "Si, à l'issue de la durée initiale du présent contrat, l'Éditeur n'a pas atteint un seuil cumulé de [X] streams "
           "ou [Y] ventes toutes plateformes confondues, l'Auteur sera en droit de résilier le présent contrat par lettre "
           "recommandée avec accusé de réception, avec effet immédiat et sans indemnité de part et d'autre."
       ))

    # ── 8 — Exclusivité ───────────────────────────────────────────────────────
    g = _g("Exclusivité", tooltip="Définit si le contrat est exclusif ou non-exclusif.", sort_order=8)
    _c(g, "Exclusivité totale", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="L'œuvre ne peut être exploitée par aucun autre cessionnaire.",
       tooltip_long="Un contrat exclusif confère à l'exploitant le droit d'être le seul à exploiter l'œuvre. Cette clause a une valeur commerciale élevée et doit être compensée en conséquence.",
       legal_ref="Art. L131-3 CPI",
       example=(
           "[Contractant 1] concède à [Contractant 2] une exclusivité totale sur l'ensemble "
           "des droits d'exploitation de [l'Œuvre] définis au présent contrat, pour tous les "
           "territoires couverts et pour toute la durée du présent accord. Pendant cette période, "
           "[Contractant 1] s'engage à ne pas concéder à un tiers le droit d'exploiter [l'Œuvre], "
           "directement ou indirectement, sous quelque forme que ce soit."
       ))
    _c(g, "Exclusivité partielle (périmètre)", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez si l'exclusivité est limitée à un territoire, un support ou une période.")
    _c(g, "Exceptions à l'exclusivité", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Side projects, pseudonymes, œuvres préexistantes exclus de la clause d'exclusivité.",
       example=(
           "Par dérogation à la clause d'exclusivité, l'Auteur se réserve expressément le droit d'exploiter ses œuvres "
           "antérieures au présent contrat, de se produire en concert et en tournée sous son nom d'artiste ou tout pseudonyme, "
           "et de participer à titre de collaborateur à des projets discographiques de tiers, à condition que ces projets ne "
           "constituent pas une concurrence directe avec les projets développés par l'Éditeur dans le cadre du présent accord."
       ))

    # ── 9 — Obligations de l'exploitant ──────────────────────────────────────
    g = _g("Obligations de l'exploitant", sort_order=9)
    _c(g, "Obligation de distribution", "toggle", sort_order=0,
       tooltip_short="L'exploitant est tenu de distribuer effectivement l'œuvre.")
    _c(g, "Minimum marketing", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="Budget ou actions marketing minimal à fournir par l'exploitant.",
       legal_ref="Art. L132-12 CPI",
       example=(
           "L'Éditeur s'engage à consacrer à la promotion de l'Œuvre un budget minimum de [montant] euros sur la période "
           "de [durée] suivant la date de sortie commerciale, incluant notamment les actions suivantes : campagnes de "
           "promotion sur les plateformes de streaming, relations presse et médias, présence en événements professionnels "
           "(Midem, Primavera Pro, etc.), et développement d'une stratégie éditoriale numérique cohérente."
       ))
    _c(g, "Calendrier de sortie", "date", sort_order=2, enabled_by_default=False,
       tooltip_short="Date prévue de sortie commerciale de l'œuvre.")
    _c(g, "Obligation de maintien de disponibilité", "toggle", sort_order=3, enabled_by_default=False,
       tooltip_short="L'exploitant doit maintenir l'œuvre disponible sur les plateformes.")
    _c(g, "Obligation d'exploitation de bonne foi", "toggle", sort_order=4, required=True,
       tooltip_short="L'exploitant s'engage à exploiter l'œuvre de manière sérieuse et loyale.",
       legal_ref="Art. L132-12 CPI")

    # ── 10 — Obligations de l'auteur/artiste ─────────────────────────────────
    g = _g("Obligations de l'auteur / artiste", sort_order=10)
    _c(g, "Livraison des masters dans les délais", "toggle", sort_order=0, required=True,
       tooltip_short="L'auteur s'engage à livrer les fichiers dans les formats et délais convenus.")
    _c(g, "Disponibilité promotionnelle", "toggle", sort_order=1, enabled_by_default=False,
       tooltip_short="L'artiste s'engage à participer aux actions promotionnelles.")
    _c(g, "Respect des délais contractuels", "toggle", sort_order=2,
       tooltip_short="L'auteur s'engage à respecter les délais prévus au contrat.")
    _c(g, "Absence de violation de droits tiers", "toggle", sort_order=3, required=True,
       tooltip_short="L'auteur garantit ne pas violer les droits de tiers (samples, interpolations...).")

    # ── 11 — Livraison des éléments techniques ────────────────────────────────
    g = _g("Livraison des éléments techniques", sort_order=11)
    _c(g, "Éléments à livrer", "multi_toggle", sort_order=0,
       options=["Fichier WAV (master final)", "Stems / pistes séparées", "Pochette haute résolution",
                "Métadonnées complètes", "Paroles (lyrics)", "Crédits complets", "Photos presse", "Vidéo clip"],
       tooltip_short="Quels fichiers et éléments doivent être livrés par l'auteur ?")
    _c(g, "Formats et normes techniques", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez les formats (WAV 24bit/48kHz, etc.), les normes de loudness (-14 LUFS), etc.")
    _c(g, "Délai de livraison", "duration", sort_order=2,
       tooltip_short="Délai accordé pour la livraison de l'ensemble des éléments.")

    # ── 12 — Avances ──────────────────────────────────────────────────────────
    g = _g("Avances", tooltip="Versements anticipés au titre du contrat.", sort_order=12)
    _c(g, "Type d'avance", "select", sort_order=0, enabled_by_default=False,
       options=["Avance recoupable", "Avance non recoupable", "Minimum garanti"],
       tooltip_short="Quel type d'avance est prévu ?",
       tooltip_long="Une avance recoupable est récupérée par l'exploitant sur les revenus futurs. Un minimum garanti est versé indépendamment des résultats.",
       legal_ref="Art. L132-6 CPI")
    _c(g, "Montant de l'avance (€)", "number", sort_order=1, enabled_by_default=False,
       tooltip_short="Montant de l'avance en euros.")
    _c(g, "Conditions de versement", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Calendrier et conditions de versement de l'avance.",
       example=(
           "L'avance prévue au présent article est consentie à titre de minimum garanti et sera recoupée sur les royalties "
           "dues à l'Auteur au titre de l'exploitation de l'Œuvre. Le recoupement s'effectuera uniquement sur les revenus "
           "générés par l'Œuvre faisant l'objet du présent contrat, à l'exclusion de tout autre titre du catalogue de "
           "l'Auteur. L'avance sera versée en deux tranches : 50 % à la signature du présent contrat, 50 % à la livraison "
           "des masters validés."
       ))

    # ── 13 — Royalties ────────────────────────────────────────────────────────
    g = _g("Royalties", tooltip="Rémunération proportionnelle aux exploitations.", sort_order=13)
    _c(g, "Mode de calcul", "select", sort_order=0,
       options=["Sur prix de vente brut", "Sur prix de vente net", "Sur net producteur", "Sur net distributeur"],
       tooltip_short="Sur quelle base les royalties sont-elles calculées ?",
       tooltip_long="La base de calcul des royalties est souvent source de litiges. « Net producteur » signifie après déduction de la part du distributeur. Soyez précis pour éviter les ambiguïtés.",
       legal_ref="Art. L131-4 CPI")
    _c(g, "Taux — exploitation physique (%)", "percentage", sort_order=1, enabled_by_default=False,
       tooltip_short="Pourcentage de royalties sur les ventes physiques (vinyle, CD).")
    _c(g, "Taux — streaming (%)", "percentage", sort_order=2,
       tooltip_short="Pourcentage de royalties sur les revenus de streaming.")
    _c(g, "Taux — synchronisation (%)", "percentage", sort_order=3, enabled_by_default=False,
       tooltip_short="Pourcentage de royalties sur les revenus de synchronisation.")
    _c(g, "Taux — YouTube / UGC (%)", "percentage", sort_order=4, enabled_by_default=False,
       tooltip_short="Pourcentage de royalties sur les revenus YouTube et contenus générés par les utilisateurs.")

    # ── 14 — Seuils et bonus ──────────────────────────────────────────────────
    g = _g("Seuils et bonus", sort_order=14)
    _c(g, "Bonus de performance", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="Bonus déclenché si l'œuvre dépasse un certain nombre de streams ou de ventes.",
       tooltip_long="Précisez le seuil (ex: 1 million de streams) et le montant du bonus correspondant.",
       example=(
           "L'Éditeur garantit à l'Auteur une rémunération minimale de [montant] euros par période de [durée], "
           "indépendamment des revenus effectivement générés par l'exploitation de l'Œuvre. Cette garantie constitue un "
           "plancher de rémunération et non un plafond ; les sommes supérieures au minimum garanti seront versées "
           "conformément aux modalités de calcul des royalties définies à l'article [X]."
       ))
    _c(g, "Paliers de rémunération", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Décrivez les paliers progressifs de rémunération selon les volumes d'exploitation.")

    # ── 15 — Recoupement ──────────────────────────────────────────────────────
    g = _g("Recoupement", tooltip="Mécanisme par lequel l'exploitant récupère ses avances sur les royalties.", sort_order=15)
    _c(g, "Recoupement prévu", "toggle", sort_order=0, enabled_by_default=False,
       tooltip_short="Les avances seront-elles recoupées sur les royalties ?",
       tooltip_long="Le recoupement est l'un des points les plus litigieux des contrats musicaux. L'exploitant récupère les avances versées sur les royalties avant de les reverser à l'auteur. Soyez précis sur le périmètre des dépenses recoupables.",
       legal_ref="Art. L132-6 CPI")
    _c(g, "Dépenses recoupables", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Listez les dépenses que l'exploitant peut récupérer sur les royalties (enregistrement, promotion, etc.).",
       example=(
           "Sont considérées comme dépenses recoupables au sens du présent contrat : les avances versées à l'Auteur, "
           "les frais d'enregistrement et de production phonographique, les frais de mixage et de mastering dans la limite "
           "de [montant] euros par titre, ainsi que les frais de fabrication des supports physiques. Ne sont pas recoupables : "
           "les dépenses de promotion et de marketing, les frais juridiques engagés par l'Éditeur, et les coûts de distribution."
       ))
    _c(g, "Ordre et plafonds de recoupement", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Dans quel ordre et jusqu'à quel plafond le recoupement s'applique-t-il ?")

    # ── 16 — Comptabilité et audit ────────────────────────────────────────────
    g = _g("Comptabilité et audit", tooltip="Obligations de transparence et droit de vérification des comptes.", sort_order=16)
    _c(g, "Fréquence des relevés de comptes", "select", sort_order=0,
       options=["Mensuel", "Trimestriel", "Semestriel", "Annuel"],
       tooltip_short="À quelle fréquence l'exploitant doit-il fournir des relevés de comptes ?",
       legal_ref="Art. L132-14 CPI")
    _c(g, "Conservation des données comptables (années)", "number", sort_order=1,
       tooltip_short="Durée pendant laquelle l'exploitant conserve les données comptables.",
       default_value={"number": 5})
    _c(g, "Droit d'audit", "toggle", sort_order=2,
       tooltip_short="Le titulaire des droits peut mandater un expert-comptable pour vérifier les comptes.",
       legal_ref="Art. L132-14 CPI")
    _c(g, "Procédure d'audit", "textarea", sort_order=3, enabled_by_default=False,
       tooltip_short="Délais, coûts et procédure pour l'exercice du droit d'audit.",
       example=(
           "[Contractant 1] ou son mandataire dûment habilité pourra, après notification écrite "
           "adressée à [Contractant 2] avec un préavis minimum de trente (30) jours, procéder à "
           "la vérification des livres de compte et documents comptables afférents à l'exploitation "
           "de [l'Œuvre]. Cet audit ne pourra être effectué qu'une seule fois par exercice "
           "comptable. Les frais d'audit seront à la charge de [Contractant 1], sauf si l'audit "
           "révèle un écart supérieur à 5 % en défaveur de [Contractant 1], auquel cas ils seront "
           "supportés par [Contractant 2]."
       ))

    # ── 17 — Garanties et PI ──────────────────────────────────────────────────
    g = _g("Garanties et propriété intellectuelle", sort_order=17)
    _c(g, "Garantie de titularité des droits", "toggle", sort_order=0, required=True,
       tooltip_short="L'auteur garantit être seul titulaire des droits sur l'œuvre.",
       legal_ref="Art. L131-3 CPI")
    _c(g, "Garantie d'originalité", "toggle", sort_order=1, required=True,
       tooltip_short="L'auteur garantit que l'œuvre est originale et ne contrefait pas d'œuvre préexistante.",
       legal_ref="Art. L112-1 CPI")
    _c(g, "Absence de sample non autorisé", "toggle", sort_order=2, required=True,
       tooltip_short="L'œuvre n'inclut aucun sample ou emprunt non autorisé par les ayants droit concernés.")
    _c(g, "Obtention des autorisations nécessaires", "toggle", sort_order=3,
       tooltip_short="Toutes les autorisations requises pour l'exploitation ont été obtenues.")

    # ── 18 — Responsabilité et indemnisation ──────────────────────────────────
    g = _g("Responsabilité et indemnisation", sort_order=18)
    _c(g, "Limitation de responsabilité", "toggle_with_details", sort_order=0,
       tooltip_short="Précisez les limites de responsabilité de chaque partie.",
       example=(
           "La responsabilité de chaque partie au titre du présent contrat est limitée aux dommages directs et prévisibles. "
           "En aucun cas, une partie ne pourra être tenue responsable des dommages indirects, pertes de profits ou manques "
           "à gagner, quand bien même elle aurait été informée de la possibilité de tels dommages. Cette limitation ne "
           "s'applique pas en cas de faute lourde ou dolosive."
       ))
    _c(g, "Prise en charge des litiges tiers", "toggle", sort_order=1,
       tooltip_short="Qui supporte les coûts en cas de litige avec un tiers (contrefaçon, sample non autorisé) ?")
    _c(g, "Assurance", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="L'une des parties est-elle tenue de souscrire une assurance spécifique ?")

    # ── 19 — Droits moraux ────────────────────────────────────────────────────
    g = _g("Droits moraux", tooltip="Droits inaliénables de l'auteur sur son œuvre (droit français).", sort_order=19)
    _c(g, "Droit au crédit (mention obligatoire)", "toggle", sort_order=0, required=True,
       tooltip_short="Le nom de l'auteur doit être mentionné sur toutes les exploitations.",
       tooltip_long="En droit français, le droit au crédit est un droit moral inaliénable et imprescriptible. L'auteur ne peut y renoncer de manière générale.",
       legal_ref="Art. L121-1 CPI")
    _c(g, "Validation artistique requise", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="L'auteur doit-il valider les adaptations ou modifications de l'œuvre ?",
       legal_ref="Art. L121-1 CPI")
    _c(g, "Autorisation d'adaptation", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="L'auteur autorise expressément les adaptations de l'œuvre dans le cadre de ce contrat.",
       legal_ref="Art. L122-4 CPI")

    # ── 20 — Synchronisation ──────────────────────────────────────────────────
    g = _g("Synchronisation et usages audiovisuels", sort_order=20)
    _c(g, "Publicité", "toggle", sort_order=0, enabled_by_default=False,
       tooltip_short="L'œuvre peut être utilisée dans des spots publicitaires.")
    _c(g, "Cinéma / Séries télévisées", "toggle", sort_order=1, enabled_by_default=False,
       tooltip_short="Utilisation de l'œuvre dans des films ou séries.")
    _c(g, "Jeux vidéo", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="Intégration de l'œuvre dans des jeux vidéo.")
    _c(g, "Plateformes sociales (Reels, Shorts, TikTok)", "toggle", sort_order=3, enabled_by_default=False,
       tooltip_short="Utilisation dans des contenus courts sur les réseaux sociaux.")
    _c(g, "Trailers / Bande-annonces", "toggle", sort_order=4, enabled_by_default=False,
       tooltip_short="Utilisation dans des bandes-annonces de films, séries ou jeux.")
    _c(g, "Podcasts", "toggle", sort_order=5, enabled_by_default=False,
       tooltip_short="Utilisation de l'œuvre en fond sonore ou générique de podcast.")
    _c(g, "Livestreams", "toggle", sort_order=6, enabled_by_default=False,
       tooltip_short="Diffusion de l'œuvre lors de streams en direct (Twitch, YouTube Live...).")
    _c(g, "Précisions synchro", "textarea", sort_order=7, enabled_by_default=False,
       tooltip_short="Conditions particulières pour les usages audiovisuels.")

    # ── 21 — Exploitation numérique ───────────────────────────────────────────
    g = _g("Exploitation numérique et plateformes", sort_order=21)
    _c(g, "Plateformes DSP (Spotify, Apple Music...)", "toggle", sort_order=0,
       tooltip_short="Distribution sur les plateformes de streaming digital.")
    _c(g, "YouTube Content ID", "toggle", sort_order=1,
       tooltip_short="Monétisation via le système Content ID de YouTube.")
    _c(g, "TikTok", "toggle", sort_order=2,
       tooltip_short="Utilisation de l'œuvre sur TikTok.")
    _c(g, "Meta (Instagram, Facebook Reels)", "toggle", sort_order=3,
       tooltip_short="Utilisation de l'œuvre sur les plateformes Meta.")
    _c(g, "Twitch", "toggle", sort_order=4, enabled_by_default=False,
       tooltip_short="Utilisation de l'œuvre lors de streams Twitch.")
    _c(g, "IA générative — entraînement / clonage / synthèse", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="Droit d'utiliser l'œuvre pour entraîner des modèles d'IA ou cloner une voix.",
       tooltip_long="Ces droits émergents sont de plus en plus sources de litiges. Précisez si l'œuvre peut servir à entraîner des modèles d'IA générative, cloner une voix ou synthétiser des éléments sonores.")
    _c(g, "NFT / Blockchain", "toggle_with_details", sort_order=6, enabled_by_default=False,
       tooltip_short="Droit de tokeniser l'œuvre ou des droits associés sous forme de NFT.")
    _c(g, "UGC / Remix utilisateurs", "toggle_with_details", sort_order=7, enabled_by_default=False,
       tooltip_short="Droit pour les utilisateurs de créer des contenus utilisant l'œuvre (UGC).")
    _c(g, "Avatars virtuels / Métavers", "toggle", sort_order=8, enabled_by_default=False,
       tooltip_short="Exploitation de l'œuvre dans des environnements virtuels et le métavers.")

    # ── 22 — Données et métadonnées ───────────────────────────────────────────
    g = _g("Données, métadonnées et collecte", sort_order=22)
    _c(g, "Gestion des identifiants (ISRC, ISWC, UPC)", "toggle", sort_order=0,
       tooltip_short="L'exploitant s'engage à renseigner correctement les identifiants de l'œuvre sur toutes les plateformes.")
    _c(g, "Reporting plateforme", "toggle", sort_order=1,
       tooltip_short="L'exploitant doit partager les rapports de streaming des plateformes.")
    _c(g, "Collecte SACEM / droits voisins", "toggle", sort_order=2,
       tooltip_short="Qui est responsable des démarches auprès de la SACEM et des organismes de gestion collective ?")
    _c(g, "Matching Content ID", "toggle", sort_order=3, enabled_by_default=False,
       tooltip_short="L'exploitant est responsable du matching Content ID sur YouTube.")

    # ── 23 — Confidentialité ──────────────────────────────────────────────────
    g = _g("Confidentialité", sort_order=23)
    _c(g, "Clause de confidentialité", "toggle", sort_order=0, required=True,
       tooltip_short="Les conditions financières et commerciales du contrat sont confidentielles.",
       tooltip_long="Les parties s'engagent à ne pas divulguer les conditions du contrat à des tiers. Cette clause survit généralement à la fin du contrat.")
    _c(g, "Durée de confidentialité post-résiliation (années)", "number", sort_order=1,
       tooltip_short="Durée pendant laquelle la clause de confidentialité s'applique après la fin du contrat.",
       default_value={"number": 3})
    _c(g, "Périmètre de la confidentialité", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Précisez ce qui est confidentiel : montants, stratégie, documents internes.",
       example=(
           "La présente obligation de confidentialité porte sur l'ensemble des informations échangées entre les parties "
           "dans le cadre du présent contrat, et notamment : les conditions financières (montant des avances, taux de "
           "royalties, seuils de déclenchement), les données d'écoute et de ventes, les stratégies de développement "
           "artistique et les projets en cours. Sont exclus du périmètre de confidentialité les informations tombées dans "
           "le domaine public et celles dont la divulgation serait imposée par une décision de justice ou une obligation légale."
       ))

    # ── 24 — Communication et image ───────────────────────────────────────────
    g = _g("Communication et image", sort_order=24)
    _c(g, "Droit d'utiliser le nom / image / voix", "toggle_with_details", sort_order=0,
       tooltip_short="L'exploitant peut utiliser le nom, l'image et la voix de l'artiste à des fins promotionnelles.",
       tooltip_long="Précisez les limites : durée, supports, zones géographiques, nature des contenus autorisés.")
    _c(g, "Biographie pour la presse", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="L'artiste fournit une biographie officielle à utiliser pour la communication.")
    _c(g, "Contenus réseaux sociaux", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="L'exploitant peut créer et publier des contenus promotionnels sur les réseaux sociaux.")

    # ── 25 — Force majeure ────────────────────────────────────────────────────
    g = _g("Force majeure", sort_order=25)
    _c(g, "Clause de force majeure (standard)", "toggle", sort_order=0, required=True,
       tooltip_short="Ni l'une ni l'autre des parties n'est responsable d'une inexécution due à la force majeure.",
       tooltip_long="La force majeure couvre les événements imprévisibles, irrésistibles et extérieurs aux parties : guerre, pandémie, catastrophe naturelle, cyberattaque, interruption des plateformes.",
       legal_ref="Art. 1218 Code civil")
    _c(g, "Événements couverts", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Listez les événements considérés comme cas de force majeure dans ce contrat.",
       example=(
           "Constituent des cas de force majeure au sens du présent contrat : les catastrophes naturelles, les épidémies "
           "déclarées par les autorités sanitaires compétentes, les guerres, les émeutes, les grèves générales affectant "
           "l'ensemble du secteur, les actes de terrorisme, les coupures massives d'électricité, les décisions "
           "gouvernementales ou réglementaires imprévues rendant impossible l'exécution des obligations contractuelles."
       ))
    _c(g, "Effets de la force majeure", "select", sort_order=2,
       options=["Suspension du contrat", "Report des obligations", "Résiliation possible"],
       tooltip_short="Quels sont les effets d'un cas de force majeure sur le contrat ?")

    # ── 26 — Résiliation ──────────────────────────────────────────────────────
    g = _g("Résiliation", tooltip="Causes et effets de la résiliation anticipée du contrat.", sort_order=26)
    _c(g, "Résiliation pour inexécution", "toggle", sort_order=0, required=True,
       tooltip_short="Le contrat peut être résilié en cas d'inexécution grave d'une obligation.",
       legal_ref="Art. 1224 Code civil")
    _c(g, "Résiliation pour non-paiement", "toggle", sort_order=1,
       tooltip_short="Non-paiement des redevances ou avances dans les délais contractuels.")
    _c(g, "Résiliation pour faillite / liquidation", "toggle", sort_order=2,
       tooltip_short="Le contrat peut être résilié en cas de faillite ou liquidation judiciaire de l'une des parties.")
    _c(g, "Résiliation pour absence d'exploitation", "toggle", sort_order=3, enabled_by_default=False,
       tooltip_short="Résiliation si l'exploitant cesse d'exploiter l'œuvre pendant une durée déterminée.",
       legal_ref="Art. L132-17 CPI")
    _c(g, "Résiliation pour atteinte à l'image", "toggle", sort_order=4, enabled_by_default=False,
       tooltip_short="Résiliation si l'une des parties cause un préjudice à l'image de l'autre.")
    _c(g, "Résiliation pour violation d'exclusivité", "toggle", sort_order=5, enabled_by_default=False,
       tooltip_short="Résiliation en cas de violation de la clause d'exclusivité.")
    _c(g, "Effets et délais de résiliation", "textarea", sort_order=6,
       tooltip_short="Précisez les effets de la résiliation : retrait des plateformes, maintien des créances, délai de préavis.",
       example=(
           "En cas de résiliation du présent contrat, pour quelque cause que ce soit, "
           "[Contractant 2] s'engage à retirer [l'Œuvre] de l'ensemble des plateformes de "
           "distribution dans un délai de trente (30) jours ouvrés à compter de la notification "
           "de résiliation. Les créances antérieures à la date de résiliation demeurent exigibles. "
           "[Contractant 1] conserve le droit de percevoir les royalties afférentes aux "
           "exploitations intervenues avant la date de résiliation effective."
       ))

    # ── 27 — Réversion des droits ─────────────────────────────────────────────
    g = _g("Réversion des droits", tooltip="Conditions dans lesquelles les droits retournent au titulaire.", sort_order=27)
    _c(g, "Retour automatique des droits", "toggle_with_details", sort_order=0,
       tooltip_short="Les droits reviennent automatiquement au titulaire à l'issue ou en cas de résiliation.",
       tooltip_long="La réversion des droits est une clause majeure dans les contrats d'artiste. Elle garantit à l'auteur de récupérer ses droits si l'exploitant n'assume plus ses obligations.",
       legal_ref="Art. L132-17 CPI",
       example=(
           "À l'issue du présent contrat ou en cas de résiliation anticipée pour quelque cause "
           "que ce soit, l'ensemble des droits concédés par [Contractant 1] seront automatiquement "
           "et de plein droit révertis à ce dernier, sans formalité ni indemnité. [Contractant 2] "
           "s'engage à prendre toutes les mesures nécessaires pour que ces droits soient "
           "effectivement libérés dans les meilleurs délais."
       ))
    _c(g, "Récupération des masters", "toggle", sort_order=1, enabled_by_default=False,
       tooltip_short="L'auteur récupère les fichiers masters à la fin du contrat.")
    _c(g, "Conditions de réversion", "textarea", sort_order=2,
       tooltip_short="Délais, procédures et conditions pour la mise en œuvre de la réversion.",
       example=(
           "Les droits concédés par [Contractant 1] seront automatiquement révertis dans les "
           "cas suivants : (i) si [Contractant 2] n'a pas procédé à la première exploitation "
           "commerciale de [l'Œuvre] avant le [début d'exploitation] convenu ou dans les "
           "dix-huit (18) mois suivant la livraison des masters définitifs ; (ii) si [l'Œuvre] "
           "cesse d'être disponible à l'écoute sur les principales plateformes de streaming "
           "(Spotify, Apple Music, Deezer) pendant une période continue de douze (12) mois ; "
           "(iii) en cas de liquidation judiciaire de [Contractant 2] ; (iv) à l'échéance "
           "du [fin d'exploitation] si aucun renouvellement n'a été signé."
       ))

    # ── 28 — Cession et sous-licence ─────────────────────────────────────────
    g = _g("Cession du contrat et sous-licence", sort_order=28)
    _c(g, "Cession du contrat autorisée", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="L'exploitant peut-il transférer ses droits à un tiers (ex: vente de catalogue) ?",
       tooltip_long="La cession du contrat permet à l'exploitant de transférer l'ensemble de ses droits à un tiers. Limitez ou encadrez cette possibilité pour préserver vos intérêts.")
    _c(g, "Sous-licence autorisée", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="L'exploitant peut-il accorder des sous-licences à des tiers ?")
    _c(g, "Vente de catalogue autorisée", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Le catalogue peut-il être vendu à un tiers sans accord préalable de l'auteur ?")

    # ── 29 — Droit applicable et juridiction ──────────────────────────────────
    g = _g("Droit applicable et juridiction compétente", sort_order=29)
    _c(g, "Droit applicable", "select", sort_order=0, required=True,
       options=["Droit français", "Droit belge", "Droit suisse", "Autre"],
       tooltip_short="Quelle loi nationale régit ce contrat ?",
       default_value={"selected": "Droit français"})
    _c(g, "Tribunaux compétents", "text", sort_order=1, required=True,
       tooltip_short="Tribunal compétent en cas de litige.",
       default_value={"text": "Tribunaux de Paris"},
       example="ex : Tribunal judiciaire de Paris — Chambre commerciale")
    _c(g, "Médiation préalable obligatoire", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="Les parties s'engagent à recourir à la médiation avant toute action judiciaire.")
    _c(g, "Clause d'arbitrage", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Les litiges sont soumis à arbitrage plutôt qu'aux tribunaux ordinaires.",
       tooltip_long="L'arbitrage offre un cadre confidentiel et souvent plus rapide que la voie judiciaire, mais peut être plus coûteux.")

    # ── 30 — Notifications ────────────────────────────────────────────────────
    g = _g("Notifications", sort_order=30)
    _c(g, "Email contractuel du cessionnaire", "text", sort_order=0,
       tooltip_short="Adresse email officielle pour toutes les notifications contractuelles.")
    _c(g, "Modalités de notification", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez les modalités : email recommandé, lettre recommandée AR, délai de prise en compte.")

    # ── 31 — Clauses générales ────────────────────────────────────────────────
    g = _g("Clauses générales", tooltip="Dispositions standard présentes dans tout contrat professionnel.", sort_order=31)
    _c(g, "Divisibilité des clauses", "toggle", sort_order=0, required=True,
       tooltip_short="Si une clause est nulle, les autres restent valides.",
       legal_ref="Art. 1184 Code civil")
    _c(g, "Intégralité du contrat", "toggle", sort_order=1, required=True,
       tooltip_short="Ce contrat constitue l'intégralité de l'accord entre les parties et annule tout accord antérieur.")
    _c(g, "Modification écrite obligatoire", "toggle", sort_order=2, required=True,
       tooltip_short="Toute modification du contrat doit faire l'objet d'un avenant écrit signé des deux parties.")
    _c(g, "Clause de non-renonciation", "toggle", sort_order=3,
       tooltip_short="Le fait de ne pas exercer un droit ne vaut pas renonciation à ce droit.")
    _c(g, "Survie des clauses", "toggle", sort_order=4,
       tooltip_short="Certaines clauses survivent à la résiliation du contrat (confidentialité, garanties).")
    _c(g, "Ordre de priorité des annexes", "textarea", sort_order=5, enabled_by_default=False,
       tooltip_short="Précisez l'ordre de priorité en cas de contradiction entre le corps du contrat et ses annexes.",
       example=(
           "En cas de contradiction entre le corps du présent contrat et ses annexes, les stipulations du corps du contrat "
           "prévaudront. Entre les différentes annexes, la priorité sera donnée à l'annexe portant la date la plus récente. "
           "Les parties s'engagent à annexer au présent contrat, dans les trente (30) jours suivant sa signature, le ou les "
           "splits sheets définissant la répartition des droits d'auteur entre co-auteurs."
       ))

    # ── 32 — Annexes ─────────────────────────────────────────────────────────
    g = _g("Annexes", tooltip="Documents annexés et faisant partie intégrante du contrat.", sort_order=32)
    _c(g, "Liste des annexes", "textarea", sort_order=0, enabled_by_default=False,
       tooltip_short="Listez toutes les annexes : splits sheets, budgets, calendriers marketing, barèmes de royalties, politiques IA, templates de reporting...")

    # ── 33 — Clauses IA ───────────────────────────────────────────────────────
    g = _g("Intelligence artificielle — clauses spécifiques", tooltip="Clauses relatives à l'utilisation de l'IA avec l'œuvre.", sort_order=33)
    _c(g, "Entraînement de modèles d'IA", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="L'œuvre peut-elle être utilisée pour entraîner des modèles d'intelligence artificielle ?",
       tooltip_long="Cette clause est de plus en plus demandée par les exploitants numériques. Elle doit être limitée dans son périmètre et compensée financièrement si accordée.")
    _c(g, "Clonage vocal", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="La voix ou les éléments sonores de l'œuvre peuvent-ils être clonés par IA ?",
       tooltip_long="Le clonage vocal par IA est un sujet juridiquement très sensible. En France, le droit à l'image vocale est protégé. Toute utilisation doit être explicitement autorisée et rémunérée.")
    _c(g, "Synthèse de voix / d'éléments musicaux", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Création de nouveaux éléments sonores par IA à partir de l'œuvre.")
    _c(g, "Exploitation algorithmique", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Utilisation de l'œuvre dans des playlists ou recommandations algorithmiques.")
    _c(g, "Politique de compensation IA", "textarea", sort_order=4, enabled_by_default=False,
       tooltip_short="Décrivez la politique de rémunération pour tous les usages liés à l'IA.",
       example=(
           "En contrepartie de l'autorisation accordée à l'Éditeur d'utiliser l'Œuvre à des fins d'entraînement de modèles "
           "d'intelligence artificielle, les parties conviennent d'une compensation forfaitaire de [montant] euros par modèle "
           "entraîné, versée à l'Auteur dans les trente (30) jours suivant chaque utilisation identifiée. L'Éditeur s'engage "
           "à tenir un registre des utilisations de l'Œuvre à des fins d'entraînement IA et à le communiquer à l'Auteur sur demande."
       ))

    db.session.commit()


# Map clause name → example text for the update command.
# Kept in sync with the examples defined in run_seed() above.
_EXAMPLES: dict[str, str] = {
    "Contexte et volonté des parties": (
        "[Contractant 1], en qualité de [Rôle 1], ci-après dénommé(e) « le [Rôle 1] », "
        "et [Contractant 2], en qualité de [Rôle 2], ci-après dénommé(e) « le [Rôle 2] », "
        "ont convenu, d'un commun accord, de formaliser les conditions d'exploitation de "
        "l'œuvre musicale intitulée [l'Œuvre], aux fins et dans les limites définies par "
        "le présent contrat. Les parties déclarent avoir pris connaissance de l'ensemble "
        "des dispositions ci-après et en accepter les termes sans réserve."
    ),
    "Glossaire des termes": (
        "Aux fins du présent contrat, les termes ci-après auront la signification suivante : "
        "« Œuvre » désigne la composition musicale intitulée « [titre] », dont les droits d'auteur appartiennent à l'Auteur ; "
        "« Exploitation » désigne tout acte de reproduction, de représentation, de distribution ou de mise à disposition "
        "au public de l'Œuvre ; "
        "« Net Receipts » désigne les sommes effectivement encaissées par l'Éditeur après déduction des remises accordées "
        "aux distributeurs et des taxes applicables ; "
        "« Streaming » désigne la mise à disposition à la demande de l'Œuvre sur les plateformes de musique dématérialisée."
    ),
    "Finalité et description": (
        "Le présent contrat a pour objet de définir les conditions dans lesquelles "
        "[Contractant 1], en qualité de [Rôle 1], concède à [Contractant 2], en qualité "
        "de [Rôle 2], le droit d'exploiter l'œuvre musicale intitulée [l'Œuvre], du "
        "[début d'exploitation] au [fin d'exploitation], dans les limites territoriales et "
        "selon les modalités précisées aux articles suivants. Cette exploitation s'inscrit "
        "dans le cadre du développement de la carrière artistique de [Contractant 1] et "
        "de la promotion de [l'Œuvre] sur l'ensemble des marchés couverts par le présent accord."
    ),
    "Titre de l'œuvre": "ex : « Nuit Électrique » — titre tel qu'il sera commercialisé",
    "Description de l'œuvre": (
        "L'œuvre faisant l'objet du présent contrat est une composition musicale originale "
        "intitulée [l'Œuvre], créée en [année de création], d'une durée de [durée de l'œuvre], "
        "dont les droits d'auteur appartiennent à [Contractant 1]. Elle est identifiée par "
        "le code ISRC [ISRC] et livrée sous format WAV 24 bits / 44,1 kHz, accompagnée des "
        "stems multipistes, du visuel de pochette haute résolution et des métadonnées "
        "complètes conformes aux standards DDEX."
    ),
    "Code ISWC": "ex : T-123.456.789-0 (à obtenir auprès de la SACEM après dépôt)",
    "Code ISRC": "ex : FRZ012345678 (code à 12 caractères attribué par le producteur phonographique)",
    "Exclusivité totale": (
        "[Contractant 1] concède à [Contractant 2] une exclusivité totale sur l'ensemble "
        "des droits d'exploitation de [l'Œuvre] définis au présent contrat, pour tous les "
        "territoires couverts et pour toute la durée du présent accord. Pendant cette période, "
        "[Contractant 1] s'engage à ne pas concéder à un tiers le droit d'exploiter [l'Œuvre], "
        "directement ou indirectement, sous quelque forme que ce soit."
    ),
    "Exceptions à l'exclusivité": (
        "Par dérogation à la clause d'exclusivité, l'Auteur se réserve expressément le droit d'exploiter ses œuvres "
        "antérieures au présent contrat, de se produire en concert et en tournée sous son nom d'artiste ou tout pseudonyme, "
        "et de participer à titre de collaborateur à des projets discographiques de tiers, à condition que ces projets ne "
        "constituent pas une concurrence directe avec les projets développés par l'Éditeur dans le cadre du présent accord."
    ),
    "Minimum marketing": (
        "L'Éditeur s'engage à consacrer à la promotion de l'Œuvre un budget minimum de [montant] euros sur la période "
        "de [durée] suivant la date de sortie commerciale, incluant notamment les actions suivantes : campagnes de "
        "promotion sur les plateformes de streaming, relations presse et médias, présence en événements professionnels "
        "(Midem, Primavera Pro, etc.), et développement d'une stratégie éditoriale numérique cohérente."
    ),
    "Conditions de versement": (
        "L'avance prévue au présent article est consentie à titre de minimum garanti et sera recoupée sur les royalties "
        "dues à l'Auteur au titre de l'exploitation de l'Œuvre. Le recoupement s'effectuera uniquement sur les revenus "
        "générés par l'Œuvre faisant l'objet du présent contrat, à l'exclusion de tout autre titre du catalogue de "
        "l'Auteur. L'avance sera versée en deux tranches : 50 % à la signature du présent contrat, 50 % à la livraison "
        "des masters validés."
    ),
    "Clause de sunset (non-exploitation)": (
        "Si, à l'issue de la durée initiale du présent contrat, l'Éditeur n'a pas atteint un seuil cumulé de [X] streams "
        "ou [Y] ventes toutes plateformes confondues, l'Auteur sera en droit de résilier le présent contrat par lettre "
        "recommandée avec accusé de réception, avec effet immédiat et sans indemnité de part et d'autre."
    ),
    "Dépenses recoupables": (
        "Sont considérées comme dépenses recoupables au sens du présent contrat : les avances versées à l'Auteur, "
        "les frais d'enregistrement et de production phonographique, les frais de mixage et de mastering dans la limite "
        "de [montant] euros par titre, ainsi que les frais de fabrication des supports physiques. Ne sont pas recoupables : "
        "les dépenses de promotion et de marketing, les frais juridiques engagés par l'Éditeur, et les coûts de distribution."
    ),
    "Procédure d'audit": (
        "[Contractant 1] ou son mandataire dûment habilité pourra, après notification écrite "
        "adressée à [Contractant 2] avec un préavis minimum de trente (30) jours, procéder à "
        "la vérification des livres de compte et documents comptables afférents à l'exploitation "
        "de [l'Œuvre]. Cet audit ne pourra être effectué qu'une seule fois par exercice "
        "comptable. Les frais d'audit seront à la charge de [Contractant 1], sauf si l'audit "
        "révèle un écart supérieur à 5 % en défaveur de [Contractant 1], auquel cas ils seront "
        "supportés par [Contractant 2]."
    ),
    "Limitation de responsabilité": (
        "La responsabilité de chaque partie au titre du présent contrat est limitée aux dommages directs et prévisibles. "
        "En aucun cas, une partie ne pourra être tenue responsable des dommages indirects, pertes de profits ou manques "
        "à gagner, quand bien même elle aurait été informée de la possibilité de tels dommages. Cette limitation ne "
        "s'applique pas en cas de faute lourde ou dolosive."
    ),
    "Périmètre de la confidentialité": (
        "La présente obligation de confidentialité porte sur l'ensemble des informations échangées entre les parties "
        "dans le cadre du présent contrat, et notamment : les conditions financières (montant des avances, taux de "
        "royalties, seuils de déclenchement), les données d'écoute et de ventes, les stratégies de développement "
        "artistique et les projets en cours. Sont exclus du périmètre de confidentialité les informations tombées dans "
        "le domaine public et celles dont la divulgation serait imposée par une décision de justice ou une obligation légale."
    ),
    "Événements couverts": (
        "Constituent des cas de force majeure au sens du présent contrat : les catastrophes naturelles, les épidémies "
        "déclarées par les autorités sanitaires compétentes, les guerres, les émeutes, les grèves générales affectant "
        "l'ensemble du secteur, les actes de terrorisme, les coupures massives d'électricité, les décisions "
        "gouvernementales ou réglementaires imprévues rendant impossible l'exécution des obligations contractuelles."
    ),
    "Effets et délais de résiliation": (
        "En cas de résiliation du présent contrat, pour quelque cause que ce soit, "
        "[Contractant 2] s'engage à retirer [l'Œuvre] de l'ensemble des plateformes de "
        "distribution dans un délai de trente (30) jours ouvrés à compter de la notification "
        "de résiliation. Les créances antérieures à la date de résiliation demeurent exigibles. "
        "[Contractant 1] conserve le droit de percevoir les royalties afférentes aux "
        "exploitations intervenues avant la date de résiliation effective."
    ),
    "Retour automatique des droits": (
        "À l'issue du présent contrat ou en cas de résiliation anticipée pour quelque cause "
        "que ce soit, l'ensemble des droits concédés par [Contractant 1] seront automatiquement "
        "et de plein droit révertis à ce dernier, sans formalité ni indemnité. [Contractant 2] "
        "s'engage à prendre toutes les mesures nécessaires pour que ces droits soient "
        "effectivement libérés dans les meilleurs délais."
    ),
    "Conditions de réversion": (
        "Les droits concédés par [Contractant 1] seront automatiquement révertis dans les "
        "cas suivants : (i) si [Contractant 2] n'a pas procédé à la première exploitation "
        "commerciale de [l'Œuvre] avant le [début d'exploitation] convenu ou dans les "
        "dix-huit (18) mois suivant la livraison des masters définitifs ; (ii) si [l'Œuvre] "
        "cesse d'être disponible à l'écoute sur les principales plateformes de streaming "
        "(Spotify, Apple Music, Deezer) pendant une période continue de douze (12) mois ; "
        "(iii) en cas de liquidation judiciaire de [Contractant 2] ; (iv) à l'échéance "
        "du [fin d'exploitation] si aucun renouvellement n'a été signé."
    ),
    "Ordre de priorité des annexes": (
        "En cas de contradiction entre le corps du présent contrat et ses annexes, les stipulations du corps du contrat "
        "prévaudront. Entre les différentes annexes, la priorité sera donnée à l'annexe portant la date la plus récente. "
        "Les parties s'engagent à annexer au présent contrat, dans les trente (30) jours suivant sa signature, le ou les "
        "splits sheets définissant la répartition des droits d'auteur entre co-auteurs."
    ),
    "Tribunaux compétents": "ex : Tribunal judiciaire de Paris — Chambre commerciale",
    "Bonus de performance": (
        "L'Éditeur garantit à l'Auteur une rémunération minimale de [montant] euros par période de [durée], "
        "indépendamment des revenus effectivement générés par l'exploitation de l'Œuvre. Cette garantie constitue un "
        "plancher de rémunération et non un plafond ; les sommes supérieures au minimum garanti seront versées "
        "conformément aux modalités de calcul des royalties définies à l'article [X]."
    ),
    "Politique de compensation IA": (
        "En contrepartie de l'autorisation accordée à l'Éditeur d'utiliser l'Œuvre à des fins d'entraînement de modèles "
        "d'intelligence artificielle, les parties conviennent d'une compensation forfaitaire de [montant] euros par modèle "
        "entraîné, versée à l'Auteur dans les trente (30) jours suivant chaque utilisation identifiée. L'Éditeur s'engage "
        "à tenir un registre des utilisations de l'Œuvre à des fins d'entraînement IA et à le communiquer à l'Auteur sur demande."
    ),
    # ── Nouveaux exemples ──────────────────────────────────────────────────────
    "Historique de collaboration": (
        "L'Auteur et l'Éditeur collaborent depuis [date] dans le cadre de [description de la collaboration précédente]. "
        "Fort de cette relation de confiance, les parties ont décidé de formaliser leurs engagements par le présent contrat, "
        "qui s'inscrit dans la continuité des échanges artistiques et commerciaux noués entre elles. Le présent accord "
        "annule et remplace tout accord verbal ou écrit antérieur portant sur l'Œuvre désignée à l'article [X]."
    ),
    "Exclusivité partielle (périmètre)": (
        "L'exclusivité accordée à l'Éditeur est limitée aux supports numériques suivants : plateformes de streaming audio "
        "(Spotify, Apple Music, Deezer, Tidal et équivalents), plateformes de téléchargement (iTunes, Amazon Music) et "
        "réseaux sociaux. Sont expressément exclus de l'exclusivité : l'exploitation physique (vinyle, CD), la "
        "synchronisation audiovisuelle, l'exploitation dans des jeux vidéo et tout usage dans des environnements de "
        "réalité virtuelle ou métavers. Sur ces supports exclus, l'Auteur demeure libre de contracter avec tout tiers "
        "de son choix."
    ),
    "Précisions territoriales": (
        "Sont inclus dans le territoire d'exploitation : l'ensemble des pays membres de l'Union européenne, la Suisse, "
        "le Royaume-Uni, le Canada, les États-Unis, le Japon, l'Australie et la Nouvelle-Zélande. Sont expressément "
        "exclus : les marchés d'Afrique subsaharienne, couverts par un accord distinct en cours de négociation. "
        "En cas de mise à disposition numérique transfrontalière involontaire résultant d'un défaut de géoblocage, "
        "l'Éditeur en informera l'Auteur dans les quarante-huit (48) heures et prendra les mesures correctrices "
        "nécessaires dans les meilleurs délais, sans que cela engage sa responsabilité contractuelle."
    ),
    "Précisions sur les modalités": (
        "L'Éditeur s'engage à distribuer l'Œuvre sur l'ensemble des plateformes de streaming majeures disponibles "
        "sur le territoire concerné dans un délai de [X] jours ouvrés à compter de la livraison des éléments techniques "
        "validés. En cas d'indisponibilité technique provisoire sur l'une des plateformes, l'Éditeur en informera "
        "l'Auteur dans les quarante-huit (48) heures et prendra les mesures nécessaires pour rétablir la disponibilité "
        "dans les meilleurs délais. L'Éditeur s'interdit de retirer l'Œuvre d'une plateforme sans en informer "
        "préalablement l'Auteur au moins quinze (15) jours à l'avance, sauf contrainte technique ou légale impérative."
    ),
    "Formats et normes techniques": (
        "Les fichiers audio seront livrés en format WAV non compressé, 24 bits / 44,1 kHz pour le master stéréo "
        "final destiné à la distribution, et en WAV 24 bits / 48 kHz pour les stems multipistes destinés à la "
        "synchronisation audiovisuelle. Le niveau de loudness devra être conforme aux recommandations des plateformes "
        "de streaming (–14 LUFS intégrés, true peak ≤ –1 dBTP). La pochette sera fournie en format PNG ou TIFF, "
        "en résolution minimale 3 000 × 3 000 pixels, mode couleur RVB, sans texte superposé sur les bords. "
        "Les métadonnées ID3 (titre, artiste, ISRC, année, genre) devront être complétées avant la livraison."
    ),
    "Paliers de rémunération": (
        "Les parties conviennent des paliers de rémunération progressive suivants, calculés sur une période glissante "
        "de douze (12) mois à compter de la date de mise en ligne commerciale de l'Œuvre : "
        "(i) de 0 à 1 000 000 de streams cumulés toutes plateformes confondues : taux standard de [X] % "
        "tel que défini à l'article Royalties ; "
        "(ii) de 1 000 001 à 5 000 000 de streams : taux majoré de [X + 2] % ; "
        "(iii) au-delà de 5 000 000 de streams : taux premium de [X + 5] %. "
        "Ces paliers sont calculés séparément pour chaque période de douze mois et ne se cumulent pas d'une "
        "période à l'autre. L'Éditeur communiquera à l'Auteur les données de streams dans son relevé trimestriel."
    ),
    "Ordre et plafonds de recoupement": (
        "Le recoupement s'opérera dans l'ordre de priorité suivant, les créances de rang supérieur devant être "
        "intégralement recoupées avant de passer au rang suivant : (i) en premier lieu, l'avance versée à la signature "
        "du présent contrat ; (ii) en deuxième lieu, les frais d'enregistrement et de production phonographique ; "
        "(iii) en troisième lieu, les frais de mastering. Le recoupement global est plafonné à [montant] euros par "
        "titre. Au-delà de ce plafond, toute royaltie due est versée à l'Auteur sans condition de recoupement "
        "préalable. L'Auteur pourra demander à tout moment un état de recoupement actualisé dans le cadre de la "
        "procédure d'audit définie à l'article Comptabilité et audit."
    ),
    "Assurance": (
        "L'Éditeur s'engage à souscrire et à maintenir, pendant toute la durée du présent contrat, une assurance "
        "responsabilité civile professionnelle couvrant notamment les risques de contrefaçon involontaire et les "
        "litiges relatifs aux droits de propriété intellectuelle, pour un montant minimum de [montant] euros par "
        "sinistre. L'Auteur s'engage à souscrire une assurance couvrant les risques liés à l'exécution de ses "
        "obligations contractuelles, notamment la garantie de titularité des droits. Chaque partie s'engage à "
        "communiquer à l'autre, sur simple demande écrite, les attestations d'assurance en cours de validité dans "
        "un délai de cinq (5) jours ouvrés."
    ),
    "Validation artistique requise": (
        "Toute adaptation, modification substantielle, synchronisation ou remix de l'Œuvre devra faire l'objet d'une "
        "demande écrite préalable adressée à l'Auteur, qui disposera d'un délai de quinze (15) jours ouvrés pour y "
        "répondre. L'absence de réponse à l'issue de ce délai ne vaut pas acceptation tacite et ne peut être "
        "interprétée comme un accord implicite. Tout refus de validation devra être motivé par écrit et ne pourra "
        "être exercé de manière abusive ou dilatoire. En cas de désaccord persistant, les parties s'engagent à "
        "recourir à la procédure de médiation prévue à l'article Droit applicable et juridiction compétente."
    ),
    "Précisions synchro": (
        "Les droits de synchronisation accordés par le présent contrat couvrent exclusivement les œuvres audiovisuelles "
        "dont la durée totale d'utilisation de l'Œuvre n'excède pas quatre-vingt-dix (90) secondes par production. "
        "Pour toute synchronisation dans une production dont le budget total de production dépasse [montant] euros, "
        "une autorisation préalable écrite de l'Auteur sera requise, dans un délai de réponse de dix (10) jours "
        "ouvrés. La rémunération de synchronisation sera négociée au cas par cas entre les parties, avec un plancher "
        "minimum de [montant] euros par utilisation, nonobstant toute autre rémunération prévue au contrat."
    ),
    "IA générative — entraînement / clonage / synthèse": (
        "L'exploitation de l'Œuvre à des fins d'entraînement de modèles d'intelligence artificielle, de clonage de "
        "voix ou de synthèse d'éléments musicaux est [autorisée / expressément interdite] dans les conditions "
        "suivantes : (i) usage strictement limité aux modèles internes développés ou opérés directement par l'Éditeur, "
        "à l'exclusion de toute mise à disposition à des tiers ; (ii) notification écrite à l'Auteur au moins "
        "trente (30) jours avant le début de tout cycle d'entraînement ; (iii) versement d'une compensation "
        "forfaitaire telle que définie à l'article Intelligence artificielle — clauses spécifiques du présent contrat ; "
        "(iv) droit pour l'Auteur d'exiger la suppression de ses données d'entraînement dans un délai de trente (30) "
        "jours sur simple demande écrite."
    ),
    "NFT / Blockchain": (
        "L'Éditeur est autorisé à tokeniser l'Œuvre ou certains droits associés sous forme de jetons non fongibles "
        "(NFT) sur les blockchains [Ethereum / Polygon / Tezos — à préciser] dans les conditions suivantes : "
        "(i) quantité maximale de [X] NFT émis par collection sans accord complémentaire ; "
        "(ii) l'Auteur percevra une redevance de [Y] % sur le prix de chaque transaction secondaire (revente) "
        "des NFT, versée via un smart contract avec partage automatique des revenus (royalty split) ; "
        "(iii) les NFT ne confèrent à leurs acquéreurs aucun droit de propriété intellectuelle sur l'Œuvre "
        "au-delà de ce qui est expressément stipulé dans les métadonnées du token et dans les conditions "
        "générales associées à la collection."
    ),
    "UGC / Remix utilisateurs": (
        "L'Éditeur est autorisé à permettre aux utilisateurs finaux de créer des contenus dérivés (UGC — User "
        "Generated Content) à partir de l'Œuvre dans le cadre des plateformes sociales (TikTok, Instagram Reels, "
        "YouTube Shorts, et équivalents), sous réserve des conditions cumulatives suivantes : "
        "(i) usage exclusivement non-commercial, à l'exclusion de toute monétisation directe par l'utilisateur ; "
        "(ii) mention obligatoire du nom d'artiste de l'Auteur sur tout contenu dérivé publié ; "
        "(iii) les revenus de monétisation générés par l'Éditeur sur ces contenus UGC via Content ID ou "
        "équivalent sont partagés selon les modalités prévues à l'article Royalties du présent contrat."
    ),
    "Droit d'utiliser le nom / image / voix": (
        "L'Auteur autorise l'Éditeur à utiliser son nom d'artiste, son image (photographies, illustrations) et sa "
        "voix à des fins exclusives de promotion et de communication commerciale en lien direct avec l'exploitation "
        "de l'Œuvre faisant l'objet du présent contrat. Cette autorisation est strictement limitée : à la durée du "
        "présent contrat ; aux territoires couverts par l'accord ; et aux supports suivants : presse professionnelle "
        "spécialisée, sites web officiels des parties, réseaux sociaux professionnels, et supports physiques liés "
        "à la commercialisation de l'Œuvre (pochette, affiche de tournée). Toute utilisation dans un contexte "
        "publicitaire pour une marque ou un produit tiers nécessitera l'accord préalable écrit de l'Auteur."
    ),
    "Biographie pour la presse": (
        "L'Auteur s'engage à fournir à l'Éditeur, dans les trente (30) jours suivant la signature du présent "
        "contrat, une biographie officielle à jour en langue française et en langue anglaise, d'une longueur "
        "maximale de cinq cents (500) mots chacune, accompagnée d'un minimum de cinq (5) photographies de presse "
        "haute résolution (format TIFF ou JPEG, résolution minimale 300 dpi, poids supérieur à 5 Mo par fichier). "
        "L'Éditeur s'engage à n'utiliser ces éléments qu'après validation préalable de l'Auteur sous quarante-huit "
        "(48) heures, et à procéder à la mise à jour des supports de communication dans les quinze (15) jours "
        "suivant la communication d'une version révisée par l'Auteur."
    ),
    "Cession du contrat autorisée": (
        "L'Éditeur pourra céder le présent contrat et l'ensemble des droits et obligations qui en découlent à tout "
        "tiers, sous réserve d'en informer l'Auteur par lettre recommandée avec accusé de réception au moins "
        "trente (30) jours avant la date effective de la cession. Dans le cas où le cessionnaire ne présenterait "
        "pas des garanties financières et artistiques équivalentes à celles de l'Éditeur initial — appréciées "
        "notamment au regard de son expérience dans le secteur musical et de sa solidité financière — l'Auteur "
        "disposera d'un droit de résiliation du présent contrat par lettre recommandée, exercé dans les trente "
        "(30) jours suivant la notification, sans indemnité de part et d'autre."
    ),
    "Sous-licence autorisée": (
        "L'Éditeur est autorisé à concéder des sous-licences à des tiers distributeurs, sous-distributeurs ou "
        "partenaires commerciaux dans le cadre de l'exploitation normale et habituelle de l'Œuvre, sous réserve "
        "que : (i) les sous-licences ne confèrent pas de droits supérieurs ou d'une durée excédant ceux accordés "
        "par le présent contrat ; (ii) l'Éditeur demeure solidairement responsable, à l'égard de l'Auteur, du "
        "respect par ses sous-licenciés de l'ensemble des obligations du présent contrat ; (iii) l'Auteur est "
        "informé de toute sous-licence dans les quinze (15) jours suivant sa conclusion, par notification "
        "mentionnant l'identité du sous-licencié et le périmètre des droits concédés."
    ),
    "Vente de catalogue autorisée": (
        "En cas de projet de cession totale ou partielle du catalogue de l'Éditeur incluant l'Œuvre à un tiers, "
        "l'Auteur disposera d'un droit de préemption lui permettant d'acquérir les droits aux conditions proposées "
        "au tiers cessionnaire. Ce droit devra être exercé dans un délai de trente (30) jours à compter de la "
        "notification écrite des conditions de la cession envisagée. En cas de vente du catalogue malgré l'exercice "
        "du droit de préemption — notamment en raison d'une offre supérieure — l'Auteur sera en droit de résilier "
        "le présent contrat par lettre recommandée avec accusé de réception adressée au cessionnaire dans les "
        "soixante (60) jours suivant la notification définitive de la cession."
    ),
    "Clause d'arbitrage": (
        "Tout litige relatif à l'interprétation, à la validité ou à l'exécution du présent contrat, qui n'aurait "
        "pas pu être réglé à l'amiable ou par médiation dans un délai de trente (30) jours, sera soumis à la "
        "procédure d'arbitrage du Centre d'Arbitrage et de Médiation de Paris (CMAP) conformément à son règlement "
        "d'arbitrage en vigueur à la date de saisine. Le tribunal arbitral sera composé d'un arbitre unique désigné "
        "par l'institution. Le siège de l'arbitrage sera fixé à Paris. La langue de la procédure arbitrale sera "
        "le français. La sentence arbitrale sera définitive et s'imposera aux parties avec force exécutoire."
    ),
    "Modalités de notification": (
        "Toute notification, mise en demeure, résiliation ou communication contractuelle devra être adressée par "
        "lettre recommandée avec accusé de réception à l'adresse indiquée en tête du présent contrat, ou par "
        "email à l'adresse contractuelle désignée à l'article Notifications, avec demande de confirmation de "
        "réception. Les notifications seront réputées reçues et produiront leurs effets juridiques : "
        "(i) le lendemain du jour de l'envoi par email, en cas de confirmation de réception électronique effective ; "
        "(ii) à la date de première présentation en cas d'envoi par lettre recommandée avec accusé de réception, "
        "même en cas de refus de réception de la part du destinataire."
    ),
    "Liste des annexes": (
        "Sont annexés au présent contrat et en font partie intégrante les documents suivants :\n"
        "Annexe 1 — Fiche technique de l'Œuvre (titre, durée, genre, ISRC, ISWC, UPC, date d'enregistrement)\n"
        "Annexe 2 — Split sheet et répartition des droits d'auteur entre co-auteurs et co-compositeurs\n"
        "Annexe 3 — Barème de royalties détaillé par plateforme, par territoire et par type d'exploitation\n"
        "Annexe 4 — Calendrier prévisionnel de sortie et plan de promotion validé par les parties\n"
        "Annexe 5 — Politique d'utilisation par l'intelligence artificielle et conditions de compensation\n"
        "Annexe 6 — Template de relevé de comptes trimestriel à utiliser obligatoirement par l'Éditeur"
    ),
    "Entraînement de modèles d'IA": (
        "L'utilisation de l'Œuvre aux fins d'entraînement de modèles d'intelligence artificielle est [autorisée / "
        "expressément interdite]. En cas d'autorisation, cette utilisation est soumise aux conditions cumulatives "
        "suivantes : (i) notification préalable écrite à l'Auteur au moins trente (30) jours avant le début de "
        "tout cycle d'entraînement, accompagnée d'une description du modèle et de ses finalités d'utilisation ; "
        "(ii) versement d'une compensation forfaitaire de [montant] euros par modèle et par cycle d'entraînement, "
        "dans les trente (30) jours suivant chaque utilisation identifiée ; (iii) droit pour l'Auteur d'exiger "
        "la suppression ou l'exclusion de ses données de tout dataset d'entraînement dans un délai de trente "
        "(30) jours sur simple demande écrite, sans que cela ne donne lieu à indemnité pour l'Éditeur."
    ),
    "Clonage vocal": (
        "Le clonage de la voix de l'Artiste par des technologies d'intelligence artificielle est [autorisé / "
        "expressément interdit]. En cas d'autorisation, les conditions suivantes s'appliquent de manière "
        "cumulative et non négociable : (i) le clone vocal ne peut être utilisé qu'aux fins expressément "
        "mentionnées au présent contrat, à l'exclusion de tout autre usage ; (ii) toute production utilisant "
        "le clone vocal devra comporter la mention claire et visible « Voix générée par intelligence artificielle "
        "à partir de [Nom d'artiste] » ; (iii) la rémunération est fixée à [montant] euros par production "
        "commerciale utilisant le clone vocal, ou [X] % des revenus nets générés par ladite production, le "
        "plus élevé des deux étant retenu ; (iv) l'Auteur conserve à tout moment le droit de révoquer cette "
        "autorisation par notification écrite avec un préavis de [X] jours."
    ),
    "Synthèse de voix / d'éléments musicaux": (
        "La création de nouveaux éléments sonores par synthèse artificielle à partir de l'Œuvre — qu'il s'agisse "
        "de mélodies, d'harmonies, d'arrangements ou de textures sonores — est [autorisée / expressément "
        "interdite]. En cas d'autorisation, les éléments synthétisés entrent dans le périmètre d'application "
        "du présent contrat et sont soumis à l'ensemble de ses conditions, notamment en matière de rémunération "
        "et de reporting. L'Éditeur s'engage à identifier et à tracer toute utilisation synthétisée dans les "
        "rapports de streaming transmis à l'Auteur et à verser la rémunération correspondante dans les conditions "
        "prévues à l'article Royalties, sans abattement ni déduction spécifique liée à la nature synthétisée "
        "des éléments exploités."
    ),
    "Exploitation algorithmique": (
        "L'Éditeur est autorisé à inclure l'Œuvre dans des playlists algorithmiques, des radios automatisées, "
        "des systèmes de recommandation et tout dispositif de curation automatisée opéré par les plateformes de "
        "streaming, sous réserve des conditions suivantes : (i) les streams générés via ces mécanismes "
        "algorithmiques sont inclus dans l'assiette de calcul des royalties et reportés distinctement dans les "
        "relevés de comptes trimestriels ; (ii) l'Éditeur communiquera à l'Auteur, sur demande écrite, un "
        "rapport semestriel mentionnant les principales playlists algorithmiques ou éditorialisées dans "
        "lesquelles l'Œuvre a été intégrée ; (iii) l'Auteur ne pourra s'opposer à l'inclusion algorithmique "
        "que pour des motifs liés à la protection de son image ou de sa réputation artistique."
    ),
    "Renouvellement tacite": (
        "À l'issue de la durée initiale prévue au présent contrat, celui-ci se renouvellera tacitement par "
        "périodes successives de [durée] an(s) aux mêmes conditions, sauf dénonciation expresse de l'une ou "
        "l'autre des parties. La dénonciation devra être notifiée par lettre recommandée avec accusé de "
        "réception au moins [X] mois avant l'échéance de la période en cours. Chaque partie aura la faculté "
        "de s'opposer au renouvellement sans avoir à justifier d'un motif particulier, à condition de "
        "respecter strictement le délai de préavis susvisé. À défaut de dénonciation dans ce délai, les "
        "parties seront réputées avoir consenti au renouvellement pour une période supplémentaire."
    ),
}


def update_examples() -> int:
    """Patch example_text on existing clauses (overwrites any existing value)."""
    updated = 0
    for name, text in _EXAMPLES.items():
        rows = (
            db.session.query(ContractClause)
            .filter(ContractClause.name == name)
            .all()
        )
        for row in rows:
            row.example_text = text
            updated += 1
    db.session.commit()
    return updated


# ── Tooltip long texts ────────────────────────────────────────────────────────
# Maps exact clause name → tooltip_long text for all clauses missing a long tooltip.
_TOOLTIPS_LONG: dict[str, str] = {
    # Préambule
    "Historique de collaboration": (
        "Le rappel d'une collaboration antérieure dans le préambule peut servir à interpréter le contrat en cas de litige : "
        "il établit la relation de confiance et la continuité des engagements. Il peut fonder une clause d'intuitu personae "
        "(contrat conclu en considération de la personne)."
    ),
    # Objet
    "Finalité et description": (
        "L'objet du contrat doit être déterminé ou déterminable (art. 1163 Code civil). Pour les droits d'auteur, il précise "
        "la nature exacte de l'exploitation autorisée. Une description vague peut être interprétée restrictivement en faveur "
        "de l'auteur (art. L122-7-1 CPI)."
    ),
    # Désignation
    "Titre de l'œuvre": (
        "Le titre exact est indispensable pour l'identification de l'œuvre dans les bases de données (SACEM, CISAC, ISRC). "
        "Un titre ambigu ou incomplet peut générer des conflits de droits lors de la distribution sur les plateformes "
        "et nuire à la collecte des droits voisins."
    ),
    "Description de l'œuvre": (
        "La description précise la forme d'expression de l'œuvre (enregistrement phonographique, partition, etc.) et ses "
        "caractéristiques techniques utiles pour la gestion des droits. En droit d'auteur, l'originalité de l'œuvre "
        "(empreinte de la personnalité de l'auteur, art. L112-1 CPI) doit être identifiable."
    ),
    "Code UPC/EAN": (
        "Le code UPC (Universal Product Code) ou EAN-13 identifie le produit commercial (album, EP, single), distinct "
        "de l'ISRC (qui identifie l'enregistrement) et de l'ISWC (la composition). Chaque format de sortie "
        "(vinyle, CD, digital) peut avoir son propre UPC attribué par le distributeur."
    ),
    "Versions concernées": (
        "Il est essentiel de lister précisément les versions incluses pour éviter tout litige sur le périmètre des droits. "
        "Un contrat portant sur la 'version originale' ne couvre pas automatiquement un remix ultérieur, "
        "qui constitue une œuvre dérivée distincte soumise à autorisation séparée."
    ),
    "Fichiers et éléments livrés": (
        "La liste des éléments à livrer conditionne souvent le versement de la deuxième tranche d'avance. "
        "Elle doit être exhaustive et précise : en cas de litige sur l'exécution du contrat, "
        "c'est cette liste qui fait foi auprès d'un tribunal."
    ),
    # Nature des droits
    "Droit de représentation": (
        "Le droit de représentation couvre toute communication de l'œuvre au public (concert, diffusion radio/TV, streaming). "
        "Ce droit est géré en France par la SACEM pour les auteurs adhérents. "
        "La cession doit être explicite et ne peut priver l'auteur de sa rémunération proportionnelle (art. L131-4 CPI)."
    ),
    "Droit de distribution": (
        "Le droit de distribution (art. L122-1 CPI) couvre la vente, le prêt et la location de copies de l'œuvre. "
        "En droit européen, ce droit est soumis au principe d'épuisement : une fois une copie commercialisée "
        "avec l'accord du titulaire, le droit de distribution sur cette copie s'épuise (directive 2001/29/CE)."
    ),
    "Mise à disposition / Streaming": (
        "Le droit de mise à disposition interactif (art. L122-2-1 CPI) couvre le streaming à la demande "
        "(Spotify, Apple Music, Deezer). Il est distinct du droit de radiodiffusion. "
        "Les revenus sont partagés entre l'auteur (SACEM), le producteur phonographique et l'artiste-interprète."
    ),
    "Droit d'adaptation / arrangement": (
        "Ce droit permet de transformer l'œuvre originale pour créer une œuvre dérivée (remix, arrangement, traduction musicale). "
        "Il doit être expressément mentionné car distinct du droit de reproduction. "
        "L'auteur de l'adaptation partage les droits sur l'œuvre dérivée avec l'auteur de l'original."
    ),
    # Modalités
    "Supports autorisés": (
        "La spécification des supports est fondamentale : un contrat portant sur la diffusion physique ne couvre pas "
        "le streaming numérique. En cas de doute, les clauses ambiguës sont interprétées en faveur de l'auteur "
        "(art. L122-7-1 CPI). La liste doit tenir compte des évolutions technologiques."
    ),
    "Précisions sur les modalités": (
        "Au-delà des supports listés, des précisions opérationnelles permettent d'éviter les conflits : délai de mise en ligne, "
        "obligation de distribution sur l'ensemble des plateformes du territoire, procédure de retrait en cas de résiliation. "
        "Ces précisions réduisent l'insécurité juridique lors de l'exécution du contrat."
    ),
    # Territoire
    "Précisions territoriales": (
        "Le territoire doit être défini avec précision, car pour l'exploitation numérique, la notion est complexe : "
        "un utilisateur peut accéder à une plateforme depuis n'importe quel pays. La pratique tend à utiliser "
        "des clauses de 'territoire résidence' de l'utilisateur plutôt que 'territoire d'accès' au serveur."
    ),
    # Durée
    "Date de prise d'effet": (
        "La date de prise d'effet détermine le début de toutes les obligations contractuelles : durée du contrat, "
        "délais de livraison, calcul des royalties. Elle peut être différente de la date de signature "
        "(contrat à effet différé ou rétroactif) mais doit être mentionnée explicitement."
    ),
    # Exclusivité
    "Exclusivité partielle (périmètre)": (
        "Une exclusivité partielle peut porter sur un territoire, un type de support ou une période déterminée. "
        "Elle doit être définie précisément : toute zone d'ambiguïté sera interprétée restrictivement "
        "en faveur de l'auteur, ce qui peut créer des conflits entre plusieurs cessionnaires simultanés."
    ),
    "Exceptions à l'exclusivité": (
        "Même avec une clause d'exclusivité, certains droits restent par nature hors périmètre : "
        "droits gérés collectivement par la SACEM, droits moraux inaliénables, œuvres préexistantes. "
        "Les exceptions doivent être listées précisément pour éviter des litiges sur leur étendue."
    ),
    # Obligations exploitant
    "Obligation de distribution": (
        "C'est une obligation de résultat : l'exploitant doit commercialiser l'œuvre effectivement, "
        "pas seulement de 'son mieux'. Le défaut d'exploitation peut constituer une cause de résiliation "
        "et de réversion des droits (art. L132-17 CPI)."
    ),
    "Minimum marketing": (
        "L'obligation de minimum marketing est souvent négligée dans les contrats des artistes indépendants, "
        "mais elle permet à l'auteur de disposer d'un recours si l'exploitant n'investit pas sérieusement "
        "dans la promotion. Le montant doit être réaliste par rapport aux standards de l'industrie."
    ),
    "Calendrier de sortie": (
        "Une date de sortie contractuelle engage l'exploitant : son non-respect sans motif légitime "
        "peut constituer une inexécution ouvrant droit à des dommages et intérêts. "
        "Prévoyez des clauses de force majeure adaptées pour les cas de retard indépendants de la volonté des parties."
    ),
    "Obligation de maintien de disponibilité": (
        "Cette clause garantit que l'œuvre reste accessible au public pendant toute la durée du contrat. "
        "Le retrait non justifié d'une œuvre des plateformes peut constituer un défaut d'exploitation "
        "ouvrant droit à la réversion des droits au bénéfice de l'auteur."
    ),
    "Obligation d'exploitation de bonne foi": (
        "L'obligation de bonne foi est un principe général des contrats (art. 1104 Code civil). "
        "Dans le secteur musical, elle couvre notamment l'obligation de ne pas favoriser d'autres artistes "
        "du catalogue au détriment de l'auteur et de respecter son image artistique."
    ),
    # Obligations auteur
    "Livraison des masters dans les délais": (
        "La livraison dans les délais est une obligation contractuelle fondamentale. "
        "En cas de retard imputable à l'auteur, l'exploitant peut demander des dommages et intérêts "
        "ou, en cas de retard persistant, la résiliation du contrat. Les délais doivent être réalistes."
    ),
    "Disponibilité promotionnelle": (
        "L'obligation de disponibilité promotionnelle couvre la participation de l'artiste aux interviews, "
        "sessions photos et événements PR. Elle doit être encadrée (nombre de jours par an, territoire, préavis minimum) "
        "pour ne pas devenir une obligation excessive et indéterminée."
    ),
    "Respect des délais contractuels": (
        "Le non-respect des délais peut constituer une inexécution contractuelle. "
        "Des clauses de notification préalable en cas de retard anticipé permettent d'éviter les litiges : "
        "l'auteur prévient l'exploitant à l'avance plutôt que de laisser un délai s'écouler sans réaction."
    ),
    "Absence de violation de droits tiers": (
        "Cette garantie engage l'auteur à s'assurer qu'aucun élément de l'œuvre ne viole les droits d'un tiers "
        "(sample non autorisé, interpolation, plagiat). En cas de litige avec un tiers, "
        "c'est l'auteur qui supporte les conséquences juridiques et financières si cette garantie est enfreinte."
    ),
    # Livraison technique
    "Éléments à livrer": (
        "La liste des éléments à livrer conditionne souvent le versement de la deuxième tranche d'avance. "
        "Les éléments non listés ne peuvent pas être exigés sans accord complémentaire. "
        "Les masters sont généralement conservés par le producteur ; les partitions relèvent de l'auteur-compositeur."
    ),
    "Formats et normes techniques": (
        "Les spécifications techniques conditionnent la qualité de la distribution sur les plateformes. "
        "La norme AES Streaming recommande –14 LUFS pour Spotify et –16 LUFS pour Apple Music. "
        "Un master mal masté peut être rejeté ou mal rendu, ce qui nuit à l'image artistique et aux streams."
    ),
    "Délai de livraison": (
        "Le délai doit être réaliste et tenir compte des contraintes de finalisation technique (mastering, artwork, métadonnées). "
        "Prévoyez une procédure de validation avec retours de corrections : "
        "un premier envoi refusé ne doit pas automatiquement constituer une violation du délai contractuel."
    ),
    # Avances
    "Montant de l'avance (€)": (
        "Le montant de l'avance doit être proportionné aux revenus attendus. "
        "En droit français, une avance disproportionnellement basse par rapport aux revenus générés peut être contestée "
        "sur la base de l'art. L131-5 CPI (prix lésionnaire), qui permet à l'auteur de demander une révision."
    ),
    "Conditions de versement": (
        "Les conditions de versement doivent être précises : date, conditions suspensives (livraison des masters validés, signature), "
        "modalités de paiement. Un échelonnement est courant : 50 % à la signature, 50 % à la livraison validée, "
        "ce qui aligne les intérêts des deux parties."
    ),
    # Royalties
    "Taux — exploitation physique (%)": (
        "Le taux sur l'exploitation physique (vinyle, CD) est historiquement calculé sur le prix de vente public HT "
        "ou sur le prix de gros. Les standards de l'industrie varient entre 15 % et 25 % du prix de gros. "
        "Attention aux abattements (containers, cassés, retours) qui doivent être plafonnés contractuellement."
    ),
    "Taux — streaming (%)": (
        "Les revenus de streaming sont partagés par les plateformes entre le distributeur (ou label) et l'artiste "
        "selon le taux contractuel. Un taux de 20-25 % sur les revenus nets du distributeur est standard "
        "pour les artistes indépendants ; il dépasse 50 % dans certains accords de distribution moderne."
    ),
    "Taux — synchronisation (%)": (
        "Les droits de synchronisation (synchro rights) sont négociés pour chaque utilisation audiovisuelle. "
        "La SACEM gère la partie composition ; la partie enregistrement (droits voisins) est négociée directement. "
        "Les tarifs varient considérablement selon la notoriété de l'artiste et l'importance de la production."
    ),
    "Taux — YouTube / UGC (%)": (
        "Les revenus YouTube et UGC sont générés via le Content ID, qui monétise automatiquement "
        "les vidéos d'utilisateurs utilisant votre musique. Ces revenus sont souvent faibles par utilisation "
        "mais peuvent être significatifs en cas de viralité. Vérifiez que votre distributeur gère activement le Content ID."
    ),
    # Seuils
    "Paliers de rémunération": (
        "Les paliers progressifs alignent les intérêts des parties : l'exploitant est incité à maximiser les streams "
        "pour atteindre les paliers plus rémunérateurs, et l'auteur bénéficie d'un taux progressif récompensant le succès. "
        "Cette structure est courante dans les contrats de distribution pour les artistes à fort potentiel."
    ),
    # Recoupement
    "Dépenses recoupables": (
        "La définition des dépenses recoupables est l'un des points les plus importants du contrat. "
        "Limitez les catégories et exigez des plafonds. Les frais de promotion et de marketing "
        "ne doivent généralement pas être recoupables selon les pratiques équilibrées de l'industrie."
    ),
    "Ordre et plafonds de recoupement": (
        "Sans ordre de priorité ni plafond, le recoupement peut s'étendre indéfiniment : "
        "l'auteur ne percevrait aucune royaltie tant que l'ensemble des dépenses n'est pas récupéré. "
        "Un plafond global protège l'auteur contre des dépenses excessives de l'exploitant."
    ),
    # Comptabilité
    "Fréquence des relevés de comptes": (
        "Un relevé semestriel ou trimestriel est standard dans l'industrie musicale. "
        "Des délais trop longs (annuels) peuvent masquer des problèmes de reversement "
        "et rendent difficile la détection d'erreurs dans le temps. L'art. L132-14 CPI impose des obligations de transparence."
    ),
    "Conservation des données comptables (années)": (
        "La durée de conservation des données comptables conditionne l'exercice effectif du droit d'audit. "
        "La prescription de droit commun est de 5 ans (art. 2224 Code civil). "
        "Une durée de 5 ans minimum est recommandée pour permettre des vérifications pluriannuelles."
    ),
    "Droit d'audit": (
        "Le droit d'audit est un droit fondamental de l'auteur, souvent difficile à faire valoir en pratique. "
        "Il permet de faire vérifier par un expert-comptable indépendant la conformité des reversements effectués. "
        "L'art. L132-14 CPI impose à l'éditeur musical de rendre compte de ses exploitations."
    ),
    "Procédure d'audit": (
        "La procédure d'audit doit être suffisamment accessible pour être effectivement exercée "
        "tout en protégeant l'exploitant contre des demandes abusives ou répétées. "
        "Un préavis de 30 jours et une fréquence annuelle sont des standards équilibrés dans l'industrie."
    ),
    # Garanties
    "Garantie de titularité des droits": (
        "L'auteur doit être le véritable titulaire des droits qu'il cède ou concède. "
        "En cas de co-création (featuring, co-composition), tous les co-auteurs doivent avoir signé ou donné leur accord. "
        "Une fausse déclaration de titularité engage pleinement la responsabilité contractuelle de l'auteur."
    ),
    "Garantie d'originalité": (
        "L'originalité est la condition fondamentale de la protection par le droit d'auteur (art. L112-1 CPI). "
        "Si l'œuvre est reconnue non originale ou constitutive de contrefaçon, le contrat peut être anéanti "
        "et l'auteur engage sa responsabilité pour les préjudices causés à l'exploitant et aux tiers."
    ),
    "Absence de sample non autorisé": (
        "Un sample non autorisé constitue une contrefaçon (art. L335-2 CPI) punissable d'amendes et d'emprisonnement. "
        "Tout sample doit faire l'objet d'une double clearance : autorisation de l'auteur-compositeur "
        "ET du producteur phonographique de l'enregistrement samplé."
    ),
    "Obtention des autorisations nécessaires": (
        "Au-delà des samples, d'autres autorisations peuvent être nécessaires : interpolations de mélodies, "
        "utilisation de phrases célèbres, photos de personnalités pour l'artwork. "
        "L'auteur doit conserver la documentation de toutes les autorisations obtenues."
    ),
    # Responsabilité
    "Limitation de responsabilité": (
        "Les clauses limitatives de responsabilité sont valables entre professionnels mais ne peuvent exonérer "
        "une partie en cas de faute lourde ou dolosive (art. 1231-3 Code civil). "
        "Elles s'interprètent strictement et ne couvrent que les dommages directs et prévisibles."
    ),
    "Prise en charge des litiges tiers": (
        "Si un tiers engage une action pour contrefaçon contre l'exploitant, "
        "la répartition des coûts de défense et des dommages éventuels doit être prévue contractuellement. "
        "L'auteur ayant garanti la titularité et l'originalité doit assumer les conséquences d'une telle action."
    ),
    "Assurance": (
        "La souscription d'une assurance RC pro est une bonne pratique permettant de couvrir les risques résiduels "
        "liés à l'exploitation (contrefaçon involontaire, défaut de clearance). "
        "Elle complète utilement les garanties contractuelles et peut être exigée par les diffuseurs ou partenaires."
    ),
    # Droits moraux
    "Validation artistique requise": (
        "Le droit moral de l'auteur (art. L121-1 CPI) lui confère un droit de contrôle sur les modifications de son œuvre. "
        "La clause de validation formalise ce droit et définit les délais et procédures, "
        "protégeant l'intégrité de l'œuvre tout en permettant à l'exploitant de planifier ses activités."
    ),
    "Autorisation d'adaptation": (
        "Le droit d'adaptation ou de transformation (art. L122-4 CPI) est distinct du droit de reproduction. "
        "Sans autorisation explicite, toute modification — même mineure — peut violer le droit moral de l'auteur. "
        "L'auteur de l'adaptation doit être identifié et rémunéré séparément."
    ),
    # Synchronisation
    "Publicité": (
        "La synchronisation dans une publicité nécessite deux autorisations distinctes : "
        "celle du compositeur/auteur (via la SACEM ou directement) et celle du producteur phonographique. "
        "Les tarifs varient selon la durée d'utilisation, le support et la portée géographique de la campagne."
    ),
    "Cinéma / Séries télévisées": (
        "La synchro cinématographique est généralement négociée directement entre le superviseur musical et l'ayant droit, "
        "hors SACEM pour la partie synchronisation. Le contrat doit préciser la durée d'utilisation, "
        "le territoire et les supports de diffusion autorisés (salles, VOD, TV)."
    ),
    "Jeux vidéo": (
        "Les droits de synchronisation dans les jeux vidéo incluent souvent une utilisation illimitée pour toute la durée de vie du jeu. "
        "Les tarifs varient selon la notoriété du jeu et de l'artiste. "
        "La SACEM administre les droits de représentation des jeux diffusés en public (ESports, streaming)."
    ),
    "Plateformes sociales (Reels, Shorts, TikTok)": (
        "TikTok, Instagram et YouTube ont des accords globaux avec les majors, "
        "mais les artistes indépendants doivent vérifier si leur distributeur est couvert par ces accords. "
        "Les revenus UGC sont faibles par utilisation individuelle mais peuvent être significatifs en cumulé lors de viralité."
    ),
    "Trailers / Bande-annonces": (
        "Les droits de synchronisation dans les bandes-annonces sont souvent négociés séparément du film ou de la série. "
        "Une bande-annonce peut être diffusée massivement sur internet, "
        "ce qui augmente considérablement la valeur du placement et le prix de la licence de synchronisation."
    ),
    "Podcasts": (
        "L'utilisation d'une œuvre musicale en générique ou en fond sonore de podcast nécessite une autorisation préalable. "
        "Spotify Podcasts et Apple Podcasts ont des accords de licence globaux, "
        "mais les utilisations significatives (reprises d'extraits notables) peuvent nécessiter des autorisations complémentaires."
    ),
    "Livestreams": (
        "Le livestreaming soulève des questions complexes de droits d'auteur. "
        "Twitch, YouTube Live et d'autres plateformes ont des politiques anti-DMCA qui peuvent bloquer ou supprimer "
        "une diffusion live utilisant de la musique protégée sans accord de licence spécifique."
    ),
    "Précisions synchro": (
        "Les droits de synchronisation doivent être définis avec précision : durée maximale d'utilisation dans l'œuvre, "
        "territoire et durée de diffusion, types de supports. "
        "Une synchro 'tous droits' (buyout) est très différente d'une synchro limitée dans le temps et l'espace."
    ),
    # Exploitation numérique
    "Plateformes DSP (Spotify, Apple Music...)": (
        "La distribution sur les DSP (Digital Service Providers) est généralement gérée via un distributeur numérique. "
        "Le contrat doit préciser si l'exploitant utilise un distributeur tiers "
        "et comment les revenus des DSP sont calculés et reversés à l'auteur."
    ),
    "YouTube Content ID": (
        "Le Content ID est le système de reconnaissance audio-vidéo de YouTube. "
        "Lorsqu'une vidéo utilise votre musique sans autorisation, elle est automatiquement identifiée "
        "et peut être monétisée au profit de l'ayant droit, bloquée ou tracée selon la politique définie."
    ),
    "TikTok": (
        "TikTok représente un canal de promotion et de revenus croissant pour les artistes. "
        "Les œuvres présentes sont utilisées dans des vidéos courtes (clips) et peuvent générer une viralité significative. "
        "Vérifiez que votre distributeur dispose d'un accord actif avec TikTok pour la monétisation."
    ),
    "Meta (Instagram, Facebook Reels)": (
        "Meta dispose d'accords de licence globaux avec les principaux distributeurs musicaux. "
        "Les revenus générés sur Instagram et Facebook Reels sont reversés aux ayants droit via le distributeur. "
        "Vérifiez que votre distributeur est bien couvert par ces accords pour ne pas perdre ces revenus."
    ),
    "Twitch": (
        "Twitch dispose d'accords avec certaines bibliothèques musicales, mais ces accords ne couvrent pas toutes les œuvres. "
        "L'utilisation de musique protégée sur Twitch peut entraîner des mutes audio ou des DMCA strikes. "
        "Un accord explicite est recommandé pour sécuriser les streams musicaux en direct."
    ),
    "NFT / Blockchain": (
        "La propriété d'un NFT (Non-Fungible Token) ne confère pas automatiquement des droits de propriété intellectuelle "
        "sur l'œuvre sous-jacente. La clause NFT doit clarifier précisément quels droits sont transférés avec le token "
        "et prévoir la royaltie de revente secondaire (smart contract)."
    ),
    "UGC / Remix utilisateurs": (
        "Les contenus générés par les utilisateurs (UGC) constituent une forme d'exploitation croissante. "
        "La politique UGC doit définir clairement les usages autorisés (non-commercial, mention obligatoire) "
        "et les modalités de partage des revenus de monétisation générés par ces contenus."
    ),
    "Avatars virtuels / Métavers": (
        "L'utilisation d'œuvres musicales dans les environnements virtuels (Roblox, Fortnite, Decentraland) est émergente. "
        "Les droits applicables aux métavers sont encore en cours de définition juridique. "
        "Une clause explicite permet de sécuriser et rémunérer ces nouveaux usages."
    ),
    # Données
    "Gestion des identifiants (ISRC, ISWC, UPC)": (
        "Les identifiants numériques sont essentiels pour le tracking des streams et le calcul des droits. "
        "Une mauvaise saisie de ces codes peut entraîner des pertes de revenus importantes "
        "lors de la collecte des droits par la SACEM, le SCPP ou les plateformes DSP."
    ),
    "Reporting plateforme": (
        "Les données des plateformes (Spotify for Artists, Apple Music for Artists) fournissent des informations "
        "précieuses sur les performances de l'œuvre par territoire et par playlist. "
        "L'exploitant doit les partager régulièrement pour permettre à l'auteur de suivre son exploitation."
    ),
    "Collecte SACEM / droits voisins": (
        "La SACEM collecte les droits d'auteur (composition) ; le SCPP et la SCAPR collectent les droits voisins (phonogrammes). "
        "La responsabilité des démarches d'affiliation et de déclaration des œuvres auprès de ces organismes "
        "doit être clairement répartie entre les parties."
    ),
    "Matching Content ID": (
        "Le matching Content ID consiste à enregistrer votre œuvre dans le système YouTube "
        "pour que toute utilisation non autorisée soit automatiquement identifiée et monétisée. "
        "Sans matching actif, les revenus YouTube peuvent être perdus ou captés par des tiers."
    ),
    # Confidentialité
    "Durée de confidentialité post-résiliation (années)": (
        "L'obligation de confidentialité doit survivre à la résiliation pour protéger les informations sensibles "
        "(montants, stratégies, données d'écoute) même après la fin de la relation contractuelle. "
        "Une durée de 3 à 5 ans est standard en pratique contractuelle française."
    ),
    "Périmètre de la confidentialité": (
        "Le périmètre doit être défini avec précision pour être juridiquement opposable. "
        "Une clause trop large ('toute information') sera difficile à appliquer en pratique. "
        "Les exclusions standards (informations publiques, obligations légales de divulgation) doivent être mentionnées."
    ),
    # Communication
    "Biographie pour la presse": (
        "La biographie officielle et les photos presse sont des outils promotionnels que l'artiste doit contrôler "
        "pour préserver son image artistique. Toute utilisation d'une biographie obsolète ou d'une photo non validée "
        "peut constituer une atteinte à l'image de l'artiste."
    ),
    "Contenus réseaux sociaux": (
        "L'exploitant peut avoir besoin de créer des contenus promotionnels (posts, stories) mentionnant l'artiste. "
        "L'auteur doit contrôler les messages et le ton pour préserver sa cohérence artistique "
        "et éviter toute association commerciale non souhaitée avec des marques ou des campagnes."
    ),
    # Force majeure
    "Événements couverts": (
        "La liste contractuelle des cas de force majeure doit être précise. En l'absence de définition, "
        "la jurisprudence applique les critères de l'art. 1218 Code civil : extériorité, imprévisibilité, irrésistibilité. "
        "La pandémie de COVID-19 a relancé le débat sur l'appréciation de ces critères dans le secteur musical."
    ),
    "Effets de la force majeure": (
        "Les effets de la force majeure peuvent varier selon le choix des parties : "
        "simple suspension des obligations (la plus courante), report des délais, ou résiliation possible "
        "si la durée de l'événement dépasse un seuil convenu. Le choix doit correspondre à la nature des obligations."
    ),
    # Résiliation
    "Résiliation pour inexécution": (
        "La résiliation pour inexécution est le droit commun des contrats (art. 1224 Code civil). "
        "En pratique, elle est souvent précédée d'une mise en demeure restée sans effet dans un délai raisonnable. "
        "La faute doit être suffisamment grave pour justifier la rupture du contrat."
    ),
    "Résiliation pour non-paiement": (
        "Le non-paiement des royalties ou des avances dans les délais contractuels est une inexécution grave. "
        "Un délai de mise en demeure préalable (30 jours en général) permet à l'exploitant de régulariser sa situation "
        "avant que la résiliation ne soit prononcée."
    ),
    "Résiliation pour faillite / liquidation": (
        "En cas de procédure collective, l'administrateur judiciaire dispose d'un droit d'option pour poursuivre "
        "les contrats en cours. Il est important de prévoir contractuellement les effets de la résiliation dans ce cas, "
        "notamment le sort des masters et des droits concédés."
    ),
    "Résiliation pour absence d'exploitation": (
        "Cette clause est liée au droit à la réversion prévu à l'art. L132-17 CPI. "
        "Elle protège l'auteur contre l'inaction d'un exploitant qui monopoliserait ses droits sans les valoriser. "
        "Un délai raisonnable (12 à 18 mois) doit être prévu avant que la clause puisse être invoquée."
    ),
    "Résiliation pour atteinte à l'image": (
        "Cette clause protège chaque partie contre les comportements de l'autre nuisant à son image publique. "
        "Elle doit être définie avec précision (comportements visés, procédure de notification) "
        "pour éviter d'être invoquée abusivement en cas de désaccord commercial."
    ),
    "Résiliation pour violation d'exclusivité": (
        "La violation d'une clause d'exclusivité est une inexécution grave permettant la résiliation immédiate "
        "et l'obtention de dommages et intérêts. Elle doit être documentée par écrit avant toute action. "
        "Prévoyez une période de mise en demeure pour les violations potentiellement involontaires."
    ),
    "Effets et délais de résiliation": (
        "Les effets de la résiliation doivent être définis précisément : délai de retrait des plateformes, "
        "sort des avances non recoupées, obligations de retrait des contenus promotionnels. "
        "Sans ces précisions, la résiliation peut entraîner des litiges sur ses effets pratiques immédiats."
    ),
    # Réversion
    "Récupération des masters": (
        "La récupération des masters à la fin du contrat est un enjeu majeur pour les artistes. "
        "Sans clause explicite, les masters peuvent rester entre les mains de l'exploitant qui les a financés. "
        "Négociez un droit de rachat à prix équitable ou un retour automatique à la fin du contrat."
    ),
    "Conditions de réversion": (
        "Les conditions précises de la réversion doivent être détaillées pour être facilement invocables : "
        "forme de la notification, délai de mise en œuvre, procédure de retrait des plateformes et des supports physiques. "
        "Sans précision, la réversion théoriquement prévue peut être difficile à mettre en œuvre."
    ),
    # Cession
    "Sous-licence autorisée": (
        "La sous-licence permet à l'exploitant de concéder à des distributeurs ou partenaires "
        "tout ou partie des droits qu'il détient. Sans autorisation de l'auteur, elle est nulle. "
        "L'auteur doit s'assurer que la sous-licence ne peut pas contourner ses droits ni diluer sa rémunération."
    ),
    "Vente de catalogue autorisée": (
        "La vente d'un catalogue musical à un fonds d'investissement ou à un autre label est une pratique courante. "
        "L'auteur doit être protégé contre les ventes qui transféreraient ses droits à des entités peu fiables "
        "ou qui modifieraient unilatéralement les conditions d'exploitation initialement négociées."
    ),
    # Droit applicable
    "Droit applicable": (
        "Le droit applicable détermine les lois régissant le contrat. En France, le CPI contient des dispositions "
        "d'ordre public favorables aux auteurs (rémunération proportionnelle, droit moral) qui s'imposent "
        "même si les parties désignent un autre droit national."
    ),
    "Tribunaux compétents": (
        "En France, les litiges relatifs aux droits d'auteur relèvent des tribunaux judiciaires spécialisés "
        "(13 juridictions désignées par décret). Les parties peuvent aussi prévoir une clause attributive de compétence "
        "pour des questions purement commerciales n'impliquant pas les droits d'auteur."
    ),
    "Médiation préalable obligatoire": (
        "La médiation préalable permet de résoudre les conflits plus rapidement et moins coûteusement qu'un procès. "
        "Elle est particulièrement adaptée aux litiges artistiques où la préservation de la relation commerciale "
        "peut être souhaitable par les deux parties."
    ),
    # Notifications
    "Email contractuel du cessionnaire": (
        "L'adresse email contractuelle est le canal officiel de toutes les communications importantes. "
        "Elle doit être une adresse professionnelle pérenne (pas une adresse personnelle susceptible d'être abandonnée) "
        "et être régulièrement consultée pour éviter de manquer des notifications critiques."
    ),
    "Modalités de notification": (
        "Les modalités de notification conditionnent la valeur probatoire des communications contractuelles. "
        "La lettre recommandée AR reste le mode de preuve le plus sûr juridiquement, "
        "mais l'email avec confirmation de lecture est de plus en plus admis en pratique commerciale."
    ),
    # Clauses générales
    "Divisibilité des clauses": (
        "La clause de divisibilité (severability) préserve la validité du contrat si une clause est déclarée nulle. "
        "Sans elle, la nullité d'une seule clause pourrait entraîner la nullité de l'ensemble du contrat, "
        "ce qui serait disproportionné par rapport à l'intention des parties."
    ),
    "Intégralité du contrat": (
        "La clause d'intégralité (entire agreement) signifie que ce contrat remplace tous les accords verbaux "
        "ou écrits antérieurs portant sur le même objet. Elle évite les litiges sur des engagements informels "
        "pris lors des négociations précontractuelles."
    ),
    "Modification écrite obligatoire": (
        "La clause de modification écrite empêche toute modification orale du contrat. "
        "Elle est essentielle pour garantir la sécurité juridique et éviter les malentendus "
        "sur des conditions renégociées informellement après la signature."
    ),
    "Clause de non-renonciation": (
        "Le fait pour une partie de ne pas exercer un droit contractuel à un moment donné "
        "ne constitue pas une renonciation définitive à ce droit. "
        "Elle évite qu'une tolérance ponctuelle (ex. : accepter un paiement tardif) soit interprétée comme un abandon."
    ),
    "Survie des clauses": (
        "Certaines clauses ont vocation à survivre à la résiliation du contrat : la confidentialité, "
        "les garanties, les obligations d'audit, les clauses de règlement des litiges. "
        "Sans mention explicite, la survie de ces clauses après la fin du contrat peut être contestée."
    ),
    "Ordre de priorité des annexes": (
        "En cas de contradiction entre le corps du contrat et une annexe, ou entre plusieurs annexes, "
        "cette clause définit quelle version prévaut. Elle évite les litiges d'interprétation "
        "en cas de contradiction entre des documents établis à des dates différentes."
    ),
    # Annexes
    "Liste des annexes": (
        "Les annexes font partie intégrante du contrat et ont la même valeur juridique que le corps du texte, "
        "sauf ordre de priorité contraire. Elles doivent être listées exhaustivement et paraphées par les deux parties "
        "pour éviter tout litige sur leur authenticité ou leur intégration au contrat."
    ),
    # Clauses IA
    "Entraînement de modèles d'IA": (
        "L'utilisation d'œuvres pour entraîner des IA fait l'objet de vives controverses juridiques. "
        "La directive européenne sur le droit d'auteur (2019/790) prévoit une exception pour la fouille de données "
        "à des fins de recherche, mais son application commerciale est contestée."
    ),
    "Clonage vocal": (
        "La voix est un attribut de la personnalité protégé par le droit à l'image vocale et par les droits voisins "
        "des artistes-interprètes (art. L212-1 CPI). Toute utilisation du clone vocal sans autorisation explicite "
        "est susceptible d'engager la responsabilité civile et pénale de l'exploitant."
    ),
    "Synthèse de voix / d'éléments musicaux": (
        "La synthèse musicale par IA à partir d'œuvres existantes soulève des questions de qualification des œuvres générées. "
        "En France, les œuvres entièrement générées par IA ne bénéficient pas de la protection du droit d'auteur, "
        "qui requiert une intervention créative humaine. Les œuvres hybrides sont dans un flou juridique."
    ),
    "Exploitation algorithmique": (
        "L'inclusion dans des playlists algorithmiques est devenue un levier majeur de la découverte musicale. "
        "L'auteur n'a pas de droit à être inclus dans ces playlists (décision discrétionnaire des plateformes), "
        "mais les revenus générés doivent être inclus dans l'assiette des royalties et reportés."
    ),
    "Politique de compensation IA": (
        "La rémunération pour les usages IA est un sujet émergent : plusieurs accords collectifs sont en négociation "
        "dans l'industrie musicale entre les majors et les fournisseurs d'IA (OpenAI, Stability AI, etc.). "
        "En l'absence d'accord sectoriel, la compensation individuelle doit être négociée contractuellement."
    ),
}


# ── Explications en langage simple (tooltip_plain) ───────────────────────────
# 1-2 phrases max, sans jargon. Point de vue : le créateur du contrat (exploitant,
# manager, label, distributeur…) et non l'artiste. L'artiste est "l'artiste" / "il/elle".

_PLAIN_TEXTS: dict[str, str] = {

    # ── 0 — Préambule ─────────────────────────────────────────────────────────
    "Contexte et volonté des parties": (
        "C'est l'introduction du contrat : vous présentez qui vous êtes et pourquoi vous signez ensemble. "
        "Ça ne crée pas d'obligation mais prouve votre bonne foi si un désaccord survient."
    ),
    "Historique de collaboration": (
        "Si vous avez déjà travaillé ensemble par le passé, notez-le ici — ça renforce la crédibilité du contrat "
        "et explique pourquoi vous vous faites confiance."
    ),

    # ── 1 — Définitions ───────────────────────────────────────────────────────
    "Glossaire des termes": (
        "Un mini-dictionnaire des mots clés du contrat (ex : 'recette nette', 'streaming', 'territoire'). "
        "Utile pour que chacun comprenne la même chose — et pour éviter les mauvaises surprises en cas de litige."
    ),

    # ── 2 — Objet ─────────────────────────────────────────────────────────────
    "Nature juridique": (
        "Vous choisissez ici si vous obtenez un droit d'exploitation temporaire sur la musique de l'artiste (licence : il reste propriétaire) "
        "ou si l'artiste vous transfère ses droits de façon définitive (cession : il ne peut plus les récupérer)."
    ),
    "Finalité et description": (
        "Décrivez concrètement ce que vous allez faire avec la musique : distribution, promotion, synchro… "
        "Plus c'est précis, plus vous êtes protégé si quelqu'un utilise l'œuvre hors de ce périmètre."
    ),

    # ── 3 — Désignation des œuvres ────────────────────────────────────────────
    "Titre de l'œuvre": (
        "Le titre exact du morceau concerné par ce contrat. "
        "Sans ça, impossible de savoir quelle chanson est couverte par l'accord."
    ),
    "Description de l'œuvre": (
        "Une description courte du morceau (genre, durée, année, format de livraison). "
        "Ça évite toute confusion si l'artiste a plusieurs titres ou si le master change."
    ),
    "Code ISWC": (
        "C'est le 'numéro de carte d'identité' de la composition musicale, attribué par la SACEM. "
        "Il permet de tracer et de percevoir les droits d'auteur de l'artiste partout dans le monde."
    ),
    "Code ISRC": (
        "C'est le code qui identifie l'enregistrement sonore (le master) sur toutes les plateformes. "
        "Spotify, Apple Music et YouTube s'en servent pour payer correctement l'artiste."
    ),
    "Code UPC/EAN": (
        "C'est le code-barre de l'album ou du single, nécessaire pour la distribution physique et numérique. "
        "Sans lui, les plateformes ne peuvent pas référencer la sortie."
    ),
    "Versions concernées": (
        "Précisez quelles versions du morceau sont couvertes : originale, remix, acoustique, instrumental… "
        "Toute version non listée reste hors du champ de ce contrat."
    ),
    "Fichiers et éléments livrés": (
        "La liste de tout ce que l'artiste doit vous remettre : fichiers audio, pochette, paroles, stems… "
        "Ça protège les deux parties si une livraison est incomplète ou contestée."
    ),

    # ── 4 — Nature des droits ─────────────────────────────────────────────────
    "Droit de reproduction": (
        "Cette clause vous donne le droit de copier la musique de l'artiste sur tous supports (CD, fichiers numériques, vinyles…). "
        "Sans ce droit, vous ne pouvez légalement rien dupliquer."
    ),
    "Droit de représentation": (
        "Cette clause vous donne le droit de diffuser publiquement la musique de l'artiste : radio, streaming, concerts, pub… "
        "C'est l'un des droits les plus importants financièrement."
    ),
    "Droit de distribution": (
        "Cette clause vous donne le droit de mettre la musique en vente dans les magasins ou en ligne. "
        "Indispensable pour toute commercialisation physique ou numérique."
    ),
    "Mise à disposition / Streaming": (
        "Cette clause vous donne le droit de diffuser la musique à la demande sur Spotify, Apple Music, Deezer, etc. "
        "C'est de là que viennent la plupart des royalties numériques aujourd'hui."
    ),
    "Droit d'adaptation / arrangement": (
        "Cette clause vous permet de modifier la musique de l'artiste : remix, arrangement, traduction… "
        "Sans elle, aucune modification n'est possible légalement."
    ),
    "Exploitation dérivée — NFT, IA, Métavers": (
        "Vous définissez ici si vous pouvez utiliser la musique de l'artiste pour créer des NFTs, alimenter une IA ou des expériences virtuelles. "
        "C'est un sujet neuf mais très important à clarifier dès maintenant."
    ),

    # ── 5 — Modalités d'exploitation ─────────────────────────────────────────
    "Supports autorisés": (
        "La liste des canaux sur lesquels vous pouvez exploiter la musique : streaming, vinyle, synchro, réseaux sociaux… "
        "Tout canal non listé vous est interdit — ce qui protège l'artiste."
    ),
    "Précisions sur les modalités": (
        "Les détails pratiques de votre exploitation : délais de mise en ligne, conditions de retrait, priorités de sortie… "
        "À compléter pour éviter les malentendus sur le 'comment'."
    ),

    # ── 6 — Territoire ────────────────────────────────────────────────────────
    "Territoire d'exploitation": (
        "Le ou les pays dans lesquels vous pouvez exploiter la musique de l'artiste. "
        "Hors de ce territoire, vous n'avez aucun droit d'exploitation."
    ),
    "Précisions territoriales": (
        "Si certains pays sont exclus ou ont des règles spéciales, notez-les ici. "
        "Utile si l'artiste travaille déjà avec un autre partenaire sur certains marchés."
    ),

    # ── 7 — Durée ─────────────────────────────────────────────────────────────
    "Durée du contrat": (
        "La durée pendant laquelle vous avez le droit d'exploiter la musique de l'artiste. "
        "À la fin de cette période, les droits reviennent automatiquement à l'artiste — sauf si le contrat est renouvelé."
    ),
    "Date de prise d'effet": (
        "La date à partir de laquelle le contrat s'applique réellement. "
        "Important pour savoir à partir de quand vos droits et obligations commencent."
    ),
    "Renouvellement tacite": (
        "Si aucune des parties ne dit rien avant la fin du contrat, il se renouvelle automatiquement. "
        "Activez cette option si vous souhaitez ce comportement — sinon, un avenant sera nécessaire."
    ),
    "Clause de sunset (non-exploitation)": (
        "Si vous n'exploitez pas la musique pendant X mois, le contrat prend fin automatiquement. "
        "Cette clause protège l'artiste contre un blocage de ses droits sans exploitation réelle de votre part."
    ),

    # ── 8 — Exclusivité ───────────────────────────────────────────────────────
    "Exclusivité totale": (
        "L'artiste s'engage à ne travailler qu'avec vous pour l'exploitation de cette musique. "
        "En échange, vous prenez généralement plus de risques financiers — mais l'artiste perd de sa liberté."
    ),
    "Exclusivité partielle (périmètre)": (
        "L'exclusivité ne porte que sur certains supports ou marchés (ex : le streaming seulement). "
        "L'artiste reste libre de travailler avec d'autres partenaires pour la synchro ou le physique."
    ),
    "Exceptions à l'exclusivité": (
        "Des situations où l'artiste peut quand même exploiter sa musique ailleurs, malgré l'exclusivité accordée. "
        "Exemple classique : les performances live ou les enregistrements acoustiques."
    ),

    # ── 9 — Obligations de l'exploitant ──────────────────────────────────────
    "Obligation de distribution": (
        "Vous vous engagez à réellement mettre la musique en vente et en ligne. "
        "Sans cette clause, rien ne vous oblige à sortir le disque — l'artiste serait bloqué sans recours."
    ),
    "Minimum marketing": (
        "Vous vous engagez à dépenser au minimum X€ pour promouvoir la musique de l'artiste. "
        "Ça garantit à l'artiste que la musique sera réellement promue, pas juste mise en ligne sans effort."
    ),
    "Calendrier de sortie": (
        "Les dates prévues pour la sortie du single, de l'album, des clips… "
        "Permet à l'artiste d'avoir un recours si vous prenez du retard sans raison valable."
    ),
    "Obligation de maintien de disponibilité": (
        "Vous vous engagez à maintenir la musique disponible sur les plateformes pendant toute la durée du contrat. "
        "Si vous la retirez sans raison, l'artiste peut vous réclamer des dommages."
    ),
    "Obligation d'exploitation de bonne foi": (
        "Vous vous engagez à faire de votre mieux pour développer la carrière ou les ventes de l'artiste. "
        "C'est une obligation générale de sérieux — difficile à prouver mais utile comme fondement en cas de litige."
    ),

    # ── 10 — Obligations de l'auteur ─────────────────────────────────────────
    "Livraison des masters dans les délais": (
        "L'artiste s'engage à vous livrer les fichiers audio dans le délai convenu. "
        "En cas de retard, vous pouvez réclamer des pénalités ou annuler la sortie."
    ),
    "Disponibilité promotionnelle": (
        "L'artiste s'engage à participer aux interviews, séances photo, tournées promo que vous organisez. "
        "S'il refuse sans raison valable, vous pouvez réduire vos efforts marketing en conséquence."
    ),
    "Respect des délais contractuels": (
        "L'artiste s'engage à respecter tous les délais du contrat (livraison, validation, réponses). "
        "Les retards peuvent coûter cher à tout le monde — et créer des tensions inutiles."
    ),
    "Absence de violation de droits tiers": (
        "L'artiste confirme que la musique lui appartient et n'utilise pas de samples non autorisés. "
        "Si un tiers le poursuit pour plagiat, c'est l'artiste qui en est responsable — pas vous."
    ),

    # ── 11 — Livraison technique ──────────────────────────────────────────────
    "Éléments à livrer": (
        "La liste exacte des fichiers que l'artiste doit vous remettre : WAV, MP3, pochette HD, paroles, stems… "
        "Évite les allers-retours et les malentendus sur ce qui doit vous être livré."
    ),
    "Formats et normes techniques": (
        "Les spécifications techniques des fichiers que vous attendez : qualité audio (24 bits / 44.1 kHz), "
        "loudness cible (–14 LUFS), taille de la pochette (3000×3000 px)…"
    ),
    "Délai de livraison": (
        "La date ou le délai (ex : 30 jours avant la sortie) dans lequel l'artiste doit vous remettre tous les fichiers. "
        "Un délai clair évite les surprises de dernière minute pour tout le monde."
    ),

    # ── 12 — Avances ──────────────────────────────────────────────────────────
    "Type d'avance": (
        "Une avance recoupable signifie que vous payez l'artiste à l'avance, "
        "mais que vous récupérez cette somme sur ses futurs revenus avant de lui verser des royalties."
    ),
    "Montant de l'avance (€)": (
        "La somme exacte que vous versez à l'artiste à la signature ou à la livraison. "
        "C'est de l'argent immédiat pour lui — mais vous le récupérerez sur ses royalties futures."
    ),
    "Conditions de versement": (
        "Quand et comment vous versez l'avance à l'artiste : à la signature, à la livraison, en plusieurs fois… "
        "Important à préciser pour éviter tout litige sur la date de paiement."
    ),

    # ── 13 — Royalties ────────────────────────────────────────────────────────
    "Mode de calcul": (
        "Comment est calculée la part de l'artiste : sur le prix de vente, sur ce que vous encaissez, ou sur les bénéfices nets. "
        "Le calcul 'sur net distributeur' est le plus courant mais aussi le plus difficile à vérifier pour l'artiste."
    ),
    "Taux — exploitation physique (%)": (
        "Le pourcentage que vous reversez à l'artiste pour chaque CD ou vinyle vendu. "
        "En général entre 8% et 20% du prix de gros selon la notoriété de l'artiste."
    ),
    "Taux — streaming (%)": (
        "Le pourcentage de vos recettes Spotify, Apple Music, Deezer… que vous reversez à l'artiste. "
        "Souvent entre 15% et 30% de vos recettes nettes de distributeur."
    ),
    "Taux — synchronisation (%)": (
        "La part de l'artiste quand vous placez sa musique dans un film, une pub, une série, un jeu vidéo. "
        "Les synchos peuvent rapporter beaucoup — l'artiste sera particulièrement attentif à ce taux."
    ),
    "Taux — YouTube / UGC (%)": (
        "La part de l'artiste sur les revenus que vous générez via YouTube Content ID et les vidéos d'utilisateurs. "
        "Ces revenus sont souvent sous-estimés mais peuvent être significatifs."
    ),
    "Bonus de performance": (
        "Des paiements supplémentaires que vous versez à l'artiste s'il dépasse certains objectifs (streams, ventes…). "
        "Un bon moyen d'aligner vos intérêts avec ceux de l'artiste."
    ),
    "Paliers de rémunération": (
        "Le taux de l'artiste augmente automatiquement quand certains seuils sont dépassés (ex : +2% au-delà d'1M de streams). "
        "Plus la musique marche, plus l'artiste touche — ce qui l'incite à s'investir dans la promotion."
    ),

    # ── 14 — Recoupement ─────────────────────────────────────────────────────
    "Recoupement prévu": (
        "Vous récupérez l'avance versée (et d'autres dépenses) sur les royalties de l'artiste avant de lui en verser. "
        "L'artiste ne perçoit des royalties qu'une fois ces dépenses 'remboursées' par les ventes."
    ),
    "Dépenses recoupables": (
        "La liste des dépenses que vous pouvez déduire des royalties de l'artiste : studio, promo, clips… "
        "L'artiste doit connaître et accepter précisément cette liste avant de signer."
    ),
    "Ordre et plafonds de recoupement": (
        "Dans quel ordre vous récupérez les dépenses, et jusqu'où (plafond global). "
        "Sans plafond, vous pourriez théoriquement récupérer sans limite sur les revenus de l'artiste."
    ),

    # ── 15 — Comptabilité et audit ────────────────────────────────────────────
    "Fréquence des relevés de comptes": (
        "À quelle fréquence vous transmettez à l'artiste un relevé de ce que sa musique a rapporté. "
        "Mensuel ou trimestriel permet à l'artiste de vérifier régulièrement qu'il est bien payé."
    ),
    "Conservation des données comptables (années)": (
        "Combien de temps vous devez conserver vos registres de ventes et de royalties. "
        "Important pour permettre à l'artiste de faire vérifier les comptes plusieurs années après."
    ),
    "Droit d'audit": (
        "L'artiste peut faire vérifier vos comptes par un comptable de son choix. "
        "C'est son principal outil pour détecter un éventuel sous-paiement — prévoyez-le avec des règles claires."
    ),
    "Procédure d'audit": (
        "Les règles pratiques pour que l'artiste réalise un audit : délai de préavis, fréquence maximale, qui paie le comptable… "
        "Des règles claires évitent que ce droit soit invoqué de façon abusive ou au contraire bloqué."
    ),

    # ── 16 — Garanties ────────────────────────────────────────────────────────
    "Garantie de titularité des droits": (
        "L'artiste confirme qu'il est bien propriétaire de la musique et qu'il peut légalement signer ce contrat. "
        "Si ce n'est pas le cas, c'est lui qui est personnellement responsable des problèmes qui en découlent."
    ),
    "Garantie d'originalité": (
        "L'artiste confirme que la musique est une création originale, pas copiée sur une autre œuvre. "
        "Si un tiers porte plainte pour plagiat, c'est l'artiste qui devra assumer la défense."
    ),
    "Absence de sample non autorisé": (
        "L'artiste confirme qu'aucun extrait d'une autre musique n'a été utilisé sans autorisation. "
        "Un sample non autorisé peut stopper une sortie et coûter très cher en dommages — pour l'artiste."
    ),
    "Obtention des autorisations nécessaires": (
        "L'artiste confirme avoir obtenu les accords écrits de toutes les personnes ayant contribué à la musique. "
        "Co-auteur, beatmaker, interprète invité — tous doivent avoir signé quelque chose."
    ),

    # ── 17 — Responsabilité ───────────────────────────────────────────────────
    "Limitation de responsabilité": (
        "Le montant maximum de dommages que l'une ou l'autre partie peut réclamer en cas de problème. "
        "Ça protège les deux parties contre des réclamations disproportionnées."
    ),
    "Prise en charge des litiges tiers": (
        "Si un tiers vous attaque à cause de la musique de l'artiste, c'est l'artiste qui assume sa défense. "
        "Et si une erreur de votre part crée un litige, c'est vous qui en êtes responsable."
    ),
    "Assurance": (
        "Vous devez disposer d'une assurance professionnelle couvrant les risques liés à l'exploitation de l'œuvre. "
        "Sans ça, si un problème survient, il se peut qu'il n'y ait pas de fonds pour indemniser l'artiste."
    ),

    # ── 18 — Droits moraux ────────────────────────────────────────────────────
    "Droit au crédit (mention obligatoire)": (
        "Le nom de l'artiste doit apparaître partout où sa musique est exploitée (plateformes, pochette, synchro…). "
        "C'est un droit inaliénable en France — mais mieux vaut l'écrire noir sur blanc dans le contrat."
    ),
    "Validation artistique requise": (
        "Vous devez obtenir l'accord écrit de l'artiste pour toute modification de son œuvre (remix, adaptation, usage en pub). "
        "Sans cette clause, vous pourriez modifier l'œuvre sans le consulter."
    ),
    "Autorisation d'adaptation": (
        "L'artiste vous autorise explicitement à créer des versions alternatives : remix, traduction, clip… "
        "Précisez qui garde les droits sur ces nouvelles versions."
    ),

    # ── 19 — Synchronisation ─────────────────────────────────────────────────
    "Publicité": (
        "Vous obtenez le droit de placer la musique de l'artiste dans des publicités (TV, web, affichage). "
        "Les synchos pub peuvent très bien payer — vérifiez l'image de la marque associée avec l'artiste."
    ),
    "Cinéma / Séries télévisées": (
        "Vous obtenez le droit de placer la musique de l'artiste dans des films, séries ou documentaires. "
        "Une bonne synchro peut donner à l'artiste une exposition massive — et vous rapporter un beau chèque."
    ),
    "Jeux vidéo": (
        "Vous obtenez le droit d'utiliser la musique de l'artiste dans des jeux vidéo. "
        "Les licences gaming peuvent être très lucratives, surtout pour des jeux à grand public."
    ),
    "Plateformes sociales (Reels, Shorts, TikTok)": (
        "Vous obtenez le droit de permettre aux utilisateurs d'intégrer la musique dans leurs vidéos sur TikTok, Instagram, YouTube Shorts. "
        "C'est souvent gratuit mais génère une visibilité massive pour l'artiste."
    ),
    "Trailers / Bande-annonces": (
        "Vous obtenez le droit d'utiliser la musique de l'artiste dans des bandes-annonces de films ou de jeux. "
        "Ce type de synchro est très visible et souvent bien rémunéré."
    ),
    "Podcasts": (
        "Vous obtenez le droit d'utiliser la musique de l'artiste comme fond sonore dans des podcasts. "
        "Précisez si c'est gratuit ou payant, et pour quelle durée d'utilisation maximale."
    ),
    "Livestreams": (
        "Vous obtenez le droit d'utiliser la musique de l'artiste dans des diffusions en direct (Twitch, YouTube Live…). "
        "Sujet sensible : une musique non couverte en live peut provoquer un blocage immédiat de la diffusion."
    ),
    "Précisions synchro": (
        "Des conditions supplémentaires pour vos utilisations en synchro : durée max de l'extrait, budget minimum de la production, types de marques exclus… "
        "Permet à l'artiste d'encadrer précisément ce qu'il vous autorise ou non."
    ),

    # ── 20 — Exploitation numérique ───────────────────────────────────────────
    "Plateformes DSP (Spotify, Apple Music...)": (
        "Vous obtenez le droit de distribuer la musique de l'artiste sur les grandes plateformes de streaming. "
        "C'est la base de toute exploitation numérique aujourd'hui."
    ),
    "YouTube Content ID": (
        "Vous enregistrez la musique de l'artiste dans le système de détection YouTube qui monétise toutes les vidéos qui l'utilisent. "
        "Tout créateur qui utilise cette musique sur YouTube génère automatiquement des revenus que vous redistribuez à l'artiste."
    ),
    "TikTok": (
        "Vous obtenez le droit de mettre la musique de l'artiste à disposition des utilisateurs de TikTok pour leurs vidéos. "
        "C'est souvent le meilleur levier de viralité pour un artiste aujourd'hui."
    ),
    "Meta (Instagram, Facebook Reels)": (
        "Vous obtenez le droit d'utiliser la musique sur Instagram Reels et Facebook. "
        "Meta verse des droits aux distributeurs qui ont un accord de licence avec eux."
    ),
    "Twitch": (
        "Vous obtenez le droit de diffuser la musique de l'artiste sur Twitch. "
        "Sans cet accord, la musique peut être coupée automatiquement par le système de détection de la plateforme."
    ),
    "IA générative — entraînement / clonage / synthèse": (
        "Vous définissez ici les conditions dans lesquelles vous pouvez utiliser la musique de l'artiste pour entraîner une IA, cloner sa voix ou créer des sons synthétiques. "
        "C'est le sujet le plus sensible du moment — à encadrer précisément même si ça semble lointain."
    ),
    "NFT / Blockchain": (
        "Vous définissez si vous pouvez créer des NFTs à partir de la musique de l'artiste, et sous quelles conditions. "
        "Précisez combien de tokens maximum, et quelle commission revient à l'artiste sur les reventes."
    ),
    "UGC / Remix utilisateurs": (
        "Vous obtenez le droit de permettre aux fans de remixer ou d'utiliser la musique de l'artiste dans leurs créations personnelles. "
        "À encadrer : usage non-commercial uniquement, mention du nom de l'artiste obligatoire."
    ),
    "Avatars virtuels / Métavers": (
        "Vous obtenez le droit d'utiliser la musique de l'artiste dans des expériences virtuelles (Roblox, Decentraland…). "
        "Un marché encore petit mais à encadrer maintenant pour éviter les conflits futurs."
    ),

    # ── 21 — Données ─────────────────────────────────────────────────────────
    "Gestion des identifiants (ISRC, ISWC, UPC)": (
        "Vous vous occupez d'enregistrer et de maintenir les codes officiels de la musique de l'artiste. "
        "Sans ces codes, les plateformes ne peuvent pas payer correctement l'artiste."
    ),
    "Reporting plateforme": (
        "Vous transmettez à l'artiste les données de performance par plateforme (streams, pays, revenus). "
        "Ces données permettent à l'artiste de vérifier que ses royalties correspondent bien aux écoutes réelles."
    ),
    "Collecte SACEM / droits voisins": (
        "Vous vous chargez de déclarer la musique à la SACEM et aux sociétés de droits voisins. "
        "Ça garantit que l'artiste perçoit ses droits d'auteur même quand il ne peut pas les suivre lui-même."
    ),
    "Matching Content ID": (
        "Vous associez la musique de l'artiste au bon profil dans les systèmes de détection automatique de YouTube. "
        "Sans ça, les revenus YouTube pourraient partir à quelqu'un d'autre par erreur."
    ),

    # ── 22 — Confidentialité ─────────────────────────────────────────────────
    "Clause de confidentialité": (
        "Ni vous ni l'artiste ne pouvez révéler les termes financiers de ce contrat à des tiers. "
        "Utile pour éviter que d'autres artistes ou concurrents connaissent les conditions que vous avez accordées."
    ),
    "Durée de confidentialité post-résiliation (années)": (
        "Même après la fin du contrat, les deux parties s'engagent à garder le secret pendant X années. "
        "Précisez cette durée pour ne pas vous retrouver lié indéfiniment."
    ),
    "Périmètre de la confidentialité": (
        "La liste exacte de ce qui est confidentiel : montants, taux, clauses spéciales… "
        "Ce qui n'est pas dans cette liste peut être partagé librement."
    ),

    # ── 23 — Communication & image ────────────────────────────────────────────
    "Droit d'utiliser le nom / image / voix": (
        "L'artiste vous autorise à utiliser son nom, sa photo et sa voix dans votre communication. "
        "Précisez les limites : pas de publicité pour des marques tierces sans l'accord séparé de l'artiste."
    ),
    "Biographie pour la presse": (
        "L'artiste vous fournit une biographie officielle (FR + EN) et des photos presse que vous pouvez utiliser librement. "
        "Ça vous permet de le promouvoir sans le solliciter pour chaque interview ou article."
    ),
    "Contenus réseaux sociaux": (
        "L'artiste vous autorise à publier du contenu le concernant sur vos réseaux (posts, stories, clips). "
        "Précisez ce que vous pouvez publier sans le demander, et ce qui nécessite sa validation préalable."
    ),

    # ── 24 — Force majeure ────────────────────────────────────────────────────
    "Clause de force majeure (standard)": (
        "Si un événement imprévisible et hors de votre contrôle (pandémie, catastrophe naturelle…) empêche d'exécuter le contrat, "
        "aucune des deux parties n'est en faute."
    ),
    "Événements couverts": (
        "La liste des situations considérées comme 'force majeure' dans ce contrat. "
        "Vérifiez que les événements pertinents pour votre secteur d'activité sont bien inclus."
    ),
    "Effets de la force majeure": (
        "Ce qui se passe concrètement : le contrat est suspendu, résilié, ou modifié ? "
        "Pendant combien de temps ? À clarifier pour éviter les interprétations opposées."
    ),

    # ── 25 — Résiliation ─────────────────────────────────────────────────────
    "Résiliation pour inexécution": (
        "Si l'une ou l'autre partie ne respecte pas ses obligations, l'autre peut mettre fin au contrat. "
        "Un préavis de mise en demeure est généralement requis avant de résilier."
    ),
    "Résiliation pour non-paiement": (
        "Si vous ne payez pas les royalties dans les délais, l'artiste peut résilier le contrat. "
        "C'est l'une des clauses les plus importantes pour protéger les revenus de l'artiste."
    ),
    "Résiliation pour faillite / liquidation": (
        "Si vous faites faillite, le contrat se termine automatiquement et les droits reviennent à l'artiste. "
        "Sans cette clause, les droits de l'artiste pourraient être bloqués dans la procédure de liquidation."
    ),
    "Résiliation pour absence d'exploitation": (
        "Si vous n'exploitez pas la musique pendant X mois sans raison valable, l'artiste peut récupérer ses droits. "
        "C'est la protection de l'artiste contre un blocage de ses droits sans contrepartie réelle de votre part."
    ),
    "Résiliation pour atteinte à l'image": (
        "Si vous faites quelque chose qui nuit à l'image ou à la réputation de l'artiste, il peut mettre fin au contrat. "
        "Très subjectif — précisez des exemples concrets pour éviter les disputes."
    ),
    "Résiliation pour violation d'exclusivité": (
        "Si vous violez une clause d'exclusivité prévue au contrat, l'artiste peut le résilier. "
        "Clause utile quand l'exclusivité est au cœur du deal."
    ),
    "Effets et délais de résiliation": (
        "Ce qui se passe après la résiliation : qui garde quoi, délai pour verser les derniers paiements… "
        "À clarifier pour que la séparation soit propre, pas une source de conflit supplémentaire."
    ),

    # ── 26 — Réversion des droits ────────────────────────────────────────────
    "Retour automatique des droits": (
        "À la fin du contrat, les droits reviennent automatiquement à l'artiste sans démarche de sa part. "
        "Indispensable pour qu'il n'ait pas à 'racheter' ce qui lui appartient déjà."
    ),
    "Récupération des masters": (
        "Si l'artiste vous a livré les fichiers audio originaux, précisez ici comment et quand vous les lui rendez. "
        "Les masters sont les actifs les plus précieux de l'artiste — il doit en récupérer les copies."
    ),
    "Conditions de réversion": (
        "Les conditions exactes pour que les droits reviennent à l'artiste : durée écoulée, seuils non atteints… "
        "Sans conditions claires, la réversion peut devenir une source de litige."
    ),

    # ── 27 — Cession et sous-licence ─────────────────────────────────────────
    "Cession du contrat autorisée": (
        "Vous pouvez transférer ce contrat à une autre société (ex : en cas de rachat de votre structure). "
        "L'artiste doit être informé et disposer d'un droit de résiliation s'il n'approuve pas le cessionnaire."
    ),
    "Sous-licence autorisée": (
        "Vous pouvez déléguer certains droits à un tiers (ex : un sous-distributeur régional). "
        "Mais vous restez responsable envers l'artiste même si c'est votre sous-traitant qui commet une erreur."
    ),
    "Vente de catalogue autorisée": (
        "Vous pouvez revendre ce contrat dans le cadre de la vente de votre catalogue musical. "
        "Prévoyez un droit de préemption pour l'artiste et un droit de résiliation s'il n'approuve pas l'acheteur."
    ),

    # ── 28 — Droit applicable ─────────────────────────────────────────────────
    "Droit applicable": (
        "La loi de quel pays s'applique à ce contrat en cas de litige. "
        "En France, le droit français est fortement protecteur pour les auteurs."
    ),
    "Tribunaux compétents": (
        "Quel tribunal traitera les litiges : tribunal judiciaire de Paris, tribunal de commerce… "
        "Préciser ça évite qu'une partie choisisse un tribunal étranger plus favorable pour elle."
    ),
    "Médiation préalable obligatoire": (
        "Avant d'aller en justice, les deux parties s'engagent à essayer de trouver un accord à l'amiable. "
        "La médiation est souvent plus rapide et bien moins coûteuse qu'un procès."
    ),
    "Clause d'arbitrage": (
        "Les litiges sont confiés à un arbitre privé plutôt qu'à un tribunal public. "
        "Plus rapide et confidentiel, mais souvent plus cher — à peser selon les enjeux financiers du contrat."
    ),

    # ── 29 — Notifications ────────────────────────────────────────────────────
    "Email contractuel du cessionnaire": (
        "L'adresse email officielle à utiliser pour toutes les communications importantes du contrat. "
        "Toute notification envoyée à cette adresse a valeur légale."
    ),
    "Modalités de notification": (
        "Comment envoyer les documents officiels : email avec accusé de réception, LRAR, et dans quel délai. "
        "Respecter ces modalités est essentiel pour que vos actions (résiliation, mise en demeure) soient valides juridiquement."
    ),

    # ── 30 — Clauses générales ────────────────────────────────────────────────
    "Divisibilité des clauses": (
        "Si un juge annule une clause, le reste du contrat reste valable. "
        "Sans cette clause, l'annulation d'une seule ligne pourrait invalider l'intégralité du contrat."
    ),
    "Intégralité du contrat": (
        "Ce contrat écrit remplace tous les accords verbaux ou emails échangés avant la signature. "
        "Ça évite qu'une promesse orale faite lors d'un déjeuner soit invoquée comme engagement contractuel."
    ),
    "Modification écrite obligatoire": (
        "Toute modification du contrat doit être faite par écrit et signée par les deux parties. "
        "Un simple SMS ou email de confirmation ne suffit pas — même si les deux parties sont d'accord."
    ),
    "Clause de non-renonciation": (
        "Si vous tolérez une violation une fois, ça ne signifie pas que vous l'acceptez pour l'avenir. "
        "Vous conservez le droit d'exiger le respect du contrat même si vous avez été souple une fois."
    ),
    "Survie des clauses": (
        "Certaines clauses continuent de s'appliquer même après la fin du contrat (confidentialité, garanties). "
        "Sans cette précision, tout s'arrête à la date de résiliation."
    ),
    "Ordre de priorité des annexes": (
        "Si le contrat principal et une annexe se contredisent, laquelle l'emporte ? "
        "Préciser l'ordre évite une bataille d'interprétation coûteuse."
    ),

    # ── 31 — Annexes ─────────────────────────────────────────────────────────
    "Liste des annexes": (
        "La liste officielle de tous les documents attachés au contrat : fiche technique, split sheet, barème de royalties… "
        "Tout document annexé fait partie intégrante du contrat et est aussi contraignant que lui."
    ),

    # ── 32 — Technologies émergentes ──────────────────────────────────────────
    "Entraînement de modèles d'IA": (
        "Vous définissez si vous pouvez utiliser la musique de l'artiste pour entraîner des systèmes d'intelligence artificielle. "
        "Une fois intégrée dans un modèle d'IA, il est très difficile de l'en retirer — à encadrer strictement."
    ),
    "Clonage vocal": (
        "Vous définissez si vous pouvez créer une version synthétique de la voix de l'artiste par IA. "
        "Si l'artiste accepte, la voix clonée doit être clairement identifiée comme artificielle, et la rémunération précisément définie."
    ),
    "Synthèse de voix / d'éléments musicaux": (
        "Des éléments de la musique de l'artiste (mélodie, rythme, timbre) peuvent être reproduits par une IA. "
        "Précisez que ces utilisations sont incluses dans le calcul des royalties de l'artiste."
    ),
    "Exploitation algorithmique": (
        "La musique de l'artiste est intégrée dans des playlists générées automatiquement par des algorithmes. "
        "Vous devez lui rapporter quelles playlists diffusent sa musique, car ça influe directement sur ses revenus."
    ),
    "Politique de compensation IA": (
        "Si vous exploitez les droits de l'artiste dans des contextes d'IA, définissez ici comment et selon quel barème vous le rémunérez. "
        "Un sujet en pleine évolution — prévoir une clause de révision annuelle est une bonne pratique."
    ),
}


def update_tooltips() -> int:
    """Patch tooltip_long on existing clauses that don't have one yet.

    Returns the number of clauses updated.
    """
    updated = 0
    for name, text in _TOOLTIPS_LONG.items():
        rows = (
            db.session.query(ContractClause)
            .filter(ContractClause.name == name, ContractClause.tooltip_long.is_(None))
            .all()
        )
        for row in rows:
            row.tooltip_long = text
            updated += 1
    db.session.commit()
    return updated


def update_plain_texts(force: bool = False) -> int:
    """Patch tooltip_plain on existing clauses.

    If force=True, overwrites existing values. Otherwise only fills nulls.
    Returns the number of clauses updated.
    """
    updated = 0
    for name, text in _PLAIN_TEXTS.items():
        q = db.session.query(ContractClause).filter(ContractClause.name == name)
        if not force:
            q = q.filter(ContractClause.tooltip_plain.is_(None))
        for row in q.all():
            row.tooltip_plain = text
            updated += 1
    db.session.commit()
    return updated
