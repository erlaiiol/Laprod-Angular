"""add contract signature (invite/sign/decline workflow)

Revision ID: 1a7eb9d24827
Revises: e028d1aeec24
Create Date: 2026-07-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1a7eb9d24827'
down_revision = 'e028d1aeec24'
branch_labels = None
depends_on = None

party_invite_status = sa.Enum(
    'none', 'pending', 'signed', 'declined', name='partyinvitestatus'
)
contract_signature_status = sa.Enum(
    'not_sent', 'pending', 'declined', 'signed', name='contractsignaturestatus'
)


def upgrade():
    bind = op.get_bind()
    party_invite_status.create(bind, checkfirst=True)
    contract_signature_status.create(bind, checkfirst=True)

    with op.batch_alter_table('user_contract', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'signature_status', contract_signature_status,
            nullable=False, server_default='not_sent',
        ))

    with op.batch_alter_table('user_contract_party', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'invite_status', party_invite_status,
            nullable=False, server_default='none',
        ))
        batch_op.add_column(sa.Column('invited_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('invited_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('signed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('signature_name', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('signature_ip', sa.String(length=45), nullable=True))
        batch_op.add_column(sa.Column(
            'consent_confirmed', sa.Boolean(), nullable=False, server_default='false',
        ))
        batch_op.add_column(sa.Column('declined_at', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            'fk_user_contract_party_invited_by_id', 'user',
            ['invited_by_id'], ['id'],
        )


def downgrade():
    with op.batch_alter_table('user_contract_party', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_contract_party_invited_by_id', type_='foreignkey')
        batch_op.drop_column('declined_at')
        batch_op.drop_column('consent_confirmed')
        batch_op.drop_column('signature_ip')
        batch_op.drop_column('signature_name')
        batch_op.drop_column('signed_at')
        batch_op.drop_column('invited_by_id')
        batch_op.drop_column('invited_at')
        batch_op.drop_column('invite_status')

    with op.batch_alter_table('user_contract', schema=None) as batch_op:
        batch_op.drop_column('signature_status')

    bind = op.get_bind()
    contract_signature_status.drop(bind, checkfirst=True)
    party_invite_status.drop(bind, checkfirst=True)
