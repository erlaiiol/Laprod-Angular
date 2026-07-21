"""add management contract type and party linked user

Revision ID: 385b799f5d35
Revises: ab3b0f56bb44
Create Date: 2026-07-20 20:51:03.228431

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '385b799f5d35'
down_revision = 'ab3b0f56bb44'
branch_labels = None
depends_on = None


def upgrade():
    # ALTER TYPE ... ADD VALUE supporte IF NOT EXISTS depuis PostgreSQL 9.6, et
    # est exécutable dans une transaction depuis PostgreSQL 12 (la seule
    # restriction restante : ne pas UTILISER la nouvelle valeur dans la même
    # transaction que celle qui l'ajoute — ce que cette migration ne fait pas).
    op.execute("ALTER TYPE contracttemplatetypeenum ADD VALUE IF NOT EXISTS 'management'")

    with op.batch_alter_table('user_contract_party', schema=None) as batch_op:
        batch_op.add_column(sa.Column('linked_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_user_contract_party_linked_user', 'user', ['linked_user_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('user_contract_party', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_contract_party_linked_user', type_='foreignkey')
        batch_op.drop_column('linked_user_id')

    # PostgreSQL ne propose pas d'ALTER TYPE ... DROP VALUE : retirer une
    # valeur d'un type ENUM existant nécessiterait de recréer le type entier
    # (et de migrer toutes les colonnes qui l'utilisent). On assume cette
    # limitation ici — une valeur d'enum inutilisée après un downgrade n'est
    # pas dangereuse tant qu'aucune ligne ne la référence, contrairement à une
    # colonne orpheline.
