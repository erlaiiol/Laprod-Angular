"""add is_ai_suggested to track

Revision ID: a1b2c3d4e5f6
Revises: 68eca9dcb5ec, 4307ce9126ba, 454727327355
Create Date: 2026-06-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = ('68eca9dcb5ec', '4307ce9126ba', '454727327355')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('track', sa.Column(
        'is_ai_suggested', sa.Boolean(), nullable=False,
        server_default='false',
    ))


def downgrade():
    op.drop_column('track', 'is_ai_suggested')
