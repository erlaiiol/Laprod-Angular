"""new: track.file_hash and associated staticmethod

Revision ID: 89d52a587eeb
Revises: 5370513c7ac1
Create Date: 2026-02-22 17:10:43.801157

"""
from alembic import op
import sqlalchemy as sa
import hashlib
import os


# revision identifiers, used by Alembic.
revision = '89d52a587eeb'
down_revision = '5370513c7ac1'
branch_labels = None
depends_on = None

# Chemin vers les fichiers audio (static/audio/)
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'static', 'audio')


def upgrade():
    # 1. Ajouter file_hash en nullable=True pour permettre la migration des données existantes
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.add_column(sa.Column('file_hash', sa.String(length=64), nullable=True))

    # 2. Calculer le hash SHA-256 pour chaque track existante
    conn = op.get_bind()
    tracks = conn.execute(sa.text("SELECT id, file_mp3 FROM track")).fetchall()

    for track_id, file_mp3 in tracks:
        if file_mp3:
            filepath = os.path.join(AUDIO_DIR, file_mp3)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                conn.execute(
                    sa.text("UPDATE track SET file_hash = :hash WHERE id = :id"),
                    {"hash": file_hash, "id": track_id}
                )
            else:
                # Fichier introuvable : générer un hash unique de secours
                fallback = hashlib.sha256(f"missing-file-{track_id}-{file_mp3}".encode()).hexdigest()
                conn.execute(
                    sa.text("UPDATE track SET file_hash = :hash WHERE id = :id"),
                    {"hash": fallback, "id": track_id}
                )
        else:
            # Pas de fichier MP3 : hash basé sur l'id
            fallback = hashlib.sha256(f"no-mp3-{track_id}".encode()).hexdigest()
            conn.execute(
                sa.text("UPDATE track SET file_hash = :hash WHERE id = :id"),
                {"hash": fallback, "id": track_id}
            )

    # 3. Passer en nullable=False + index unique maintenant que toutes les lignes ont un hash
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.alter_column('file_hash', nullable=False)
        batch_op.create_index(batch_op.f('ix_track_file_hash'), ['file_hash'], unique=True)


def downgrade():
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_track_file_hash'))
        batch_op.drop_column('file_hash')
