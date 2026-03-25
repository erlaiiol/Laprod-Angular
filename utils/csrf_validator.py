# ===================================
# CSRF TOKEN DECORATOR
# ===================================

# NOT in use yet

from functools import wraps
from flask import request, jsonify
from flask_wtf.csrf import validate_csrf
from werkzeug.exceptions import BadRequest

def require_csrf_token_json(f):
    """ POUR LES ROUTES API JSON (header X-CSRF-TOKEN)"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-CSRF-Token')
        if not token:
            return jsonify({'error': 'Token CSRF manquant'}), 403
        try:
            validate_csrf(token)
        except BadRequest:
            return jsonify({'error': 'Token CSRF invalide'}), 403
        return f(*args, **kwargs)
    return wrapper


def require_csrf_token_form(f):
    """ Pour les routes avec FormData (token dans le body)"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Flask-WTF vérifie automatiquement request.form['csrf_token']
        # Il suffit de déclencher la validation
        try:
            validate_csrf(request.form.get('csrf_token'))
        except BadRequest:
            return jsonify({'error': 'Token CSRF invalide'}), 403
        return f(*args, **kwargs)
    return wrapper
