"""
utils/auth_helpers.py — LaProd
==============================
Helpers d'authentification JWT pour les routes Flask.

Fournit :
  get_current_user()   → (User, None) ou (None, error_response)
  @require_user        → décorateur : injecte `current_user` dans les kwargs de la route
  @require_admin       → décorateur : idem + vérifie is_admin

Usage dans un blueprint :
    from flask_jwt_extended import jwt_required
    from utils.auth_helpers import require_user, require_admin

    @bp.route('/endpoint', methods=['POST'])
    @jwt_required()
    @require_user
    def endpoint(current_user):
        ...

    @bp.route('/admin-only', methods=['POST'])
    @jwt_required()
    @require_admin
    def admin_only(current_user):
        ...

Note : @require_user / @require_admin doivent toujours être placés APRÈS @jwt_required()
dans la pile de décorateurs, car get_jwt_identity() nécessite le contexte JWT initialisé
par Flask-JWT-Extended.
"""

from functools import wraps
from flask_jwt_extended import get_jwt_identity
from extensions import db
from models import User
from serializers import err as _err


def get_current_user():
    """
    Récupère l'utilisateur courant depuis le JWT.

    Returns:
        (User, None)            si trouvé
        (None, error_response)  si introuvable (404)
    """
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return None, _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)
    return user, None


def require_user(f):
    """
    Décorateur : récupère l'utilisateur JWT et l'injecte en tant que `current_user`
    dans les kwargs de la route.

    Retourne une réponse 404 si l'utilisateur n'existe plus en base.

    Doit être placé après @jwt_required() dans la pile.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user, error = get_current_user()
        if error:
            return error
        return f(*args, current_user=user, **kwargs)
    return decorated


def require_admin(f):
    """
    Décorateur : récupère l'utilisateur JWT, l'injecte en tant que `current_user`,
    et vérifie que is_admin est True.

    Retourne 404 si introuvable, 403 si non-admin.

    Remplace le pattern _require_admin() local dans cud_admin_api.py.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user, error = get_current_user()
        if error:
            return error
        if not user.is_admin:
            return _err('Accès réservé aux administrateurs.', status=403)
        return f(*args, current_user=user, **kwargs)
    return decorated
