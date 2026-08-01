# Positionnement — ce que LaProd est, et ce qu'elle refuse d'être

Ce document existe pour une raison précise : c'est lui qui tranche quand une décision
technique est défendable sur le plan de l'ingénierie mais contredit la promesse faite
aux utilisateurs. Toute décision produit ou d'architecture qui touche à l'argent, au
classement du catalogue ou aux données personnelles se lit d'abord ici.

---

## 0. Le prisme de marque

> « Passe de ta passion à ta carrière. »

C'est la phrase qui doit filtrer toute décision de rédaction, sur ce document comme sur
les autres. Elle fixe un cadre précis :

- LaProd ne promet pas le succès, la notoriété ou l'entrée dans l'industrie musicale —
  personne ne peut tenir cette promesse honnêtement.
- LaProd promet des outils professionnels, accessibles dès le premier upload, qui
  permettent de travailler *comme* un professionnel : facturer, protéger son travail,
  contractualiser, être payé.
- LaProd n'est plus décrite comme « une marketplace ». La marketplace de beats, le
  Contract Builder, le mix/mastering, le wallet ou les toplines sont les **outils** d'une
  plateforme de professionnalisation plus large — pas l'identité de la plateforme elle-même.
- La promesse économique du §1 ci-dessous — un marché géré par ses acteurs, pas par des
  intermédiaires — reste la pièce fondatrice de cette histoire : elle est ce qui rend
  crédible l'idée qu'on peut construire une carrière ici plutôt qu'ailleurs. Elle n'est
  pas remplacée, elle est **nommée pour ce qu'elle est** : le socle économique de la
  promesse de marque, pas la promesse elle-même.

Ce chapitre ne change ni le modèle économique, ni les engagements juridiques, ni le
comportement de l'application. Il ne fait que dire dans quel ordre les raconter.

---

## 1. La promesse économique de la marketplace

> « Un marché géré par ses acteurs — pas par des intermédiaires. »

LaProd met en relation des beatmakers, des arrangeurs, des ingénieurs du son et des
artistes. Elle ne s'interpose pas : elle encaisse, sécurise juridiquement, et prélève
une commission visible. C'est l'un des outils qui permettent à un créateur de passer de
sa passion à sa carrière — pas la promesse elle-même (§0). Trois conséquences concrètes,
toutes déjà inscrites dans le code :

| Promesse | Où elle est tenue dans le code |
|---|---|
| La commission porte sur le **net encaissé**, pas sur le prix catalogue | `utils/money.py::split_platform_fee` — « le vendeur finance sa remise sur sa propre part, la commission suit à la baisse » |
| Le catalogue d'un vendeur n'est **jamais** plafonné, à aucun palier | `utils/plans.py` — le palier module une *cadence* d'upload, pas un stock |
| L'utilisateur n'est **jamais** un produit qu'on revend | `src/app/pages/legal/cookies/cookies.component.html`, `utils/gdpr_purge.py` |

### 1.1 Une plateforme solidaire, pas une plateforme gratuite

LaProd n'est pas une utopie du tout-gratuit — elle ne le prétend pas et ne doit jamais le
laisser croire. La position exacte est plus intéressante, et plus honnête :

> Oui, la plateforme est gratuite pour toi. Non, elle n'est pas gratuite pour
> l'hébergeur. On fera notre maximum pour livrer un maximum d'outils et de modules
> gratuits ; en retour, on sera aussi **justes** avec ceux qui nous permettent de la
> faire tourner et de la faire évoluer.

C'est une différence de posture, pas de vocabulaire. Faire de la musique une activité
professionnelle est une démarche entrepreneuriale : ça peut rapporter beaucoup plus que
ça ne coûte, mais ça peut aussi coûter — et prétendre le contraire serait mentir aux
créateurs plutôt que les protéger. Le rôle de LaProd n'est pas de cacher ce coût, c'est
de le rendre lisible et de le répartir équitablement : un maximum de valeur reste gratuite
pour tout le monde, et ceux qui choisissent de payer pour aller plus loin (un outil, une
mise en avant, un palier) financent directement l'infrastructure et l'évolution du
produit — ils ne la subventionnent pas à fonds perdu, ils achètent quelque chose de réel.

Ce que ça exclut n'est donc pas « toute monétisation qui touche le créateur » — ce serait
absurde, un abonnement Premium ou un contrat facturé en font déjà partie et sont assumés.
Ce que ça exclut, c'est de faire sentir au créateur qu'il est la marchandise plutôt que le
client : le tromper sur ce qui influence sa visibilité, monétiser ses données plutôt que
son consentement à payer, ou lui vendre une urgence fabriquée. La ligne est le §4.

---

## 2. Les engagements publics qui contraignent l'ingénierie

Ce sont des textes **publiés**, opposables. Les modifier n'est pas un détail de rédaction :
c'est un changement de positionnement, qui se décide avant d'écrire la moindre ligne.

### 2.1 Cookies et traçage — `/cookies`

Le texte en ligne affirme, mot pour mot :

- « aucun cookie **publicitaire** ou de tracking comportemental tiers » ;
- « aucun pixel publicitaire (Facebook Pixel, Google Ads, etc.) » ;
- « aucun cookie de remarketing » ;
- « aucun outil d'analytics tiers à des fins de profilage comportemental ».

**Conséquence directe** : toute régie tierce (AdSense, Taboola, réseaux programmatiques,
AdMob dans le WebView Capacitor) est *hors positionnement*. Elle exigerait une bannière
de consentement (CMP), la réécriture de trois pages légales, et la perte de l'argument
qui différencie LaProd de ses concurrents. Voir `docs/roadmap.md` § Régie interne pour
l'alternative retenue.

### 2.2 Sécurité du navigateur — CSP stricte

`nginx/nginx.conf` définit un `$csp` en liste blanche : `script-src` n'autorise que
`'self'`, Stripe, jsDelivr et Cloudflare Turnstile. Un tag publicitaire tiers impose
d'ouvrir `script-src`, `frame-src` et `connect-src` à des domaines arbitraires — c'est-à-dire
de démonter la protection. Le projet a déjà payé le prix d'une CSP mal maîtrisée
(incident du critical CSS inliné, navbar sans style en production).

### 2.3 Le registre de langue est un engagement, pas une coquetterie

`utils/plans.py` documente deux registres :

- **TU** — l'indépendant (artiste, beatmaker, ingénieur). C'est le registre de la
  marketplace : home, track-detail, commande mix/master, licences.
- **VOUS** — la structure (SMAC, festival, club, label). C'est le registre du Contract
  Builder et du Contract Analyzer.

Un texte rédigé dans le mauvais registre décrédibilise l'outil au moment précis où il
doit inspirer confiance. Tout nouveau texte visible reprend le registre de la surface
sur laquelle il s'affiche. C'est cette règle, et non une exception, qui justifie que
l'onglet « Producteur » de la landing page (§0) parle en VOUS quand les trois autres
onglets — Artiste, Beatmaker, Ingénieur — parlent en TU : le Producteur s'adresse à une
structure, pas à un indépendant.

### 2.4 Fidélité et transparence, jamais la sensation de vache à lait

Les paliers sont conçus pour qu'on y monte « le jour où on en a besoin — pas parce qu'on
nous y pousse ». Le corollaire technique est déjà appliqué dans le module premium :
**on ne floute jamais un contenu, on n'invente jamais une urgence**. Un contenu réservé
reste lisible ; c'est le bouton d'action qui devient un CTA Premium, et l'autorisation
est vérifiée côté serveur (`can_*` dans `utils/plans.py` / `serializers.capabilities_dict`).

Le test à appliquer avant toute nouvelle option payante n'est pas « est-ce qu'on peut
facturer ça ? » — presque tout le peut — mais « est-ce que le créateur, en payant, a le
sentiment d'acheter un outil qui l'aide, ou celui qu'on lui extrait de la valeur parce
qu'il n'a pas le choix ? ». Le premier renforce la confiance ; le second la détruit, même
quand le prix est raisonnable. Concrètement : toute forme de mise en avant payante
**ajoute** de la visibilité à un vendeur, elle ne **retire** rien aux autres, et elle est
toujours identifiée comme telle (§4.3).

---

## 3. Modèle économique — l'état réel

| Source | Statut | Mécanique |
|---|---|---|
| Commission marketplace 10 % | En production | `utils/money.py::split_platform_fee`, wallet interne, payout Stripe Connect |
| Abonnements (4 paliers) | En production | `utils/plans.py`, `routes/premium_api.py` |
| Campagne « toute la plateforme » | En production | 19,99 € l'unité — `utils/campaign_service.py::SUPER_PREMIUM_PRICE_EUR` |
| Contract Builder (Pro Structuré) | En production | 49,99 €/mois, argument du ratio vs cabinet juridique |
| **Mise en avant payante (régie interne)** | **À construire** | `docs/roadmap.md` § Chantier 1 |

L'objectif assigné au chantier régie est explicite et modeste : **couvrir le coût
d'infrastructure** (VPS OVH + domaine + sauvegardes) — pas maximiser un revenu
publicitaire. C'est une brique de plus dans le même principe que les paliers ou le
Contract Builder : un outil que le créateur choisit d'acheter parce qu'il lui rend
service, pas un espace vendu à un tiers sur son dos. Voir §1.1.

---

## 4. Le test de cohérence

Avant d'ajouter une fonctionnalité qui rapporte de l'argent, elle doit passer ces cinq
questions. Une seule réponse « non » suffit à changer la conception.

1. **Est-ce que l'utilisateur qui paie obtient quelque chose de mesurable ?**
   (Pas « de la visibilité » en général : des impressions, des clics, des ventes attribuées.)
2. **Est-ce que celui qui ne paie pas perd quelque chose ?**
   Si oui, ce n'est pas une option — c'est une dégradation.
3. **Est-ce identifiable au premier coup d'œil ?**
   Une mise en avant payante non signalée est une pratique commerciale trompeuse
   (art. L.121-1 du Code de la consommation) et une infraction au règlement européen
   *Platform-to-Business* 2019/1150 (art. 5 : obligation de décrire les paramètres
   principaux de classement et toute rémunération qui les influence).
4. **Est-ce que ça survit sans dépendance tierce ?**
   Pas de JS externe, pas de cookie tiers, pas de modification de la CSP.
5. **Est-ce que le texte légal publié reste vrai après l'implémentation ?**
   Si non, la mise à jour des pages `/cgu`, `/privacy` et `/cookies` fait partie du
   périmètre — pas d'un « suivi ultérieur ».

---

## 5. Ce qui est explicitement écarté

Ce tableau n'écarte pas « la monétisation qui touche le créateur » en général — les
abonnements, le Contract Builder ou une mise en avant achetée en font partie et sont
assumés (§1.1). Il écarte les formes précises qui feraient basculer le créateur du
statut de client à celui de matière première.

| Écarté | Motif |
|---|---|
| Régie tierce (AdSense / programmatique / AdMob) | §2.1, §2.2 — et rendement dérisoire au volume de trafic actuel (voir `docs/roadmap.md`) |
| Revente ou enrichissement de données utilisateurs | §1, `utils/gdpr_purge.py` |
| Publicité audio insérée dans le player | Le player est l'outil de travail de l'acheteur ; le dégrader détruit la conversion |
| Interstitiels, pop-ups, compte à rebours factices | §2.4 |
| Placement payant non signalé dans les résultats | §4.3 |
| Suppression de la publicité vendue comme avantage Premium | Créerait une incitation à dégrader l'expérience gratuite — l'inverse de §2.4 |
