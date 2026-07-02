"""
Prerender Open Graph — pour les bots de réseaux sociaux (Instagram, WhatsApp, etc.)

Ces routes sont appelées uniquement par nginx quand le User-Agent est un crawler connu.
Les vrais utilisateurs continuent à recevoir le SPA Angular via try_files.

Nginx détecte les bots et proxy vers /og-preview/<path> au lieu de servir index.html.
Chaque handler retourne du HTML minimaliste avec les bonnes balises Open Graph.
"""

import os
from flask import Blueprint, render_template_string, request
from models import Track, User
from extensions import db

og_preview_bp = Blueprint('og_preview', __name__, url_prefix='/og-preview')

SITE_URL   = os.getenv('SITE_URL', 'https://laprod.net')
ASSETS_URL = os.getenv('ASSETS_URL', 'https://laprod.net/db_assets')
LOGO_URL   = f'{SITE_URL}/assets/logo.png'

_OG_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<meta property="og:site_name"    content="LaProd">
<meta property="og:type"         content="{{ og_type }}">
<meta property="og:url"          content="{{ url }}">
<meta property="og:title"        content="{{ title }}">
<meta property="og:description"  content="{{ description }}">
<meta property="og:image"        content="{{ image }}">
<meta property="og:image:width"  content="512">
<meta property="og:image:height" content="512">
<meta name="twitter:card"        content="summary_large_image">
<meta name="twitter:title"       content="{{ title }}">
<meta name="twitter:description" content="{{ description }}">
<meta name="twitter:image"       content="{{ image }}">
<meta http-equiv="refresh" content="0;url={{ url }}">
</head>
<body>
<p><a href="{{ url }}">{{ title }}</a></p>
</body>
</html>"""


def _render(title, description, image, url, og_type='website'):
    return render_template_string(
        _OG_TEMPLATE,
        title=title,
        description=description,
        image=image or LOGO_URL,
        url=url,
        og_type=og_type,
    )


def _asset_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith('http'):
        return path
    return f'{ASSETS_URL}/{path}'


# ── Track ─────────────────────────────────────────────────────────────────────

@og_preview_bp.route('/track/<int:track_id>')
def og_track(track_id: int):
    track = db.session.get(Track, track_id)
    if not track or not track.is_approved:
        return _render('LaProd — Beat introuvable', '', LOGO_URL, SITE_URL), 404

    artist = track.composer_user.username if track.composer_user else 'LaProd'
    price  = f'{float(track.price_mp3):.2f}€' if track.price_mp3 else ''
    desc_parts = [f'Beat par {artist}']
    if track.style:
        desc_parts.append(track.style)
    if track.bpm:
        desc_parts.append(f'{track.bpm} BPM')
    if price:
        desc_parts.append(f'à partir de {price}')
    description = ' · '.join(desc_parts)

    return _render(
        title=f'{track.title} — LaProd',
        description=description,
        image=_asset_url(track.image_file),
        url=f'{SITE_URL}/track/{track_id}',
        og_type='music.song',
    )


# ── Profil utilisateur ────────────────────────────────────────────────────────

@og_preview_bp.route('/profile/<username>')
def og_profile(username: str):
    user = User.query.filter_by(username=username).first()
    if not user:
        return _render('LaProd — Profil introuvable', '', LOGO_URL, SITE_URL), 404

    role_labels = []
    if user.is_beatmaker:       role_labels.append('Beatmaker')
    if user.is_mix_engineer:    role_labels.append('Ingénieur du son')
    if user.is_artist:          role_labels.append('Artiste')

    desc = user.bio or (', '.join(role_labels) + ' sur LaProd' if role_labels else 'Profil sur LaProd')

    return _render(
        title=f'{username} — LaProd',
        description=desc[:200],
        image=_asset_url(user.profile_image),
        url=f'{SITE_URL}/profile/{username}',
    )


# ── Mix engineer (page order) ─────────────────────────────────────────────────

@og_preview_bp.route('/mix/order/<int:engineer_id>')
def og_mix_engineer(engineer_id: int):
    user = db.session.get(User, engineer_id)
    if not user or not user.is_mix_engineer:
        return _render('LaProd — Ingénieur introuvable', '', LOGO_URL, SITE_URL), 404

    price_str = f'à partir de {float(user.mixmaster_price_min):.0f}€' if user.mixmaster_price_min else ''
    desc = user.mixmaster_bio or f'Ingénieur du son certifié sur LaProd{" · " + price_str if price_str else ""}.'

    return _render(
        title=f'{user.username} — Mix & Mastering · LaProd',
        description=desc[:200],
        image=_asset_url(user.profile_image),
        url=f'{SITE_URL}/mix/order/{engineer_id}',
    )


# ── Catch-all pour les routes non gérées ─────────────────────────────────────

@og_preview_bp.route('/', defaults={'path': ''})
@og_preview_bp.route('/<path:path>')
def og_default(path: str):
    return _render(
        title='LaProd — Beats & Mix en ligne',
        description='Achetez des licences de beats, commandez votre mix ou enregistrez des toplines directement en ligne.',
        image=LOGO_URL,
        url=f'{SITE_URL}/{path}',
    )
