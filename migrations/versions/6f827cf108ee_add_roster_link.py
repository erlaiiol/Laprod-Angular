"""add roster link

Revision ID: 6f827cf108ee
Revises: 8b4ff4fc41ff
Create Date: 2026-07-20 18:11:42.165978

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f827cf108ee'
down_revision = '8b4ff4fc41ff'
branch_labels = None
depends_on = None

roster_link_status = sa.Enum(
    'invited', 'active', 'declined', 'revoked', 'ended', name='rosterlinkstatus'
)


def upgrade():
    # Pas de création explicite du type : op.create_table() la déclenche déjà
    # automatiquement pour la colonne Enum ci-dessous (Alembic ignore le flag
    # create_type=False sur create_table, contrairement à batch add_column —
    # tenter de créer le type à la main en amont provoque un DuplicateObject).
    op.create_table(
        'roster_link',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('producer_id', sa.Integer(), nullable=False),
        sa.Column('artist_id', sa.Integer(), nullable=False),
        sa.Column('status', roster_link_status, nullable=False, server_default='invited'),
        sa.Column('invited_by_id', sa.Integer(), nullable=False),
        sa.Column('management_contract_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['producer_id'], ['user.id']),
        sa.ForeignKeyConstraint(['artist_id'], ['user.id']),
        sa.ForeignKeyConstraint(['invited_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['management_contract_id'], ['user_contract.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('producer_id', 'artist_id', name='uq_roster_link_pair'),
    )
    op.create_index('idx_roster_producer_status', 'roster_link', ['producer_id', 'status'])
    op.create_index('idx_roster_artist_status', 'roster_link', ['artist_id', 'status'])


def downgrade():
    op.drop_index('idx_roster_artist_status', table_name='roster_link')
    op.drop_index('idx_roster_producer_status', table_name='roster_link')
    op.drop_table('roster_link')

    roster_link_status.drop(op.get_bind(), checkfirst=True)
