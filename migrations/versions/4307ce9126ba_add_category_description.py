"""add description to category

Revision ID: 4307ce9126ba
Revises: e5f6a7b8c9d0
Create Date: 2026-05-24 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '4307ce9126ba'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('category', schema=None) as batch_op:
        batch_op.drop_column('description')
