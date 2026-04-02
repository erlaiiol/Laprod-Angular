#!/bin/sh
set -e

# =============================================================================
# Fix permissions sur les volumes montés depuis le host (static, logs)
# L'entrypoint tourne en root pour pouvoir chown, puis bascule vers appuser
# via gosu avant de lancer gunicorn.
# =============================================================================
chown -R appuser:appuser /usr/src/app/static /usr/src/app/logs 2>/dev/null || true

echo "=== LaProd - Démarrage ==="

# Migrations et création admin : tournent en tant qu'appuser via gosu
echo ">>> Migrations base de données..."
gosu appuser uv run flask db upgrade
echo ">>> Migrations OK"

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
        --workers $WORKERS \
        --bind 0.0.0.0:5000 \
        --timeout 120 \
        --preload \
        --worker-tmp-dir /dev/shm \
        --max-requests 1000 \
        --max-requests-jitter 50 \
        --access-logfile - \
        --error-logfile - \
        app:app
fi
