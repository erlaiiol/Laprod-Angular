# LaProd — Marketplace de licences musicales

**LaProd** est une plateforme web full-stack dédiée à la mise en relation entre beatmakers, arrangeurs et artistes. Les beatmakers y vendent des licences musicales (MP3, WAV, Stems) et proposent des services de mix/mastering. Les artistes achètent des beats et commandent des prestations d'ingénierie sonore.

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Frontend | Angular 21 (standalone components, signals, WaveSurfer.js) |
| Backend | Flask 3 + SQLAlchemy 2 (Python 3.11) |
| Base de données | PostgreSQL 15 |
| Cache / files | Redis + RQ (workers asynchrones) |
| Paiement | Stripe (checkout, webhooks, wallet interne) |
| Auth | JWT (Flask-JWT-Extended) + Google OAuth (Authlib) |
| Stockage fichiers | Système de fichiers local (`db_assets/`) |
| Reverse proxy | nginx |
| Déploiement | Docker Compose (OVH VPS — `deploy@51.77.192.230`) |

---

## Architecture du projet

```
LaProd-Angular/
├── src/                    # Frontend Angular
│   ├── app/
│   │   ├── pages/          # Pages (home, track-detail, dashboard, mixmaster, legal…)
│   │   ├── components/     # Composants réutilisables (track-card, player, modals…)
│   │   ├── services/       # Services Angular (auth, player, track, playlist…)
│   │   ├── guards/         # Route guards (authGuard, adminGuard)
│   │   └── layout/         # Navbar, footer, player
│   └── styles/
│       ├── _variables.scss # Palette de couleurs centralisée (v.$primary, v.$gold…)
│       └── _mixins.scss    # Mixins SCSS partagés (badge, btn-ghost)
├── routes/                 # Blueprints Flask (auth, tracks, dashboard, mixmaster…)
├── tasks/                  # Workers RQ (traitement audio, notifications…)
├── models.py               # Modèles SQLAlchemy
├── serializers.py          # Sérialisation JSON des entités
├── helpers.py              # CRUD helpers partagés
├── config.py               # Configuration Flask (ENV, DEBUG, STRIPE…)
├── nginx/                  # Configuration nginx + TLS
├── docker-compose.yml      # Production
└── docker-compose.dev.yml  # Développement local
```

---

## Prérequis

- Node.js 20+
- Python 3.11+
- PostgreSQL 15
- Redis 7
- Docker & Docker Compose (pour le déploiement)

---

## Setup local (développement)

### 1. Cloner le dépôt

```bash
git clone <url-du-repo>
cd LaProd-Angular
```

### 2. Backend Flask

```bash
python -m venv venv
source venv/bin/activate
pip install -r pyproject.toml   # ou pip install -e .

cp .env.example .env            # remplir les variables
flask db upgrade                # migrations Alembic
python app.py                   # serveur de dev Flask (port 5000)
```

### 3. Worker RQ (audio processing)

```bash
rq worker --with-scheduler
```

### 4. Frontend Angular

```bash
npm install
ng serve                        # http://localhost:4200
```

Le proxy Angular (`proxy.conf.json`) redirige `/api` → `http://localhost:5000`.

---

## Variables d'environnement

Créer un fichier `.env` à la racine (ne jamais committer) :

```env
# Flask
FLASK_ENV=development
SECRET_KEY=<clé secrète>

# Base de données
DATABASE_URL=postgresql://user:password@localhost/laprod

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=<clé JWT>

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Email (SMTP)
MAIL_SERVER=smtp.example.com
MAIL_USERNAME=...
MAIL_PASSWORD=...
```

---

## Déploiement (production — OVH)

```bash
# Sur le serveur
ssh deploy@51.77.192.230
cd /var/www/LaProd/Laprod-Angular/Laprod-Angular

git pull
docker compose up -d --build
```

Pour reconstruire uniquement le frontend :

```bash
docker compose up -d --build frontend
```

Pour reconstruire uniquement le backend :

```bash
docker compose up -d --build web
```

---

## Fonctionnalités principales

- **Marketplace de beats** — catalogue filtrable par BPM, tonalité, style, gamme ; algorithme de recommandation basé sur des critères musicaux réels
- **Licences musicales** — MP3, WAV, Stems à la carte ; contrat PDF généré automatiquement à l'achat ; droits calés sur le budget
- **Mix & Mastering** — commande de prestations d'ingénierie sonore avec paiement progressif (acompte + solde à la livraison), briefing détaillé, révisions
- **Analyse de contrats** — dépôt de n'importe quel contrat musical pour analyse des droits cédés, exclusivités et durée
- **Playlists** — création, gestion, image de couverture générée ou uploadée
- **Wallet interne** — accumulation des revenus, payout Stripe à la demande
- **Premium** — abonnement mensuel/annuel ; fonctionnalités Pro et accès topline
- **Topline** — système de réponse audio sur les beats (artistes enregistrent par-dessus)
- **Gamification** — concours de beats (à venir)
- **OAuth** — connexion Google
- **Notifications** — système interne temps réel

---

## Philosophie produit

LaProd est conçu par des musiciens pour des musiciens. L'objectif est une rémunération juste pour chaque créateur et un marché géré par ses acteurs — pas par des intermédiaires. Chaque fonctionnalité de paiement, contrat ou licence est pensée pour protéger à la fois l'acheteur et le vendeur.

---

## Contact

- Site : [laprod.net](https://laprod.net)
- Email : [contact@laprod.net](mailto:contact@laprod.net)
