# Règles de développement

Ce document est la référence courte à charger avant d'écrire du code sur LaProd — humain
ou agent. Chaque règle vient d'un problème réellement rencontré sur ce projet. Elles ne
sont pas des préférences de style : les enfreindre a déjà produit une faille
d'autorisation, un site sans CSS en production, une pagination cassée ou un certificat
expiré.

Ordre de lecture pour une nouvelle fonctionnalité :
`positioning.md` → `architecture.md` → ce document → `api.md` / `conventions.md`.

---

## R1 — L'autorisation vit côté serveur, dans une source unique

- Jamais de comparaison littérale de `subscription_plan`. `user.can_*` ou
  `plans.plan_rank()`, rien d'autre.
- Toute route de mutation revérifie la capacité, même si l'UI a déjà grisé le bouton.
- Une capacité exposée au front vient de `serializers.capabilities_dict()` — la même
  source que celle qui protège l'API. Une case cochée dans l'UI qui ne correspond à
  aucun droit réel est un mensonge commercial.
- Nouvelle règle d'autorisation ⇒ **deux** tests : autorisé et refusé.

## R2 — L'argent passe par `utils/money.py`

Pas de `float`, pas de `int(x * 100)`, pas de `/ 100`, pas de double arrondi.
`remise + net == brut` et `commission + revenu == total` sont exacts par construction.
La commission porte sur le montant **réellement encaissé**, jamais sur le prix catalogue.

## R3 — Le wallet ne connaît que des montants positifs

`WalletTransaction.amount > 0` et `Wallet.balance_available >= 0` sont des contraintes en
base. Un débit est une transaction de montant **positif** avec un `type` de débit. Toute
écriture concurrente sur un solde prend un verrou de ligne
(`select(Wallet).with_for_update()`). On ne dépense jamais du solde `pending`.

## R4 — Aucun code ne suppose que Redis répond

Redis est configuré en `allkeys-lru` avec 128 Mo : une clé peut disparaître à tout moment.
Lecture et écriture de cache sont enveloppées dans `try/except: pass`, et le chemin sans
cache reste fonctionnel. Le module propriétaire exporte son `invalidate_*_cache()`.

## R5 — Un classement paginé calculé en fond doit être figé pendant la pagination

Un job asynchrone qui se termine entre la page 1 et la page 2 réordonne la liste et
casse la navigation. Le schéma de référence est dans `routes/tracks_api.py::get_tracks` :
snapshot Redis à TTL courte, ordre conservé, filtres appliqués **en préservant l'ordre**
(le rang fait office de score) au lieu de repartir sur un tri par date.

## R6 — Un tableau paginé ne contient que ce qui est compté dans `total`

Recommandation transverse, contenu sponsorisé, encart promotionnel : **clé JSON distincte**.
Sinon `total` ment, `pages` se décale, et le front affiche des doublons entre deux pages.

## R7 — `@csrf.exempt` est le premier décorateur après `@route`

Sous `@jwt_required()`, l'exemption peut ne pas s'appliquer en production — et les tests
ne le voient pas, car le CSRF est désactivé quand `TESTING=True`.
Référence d'ordre correct : `routes/campaign_api.py`.

## R8 — Pas de relation SQLAlchemy lue dans une boucle sans `selectinload`

Chaque accès lazy en boucle est une requête SQL de plus. Trois requêtes au total, quelle
que soit la taille de la liste.

## R9 — Les cascades passent par la collection, jamais par `passive_deletes`

FK `NOT NULL` vers `user` ⇒ `cascade='all, delete-orphan'` sur le backref. SQLite ne
force pas les clés étrangères en test : un `passive_deletes=True` passerait les tests et
casserait la suppression de compte en production.

## R10 — Rien d'inline dans le HTML, rien de tiers dans la CSP

Aucun `onload=` / `onerror=` dans un template (`ImgFallbackDirective` existe pour ça).
Ajouter un domaine à `$csp` est une décision d'architecture qui se discute avec
`docs/positioning.md` en main, pas un ajustement de configuration.

## R11 — Angular : OnPush, signals, et `untracked()` dans les `effect()`

`ChangeDetectionStrategy.OnPush` sur tout composant. Un `effect()` dont une branche lit
un signal et l'autre non se comporte différemment au premier et au deuxième déclenchement :
toute lecture « pour information » passe par `untracked()`. Un état qui doit se rafraîchir
à la connexion s'écrit avec un `effect()` sur `isLoggedIn()`, pas avec un
`afterNextRender` one-shot.

## R12 — Aucune couleur hex en dur dans un `.scss`

`v.$primary`, `v.$bg-surface`, `rgba(v.$tag-green, 0.12)`. Un hex en dur casse le thème
clair sans que rien ne le signale.

## R13 — La requête HTTP ne fait jamais de travail long

Traitement audio, emails, PDF lourds, calculs de recommandation → RQ. Récurrent →
APScheduler. Le front suit l'avancement via `job_status_api`.

## R14 — Les messages d'erreur sont écrits pour un humain

`err()` reçoit un texte en français, sans jargon ni détail d'implémentation, plus un
`code` stable que le front teste. La trace technique (type d'exception, `request_id`
Stripe, identifiants) va dans `current_app.logger`.

## R15 — Une migration non testée met le site hors ligne

`entrypoint.sh` applique `flask db upgrade head` au démarrage de `web`. Relire la
migration générée, écrire le `downgrade`, créer explicitement les types enum PostgreSQL,
prévoir un `server_default` pour toute colonne `NOT NULL` ajoutée à une table peuplée.

## R16 — Une fonctionnalité visible se termine par une entrée `updates.json`

Français, ton direct, `short` en une phrase, `detail` en 2–3 phrases orientées bénéfice,
aucun terme technique, `sent_at: null`. Les refactorisations internes n'y figurent pas.

## R17 — Si le texte légal publié devient faux, sa mise à jour fait partie du périmètre

`/cgu`, `/privacy`, `/cookies` sont des engagements opposables. Une fonctionnalité qui
les contredit n'est pas « à finir plus tard » : soit elle est conçue pour les respecter,
soit sa mise en conformité est livrée avec elle.

---

## Checklist avant de rendre une passe

- [ ] `tsc --noEmit` sans erreur
- [ ] `ng build` passe ; `pytest` vert ; `ng test` (Vitest) vert
- [ ] Aucun `console.log` oublié, aucun hex en dur dans les SCSS
- [ ] `float()` sur tout champ monétaire ajouté à un serializer
- [ ] `selectinload` sur toute relation lue en boucle
- [ ] `@csrf.exempt` en tête sur les nouvelles routes de mutation
- [ ] Nouveau composant : `OnPush` présent ; images de liste : `loading="lazy"`
- [ ] Test du refus d'autorisation, pas seulement du chemin nominal
- [ ] Responsive vérifié ≤ 600 px, thème clair **et** sombre
- [ ] Entrée `updates.json` si l'utilisateur le remarque
- [ ] Pages légales relues si la fonctionnalité touche données / classement / paiement
