"""add mobile_studio_session table

Revision ID: ec043e6f6d5e
Revises: bd3c3e3d2f23
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ec043e6f6d5e'
down_revision = 'bd3c3e3d2f23'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'mobile_studio_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('topline_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['track_id'], ['track.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['topline_id'], ['topline.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('mobile_studio_session')
