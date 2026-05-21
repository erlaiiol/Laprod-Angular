"""Premium subscription_plan + is_certified_master_engineer

Revision ID: a1b2c3d4e5f6
Revises: ca5c5cbf0864
Create Date: 2026-05-21 10:00:00.000000

Remplace la colonne booléenne is_premium par subscription_plan (free|amateur|pro).
Ajoute is_certified_master_engineer pour la spécialisation mastering.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'b0cf100bcfd7'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Ajouter subscription_plan avec valeur par défaut 'free'
    op.add_column('user', sa.Column(
        'subscription_plan', sa.String(20), nullable=False, server_default='free'
    ))

    # 2. Migrer les abonnements actifs vers 'amateur'
    op.execute("""
        UPDATE "user"
        SET subscription_plan = 'amateur'
        WHERE is_premium = TRUE
          AND (premium_expires_at IS NULL OR premium_expires_at > NOW())
    """)

    # 3. Supprimer l'ancienne colonne is_premium
    op.drop_column('user', 'is_premium')

    # 4. Ajouter is_certified_master_engineer
    op.add_column('user', sa.Column(
        'is_certified_master_engineer', sa.Boolean(), nullable=False, server_default='false'
    ))


def downgrade():
    # Restaurer is_premium depuis subscription_plan
    op.add_column('user', sa.Column(
        'is_premium', sa.Boolean(), nullable=False, server_default='false'
    ))
    op.execute("""
        UPDATE "user"
        SET is_premium = TRUE
        WHERE subscription_plan != 'free'
    """)
    op.drop_column('user', 'subscription_plan')
    op.drop_column('user', 'is_certified_master_engineer')
