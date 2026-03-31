"""
Helpers et décorateurs communs
"""
from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user
import bleach
import config


def admin_required(f):
    """
    Décorateur pour restreindre l'accès aux administrateurs
    
    Usage:
        @app.route('/admin/...')
        @login_required
        @admin_required
        def ma_fonction_admin():
            ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def get_scale_family_and_color(scale):
    """
    Retourne la couleur associée à une gamme musicale
    
    Args:
        scale: Nom de la gamme (ex: "C MAJOR")
    
    Returns:
        str: Code couleur hexadécimal
    """
    SCALE_COLORS = {
        "C MAJOR": "#A0C4FF", "A MINOR": "#A0C4FF",
        "G MAJOR": "#FFD6A5", "E MINOR": "#FFD6A5",
        "D MAJOR": "#B5E48C", "B MINOR": "#B5E48C",
        "A MAJOR": "#FFADAD", "F# MINOR": "#FFADAD",
        "E MAJOR": "#9BF6FF", "C# MINOR": "#9BF6FF",
        "B MAJOR": "#FFC6FF", "G# MINOR": "#FFC6FF",
        "F# MAJOR": "#FFFFBA", "D# MINOR": "#FFFFBA",
        "C# MAJOR": "#FF9CEE", "A# MINOR": "#FF9CEE",
        "F MAJOR": "#BDB2FF", "D MINOR": "#BDB2FF",
        "A# MAJOR": "#FFB347", "G MINOR": "#FFB347",
        "E# MAJOR": "#CAFFBF", "C# MINOR": "#CAFFBF",
        "Bb MAJOR": "#FFC9DE", "G# MINOR": "#FFC9DE",
        "Eb MAJOR": "#A0E7FF", "C MINOR": "#A0E7FF",
        "Ab MAJOR": "#FDFFB6", "F MINOR": "#FDFFB6",
        "Db MAJOR": "#FFDAB9", "Bb MINOR": "#FFDAB9",
        "Gb MAJOR": "#E0BBE4", "Eb MINOR": "#E0BBE4",
        "Cb MAJOR": "#C9E4E7", "Ab MINOR": "#C9E4E7"
    }
    
    return SCALE_COLORS.get(scale.upper(), "#CCCCCC")


def allowed_file(filename, allowed_extensions):
    """
    Vérifie si un fichier a une extension autorisée
    
    Args:
        filename: Nom du fichier
        allowed_extensions: Set d'extensions autorisées (ex: {'mp3', 'wav'})
    
    Returns:
        bool: True si l'extension est autorisée
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions


def generate_track_image(title, scale, output_path, size=800):
    """
    Génère une image pour un track avec fond coloré selon la gamme

    Args:
        title: Titre du track
        scale: Gamme musicale (ex: "C MAJOR")
        output_path: Chemin où sauvegarder l'image
        size: Taille de l'image (default: 800x800)
    """
    from PIL import Image, ImageDraw, ImageFont
    from flask import current_app
    from pathlib import Path

    # Couleur de fond selon la gamme
    bg_color_hex = get_scale_family_and_color(scale)
    bg_color = tuple(int(bg_color_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))

    # Créer l'image
    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # Logo watermark (si existe)
    logo_path = Path(current_app.root_path) / 'static' / 'images' / 'main' / 'logo.png'
    if logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo = logo.resize((size, size), Image.Resampling.LANCZOS)
            # Rendre le logo transparent (alpha 30)
            alpha = logo.getchannel('A').point(lambda p: 30)
            logo.putalpha(alpha)
            img.paste(logo, (0, 0), logo)
        except Exception as e:
            current_app.logger.warning(f"Erreur chargement logo: {e}", exc_info=True)

    # Texte du titre
    try:
        font_path = Path(current_app.root_path) / 'static' / 'fonts' / 'MomoSignature-Regular.ttf'
        font = ImageFont.truetype(str(font_path), size // 8)
    except:
        font = ImageFont.load_default()

    # Calculer position centrée
    bbox = draw.textbbox((0, 0), title, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Choisir couleur texte (contraste avec fond)
    brightness = (bg_color[0] * 0.299 + bg_color[1] * 0.587 + bg_color[2] * 0.114)
    text_color = (0, 0, 0) if brightness > 180 else (255, 255, 255)

    # Dessiner le texte centré
    draw.text(((size - text_w) // 2, (size - text_h) // 2), title, font=font, fill=text_color)

    # Sauvegarder
    img.save(output_path)

def sanitize_html(input_html):
    """
    Nettoie une chaîne HTML pour éviter les attaques XSS
    
    Args:
        input_html: Chaîne HTML à nettoyer
    
    Returns:
        str: Chaîne HTML nettoyée
    """
    return bleach.clean(
        input_html,
        tags=config.ALLOWED_TAGS,
        attributes=config.ALLOWED_ATTRIBUTES
    )


# ── Helpers Redis — refresh tokens ───────────────────────────────────────────
# Clé Redis : "refresh_token:{user_id}:{jti}"  →  valeur "1"  (TTL = exp du token)
# Usage :
#   store_refresh_token(user.id, jti, ttl)         après chaque create_refresh_token()
#   is_refresh_token_valid(user.id, jti)           dans /auth/refresh
#   revoke_all_refresh_tokens(user.id)             dans /auth/logout et reset-password

REFRESH_PREFIX = "refresh_token:"


def store_refresh_token(user_id: int, jti: str, ttl: int) -> None:
    """Enregistre le JTI du refresh token dans Redis avec TTL = durée de vie du token."""
    from extensions import redis_client
    redis_client.set(f"{REFRESH_PREFIX}{user_id}:{jti}", "1", ex=ttl)


def is_refresh_token_valid(user_id: int, jti: str) -> bool:
    """Vérifie si le refresh token (jti) est encore valide (présent dans Redis)."""
    from extensions import redis_client
    return redis_client.exists(f"{REFRESH_PREFIX}{user_id}:{jti}") == 1


def revoke_all_refresh_tokens(user_id: int) -> None:
    """Révoque TOUS les refresh tokens d'un user (logout, changement de mot de passe)."""
    from extensions import redis_client
    keys = redis_client.keys(f"{REFRESH_PREFIX}{user_id}:*")
    if keys:
        redis_client.delete(*keys)