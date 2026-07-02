"""merge tooltip_plain and other head

Revision ID: 3ba30de38760
Revises: 454727327355, 68eca9dcb5ec
Create Date: 2026-05-17 13:45:51.090488

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3ba30de38760'
down_revision = ('454727327355', '68eca9dcb5ec')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
