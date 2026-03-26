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
            'data': {
                'tags':   tags_data,
                'keys':   list(keys),
                'styles': list(styles)
            }
        })

    except Exception as e:
        current_app.logger.warning(f'Erreur API get_all_tags(): {e}')
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': 'Erreur lors du chargement des filtres'}
        }), 500

@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['GET'])
def get_tag(tag_id):
    """Récuperer 1 tag et sa catégorie"""

    try:
        tag = db.get_or_404(Tag, tag_id)
        return jsonify({
            'success': True,
            'data': {
                'tag': {
                    'id':   tag.id,
                    'name': tag.name,
                    'category': {
                        'name':  tag.category_obj.name  if tag.category_obj else 'other',
                        'color': tag.category_obj.color if tag.category_obj else '#000000'
                    }
                }
            }
        })
    except Exception as e:
        current_app.logger.warning(f'erreur API get_tag(): {e}')
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': 'Tag introuvable'}
        }), 404


# ============================================
# ROUTES CUD TAGS — admin uniquement
# ============================================

@tags_filters_api_bp.route('/tags', methods=['POST'])
@login_required
def create_tag():
    """Créer un tag (admin seulement) — POST /filters/tags"""

    if not current_user.is_admin:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé'}}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Corps JSON manquant'}}), 400

    tag_name    = data.get('name', '').strip().lower()
    category_id = data.get('category_id')

    if not tag_name:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le nom du tag est requis'}}), 400

    if len(tag_name) > 50:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Nom de tag trop long (50 caractères max)'}}), 400

    if db.session.query(Tag).filter(Tag.name.ilike(tag_name)).first():
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Ce tag existe déjà'}}), 409

    if not category_id:
        default_category = db.session.query(Category).filter_by(name='other').first()
        if not default_category:
            default_category = Category(name='other', color='#6b7280')
            db.session.add(default_category)
            db.session.flush()
        category_id = default_category.id
    else:
        if not db.session.get(Category, category_id):
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Catégorie introuvable'}}), 404

    tag = Tag(name=tag_name, category_id=category_id)
    db.session.add(tag)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': f'Tag "{tag.name}" créé'},
            'data': {
                'tag': {
                    'id':   tag.id,
                    'name': tag.name,
                    'category': {
                        'name':  tag.category_obj.name  if tag.category_obj else 'other',
                        'color': tag.category_obj.color if tag.category_obj else '#6b7280'
                    }
                }
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur création tag: {e}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la création du tag'}}), 500


@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['PUT'])
@login_required
def update_tag(tag_id):
    """Modifier un tag (admin seulement) — PUT /filters/tag/<id>"""

    if not current_user.is_admin:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé'}}), 403

    tag = db.get_or_404(Tag, tag_id)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Corps JSON manquant'}}), 400

    if 'name' in data:
        new_name = data['name'].strip().lower()
        if not new_name:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le nom ne peut pas être vide'}}), 400
        if len(new_name) > 50:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Nom trop long (50 caractères max)'}}), 400
        if db.session.query(Tag).filter(Tag.name == new_name, Tag.id != tag_id).first():
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Un tag avec ce nom existe déjà'}}), 409
        tag.name = new_name

    if 'category_id' in data:
        category_id = int(data['category_id'])
        if not db.session.get(Category, category_id):
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Catégorie introuvable'}}), 404
        tag.category_id = category_id

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': 'Tag mis à jour'},
            'data': {
                'tag': {
                    'id':   tag.id,
                    'name': tag.name,
                    'category': {
                        'name':  tag.category_obj.name  if tag.category_obj else 'other',
                        'color': tag.category_obj.color if tag.category_obj else '#6b7280'
                    }
                }
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur mise à jour tag #{tag_id}: {e}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la mise à jour'}}), 500


@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['DELETE'])
@login_required
def delete_tag(tag_id):
    """Supprimer un tag (admin seulement) — DELETE /filters/tag/<id>"""

    if not current_user.is_admin:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé'}}), 403

    tag = db.get_or_404(Tag, tag_id)
    tag_name = tag.name

    try:
        db.session.delete(tag)
        db.session.commit()
        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': f'Tag "{tag_name}" supprimé'}
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur suppression tag #{tag_id}: {e}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la suppression'}}), 500


# ============================================
# ROUTES CUD CATÉGORIES — admin uniquement
# ============================================

@tags_filters_api_bp.route('/categories', methods=['POST'])
@login_required
def create_category():
    """Créer une catégorie (admin seulement) — POST /filters/categories"""

    if not current_user.is_admin:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé'}}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Corps JSON manquant'}}), 400

    category_name  = data.get('name',  '').strip().lower()
    category_color = data.get('color', '#6b7280')

    if not category_name:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le nom de la catégorie est requis'}}), 400

    if db.session.query(Category).filter_by(name=category_name).first():
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Cette catégorie existe déjà'}}), 409

    category = Category(name=category_name, color=category_color)
    db.session.add(category)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': f'Catégorie "{category.name}" créée'},
            'data': {
                'category': {'id': category.id, 'name': category.name, 'color': category.color}
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur création catégorie: {e}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la création'}}), 500


@tags_filters_api_bp.route('/category/<int:category_id>', methods=['PUT'])
@login_required
def update_category(category_id):
    """Modifier une catégorie (admin seulement) — PUT /filters/category/<id>"""

    if not current_user.is_admin:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé'}}), 403

    category = db.get_or_404(Category, category_id)
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Corps JSON manquant'}}), 400

    if 'name' in data:
        new_name = data['name'].strip().lower()
        if not new_name:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le nom ne peut pas être vide'}}), 400
        if db.session.query(Category).filter(Category.name == new_name, Category.id != category_id).first():
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Une catégorie avec ce nom existe déjà'}}), 409
        category.name = new_name

    if 'color' in data:
        category.color = data['color']

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': 'Catégorie mise à jour'},
            'data': {
                'category': {'id': category.id, 'name': category.name, 'color': category.color}
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur mise à jour catégorie #{category_id}: {e}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la mise à jour'}}), 500


@tags_filters_api_bp.route('/category/<int:category_id>', methods=['DELETE'])
@login_required
def delete_category(category_id):
    """
    Supprimer une catégorie (admin seulement) — DELETE /filters/category/<id>
    Les tags associés sont réassignés à la catégorie "other"
    """

    if not current_user.is_admin:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé'}}), 403

    category = db.get_or_404(Category, category_id)

    if category.name == 'other':
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'La catégorie "other" ne peut pas être supprimée'}}), 400

    # Réassigner les tags orphelins à "other"
    other = db.session.query(Category).filter_by(name='other').first()
    if not other:
        other = Category(name='other', color='#6b7280')
        db.session.add(other)
        db.session.flush()

    reassigned = db.session.query(Tag).filter_by(category_id=category_id).count()
    db.session.query(Tag).filter_by(category_id=category_id).update({'category_id': other.id})
    db.session.delete(category)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'feedback': {
                'level': 'info',
                'message': f'Catégorie supprimée. {reassigned} tag(s) réassigné(s) à "other".'
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur suppression catégorie #{category_id}: {e}')
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la suppression'}}), 500
