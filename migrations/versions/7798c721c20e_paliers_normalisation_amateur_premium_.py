"""paliers: normalisation amateur->premium, pro->pro_structure

Migration de DONNÉES (aucun changement de schéma).

Les paliers passent de 3 à 4 : free / premium / semi_pro / pro_structure.
Le code normalise déjà les anciens identifiants à la lecture (utils/plans.py,
LEGACY_ALIASES), donc rien ne casse sans cette migration — mais laisser des
valeurs héritées en base garantit qu'on trébuchera dessus un jour, dans une
requête SQL écrite à la main ou un export.

Correspondance retenue :
  amateur -> premium         (même positionnement : l'indépendant amateur)
  pro     -> pro_structure   (accès total au contract builder, ce qu'ils ont payé)

'pro' NE devient PAS 'semi_pro' : ce serait retirer à un abonné payant l'accès
illimité au contract builder qu'il a acheté. On n'accorde jamais moins que ce qui
a été payé — même au prix d'être plus généreux que la nouvelle grille.

Revision ID: 7798c721c20e
Revises: 6d617233132b
Create Date: 2026-07-14 20:41:06.914456

"""
from alembic import op
import sqlalchemy as sa


revision = '7798c721c20e'
down_revision = '6d617233132b'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE \"user\" SET subscription_plan = 'premium' "
        "WHERE subscription_plan = 'amateur'"
    ))
    conn.execute(sa.text(
        "UPDATE \"user\" SET subscription_plan = 'pro_structure' "
        "WHERE subscription_plan = 'pro'"
    ))


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE \"user\" SET subscription_plan = 'amateur' "
        "WHERE subscription_plan = 'premium'"
    ))
    # semi_pro n'existait pas avant : on le ramène au plan payant le plus proche
    # vers le BAS ('amateur'), pour ne pas accorder rétroactivement un accès Pro.
    conn.execute(sa.text(
        "UPDATE \"user\" SET subscription_plan = 'amateur' "
        "WHERE subscription_plan = 'semi_pro'"
    ))
    conn.execute(sa.text(
        "UPDATE \"user\" SET subscription_plan = 'pro' "
        "WHERE subscription_plan = 'pro_structure'"
    ))
