"""add_apple_signin_columns

Revision ID: a1c9f2e7d4b3
Revises: b9e37d82b0aa
Create Date: 2026-09-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c9f2e7d4b3'
down_revision = 'b9e37d82b0aa'
branch_labels = None
depends_on = None


def upgrade():
    # Toutes nullable : aucune donnée existante à backfiller (R15 ne s'applique
    # pas ici, pas de NOT NULL ajouté à une table peuplée).
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('apple_sub', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('apple_refresh_token', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('apple_refresh_token_client_id', sa.String(length=255), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_apple_sub'), ['apple_sub'], unique=True)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_apple_sub'))
        batch_op.drop_column('apple_refresh_token_client_id')
        batch_op.drop_column('apple_refresh_token')
        batch_op.drop_column('apple_sub')
