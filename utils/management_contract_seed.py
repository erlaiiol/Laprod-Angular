"""
Seed data for the management contract builder (mandat de management artistique) :
add-on optionnel attachable à un RosterLink actif (producteur ↔ artiste) déjà noué
librement sur la plateforme.

Même architecture idempotente que utils/musical_performance_seed.py, mais les
groupes créés portent contract_type = 'management' afin de rester indépendants
des templates exploitation et performance.

Called by the `flask seed-management-contracts` CLI command in app.py.

Rappel juridique structurant — À NE JAMAIS PERDRE DE VUE EN MODIFIANT CE FICHIER :

Ce module génère un MANDAT DE MANAGEMENT (conseil, stratégie de carrière, mise en
réseau, coordination administrative), relevant du droit commun du mandat entre
entrepreneurs indépendants (art. 1984 et s. du Code civil). Il ne génère PAS et ne
doit JAMAIS servir de support à un contrat d'AGENT ARTISTIQUE.

L'activité d'agent artistique — mettre en rapport, à titre habituel et contre
rémunération, un artiste du spectacle avec un entrepreneur de spectacles vivants en
vue de la conclusion d'un contrat de travail — est une activité réglementée qui
nécessite une licence spécifique délivrée par l'autorité compétente (art. L.7121-9
et s. du Code du travail, régime issu de la loi n° 2011-893 du 26 juillet 2011). La
rémunération de l'agent y est en outre plafonnée par la réglementation. Exercer
cette activité sans licence est pénalement sanctionné.

La frontière entre les deux régimes n'est pas toujours nette en pratique : un
« manager » qui, au-delà du conseil, négocie et conclut lui-même des dates de
concert rémunérées pour le compte de l'artiste bascule dans le champ de l'agent
artistique. Ce fichier porte donc, sur les clauses structurantes (objet du mandat,
commission, indépendance des parties), des avertissements explicites — jamais des
affirmations catégoriques sur des seuils chiffrés que ce générateur ne peut garantir
à jour : en cas de doute, la clause renvoie systématiquement à un avocat spécialisé.
"""

from models import ContractClause, ContractClauseGroup, ClauseTypeEnum, ContractTemplateTypeEnum
from extensions import db


def run_seed(force: bool = False) -> int:
    """Insert or refresh all management contract groups and clauses.

    Idempotent, même logique que musical_performance_seed.run_seed() : sans
    --force, ne complète que les champs pédagogiques vides (tooltips, détail
    juridique, exemples) sans jamais écraser une retouche faite depuis l'admin.
    Avec force=True, les textes de ce fichier font autorité.

    Retourne le nombre de clauses créées ou mises à jour.
    """
    touched = 0

    content_fields = ('tooltip_short', 'tooltip_long', 'tooltip_plain',
                      'legal_reference', 'example_text')

    def _g(name, description=None, tooltip=None, sort_order=0):
        g = (
            db.session.query(ContractClauseGroup)
            .filter_by(name=name, contract_type=ContractTemplateTypeEnum.management)
            .first()
        )
        if g is None:
            g = ContractClauseGroup(
                name=name, description=description, tooltip=tooltip, sort_order=sort_order,
                contract_type=ContractTemplateTypeEnum.management,
            )
            db.session.add(g)
            db.session.flush()
            return g

        if force or g.description is None:
            g.description = description if force else (g.description or description)
        if force or g.tooltip is None:
            g.tooltip = tooltip if force else (g.tooltip or tooltip)
        return g

    def _c(group, name, ctype, tooltip_short=None, tooltip_long=None, plain=None,
           legal_ref=None, options=None, default_value=None,
           required=False, enabled_by_default=True, sort_order=0, example=None):
        nonlocal touched

        incoming = {
            'tooltip_short':   tooltip_short,
            'tooltip_long':    tooltip_long,
            'tooltip_plain':   plain,
            'legal_reference': legal_ref,
            'example_text':    example,
        }

        existing = (
            db.session.query(ContractClause)
            .filter_by(group_id=group.id, name=name)
            .first()
        )

        if existing is not None:
            changed = False
            for field in content_fields:
                new = incoming[field]
                if new is None:
                    continue
                if force or getattr(existing, field) is None:
                    if getattr(existing, field) != new:
                        setattr(existing, field, new)
                        changed = True
            if changed:
                touched += 1
            return

        db.session.add(ContractClause(
            group_id              = group.id,
            name                  = name,
            clause_type           = ClauseTypeEnum(ctype),
            tooltip_short         = tooltip_short,
            tooltip_long          = tooltip_long,
            tooltip_plain         = plain,
            legal_reference       = legal_ref,
            options               = options,
            default_value         = default_value,
            is_required           = required,
            is_enabled_by_default = enabled_by_default,
            sort_order            = sort_order,
            example_text          = example,
        ))
        touched += 1

    # ── 0 — Préambule ─────────────────────────────────────────────────────────
    g = _g("Préambule", tooltip="Contexte de la collaboration, qualité juridique de chacun, volonté commune.", sort_order=0)
    _c(g, "Contexte et volonté des parties", "textarea", sort_order=0,
       tooltip_short="Décrivez le contexte de la collaboration et l'intention commune des parties.",
       tooltip_long="Le préambule expose la volonté des parties et sert à interpréter le contrat en cas de "
                    "litige. Pour un mandat de management, il est utile d'y rappeler depuis quand la relation "
                    "existe (souvent informelle avant la signature) et le projet artistique visé.",
       plain="Quelques lignes qui expliquent qui vous êtes, depuis quand vous travaillez ensemble et pourquoi "
             "vous formalisez cet accord maintenant.",
       example=(
           "[Contractant 1], ci-après dénommé(e) « le Manager », et [Contractant 2], ci-après dénommé(e) "
           "« l'Artiste », collaborent depuis [date de début de collaboration] au développement du projet "
           "artistique de l'Artiste. Les parties, agissant chacune en qualité d'entrepreneur indépendant, ont "
           "convenu de formaliser les conditions de cette collaboration dans les stipulations qui suivent, "
           "dont elles déclarent accepter les termes sans réserve."
       ))
    _c(g, "Qualité d'indépendant des parties", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez le statut juridique de chaque partie (micro-entreprise, société, association).",
       tooltip_long="Utile pour la facturation de la commission (le Manager doit pouvoir émettre une facture) "
                    "et pour écarter tout risque de requalification en lien de subordination.",
       plain="Le statut sous lequel chacun facture : micro-entreprise, société, association loi 1901...",
       example=(
           "[Contractant 1] déclare exercer son activité de management sous le statut de [statut juridique — "
           "micro-entreprise, société, association], immatriculé sous le numéro [SIREN/SIRET]. [Contractant 2] "
           "déclare exercer son activité artistique sous le statut de [statut juridique], lui permettant de "
           "percevoir directement ses revenus et, le cas échéant, de reverser la commission prévue au présent "
           "mandat sans risque de requalification en salaire occulte."
       ))

    # ── 1 — Objet du mandat ───────────────────────────────────────────────────
    g = _g("Objet du mandat", tooltip="Nature, périmètre et limites du mandat de management confié.", sort_order=1)
    _c(g, "Nature du mandat", "select", sort_order=0, required=True,
       options=["Mandat non-exclusif", "Mandat exclusif"],
       tooltip_short="Le Manager est-il le seul interlocuteur autorisé de l'Artiste sur son périmètre ?",
       tooltip_long="Un mandat exclusif interdit à l'Artiste de confier le même périmètre à un autre manager "
                    "pendant la durée du contrat. Un mandat non-exclusif laisse l'Artiste libre de travailler "
                    "en parallèle avec d'autres interlocuteurs sur d'autres aspects de sa carrière.",
       plain="« Exclusif » : vous êtes le seul manager de l'artiste sur ce périmètre. « Non-exclusif » : "
             "l'artiste peut aussi travailler avec d'autres personnes en parallèle.")
    _c(g, "Périmètre du mandat", "multi_toggle", sort_order=1, required=True,
       options=["Conseil et stratégie de carrière", "Développement artistique", "Mise en réseau (labels, médias, partenaires)",
                "Coordination administrative", "Supervision de la promotion et de la communication",
                "Relecture et négociation de contrats d'exploitation (hors booking de spectacles)"],
       tooltip_short="Sur quels aspects de la carrière de l'Artiste porte le mandat ?",
       tooltip_long="Le périmètre ne doit volontairement PAS inclure la négociation ou la conclusion, à titre "
                    "habituel, de contrats d'engagement de spectacles rémunérés pour le compte de l'Artiste — "
                    "cette activité relève de l'agent artistique réglementé (voir clause suivante). Un mandat de "
                    "management porte sur le conseil et la coordination, pas sur le booking.",
       plain="Cochez ce sur quoi vous intervenez vraiment : conseil, réseau, coordination... "
             "Le booking de concerts (négocier et signer des dates rémunérées) n'en fait volontairement pas "
             "partie — voir l'avertissement juridique ci-dessous.")
    _c(g, "Limite de l'activité d'agent artistique", "toggle_with_details", sort_order=2, required=True,
       tooltip_short="Le Manager n'exerce PAS d'activité d'agent artistique réglementée dans le cadre de ce mandat.",
       tooltip_long="L'activité consistant à mettre en rapport, à titre habituel et contre rémunération, un "
                    "artiste avec un entrepreneur de spectacles en vue de la conclusion d'un contrat "
                    "d'engagement est réservée aux AGENTS ARTISTIQUES titulaires d'une licence (art. L.7121-9 "
                    "et s. du Code du travail, régime issu de la loi n° 2011-893 du 26 juillet 2011). La "
                    "rémunération de l'agent y est en outre plafonnée par la réglementation. Ce générateur "
                    "produit un mandat de management (conseil, stratégie), pas un contrat d'agent artistique : "
                    "si votre rôle réel consiste à négocier et conclure des dates de spectacle rémunérées pour "
                    "le compte de l'Artiste, consultez un avocat spécialisé avant de signer — ce document "
                    "n'est pas adapté à cette activité et ne vous couvre pas juridiquement pour l'exercer.",
       plain="Cette clause dit noir sur blanc que vous ne faites PAS le métier réglementé d'agent artistique "
             "(qui négocie des cachets de concert contre commission, avec une licence obligatoire). Si c'est "
             "pourtant ce que vous faites en réalité, ce contrat ne vous protège pas : voyez un avocat.",
       legal_ref="Art. L.7121-9 et s. C. trav.",
       example=(
           "Les parties reconnaissent expressément que le présent mandat porte sur des missions de conseil, de "
           "stratégie de carrière, de développement artistique et de coordination, à l'exclusion de toute "
           "activité de mise en rapport habituelle et rémunérée de l'Artiste avec des entrepreneurs de "
           "spectacles vivants en vue de la conclusion de contrats d'engagement, laquelle relève du régime "
           "réglementé de l'agent artistique (art. L.7121-9 et s. du Code du travail) et suppose une licence "
           "que le Manager ne détient pas dans le cadre du présent contrat."
       ))
    _c(g, "Finalité et description", "textarea", sort_order=3,
       tooltip_short="Décrivez concrètement les missions confiées au Manager pour ce projet artistique.",
       example=(
           "Le présent contrat a pour objet de définir les conditions dans lesquelles [Contractant 2] confie à "
           "[Contractant 1] une mission de management portant sur [périmètre du mandat], en vue du développement "
           "de sa carrière artistique, à compter du [début du mandat] et pour la durée précisée ci-après."
       ))

    # ── 2 — Durée et renouvellement ───────────────────────────────────────────
    g = _g("Durée et renouvellement", tooltip="Durée initiale du mandat et conditions de reconduction.", sort_order=2)
    _c(g, "Durée initiale", "duration", sort_order=0, required=True,
       tooltip_short="Durée totale de validité du mandat.",
       tooltip_long="Une durée initiale courte (6 à 12 mois) est un usage prudent pour un premier mandat entre "
                    "parties qui n'ont pas encore beaucoup travaillé ensemble : elle permet de valider la "
                    "collaboration avant de s'engager plus durablement.",
       plain="Combien de temps dure l'engagement avant qu'il faille le renouveler explicitement.")
    _c(g, "Date de prise d'effet", "date", sort_order=1, required=True,
       tooltip_short="Date à partir de laquelle le mandat prend effet.")
    _c(g, "Renouvellement tacite", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Le mandat se renouvelle-t-il automatiquement à échéance ?",
       tooltip_long="Précisez le délai de préavis pour s'opposer au renouvellement et la durée de chaque "
                    "reconduction. Un renouvellement tacite sans préavis clair est une source fréquente de "
                    "litige en fin de mandat.",
       plain="Si vous ne dites rien à l'échéance, le contrat repart-il automatiquement pour la même durée ? "
             "Précisez le délai pour s'y opposer.",
       example=(
           "À l'issue de la durée initiale prévue au présent mandat, celui-ci se renouvellera tacitement par "
           "périodes successives de [durée du mandat] aux mêmes conditions, sauf dénonciation expresse de l'une "
           "ou l'autre des parties notifiée par lettre recommandée avec accusé de réception au moins [nombre] "
           "jours avant l'échéance de la période en cours. À défaut de dénonciation dans ce délai, les parties "
           "seront réputées avoir consenti au renouvellement pour une période supplémentaire."
       ))
    _c(g, "Préavis de non-reconduction", "textarea", sort_order=3, enabled_by_default=False,
       tooltip_short="Délai dans lequel une partie doit notifier son intention de ne pas reconduire le mandat.",
       example=(
           "Chaque partie pourra s'opposer à la reconduction tacite du présent mandat en notifiant son intention "
           "à l'autre partie par lettre recommandée avec accusé de réception, au plus tard [nombre] jours avant "
           "le terme de la période en cours."
       ))

    # ── 3 — Commission ────────────────────────────────────────────────────────
    g = _g("Commission", tooltip="Rémunération du Manager, assiette de calcul et modalités de reversement.", sort_order=3)
    _c(g, "Taux de commission (%)", "percentage", sort_order=0, required=True,
       tooltip_short="Pourcentage prélevé par le Manager sur les revenus entrant dans l'assiette.",
       tooltip_long="Il n'existe pas de plafond légal pour un mandat de management de droit commun (contrairement "
                    "à l'agent artistique, dont la commission est plafonnée par la réglementation — voir la "
                    "clause « Limite de l'activité d'agent artistique »). L'usage du secteur pour un management "
                    "personnel se situe le plus souvent entre 10 % et 20 % selon le périmètre confié ; retenez "
                    "un taux cohérent avec l'étendue réelle des missions.",
       plain="Votre pourcentage sur ce que touche l'artiste. Il n'y a pas de plafond légal fixe pour un mandat "
             "de management (contrairement à l'agent artistique) — l'usage tourne autour de 10 à 20 %.",
       legal_ref="Art. 1984 et s. C. civ.")
    _c(g, "Assiette de la commission", "select", sort_order=1, required=True,
       options=["Revenus bruts", "Revenus nets (après frais de production/promotion)",
                "Revenus nets de commissions tierces (label, distributeur, agent booking)"],
       tooltip_short="Sur quels revenus la commission est-elle calculée ?",
       tooltip_long="L'assiette de calcul est l'un des points les plus litigieux des mandats de management. "
                    "« Net de commissions tierces » évite une double commission quand un agent booking ou un "
                    "label prélève déjà sa part sur le même revenu.",
       plain="Sur quoi se calcule votre pourcentage : le total brut encaissé par l'artiste, ou ce qui reste "
             "après déduction d'autres frais et commissions déjà prélevés en amont ?")
    _c(g, "Revenus inclus dans l'assiette", "multi_toggle", sort_order=2,
       options=["Cachets de concert", "Royalties d'exploitation (streaming, ventes)", "Synchronisations",
                "Partenariats et sponsoring", "Merchandising", "Autres revenus liés à la carrière de l'Artiste"],
       tooltip_short="Sur quels types de revenus la commission s'applique-t-elle ?",
       tooltip_long="Listez précisément les sources de revenus commissionnées : un mandat qui reste vague sur "
                    "ce point génère systématiquement des désaccords au moment du décompte.",
       plain="Cochez les types de revenus concernés par votre commission — cachets, streaming, sponsoring...")
    _c(g, "Modalités de reversement", "textarea", sort_order=3,
       tooltip_short="Qui encaisse en premier, délai de reversement, fréquence des comptes.",
       tooltip_long="Précisez si l'Artiste encaisse directement et reverse sa commission au Manager, ou si le "
                    "Manager encaisse pour le compte de l'Artiste et lui reverse le solde — cette dernière "
                    "option suppose une vigilance particulière (les fonds de l'Artiste ne doivent jamais être "
                    "confondus avec la trésorerie propre du Manager).",
       plain="Comment l'argent circule concrètement : qui reçoit le paiement en premier, et sous combien de "
             "temps l'autre partie reçoit sa part.",
       example=(
           "[Contractant 2] encaisse directement l'ensemble des revenus visés à l'article « Revenus inclus dans "
           "l'assiette » et reverse à [Contractant 1] la commission due dans un délai de [nombre] jours suivant "
           "leur encaissement effectif, accompagnée d'un relevé détaillant l'origine de chaque somme."
       ))
    _c(g, "Facturation de la commission", "toggle", sort_order=4, enabled_by_default=False,
       tooltip_short="Le Manager facture sa commission (TVA applicable selon son régime).",
       tooltip_long="Le Manager doit disposer d'un statut lui permettant de facturer (micro-entreprise, société) "
                    "pour percevoir sa commission ; à défaut, le versement peut être requalifié en salaire "
                    "occulte par l'administration fiscale ou sociale.",
       plain="Le manager émet une vraie facture pour sa commission, comme tout prestataire indépendant.")

    # ── 4 — Exclusivité territoriale ──────────────────────────────────────────
    g = _g("Exclusivité territoriale", tooltip="Limites géographiques de l'exclusivité, le cas échéant.", sort_order=4)
    _c(g, "Territoire du mandat", "territory", sort_order=0, enabled_by_default=False,
       options=["France", "Union européenne", "Monde entier", "Autre"],
       tooltip_short="Sur quel territoire l'exclusivité du mandat s'applique-t-elle ?",
       tooltip_long="Un mandat exclusif peut être limité géographiquement (ex. exclusif en France, libre à "
                    "l'international) : cela permet à l'Artiste de travailler avec un manager local sur "
                    "d'autres marchés sans violer l'exclusivité confiée au Manager principal.",
       plain="Si le mandat est exclusif, sur quel territoire ? Vous pouvez limiter l'exclusivité à la France "
             "et laisser l'artiste libre ailleurs.")
    _c(g, "Exceptions à l'exclusivité", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Relations professionnelles préexistantes exclues du périmètre exclusif.",
       example=(
           "Par dérogation à la clause d'exclusivité, [Contractant 2] se réserve le droit de poursuivre ses "
           "relations professionnelles antérieures au présent contrat avec [préciser], lesquelles ne sont pas "
           "soumises à la commission prévue au présent mandat."
       ))

    # ── 5 — Obligations du Manager ────────────────────────────────────────────
    g = _g("Obligations du Manager", sort_order=5)
    _c(g, "Compte-rendu périodique", "select", sort_order=0,
       options=["Mensuel", "Trimestriel", "Semestriel"],
       tooltip_short="À quelle fréquence le Manager rend-il compte de son activité à l'Artiste ?",
       tooltip_long="Le compte-rendu périodique (démarches effectuées, contacts pris, opportunités en cours) "
                    "est la contrepartie naturelle de la commission perçue : son absence est une source "
                    "fréquente de perte de confiance dans la relation.",
       plain="À quelle fréquence le manager fait le point sur ce qu'il a fait pour l'artiste.")
    _c(g, "Transparence sur les opportunités reçues", "toggle", sort_order=1,
       tooltip_short="Le Manager s'engage à transmettre à l'Artiste toute proposition reçue le concernant.",
       tooltip_long="Cette obligation évite qu'une opportunité intéressante soit écartée par le Manager sans "
                    "que l'Artiste en soit informé — un point de tension classique dans les mandats exclusifs.",
       plain="Le manager ne filtre pas les propositions à votre insu : tout ce qui vous concerne vous est "
             "transmis, même s'il pense que ce n'est pas intéressant.")
    _c(g, "Moyens mis en œuvre", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Décrivez les moyens concrets que le Manager s'engage à mobiliser (réseau, budget, temps).",
       tooltip_long="Un mandat de management est une obligation de moyens, pas de résultat : le Manager ne "
                    "garantit pas le succès de l'Artiste, mais peut s'engager sur des moyens vérifiables "
                    "(nombre de contacts pris, participation à des évènements professionnels, budget promo).",
       example=(
           "Le Manager s'engage à mobiliser, dans le cadre de son mandat, les moyens suivants : mise en relation "
           "avec au moins [nombre] contacts professionnels pertinents (labels, médias, partenaires) par [durée], "
           "participation aux principaux évènements professionnels du secteur (Midem, Primavera Pro ou "
           "équivalents), et disponibilité pour un point d'échange régulier avec l'Artiste selon la fréquence "
           "fixée à l'article Compte-rendu périodique. Ces engagements constituent une obligation de moyens et "
           "non de résultat : le Manager ne garantit pas le succès commercial ou artistique de l'Artiste."
       ))

    # ── 6 — Obligations de l'Artiste ──────────────────────────────────────────
    g = _g("Obligations de l'Artiste", sort_order=6)
    _c(g, "Disponibilité et bonne foi", "toggle", sort_order=0,
       tooltip_short="L'Artiste s'engage à collaborer de bonne foi avec le Manager et à rester joignable.",
       tooltip_long="Sans cette réciprocité, le Manager ne peut remplir sa mission : un Artiste injoignable ou "
                    "qui prend des engagements sans en informer le Manager rend le mandat inopérant.")
    _c(g, "Communication des opportunités reçues directement", "toggle", sort_order=1,
       tooltip_short="L'Artiste informe le Manager de toute proposition reçue directement, pour coordination.",
       tooltip_long="En mandat exclusif, cette obligation est le pendant logique de l'exclusivité concédée au "
                    "Manager : elle permet d'éviter les doublons ou les négociations parallèles incohérentes.")
    _c(g, "Respect de l'exclusivité", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="En cas de mandat exclusif, l'Artiste s'engage à ne pas confier le même périmètre à un tiers.",
       tooltip_long="Le manquement à l'exclusivité par l'Artiste (signature d'un mandat concurrent sur le même "
                    "périmètre) est en pratique la cause de résiliation la plus fréquente des mandats exclusifs.")

    # ── 7 — Révocation et résiliation ─────────────────────────────────────────
    g = _g("Révocation et résiliation", tooltip="Conditions de fin anticipée du mandat et devenir des affaires en cours.", sort_order=7)
    _c(g, "Résiliation pour inexécution", "toggle", sort_order=0, required=True,
       tooltip_short="Le mandat peut être résilié en cas de manquement grave non réparé après mise en demeure.",
       tooltip_long="La résiliation pour inexécution suppose un manquement suffisamment grave et une mise en "
                    "demeure préalable restée sans effet ; elle permet à la partie non défaillante de sortir "
                    "du mandat sans attendre une décision de justice, sous réserve du contrôle a posteriori du "
                    "juge.",
       legal_ref="Art. 1224 s. C. civ.",
       plain="Si l'autre partie ne respecte pas un engagement important, vous pouvez sortir du contrat après "
             "un avertissement écrit resté sans effet.")
    _c(g, "Révocation ad nutum du mandat", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="Le mandat civil est en principe révocable à tout moment par le mandant (l'Artiste).",
       tooltip_long="En droit commun du mandat, le mandant peut révoquer le mandataire à tout moment (art. 2004 "
                    "C. civ.), y compris sans faute de ce dernier — c'est une règle d'ordre public que les "
                    "parties ne peuvent pas totalement écarter, même en mandat « exclusif » et « irrévocable ». "
                    "Une clause d'indemnisation en cas de révocation anticipée sans motif reste possible et "
                    "recommandée pour sécuriser le Manager.",
       legal_ref="Art. 2004 C. civ.",
       plain="Même dans un mandat « exclusif », la loi permet à l'artiste de mettre fin au mandat à tout moment. "
             "Ce que vous pouvez négocier, c'est une indemnité si la rupture intervient sans motif et avant "
             "terme — pas empêcher la rupture elle-même.",
       example=(
           "En cas de révocation du mandat par [Contractant 2] avant son terme et en l'absence de manquement "
           "imputable à [Contractant 1], une indemnité égale à [montant / modalité de calcul] sera due à "
           "[Contractant 1] au titre des diligences accomplies et des affaires en cours."
       ))
    _c(g, "Clause de survie post-résiliation (affaires en cours)", "toggle_with_details", sort_order=2,
       tooltip_short="La commission reste due sur les affaires initiées pendant le mandat, même après sa fin.",
       tooltip_long="Cette clause dite « de queue » (tail clause) évite que l'Artiste mette fin au mandat juste "
                    "avant la conclusion d'une affaire initiée par le Manager pour échapper à la commission. "
                    "Limitez-la dans le temps et au périmètre des affaires réellement initiées avant la fin du "
                    "mandat, pour rester raisonnable et proportionnée.",
       plain="Si le manager a lancé une négociation avant la fin du contrat et qu'elle aboutit juste après, la "
             "commission reste due — sinon il suffirait de mettre fin au contrat au bon moment pour ne rien "
             "payer. Cette clause doit rester limitée dans le temps pour être équitable.",
       example=(
           "Pour les affaires dont les négociations ont été engagées par [Contractant 1] avant la date de fin du "
           "présent mandat et qui aboutissent dans les [nombre] mois suivant cette date, la commission prévue à "
           "l'article « Commission » reste due à [Contractant 1] dans les conditions habituelles."
       ))
    _c(g, "Clause de non-sollicitation", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Le Manager s'interdit de démarcher activement les contacts professionnels de l'Artiste après la fin du mandat.",
       tooltip_long="Cette clause protège le réseau professionnel constitué par l'Artiste pendant le mandat ; "
                    "elle doit rester limitée dans le temps et proportionnée pour ne pas s'apparenter à une "
                    "clause de non-concurrence déguisée et disproportionnée.",
       plain="Après la fin du contrat, le manager ne peut pas activement démarcher les contacts qu'il a "
             "connus grâce à vous, pendant une durée limitée.",
       example=(
           "Pendant une durée de [durée] à compter de la fin du présent mandat, quelle qu'en soit la cause, "
           "[Contractant 1] s'interdit de démarcher activement, pour son propre compte ou celui d'un tiers, les "
           "contacts professionnels (labels, partenaires, diffuseurs) dont il/elle a eu connaissance dans le "
           "cadre de l'exécution du présent mandat. Cette interdiction ne fait pas obstacle à la poursuite de "
           "relations professionnelles préexistantes au mandat ni à une sollicitation initiée spontanément par le "
           "contact concerné."
       ))

    # ── 8 — Confidentialité ───────────────────────────────────────────────────
    g = _g("Confidentialité", sort_order=8)
    _c(g, "Clause de confidentialité", "toggle", sort_order=0,
       tooltip_short="Les conditions financières du mandat et les informations échangées restent confidentielles.",
       tooltip_long="Les parties s'engagent à ne pas divulguer les conditions du mandat (taux de commission, "
                    "revenus, stratégie) à des tiers ; cette clause survit généralement à la fin du contrat.")
    _c(g, "Durée de confidentialité post-résiliation (années)", "number", sort_order=1, enabled_by_default=False,
       tooltip_short="Durée pendant laquelle la clause de confidentialité s'applique après la fin du mandat.",
       default_value={"number": 2})

    # ── 9 — Droit applicable et juridiction ───────────────────────────────────
    g = _g("Droit applicable et juridiction compétente", sort_order=9)
    _c(g, "Droit applicable", "select", sort_order=0, required=True,
       options=["Droit français", "Autre"],
       default_value={"selected": "Droit français"},
       tooltip_short="Quelle loi nationale régit ce mandat ?")
    _c(g, "Juridiction compétente", "text", sort_order=1, enabled_by_default=False,
       tooltip_short="Tribunal territorialement compétent en cas de litige.",
       tooltip_long="La clause attributive de compétence territoriale n'est valable qu'entre commerçants "
                    "(art. 48 CPC) : si l'une des parties est un particulier, les règles légales de compétence "
                    "s'appliquent malgré la clause.",
       default_value={"text": "Tribunaux de Paris"},
       example="ex : Tribunal judiciaire de Paris — clause inopposable si l'une des parties est un particulier non commerçant (art. 48 CPC)")
    _c(g, "Médiation préalable obligatoire", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="Les parties s'engagent à tenter une médiation avant toute action judiciaire.")

    # ── 10 — Notifications ────────────────────────────────────────────────────
    g = _g("Notifications", sort_order=10)
    _c(g, "Email de contact du Manager", "text", sort_order=0,
       tooltip_short="Adresse email officielle du Manager pour les notifications contractuelles.",
       example="ex : contact@nomdumanager.example — adresse effectivement surveillée, utilisée pour le calcul des délais de préavis et de notification")
    _c(g, "Email de contact de l'Artiste", "text", sort_order=1,
       tooltip_short="Adresse email officielle de l'Artiste pour les notifications contractuelles.",
       example="ex : contact@nomartiste.example")
    _c(g, "Modalités de notification", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Email pour le quotidien, lettre recommandée pour les notifications graves.",
       example=(
           "Toute notification courante sera valablement effectuée par courrier électronique aux adresses "
           "désignées ci-dessus. Les notifications relatives à la révocation, à la résiliation ou à une mise en "
           "demeure devront être doublées d'une lettre recommandée avec accusé de réception."
       ))

    # ── 11 — Clauses générales ────────────────────────────────────────────────
    g = _g("Clauses générales", sort_order=11)
    _c(g, "Intégralité de l'accord", "toggle", sort_order=0,
       tooltip_short="Le contrat et ses annexes constituent l'intégralité de l'accord entre les parties.")
    _c(g, "Modification écrite", "toggle", sort_order=1,
       tooltip_short="Toute modification du mandat requiert un avenant écrit signé des deux parties.")
    _c(g, "Divisibilité", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="La nullité d'une clause n'affecte pas la validité des autres.",
       legal_ref="Art. 1184 C. civ.")
    _c(g, "Indépendance des parties", "toggle", sort_order=3, required=True,
       tooltip_short="Le mandat ne crée ni lien de subordination, ni société entre le Manager et l'Artiste.",
       tooltip_long="Clause déclarative utile mais non suffisante : en cas de litige, le juge requalifie selon "
                    "les conditions réelles d'exécution (faisceau d'indices : directives, horaires imposés, "
                    "intégration à un service organisé). De la même façon, l'écrire ne suffit pas non plus à "
                    "écarter une requalification en agent artistique si l'activité réellement exercée en relève "
                    "— voir la clause « Limite de l'activité d'agent artistique ».",
       plain="Cette clause rappelle que ni l'artiste n'est salarié du manager, ni l'inverse. Attention : "
             "l'écrire ne suffit pas — c'est la réalité de la relation qui compte pour un juge.")

    # ── 12 — Annexes ──────────────────────────────────────────────────────────
    g = _g("Annexes", tooltip="Documents annexés faisant partie intégrante du mandat.", sort_order=12)
    _c(g, "Liste des annexes", "textarea", sort_order=0, enabled_by_default=False,
       tooltip_short="Feuille de route, budget prévisionnel, calendrier de développement, mandats de représentation ponctuels...",
       plain="La liste des documents joints au contrat (feuille de route, budget...) qui comptent autant que le "
             "contrat principal.",
       example=(
           "Font partie intégrante du présent mandat les annexes suivantes, datées et paraphées par les parties : "
           "Annexe 1 — Feuille de route et objectifs de développement artistique ; Annexe 2 — Budget prévisionnel "
           "des actions de management ; Annexe 3 — Calendrier prévisionnel de développement ; Annexe 4 — Liste des "
           "contacts professionnels préexistants exclus de la commission, le cas échéant."
       ))

    db.session.commit()
    return touched
