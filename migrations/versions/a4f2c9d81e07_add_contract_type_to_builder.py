"""add contract_type to contract builder (groups + user contracts)

Revision ID: a4f2c9d81e07
Revises: d5e6f7a8b9c0
Create Date: 2026-07-08 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4f2c9d81e07'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None

contract_template_type = sa.Enum(
    'exploitation', 'performance', name='contracttemplatetypeenum'
)


def upgrade():
    bind = op.get_bind()
    contract_template_type.create(bind, checkfirst=True)

    with op.batch_alter_table('contract_clause_group', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'contract_type', contract_template_type,
            nullable=False, server_default='exploitation',
        ))

    with op.batch_alter_table('user_contract', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'contract_type', contract_template_type,
            nullable=False, server_default='exploitation',
        ))


def downgrade():
    with op.batch_alter_table('user_contract', schema=None) as batch_op:
        batch_op.drop_column('contract_type')

    with op.batch_alter_table('contract_clause_group', schema=None) as batch_op:
        batch_op.drop_column('contract_type')

    contract_template_type.drop(op.get_bind(), checkfirst=True)
