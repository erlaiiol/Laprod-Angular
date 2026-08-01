# API — conventions et carte des endpoints

API JSON servie par Flask sous `/api`, consommée par le front Angular et par le WebView
Capacitor. Tout ce qui suit est **contraignant** : le front dépend de la forme exacte des
réponses, et `src/testing/data/` en contient des copies typées.

---

## 1. Enveloppe de réponse

Deux helpers, définis dans `serializers.py`, et rien d'autre :

```python
from serializers import ok, err

ok(data=None, message='', status=200, level='success', code=None)
err(message, level='error', code=None, status=400, data=None)
```

Succès :
```json
{ "success": true, "data": { ... }, "feedback": { "level": "success", "message": "..." } }
```

Erreur :
```json
{ "success": false, "feedback": { "level": "error", "message": "..." }, "code": "QUOTA_REACHED" }
```

- `data` n'est présent que s'il y a des données. `feedback` n'est présent que si un
  message est destiné à l'utilisateur — le front l'affiche automatiquement en toast.
- `message` est **rédigé pour l'utilisateur final**, en français, sans jargon technique
  ni détail d'implémentation. La trace technique va dans `current_app.logger`, jamais
  dans la réponse.
- `code` est un identifiant stable et machine-lisible (`SLOT_TOO_SOON`, `QUOTA_REACHED`,
  `connect_required`…). C'est lui que le front teste, jamais le texte du message.

---

## 2. Décorateurs — ordre imposé

```python
@bp.route('/api/domaine/action', methods=['POST'])
@csrf.exempt              # ← TOUJOURS en premier après @route
@jwt_required()
@limiter.limit('20 per hour')
@handle_route_exceptions
@require_user
@commit_or_rollback
def action(current_user):
    ...
```

**Pourquoi `@csrf.exempt` en premier** : Flask-WTF évalue l'exemption sur la fonction
enregistrée dans `view_functions`. Appliqué sous `@jwt_required()`, le contrôle CSRF peut
malgré tout s'exécuter en production — et les tests ne le voient pas, car Flask désactive
le CSRF quand `TESTING=True`. `routes/campaign_api.py` est la référence d'ordre correct.

| Décorateur | Provenance | Rôle |
|---|---|---|
| `csrf.exempt` | `extensions` | Route API JSON authentifiée par JWT |
| `jwt_required()` | flask-jwt-extended | Auth. `optional=True` via `verify_jwt_in_request` pour les routes semi-publiques |
| `limiter.limit()` | `extensions` | Anti-abus. Obligatoire sur tout POST public ou coûteux |
| `handle_route_exceptions` | `utils/crud_helpers` | Traduit `EntityNotFound` / `EntityForbidden` en réponses propres |
| `require_user` | `utils/auth_helpers` | Injecte `current_user`, 401 sinon |
| `require_admin` | `utils/auth_helpers` | Idem + contrôle `is_admin` |
| `commit_or_rollback` | `utils/crud_helpers` | Commit en sortie, rollback sur exception |

---

## 3. Autorisation

1. **Jamais** de comparaison littérale de `subscription_plan`. On passe par
   `user.can_*` (dérivés de `utils/plans.py`) ou par `plans.plan_rank(...) >= plans.plan_rank(plans.PREMIUM)`.
2. Le contrôle est **toujours** côté serveur. L'UI qui grise un bouton est un confort,
   pas une protection : chaque route de mutation revérifie la capacité.
3. La propriété d'une ressource se vérifie par `require_ownership(entity, 'owner_id', current_user)`.
4. Les capacités renvoyées au front proviennent de `serializers.capabilities_dict()` —
   la même source que celle qui autorise l'API.

---

## 4. Pagination

Forme unique, tous endpoints paginés confondus :

```json
{
  "tracks": [ ... ],
  "pagination": { "page": 1, "per_page": 20, "total": 137, "pages": 7 }
}
```

- `per_page` est plafonné côté serveur (100 sur `/api/tracks`).
- `pages` vaut au minimum 1, même quand `total` vaut 0.
- **Le tableau paginé ne contient que des éléments comptés dans `total`.** Tout contenu
  injecté (recommandation transverse, mise en avant, encart) part dans une **clé
  distincte** — sinon `total` ment et la pagination se décale.

---

## 5. Types et pièges de sérialisation

| Type Python | À faire | Sinon |
|---|---|---|
| `Decimal` (Numeric) | `float(x) if x is not None else None` | JSON string, comparaisons cassées côté front |
| `datetime` | `.isoformat()` | Format dépendant de la locale |
| `Enum` | `.value` | Sérialisation illisible |
| Clés `int` dans un dict caché en Redis | reconvertir `{int(k): v ...}` au chargement | `json.dumps` transforme les clés en `str` |

---

## 6. Carte des domaines

36 blueprints, enregistrés dans `app.py` (imports centralisés dans `routes/__init__.py`).

| Domaine | Blueprint | Principales routes |
|---|---|---|
| Catalogue | `tracks_api` | `GET /api/tracks`, `GET /api/track/<id>`, `POST /api/post`, `POST /api/track/<id>/view`, `GET /api/my/view-stats` |
| Filtres | `tags_filters_api` | tags, styles, gammes, artistes similaires |
| Recommandation | `recommendation_api` | recommandations personnalisées |
| Streaming | `streaming_service` | `/api/stream/tracks/<id>/preview` (watermarquée 1:30, publique — download & topline), `/full` (titre entier, écoute publique), `/download/<format>` (attachment, achat requis) |
| Auth | `auth_api` | login, register, refresh, OAuth Google, vérification email |
| Profils | `main_api` | profil public, édition, sécurité |
| Paiement beat | `payment_track_api` | checkout Stripe, succès |
| Paiement mix | `payment_mixmaster_api` | acompte, solde, révisions |
| Webhooks | `stripe_webhook_api` | événements Stripe |
| Wallet | `wallet_api` | solde, transactions, retrait |
| Connect | `stripe_connect_api` | onboarding vendeur |
| Abonnements | `premium_api` | `GET /plans`, `POST /subscribe`, `POST /activate` |
| Licences / contrats | `licenses_api`, `contracts_api`, `invoice_api` | contrat PDF, facture |
| Contract Builder | `contract_builder_api` | templates, clauses, génération, signature |
| Contract Analyzer | `contract_analyzer_api` | analyse de contrat déposé |
| Mix & Master | `mixmaster_api`, `mixmaster_media_api` | commandes, livraisons, révisions |
| Toplines | `toplines_api` | enregistrement, publication |
| Playlists / favoris | `playlist_api`, `favorites_api` | CRUD, couverture |
| Achats | `purchases_api` | historique acheteur |
| Promo | `promo_api` | codes promo vendeur |
| Campagnes | `campaign_api` | audiences, créneaux, quotas, envoi |
| Producteur | `roster_api`, `planning_api`, `royalties_api` | roster, planning + iCal, splits |
| Structures | `structure_api` | structures Pro |
| Témoignages | `testimonials_api` | demandes et publication |
| Jobs | `job_status_api` | suivi des tâches RQ |
| Admin | `admin_api` | modération, statistiques, support |
| SEO | `og_preview` | cartes Open Graph |

---

## 7. Ajouter un endpoint — checklist

- [ ] Blueprint du bon domaine (nouveau fichier si le domaine est nouveau, + `routes/__init__.py` + `app.py`)
- [ ] `@csrf.exempt` en premier sur les POST/PUT/DELETE
- [ ] `@limiter.limit()` si la route est publique, coûteuse, ou écrit en base
- [ ] Réponse construite avec `ok()` / `err()`, message rédigé pour un humain
- [ ] Code d'erreur stable (`code=`) pour chaque cas que le front doit distinguer
- [ ] Sérialisation dans `serializers.py`, `float()` sur les montants
- [ ] Autorisation revérifiée serveur, via `can_*` ou `plan_rank`
- [ ] Aucune relation SQLAlchemy lue dans une boucle sans `selectinload`
- [ ] Test pytest du chemin nominal **et** du refus d'autorisation
- [ ] Objet de test ajouté à `src/testing/data/` si le front le consomme
