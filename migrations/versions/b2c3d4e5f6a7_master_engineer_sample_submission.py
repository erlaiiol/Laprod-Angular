"""Master engineer sample submission fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-21 11:00:00.000000

Ajoute les colonnes de soumission d'échantillon mastering pour la certification
is_certified_master_engineer par l'admin (workflow identique aux samples mixage).
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('master_sample_raw', sa.String(200), nullable=True))
    op.add_column('user', sa.Column('master_sample_processed', sa.String(200), nullable=True))
    op.add_column('user', sa.Column(
        'master_sample_submitted', sa.Boolean(), nullable=False, server_default='false'
    ))


def downgrade():
    op.drop_column('user', 'master_sample_submitted')
    op.drop_column('user', 'master_sample_processed')
    op.drop_column('user', 'master_sample_raw')
