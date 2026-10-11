"""add apple_iap_transaction table

Revision ID: c4e8a1f07b52
Revises: ec043e6f6d5e
Create Date: 2026-09-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e8a1f07b52'
down_revision = 'ec043e6f6d5e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'apple_iap_transaction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('product_id', sa.String(length=120), nullable=False),
        sa.Column('plan', sa.String(length=20), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=False),
        sa.Column('environment', sa.String(length=20), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=8), nullable=True),
        sa.Column('purchased_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_apple_iap_transaction_transaction_id', 'apple_iap_transaction',
                    ['transaction_id'], unique=True)
    op.create_index('ix_apple_iap_transaction_user_id', 'apple_iap_transaction',
                    ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_apple_iap_transaction_user_id', table_name='apple_iap_transaction')
    op.drop_index('ix_apple_iap_transaction_transaction_id', table_name='apple_iap_transaction')
    op.drop_table('apple_iap_transaction')
