"""add planning event and ical feed token

Revision ID: ab3b0f56bb44
Revises: 6f827cf108ee
Create Date: 2026-07-20 19:56:19.537898

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ab3b0f56bb44'
down_revision = '6f827cf108ee'
branch_labels = None
depends_on = None

planning_event_type = sa.Enum(
    'recording_session', 'writing_session', 'rehearsal', 'concert', 'showcase',
    'residency', 'video_shoot', 'media_interview', 'meeting', 'appointment',
    'sacem_deposit', 'contractual_deadline', 'release', 'other',
    name='planningeventtypeenum',
)
planning_event_status = sa.Enum(
    'proposed', 'confirmed', 'cancelled', name='planningeventstatus'
)


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ical_feed_token', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_user_ical_feed_token', ['ical_feed_token'])
        batch_op.create_index('ix_user_ical_feed_token', ['ical_feed_token'])

    # Pas de création explicite des types Enum : op.create_table() la déclenche
    # déjà automatiquement pour les colonnes ci-dessous (cf. migration
    # 6f827cf108ee_add_roster_link.py — créer le type à la main en amont
    # provoque un DuplicateObject sur PostgreSQL).
    op.create_table(
        'planning_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('roster_link_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('event_type', planning_event_type, nullable=False, server_default='other'),
        sa.Column('status', planning_event_status, nullable=False, server_default='proposed'),
        sa.Column('start_at', sa.DateTime(), nullable=False),
        sa.Column('end_at', sa.DateTime(), nullable=True),
        sa.Column('timezone', sa.String(length=50), nullable=False, server_default='Europe/Paris'),
        sa.Column('all_day', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('location', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['roster_link_id'], ['roster_link.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('end_at IS NULL OR end_at >= start_at', name='ck_planning_event_end_after_start'),
    )
    op.create_index('idx_planning_roster_start', 'planning_event', ['roster_link_id', 'start_at'])


def downgrade():
    op.drop_index('idx_planning_roster_start', table_name='planning_event')
    op.drop_table('planning_event')

    planning_event_status.drop(op.get_bind(), checkfirst=True)
    planning_event_type.drop(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_ical_feed_token')
        batch_op.drop_constraint('uq_user_ical_feed_token', type_='unique')
        batch_op.drop_column('ical_feed_token')
