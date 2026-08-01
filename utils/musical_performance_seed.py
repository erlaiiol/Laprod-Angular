"""
Seed data for the musical performance contract builder (contrat de représentation /
restitution publique d'œuvre musicale) : concert, showcase, festival, DJ set, live PA,
première partie, résidence, évènement privé ou d'entreprise, prestation en ERP.

Même architecture que utils/contract_builder_seed.py, mais les groupes créés portent
contract_type = 'performance' afin de rester indépendants du template exploitation.

Called by the `flask seed-performance-contracts` CLI command in app.py.

Rappel juridique structurant : ce module génère des contrats de REPRÉSENTATION
(entre un producteur/artiste entrepreneur de spectacles et un organisateur), à ne pas
confondre avec le contrat de travail d'artiste salarié (présomption de salariat de
l'art. L7121-3 du Code du travail). Les tooltips et l'UI portent cet avertissement.
"""

from models import ContractClause, ContractClauseGroup, ClauseTypeEnum, ContractTemplateTypeEnum
from extensions import db


def run_seed(force: bool = False) -> int:
    """Insert or refresh all performance contract groups and clauses.

    Idempotent : les groupes et clauses sont créés s'ils n'existent pas, et complétés
    s'ils existent déjà. C'est indispensable, car les bases peuplées par une version
    antérieure de ce fichier contiennent les clauses mais pas leurs textes pédagogiques
    (« en clair », détail juridique, exemples) — un simple garde-fou « existe déjà →
    on sort » les laissait définitivement vides.

    Par défaut, seuls les champs vides (NULL) sont complétés : les textes retouchés à la
    main depuis l'admin ne sont jamais écrasés. Avec force=True, les textes de ce fichier
    font autorité et remplacent les valeurs en base.

    Retourne le nombre de clauses créées ou mises à jour.
    """
    touched = 0

    # Champs pédagogiques : les seuls que le backfill complète sur une clause existante.
    # Les champs structurels (type, obligatoire, ordre, valeur par défaut) sont laissés
    # tels quels sur une clause déjà en base : ils peuvent avoir été ajustés via l'admin.
    content_fields = ('tooltip_short', 'tooltip_long', 'tooltip_plain',
                      'legal_reference', 'example_text')

    def _g(name, description=None, tooltip=None, sort_order=0):
        g = (
            db.session.query(ContractClauseGroup)
            .filter_by(name=name, contract_type=ContractTemplateTypeEnum.performance)
            .first()
        )
        if g is None:
            g = ContractClauseGroup(
                name=name, description=description, tooltip=tooltip, sort_order=sort_order,
                contract_type=ContractTemplateTypeEnum.performance,
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
    g = _g("Préambule", tooltip="Contexte de l'évènement, volonté des parties, qualité juridique de chacun.", sort_order=0)
    _c(g, "Contexte et volonté des parties", "textarea", sort_order=0,
       tooltip_short="Décrivez l'évènement, la qualité des parties et leur volonté commune.",
       tooltip_long="Le préambule expose la volonté des parties et sert à interpréter le contrat en cas de litige. "
                    "Pour un contrat de représentation, il est essentiel d'y préciser que chaque partie agit en qualité "
                    "d'entrepreneur indépendant : l'artiste (ou son producteur) fournit un spectacle « clé en main », "
                    "l'organisateur en assure l'accueil et l'exploitation.",
       plain="Quelques lignes qui expliquent qui organise quoi, où, et pourquoi vous signez ce contrat. "
             "Ce n'est pas la partie la plus « juridique », mais elle aide à comprendre le reste.",
       example=(
           "[Contractant 2], en qualité de [Rôle 2], ci-après dénommé(e) « l'Organisateur », organise "
           "l'évènement [l'Évènement] le [date de l'évènement] au [lieu]. "
           "[Contractant 1], en qualité de [Rôle 1], ci-après dénommé(e) « l'Artiste », dispose du répertoire "
           "et des moyens artistiques nécessaires à la représentation objet du présent contrat. "
           "Les parties, agissant chacune en qualité d'entrepreneur indépendant, ont convenu de formaliser "
           "les conditions de la représentation publique dans les stipulations qui suivent, dont elles "
           "déclarent accepter les termes sans réserve."
       ))
    _c(g, "Qualité d'entrepreneur de spectacles des parties", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Précisez les récépissés de déclaration d'entrepreneur de spectacles vivants de chaque partie.",
       tooltip_long="Depuis octobre 2019, la licence d'entrepreneur de spectacles est remplacée par un récépissé de "
                    "déclaration valable 5 ans. L'organisateur qui n'exerce pas à titre principal peut organiser jusqu'à "
                    "6 représentations par an sans déclaration (organisateur occasionnel, dispositif GUSO le cas échéant).",
       plain="Si vous êtes un professionnel du spectacle, indiquez ici vos numéros de déclaration (ex-licences). "
             "Un organisateur occasionnel (moins de 7 dates par an) n'en a pas besoin.",
       legal_ref="Art. L7122-1 s. Code du travail",
       example=(
           "[Contractant 1] déclare être titulaire du récépissé de déclaration d'entrepreneur de spectacles vivants "
           "n° [numéro], en cours de validité. [Contractant 2] déclare être titulaire du récépissé n° [numéro] "
           "(ou, le cas échéant, agir en qualité d'organisateur occasionnel au sens de l'article L7122-19 du Code du travail)."
       ))

    # ── 1 — Définitions ───────────────────────────────────────────────────────
    g = _g("Définitions contractuelles", tooltip="Termes clés du contrat de représentation, définis pour éviter toute ambiguïté.", sort_order=1)
    _c(g, "Glossaire des termes", "textarea", sort_order=0, enabled_by_default=False,
       tooltip_short="Définissez : Spectacle, Représentation, Plateau, Balances, Backline, Jauge, Recettes...",
       tooltip_long="Les définitions évitent les divergences d'interprétation. En spectacle vivant, « Recettes brutes » "
                    "vs « Recettes nettes » (après TVA, SACEM, frais de billetterie) est la source de litige la plus "
                    "fréquente dans les accords de partage : définissez-les précisément.",
       plain="Un petit lexique du contrat. Surtout utile si vous partagez les recettes : "
             "précisez bien ce qu'on entend par « recettes » (avant ou après frais ?).",
       example=(
           "Aux fins du présent contrat : « le Spectacle » désigne la prestation musicale de [Contractant 1] décrite "
           "en annexe ; « la Représentation » désigne l'exécution publique du Spectacle le [date de l'évènement] au [lieu] ; "
           "« la Jauge » désigne la capacité d'accueil du lieu, soit [jauge] personnes ; « les Recettes nettes » désignent "
           "les recettes de billetterie effectivement encaissées, déduction faite de la TVA, des droits d'auteur (SACEM), "
           "de la rémunération équitable (SPRE) et des frais de billetterie justifiés."
       ))

    # ── 2 — Objet du contrat ──────────────────────────────────────────────────
    g = _g("Objet du contrat", tooltip="Nature juridique du contrat et type d'évènement concerné.", sort_order=2)
    _c(g, "Type d'évènement", "select", sort_order=0, required=True,
       options=["Concert", "Showcase promotionnel", "Festival", "Première partie", "DJ Set",
                "Live PA / Performance électronique", "Performance scénique", "Résidence avec restitution publique",
                "Évènement privé", "Évènement d'entreprise", "Prestation en établissement recevant du public (ERP)",
                "Cérémonie / Mariage", "Autre"],
       tooltip_short="Quel type de représentation publique fait l'objet du contrat ?",
       tooltip_long="Le type d'évènement conditionne les clauses activées par défaut dans les modèles proposés "
                    "(quick-start) : un DJ set n'active pas les clauses musiciens/backline, un festival active "
                    "les accréditations et la clause de rayon. Ce choix n'a pas de valeur juridique en soi mais "
                    "structure la suite du contrat.",
       plain="Choisissez le format de l'évènement : le reste du contrat s'adapte "
             "(un DJ set n'a pas les mêmes clauses techniques qu'un festival).")
    _c(g, "Nature juridique", "select", sort_order=1, required=True,
       options=["Contrat de cession du droit d'exploitation d'un spectacle", "Contrat de coréalisation",
                "Contrat de prestation de service artistique", "Contrat de location de salle inversée (premier accueil)"],
       tooltip_short="Cession de spectacle, coréalisation ou simple prestation de service ?",
       tooltip_long="Dans la cession, l'organisateur achète le spectacle « clé en main » contre un prix fixe : le producteur "
                    "reste l'employeur des artistes. Dans la coréalisation, producteur et organisateur partagent les recettes "
                    "et les risques. La prestation de service vise les cas où l'artiste, entrepreneur indépendant "
                    "(auto-entrepreneur, société), vend directement sa prestation — attention à la présomption de salariat.",
       plain="« Cession » = l'organisateur achète le spectacle à prix fixe. « Coréalisation » = on partage les recettes. "
             "« Prestation de service » = l'artiste indépendant facture sa prestation.",
       legal_ref="Art. L7121-3 C. trav. ; Art. 1710 C. civ.")
    _c(g, "Finalité et description", "textarea", sort_order=2,
       tooltip_short="Décrivez précisément l'objet du contrat : qui fournit quoi, pour quel évènement.",
       tooltip_long="L'objet du contrat doit être déterminé ou déterminable (art. 1163 Code civil). Une description "
                    "précise limite les risques de litige sur l'étendue de la prestation attendue et sert de référence "
                    "en cas de désaccord sur ce qui avait été convenu.",
       plain="Le paragraphe qui résume tout : qui joue, où, quand, pour qui.",
       example=(
           "Le présent contrat a pour objet de définir les conditions dans lesquelles [Contractant 1], en qualité de "
           "[Rôle 1], s'engage à assurer la représentation publique de sa prestation musicale dans le cadre de "
           "[l'Évènement], organisé par [Contractant 2] le [date de l'évènement] au [lieu], [adresse du lieu]. "
           "La prestation, d'une durée d'environ [durée de la prestation], sera exécutée dans les conditions "
           "artistiques, techniques et financières définies aux articles suivants."
       ))

    # ── 3 — L'évènement ───────────────────────────────────────────────────────
    g = _g("L'évènement", tooltip="Identification précise de l'évènement : date, lieu, jauge, configuration.", sort_order=3)
    _c(g, "Nom de l'évènement", "text", sort_order=0, required=True,
       tooltip_short="Nom commercial de l'évènement ou de la soirée.",
       tooltip_long="Le nom exact de l'évènement sert de référence dans toutes les clauses (SACEM, assurance, "
                    "communication) et doit correspondre à celui utilisé sur les supports de promotion et la billetterie.",
       plain="Le nom affiché sur l'affiche et les billets. Utilisez toujours le même partout (contrat, facture, promo).",
       example="[l'Évènement]")
    _c(g, "Date de la représentation", "date", sort_order=1, required=True,
       tooltip_short="Date de la représentation publique.",
       tooltip_long="La date fixe le point de départ des délais contractuels (préavis d'annulation, paiement du solde, "
                    "clause de rayon). En cas de tournée, chaque date doit faire l'objet d'un contrat distinct ou d'une "
                    "annexe datée séparément.",
       plain="La date du concert. Pour plusieurs dates, utilisez la clause « Nombre de représentations » ou une annexe de tournée.")
    _c(g, "Lieu et adresse", "textarea", sort_order=2, required=True,
       tooltip_short="Nom de la salle / du site et adresse complète.",
       tooltip_long="L'adresse précise détermine la juridiction territorialement compétente à défaut de clause "
                    "attributive et sert de référence pour les autorisations administratives et l'assurance du lieu.",
       plain="Le nom et l'adresse complète du lieu. Utile aussi pour le GPS de l'équipe et les livreurs de matériel.",
       example="[lieu], [adresse du lieu] — [précisez la configuration : debout, assis, plein air...]")
    _c(g, "Nombre de représentations", "number", sort_order=3, enabled_by_default=False,
       tooltip_short="Nombre de représentations couvertes par le contrat (résidences, festivals multi-jours).",
       tooltip_long="Si un même contrat couvre plusieurs dates (résidence, plusieurs soirs de festival), précisez le "
                    "nombre exact et si la rémunération est due par date ou de manière forfaitaire : à défaut de précision, "
                    "l'usage est un cachet par représentation.",
       plain="À activer seulement si l'artiste joue plusieurs fois (sinon, une seule représentation est présumée).")
    _c(g, "Jauge du lieu", "number", sort_order=4, enabled_by_default=False,
       tooltip_short="Capacité d'accueil du lieu (nombre de spectateurs).",
       tooltip_long="La jauge conditionne la sécurité (ERP), le montant des droits SACEM et sert de référence dans les "
                    "clauses de partage de recettes. Pour un lieu en plein air, indiquez la jauge autorisée par arrêté.",
       plain="Le nombre de places du lieu. Sert de référence si vous avez un partage de recettes ou un minimum garanti.")
    _c(g, "Représentation en plein air", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="L'évènement se déroule-t-il en extérieur ? Précisez le dispositif de repli.",
       tooltip_long="Un évènement en plein air appelle des clauses spécifiques : jauge soumise à arrêté préfectoral, "
                    "solution de repli en cas d'intempéries (voir l'article dédié) et protection du matériel scénique "
                    "et technique contre les éléments.",
       plain="En extérieur, prévoyez toujours un plan B météo : repli en intérieur, report ou annulation — "
             "et qui paie quoi dans chaque cas (voir l'article Annulation).",
       example=(
           "La Représentation se déroulant en plein air, l'Organisateur s'engage à fournir une scène couverte et des "
           "protections adaptées pour le matériel. En cas d'intempéries rendant la Représentation impossible ou dangereuse, "
           "les stipulations de l'article « Annulation et report » s'appliquent."
       ))
    _c(g, "Accès, parking et logistique du site", "textarea", sort_order=6, enabled_by_default=False,
       tooltip_short="Modalités d'accès au site : parking, quai de déchargement, horaires d'accès.",
       tooltip_long="Une logistique d'accès mal anticipée (stationnement interdit, accès livraison fermé, horaires "
                    "restrictifs) est une cause fréquente de retard aux balances : cette clause sécurise le déroulement "
                    "de la journée avant même la prestation artistique.",
       plain="Où se garer, où décharger le matériel, à quelle heure on peut arriver. À préciser surtout en centre-ville "
             "ou dans les lieux avec accès restreint.",
       example=(
           "L'Organisateur garantit à [Contractant 1] et à son équipe un accès au lieu à compter de [heure], un "
           "emplacement de stationnement pour [nombre] véhicule(s) à proximité immédiate de l'accès artistes, ainsi "
           "que l'assistance d'une personne référente pour le déchargement du matériel."
       ))

    # ── 4 — Prestation artistique ─────────────────────────────────────────────
    g = _g("Prestation artistique", tooltip="Contenu et déroulé de la prestation : durée, horaires, effectif, répertoire.", sort_order=4)
    _c(g, "Durée de la prestation", "text", sort_order=0, required=True,
       tooltip_short="Durée du set / de la représentation (ex : 90 minutes).",
       tooltip_long="La durée contractuelle sert de référence en cas de litige sur l'exécution de la prestation : "
                    "un set significativement écourté sans motif légitime peut justifier une réduction du cachet "
                    "proportionnelle, ou l'inverse si l'organisateur impose un dépassement non prévu.",
       plain="Combien de temps dure votre prestation. Précisez si les rappels sont inclus dans ce temps ou en plus.",
       example="[durée de la prestation]")
    _c(g, "Horaire de passage", "text", sort_order=1,
       tooltip_short="Heure prévue de début de la prestation.",
       tooltip_long="L'horaire de passage a une valeur contractuelle propre en festival ou plateau multi-artistes : "
                    "un changement d'horaire unilatéral par l'organisateur (déclassement, tête d'affiche → première "
                    "partie) peut constituer un manquement justifiant une renégociation du cachet.",
       plain="En festival, l'horaire de passage a une vraie valeur : un déclassement (passage plus tôt, scène secondaire) "
             "peut justifier une renégociation. Précisez-le.",
       example="[heure de passage]")
    _c(g, "Balances / Soundcheck", "toggle_with_details", sort_order=2,
       tooltip_short="Horaire et durée des balances, présence du personnel technique.",
       tooltip_long="Les balances conditionnent la qualité sonore de la prestation : leur absence ou leur réduction "
                    "non convenue par l'organisateur peut engager sa responsabilité si la prestation en pâtit "
                    "techniquement.",
       plain="Le créneau réservé pour tester le son avant le concert. Sans balances correctes, la prestation risque "
             "d'être moins bonne — c'est donc à sécuriser dans le contrat, pas à négocier le jour J.",
       example=(
           "L'Organisateur garantit à [Contractant 1] un accès au plateau pour les balances le [date de l'évènement] "
           "à [heure de balance], pour une durée minimale de [durée] en présence du régisseur son et lumière du lieu. "
           "Le système de diffusion sera opérationnel et conforme à la fiche technique annexée."
       ))
    _c(g, "Effectif et line-up", "textarea", sort_order=3,
       tooltip_short="Composition de l'équipe artistique et technique en tournée (musiciens, techniciens, accompagnants).",
       tooltip_long="L'effectif déclaré engage l'organisateur sur le nombre de repas, chambres et accréditations à "
                    "fournir : toute variation substantielle et tardive peut justifier un ajustement des défraiements "
                    "ou, à l'inverse, un refus légitime de l'organisateur si elle n'a pas été notifiée à temps.",
       plain="Listez qui monte sur scène et qui accompagne (ingé son, tour manager…). "
             "C'est cette liste qui sert pour les accréditations, les repas et l'hébergement.",
       example=(
           "La prestation sera exécutée par [Contractant 1] accompagné(e) de [nombre] musicien(s) et de [nombre] "
           "technicien(s), soit une équipe totale de [nombre] personnes. Toute modification substantielle du line-up "
           "devra être notifiée à l'Organisateur au moins [nombre] jours avant la Représentation."
       ))
    _c(g, "Répertoire / programme", "textarea", sort_order=4, enabled_by_default=False,
       tooltip_short="Répertoire ou programme indicatif de la représentation.",
       tooltip_long="L'artiste conserve en principe la maîtrise artistique de son répertoire. Une exigence de setlist "
                    "imposée par l'organisateur, combinée à d'autres directives, peut être un indice de subordination "
                    "(risque de requalification en contrat de travail).",
       plain="À titre indicatif seulement : le programme peut évoluer, l'artiste garde la main sur son répertoire. "
             "Si l'organisateur impose vraiment la setlist, ça ressemble davantage à du salariat.",
       example=(
           "La Représentation sera exécutée selon le répertoire habituel de [Contractant 1], communiqué à titre "
           "indicatif à l'Organisateur au moins [nombre] jours avant [l'Évènement]. [Contractant 1] conserve la "
           "maîtrise artistique de son répertoire et de sa setlist, laquelle pourra évoluer jusqu'au jour de la "
           "Représentation selon le contexte scénique. Toute demande particulière de l'Organisateur (morceau "
           "imposé, retrait d'un titre) sera soumise à l'accord de [Contractant 1] et ne saurait lui être imposée "
           "unilatéralement."
       ))
    _c(g, "Exclusivité le jour de l'évènement", "toggle", sort_order=5, enabled_by_default=False,
       tooltip_short="L'artiste s'interdit toute autre prestation publique le même jour.",
       tooltip_long="Cette clause protège l'organisateur contre une prestation concurrente le même soir dans un lieu "
                    "proche, qui diluerait le public. Elle doit rester raisonnable dans son périmètre pour ne pas être "
                    "jugée abusive.",
       plain="Empêche l'artiste de jouer ailleurs le même soir. Standard pour un concert payant, "
             "inutile pour un DJ résident multi-clubs — à négocier.")
    _c(g, "Première partie / autres artistes", "toggle_with_details", sort_order=6, enabled_by_default=False,
       tooltip_short="Présence d'une première partie ou d'autres artistes à l'affiche : ordre de passage, validation.",
       tooltip_long="En plateau multi-artistes, l'ordre de passage et la place sur l'affiche ont une valeur "
                    "contractuelle : un artiste programmé en tête d'affiche qui se retrouve relégué sans accord peut "
                    "invoquer un manquement de l'organisateur.",
       plain="Précisez si d'autres artistes jouent le même soir et dans quel ordre — surtout si vous êtes tête "
             "d'affiche, pour éviter d'être « rétrogradé » sans votre accord.",
       example=(
           "L'Organisateur informera [Contractant 1] de l'identité des autres artistes programmés le même soir. "
           "[Contractant 1] se produira en tête d'affiche ; l'ordre de passage ne pourra être modifié sans son accord écrit."
       ))
    _c(g, "Interdiction de se faire remplacer", "toggle", sort_order=7,
       tooltip_short="La prestation est conclue intuitu personae : l'artiste ne peut se faire remplacer.",
       tooltip_long="Le contrat conclu intuitu personae (en considération de la personne) ne peut être exécuté par un "
                    "tiers sans l'accord de l'organisateur : c'est l'artiste nommément désigné qui est attendu sur scène, "
                    "pas un remplaçant de son choix.",
       legal_ref="Art. 1216 C. civ.",
       plain="Le contrat est conclu avec CET artiste précis : pas de remplaçant sans accord de l'organisateur.")

    # ── 5 — Rémunération ──────────────────────────────────────────────────────
    g = _g("Rémunération", tooltip="Cachet, partage de recettes, minimum garanti, modalités de paiement.", sort_order=5)
    _c(g, "Formule de rémunération", "select", sort_order=0, required=True,
       options=["Cachet fixe", "Partage des recettes de billetterie", "Minimum garanti + partage des recettes",
                "Cachet fixe + intéressement au-delà d'un seuil", "Prestation à titre gracieux (défraiements uniquement)"],
       tooltip_short="Comment l'artiste est-il rémunéré ?",
       tooltip_long="Les quatre modèles usuels du secteur : cachet fixe (cession classique) ; partage de recettes "
                    "(coréalisation, souvent 60/40 ou 70/30 au profit du producteur) ; minimum garanti + partage "
                    "(l'organisateur garantit un plancher, l'artiste touche le partage s'il est supérieur) ; "
                    "cachet + intéressement au-delà d'un seuil de recettes (sold-out bonus).",
       plain="« Cachet fixe » : montant connu d'avance, c'est l'organisateur qui prend le risque. "
             "« Partage » : vous touchez un % de la billetterie. « Minimum garanti + partage » : le meilleur des deux — "
             "un plancher assuré, plus si la billetterie marche.")
    _c(g, "Montant du cachet / prix de cession (€ HT)", "number", sort_order=1,
       tooltip_short="Montant en euros hors taxes du cachet ou du prix de cession du spectacle.",
       tooltip_long="ATTENTION — présomption de salariat : l'artiste du spectacle qui se produit contre rémunération est "
                    "présumé salarié (art. L7121-3 C. trav.), sauf s'il exerce en qualité d'entrepreneur de spectacles "
                    "inscrit ou dans des conditions d'indépendance établies. Si l'artiste n'est ni producteur de son propre "
                    "spectacle ni immatriculé, l'organisateur doit l'employer (GUSO pour les organisateurs occasionnels) "
                    "et non lui « acheter une prestation ».",
       plain="Le prix. Si l'artiste n'a pas de structure (société, association, micro-entreprise de spectacle), "
             "un simple virement ne suffit pas : il faut passer par un contrat d'engagement (salaire + GUSO). "
             "Ce générateur produit un contrat entre entrepreneurs indépendants.",
       legal_ref="Art. L7121-3 C. trav.")
    _c(g, "Partage des recettes (%)", "percentage", sort_order=2, enabled_by_default=False,
       tooltip_short="Pourcentage des recettes nettes de billetterie revenant à l'artiste / au producteur.",
       tooltip_long="Précisez l'assiette : recettes NETTES (après TVA, SACEM, SPRE, frais de billetterie) ou brutes. "
                    "L'usage en coréalisation est un partage sur les recettes nettes, avec reddition de comptes "
                    "accompagnée du bordereau de billetterie.",
       plain="Votre pourcentage sur la billetterie. Vérifiez bien sur quoi il se calcule : "
             "les recettes « nettes » (après taxes et frais) sont plus petites que les « brutes ».")
    _c(g, "Minimum garanti (€ HT)", "number", sort_order=3, enabled_by_default=False,
       tooltip_short="Montant plancher garanti à l'artiste quel que soit le niveau des recettes.",
       tooltip_long="Le minimum garanti sécurise l'artiste contre une billetterie décevante : il est dû quelle que "
                    "soit la recette, le partage ne s'appliquant qu'au-delà de ce plancher. C'est le modèle le plus "
                    "équilibré entre les deux parties en coréalisation.",
       plain="Le montant minimum que vous touchez, même si la salle est vide. Si le partage de recettes dépasse ce "
             "montant, vous touchez le partage ; sinon, vous touchez le minimum garanti.",
       example=(
           "L'Organisateur garantit à [Contractant 1] une rémunération minimale de [montant] € HT. Si le partage des "
           "recettes défini ci-dessus excède ce montant, seule la somme issue du partage sera due ; dans le cas "
           "contraire, le minimum garanti sera versé intégralement."
       ))
    _c(g, "Acompte", "toggle_with_details", sort_order=4, enabled_by_default=False,
       tooltip_short="Versement d'un acompte à la signature : montant ou pourcentage, date de versement.",
       tooltip_long="L'acompte engage financièrement l'organisateur dès la signature et sert de garantie à l'artiste "
                    "en cas d'annulation tardive : c'est généralement lui qui reste acquis lorsque l'organisateur "
                    "annule (voir l'article Annulation et report).",
       plain="Usage courant : 30 à 50 % à la signature, le solde le jour J. L'acompte protège l'artiste "
             "en cas d'annulation (voir l'article Annulation).",
       example=(
           "Un acompte de [montant] € (soit [pourcentage] % du prix total) sera versé par l'Organisateur à la signature "
           "du présent contrat. Le solde sera exigible au plus tard le jour de la Représentation, avant l'entrée en scène."
       ))
    _c(g, "Modalités et délai de paiement", "textarea", sort_order=5,
       tooltip_short="Mode de règlement (virement, chèque), échéance, coordonnées de facturation.",
       tooltip_long="Le Code de commerce encadre les délais de paiement entre professionnels et prévoit des pénalités "
                    "de retard automatiques, même sans clause contractuelle ; les préciser ici évite toute contestation "
                    "sur le taux applicable.",
       plain="Comment et quand vous êtes payé. Idéalement le jour même du concert ou peu après — plus le délai est "
             "long, plus il y a de risque de ne jamais être payé.",
       example=(
           "Le règlement interviendra par virement bancaire sur le compte de [Contractant 1] au plus tard [nombre] jours "
           "après la Représentation, sur présentation d'une facture conforme. Tout retard de paiement entraînera de plein "
           "droit l'application de pénalités au taux de trois fois le taux d'intérêt légal, ainsi que l'indemnité "
           "forfaitaire de recouvrement de 40 € prévue à l'article D441-5 du Code de commerce."
       ),
       legal_ref="Art. L441-10 C. com.")
    _c(g, "Régime de TVA", "select", sort_order=6, enabled_by_default=False,
       options=["TVA 5,5 % (cession de spectacle vivant)", "TVA 20 % (prestation de service)",
                "TVA 2,10 % (représentations éligibles)", "Exonération / franchise en base (art. 293 B CGI)"],
       tooltip_short="Taux de TVA applicable au cachet ou au prix de cession.",
       tooltip_long="La cession de spectacle vivant bénéficie du taux réduit de 5,5 % (art. 278-0 bis F CGI). Le taux de "
                    "2,10 % s'applique aux 140 premières représentations de certains spectacles. Une simple prestation "
                    "technique ou un DJ set « animation » relèvent en principe du taux normal de 20 %. En cas de doute, "
                    "consultez un expert-comptable du spectacle.",
       plain="Le taux de TVA dépend de la nature de la prestation : 5,5 % pour un vrai spectacle vivant vendu par un "
             "producteur, 20 % pour une animation/prestation classique, 0 % si vous êtes en franchise de TVA.",
       legal_ref="Art. 278-0 bis F CGI")
    _c(g, "Frais annexes refacturés", "textarea", sort_order=7, enabled_by_default=False,
       tooltip_short="Frais refacturés en sus du cachet (transport, technique...), avec justificatifs.",
       tooltip_long="Les frais refacturés doivent être distincts du cachet et justifiés (factures, billets) pour ne pas "
                    "être requalifiés en complément de rémunération soumis aux mêmes charges et à la même TVA que "
                    "la prestation principale.",
       plain="Des frais en plus du cachet (location de matériel spécial, transport exceptionnel...) que l'organisateur "
             "accepte de rembourser sur justificatifs.",
       example=(
           "Outre le cachet défini au présent contrat, l'Organisateur remboursera à [Contractant 1], sur "
           "présentation de justificatifs, les frais suivants engagés pour les besoins exclusifs de la "
           "Représentation : [liste des frais — location de matériel spécifique, transport exceptionnel, "
           "prestataire technique additionnel]. Ces frais sont distincts du cachet et ne sauraient être "
           "requalifiés en complément de rémunération ; ils sont remboursés à l'euro l'euro, sans marge, dans le "
           "même délai que le solde du cachet."
       ))

    # ── 6 — Défraiements et logistique ────────────────────────────────────────
    g = _g("Défraiements et hospitalité", tooltip="Transport, hébergement, restauration, per diem de l'équipe artistique.", sort_order=6)
    _c(g, "Transport", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="Prise en charge du transport : qui organise, qui paie, quel périmètre.",
       tooltip_long="Le transport n'est pas un frais accessoire négligeable en tournée : son absence de précision "
                    "contractuelle est l'une des sources de désaccord les plus fréquentes après la rémunération elle-même. "
                    "Distinguez la prise en charge (qui paie) de l'organisation (qui réserve).",
       plain="Précisez qui paie et qui organise : billets de train/avion, véhicule, kilomètres. "
             "« Prise en charge » sans détail = source de conflit garantie.",
       example=(
           "L'Organisateur prend en charge le transport aller-retour de l'équipe artistique ([nombre] personnes) depuis "
           "[ville de départ] jusqu'au lieu de la Représentation : billets de train 2nde classe (ou indemnité kilométrique "
           "de [montant] €/km pour un trajet en véhicule), sur présentation de justificatifs."
       ))
    _c(g, "Hébergement", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="Nombre de chambres, catégorie d'hôtel, nuits prises en charge.",
       tooltip_long="À défaut de précision sur le nombre de chambres et leur configuration (single/double), l'usage "
                    "du secteur retient une chambre par personne ; en cas de désaccord, c'est cette absence de détail "
                    "qui est généralement source de litige, pas le principe même de l'hébergement.",
       plain="Combien de chambres, dans quel type d'hôtel, pour combien de nuits. Précisez si c'est en chambre "
             "individuelle ou partagée pour éviter les mauvaises surprises à l'arrivée.",
       example=(
           "L'Organisateur fournira [nombre] chambre(s) single dans un hôtel de catégorie 3 étoiles minimum, situé à "
           "moins de [nombre] km du lieu de la Représentation, pour la nuit du [date de l'évènement], petit-déjeuner inclus."
       ))
    _c(g, "Repas / catering", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Repas chauds, catering en loge, régimes alimentaires particuliers.",
       tooltip_long="Le catering (boissons et collations en loge, disponibles en continu) est distinct du repas "
                    "principal : les deux sont d'usage en spectacle vivant mais doivent être précisés séparément pour "
                    "éviter tout malentendu sur ce qui est réellement fourni.",
       plain="Un vrai repas chaud pour l'équipe, plus des boissons et en-cas disponibles en loge dès l'arrivée. "
             "Signalez les régimes particuliers (végétarien, allergies) à l'avance.",
       example=(
           "L'Organisateur fournira un repas chaud complet par personne pour l'équipe artistique ([nombre] personnes) "
           "le soir de la Représentation, ainsi qu'un catering en loge (boissons fraîches et chaudes, collations) "
           "disponible dès l'arrivée. Régimes particuliers notifiés en annexe (rider)."
       ))
    _c(g, "Per diem", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Indemnité journalière forfaitaire par personne, en remplacement ou complément des repas.",
       tooltip_long="Le per diem est un remboursement forfaitaire de frais, non un salaire : il doit rester d'un "
                    "montant raisonnable et cohérent avec les usages du secteur pour ne pas être requalifié en "
                    "élément de rémunération soumis à charges.",
       plain="Somme forfaitaire par jour et par personne (souvent 20-40 €) versée en espèces pour couvrir les frais "
             "quotidiens quand les repas ne sont pas fournis.",
       example=(
           "L'Organisateur versera à chaque membre de l'équipe artistique un per diem forfaitaire de [per diem] "
           "par jour de présence sur le lieu de la Représentation, en espèces ou par virement, destiné à couvrir "
           "les frais quotidiens non pris en charge par ailleurs (repas non fournis, menues dépenses). Ce per diem "
           "est distinct du cachet et de tout remboursement de frais sur justificatifs, et ne saurait être cumulé "
           "avec la prise en charge intégrale d'un même repas au titre de l'article Repas / catering."
       ))

    # ── 7 — Conditions techniques ─────────────────────────────────────────────
    g = _g("Conditions techniques", tooltip="Fiche technique, son, lumières, backline, loges, accréditations.", sort_order=7)
    _c(g, "Fiche technique annexée", "toggle", sort_order=0,
       tooltip_short="La fiche technique de l'artiste fait partie intégrante du contrat (annexe).",
       tooltip_long="La fiche technique (patch, plan de scène, besoins son/lumière) annexée au contrat a valeur "
                    "contractuelle : son non-respect par l'organisateur peut justifier le refus de jouer sans perte du "
                    "cachet. Datez et paraphez l'annexe.",
       plain="Votre fiche technique jointe au contrat devient obligatoire pour l'organisateur : "
             "s'il ne fournit pas ce qui y figure, c'est lui qui est en tort.")
    _c(g, "Sonorisation et éclairage fournis par", "select", sort_order=1,
       options=["L'Organisateur", "L'Artiste", "Mixte (répartition en annexe)"],
       tooltip_short="Qui fournit le système son et lumière ?",
       tooltip_long="Le partage de la charge technique doit être explicite : à défaut, l'organisateur d'un lieu équipé "
                    "est présumé la fournir, mais pour un évènement privé ou hors salle habituelle, c'est souvent "
                    "l'artiste qui l'apporte — ce qui justifie alors une facturation distincte.",
       plain="En salle équipée, c'est l'organisateur. En évènement privé ou d'entreprise, c'est souvent l'artiste/DJ "
             "qui vient avec son matériel — dans ce cas facturez-le.")
    _c(g, "Backline fourni", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Instruments et amplis mis à disposition par l'organisateur (batterie, amplis, clavier...).",
       tooltip_long="Le backline listé en annexe a la même valeur contractuelle que la fiche technique : son absence "
                    "au moment des balances peut justifier un report ou une réduction proportionnelle si la prestation "
                    "en est affectée.",
       plain="Le matériel (batterie, amplis...) que la salle fournit pour éviter à l'artiste de tout transporter. "
             "Listez précisément ce qui est prévu pour éviter les surprises le jour J.",
       example=(
           "L'Organisateur mettra à disposition le backline suivant, conforme à la fiche technique : [liste du backline]. "
           "Tout élément manquant devra être signalé à [Contractant 1] au moins [nombre] jours avant la Représentation."
       ))
    _c(g, "Matériel DJ / régie", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Pour un DJ set : platines, mixer, retours cabine, table stable — précisez modèles et configuration.",
       tooltip_long="Contrairement au backline instrumental classique, le matériel DJ n'est pas standardisé d'un lieu "
                    "à l'autre : préciser les modèles exacts attendus évite qu'un matériel « équivalent » mais "
                    "inadapté (firmware obsolète, table instable) ne compromette la prestation.",
       plain="Clause spécifique DJ : exigez les modèles précis (ex : 2× CDJ-3000 + DJM-900NXS2 à jour de firmware, "
             "retours cabine). Le matériel d'entrée de gamme est LA galère classique des DJ sets.",
       example=(
           "L'Organisateur fournira une régie DJ composée de : [équipement] (firmware à jour), installée sur support "
           "stable et isolée des vibrations, avec un système de retour cabine indépendant réglable depuis la cabine. "
           "[Contractant 1] pourra connecter son propre équipement complémentaire après validation technique."
       ))
    _c(g, "Personnel technique du lieu", "textarea", sort_order=4, enabled_by_default=False,
       tooltip_short="Régisseur, ingénieur son, technicien lumière présents aux balances et pendant la représentation.",
       tooltip_long="La présence d'un régisseur du lieu, connaissant les équipements et les issues de secours, est "
                    "généralement une obligation de l'organisateur au titre de la sécurité du public ; ce n'est pas "
                    "une simple prestation de confort pour l'artiste.",
       plain="Qui, côté salle, s'occupe du son et des lumières pendant votre passage. Sans personnel technique dédié, "
             "votre équipe doit tout gérer seule.",
       example=(
           "L'Organisateur mettra à disposition de [Contractant 1], dès l'arrivée de l'équipe artistique et pour "
           "toute la durée des balances et de la Représentation, un régisseur son et, le cas échéant, un régisseur "
           "lumière connaissant parfaitement les équipements du lieu et les issues de secours. Ce personnel "
           "technique demeure sous la responsabilité et l'autorité de l'Organisateur ; il travaille en "
           "coordination avec l'équipe technique de [Contractant 1] pour la mise en œuvre de la fiche technique "
           "annexée."
       ))
    _c(g, "Loges", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="Loge privative, fermant à clé, avec sanitaires, miroir, catering.",
       tooltip_long="La loge privative fermant à clé participe à la sécurité des effets personnels de l'artiste et à "
                    "sa préparation dans des conditions dignes ; son absence dans un lieu qui en dispose normalement "
                    "peut être signalée comme un manquement mineur mais réel.",
       plain="Un espace privé pour se préparer et se poser avant/après le concert, qui ferme à clé. "
             "Standard dans toute salle professionnelle.",
       example=(
           "L'Organisateur mettra à disposition de [Contractant 1] une loge privative, propre, chauffée, fermant à clé, "
           "équipée de sanitaires à proximité, de miroirs et de prises électriques, accessible dès l'arrivée de l'équipe "
           "et jusqu'à une heure après la fin de la Représentation."
       ))
    _c(g, "Accréditations / badges / pass", "toggle_with_details", sort_order=6, enabled_by_default=False,
       tooltip_short="Nombre de pass « all access », invitations équipe, accès backstage (indispensable en festival).",
       tooltip_long="En festival ou grand évènement, l'accès aux zones techniques et backstage est strictement "
                    "contrôlé par badge : un nombre insuffisant d'accréditations peut concrètement empêcher une "
                    "partie de l'équipe de travailler — précisez donc un nombre ferme, pas une estimation.",
       plain="Les badges qui permettent à votre équipe (et vos invités) d'accéder aux coulisses. "
             "Indispensable en festival où sans badge, on ne rentre nulle part.",
       example=(
           "L'Organisateur remettra à [Contractant 1] [nombre] accréditations « accès total » pour son équipe et "
           "[nombre] invitations pour ses guests, à retirer à l'accueil artistes le jour de la Représentation."
       ))
    _c(g, "Gardiennage du matériel", "toggle", sort_order=7, enabled_by_default=False,
       tooltip_short="L'organisateur assure la surveillance du matériel entre le déchargement et le rechargement.",
       tooltip_long="À défaut de clause, la responsabilité du matériel laissé sans surveillance sur le site relève "
                    "du droit commun de la responsabilité civile, ce qui rend la preuve d'une faute difficile : "
                    "une obligation contractuelle de gardiennage sécurise l'artiste en cas de vol ou de dégradation.",
       plain="L'organisateur est responsable de votre matériel entre l'arrivée et le départ (vol, casse). "
             "Important en festival où le matériel reste en zone technique.")

    # ── 8 — Billetterie et recettes ───────────────────────────────────────────
    g = _g("Billetterie et recettes", tooltip="Qui exploite la billetterie, prix des places, invitations, reddition de comptes.", sort_order=8)
    _c(g, "Exploitant de la billetterie", "select", sort_order=0,
       options=["L'Organisateur", "Coréalisation (billetterie commune)", "L'Artiste / le Producteur", "Entrée gratuite"],
       tooltip_short="Qui émet les billets et encaisse les recettes ?",
       tooltip_long="L'exploitant de la billetterie est responsable des obligations fiscales (billetterie conforme, "
                    "art. 290 quater CGI) et sociales attachées aux entrées. En coréalisation, un bordereau de recettes "
                    "contradictoire est établi à l'issue de la représentation.",
       plain="Qui vend les billets et encaisse l'argent. En coréalisation, les deux parties ont accès au détail des "
             "ventes ; sinon, c'est simplement l'organisateur qui gère tout.",
       legal_ref="Art. 290 quater CGI")
    _c(g, "Prix des places", "text", sort_order=1, enabled_by_default=False,
       tooltip_short="Prix de vente public des billets (plein tarif / réduit / prévente).",
       tooltip_long="En partage de recettes, le prix de vente public est un élément déterminant de la rémunération "
                    "de l'artiste : sa modification unilatérale par l'organisateur (soldes, gratuité massive) sans "
                    "accord préalable peut être contestée comme une atteinte à l'économie du contrat.",
       plain="À activer surtout en partage de recettes : le prix du billet détermine directement votre rémunération, "
             "il ne doit pas pouvoir changer sans votre accord.",
       example="[prix des places]")
    _c(g, "Invitations et exonérés", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Quota d'invitations de chaque partie, traitement dans le partage des recettes.",
       tooltip_long="Un quota d'invitations non plafonné peut réduire artificiellement l'assiette du partage de "
                    "recettes : au-delà du quota convenu, chaque place gratuite devrait être réintégrée à son prix "
                    "public dans le calcul de la part revenant à l'artiste.",
       plain="Combien de places gratuites chaque partie peut distribuer. Au-delà de ce nombre, ça doit compter comme "
             "si la place avait été vendue (sinon l'organisateur pourrait « vider » la billetterie en invitations).",
       example=(
           "Chaque partie disposera d'un quota de [nombre] invitations. Au-delà de ce quota, toute place exonérée devra "
           "être validée par les deux parties et sera réintégrée dans l'assiette du partage des recettes à son prix public."
       ))
    _c(g, "Reddition de comptes billetterie", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Remise du bordereau de billetterie et versement de la part de recettes : délai et justificatifs.",
       tooltip_long="En l'absence de délai contractuel de reddition de comptes, l'artiste n'a aucun moyen de vérifier "
                    "le calcul de sa part de recettes ni de contester un désaccord dans un temps raisonnable : cette "
                    "clause est donc indissociable de tout modèle de rémunération au partage.",
       plain="L'organisateur vous transmet le détail exact des ventes et vous paie votre part dans un délai précis "
             "après le concert. Sans cette clause, difficile de vérifier ce qui vous est réellement dû.",
       example=(
           "L'Organisateur remettra à [Contractant 1], au plus tard [nombre] jours après la Représentation, le relevé "
           "détaillé de billetterie (entrées payantes par catégorie, exonérés, recette brute et nette) accompagné des "
           "justificatifs, et procédera au versement de la part de recettes dans le même délai."
       ))

    # ── 9 — Captation, image et promotion ─────────────────────────────────────
    g = _g("Captation, image et promotion", tooltip="Enregistrement du concert, photos, diffusion, usage promotionnel.", sort_order=9)
    _c(g, "Autorisation de captation", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="L'organisateur peut-il enregistrer (audio/vidéo) la représentation ? À quelles fins ?",
       tooltip_long="La fixation de la prestation d'un artiste-interprète requiert son autorisation écrite (art. L212-3 "
                    "CPI) : sans cette clause, AUCUNE captation n'est licite. Distinguez la captation d'archive, la "
                    "captation promotionnelle (extraits) et la captation d'exploitation (diffusion intégrale, DVD, "
                    "streaming), qui appelle une rémunération distincte.",
       plain="Sans votre accord écrit, personne n'a le droit d'enregistrer votre concert. "
             "Si vous l'autorisez, limitez : durée des extraits, plateformes, et durée d'utilisation.",
       legal_ref="Art. L212-3 CPI",
       example=(
           "[Contractant 1] autorise l'Organisateur à capter des extraits de la Représentation (durée cumulée maximale "
           "de [durée], sans captation intégrale), à des fins exclusivement mémorielles et promotionnelles de "
           "[l'Évènement], à l'exclusion de toute exploitation commerciale. Toute autre captation ou diffusion fera "
           "l'objet d'un accord écrit distinct prévoyant une rémunération spécifique."
       ))
    _c(g, "Photographies", "toggle", sort_order=1, enabled_by_default=False,
       tooltip_short="Autorisation de photographier la prestation (presse, photographe officiel).",
       tooltip_long="Comme la captation vidéo, la fixation de l'image de l'artiste-interprète sur scène requiert son "
                    "autorisation : cette clause distincte permet d'autoriser la photographie sans nécessairement "
                    "ouvrir la porte à une captation audio ou vidéo complète.",
       plain="Autorise un photographe (presse, photographe officiel de la salle) à prendre des photos de votre "
             "concert. Séparé de la captation vidéo/audio, qui a ses propres règles.")
    _c(g, "Diffusion sur les réseaux sociaux", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Publication d'extraits sur les réseaux de l'organisateur : plateformes, durée, validation.",
       tooltip_long="Une autorisation de captation ne vaut pas automatiquement autorisation de diffusion publique : "
                    "ces deux actes sont juridiquement distincts et doivent être encadrés séparément, avec une "
                    "limitation de durée et de plateformes pour rester proportionnée à l'objectif promotionnel.",
       plain="Autorise l'organisateur à publier des extraits sur ses réseaux (Instagram, TikTok...). "
             "Précisez la durée maximale des extraits et exigez d'être crédité.",
       example=(
           "L'Organisateur pourra publier sur ses comptes officiels ([plateformes]) des extraits de la Représentation "
           "d'une durée unitaire maximale de [durée], en créditant systématiquement [Contractant 1]. "
           "Les publications resteront en ligne sans limitation de durée sauf demande de retrait motivée de [Contractant 1]."
       ))
    _c(g, "Utilisation promotionnelle du nom et de l'image", "toggle_with_details", sort_order=3,
       tooltip_short="Usage du nom, logo, photos et biographie de l'artiste pour la promotion de l'évènement.",
       tooltip_long="Le droit à l'image (art. 9 C. civ.) impose une autorisation expresse et spéciale : précisez les "
                    "supports (affiches, réseaux, presse), le territoire et la durée. L'artiste fournit en général un kit "
                    "promo (photos HD approuvées, bio, logo) dont l'usage est obligatoire.",
       plain="L'organisateur a besoin de votre nom et photo pour l'affiche : c'est normal. "
             "Imposez l'usage de VOS visuels officiels et la validation de l'orthographe du nom de scène.",
       legal_ref="Art. 9 C. civ.",
       example=(
           "[Contractant 1] autorise l'Organisateur à utiliser son nom de scène, son image et sa biographie aux seules "
           "fins d'annonce et de promotion de [l'Évènement], sur tous supports, jusqu'à la date de la Représentation. "
           "L'Organisateur s'engage à utiliser exclusivement les visuels et éléments fournis par [Contractant 1]."
       ))
    _c(g, "Droit à l'image des invités (évènement privé)", "toggle_with_details", sort_order=4, enabled_by_default=False,
       tooltip_short="Restrictions de captation impliquant les invités d'un évènement privé.",
       tooltip_long="Le droit à l'image de personnes tierces identifiables (les invités) appartient à ces personnes "
                    "et non à l'artiste ni à l'organisateur : toute publication les impliquant sans leur consentement "
                    "expose son auteur à un risque contentieux distinct du droit à l'image de l'artiste lui-même.",
       plain="Pour un mariage ou une soirée privée : si l'artiste veut publier des images de sa prestation, "
             "les invités identifiables ne doivent pas y figurer sans accord de l'hôte.",
       example=(
           "S'agissant d'un évènement privé, [Contractant 1] s'interdit de capter ou publier des images sur lesquelles "
           "les invités seraient identifiables, sauf accord écrit préalable de l'Organisateur. [Contractant 1] pourra "
           "en revanche publier des images de sa seule prestation (scène, matériel, ambiance non identifiable)."
       ))
    _c(g, "Mention et crédit obligatoires", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="Libellé exact du nom de scène et crédits sur tous les supports de communication.",
       tooltip_long="Fixer contractuellement le libellé exact du nom de scène (orthographe, majuscules, éventuel "
                    "logo) évite les erreurs récurrentes sur les supports de communication et facilite, le cas "
                    "échéant, une réclamation fondée sur le droit moral au respect du nom.",
       plain="L'orthographe exacte de votre nom de scène à utiliser partout (affiches, programmes, réseaux) — "
             "pour éviter les fautes de frappe qui traînent ensuite partout.",
       example=(
           "Le nom de scène de [Contractant 1] devra être reproduit à l'identique — orthographe, majuscules, "
           "typographie — soit : « [nom de scène exact] », sur l'ensemble des supports de communication de "
           "l'évènement (affiches, programmes, réseaux sociaux, site internet, billetterie). L'Organisateur "
           "soumettra à validation de [Contractant 1] tout support de communication avant sa première publication, "
           "dans un délai de [nombre] jours."
       ))

    # ── 10 — Merchandising ────────────────────────────────────────────────────
    g = _g("Merchandising", tooltip="Vente de produits dérivés de l'artiste sur le lieu de l'évènement.", sort_order=10)
    _c(g, "Vente de merchandising autorisée", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="L'artiste peut vendre ses produits dérivés (t-shirts, vinyles, CD) sur place.",
       tooltip_long="Le droit de vendre du merchandising sur le lieu n'est pas automatique : certains lieux le "
                    "réservent à leur propre exploitation ou le soumettent à une commission. À défaut d'autorisation "
                    "explicite, l'artiste ne peut pas présumer ce droit acquis.",
       plain="Le « merch » est une source de revenus importante en tournée. Vérifiez si le lieu prend une commission "
             "(0 à 25 % selon les salles) et qui fournit la table et le vendeur.",
       example=(
           "[Contractant 1] est autorisé(e) à vendre ses produits dérivés (textile, supports enregistrés) dans l'enceinte "
           "du lieu, à un emplacement visible et éclairé fourni par l'Organisateur, de l'ouverture des portes jusqu'à "
           "[durée] après la fin de la Représentation."
       ))
    _c(g, "Commission du lieu sur les ventes (%)", "percentage", sort_order=1, enabled_by_default=False,
       tooltip_short="Pourcentage des ventes de merchandising reversé au lieu / à l'organisateur.",
       tooltip_long="La commission sur le merchandising est une pratique distincte du cachet et doit faire l'objet "
                    "d'une reddition de comptes propre (nombre d'articles vendus, prix unitaire) pour permettre à "
                    "l'artiste de vérifier le calcul de la somme reversée.",
       plain="Le pourcentage que la salle prélève sur vos ventes de merch. Variable selon les lieux (souvent entre "
             "0 et 25 %) — à négocier avant, pas à découvrir à la fin de la soirée.")
    _c(g, "Personnel de vente", "select", sort_order=2, enabled_by_default=False,
       options=["Fourni par l'Artiste", "Fourni par l'Organisateur", "Vente en autonomie (stand non tenu)"],
       tooltip_short="Qui tient le stand de merchandising ?",
       tooltip_long="La personne qui tient le stand engage la responsabilité de la partie qui l'a mise à disposition "
                    "en cas d'erreur de caisse ou de vol : préciser cette responsabilité évite les contestations sur "
                    "les écarts de recette constatés en fin de soirée.",
       plain="Qui s'occupe physiquement de vendre vos produits : vous-même, quelqu'un de votre équipe, ou une "
             "personne fournie par le lieu.")

    # ── 11 — Obligations de l'organisateur ────────────────────────────────────
    g = _g("Obligations de l'organisateur", tooltip="Sécurité, déclarations SACEM/SPRE, autorisations, assurances du lieu.", sort_order=11)
    _c(g, "Déclaration et paiement SACEM", "toggle", sort_order=0,
       tooltip_short="L'organisateur déclare l'évènement à la SACEM et acquitte les droits d'auteur.",
       tooltip_long="L'organisateur demeure généralement responsable des déclarations SACEM liées à l'évènement : "
                    "déclaration préalable, remise du programme des œuvres exécutées après la représentation, et paiement "
                    "des droits (assis sur les recettes ou le budget des dépenses). L'artiste doit lui remettre la liste "
                    "exacte des œuvres jouées pour permettre la répartition aux ayants droit.",
       plain="C'est l'organisateur qui déclare le concert à la SACEM et paie les droits d'auteur — pas l'artiste. "
             "L'artiste doit juste fournir la liste des morceaux joués (ça lui permet d'ailleurs de toucher "
             "ses propres droits SACEM s'il joue ses compositions !).",
       legal_ref="Art. L122-2 et L132-18 s. CPI",
       example=(
           "L'Organisateur fera son affaire de la déclaration de la Représentation auprès de la SACEM et du paiement "
           "des droits d'auteur y afférents. [Contractant 1] lui remettra, à l'issue de la Représentation, le programme "
           "exact des œuvres exécutées afin de permettre la répartition des droits."
       ))
    _c(g, "Rémunération équitable SPRE", "toggle", sort_order=1, enabled_by_default=False,
       tooltip_short="Si de la musique enregistrée est diffusée (DJ set, avant-show, interludes) : redevance SPRE.",
       tooltip_long="La diffusion de musique enregistrée dans un lieu public (DJ set, sonorisation d'attente, interludes) "
                    "ouvre droit à la « rémunération équitable » collectée par la SPRE au profit des artistes-interprètes "
                    "et producteurs de phonogrammes. Elle s'ajoute aux droits SACEM et incombe en principe à l'exploitant "
                    "du lieu / l'organisateur. Barème spécifique pour les discothèques et soirées dansantes.",
       plain="Aide contextuelle : dès qu'on passe des disques (DJ set, musique d'attente), il y a une deuxième redevance "
             "en plus de la SACEM : la SPRE. C'est aussi l'organisateur qui la paie.",
       legal_ref="Art. L214-1 CPI")
    _c(g, "Sécurité du public et service d'ordre", "toggle", sort_order=2,
       tooltip_short="L'organisateur assure la sécurité du public, de l'artiste et le respect des normes ERP.",
       tooltip_long="L'organisateur est responsable de la sécurité du public et des artistes : respect des règles ERP, "
                    "jauge autorisée, service de sécurité adapté, secours. Il doit garantir à l'artiste un accès scène "
                    "sécurisé et empêcher l'accès du public au plateau et aux loges.",
       plain="C'est l'organisateur qui garantit que tout est sécurisé : jauge respectée, service de sécurité, accès "
             "au plateau et aux loges protégé du public.",
       legal_ref="Art. R143-2 s. CCH")
    _c(g, "Autorisations administratives", "toggle", sort_order=3,
       tooltip_short="Débit de boisson, occupation du domaine public, autorisation de nuit, déclaration préfecture...",
       tooltip_long="Le défaut d'autorisation administrative (occupation du domaine public, débit de boissons "
                    "temporaire, dérogation horaire) expose l'organisateur seul à une interdiction ou une fermeture "
                    "de l'évènement par les autorités : l'artiste n'a pas à en assumer les conséquences financières.",
       plain="Toutes les autorisations (mairie, préfecture, débit de boissons, horaires de nuit) sont l'affaire de "
             "l'organisateur. Si l'évènement est annulé faute d'autorisation, c'est sa responsabilité.")
    _c(g, "Assurance responsabilité civile organisateur", "toggle_with_details", sort_order=4,
       tooltip_short="L'organisateur justifie d'une assurance RC couvrant l'évènement, le public et le matériel accueilli.",
       tooltip_long="L'assurance responsabilité civile organisateur couvre les dommages causés aux tiers (public, "
                    "artiste, matériel) pendant l'évènement ; son absence expose l'artiste à devoir se retourner "
                    "personnellement contre l'organisateur en cas de sinistre, sans garantie de solvabilité.",
       plain="L'organisateur doit avoir une assurance qui couvre les dégâts éventuels pendant l'évènement — y compris "
             "sur votre matériel. Demandez l'attestation avant le concert, pas après un incident.",
       example=(
           "L'Organisateur déclare avoir souscrit une assurance responsabilité civile organisateur couvrant l'ensemble "
           "des dommages corporels, matériels et immatériels pouvant survenir pendant l'évènement, y compris les dommages "
           "causés au matériel de [Contractant 1]. Attestation communiquée sur demande avant la Représentation."
       ))
    _c(g, "Limitation sonore et réglementation locale", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="Limiteur de niveau sonore, arrêtés locaux, couvre-feu : informer l'artiste des contraintes.",
       tooltip_long="Une contrainte sonore ou horaire non communiquée avant la signature (limiteur de décibels qui "
                    "coupe le son, couvre-feu imposant une fin anticipée) peut être invoquée par l'artiste comme une "
                    "information essentielle manquante ayant affecté sa prestation.",
       plain="Si la salle a un limiteur de décibels ou un couvre-feu à 22h, l'artiste doit le savoir AVANT de signer — "
             "pas en arrivant aux balances.",
       legal_ref="Décret n° 2017-1244 (niveaux sonores)",
       example=(
           "L'Organisateur informe [Contractant 1], avant la signature du présent contrat, des contraintes "
           "sonores et réglementaires applicables au lieu de la Représentation : limiteur de niveau sonore fixé à "
           "[nombre] dB(A), couvre-feu à [heure], et/ou arrêté municipal ou préfectoral limitant l'horaire ou le "
           "volume de diffusion. [Contractant 1] adaptera sa prestation technique à ces contraintes, sous réserve "
           "qu'elles lui aient été communiquées dans les conditions du présent article ; à défaut d'information "
           "préalable, l'Organisateur ne pourra se prévaloir d'une prestation non conforme du fait de ces "
           "contraintes."
       ))

    # ── 12 — Obligations de l'artiste ─────────────────────────────────────────
    g = _g("Obligations de l'artiste", tooltip="Ponctualité, conformité de la prestation, comportement, matériel propre.", sort_order=12)
    _c(g, "Ponctualité et présence", "toggle", sort_order=0,
       tooltip_short="Arrivée à l'heure convenue pour les balances et la représentation.",
       tooltip_long="Le retard de l'artiste peut constituer une inexécution partielle de son obligation contractuelle : "
                    "s'il compromet les balances ou l'horaire de passage, il peut justifier une réduction du cachet "
                    "proportionnelle au préjudice réellement subi par l'organisateur.",
       plain="L'artiste s'engage à être là pour les balances et à l'heure de passage. "
             "En cas de retard qui fait capoter l'évènement, le cachet peut être réduit ou perdu.")
    _c(g, "Prestation conforme", "toggle", sort_order=1,
       tooltip_short="Prestation exécutée de manière professionnelle, conforme à la durée et au format convenus.",
       tooltip_long="Cette clause générale rappelle l'obligation de moyens (et non de résultat artistique) de "
                    "l'artiste : exécuter la prestation avec professionnalisme, dans le respect de la durée et du "
                    "format convenus, sans garantir un succès public qui échappe à son contrôle.",
       plain="L'artiste s'engage à assurer une prestation sérieuse, dans le format et la durée prévus au contrat.")
    _c(g, "Sobriété et comportement", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="Engagement de comportement professionnel, respect du lieu, du personnel et du public.",
       tooltip_long="Cette clause de comportement, courante en évènement privé ou d'entreprise, permet à "
                    "l'organisateur de justifier une réduction de cachet ou une résiliation en cas de manquement "
                    "grave et constaté (état d'ébriété empêchant la prestation, comportement irrespectueux).",
       plain="L'artiste s'engage à un comportement professionnel : pas d'excès qui empêcherait de jouer correctement, "
             "respect du lieu et des équipes. Surtout utile en évènement privé ou d'entreprise.")
    _c(g, "Matériel personnel et consommables", "textarea", sort_order=3, enabled_by_default=False,
       tooltip_short="Matériel apporté par l'artiste (instruments, ordinateur, contrôleurs) et consommables à sa charge.",
       tooltip_long="Distinguer clairement le matériel apporté par l'artiste de celui fourni par l'organisateur "
                    "(backline, sonorisation) évite tout litige sur la responsabilité en cas de dommage ou de perte "
                    "pendant le transport et l'installation.",
       plain="Ce que l'artiste apporte lui-même (son ordinateur, ses contrôleurs, ses baguettes...) et qui reste "
             "sous sa responsabilité, par opposition à ce que fournit la salle.",
       example=(
           "[Contractant 1] apporte et demeure seul(e) responsable du matériel suivant : [liste — instruments "
           "personnels, ordinateur et contrôleurs, câblage spécifique, baguettes et consommables]. Ce matériel "
           "reste sous la garde de [Contractant 1] pendant le transport, l'installation et la désinstallation, à "
           "l'exclusion du backline et de la sonorisation fournis par l'Organisateur."
       ))
    _c(g, "Assurance de l'artiste", "toggle_with_details", sort_order=4, enabled_by_default=False,
       tooltip_short="RC professionnelle de l'artiste et assurance de ses instruments / matériel.",
       tooltip_long="L'assurance de l'artiste couvre son propre matériel et sa responsabilité professionnelle, en "
                    "miroir de celle de l'organisateur : chaque partie reste responsable des dommages causés par son "
                    "propre fait ou son propre matériel, ce qui simplifie le règlement des sinistres.",
       plain="Votre propre assurance (RC pro et matériel). Chacun protège ses affaires : votre matériel, votre "
             "assurance ; le lieu et le public, l'assurance de l'organisateur.",
       example=(
           "[Contractant 1] déclare être titulaire d'une assurance responsabilité civile professionnelle couvrant sa "
           "prestation, ainsi que d'une assurance couvrant son propre matériel. Chaque partie conserve la charge des "
           "dommages causés par son propre fait ou son propre matériel."
       ))
    _c(g, "Promotion de l'évènement par l'artiste", "toggle_with_details", sort_order=5, enabled_by_default=False,
       tooltip_short="Relais de l'évènement sur les réseaux de l'artiste : nombre de publications, calendrier.",
       tooltip_long="Un engagement de promotion sur les réseaux de l'artiste doit rester chiffré et raisonnable "
                    "(nombre et type de publications) pour rester une obligation accessoire à la prestation "
                    "artistique, et non une prestation de communication distincte qui appellerait sa propre "
                    "rémunération.",
       plain="De plus en plus demandé : l'artiste s'engage à annoncer la date sur ses réseaux. "
             "Restez raisonnable (1-2 posts + 1 story), c'est un engagement contractuel.",
       example=(
           "[Contractant 1] s'engage à relayer l'annonce de [l'Évènement] sur ses réseaux sociaux officiels, à "
           "raison d'au minimum [nombre] publication(s) et [nombre] story/stories, entre la confirmation du "
           "présent contrat et la date de la Représentation, à partir des visuels et informations fournis par "
           "l'Organisateur. Cet engagement constitue une obligation accessoire à la prestation artistique et ne "
           "saurait être interprété comme une prestation de communication distincte donnant lieu à rémunération "
           "complémentaire."
       ))

    # ── 13 — Annulation et report ─────────────────────────────────────────────
    g = _g("Annulation et report", tooltip="Conséquences financières d'une annulation par l'une ou l'autre partie, et modalités de report.", sort_order=13)
    _c(g, "Modèle d'annulation", "select", sort_order=0, required=True,
       options=["Annulation simple (restitution de l'acompte, pas d'indemnité)",
                "Acompte conservé par la partie victime",
                "Indemnité forfaitaire (montant à préciser ci-dessous)",
                "Indemnité égale à la totalité du cachet",
                "Barème progressif selon la date d'annulation"],
       tooltip_short="Quel régime s'applique si l'une des parties annule sans motif légitime ?",
       tooltip_long="La clause d'annulation est une clause pénale (art. 1231-5 C. civ.) : le juge peut la modérer si elle "
                    "est manifestement excessive. L'usage du secteur : annulation par l'organisateur à moins de 30 jours "
                    "de la date = cachet intégralement dû ; annulation lointaine = acompte conservé. L'annulation par "
                    "l'artiste l'expose au remboursement des frais engagés (communication, technique) sur justificatifs.",
       plain="Décidez À L'AVANCE ce qui se passe si ça annule. Le plus courant : si l'organisateur annule à moins d'un "
             "mois de la date, il doit tout le cachet ; si l'artiste annule sans raison valable, il rembourse l'acompte "
             "et les frais engagés.",
       legal_ref="Art. 1231-5 C. civ.")
    _c(g, "Précisions sur l'indemnité d'annulation", "textarea", sort_order=1, enabled_by_default=False,
       tooltip_short="Montants, barème par période, frais remboursables — précisez le modèle choisi ci-dessus.",
       tooltip_long="Un modèle d'annulation choisi sans barème chiffré associé reste difficile à appliquer en "
                    "pratique : cette clause traduit le modèle sélectionné en montants ou pourcentages précis, "
                    "opposables aux deux parties.",
       plain="Le détail chiffré de ce qui se passe en cas d'annulation, selon le modèle choisi juste au-dessus "
             "(montants exacts, dates butoirs).",
       example=(
           "En cas d'annulation du fait de l'Organisateur : plus de 60 jours avant la Représentation, l'acompte reste "
           "acquis à [Contractant 1] ; entre 60 et 30 jours, 50 % du cachet est dû ; moins de 30 jours avant la date, "
           "le cachet est intégralement dû. En cas d'annulation du fait de [Contractant 1] hors force majeure, "
           "celui-ci/celle-ci restituera l'acompte perçu et remboursera à l'Organisateur les frais engagés, "
           "sur présentation de justificatifs et dans la limite de [montant] €."
       ))
    _c(g, "Report d'un commun accord", "toggle_with_details", sort_order=2, enabled_by_default=False,
       tooltip_short="Possibilité de reporter la représentation à une date convenue, aux mêmes conditions.",
       tooltip_long="Le report, distinct de l'annulation, permet de conserver l'économie générale du contrat (cachet, "
                    "conditions techniques) en déplaçant simplement la date : il évite le déclenchement du régime "
                    "d'indemnisation tant qu'un accord sur une nouvelle date reste possible dans le délai fixé.",
       plain="Plutôt que d'annuler et de tout rembourser, les deux parties trouvent une nouvelle date, aux mêmes "
             "conditions. Prévoyez un délai limite pour se mettre d'accord, sinon ça retombe sur l'annulation.",
       example=(
           "En cas d'impossibilité de maintenir la Représentation, les parties s'efforceront de convenir d'une date de "
           "report dans un délai de [nombre] mois, aux mêmes conditions financières et techniques. L'acompte versé sera "
           "affecté à la nouvelle date. À défaut d'accord sur une date de report dans ce délai, le régime d'annulation "
           "s'appliquera."
       ))
    _c(g, "Intempéries (plein air)", "toggle_with_details", sort_order=3, enabled_by_default=False,
       tooltip_short="Sort du cachet si la représentation en extérieur est empêchée par la météo.",
       tooltip_long="Les intempéries en plein air ne relèvent généralement pas de la force majeure (le risque météo "
                    "est prévisible pour un évènement extérieur) : une clause spécifique est donc nécessaire pour "
                    "régler le sort du cachet, distincte du régime de force majeure applicable aux autres aléas.",
       plain="En plein air, la pluie n'est PAS un cas de force majeure (c'est prévisible !). "
             "Il faut donc une clause : en général, si l'artiste est sur place et prêt à jouer, le cachet est dû.",
       example=(
           "En cas d'intempéries empêchant la Représentation en extérieur, l'Organisateur mettra en œuvre la solution de "
           "repli prévue. À défaut de repli possible, et dès lors que [Contractant 1] s'est tenu prêt à exécuter sa "
           "prestation sur le lieu à l'horaire convenu, le cachet demeure intégralement dû."
       ))
    _c(g, "Maladie ou indisponibilité de l'artiste", "textarea", sort_order=4, enabled_by_default=False,
       tooltip_short="Justificatifs exigés (certificat médical), restitution de l'acompte, recherche d'un report.",
       tooltip_long="L'indisponibilité de l'artiste pour raison médicale, dûment justifiée, est traitée distinctement "
                    "d'une annulation volontaire : elle exonère les deux parties de pénalité mais implique en "
                    "contrepartie la restitution de l'acompte perçu, faute de prestation exécutée.",
       plain="Si l'artiste tombe malade ou a un accident, avec un certificat médical à l'appui : personne ne paie de "
             "pénalité, l'acompte est rendu, et on essaie de trouver une nouvelle date.",
       example=(
           "En cas de maladie ou d'accident empêchant [Contractant 1] d'assurer la Représentation, dûment justifié par "
           "certificat médical communiqué sans délai, le présent contrat sera résolu sans indemnité de part ni d'autre ; "
           "l'acompte perçu sera restitué à l'Organisateur, et les parties rechercheront de bonne foi une date de report."
       ))

    # ── 14 — Force majeure ────────────────────────────────────────────────────
    g = _g("Force majeure", tooltip="Événements imprévisibles et irrésistibles empêchant la représentation.", sort_order=14)
    _c(g, "Événements couverts", "textarea", sort_order=0,
       tooltip_short="Définition contractuelle de la force majeure et exemples (catastrophe, interdiction administrative...).",
       tooltip_long="La force majeure (art. 1218 C. civ.) suppose un événement échappant au contrôle du débiteur, "
                    "imprévisible à la conclusion du contrat et irrésistible. La jurisprudence est stricte : la faible "
                    "billetterie, la pluie prévisible ou la défaillance d'un prestataire ne sont PAS des cas de force "
                    "majeure. Une liste contractuelle sécurise les deux parties.",
       plain="La force majeure, c'est l'événement vraiment imprévisible qui empêche tout (catastrophe naturelle, "
             "interdiction préfectorale, deuil national). Une billetterie décevante n'en est jamais un !",
       legal_ref="Art. 1218 C. civ.",
       example=(
           "Constituent notamment des cas de force majeure, sous réserve des conditions de l'article 1218 du Code civil : "
           "catastrophe naturelle, incendie du lieu, interdiction administrative de l'évènement, deuil national, épidémie "
           "entraînant des restrictions de rassemblement, grève générale des transports rendant l'accès impossible. "
           "Ne constituent pas des cas de force majeure : l'insuffisance des ventes, les difficultés financières d'une "
           "partie, ou les intempéries pour un évènement en plein air (régies par l'article dédié)."
       ))
    _c(g, "Effets de la force majeure", "select", sort_order=1,
       options=["Résolution sans indemnité (acompte restitué)", "Report à une date convenue",
                "Suspension puis résolution si l'empêchement perdure"],
       tooltip_short="Que se passe-t-il si un cas de force majeure survient ?",
       tooltip_long="L'art. 1218 du Code civil permet la résolution de plein droit en cas d'empêchement définitif, "
                    "ou la suspension si l'empêchement est temporaire. Choisir explicitement l'effet applicable "
                    "évite toute discussion sur le sort du contrat et de l'acompte au moment où l'évènement survient.",
       plain="Dans presque tous les contrats de concert : annulation sans pénalité pour personne, "
             "chacun reprend ses billes (l'acompte est rendu), et on essaie de reporter.")

    # ── 15 — Confidentialité ──────────────────────────────────────────────────
    g = _g("Confidentialité", tooltip="Non-divulgation des conditions du contrat et, pour les évènements privés, de l'évènement lui-même.", sort_order=15)
    _c(g, "Confidentialité des conditions financières", "toggle", sort_order=0, enabled_by_default=False,
       tooltip_short="Les parties s'interdisent de divulguer le montant du cachet et les conditions négociées.",
       tooltip_long="La confidentialité tarifaire protège la stratégie commerciale de l'artiste, dont les cachets "
                    "varient légitimement selon le type d'évènement, le lieu ou la notoriété du client, sans avoir "
                    "à justifier ces écarts publiquement.",
       plain="Personne ne communique le montant du cachet. Courant chez les artistes dont les tarifs varient "
             "selon les évènements.")
    _c(g, "Confidentialité de l'évènement (évènement privé)", "toggle_with_details", sort_order=1, enabled_by_default=False,
       tooltip_short="Évènement privé ou d'entreprise : non-divulgation du lieu, des invités, du client final.",
       tooltip_long="Dans un évènement privé, la confidentialité protège la vie privée du client et de ses invités "
                    "(art. 9 Code civil) : elle porte sur l'existence même de la prestation, l'identité des personnes "
                    "présentes et le lieu, et doit survivre un temps raisonnable après l'évènement.",
       plain="Pour un mariage, un anniversaire ou une soirée d'entreprise : l'artiste ne communique pas sur "
             "l'identité du client, le lieu ni les invités — parfois même pas sur l'existence de la prestation.",
       example=(
           "[Contractant 1] s'engage à la plus stricte confidentialité concernant l'évènement : identité de l'hôte et "
           "des invités, lieu, date et toute information dont il aurait connaissance à l'occasion de sa prestation. "
           "Toute communication publique (y compris sur les réseaux sociaux) relative à l'évènement est subordonnée à "
           "l'accord écrit préalable de l'Organisateur. Cette obligation survit [durée] après la Représentation."
       ))

    # ── 16 — Exclusivité territoriale ─────────────────────────────────────────
    g = _g("Exclusivité territoriale (clause de rayon)", tooltip="Interdiction de se produire à proximité de l'évènement pendant une période donnée.", sort_order=16)
    _c(g, "Clause de rayon", "toggle_with_details", sort_order=0, enabled_by_default=False,
       tooltip_short="L'artiste s'interdit de jouer dans un rayon de X km, Y jours avant/après l'évènement.",
       tooltip_long="Clause usuelle en festival : elle protège l'attractivité de l'évènement. Pour être valable, elle doit "
                    "être proportionnée (rayon, durée et périmètre limités) et ne pas priver l'artiste de sa liberté de "
                    "travailler. Usage : 50 à 100 km, 30 à 90 jours avant / 30 jours après. Compensez une clause large "
                    "par un cachet plus élevé.",
       plain="Le festival ne veut pas que vous jouiez dans la ville d'à côté le mois précédent (sinon son public a déjà "
             "vu votre concert). Négociez le rayon et la durée — et faites payer une exclusivité étendue.",
       example=(
           "[Contractant 1] s'engage à ne pas se produire en concert public, sous son nom de scène, dans un rayon de "
           "[nombre] km autour du lieu de l'évènement, pendant les [nombre] jours précédant et les [nombre] jours suivant "
           "la Représentation, sauf accord écrit de l'Organisateur. Sont exclus de cette interdiction : les prestations "
           "privées non annoncées publiquement et les engagements antérieurs à la signature, notifiés à l'Organisateur."
       ))

    # ── 17 — Résiliation ──────────────────────────────────────────────────────
    g = _g("Résiliation", tooltip="Résiliation du contrat pour inexécution avant la représentation.", sort_order=17)
    _c(g, "Résiliation pour inexécution", "toggle", sort_order=0,
       tooltip_short="Résiliation de plein droit en cas de manquement grave non réparé après mise en demeure.",
       tooltip_long="La résiliation pour inexécution (art. 1224 C. civ.) suppose un manquement suffisamment grave "
                    "et une mise en demeure préalable restée sans effet ; elle permet à la partie non défaillante de "
                    "sortir du contrat sans attendre une décision de justice, sous réserve du contrôle a posteriori du juge.",
       legal_ref="Art. 1224 s. C. civ.",
       plain="Si l'autre partie ne respecte pas un engagement important (pas d'acompte versé, technique absente...), "
             "vous pouvez sortir du contrat après un avertissement écrit resté sans effet.")
    _c(g, "Résiliation pour non-paiement de l'acompte", "toggle", sort_order=1, enabled_by_default=False,
       tooltip_short="Le défaut de versement de l'acompte à l'échéance libère l'artiste de ses engagements.",
       tooltip_long="Le non-paiement de l'acompte à la date convenue est un manquement suffisamment identifiable pour "
                    "justifier une résiliation automatique sans mise en demeure supplémentaire, dès lors que cette "
                    "clause résolutoire est expressément prévue.",
       plain="Si l'organisateur ne paie pas l'acompte à la date prévue, l'artiste peut considérer le contrat comme "
             "caduc et se dégager de son engagement, sans autre formalité.")
    _c(g, "Effets de la résiliation", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Sort de l'acompte, indemnités et frais en cas de résiliation — renvoie au régime d'annulation.",
       tooltip_long="Préciser les effets de la résiliation évite qu'elle ne laisse un vide contractuel sur le sort "
                    "des sommes déjà versées ou dues : en pratique, la résiliation aux torts d'une partie est "
                    "généralement traitée comme une annulation imputable à cette même partie.",
       plain="Ce qui se passe concrètement une fois le contrat résilié : qui garde quoi, qui doit encore quoi. "
             "En général, ça reprend les mêmes règles que pour une annulation.",
       example=(
           "La résiliation prononcée aux torts d'une partie emporte application du régime d'annulation prévu au présent "
           "contrat, l'annulation étant réputée du fait de la partie défaillante. Les sommes dues au titre de prestations "
           "déjà exécutées et les obligations de confidentialité survivent à la résiliation."
       ))

    # ── 18 — Droit applicable et juridiction ──────────────────────────────────
    g = _g("Droit applicable et juridiction compétente", tooltip="Loi applicable au contrat et tribunal compétent en cas de litige.", sort_order=18)
    _c(g, "Droit applicable", "text", sort_order=0, default_value={"text": "Droit français"},
       tooltip_short="Loi applicable au contrat (droit français par défaut).",
       tooltip_long="Pour un contrat exécuté entièrement en France entre parties françaises, cette clause a surtout "
                    "une vertu de clarté ; elle devient déterminante dès qu'un élément d'extranéité existe (artiste "
                    "ou organisateur étranger, tournée internationale).",
       plain="Précise que c'est la loi française qui s'applique en cas de désaccord. Utile surtout si l'une des "
             "parties est étrangère.",
       example="Droit français")
    _c(g, "Juridiction compétente", "text", sort_order=1, enabled_by_default=False,
       tooltip_short="Tribunal territorialement compétent (attention : inopposable aux non-commerçants).",
       tooltip_long="La clause attributive de compétence territoriale n'est valable qu'entre commerçants (art. 48 CPC). "
                    "Si l'une des parties est un particulier ou une association non commerçante, les règles légales de "
                    "compétence s'appliquent malgré la clause.",
       plain="Le tribunal qui jugerait en cas de litige. Attention : cette clause ne s'impose pas si l'une des "
             "parties est un particulier ou une association non commerçante — la loi prévoit alors son propre tribunal.",
       example="[Tribunal compétent]")
    _c(g, "Médiation préalable obligatoire", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="Tentative de résolution amiable (médiation) avant toute action en justice.",
       tooltip_long="Une clause de médiation préalable, si elle est rédigée de façon suffisamment précise, peut être "
                    "opposée par le défendeur pour faire déclarer une action en justice irrecevable tant que la "
                    "médiation n'a pas été tentée : elle a donc une réelle portée procédurale, pas seulement incitative.",
       plain="Avant d'aller au tribunal, les parties s'obligent à tenter une médiation. "
             "Moins cher, plus rapide, et souvent suffisant.")

    # ── 19 — Notifications ────────────────────────────────────────────────────
    g = _g("Notifications", tooltip="Adresses de contact officielles pour toute notification contractuelle.", sort_order=19)
    _c(g, "Email de contact de l'organisateur", "text", sort_order=0,
       tooltip_short="Adresse email officielle de l'organisateur pour les notifications contractuelles.",
       tooltip_long="L'adresse email désignée fait courir les délais de notification prévus au contrat (préavis "
                    "d'annulation, réponse à une demande de report) : elle doit être une adresse effectivement "
                    "surveillée, pas une boîte générique rarement consultée.",
       plain="L'email officiel à utiliser pour tout ce qui est important dans ce contrat (annulation, report...). "
             "Choisissez une adresse que vous consultez vraiment.",
       example="[Email Contractant 2]")
    _c(g, "Email de contact de l'artiste / production", "text", sort_order=1,
       tooltip_short="Adresse email officielle de l'artiste ou de sa production.",
       tooltip_long="Comme pour l'organisateur, cette adresse sert de référence pour le calcul des délais de "
                    "notification contractuels ; en cas de changement en cours de contrat, il est prudent d'en "
                    "informer l'autre partie par écrit.",
       plain="L'email officiel de l'artiste ou de son équipe pour recevoir les communications importantes.",
       example="[Email Contractant 1]")
    _c(g, "Modalités de notification", "textarea", sort_order=2, enabled_by_default=False,
       tooltip_short="Formes admises : email avec accusé, LRAR pour les notifications graves (annulation, résiliation).",
       tooltip_long="Distinguer les notifications courantes (email suffisant) des notifications graves (annulation, "
                    "résiliation, mise en demeure) qui appellent une lettre recommandée avec accusé de réception "
                    "sécurise la preuve de la date et du contenu de l'information transmise.",
       plain="Comment prévenir l'autre partie selon la gravité du sujet : un simple email pour le quotidien, "
             "une lettre recommandée pour les sujets sérieux (annulation, résiliation).",
       example=(
           "Toute notification au titre du présent contrat sera valablement effectuée par courrier électronique aux "
           "adresses désignées ci-dessus, avec demande d'accusé de réception. Les notifications relatives à l'annulation, "
           "au report ou à la résiliation devront être doublées d'une lettre recommandée avec accusé de réception."
       ))

    # ── 20 — Clauses générales ────────────────────────────────────────────────
    g = _g("Clauses générales", tooltip="Stipulations transversales de fin de contrat.", sort_order=20)
    _c(g, "Intégralité de l'accord", "toggle", sort_order=0,
       tooltip_short="Le contrat et ses annexes constituent l'intégralité de l'accord entre les parties.",
       tooltip_long="Cette clause écarte les échanges antérieurs (emails, discussions orales) qui ne seraient pas "
                    "repris dans le contrat et ses annexes : seul l'écrit final signé fait foi entre les parties.",
       plain="Seul ce contrat (et ses annexes signées) compte — pas les emails ou promesses orales échangés avant "
             "la signature.")
    _c(g, "Modification écrite", "toggle", sort_order=1,
       tooltip_short="Toute modification du contrat requiert un avenant écrit signé des deux parties.",
       tooltip_long="Cette clause protège contre les modifications informelles (accord verbal de dernière minute) "
                    "qui seraient difficiles à prouver en cas de litige : tout changement doit être formalisé par "
                    "un avenant écrit et signé par les deux parties.",
       plain="Si on veut changer quelque chose au contrat après signature, il faut un écrit signé par les deux — "
             "un accord oral ne suffit pas.")
    _c(g, "Divisibilité", "toggle", sort_order=2, enabled_by_default=False,
       tooltip_short="La nullité d'une clause n'affecte pas la validité des autres.",
       tooltip_long="Cette clause de divisibilité (ou clause de sauvegarde) évite qu'une clause jugée illégale ou "
                    "abusive n'entraîne l'annulation de l'ensemble du contrat : seule la clause litigieuse est "
                    "écartée, le reste continue à s'appliquer.",
       plain="Si un tribunal annule une clause du contrat (parce qu'elle est illégale par exemple), le reste du "
             "contrat continue de s'appliquer normalement.")
    _c(g, "Clause de non-renonciation", "toggle", sort_order=3, enabled_by_default=False,
       tooltip_short="Ne pas exiger l'application d'une clause ne vaut pas renonciation à celle-ci.",
       tooltip_long="Sans cette clause, la tolérance répétée d'un manquement (par exemple, accepter des paiements "
                    "en retard sans réagir) pourrait être interprétée comme une renonciation tacite au droit d'exiger "
                    "le respect strict de cette obligation à l'avenir.",
       plain="Si une partie ferme les yeux une fois sur un manquement (ex : un petit retard de paiement toléré), "
             "ça ne veut pas dire qu'elle renonce à exiger le respect strict du contrat la prochaine fois.")
    _c(g, "Indépendance des parties", "toggle", sort_order=4,
       tooltip_short="Le contrat ne crée ni lien de subordination, ni société, ni mandat entre les parties.",
       tooltip_long="Clause déclarative utile mais non suffisante : en cas de litige, le juge requalifie selon les "
                    "conditions réelles d'exécution (faisceau d'indices : directives, horaires imposés, matériel fourni, "
                    "intégration à un service organisé). Si l'artiste personne physique n'est pas entrepreneur de "
                    "spectacles, la présomption de salariat de l'art. L7121-3 C. trav. s'applique malgré cette clause.",
       plain="Cette clause rappelle que l'artiste n'est pas salarié de l'organisateur. Attention : l'écrire ne suffit "
             "pas — c'est la réalité de la relation qui compte pour un juge.",
       legal_ref="Art. L7121-3 C. trav.")

    # ── 21 — Annexes ──────────────────────────────────────────────────────────
    g = _g("Annexes", tooltip="Documents annexés faisant partie intégrante du contrat.", sort_order=21)
    _c(g, "Liste des annexes", "textarea", sort_order=0, enabled_by_default=False,
       tooltip_short="Fiche technique, plan de scène, rider hospitality, kit promo, attestations d'assurance...",
       tooltip_long="Les annexes listées et paraphées par les parties ont la même valeur contractuelle que le corps "
                    "du contrat lui-même : un document mentionné mais non joint ou non signé ne peut être invoqué "
                    "en cas de litige.",
       plain="La liste de tous les documents joints au contrat (fiche technique, rider...) qui comptent autant que "
             "le contrat principal — pensez à les dater et signer aussi.",
       example=(
           "Font partie intégrante du présent contrat les annexes suivantes, datées et paraphées par les parties : "
           "Annexe 1 — Fiche technique et plan de scène ; Annexe 2 — Rider hospitality (loges, catering, hébergement) ; "
           "Annexe 3 — Kit promotionnel (visuels, biographie, crédits) ; Annexe 4 — Attestations d'assurance ; "
           "Annexe 5 — Récépissés de déclaration d'entrepreneur de spectacles."
       ))

    db.session.commit()
    return touched
