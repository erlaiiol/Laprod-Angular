#!/bin/sh
set -e

# =============================================================================
# Fix permissions sur les volumes montés depuis le host (static, logs)
# L'entrypoint tourne en root pour pouvoir chown, puis bascule vers appuser
# via gosu avant de lancer gunicorn.
# =============================================================================

# Créer tous les sous-dossiers requis (idempotent — mkdir -p ne fail pas si présent)
mkdir -p \
  /usr/src/app/db_assets/audio \
  /usr/src/app/db_assets/images/profiles \
  /usr/src/app/db_assets/contracts \
  /usr/src/app/db_assets/invoices \
  /usr/src/app/db_assets/mixmaster/uploads \
  /usr/src/app/db_assets/mixmaster/processed \
  /usr/src/app/db_assets/mixmaster/previews \
  /usr/src/app/db_assets/mixmaster/samples \
  /usr/src/app/logs

# Donner la propriété à appuser et s'assurer qu'il peut lire/écrire
# chmod u+rwX : r/w sur tous les fichiers + x sur les dossiers uniquement
chown -R appuser:appuser /usr/src/app/db_assets /usr/src/app/logs
chmod -R u+rwX /usr/src/app/db_assets /usr/src/app/logs

echo "=== LaProd - Démarrage ==="

# Migrations et création admin : tournent en tant qu'appuser via gosu
echo ">>> Migrations base de données..."
gosu appuser uv run flask db upgrade head
echo ">>> Migrations OK"

echo ">>> Seed contract builder (no-op si déjà peuplé)..."
gosu appuser uv run flask seed-contract-builder
echo ">>> Seed OK"

echo ">>> Création du compte admin..."
gosu appuser uv run python -c "
from app import app
from extensions import db
from models import User
from datetime import datetime
import os

with app.app_context():
    if User.query.filter_by(username='admin').first():
        print('Admin existe deja')
    else:
        admin = User(
            username='admin',
            email='admin@laprod.net',
            is_admin=True,
            signature='Admin LaProd',
            account_status='active',
            email_verified=True,
            terms_accepted_at=datetime.now(),
            user_type_selected=True
        )
        admin.set_password(os.environ.get('ADMIN_PASSWORD', 'CHANGE_ME_NOW'))
        db.session.add(admin)
        db.session.commit()
        print('Admin cree avec succes')
"
echo ">>> Admin OK"

if [ "$FLASK_ENV" = "development" ]; then
    echo ">>> Démarrage Flask dev server (hot-reload)..."
    exec gosu appuser uv run flask run --host=0.0.0.0 --port=5000
else
    # Calcul dynamique du nombre de workers : (2 x CPU) + 1
    WORKERS=$((2 * $(nproc) + 1))
    echo ">>> Démarrage gunicorn ($WORKERS workers)..."
    exec gosu appuser uv run gunicorn \
        --config gunicorn.conf.py \
        --workers $WORKERS \
        --preload \
        app:app
fi
