"""campagnes: segment affinity

Ajoute 'affinity' aux valeurs autorisées de marketing_campaign.segment.
Ciblage des auditeurs dont les goûts (déduits par l'algo de reco) collent au style
du vendeur, sans qu'ils le connaissent déjà.

Migration de contrainte uniquement (pas de nouvelle colonne). SQLite ne sait pas
faire ALTER d'un CHECK : batch_alter_table recrée la table proprement.

Revision ID: f11efd5923a5
Revises: 7798c721c20e
Create Date: 2026-07-15 04:00:19.683268

"""
from alembic import op


revision = 'f11efd5923a5'
down_revision = '7798c721c20e'
branch_labels = None
depends_on = None

_OLD = "segment IN ('buyers','favorites','listeners','all')"
_NEW = "segment IN ('buyers','favorites','listeners','affinity','all')"


def upgrade():
    with op.batch_alter_table('marketing_campaign', schema=None) as batch_op:
        batch_op.drop_constraint('ck_campaign_segment', type_='check')
        batch_op.create_check_constraint('ck_campaign_segment', _NEW)


def downgrade():
    # Repli : les campagnes 'affinity' existantes redeviennent 'listeners' (le
    # segment le plus proche) pour ne pas violer l'ancienne contrainte au retour.
    op.execute(
        "UPDATE marketing_campaign SET segment = 'listeners' WHERE segment = 'affinity'"
    )
    with op.batch_alter_table('marketing_campaign', schema=None) as batch_op:
        batch_op.drop_constraint('ck_campaign_segment', type_='check')
        batch_op.create_check_constraint('ck_campaign_segment', _OLD)
