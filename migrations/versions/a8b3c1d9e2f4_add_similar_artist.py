"""Add similar_artist and track_similar_artist tables

Revision ID: a8b3c1d9e2f4
Revises: 4307ce9126ba
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'a8b3c1d9e2f4'
down_revision = '4307ce9126ba'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'similar_artist',
        sa.Column('id',         sa.Integer(),     nullable=False),
        sa.Column('name',       sa.String(64),    nullable=False),
        sa.Column('scene',      sa.String(32),    nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'track_similar_artist',
        sa.Column('track_id',  sa.Integer(), nullable=False),
        sa.Column('artist_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['track_id'],  ['track.id'],          ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['artist_id'], ['similar_artist.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('track_id', 'artist_id'),
    )


def downgrade():
    op.drop_table('track_similar_artist')
    op.drop_table('similar_artist')
