"""Migration one-shot : corrige subscription_plan pour les comptes déjà expirés.

Avant l'ajout du job planifié run_premium_expiry_downgrade (utils/scheduled_tasks.py),
rien ne remettait subscription_plan à 'free' quand premium_expires_at était dépassé —
seul is_premium_active (calculé à la volée) reflétait le vrai statut. Ce script aligne
une bonne fois le stock existant, SANS notifier les utilisateurs (pas d'email surprise
à des comptes expirés depuis parfois longtemps). Le job planifié prend ensuite le relai
pour les expirations futures, avec notification.

Idempotent : relançable à volonté, ne touche que les lignes encore désynchronisées.

Usage (depuis la racine du projet) :

    python scripts/backfill_lapsed_premium_plan.py --dry-run   # liste sans écrire
    python scripts/backfill_lapsed_premium_plan.py             # applique
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
from extensions import db
from models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--dry-run', action='store_true',
                        help="liste les comptes concernés sans écrire en base")
    args = parser.parse_args()

    with app.app_context():
        now = datetime.now()
        lapsed = User.query.filter(
            User.subscription_plan != 'free',
            User.premium_expires_at.isnot(None),
            User.premium_expires_at < now,
        ).all()

        if not lapsed:
            print("Aucun compte désynchronisé — rien à faire.")
            return 0

        for user in lapsed:
            print(f"  #{user.id:<6} {user.username:<25} {user.subscription_plan:<8} "
                  f"expiré le {user.premium_expires_at:%d/%m/%Y}")

        if args.dry_run:
            print(f"\n[dry-run] {len(lapsed)} compte(s) seraient repassés en 'free'.")
            return 0

        for user in lapsed:
            user.subscription_plan = 'free'
        db.session.commit()
        print(f"\n{len(lapsed)} compte(s) repassé(s) en 'free'.")
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
