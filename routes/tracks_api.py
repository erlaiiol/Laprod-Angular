"""
Blueprint TRACKS version API - Gestion des beats et toplines
Routes pour GET, POST, PUT, DELETE Tracks
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_file, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from pathlib import Path
import uuid
import shutil
import config

from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

from extensions import db, limiter
from models import Track, Tag, Category, User, Topline
from helpers import generate_track_image
from utils.ownership_authorizer import TrackOwnership, requires_ownership

# Imports pour validation et watermarking
try:
    from utils.audio_processing import apply_watermark_and_trim, convert_to_mp3
    WATERMARK_AVAILABLE = True
except ImportError:
    WATERMARK_AVAILABLE = False

try:
    from utils.file_validator import validate_specific_audio_format, validate_stems_archive
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

tracks_api_bp = Blueprint('tracks_api', __name__, url_prefix='/tracks')


@tracks_api_bp.route('/track/<int:track_id>', methods=['GET'])
def get_track(track_id):
    """
    Récupérer les informations d'un track spécifique
    (pour le persistent player)
    """

    try:
        track = db.get_or_404(Track, track_id)

        return jsonify({
            'success': True,
            'data': {
                'track': {
                    'id': track.id,
                    'title': track.title,
                    'bpm': track.bpm,
                    'key': track.key,
                    'style': track.style,
                    'price_mp3': float(track.price_mp3) if track.price_mp3 else None,
                    'price_wav': float(track.price_wav) if track.price_wav else None,
                    'price_stems': float(track.price_stems) if track.price_stems else None,
                    'composer': track.composer_user.username if track.composer_user else None
                }
            }
        })
    except Exception as e:
        current_app.logger.warning(f'erreur API get_track(): {e}')
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': 'Erreur lors de la récupération du track'}
        }), 500


@tracks_api_bp.route('/tracks', methods=['GET'])
def get_tracks():
    """
    Récupérer la liste des tracks avec filtres et pagination
    Utilisé par le front Angular pour la page d'accueil
    """


    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 100)  # Limite max

    try:
        track_query = select(Track).options(selectinload(Track.tags), selectinload(Track.composer_user))

        # Base query: admins voient tout, public voit seulement approuvé
        if not (current_user.is_authenticated and current_user.is_admin):
            track_query = track_query.where(Track.is_approved.is_(True))

        # Récupérer les filtres
        search = request.args.get('search', '').strip()[:50]
        bpm_min = request.args.get('bpm_min', type=int)
        bpm_max = request.args.get('bpm_max', type=int)
        keys_param = request.args.get('keys', '').strip()
        styles_param = request.args.get('styles', '').strip()
        tags_param = request.args.get('tags', '').strip()

        # Sécurité: échapper les caractères spéciaux SQL LIKE
        search = search.replace('%', '\\%').replace('_', '\\_')

        # Appliquer les filtres
        if search:
            track_query = track_query.where(
                or_(
                    Track.title.ilike(f'%{search}%'),
                    Track.composer_user.has(User.username.ilike(f'%{search}%'))
                )
            )

        if bpm_min is not None:
            track_query = track_query.where(Track.bpm >= bpm_min)
        if bpm_max is not None:
            track_query = track_query.where(Track.bpm <= bpm_max)

        if keys_param:
            keys_list = [k.strip() for k in keys_param.split(',') if k.strip()]
            if keys_list:
                track_query = track_query.where(Track.key.in_(keys_list))

        if styles_param:
            styles_list = [s.strip() for s in styles_param.split(',') if s.strip()]
            if styles_list:
                track_query = track_query.where(Track.style.in_(styles_list))

        if tags_param:
            tags_list = [t.strip() for t in tags_param.split(',') if t.strip()]
            if tags_list:
                # Jointure avec tags pour filtrer
                track_query = track_query.where(
                    Track.tags.any(Tag.name.in_(tags_list))
                )

        # Pagination
        tracks = db.session.execute(
            track_query.order_by(Track.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).scalars().all()

        # Compter le total pour la pagination
        total_query = select(func.count()).select_from(track_query.subquery())
        total = db.session.execute(total_query).scalar()

        # Formater la réponse
        tracks_data = []
        for track in tracks:
            track_dict = {
                'id': track.id,
                'title': track.title,
                'bpm': track.bpm,
                'key': track.key,
                'style': track.style,
                'price_mp3': float(track.price_mp3) if track.price_mp3 else None,
                'price_wav': float(track.price_wav) if track.price_wav else None,
                'price_stems': float(track.price_stems) if track.price_stems else None,
                'is_approved': track.is_approved,
                'composer_user': {
                    'username': track.composer_user.username if track.composer_user else None
                },
                'audio_file': track.audio_file,
                'image_file': track.image_file,
                'tags': [{'name': tag.name, 'category': tag.category_obj.name if tag.category_obj else 'other', 'color': tag.category_obj.color if tag.category_obj else '#000000'} for tag in track.tags]
            }
            tracks_data.append(track_dict)

        return jsonify({
            'success': True,
            'data': {
                'tracks': tracks_data,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'pages': (total + per_page - 1) // per_page
                }
            }
        })

    except Exception as e:
        current_app.logger.warning(f'Erreur api get_tracks(): {e}')
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': 'Erreur lors de la récupération des tracks'}
        }), 500