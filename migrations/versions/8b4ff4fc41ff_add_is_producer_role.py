"""Add is_producer role (self-declared, no certification)

Revision ID: 8b4ff4fc41ff
Revises: cd41585e0e53
Create Date: 2026-07-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8b4ff4fc41ff'
down_revision = 'cd41585e0e53'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_producer', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('is_producer')
