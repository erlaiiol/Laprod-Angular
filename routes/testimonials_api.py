"""
Testimonials API — Feature flag DEV only (TESTIMONIALS_ENABLED env var)
"""
import os
from flask import Blueprint, request, current_app
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from extensions import db, csrf, limiter
from models import TestimonialRequest, User
from serializers import ok, err
from sqlalchemy import select

testimonials_api_bp = Blueprint('testimonials_api', __name__, url_prefix='/api/testimonials')

_ENABLED = os.environ.get('TESTIMONIALS_ENABLED', 'false').lower() == 'true'


def _check_enabled():
    if not _ENABLED:
        return err('Page non disponible.', status=404)
    return None


@testimonials_api_bp.route('/published', methods=['GET'])
@csrf.exempt
def get_published_testimonials():
    blocked = _check_enabled()
    if blocked:
        return blocked

    rows = db.session.scalars(
        select(TestimonialRequest)
        .where(TestimonialRequest.is_published == True)
        .order_by(TestimonialRequest.created_at.desc())
        .limit(20)
    ).all()

    data = [
        {
            'id':         r.id,
            'email':      r.email[:3] + '***' + r.email[r.email.index('@'):] if '@' in r.email else '***',
            'role':       r.role,
            'message':    r.message,
            'rating':     r.rating,
            'created_at': r.created_at.isoformat() if r.created_at else None,
            'username':   r.user.username if r.user else None,
        }
        for r in rows
    ]
    return ok(data)


@testimonials_api_bp.route('/submit', methods=['POST'])
@csrf.exempt
@limiter.limit('3 per day')
def submit_testimonial():
    blocked = _check_enabled()
    if blocked:
        return blocked

    # JWT optional — enrichit avec user si connecté
    user_id = None
    email_default = None
    try:
        verify_jwt_in_request(optional=True)
        uid = get_jwt_identity()
        if uid:
            u = db.session.get(User, int(uid))
            if u:
                user_id = u.id
                email_default = u.email
    except Exception:
        pass

    body = request.get_json(silent=True) or {}
    email   = body.get('email', email_default or '').strip()
    message = body.get('message', '').strip()
    role    = body.get('role', '').strip() or None
    rating  = body.get('rating')

    if not email or not message:
        return err('Email et message requis.', status=400)
    if len(message) < 20:
        return err('Message trop court (20 caractères minimum).', status=400)
    if rating is not None and rating not in (1, 2, 3, 4, 5):
        return err('Note invalide.', status=400)

    tr = TestimonialRequest(
        user_id=user_id,
        email=email,
        role=role,
        message=message,
        rating=int(rating) if rating else None,
        is_verified=False,
        is_published=False,
    )
    db.session.add(tr)
    db.session.commit()

    return ok({'id': tr.id}, status=201)
