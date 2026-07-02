"""TrackFactory — construit des objets Track SQLAlchemy via factory-boy.

Champs obligatoires que le test DOIT fournir :
  - composer_id : ID du User beatmaker

Variations courantes par surcharge :
  - is_approved=False         → track en attente d'approbation admin
  - file_mp3='audio/x.mp3'   → track avec fichier complet disponible à l'achat
  - is_exclusive_sold=True    → exclusivité vendue (409 au checkout)
  - price_mp3=Decimal('50')  → prix élevé pour tester seuils
  - sacem_percentage_composer=0 ou 85  → valeurs limites SACEM
  - contract_price_exclusive=500       → prix custom override plateforme
"""

import uuid
from decimal import Decimal
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models import Track


class TrackFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Track
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    # composer_id est obligatoire — le test doit le fournir
    composer_id = None

    title      = factory.Sequence(lambda n: f'Test Beat {n}')
    file_hash  = factory.LazyFunction(lambda: uuid.uuid4().hex)
    audio_file = factory.LazyFunction(lambda: f'audio/preview_{uuid.uuid4().hex[:8]}.mp3')

    # Fichiers complets — None par défaut (non disponibles à la vente directe)
    # Surcharger avec un chemin fictif pour tester les downloads et le checkout
    file_mp3   = None
    file_wav   = None
    file_stems = None
    image_file = None

    bpm   = 120
    key   = 'C major'
    style = 'Trap'

    is_approved       = True
    approved_at       = None
    is_ai_suggested   = False
    is_exclusive_sold = False
    exclusive_buyer_id = None
    exclusive_sold_at  = None

    # Prix standard plateforme
    price_mp3   = Decimal('9.99')
    price_wav   = Decimal('19.99')
    price_stems = Decimal('49.99')

    # Tous les prix de contrat à None → la plateforme utilise ses valeurs par défaut
    # (CONTRACT_EXCLUSIVE_PRICE, CONTRACT_DURATIONS, etc. dans config.py)
    contract_price_exclusive      = None
    contract_price_duration_3y    = None
    contract_price_duration_5y    = None
    contract_price_duration_10y   = None
    contract_price_lifetime       = None
    contract_price_mechanical     = None
    contract_price_public_show    = None
    contract_price_arrangement    = None
    contract_price_territory_eu   = None
    contract_price_territory_world = None

    # SACEM : 50% composer / 50% buyer par défaut (bornes valides : 0–85)
    sacem_percentage_composer = 50
