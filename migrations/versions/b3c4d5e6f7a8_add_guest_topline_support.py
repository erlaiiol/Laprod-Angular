"""add guest topline support

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-04 00:00:00.000000

- topline.artist_id : NOT NULL → nullable (support guest)
- topline.guest_session_id : VARCHAR(36) nullable, index
- topline.guest_expires_at : DATETIME nullable
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('topline', schema=None) as batch_op:
        batch_op.alter_column(
            'artist_id',
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(sa.Column('guest_session_id', sa.String(36), nullable=True))
        batch_op.add_column(sa.Column('guest_expires_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_topline_guest_session_id', ['guest_session_id'])


def downgrade():
    with op.batch_alter_table('topline', schema=None) as batch_op:
        batch_op.drop_index('ix_topline_guest_session_id')
        batch_op.drop_column('guest_expires_at')
        batch_op.drop_column('guest_session_id')
        batch_op.alter_column(
            'artist_id',
            existing_type=sa.Integer(),
            nullable=False,
        )
