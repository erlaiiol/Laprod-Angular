"""add track split

Revision ID: 988595a1e39c
Revises: 385b799f5d35
Create Date: 2026-07-21 01:55:03.925030

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '988595a1e39c'
down_revision = '385b799f5d35'
branch_labels = None
depends_on = None


track_split_role = sa.Enum(
    'topliner', 'beatmaker', 'mix_engineer', 'label', 'producer', 'other',
    name='tracksplitrole',
)
track_split_status = sa.Enum('declared', 'confirmed', name='tracksplitstatus')


def upgrade():
    # Pas de création explicite des types Enum : op.create_table() la déclenche
    # déjà automatiquement pour les colonnes ci-dessous (cf. migration
    # 6f827cf108ee_add_roster_link.py — créer le type à la main en amont
    # provoque un DuplicateObject sur PostgreSQL).
    op.create_table(
        'track_split',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('external_name', sa.String(length=200), nullable=False),
        sa.Column('role', track_split_role, nullable=False),
        sa.Column('percentage', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('status', track_split_status, nullable=False, server_default='declared'),
        sa.Column('added_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['track_id'], ['track.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['added_by_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('percentage > 0 AND percentage <= 100', name='ck_track_split_percentage_range'),
    )
    op.create_index('idx_track_split_track', 'track_split', ['track_id'])


def downgrade():
    op.drop_index('idx_track_split_track', table_name='track_split')
    op.drop_table('track_split')

    track_split_status.drop(op.get_bind(), checkfirst=True)
    track_split_role.drop(op.get_bind(), checkfirst=True)
