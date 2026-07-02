"""Add playlist and playlist_track tables

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5c6'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'playlist',
        sa.Column('id',           sa.Integer(),     primary_key=True),
        sa.Column('beatmaker_id', sa.Integer(),     sa.ForeignKey('user.id'), nullable=False),
        sa.Column('title',        sa.String(200),   nullable=False),
        sa.Column('image_file',   sa.String(200),   nullable=True),
        sa.Column('created_at',   sa.DateTime(),    nullable=True),
    )
    op.create_table(
        'playlist_track',
        sa.Column('playlist_id', sa.Integer(), sa.ForeignKey('playlist.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('track_id',    sa.Integer(), sa.ForeignKey('track.id',    ondelete='CASCADE'), primary_key=True),
        sa.Column('position',    sa.Integer(), nullable=True),
        sa.Column('added_at',    sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('playlist_track')
    op.drop_table('playlist')
