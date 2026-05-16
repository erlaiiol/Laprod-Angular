"""
utils/crud_helpers.py — LaProd
===============================
Helpers CRUD génériques pour les routes Flask.

Fournit :
  get_or_404(model, entity_id, message)  → entité ou lève EntityNotFound
  require_ownership(entity, field, user) → lève EntityForbidden si non-propriétaire
  @handle_route_exceptions               → catch EntityNotFound/EntityForbidden → HTTP response
  @commit_or_rollback                    → catch Exception → rollback + log + 500

Architecture :
  Les deux exceptions (EntityNotFound, EntityForbidden) permettent de découpler la logique
  métier de la gestion HTTP. La route lance des exceptions typées ; @handle_route_exceptions
  les convertit en réponses HTTP.

  @commit_or_rollback re-lève EntityNotFound/EntityForbidden pour que @handle_route_exceptions
  les attrape (il doit être placé avant dans la pile de décorateurs).

Ordre de décoration recommandé :
    @bp.route(...)
    @jwt_required()
    @csrf.exempt
    @handle_route_exceptions     ← attrape EntityNotFound / EntityForbidden
    @require_user                ← injecte current_user
    @commit_or_rollback          ← rollback sur Exception générique
    def ma_route(entity_id, current_user):
        entity = get_or_404(Model, entity_id)          # lève EntityNotFound si absent
        require_ownership(entity, 'user_id', current_user)  # lève EntityForbidden si non-proprio
        entity.field = value
        db.session.commit()
        return ok(...)

Note sur commit_or_rollback :
  Ce décorateur NE commit PAS automatiquement. La route doit appeler db.session.commit()
  explicitement. Le décorateur gère uniquement le rollback + log en cas d'exception non gérée.
  Cela préserve le contrôle de la transaction côté logique métier.
"""

from functools import wraps
from flask import current_app
from extensions import db
from serializers import err as _err


# =============================================================================
# Exceptions typées
# =============================================================================

class EntityNotFound(Exception):
    """Levée par get_or_404 quand une entité est absente de la base."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class EntityForbidden(Exception):
    """Levée par require_ownership quand l'utilisateur n'est pas propriétaire."""
    def __init__(self, message: str = 'Accès refusé.'):
        self.message = message
        super().__init__(message)


# =============================================================================
# Fonctions utilitaires
# =============================================================================

def get_or_404(model, entity_id, message: str | None = None):
    """
    Récupère une entité par ID ou lève EntityNotFound.

    Args:
        model      : Classe SQLAlchemy (ex: Track, Topline, User)
        entity_id  : Valeur de la clé primaire
        message    : Message d'erreur personnalisé (optionnel)

    Returns:
        L'instance SQLAlchemy si trouvée.

    Raises:
        EntityNotFound si l'entité n'existe pas en base.

    Différence avec db.get_or_404() :
        db.get_or_404() lève une HTTPException Flask (gérée globalement).
        get_or_404() lève EntityNotFound (gérée par @handle_route_exceptions),
        ce qui permet de personnaliser le message et le code de réponse JSON.
    """
    entity = db.session.get(model, entity_id)
    if not entity:
        raise EntityNotFound(message or f'{model.__name__} introuvable.')
    return entity


def require_ownership(entity, owner_field: str, current_user):
    """
    Vérifie que current_user est propriétaire de l'entité (ou admin).

    Args:
        entity       : Instance SQLAlchemy
        owner_field  : Nom du champ FK vers user (ex: 'artist_id', 'composer_id', 'user_id')
        current_user : Instance User issue du JWT

    Raises:
        EntityForbidden si current_user.id != entity.<owner_field> et non-admin.
    """
    owner_id = getattr(entity, owner_field, None)
    if owner_id != current_user.id and not current_user.is_admin:
        raise EntityForbidden('Accès refusé.')


# =============================================================================
# Décorateurs
# =============================================================================

def handle_route_exceptions(f):
    """
    Décorateur : intercepte EntityNotFound et EntityForbidden et retourne
    la réponse HTTP JSON correspondante.

    - EntityNotFound  → 404 avec le message de l'exception
    - EntityForbidden → 403 avec le message de l'exception

    Doit être placé AVANT @require_user et @commit_or_rollback dans la pile
    (= plus loin de la fonction dans le code source) pour pouvoir attraper
    les exceptions levées par ces décorateurs et par la fonction elle-même.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except EntityNotFound as e:
            return _err(e.message, status=404)
        except EntityForbidden as e:
            return _err(e.message, status=403)
    return decorated


def commit_or_rollback(f):
    """
    Décorateur : wraps la route dans un try/except générique.

    En cas d'exception non gérée (ni EntityNotFound ni EntityForbidden) :
      1. db.session.rollback()
      2. current_app.logger.error(...)
      3. Retourne une réponse 500

    EntityNotFound et EntityForbidden sont re-levées sans interception
    pour remonter jusqu'à @handle_route_exceptions.

    Note : la route doit appeler db.session.commit() elle-même.
    Ce décorateur gère uniquement le rollback en cas d'échec.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except (EntityNotFound, EntityForbidden):
            raise  # re-raise pour handle_route_exceptions
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f'[{f.__name__}] Erreur non gérée : {e}', exc_info=True
            )
            return _err('Erreur serveur.', status=500)
    return decorated
