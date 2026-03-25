"""
Blueprint API - Routes REST pour tags et catégories
API JSON pour la gestion des tags et catégories (CRUD)
"""
from flask import Blueprint, render_template, request, flash, abort, current_app, jsonify
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf, validate_csrf
from werkzeug.exceptions import BadRequest
from extensions import db
from models import Tag, Category
from helpers import admin_required

from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

tags_filters_api_bp = Blueprint('tags_filters_api', __name__, url_prefix='/filters')



@tags_filters_api_bp.route('/tags/all', methods=['GET'])
def get_all_tags():
    """
    Récupérer tous les tags avec leurs catégories,
    + les valeurs uniques de gammes (keys) et styles extraites des tracks approuvés.
    Un seul appel remplace populateFiltersFromDatabase() + loadTagsWithCategories() de filters.js.
    → GET /filters/tags/all
    """
    from models import Track
    from sqlalchemy import distinct

    try:
        # ── Tags ──────────────────────────────────────────────────────────────
        tags = db.session.execute(
            select(Tag).options(selectinload(Tag.category_obj))
        ).scalars().all()

        tags_data = []
        for tag in tags:
            tags_data.append({
                'id':   tag.id,
                'name': tag.name,
                'category': {
                    'name':  tag.category_obj.name  if tag.category_obj else 'other',
                    'color': tag.category_obj.color if tag.category_obj else '#000000'
                }
            })

        # ── Gammes (keys) — valeurs distinctes des tracks approuvés ───────────
        keys = db.session.execute(
            select(distinct(Track.key))
            .where(Track.key.isnot(None), Track.key != '', Track.is_approved == True)
            .order_by(Track.key)
        ).scalars().all()

        # ── Styles — valeurs distinctes des tracks approuvés ──────────────────
        styles = db.session.execute(
            select(distinct(Track.style))
            .where(Track.style.isnot(None), Track.style != '', Track.is_approved == True)
            .order_by(Track.style)
        ).scalars().all()

        return jsonify({
            'success': True,
            'tags':   tags_data,
            'keys':   list(keys),
            'styles': list(styles)
        })

    except Exception as e:
        current_app.logger.warning(f'Erreur API get_all_tags(): {e}')
        return jsonify({
            'success': False, 
            'error': str(e)
            }), 500

@tags_filters_api_bp.route('/tags')
def get_tags():
    tags = db.session.execute(select(Tag).options(selectinload(Tag.category_obj)))

@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['GET'])
def get_tag():
    """Récuperer 1 tag et sa catégorie"""

    try:
        tag = db.get_or_404(Tag, tag_id)
    except Exception as e:
        current_app.logger.warning(f'erreur API get_tag(): {e}')
        return jsonify({ 
            'success': False, 
            'error': str(e)
            }), 500
