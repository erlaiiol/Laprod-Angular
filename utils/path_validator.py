"""
Validation de chemins de fichiers pour éviter Path Traversal
"""
from pathlib import Path
from flask import current_app


def safe_join_path(base_path, user_path):
    """
    Joindre des chemins en évitant le path traversal

    Args:
        base_path: Chemin de base sécurisé (ex: /app/static)
        user_path: Chemin relatif fourni par l'utilisateur/DB (ex: audio/file.mp3)

    Returns:
        Path: Chemin absolu sécurisé

    Raises:
        ValueError: Si path traversal détecté

    Example:
        >>> safe_join_path('/app/static', 'audio/beat.mp3')
        Path('/app/static/audio/beat.mp3')

        >>> safe_join_path('/app/static', '../../.env')
        ValueError: Path traversal détecté
    """
    abs_base = Path(base_path).resolve()
    abs_user = (abs_base / user_path).resolve()

    # Vérifier que le chemin résolu est bien dans le dossier de base
    if not str(abs_user).startswith(str(abs_base)):
        current_app.logger.error(
            f"SECURITY: Path traversal detecte - Base: {abs_base}, User: {user_path}, Result: {abs_user}"
        )
        raise ValueError("Path traversal detecte")

    return abs_user


def validate_static_path(relative_path, check_exists=True):
    """
    Valider qu'un chemin relatif pointe vers un fichier dans static/

    Args:
        relative_path: Chemin relatif depuis static/ (ex: 'audio/beat.mp3')
        check_exists: Si True, vérifie que le fichier existe (défaut: True)

    Returns:
        Path: Chemin absolu sécurisé

    Raises:
        ValueError: Si path traversal détecté ou fichier inexistant

    Example:
        >>> validate_static_path('audio/beat.mp3')
        Path('/app/static/audio/beat.mp3')

        >>> validate_static_path('../../.env')
        ValueError: Path traversal détecté
    """
    static_folder = Path(current_app.root_path) / 'static'
    full_path = safe_join_path(static_folder, relative_path)

    if check_exists and not full_path.exists():
        current_app.logger.warning(f"Fichier introuvable: {relative_path}")
        raise ValueError(f"Fichier introuvable: {relative_path}")

    return full_path
