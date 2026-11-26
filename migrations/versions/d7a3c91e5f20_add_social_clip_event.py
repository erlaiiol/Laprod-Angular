"""add social_clip_event table (Mode Clip)

Revision ID: d7a3c91e5f20
Revises: c4e8a1f07b52
Create Date: 2026-11-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd7a3c91e5f20'
down_revision = 'c4e8a1f07b52'
branch_labels = None
depends_on = None


def upgrade():
    # Nouvelle table, aucune colonne ajoutée à une table peuplée ; mode/action en
    # String + CheckConstraint (pas d'enum PostgreSQL à créer, cf. R15).
    op.create_table(
        'social_clip_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('clip_uid', sa.String(length=36), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('target', sa.String(length=16), nullable=True),
        sa.Column('duration_s', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('playback', 'rec')", name='ck_social_clip_mode'),
        sa.CheckConstraint("action IN ('saved', 'shared')", name='ck_social_clip_action'),
        sa.CheckConstraint('duration_s >= 0 AND duration_s <= 45', name='ck_social_clip_duration'),
        sa.ForeignKeyConstraint(['track_id'], ['track.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_social_clip_event_track', 'social_clip_event', ['track_id'], unique=False)
    op.create_index('ix_social_clip_event_user', 'social_clip_event', ['user_id'], unique=False)


def downgrade():
    op.drop_index('ix_social_clip_event_user', table_name='social_clip_event')
    op.drop_index('ix_social_clip_event_track', table_name='social_clip_event')
    op.drop_table('social_clip_event')
