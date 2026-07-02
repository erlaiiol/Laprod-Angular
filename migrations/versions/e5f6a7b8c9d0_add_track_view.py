"""Add track_view table for view analytics

Revision ID: e5f6a7b8c9d0
Revises: d1e2f3a4b5c6
Create Date: 2026-05-23

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'track_view',
        sa.Column('id',         sa.Integer(),     primary_key=True),
        sa.Column('track_id',   sa.Integer(),     sa.ForeignKey('track.id',  ondelete='CASCADE'),    nullable=False),
        sa.Column('user_id',    sa.Integer(),     sa.ForeignKey('user.id',   ondelete='SET NULL'),   nullable=True),
        sa.Column('ip_hash',    sa.String(64),    nullable=False),
        sa.Column('source',     sa.String(32),    nullable=False, server_default='player'),
        sa.Column('created_at', sa.DateTime(),    nullable=False),
    )
    op.create_index('ix_track_view_track',   'track_view', ['track_id'])
    op.create_index('ix_track_view_user',    'track_view', ['user_id'])
    op.create_index('ix_track_view_ip_date', 'track_view', ['track_id', 'ip_hash', 'created_at'])


def downgrade():
    op.drop_index('ix_track_view_ip_date', 'track_view')
    op.drop_index('ix_track_view_user',    'track_view')
    op.drop_index('ix_track_view_track',   'track_view')
    op.drop_table('track_view')
