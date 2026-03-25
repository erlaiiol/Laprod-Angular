"""fix missing user columns

Ajoute les colonnes absentes des migrations précédentes (autogenerate
n'avait pas détecté de diff car la DB locale les avait déjà).
Utilise IF NOT EXISTS → idempotent sur les serveurs où elles ont été
ajoutées manuellement.

Revision ID: c50728c867e4
Revises: 306436f07678
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'c50728c867e4'
down_revision = '306436f07678'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE "user"
          ADD COLUMN IF NOT EXISTS is_certified_producer_arranger
              BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS mixmaster_reference_price FLOAT,
          ADD COLUMN IF NOT EXISTS mixmaster_price_min FLOAT,
          ADD COLUMN IF NOT EXISTS mixmaster_sample_submitted
              BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS producer_arranger_request_submitted
              BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS is_premium
              BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS premium_since TIMESTAMP,
          ADD COLUMN IF NOT EXISTS premium_expires_at TIMESTAMP,
          ADD COLUMN IF NOT EXISTS upload_track_tokens INTEGER DEFAULT 20,
          ADD COLUMN IF NOT EXISTS last_upload_reset DATE DEFAULT CURRENT_DATE,
          ADD COLUMN IF NOT EXISTS topline_tokens INTEGER DEFAULT 5,
          ADD COLUMN IF NOT EXISTS last_topline_reset DATE DEFAULT CURRENT_DATE
    """)


def downgrade():
    op.execute("""
        ALTER TABLE "user"
          DROP COLUMN IF EXISTS last_topline_reset,
          DROP COLUMN IF EXISTS topline_tokens,
          DROP COLUMN IF EXISTS last_upload_reset,
          DROP COLUMN IF EXISTS upload_track_tokens,
          DROP COLUMN IF EXISTS premium_expires_at,
          DROP COLUMN IF EXISTS premium_since,
          DROP COLUMN IF EXISTS is_premium,
          DROP COLUMN IF EXISTS producer_arranger_request_submitted,
          DROP COLUMN IF EXISTS mixmaster_sample_submitted,
          DROP COLUMN IF EXISTS mixmaster_price_min,
          DROP COLUMN IF EXISTS mixmaster_reference_price,
          DROP COLUMN IF EXISTS is_certified_producer_arranger
    """)
