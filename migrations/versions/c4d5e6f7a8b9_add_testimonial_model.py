"""add testimonial model

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-07-04 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'testimonial_request',
        sa.Column('id',           sa.Integer(),     nullable=False),
        sa.Column('user_id',      sa.Integer(),     nullable=True),
        sa.Column('email',        sa.String(120),   nullable=False),
        sa.Column('role',         sa.String(30),    nullable=True),
        sa.Column('message',      sa.Text(),        nullable=False),
        sa.Column('rating',       sa.Integer(),     nullable=True),
        sa.Column('is_verified',  sa.Boolean(),     nullable=False, server_default='false'),
        sa.Column('is_published', sa.Boolean(),     nullable=False, server_default='false'),
        sa.Column('created_at',   sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_testimonial_published', 'testimonial_request', ['is_published', 'created_at'])


def downgrade():
    op.drop_index('idx_testimonial_published', table_name='testimonial_request')
    op.drop_table('testimonial_request')
