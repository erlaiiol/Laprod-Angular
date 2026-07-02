"""
Blueprint API - Routes REST pour tags et catégories
API JSON pour la gestion des tags et catégories (CRUD)
"""
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from extensions import db, csrf
from models import Tag, Category, SimilarArtist
from serializers import ok, err
from utils.auth_helpers import require_admin
from utils.crud_helpers import commit_or_rollback

from sqlalchemy import select, distinct
from sqlalchemy.orm import selectinload

tags_filters_api_bp = Blueprint('tags_filters_api', __name__, url_prefix='/api/filters')


# ── GET public ────────────────────────────────────────────────────────────────

@tags_filters_api_bp.route('/tags/all', methods=['GET'])
def get_all_tags():
    """
    Récupérer tous les tags avec leurs catégories,
    + les valeurs uniques de gammes (keys) et styles extraites des tracks approuvés.
    Un seul appel remplace populateFiltersFromDatabase() + loadTagsWithCategories() de filters.js.
    → GET /filters/tags/all
    """
    from models import Track

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
                    'name':        tag.category_obj.name        if tag.category_obj else 'other',
                    'color':       tag.category_obj.color       if tag.category_obj else '#000000',
                    'description': tag.category_obj.description if tag.category_obj else None,
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

        return ok({'tags': tags_data, 'keys': list(keys), 'styles': list(styles)})

    except Exception as e:
        current_app.logger.warning(f'Erreur API get_all_tags(): {e}')
        return err('Erreur lors du chargement des filtres', status=500)


@tags_filters_api_bp.route('/similar-artists', methods=['GET'])
def get_similar_artists_public():
    """Liste publique des artistes similaires, groupée par scène."""
    artists = db.session.query(SimilarArtist).order_by(SimilarArtist.scene, SimilarArtist.name).all()
    by_scene: dict[str, list] = {}
    for a in artists:
        by_scene.setdefault(a.scene, []).append({'id': a.id, 'name': a.name, 'scene': a.scene})
    scenes = [{'name': s, 'artists': lst} for s, lst in sorted(by_scene.items())]
    return ok({'scenes': scenes})


@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['GET'])
def get_tag(tag_id):
    """Récuperer 1 tag et sa catégorie"""
    try:
        tag = db.get_or_404(Tag, tag_id)
        return ok({'tag': {
            'id':   tag.id,
            'name': tag.name,
            'category': {
                'name':  tag.category_obj.name  if tag.category_obj else 'other',
                'color': tag.category_obj.color if tag.category_obj else '#000000'
            }
        }})
    except Exception as e:
        current_app.logger.warning(f'erreur API get_tag(): {e}')
        return err('Tag introuvable', status=404)


# ── CUD Tags — admin uniquement ───────────────────────────────────────────────

@tags_filters_api_bp.route('/tags', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
@commit_or_rollback
def create_tag(current_user):
    """Créer un tag (admin seulement) — POST /filters/tags"""
    data = request.get_json()
    if not data:
        return err('Corps JSON manquant', level='warning')

    tag_name    = data.get('name', '').strip().lower()
    category_id = data.get('category_id')

    if not tag_name:
        return err('Le nom du tag est requis', level='warning')

    if len(tag_name) > 50:
        return err('Nom de tag trop long (50 caractères max)', level='warning')

    if db.session.query(Tag).filter(Tag.name.ilike(tag_name)).first():
        return err('Ce tag existe déjà', level='warning', status=409)

    if not category_id:
        default_category = db.session.query(Category).filter_by(name='other').first()
        if not default_category:
            default_category = Category(name='other', color='#6b7280')
            db.session.add(default_category)
            db.session.flush()
        category_id = default_category.id
    else:
        if not db.session.get(Category, category_id):
            return err('Catégorie introuvable', level='warning', status=404)

    tag = Tag(name=tag_name, category_id=category_id)
    db.session.add(tag)
    db.session.commit()
    return ok({'tag': {
        'id':   tag.id,
        'name': tag.name,
        'category': {
            'name':  tag.category_obj.name  if tag.category_obj else 'other',
            'color': tag.category_obj.color if tag.category_obj else '#6b7280'
        }
    }}, message=f'Tag "{tag.name}" créé', level='info', status=201)


@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
@commit_or_rollback
def update_tag(tag_id, current_user):
    """Modifier un tag (admin seulement) — PUT /filters/tag/<id>"""
    tag = db.get_or_404(Tag, tag_id)
    data = request.get_json()
    if not data:
        return err('Corps JSON manquant', level='warning')

    if 'name' in data:
        new_name = data['name'].strip().lower()
        if not new_name:
            return err('Le nom ne peut pas être vide', level='warning')
        if len(new_name) > 50:
            return err('Nom trop long (50 caractères max)', level='warning')
        if db.session.query(Tag).filter(Tag.name == new_name, Tag.id != tag_id).first():
            return err('Un tag avec ce nom existe déjà', level='warning', status=409)
        tag.name = new_name

    if 'category_id' in data:
        category_id = int(data['category_id'])
        if not db.session.get(Category, category_id):
            return err('Catégorie introuvable', level='warning', status=404)
        tag.category_id = category_id

    db.session.commit()
    return ok({'tag': {
        'id':   tag.id,
        'name': tag.name,
        'category': {
            'name':  tag.category_obj.name  if tag.category_obj else 'other',
            'color': tag.category_obj.color if tag.category_obj else '#6b7280'
        }
    }}, message='Tag mis à jour', level='info')


@tags_filters_api_bp.route('/tag/<int:tag_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
@commit_or_rollback
def delete_tag(tag_id, current_user):
    """Supprimer un tag (admin seulement) — DELETE /filters/tag/<id>"""
    tag = db.get_or_404(Tag, tag_id)
    tag_name = tag.name
    db.session.delete(tag)
    db.session.commit()
    return ok(message=f'Tag "{tag_name}" supprimé', level='info')


# ── CUD Catégories — admin uniquement ────────────────────────────────────────

@tags_filters_api_bp.route('/categories', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
@commit_or_rollback
def create_category(current_user):
    """Créer une catégorie (admin seulement) — POST /filters/categories"""
    data = request.get_json()
    if not data:
        return err('Corps JSON manquant', level='warning')

    category_name  = data.get('name',  '').strip().lower()
    category_color = data.get('color', '#6b7280')

    if not category_name:
        return err('Le nom de la catégorie est requis', level='warning')

    if db.session.query(Category).filter_by(name=category_name).first():
        return err('Cette catégorie existe déjà', level='warning', status=409)

    category = Category(name=category_name, color=category_color)
    db.session.add(category)
    db.session.commit()
    return ok(
        {'category': {'id': category.id, 'name': category.name, 'color': category.color}},
        message=f'Catégorie "{category.name}" créée', level='info', status=201,
    )


@tags_filters_api_bp.route('/category/<int:category_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
@commit_or_rollback
def update_category(category_id, current_user):
    """Modifier une catégorie (admin seulement) — PUT /filters/category/<id>"""
    category = db.get_or_404(Category, category_id)
    data = request.get_json()
    if not data:
        return err('Corps JSON manquant', level='warning')

    if 'name' in data:
        new_name = data['name'].strip().lower()
        if not new_name:
            return err('Le nom ne peut pas être vide', level='warning')
        if db.session.query(Category).filter(Category.name == new_name, Category.id != category_id).first():
            return err('Une catégorie avec ce nom existe déjà', level='warning', status=409)
        category.name = new_name

    if 'color' in data:
        category.color = data['color']

    db.session.commit()
    return ok(
        {'category': {'id': category.id, 'name': category.name, 'color': category.color}},
        message='Catégorie mise à jour', level='info',
    )


@tags_filters_api_bp.route('/category/<int:category_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
@commit_or_rollback
def delete_category(category_id, current_user):
    """
    Supprimer une catégorie (admin seulement) — DELETE /filters/category/<id>
    Les tags associés sont réassignés à la catégorie "other"
    """
    category = db.get_or_404(Category, category_id)

    if category.name == 'other':
        return err('La catégorie "other" ne peut pas être supprimée', level='warning')

    # Réassigner les tags orphelins à "other"
    other = db.session.query(Category).filter_by(name='other').first()
    if not other:
        other = Category(name='other', color='#6b7280')
        db.session.add(other)
        db.session.flush()

    reassigned = db.session.query(Tag).filter_by(category_id=category_id).count()
    db.session.query(Tag).filter_by(category_id=category_id).update({'category_id': other.id})
    db.session.delete(category)
    db.session.commit()
    return ok(message=f'Catégorie supprimée. {reassigned} tag(s) réassigné(s) à "other".', level='info')
