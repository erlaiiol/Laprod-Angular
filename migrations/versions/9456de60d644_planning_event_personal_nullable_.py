"""planning_event: roster_link_id nullable (événements personnels)

Revision ID: 9456de60d644
Revises: 988595a1e39c
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9456de60d644'
down_revision = '988595a1e39c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('planning_event', schema=None) as batch_op:
        batch_op.alter_column('roster_link_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Un downgrade échouerait s'il existe déjà des événements personnels
    # (roster_link_id NULL) : c'est le comportement voulu, pas un bug — on ne
    # revient pas silencieusement à un état qui perdrait ces événements.
    with op.batch_alter_table('planning_event', schema=None) as batch_op:
        batch_op.alter_column('roster_link_id', existing_type=sa.Integer(), nullable=False)
