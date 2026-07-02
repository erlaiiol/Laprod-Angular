"""ToplineFactory — construit des objets Topline SQLAlchemy via factory-boy.

Une topline est un enregistrement vocal d'un artiste déposé sur un beat.

Champs obligatoires que le test DOIT fournir :
  - track_id  : ID du Track sur lequel la topline est déposée
  - artist_id : ID du User artiste (rôle is_artist=True recommandé)

Variations courantes :
  is_published=True   → topline visible publiquement
  description=None    → topline sans description
"""

import uuid
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models import Topline


class ToplineFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Topline
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    # Obligatoires — le test doit les fournir
    track_id  = None
    artist_id = None

    audio_file  = factory.LazyFunction(lambda: f'audio/toplines/topline_{uuid.uuid4().hex[:8]}.wav')
    description = 'Topline test — vocal hook'
    is_published = False
