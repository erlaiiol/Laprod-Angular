"""add wallet tables

Ajoute les tables wallet et wallet_transaction (système de gains interne).
Supprime les colonnes de révisions mixmaster et les colonnes de prix max
qui ne sont plus utilisées dans le nouveau modèle.

Revision ID: 88a618a2bac7
Revises: c50728c867e4
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = '88a618a2bac7'
down_revision = 'c50728c867e4'
branch_labels = None
depends_on = None


def _get_columns(table_name):
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return {col['name'] for col in inspector.get_columns(table_name)}


def _table_exists(table_name):
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return table_name in inspector.get_table_names()


def _index_exists(index_name, table_name):
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    return any(idx['name'] == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    # --- Wallet ---
    if not _table_exists('wallet'):
        op.create_table(
            'wallet',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('balance_available', sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column('balance_pending', sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id'),
            sa.CheckConstraint('balance_available >= 0', name='check_balance_available_positive'),
            sa.CheckConstraint('balance_pending >= 0', name='check_balance_pending_positive'),
        )

    # --- WalletTransaction ---
    if not _table_exists('wallet_transaction'):
        op.create_table(
            'wallet_transaction',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('wallet_id', sa.Integer(), nullable=False),
            sa.Column('type', sa.String(length=50), nullable=False),
            sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('available_at', sa.DateTime(), nullable=True),
            sa.Column('purchase_id', sa.Integer(), nullable=True),
            sa.Column('mixmaster_request_id', sa.Integer(), nullable=True),
            sa.Column('stripe_transfer_id', sa.String(length=200), nullable=True),
            sa.Column('description', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['mixmaster_request_id'], ['mixmaster_request.id'], ),
            sa.ForeignKeyConstraint(['purchase_id'], ['purchase.id'], ),
            sa.ForeignKeyConstraint(['wallet_id'], ['wallet.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )
        if not _index_exists('idx_wallet_txn_wallet_id', 'wallet_transaction'):
            op.create_index('idx_wallet_txn_wallet_id', 'wallet_transaction', ['wallet_id'])
        if not _index_exists('idx_wallet_txn_status_available_at', 'wallet_transaction'):
            op.create_index('idx_wallet_txn_status_available_at', 'wallet_transaction', ['status', 'available_at'])
        if not _index_exists('idx_wallet_txn_created_at', 'wallet_transaction'):
            op.create_index('idx_wallet_txn_created_at', 'wallet_transaction', ['created_at'])

    # --- Colonnes supprimées de mixmaster_request ---
    mm_cols = _get_columns('mixmaster_request')
    with op.batch_alter_table('mixmaster_request') as batch_op:
        if 'stripe_revision1_transfer_id' in mm_cols:
            batch_op.drop_column('stripe_revision1_transfer_id')
        if 'stripe_revision2_transfer_id' in mm_cols:
            batch_op.drop_column('stripe_revision2_transfer_id')
        if 'revision_count' in mm_cols:
            batch_op.drop_column('revision_count')

    # --- Colonnes modifiées dans price_change_request ---
    pcr_cols = _get_columns('price_change_request')
    with op.batch_alter_table('price_change_request') as batch_op:
        if 'old_reference_price' not in pcr_cols:
            batch_op.add_column(sa.Column('old_reference_price', sa.Numeric(precision=10, scale=2), nullable=True))
        if 'new_reference_price' not in pcr_cols:
            batch_op.add_column(sa.Column('new_reference_price', sa.Numeric(precision=10, scale=2), nullable=True))
        if 'new_price_max' in pcr_cols:
            batch_op.drop_column('new_price_max')
        if 'old_price_max' in pcr_cols:
            batch_op.drop_column('old_price_max')

    # --- Colonne supprimée de user ---
    user_cols = _get_columns('user')
    with op.batch_alter_table('user') as batch_op:
        if 'mixmaster_price_max' in user_cols:
            batch_op.drop_column('mixmaster_price_max')


def downgrade():
    # --- Restaurer user.mixmaster_price_max ---
    user_cols = _get_columns('user')
    with op.batch_alter_table('user') as batch_op:
        if 'mixmaster_price_max' not in user_cols:
            batch_op.add_column(sa.Column('mixmaster_price_max', sa.Numeric(precision=10, scale=2), nullable=True))

    # --- Restaurer price_change_request ---
    pcr_cols = _get_columns('price_change_request')
    with op.batch_alter_table('price_change_request') as batch_op:
        if 'old_price_max' not in pcr_cols:
            batch_op.add_column(sa.Column('old_price_max', sa.Numeric(precision=10, scale=2), nullable=True))
        if 'new_price_max' not in pcr_cols:
            batch_op.add_column(sa.Column('new_price_max', sa.Numeric(precision=10, scale=2), nullable=True))
        if 'new_reference_price' in pcr_cols:
            batch_op.drop_column('new_reference_price')
        if 'old_reference_price' in pcr_cols:
            batch_op.drop_column('old_reference_price')

    # --- Restaurer colonnes mixmaster_request ---
    mm_cols = _get_columns('mixmaster_request')
    with op.batch_alter_table('mixmaster_request') as batch_op:
        if 'revision_count' not in mm_cols:
            batch_op.add_column(sa.Column('revision_count', sa.Integer(), nullable=True))
        if 'stripe_revision2_transfer_id' not in mm_cols:
            batch_op.add_column(sa.Column('stripe_revision2_transfer_id', sa.String(length=200), nullable=True))
        if 'stripe_revision1_transfer_id' not in mm_cols:
            batch_op.add_column(sa.Column('stripe_revision1_transfer_id', sa.String(length=200), nullable=True))

    # --- Supprimer les index et tables wallet ---
    if _table_exists('wallet_transaction'):
        if _index_exists('idx_wallet_txn_created_at', 'wallet_transaction'):
            op.drop_index('idx_wallet_txn_created_at', table_name='wallet_transaction')
        if _index_exists('idx_wallet_txn_status_available_at', 'wallet_transaction'):
            op.drop_index('idx_wallet_txn_status_available_at', table_name='wallet_transaction')
        if _index_exists('idx_wallet_txn_wallet_id', 'wallet_transaction'):
            op.drop_index('idx_wallet_txn_wallet_id', table_name='wallet_transaction')
        op.drop_table('wallet_transaction')
    if _table_exists('wallet'):
        op.drop_table('wallet')
