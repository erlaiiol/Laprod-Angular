"""
Mixmaster API — GET endpoints (public + JWT)
Ingénieurs certifiés, détail commande, historique artiste
"""
from flask import Blueprint, jsonify, url_for
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import select
from extensions import db, csrf
from models import User, MixMasterRequest

mixmaster_api_bp = Blueprint('mixmaster_api', __name__, url_prefix='/mixmaster-api')


def _engineer_dict(eng: User) -> dict:
    ref = eng.mixmaster_reference_price or 0
    if ref and eng.is_certified_producer_arranger:
        price_max = round(ref * 1.80, 2)
    elif ref:
        price_max = round(ref * 1.20, 2)
    else:
        price_max = 0

    return {
        'id':                        eng.id,
        'username':                  eng.username,
        'profile_image':             eng.profile_image,
        'bio':                       eng.mixmaster_bio,
        'reference_price':           eng.mixmaster_reference_price,
        'price_min':                 eng.mixmaster_price_min,
        'price_max':                 price_max,
        'is_certified_producer_arranger': eng.is_certified_producer_arranger,
        'sample_raw_url':            url_for('audio.serve_engineer_sample', user_id=eng.id, sample_type='raw', _external=False) if eng.mixmaster_sample_raw else None,
        'sample_processed_url':      url_for('audio.serve_engineer_sample', user_id=eng.id, sample_type='processed', _external=False) if eng.mixmaster_sample_processed else None,
        'stripe_ready':              bool(eng.stripe_onboarding_complete and eng.mixmaster_reference_price and eng.mixmaster_price_min),
        'active_orders':             MixMasterRequest.get_active_requests_count(eng.id),
        'slots_available':           max(0, 5 - MixMasterRequest.get_active_requests_count(eng.id)),
    }


def _order_dict_full(o: MixMasterRequest, perspective: str = 'artist') -> dict:
    """Sérialise un MixMasterRequest avec tous les champs nécessaires pour les actions."""
    can_rev, _ = o.can_request_revision()
    return {
        'id':                    o.id,
        'title':                 o.title,
        'status':                o.status,
        'stripe_payment_status': o.stripe_payment_status,
        'total_price':           o.total_price,
        'deposit_amount':        o.deposit_amount,
        'remaining_amount':      o.remaining_amount,
        'engineer_revenue':      o.engineer_revenue,
        'revision_count':        o.revision_count,
        'revision1_message':     o.revision1_message,
        'revision2_message':     o.revision2_message,
        'can_request_revision':  can_rev,
        'is_expired':            o.is_expired(),
        # Finances
        'total_transferred':     o.get_total_transferred_to_engineer(),
        'final_transfer_amount': o.get_final_transfer_amount(),
        # Artiste
        'artist_id':             o.artist_id,
        'artist_username':       o.artist.username if o.artist else None,
        'artist_image':          o.artist.profile_image if o.artist else None,
        # Ingénieur
        'engineer_id':           o.engineer_id,
        'engineer_username':     o.engineer.username if o.engineer else None,
        'engineer_image':        o.engineer.profile_image if o.engineer else None,
        # Services
        'services': {
            'cleaning':  o.service_cleaning,
            'effects':   o.service_effects,
            'artistic':  o.service_artistic,
            'mastering': o.service_mastering,
        },
        'has_separated_stems': o.has_separated_stems,
        # Briefing
        'artist_message':      o.artist_message,
        'brief_vocals':        o.brief_vocals,
        'brief_backing_vocals': o.brief_backing_vocals,
        'brief_ambiance':      o.brief_ambiance,
        'brief_bass':          o.brief_bass,
        'brief_energy_style':  o.brief_energy_style,
        'brief_references':    o.brief_references,
        'brief_instruments':   o.brief_instruments,
        'brief_percussion':    o.brief_percussion,
        'brief_effects':       o.brief_effects,
        'brief_structure':     o.brief_structure,
        # Fichiers — accès via proxy /static/
        'reference_file_url':           f'/static/{o.reference_file}' if o.reference_file else None,
        'original_file_url':            f'/static/{o.original_file}' if o.original_file else None,
        'processed_file_preview_url':   f'/static/{o.processed_file_preview}' if o.processed_file_preview else None,
        'processed_file_preview_full_url': f'/static/{o.processed_file_preview_full}' if o.processed_file_preview_full else None,
        # Arborescence de l'archive
        'archive_file_tree': o.archive_file_tree or [],
        # Dates
        'created_at':   o.created_at.isoformat() if o.created_at else None,
        'accepted_at':  o.accepted_at.isoformat() if o.accepted_at else None,
        'deadline':     o.deadline.isoformat() if o.deadline else None,
        'delivered_at': o.delivered_at.isoformat() if o.delivered_at else None,
        'completed_at': o.completed_at.isoformat() if o.completed_at else None,
    }


# ─── Ingénieurs certifiés (public) ────────────────────────────────────────────

@mixmaster_api_bp.route('/engineers', methods=['GET'])
@csrf.exempt
def get_engineers():
    """Liste des ingénieurs certifiés (public)."""
    engineers = db.session.scalars(
        select(User).where(User.is_mixmaster_engineer == True).order_by(User.username)
    ).all()
    return jsonify({
        'success': True,
        'data': {'engineers': [_engineer_dict(e) for e in engineers]},
    }), 200


@mixmaster_api_bp.route('/engineers/<int:engineer_id>', methods=['GET'])
@csrf.exempt
def get_engineer(engineer_id):
    """Détail d'un ingénieur (public)."""
    eng = db.get_or_404(User, engineer_id)
    if not eng.is_mixmaster_engineer:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Ingénieur introuvable.'}}), 404
    return jsonify({'success': True, 'data': {'engineer': _engineer_dict(eng)}}), 200


# ─── Demandes de l'artiste (JWT) ──────────────────────────────────────────────

@mixmaster_api_bp.route('/my-requests', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_my_requests():
    """Demandes de mix/master de l'artiste connecté."""
    user_id = int(get_jwt_identity())
    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.artist_id == user_id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()
    return jsonify({
        'success': True,
        'data': {'requests': [_order_dict_full(o, 'artist') for o in orders]},
    }), 200


# ─── Commandes de l'ingénieur (JWT) ───────────────────────────────────────────

@mixmaster_api_bp.route('/my-orders', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_my_orders():
    """Commandes de mix/master reçues par l'ingénieur connecté."""
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)
    if not user.is_mix_engineer:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé.'}}), 403

    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.engineer_id == user_id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()
    return jsonify({
        'success': True,
        'data': {'orders': [_order_dict_full(o, 'engineer') for o in orders]},
    }), 200


# ─── Détail d'une commande (JWT — artiste ou ingénieur) ───────────────────────

@mixmaster_api_bp.route('/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_order(order_id):
    """Détail complet d'une commande (artiste ou ingénieur concerné)."""
    user_id = int(get_jwt_identity())
    order = db.get_or_404(MixMasterRequest, order_id)
    if order.artist_id != user_id and order.engineer_id != user_id:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé.'}}), 403
    return jsonify({'success': True, 'data': {'order': _order_dict_full(order)}}), 200
