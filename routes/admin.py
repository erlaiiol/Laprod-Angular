"""
Blueprint ADMIN - Administration et modération
Routes pour gérer les tracks, users, categories et toplines
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from werkzeug.utils import secure_filename
from flask_login import login_required, current_user
from datetime import datetime
import os
import config

from pathlib import Path
from extensions import db
from models import Track, User, Tag, Category, Topline, MixMasterRequest, Contract, PriceChangeRequest
from helpers import admin_required, generate_track_image

from utils import email_service, notification_service
from utils.ownership_authorizer import ToplineOwnership, requires_ownership

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

admin_bp = Blueprint('admin', __name__, url_prefix='/legacy/admin')

# chemin vers le dossier des images de tracks
tracks_images_folder = config.IMAGES_FOLDER / 'tracks'


# ============================================
# NEW ADMIN ROUTES - SEPARATE PAGES
# ============================================

@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Dashboard admin avec statistiques générales"""
    # Statistiques tracks
    pending_tracks_count = db.session.query(Track).filter_by(is_approved=False).count()
    approved_tracks_count = db.session.query(Track).filter_by(is_approved=True).count()
    total_tracks = db.session.query(Track).count()

    # Statistiques users
    total_users = db.session.query(User).filter_by(account_status='active').count()
    premium_users = db.session.query(User).filter_by(is_premium=True, account_status='active').count()
    beatmakers_count = db.session.query(User).filter_by(is_beatmaker=True, account_status='active').count()
    artists_count = db.session.query(User).filter_by(is_artist=True, account_status='active').count()
    engineers_count = db.session.query(User).filter_by(is_mixmaster_engineer=True, account_status='active').count()

    # Statistiques contrats
    total_contracts = db.session.query(Contract).count()
    exclusive_contracts = db.session.query(Contract).filter_by(is_exclusive=True).count()

    # Statistiques Mix/Master
    mm_in_progress = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.status.in_(['accepted', 'processing', 'delivered'])
    ).count()
    mm_completed = db.session.query(MixMasterRequest).filter_by(status='completed').count()

    # Activité récente (derniers tracks approuvés)
    recent_tracks = db.session.query(Track).filter_by(is_approved=True).order_by(
        Track.approved_at.desc()
    ).limit(5).all()

    # Derniers utilisateurs inscrits
    recent_users = db.session.query(User).filter_by(account_status='active').order_by(
        User.created_at.desc()
    ).limit(5).all()

    return render_template('admin/dashboard.html',
                         active_tab='dashboard',
                         page_title='Dashboard',
                         pending_tracks_count=pending_tracks_count,
                         approved_tracks_count=approved_tracks_count,
                         total_tracks=total_tracks,
                         total_users=total_users,
                         premium_users=premium_users,
                         beatmakers_count=beatmakers_count,
                         artists_count=artists_count,
                         engineers_count=engineers_count,
                         total_contracts=total_contracts,
                         exclusive_contracts=exclusive_contracts,
                         mm_in_progress=mm_in_progress,
                         mm_completed=mm_completed,
                         recent_tracks=recent_tracks,
                         recent_users=recent_users,
                         pending_count=pending_tracks_count)


@admin_bp.route('/tracks')
@login_required
@admin_required
def admin_tracks():
    """Page de gestion des tracks avec filtrage par statut"""
    status = request.args.get('status', 'pending')

    if status == 'pending':
        tracks = db.session.query(Track).filter_by(is_approved=False).order_by(Track.created_at.desc()).all()
    elif status == 'approved':
        tracks = db.session.query(Track).filter_by(is_approved=True).order_by(Track.created_at.desc()).all()
    else:
        tracks = db.session.query(Track).order_by(Track.created_at.desc()).all()

    # Compter pour les badges
    pending_count = db.session.query(Track).filter_by(is_approved=False).count()
    approved_count = db.session.query(Track).filter_by(is_approved=True).count()

    return render_template('admin/tracks.html',
                         active_tab='tracks',
                         page_title='Gestion des Beats',
                         tracks=tracks,
                         status=status,
                         pending_count=pending_count,
                         approved_count=approved_count)


@admin_bp.route('/users')
@login_required
@admin_required
def admin_users():
    """Page de gestion des utilisateurs avec filtrage par type"""
    user_type = request.args.get('user_type', 'all')

    # Query de base
    query = User.query

    # Filtrage par type
    if user_type == 'beatmakers':
        query = query.filter_by(is_beatmaker=True)
    elif user_type == 'artists':
        query = query.filter_by(is_artist=True)
    elif user_type == 'engineers':
        query = query.filter_by(is_mixmaster_engineer=True)

    all_users = query.order_by(User.created_at.desc()).all()

    # Enrichir avec statistiques
    users_data = []
    for user in all_users:
        tracks_count = db.session.query(Track).filter_by(composer_id=user.id).count()
        contracts_count = db.session.query(Contract).filter_by(client_id=user.id).count()
        mm_count = db.session.query(MixMasterRequest).filter_by(engineer_id=user.id).count()

        users_data.append({
            'user': user,
            'tracks_count': tracks_count,
            'contracts_count': contracts_count,
            'mm_count': mm_count
        })

    # Compter pour badges
    beatmakers_count = db.session.query(User).filter_by(is_beatmaker=True).count()
    artists_count = db.session.query(User).filter_by(is_artist=True).count()
    engineers_count = db.session.query(User).filter_by(is_mixmaster_engineer=True).count()
    all_count = db.session.query(User).count()

    # Compter pending tracks pour sidebar
    pending_count = db.session.query(Track).filter_by(is_approved=False).count()

    return render_template('admin/users.html',
                         active_tab='users',
                         page_title='Gestion des Utilisateurs',
                         users=users_data,
                         user_type=user_type,
                         beatmakers_count=beatmakers_count,
                         artists_count=artists_count,
                         engineers_count=engineers_count,
                         all_count=all_count,
                         pending_count=pending_count)


@admin_bp.route('/contracts')
@login_required
@admin_required
def admin_contracts():
    """Page de gestion des contrats"""
    contracts = db.session.query(Contract).order_by(Contract.created_at.desc()).all()

    # Statistiques
    exclusive_count = db.session.query(Contract).filter_by(is_exclusive=True).count()
    non_exclusive_count = db.session.query(Contract).filter_by(is_exclusive=False).count()
    total_revenue = sum([c.price for c in contracts])

    # Compter pending tracks pour sidebar
    pending_count = db.session.query(Track).filter_by(is_approved=False).count()

    return render_template('admin/contracts.html',
                         active_tab='contracts',
                         page_title='Gestion des Contrats',
                         contracts=contracts,
                         exclusive_count=exclusive_count,
                         non_exclusive_count=non_exclusive_count,
                         total_revenue=total_revenue,
                         pending_count=pending_count)


@admin_bp.route('/transactions')
@login_required
@admin_required
def admin_transactions():
    """Page de gestion des transactions Mix/Master"""
    status = request.args.get('status', 'all')

    # Filtrer par statut
    if status == 'in_progress':
        transactions = db.session.query(MixMasterRequest).filter(
            MixMasterRequest.status.in_(['accepted', 'processing', 'delivered'])
        ).order_by(MixMasterRequest.created_at.desc()).all()
    elif status == 'completed':
        transactions = db.session.query(MixMasterRequest).filter_by(status='completed').order_by(
            MixMasterRequest.completed_at.desc()
        ).all()
    elif status == 'awaiting':
        transactions = db.session.query(MixMasterRequest).filter_by(status='awaiting_acceptance').order_by(
            MixMasterRequest.created_at.desc()
        ).all()
    else:
        transactions = db.session.query(MixMasterRequest).order_by(
            MixMasterRequest.created_at.desc()
        ).all()

    # Compter pour badges
    awaiting_count = db.session.query(MixMasterRequest).filter_by(status='awaiting_acceptance').count()
    in_progress_count = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.status.in_(['accepted', 'processing', 'delivered'])
    ).count()
    completed_count = db.session.query(MixMasterRequest).filter_by(status='completed').count()
    all_count = db.session.query(MixMasterRequest).count()

    # Revenue total
    completed_transactions = db.session.query(MixMasterRequest).filter_by(status='completed').all()
    total_revenue = sum([t.total_price for t in completed_transactions])

    # Compter pending tracks pour sidebar
    pending_count = db.session.query(Track).filter_by(is_approved=False).count()

    return render_template('admin/transactions.html',
                         active_tab='transactions',
                         page_title='Transactions Mix/Master',
                         transactions=transactions,
                         status=status,
                         awaiting_count=awaiting_count,
                         in_progress_count=in_progress_count,
                         completed_count=completed_count,
                         all_count=all_count,
                         total_revenue=total_revenue,
                         pending_count=pending_count)


@admin_bp.route('/categories')
@login_required
@admin_required
def admin_categories():
    """Page de gestion des catégories et tags"""
    categories = db.session.query(Category).all()

    # Enrichir avec le nombre de tags
    categories_data = []
    for cat in categories:
        tag_count = db.session.query(Tag).filter_by(category_id=cat.id).count()
        categories_data.append({
            'id': cat.id,
            'name': cat.name,
            'color': cat.color if cat.color else '#6b7280',
            'tag_count': tag_count
        })

    # Compter pending tracks pour sidebar
    pending_count = db.session.query(Track).filter_by(is_approved=False).count()

    return render_template('admin/categories.html',
                         active_tab='categories',
                         page_title='Tags & Catégories',
                         categories=categories_data,
                         pending_count=pending_count)


# ============================================
# DASHBOARD ADMIN (OLD - TO BE DEPRECATED)
# ============================================

@admin_bp.route('/old')
@login_required
@admin_required
def admin_panel():
    """
    [DEPRECATED] Page d'administration principale avec tous les onglets
    Redirige vers la nouvelle structure avec sidebar
    """
    return redirect(url_for('admin.dashboard'))

# ============================================
# GESTION DES TRACKS
# ============================================

@admin_bp.route('/track/<int:track_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_track(track_id):
    """Éditer un track - Interface admin avancée avec création de tags"""
    track = db.get_or_404(Track, track_id)
    
    if request.method == 'POST':
        # Mettre à jour les champs de base
        track.title = request.form.get('title')
        track.bpm = int(request.form.get('bpm'))
        track.key = request.form.get('key')
        track.style = request.form.get('style')
        track.price_mp3 = float(request.form.get('price_mp3'))
        track.price_wav = float(request.form.get('price_wav'))
        if track.file_stems and request.form.get('price_stems'):
            track.price_stems = float(request.form.get('price_stems'))

        # Gérer les tags (IDs séparés par des virgules)
        tag_ids_str = request.form.get('tag_ids', '')
        if tag_ids_str:
            selected_tag_ids = [int(id.strip()) for id in tag_ids_str.split(',') if id.strip()]
            tags = db.session.query(Tag).filter(Tag.id.in_(selected_tag_ids)).all()
            track.tags = tags
        else:
            track.tags = []
        
        # Gestion de l'image
        file_image = request.files.get('file_image')
        tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
        tracks_img_folder.mkdir(parents=True, exist_ok=True)

        if file_image and file_image.filename != '':
            # Nouvelle image fournie par l'utilisateur
            from utils.file_validator import validate_image_file
            import uuid
            is_valid, error_message = validate_image_file(file_image)
            if is_valid:
                original_filename = secure_filename(file_image.filename)
                extension = Path(original_filename).suffix.lower()
                safe_title = secure_filename(track.title)[:30]
                new_img_filename = f"{safe_title}_{uuid.uuid4().hex[:8]}{extension}"
                new_img_path = tracks_img_folder / new_img_filename
                try:
                    # Supprimer l'ancienne image custom si elle existe
                    if track.image_file:
                        old_name = track.image_file.replace('images/tracks/', '')
                        if old_name and old_name != 'default_track.png':
                            old_path = tracks_img_folder / old_name
                            if old_path.exists():
                                old_path.unlink()
                    file_image.save(new_img_path)
                    track.image_file = f'images/tracks/{new_img_filename}'
                except Exception as e:
                    current_app.logger.error(f"Erreur sauvegarde image: {e}", exc_info=True)
                    flash("Erreur lors du téléchargement de l'image. L'ancienne image est conservée.", 'warning')
            else:
                flash(f'Image non valide : {error_message}. L\'ancienne image est conservée.', 'warning')
        elif not track.image_file:
            # Aucune image uploadée ET aucune image existante → auto-génération
            try:
                import uuid
                img_filename = f"{secure_filename(track.title)}_{uuid.uuid4().hex[:8]}.png"
                img_path = tracks_img_folder / img_filename
                generate_track_image(track.title, track.key, img_path)
                track.image_file = f'images/tracks/{img_filename}'
            except Exception as e:
                current_app.logger.warning(f"Erreur génération image: {e}", exc_info=True)
        # else : image existante conservée telle quelle
        
        try:
            db.session.commit()
            flash('Track mis à jour avec succès (admin) !', 'success')
            return redirect(url_for('admin.admin_panel'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour: {str(e)}', 'danger')
    
    # GET : afficher le formulaire
    existing_tags = [
        {
            'id': tag.id,
            'name': tag.name,
            'category': tag.category_obj.name if tag.category_obj else 'other'
        }
        for tag in track.tags
    ]
    
    return render_template('edit_track.html', track=track, existing_tags=existing_tags)


@admin_bp.route('/approve-track/<int:track_id>')
@login_required
@admin_required
def approve_track(track_id):
    """Approuver un track"""
    track = db.get_or_404(Track, track_id)
    track.is_approved = True
    track.approved_at = datetime.now()
    db.session.commit()

    try:
        email_service.send_track_approved_email(track)
    except Exception as e:
        current_app.logger.warning(f"Erreur lors de l'envoi de l'email d'approbation Track is_approved: {e}", exc_info=True)
    try:
        notification_service.send_track_approved_notification(track)
    except Exception as e:
            current_app.logger.warning(f"Erreur lors de l'envoi de la notification d'approbation Track is_approved: {e}", exc_info=True)

    flash(f'Track "{track.title}" approuvé !', 'success')
    return redirect(url_for('admin.admin_tracks', status='pending'))


@admin_bp.route('/reject-track/<int:track_id>')
@login_required
@admin_required
def reject_track(track_id):
    """Rejeter et supprimer un track"""
    track = db.get_or_404(Track, track_id)
    title = track.title
    db.session.delete(track)
    db.session.commit()

    try:
        email_service.send_track_rejected_email(track)
    except Exception as e:
        current_app.logger.warning(f"Erreur lors de l'envoi de l'email de rejet Track is_approved: {e}", exc_info=True)

    try:
        notification_service.send_track_rejected_notification(track)
    except Exception as e:
        current_app.logger.warning(f"Erreur lors de l'envoi de la notification de rejet Track is_approved: {e}", exc_info=True)


    flash(f'Track "{title}" supprimé.', 'warning')
    return redirect(url_for('admin.admin_tracks', status='pending'))


# ============================================
# GESTION DES UTILISATEURS
# ============================================

@admin_bp.route('/toggle-user/<int:user_id>')
@login_required
@admin_required
def toggle_user(user_id):
    """Activer/Désactiver un utilisateur"""
    user = db.get_or_404(User, user_id)

    if user.id == current_user.id:
        flash('Vous ne pouvez pas vous désactiver !', 'danger')
        return redirect(url_for('admin.admin_users'))

    # Toggle account_status entre 'active' et 'deleted'
    if user.account_status == 'active':
        user.account_status = 'deleted'
        status = "désactivé"
    else:
        user.account_status = 'active'
        status = "activé"

    db.session.commit()
    flash(f'Utilisateur {user.username} {status}.', 'info')
    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/toggle-user-role/<int:user_id>/<string:role>', methods=['POST'])
@login_required
@admin_required
def toggle_user_role(user_id, role):
    """Toggle un rôle spécifique pour un utilisateur (beatmaker, artist, engineer, producer_arranger)"""
    user = db.get_or_404(User, user_id)

    if role == 'beatmaker':
        user.is_beatmaker = not user.is_beatmaker
        status = "activé" if user.is_beatmaker else "désactivé"
        flash(f'Rôle Beatmaker {status} pour {user.username}.', 'info')
    elif role == 'artist':
        user.is_artist = not user.is_artist
        status = "activé" if user.is_artist else "désactivé"
        flash(f'Rôle Interprète {status} pour {user.username}.', 'info')
    elif role == 'engineer':
        user.is_mixmaster_engineer = not user.is_mixmaster_engineer
        status = "activé" if user.is_mixmaster_engineer else "désactivé"
        flash(f'Rôle Engineer {status} pour {user.username}.', 'info')
    elif role == 'producer_arranger':
        # Vérifier que l'utilisateur est déjà engineer
        if not user.is_mixmaster_engineer:
            flash(f'{user.username} doit d\'abord être Engineer pour devenir Producteur/Arrangeur.', 'warning')
        else:
            user.is_certified_producer_arranger = not user.is_certified_producer_arranger
            status = "activé" if user.is_certified_producer_arranger else "désactivé"
            flash(f'Certification Producteur/Arrangeur {status} pour {user.username}.', 'info')
    else:
        flash('Rôle invalide.', 'error')

    db.session.commit()
    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/manage-users', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_users():
    """Gérer les utilisateurs"""
    if request.method == 'POST':
        try:
            user_id = request.form.get('user_id')
            action = request.form.get('action')

            user = db.get_or_404(User, user_id)
        except Exception as e:
            flash(f'Erreur: {str(e)}', f'{user.username} introuvable.', 'danger')
            return redirect(url_for('admin.manage_users'))
        
        if action == 'toggle':
            if user.account_status == 'active':
                user.account_status = 'deleted'
                status = "désactivé"
            else:
                user.account_status = 'active'
                status = "activé"

            db.session.commit()
            flash(f'Utilisateur {user.username} {status}.', 'info')

        return redirect(url_for('admin.manage_users'))

    users = db.session.query(User).all()
    return render_template('_admin_manage_users.html', users=users)



# ============================================
# GESTION DES CATÉGORIES
# ============================================

@admin_bp.route('/categories', methods=['GET'])
@login_required
@admin_required
def manage_categories():
    """Page d'administration des catégories"""
    categories = db.session.query(Category).all()
    
    # Compter le nombre de tags par catégorie
    categories_data = []
    for cat in categories:
        tag_count = db.session.query(Tag).filter_by(category_id=cat.id).count()
        categories_data.append({
            'id': cat.id,
            'name': cat.name,
            'tag_count': tag_count
        })
    
    return render_template('admin_categories.html', categories=categories_data)


# Note: La suppression de catégories se fait désormais via l'API REST
# Route DELETE /api/categories/<id> (voir routes/api.py)


# ============================================
# GESTION DES MIX/MASTER ENGINEERS
# ============================================

@admin_bp.route('/engineers')
@login_required
@admin_required
def manage_engineers():
    """Page d'administration des engineers avec navigation par tabs"""
    tab = request.args.get('tab', 'pending')

    # Engineers certifiés
    certified_engineers = db.session.query(User).filter_by(is_mixmaster_engineer=True).all()

    # Engineers en attente de certification (ont soumis un échantillon mais pas encore certifiés)
    pending_engineers = db.session.query(User).filter(
        User.is_mix_engineer == True,
        User.mixmaster_sample_submitted == True,
        User.is_mixmaster_engineer == False
    ).all()

    # Demandes de certification Producteur/Arrangeur
    producer_arranger_requests = db.session.query(User).filter(
        User.is_mixmaster_engineer == True,
        User.producer_arranger_request_submitted == True,
        User.is_certified_producer_arranger == False
    ).all()

    # Demandes de modification de prix en attente
    pending_price_changes = db.session.query(PriceChangeRequest).filter_by(status='pending').order_by(
        PriceChangeRequest.created_at.desc()
    ).all()

    # Tous les utilisateurs
    all_users = db.session.query(User).order_by(User.username).all()

    # Compter pending tracks pour sidebar
    pending_count = db.session.query(Track).filter_by(is_approved=False).count()

    return render_template('admin/engineers.html',
                         active_tab='engineers',
                         page_title='Mix Engineers',
                         tab=tab,
                         certified_engineers=certified_engineers,
                         pending_engineers=pending_engineers,
                         producer_arranger_requests=producer_arranger_requests,
                         pending_price_changes=pending_price_changes,
                         all_users=all_users,
                         pending_count=pending_count)


@admin_bp.route('/engineers/certify/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def certify_engineer(user_id):
    """Certifier un utilisateur comme mix/master engineer"""
    user = db.get_or_404(User, user_id)

    user.is_mixmaster_engineer = True
    db.session.commit()

    flash(f'{user.username} a été certifié comme mix/master engineer !', 'success')
    return redirect(url_for('admin.manage_engineers'))


@admin_bp.route('/engineers/revoke/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def revoke_engineer(user_id):
    """Révoquer la certification d'un engineer"""
    user = db.get_or_404(User, user_id)

    # Vérifier s'il a des demandes en cours
    active_requests = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.engineer_id == user_id,
        MixMasterRequest.status.in_(['pending', 'processing', 'delivered'])
    ).count()

    if active_requests > 0:
        flash(f'{user.username} a {active_requests} demande(s) en cours. Impossible de révoquer maintenant.', 'danger')
        return redirect(url_for('admin.manage_engineers'))

    user.is_mixmaster_engineer = False
    db.session.commit()

    flash(f'La certification de {user.username} a été révoquée.', 'warning')
    return redirect(url_for('admin.manage_engineers'))


@admin_bp.route('/engineers/reject-sample/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reject_engineer_sample(user_id):
    """Rejeter la demande de certification d'un engineer"""
    user = db.get_or_404(User, user_id)

    # Réinitialiser les informations de soumission
    user.mixmaster_sample_submitted = False
    user.mixmaster_sample_raw = None
    user.mixmaster_sample_processed = None
    user.mixmaster_bio = None
    user.mixmaster_reference_price = None
    user.mixmaster_price_min = None

    db.session.commit()

    flash(f'La demande de certification de {user.username} a été rejetée.', 'info')
    return redirect(url_for('admin.manage_engineers'))

@admin_bp.route('/price-requests/approve/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def approve_price_change(request_id):
    """Approuver une demande de modification de prix"""
    price_request = db.get_or_404(PriceChangeRequest, request_id)

    if price_request.status != 'pending':
        flash('Cette demande a déjà été traitée.', 'warning')
        return redirect(url_for('admin.manage_engineers'))

    # Mettre à jour les prix de l'engineer (arrondis)
    engineer = price_request.engineer
    engineer.mixmaster_reference_price = round(price_request.new_reference_price)
    engineer.mixmaster_price_min = round(price_request.new_price_min)

    # Marquer la demande comme approuvée
    price_request.status = 'approved'
    price_request.processed_at = datetime.now()
    price_request.processed_by = current_user.id

    db.session.commit()

    flash(f' Prix approuvés pour {engineer.username}: {engineer.mixmaster_price_min}€ - {engineer.mixmaster_reference_price}€ (réf.)', 'success')
    return redirect(url_for('admin.manage_engineers'))


@admin_bp.route('/price-requests/reject/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def reject_price_change(request_id):
    """Rejeter une demande de modification de prix"""
    price_request = db.get_or_404(PriceChangeRequest, request_id)

    if price_request.status != 'pending':
        flash('Cette demande a déjà été traitée.', 'warning')
        return redirect(url_for('admin.manage_engineers'))

    # Marquer la demande comme rejetée
    price_request.status = 'rejected'
    price_request.processed_at = datetime.now()
    price_request.processed_by = current_user.id

    db.session.commit()

    flash(f' Demande de prix rejetée pour {price_request.engineer.username}', 'info')
    return redirect(url_for('admin.manage_engineers'))


# ============================================
# GESTION CERTIFICATION PRODUCTEUR/ARRANGEUR
# ============================================

@admin_bp.route('/producer-arranger/approve/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def approve_producer_arranger(user_id):
    """Approuver un utilisateur comme producteur/arrangeur certifié"""
    user = db.get_or_404(User, user_id)

    # Vérifier qu'il a bien demandé la certification
    if not user.producer_arranger_request_submitted:
        flash(f'{user.username} n\'a pas demandé la certification producteur/arrangeur.', 'warning')
        return redirect(url_for('admin.manage_engineers'))

    # Vérifier qu'il est déjà mix/master engineer
    if not user.is_mixmaster_engineer:
        flash(f'{user.username} doit d\'abord être certifié mix/master engineer.', 'warning')
        return redirect(url_for('admin.manage_engineers'))

    user.is_certified_producer_arranger = True

    db.session.commit()

    flash(f'{user.username} a été certifié comme producteur/arrangeur !', 'success')
    return redirect(url_for('admin.manage_engineers'))


@admin_bp.route('/producer-arranger/revoke/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def revoke_producer_arranger(user_id):
    """Révoquer la certification producteur/arrangeur"""
    user = db.get_or_404(User, user_id)

    user.is_certified_producer_arranger = False
    user.producer_arranger_request_submitted = False
    db.session.commit()

    flash(f'La certification producteur/arrangeur de {user.username} a été révoquée.', 'warning')
    return redirect(url_for('admin.manage_engineers'))


@admin_bp.route('/producer-arranger/reject/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reject_producer_arranger_request(user_id):
    """Rejeter la demande de certification producteur/arrangeur"""
    user = db.get_or_404(User, user_id)

    user.producer_arranger_request_submitted = False
    db.session.commit()

    flash(f'La demande de certification producteur/arrangeur de {user.username} a été rejetée.', 'info')
    return redirect(url_for('admin.manage_engineers'))


@admin_bp.route('/engineers/update-prices/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def update_engineer_prices(user_id):
    """
    [ADMIN ONLY] Modifier directement les prix d'un engineer

    Cette route permet à l'admin de modifier les prix sans passer par le système
    de demande/approbation. Utile pour corrections rapides.
    """
    user = db.get_or_404(User, user_id)

    # Vérifier que c'est bien un engineer
    if not user.is_mixmaster_engineer:
        flash(f'{user.username} n\'est pas un mix/master engineer.', 'warning')
        return redirect(url_for('admin.manage_engineers'))

    # Récupérer et valider les nouveaux prix
    try:
        new_price_min = round(float(request.form.get('new_price_min', 0)))
        new_reference_price = round(float(request.form.get('new_reference_price', 0)))
    except (ValueError, TypeError):
        flash('Prix invalides. Veuillez entrer des nombres valides.', 'error')
        return redirect(url_for('admin.manage_engineers'))

    # Validation des bornes
    if new_price_min < 20 or new_price_min > 500:
        flash('Le prix minimum doit être entre 20€ et 500€.', 'error')
        return redirect(url_for('admin.manage_engineers'))

    if new_reference_price < 20 or new_reference_price > 500:
        flash('Le prix de référence doit être entre 20€ et 500€.', 'error')
        return redirect(url_for('admin.manage_engineers'))

    if new_price_min > new_reference_price:
        flash('Le prix minimum ne peut pas être supérieur au prix de référence.', 'error')
        return redirect(url_for('admin.manage_engineers'))

    # Mettre à jour les prix
    user.mixmaster_price_min = new_price_min
    user.mixmaster_reference_price = new_reference_price

    db.session.commit()

    flash(f' Prix mis à jour pour {user.username}: {new_price_min}€ - {new_reference_price}€ (réf.)', 'success')
    return redirect(url_for('admin.manage_engineers'))


# ============================================
# GESTION DES TOKENS (QUOTAS)
# ============================================

@admin_bp.route('/user/<int:user_id>/add-track-tokens', methods=['POST'])
@login_required
@admin_required
def add_track_tokens(user_id):
    """Ajouter des tokens d'upload de tracks à un utilisateur (promo/événement)"""
    user = db.get_or_404(User, user_id)

    try:
        tokens = int(request.form.get('tokens', 0))
        if tokens <= 0:
            flash('Le nombre de tokens doit être positif.', 'error')
            return redirect(url_for('admin.admin_users'))

        user.upload_track_tokens_promotion(tokens)
        db.session.commit()

        flash(f' {tokens} token(s) d\'upload ajouté(s) à {user.username}. Total: {user.upload_track_tokens} tokens', 'success')
    except ValueError as e:
        flash(f' Erreur: {str(e)}', 'error')
    except Exception as e:
        flash(f' Erreur inattendue: {str(e)}', 'error')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/user/<int:user_id>/add-topline-tokens', methods=['POST'])
@login_required
@admin_required
def add_topline_tokens(user_id):
    """Ajouter des tokens de topline à un utilisateur (promo/événement)"""
    user = db.get_or_404(User, user_id)

    try:
        tokens = int(request.form.get('tokens', 0))
        if tokens <= 0:
            flash('Le nombre de tokens doit être positif.', 'error')
            return redirect(url_for('admin.admin_users'))

        user.topline_tokens_promotion(tokens)
        db.session.commit()

        flash(f' {tokens} token(s) de topline ajouté(s) à {user.username}. Total: {user.topline_tokens} tokens', 'success')
    except ValueError as e:
        flash(f' Erreur: {str(e)}', 'error')
    except Exception as e:
        flash(f' Erreur inattendue: {str(e)}', 'error')

    return redirect(url_for('admin.admin_users'))


@admin_bp.route('/user/<int:user_id>/toggle-premium', methods=['POST'])
@login_required
@admin_required
def toggle_premium(user_id):
    """Activer/Désactiver le statut premium d'un utilisateur"""
    user = db.get_or_404(User, user_id)

    from datetime import datetime, timedelta

    if not user.is_premium:
        # Activer premium pour 30 jours
        user.is_premium = True
        user.premium_since = datetime.now()
        user.premium_expires_at = datetime.now() + timedelta(days=30)
        flash(f' Premium activé pour {user.username} (30 jours)', 'success')
    else:
        # Désactiver premium
        user.is_premium = False
        user.premium_expires_at = datetime.now()
        flash(f' Premium désactivé pour {user.username}', 'warning')

    db.session.commit()
    return redirect(url_for('admin.admin_users'))