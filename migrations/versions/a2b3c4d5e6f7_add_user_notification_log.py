"""add user_notification_log

Revision ID: a2b3c4d5e6f7
Revises: c7425c996797
Create Date: 2026-07-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a2b3c4d5e6f7'
down_revision = 'c7425c996797'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_notification_log',
        sa.Column('id',                sa.Integer(),     nullable=False),
        sa.Column('user_id',           sa.Integer(),     nullable=False),
        sa.Column('notification_type', sa.String(80),    nullable=False),
        sa.Column('period_key',        sa.String(30),    nullable=False),
        sa.Column('sent_at',           sa.DateTime(),    nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'notification_type', 'period_key',
                            name='uq_user_notif_dedup'),
    )
    with op.batch_alter_table('user_notification_log', schema=None) as batch_op:
        batch_op.create_index('idx_user_notif_log', ['user_id', 'notification_type'], unique=False)


def downgrade():
    with op.batch_alter_table('user_notification_log', schema=None) as batch_op:
        batch_op.drop_index('idx_user_notif_log')
    op.drop_table('user_notification_log')
