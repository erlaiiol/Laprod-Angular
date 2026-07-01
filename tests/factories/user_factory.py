"""UserFactory — construit des objets User SQLAlchemy via factory-boy."""

import uuid
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models import User


class UserFactory(SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    # Champs uniques — toujours générés aléatoirement pour éviter les conflits
    email    = factory.LazyFunction(lambda: f'user_{uuid.uuid4().hex[:8]}@test.laprod.fr')
    username = factory.LazyFunction(lambda: f'user_{uuid.uuid4().hex[:8]}')

    # Valeurs par défaut : utilisateur actif générique sans rôle spécifique
    email_verified     = True
    account_status     = 'active'
    user_type_selected = True
    is_beatmaker       = False
    is_artist          = False
    is_mix_engineer    = False
    is_admin           = False
    subscription_plan  = 'free'

    # Certifications mix/master — désactivées par défaut
    is_mixmaster_engineer          = False
    is_certified_master_engineer   = False
    is_certified_producer_arranger = False
    mixmaster_reference_price      = None
    mixmaster_price_min            = None
    mixmaster_bio                  = None
    mixmaster_sample_submitted     = False

    # Stripe Connect — non configuré par défaut
    stripe_account_id          = None
    stripe_account_status      = None
    stripe_onboarding_complete = False

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override nécessaire : set_password() doit être appelé explicitement."""
        obj = User(**kwargs)
        obj.set_password('TestPass123!')
        session = cls._meta.sqlalchemy_session
        session.add(obj)
        session.commit()
        return obj
