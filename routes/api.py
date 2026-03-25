"""
Blueprint API - Routes REST pour tags et catégories
API JSON pour la gestion des tags et catégories (CRUD)
"""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from flask_wtf.csrf import generate_csrf, validate_csrf
from werkzeug.exceptions import BadRequest
from extensions import db
from models import Tag, Category
from helpers import admin_required

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

api_bp = Blueprint('api', __name__, url_prefix='/api')

# ============================================
# ROUTE CSRF TOKEN
# ===========================================

@api_bp.route('/csrf-token', methods=['GET'])
def get_csrf_token():
    """Fournir un token CSRF pour les requêtes AJAX"""
    return jsonify({'csrf_token': generate_csrf()})

@api_bp.before_request
def check_csrf_for_json():
    """Vérifier le token CSRF pour les requêtes JSON (POST, PUT, DELETE)"""
    if request.method in ['GET', 'HEAD', 'OPTIONS']:
        return None # Pas besoin de CSRF pour ces méthodes
    
    if request.path == 'api/csrf-token':
        return None # Pas besoin de CSRF pour cette route spécifique
    
    token = request.headers.get('X-CSRFToken')

    if not token:
        return jsonify({
            'success': False,
            'error': 'Token CSRF manquant dans les headers'
        }), 403
    
    try:
        validate_csrf(token)
    except BadRequest:
        return jsonify({
            'success': False,
            'error': 'Token CSRF invalide ou expiré'
        }), 403

    return None

# ============================================
# ROUTES TAGS
# ============================================

@api_bp.route('/tags/all', methods=['GET'])
def get_all_tags():
    """Récupérer tous les tags avec leurs catégories"""
    tags = db.session.query(Tag).join(Category).all()
    
    return jsonify([
        {
            'id': tag.id,
            'name': tag.name,
            'category_id': tag.category_id,
            'category': tag.category_obj.name if tag.category_obj else 'other'
        }
        for tag in tags
    ])


@api_bp.route('/tags', methods=['POST'])
@login_required
@admin_required
def create_tag():
    """Ajouter un tag (admin seulement)"""
    data = request.get_json()
    tag_name = data.get('name', '').strip().lower()
    category_id = data.get('category_id')
    
    if not tag_name:
        return jsonify({'error': 'nom de tag requis'}), 400
    
    existing = db.session.query(Tag).filter(Tag.name.ilike(tag_name)).first()
    if existing:
        return jsonify({'error': 'Tag déjà existant'}), 409
    
    if not category_id:
        default_category = db.session.query(Category).filter_by(name='other').first()
        if not default_category:
            # Créer la catégorie "other" si elle n'existe pas
            default_category = Category(name='other')
            db.session.add(default_category)
            db.session.flush()  # Pour obtenir l'ID
        category_id = default_category.id
    else:
        # Vérifier que la catégorie existe
        category = db.session.get(Category, category_id)
        if not category:
            return jsonify({'error': 'Catégorie inexistante'}), 404
        
    tag = Tag(name=tag_name, category_id=category_id)
    db.session.add(tag)

    try:
        db.session.commit()
        return jsonify({
            'id': tag.id,
            'name': tag.name,
            'category_id': tag.category_id,
            'category': tag.category_obj.name
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/tags/<int:tag_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def manage_tag(tag_id):
    """Gérer un tag spécifique (GET/PUT/DELETE) - admin seulement"""
    
    # Vérifier que c'est un admin
    if not current_user.is_admin:
        return jsonify({'error': 'Accès refusé'}), 403
    
    # Récupérer le tag
    tag = db.get_or_404(Tag, tag_id)
    
    # GET : Retourner les infos du tag
    if request.method == 'GET':
        return jsonify({
            'id': tag.id,
            'name': tag.name,
            'category_id': tag.category_id,
            'category': tag.category_obj.name if tag.category_obj else None
        })
    
    # PUT : Modifier le tag (notamment sa catégorie)
    elif request.method == 'PUT':
        data = request.get_json()
        
        # Modifier le nom si fourni
        if 'name' in data:
            new_name = data['name'].strip()
            if not new_name:
                return jsonify({'error': 'Le nom ne peut pas être vide'}), 400
            
            # Vérifier qu'aucun autre tag n'a ce nom
            existing = db.session.query(Tag).filter(Tag.name == new_name, Tag.id != tag_id).first()
            if existing:
                return jsonify({'error': 'Un tag avec ce nom existe déjà'}), 409
            
            tag.name = new_name
        
        # Modifier la catégorie si fournie
        if 'category_id' in data:
            category_id = int(data['category_id'])
            
            # Vérifier que la catégorie existe
            category = db.session.get(Category, category_id)
            if not category:
                return jsonify({'error': 'Catégorie inexistante'}), 404
            
            tag.category_id = category_id
        
        try:
            db.session.commit()
            return jsonify({
                'success': True,
                'tag': {
                    'id': tag.id,
                    'name': tag.name,
                    'category_id': tag.category_id,
                    'category': tag.category_obj.name
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    # DELETE : Supprimer le tag
    elif request.method == 'DELETE':
        try:
            db.session.delete(tag)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Tag supprimé'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500


@api_bp.route('/tags/search', methods=['GET'])
@login_required
def search_tags():
    """Rechercher des tags existants (autocomplétion)"""
    query = request.args.get('q', '').strip().lower()
    
    if len(query) < 2:
        return jsonify([])
    
    # Rechercher les tags qui correspondent
    tags = db.session.query(Tag).filter(Tag.name.like(f'%{query}%')).limit(10).all()
    
    return jsonify([
        {
            'name': tag.name,
            'category': tag.category_obj.name if tag.category_obj else 'other'
        }
        for tag in tags
    ])


# ============================================
# ROUTES CATÉGORIES
# ============================================

@api_bp.route('/categories', methods=['GET'])
def get_categories():
    """Récupérer toutes les catégories (public pour la coloration des tags)"""
    categories = db.session.query(Category).all()
    return jsonify([
        {'id': c.id, 'name': c.name, 'color': c.color if c.color else '#6b7280'}
        for c in categories
    ])


@api_bp.route('/tags', methods=['GET'])
def get_all_tags_simple():
    """Récupérer tous les tags (version simple avec catégories)"""
    tags = db.session.query(Tag).join(Category).all()

    return jsonify({
        'success': True,
        'tags': [
            {
                'id': tag.id,
                'name': tag.name,
                'category_id': tag.category_id,
                'category': tag.category_obj.name if tag.category_obj else 'other'
            }
            for tag in tags
        ]
    })


@api_bp.route('/categories', methods=['POST'])
@login_required
@admin_required
def create_category():
    """Créer une nouvelle catégorie (admin seulement)"""
    data = request.get_json()
    category_name = data.get('name', '').strip().lower()
    category_color = data.get('color', '#6b7280')  # Couleur par défaut

    if not category_name:
        return jsonify({'success': False, 'error': 'Nom de catégorie requis'}), 400

    # Vérifier si elle existe déjà
    existing = db.session.query(Category).filter_by(name=category_name).first()
    if existing:
        return jsonify({'success': False, 'error': 'Catégorie déjà existante'}), 409

    # Créer la nouvelle catégorie
    category = Category(name=category_name, color=category_color)
    db.session.add(category)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'id': category.id,
            'name': category.name,
            'color': category.color,
            'message': 'Catégorie créée avec succès'
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/categories/<int:category_id>', methods=['GET', 'PUT'])
@login_required
def manage_category(category_id):
    """Récupérer ou modifier une catégorie spécifique"""
    category = db.get_or_404(Category, category_id)

    if request.method == 'GET':
        tags = db.session.query(Tag).filter_by(category_id=category_id).all()

        return jsonify({
            'id': category.id,
            'name': category.name,
            'color': category.color,
            'tags': [{
                'id': tag.id,
                'name': tag.name
            } for tag in tags]
        })

    elif request.method == 'PUT':
        # Vérifier admin
        if not current_user.is_admin:
            return jsonify({'success': False, 'error': 'Accès refusé'}), 403

        data = request.get_json()

        # Mettre à jour le nom si fourni
        if 'name' in data:
            new_name = data['name'].strip().lower()
            if not new_name:
                return jsonify({'success': False, 'error': 'Le nom ne peut pas être vide'}), 400

            # Vérifier qu'aucune autre catégorie n'a ce nom
            existing = db.session.query(Category).filter(Category.name == new_name, Category.id != category_id).first()
            if existing:
                return jsonify({'success': False, 'error': 'Une catégorie avec ce nom existe déjà'}), 409

            category.name = new_name

        # Mettre à jour la couleur si fournie
        if 'color' in data:
            category.color = data['color']

        try:
            db.session.commit()
            return jsonify({
                'success': True,
                'category': {
                    'id': category.id,
                    'name': category.name,
                    'color': category.color
                }
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/categories/<int:category_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(category_id):
    """Supprimer une catégorie et réassigner ses tags à 'other'"""
    category = db.get_or_404(Category, category_id)

    other = db.session.query(Category).filter_by(name='other').first()
    if not other:
        other = Category(name='other', color='#6b7280')
        db.session.add(other)
        db.session.flush()

    db.session.query(Tag).filter_by(category_id=category_id).update({'category_id': other.id})
    db.session.delete(category)

    try:
        db.session.commit()
        from flask import redirect, url_for, flash
        flash(f'Catégorie supprimée, tags réassignés à "other".', 'success')
        return redirect(url_for('admin.admin_categories'))
    except Exception as e:
        db.session.rollback()
        from flask import redirect, url_for, flash
        flash(f'Erreur lors de la suppression : {str(e)}', 'danger')
        return redirect(url_for('admin.admin_categories'))


# ============================================
# ROUTES FILTRES
# ============================================

@api_bp.route('/filter-options', methods=['GET'])
def get_filter_options():
    """
    Récupérer toutes les options disponibles pour les filtres
    (gammes, styles, tags)
    """
    from models import Track

    try:
        # Récupérer toutes les tracks approuvées
        tracks = db.session.query(Track).filter_by(is_approved=True).all()

        # Extraire les valeurs uniques
        keys = sorted(list(set(track.key for track in tracks if track.key)))
        styles = sorted(list(set(track.style for track in tracks if track.style)))

        # Extraire tous les tags (relation many-to-many)
        all_tags = set()
        for track in tracks:
            # track.tags est une liste d'objets Tag (relation many-to-many)
            for tag in track.tags:
                all_tags.add(tag.name)

        tags = sorted(list(all_tags))

        return jsonify({
            'success': True,
            'keys': keys,
            'styles': styles,
            'tags': tags
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500