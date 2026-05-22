"""add premium_source and premium_price_paid to user

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('premium_source', sa.String(20), nullable=True))
    op.add_column('user', sa.Column('premium_price_paid', sa.Numeric(10, 2), nullable=True))


def downgrade():
    op.drop_column('user', 'premium_price_paid')
    op.drop_column('user', 'premium_source')
