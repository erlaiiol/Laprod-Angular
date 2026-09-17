"""add track reference_audio_file

Revision ID: bd3c3e3d2f23
Revises: a1c9f2e7d4b3
Create Date: 2026-09-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd3c3e3d2f23'
down_revision = 'a1c9f2e7d4b3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reference_audio_file', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.drop_column('reference_audio_file')
