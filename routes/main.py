"""
Blueprint MAIN - Pages publiques
Routes accessibles à tous (avec/sans login)
"""
from flask import Blueprint, redirect, render_template, abort, request, current_app, flash, url_for
from flask_login import current_user, login_required

from extensions import db
from utils import email_service
from models import Track, User, Topline, Tag, Notification
from utils import notification_service
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Page d'accueil avec système de filtrage et pagination"""

    page = request.args.get('page', 1, type=int)
    per_page = 20

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

        # Initialiser les listes
        keys_list = []
        styles_list = []
        tags_list = []

        # Appliquer les filtres
        if search:
            track_query = track_query.where(
                or_(
                    Track.title.ilike(f'%{search}%', escape='\\'),
                    Track.composer_user.has(
                        User.username.ilike(f'%{search}%', escape='\\')
                    )
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
                track_query = (track_query
                            .join(Track.tags)
                            .where(Tag.name.in_(tags_list))
                            .group_by(Track.id)
                            .having(func.count(Tag.id) == len(tags_list))
                            )

        
        track_query = track_query.order_by(Track.created_at.desc())
        # Exécuter avec pagination
        pagination = db.paginate(
            track_query, 
            page=page,
            per_page=per_page,
            error_out=False
        )



        # Préparer les filtres actifs
        active_filters = {
            'search': search,
            'bpm_min': bpm_min,
            'bpm_max': bpm_max,
            'keys': keys_list,
            'styles': styles_list,
            'tags': tags_list
        }

        return render_template(
            "index.html",
            tracks=pagination.items,
            active_filters=active_filters,
            pagination=pagination
        )

    except Exception as e:
        current_app.logger.error(f"Erreur page index: {e}", exc_info=True)
        # Fallback: afficher tous les tracks approuvés sans filtre
        fallback_query = (select(Track)
                          .options(selectinload(Track.tags), selectinload(Track.composer_user))
                          .where(Track.is_approved.is_(True))
                          .order_by(Track.created_at.desc()))
        
        pagination = db.paginate(
            fallback_query,
            page=page,
            per_page=per_page,
            error_out=False
        )

        return render_template(
            "index.html",
            tracks=pagination.items,
            active_filters={},
            pagination=pagination
        )


@main_bp.route('/track/<int:track_id>')
def track_detail(track_id):
    """Détail d'un track avec ses toplines"""

    try:
        track = db.get_or_404(Track, track_id)

        # Vérifier permissions pour tracks non approuvés
        if not track.is_approved:
            if not current_user.is_authenticated:
                current_app.logger.warning(f"Tentative acces track non approuve #{track_id} par utilisateur non connecte")
                abort(403)

            if current_user.id != track.composer_id and not current_user.is_admin:
                current_app.logger.warning(f"Tentative acces track non approuve #{track_id} par user #{current_user.id}")
                abort(403)

        # Récupérer les toplines
        toplines = db.session.query(Topline).where(Topline.track_id == track_id).order_by(Topline.created_at.desc()).all()

        return render_template('track.html', track=track, toplines=toplines)

    except Exception as e:
        if '403' in str(e) or '404' in str(e):
            raise  # Re-lever les erreurs HTTP
        current_app.logger.error(f"Erreur affichage track #{track_id}: {e}", exc_info=True)
        abort(500)


@main_bp.route('/profile/<username>')
def profile(username):
    """Profil public d'un compositeur"""

    try:
        user = db.session.query(User).where(User.username == username).first_or_404()

        # Déterminer quels tracks afficher
        if current_user.is_authenticated and (current_user.id == user.id or current_user.is_admin):
            tracks = user.tracks
        else:
            tracks = [t for t in user.tracks if t.is_approved]

        return render_template('profile.html', user=user, tracks=tracks)

    except Exception as e:
        if '404' in str(e):
            raise
        current_app.logger.error(f"Erreur affichage profil {username}: {e}", exc_info=True)
        abort(500)

@main_bp.route('/notifications')
@login_required
def notifications():

    try:
        notifications = (
            db.session.query(Notification).where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
            .order_by(Notification.created_at.desc())
                      .all()
        )

    except Exception as e:
        current_app.logger.error(
            f'Erreur de chargement des notifications {current_user.username}: {e}',
            exc_info=True
        )
        abort(500)
    return render_template('notifications.html', notifications=notifications)

@main_bp.route('/notifications/goto/<int:notif_id>', methods=['GET'])
@login_required
def go_to_notification(notif_id):
    """Marquer une notification comme lue"""

    try:
        notification = db.get_or_404(Notification, notif_id)

        # Vérifier que la notification appartient à l'utilisateur courant
        if notification.user_id != current_user.id:
            current_app.logger.warning(
                f"Tentative d'accès non autorisée à la notification #{notif_id} par l'utilisateur #{current_user.id}"
            )
            abort(403)
        if not notification.is_read:   
            Notification.mark_as_read(notification)
            db.session.commit()
            return redirect(notification.link) if notification.link else redirect(url_for('main.notifications'))

    except Exception as e:
        db.session.rollback()
        if '403' in str(e) or '404' in str(e):
            raise
        current_app.logger.error(
            f"Erreur lors de la mise à jour de la notification #{notif_id}, {notification.title}, {notification.message} pour l'utilisateur #{current_user.id}: {e}",
            exc_info=True
        )

        flash("Une erreur est survenue lors de la mise à jour de la notification.", 'danger')
        return redirect(url_for('main.notifications'))
    
@main_bp.route('/notifications/mark_all_as_read/<int:user_id>', methods=['POST'])
@login_required
def mark_all_notifications_as_read(user_id):
    """Marquer toutes les notifications comme lues pour un utilisateur donné"""

    try:
        if user_id != current_user.id:
            current_app.logger.warning(
                f"Tentative d'accès non autorisée pour marquer toutes les notifications comme lues pour l'utilisateur #{user_id} par l'utilisateur #{current_user.id}"
            )
            abort(403)

        notification_service.mark_all_as_read(user_id)
        db.session.commit()
        flash("Toutes les notifications ont été marquées comme lues.", 'success')
        return redirect(url_for('main.notifications'))

    except Exception as e:
        db.session.rollback()
        if '403' in str(e):
            raise
        current_app.logger.error(
            f"Erreur lors de la mise à jour des notifications pour l'utilisateur #{user_id}: {e}",
            exc_info=True
        )
        flash("Une erreur est survenue lors de la mise à jour des notifications.", 'danger')
        return redirect(url_for('main.notifications'))

# ============================================
# ROUTES LÉGALES
# ============================================

@main_bp.route('/terms')
@main_bp.route('/terms-of-service')
def terms_of_service():
    """Conditions Générales d'Utilisation et de Vente"""
    return render_template('legal/terms_of_service.html')


@main_bp.route('/privacy')
@main_bp.route('/privacy-policy')
def privacy_policy():
    """Politique de confidentialité (RGPD)"""
    return render_template('legal/privacy_policy.html')


@main_bp.route('/legal-notice')
@main_bp.route('/mentions-legales')
def legal_notice():
    """Mentions légales"""
    return render_template('legal/legal_notice.html')


@main_bp.route('/dmca')
def dmca():
    """Procédure DMCA / Signalement de contrefaçon"""
    return render_template('legal/dmca.html')


@main_bp.route('/cookies')
def cookies():
    """Politique de cookies"""
    return render_template('legal/cookies.html')


# ============================================
# PAGE DE CONTACT / SUPPORT
# ============================================

_CONTACT_REASONS = {
    'contract_error':     'Erreur dans la création du contrat',
    'download_error':     'Impossible de télécharger le fichier audio',
    'mixmaster_download': 'Problème lors du téléchargement de mon mix/master',
}

@main_bp.route('/contact', methods=['GET', 'POST'])
@login_required
def contact():
    """Page de contact support"""
    reason_key      = request.args.get('reason', '')
    ref             = request.args.get('ref', '')
    prefill_subject = _CONTACT_REASONS.get(reason_key, '')

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        ref     = request.form.get('ref', '').strip()

        if not subject or not message:
            flash('Veuillez remplir le sujet et le message.', 'danger')
            return render_template('contact.html', prefill_subject=subject, ref=ref)

        sent = email_service.send_contact_support_email(
            user=current_user,
            subject=subject,
            message=message,
            ref=ref
        )

        if sent:
            flash('Votre message a été envoyé. Vous recevrez une confirmation par email.', 'success')
            return redirect(url_for('main.contact'))
        else:
            flash(
                'Une erreur est survenue lors de l\'envoi. '
                'Réessayez ou écrivez directement à contact@laprod.net.',
                'danger'
            )
            return render_template('contact.html', prefill_subject=subject, ref=ref)

    return render_template('contact.html', prefill_subject=prefill_subject, ref=ref)
