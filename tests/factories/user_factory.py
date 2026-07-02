"""UserFactory — construit des objets User SQLAlchemy via factory-boy.

Colonnes importantes NON incluses dans la factory (rarement utiles en test) :
  bio, profile_image, instagram, twitter, youtube, soundcloud, signature,
  terms_accepted_at, deleted_at, oauth_provider, google_id, profile_picture_url,
  master_sample_raw/processed, mixmaster_sample_raw/processed,
  mixmaster_bio, premium_since, premium_price_paid.

Pour le statut premium, utiliser subscription_plan + premium_expires_at :
  - 'free'    → is_premium_active = False (quelle que soit premium_expires_at)
  - 'amateur' → is_premium_active = True si premium_expires_at is None ou futur
  - 'pro'     → idem amateur, mais quotas plus élevés

NE PAS passer is_premium=True : c'est un hybrid_property sans setter → AttributeError.
"""

import uuid
from datetime import datetime, timedelta
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

    # Abonnement — 'free' | 'amateur' | 'pro'
    # is_premium_active est dérivé de subscription_plan + premium_expires_at
    subscription_plan  = 'free'
    premium_expires_at = None   # None → premium valide indéfiniment (si plan != 'free')
    premium_source     = None   # 'stripe' | 'admin' | None

    # Tokens upload (colonne db, pas un hybrid_property — peut être surchargé directement)
    # Modèle default = 20 ; ici on le rend explicite pour la lisibilité des tests
    upload_track_tokens = 20
    topline_tokens      = 5

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
