"""add topline.is_mobile_processed

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'topline',
        sa.Column('is_mobile_processed', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade():
    op.drop_column('topline', 'is_mobile_processed')
