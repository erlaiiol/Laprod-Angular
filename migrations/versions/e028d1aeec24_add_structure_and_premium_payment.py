"""add_structure_and_premium_payment

Revision ID: e028d1aeec24
Revises: 9456de60d644
Create Date: 2026-07-22 00:57:37.122417

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e028d1aeec24'
down_revision = '9456de60d644'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('premium_payment',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('plan', sa.String(length=20), nullable=False),
    sa.Column('amount_paid', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=False),
    sa.Column('is_renewal', sa.Boolean(), nullable=False),
    sa.Column('stripe_payment_intent_id', sa.String(length=120), nullable=True),
    sa.Column('stripe_checkout_session_id', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('premium_payment', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_premium_payment_user_id'), ['user_id'], unique=False)

    op.create_table('structure',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('legal_form', sa.String(length=100), nullable=True),
    sa.Column('capital', sa.String(length=80), nullable=True),
    sa.Column('siren', sa.String(length=20), nullable=True),
    sa.Column('siret', sa.String(length=25), nullable=True),
    sa.Column('rcs', sa.String(length=100), nullable=True),
    sa.Column('legal_rep', sa.String(length=200), nullable=True),
    sa.Column('signatory_title', sa.String(length=150), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('email', sa.String(length=120), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id')
    )
    with op.batch_alter_table('user_contract_party', schema=None) as batch_op:
        batch_op.add_column(sa.Column('linked_structure_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_user_contract_party_linked_structure_id', 'structure',
            ['linked_structure_id'], ['id'],
        )


def downgrade():
    with op.batch_alter_table('user_contract_party', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_contract_party_linked_structure_id', type_='foreignkey')
        batch_op.drop_column('linked_structure_id')

    op.drop_table('structure')

    with op.batch_alter_table('premium_payment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_premium_payment_user_id'))

    op.drop_table('premium_payment')
