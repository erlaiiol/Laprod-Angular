"""
Blueprint Authentication - Login, Register, Logout, Google OAuth
"""
import json
import re
import uuid
import time
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from email_validator import validate_email, EmailNotValidError
import os
from datetime import datetime
from pathlib import Path
import config
from utils.file_validator import validate_image_file
from sqlalchemy import select, or_

from extensions import db, limiter, oauth, csrf, redis_client
from models import User, PriceChangeRequest
from helpers import sanitize_html, store_refresh_token, is_refresh_token_valid, revoke_all_refresh_tokens
from utils import email_service, notification_service

from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
    jwt_required,
    get_jwt_identity,
    get_jwt
)

# ── Stockage temporaire des codes OAuth (60 s) ───────────────────────────────
# En production, remplacer par Redis.
_oauth_pending: dict = {}  # { code: { expires_at, tokens, user, next } }

def _store_oauth_code(payload: dict) -> str:
    code = str(uuid.uuid4())
    redis_client.setex(
        f"oauth:{code}",
        60,
        json.dumps(payload)
    )

    return code

def _pop_oauth_code(code: str) -> dict | None:
    key = f"oauth:{code}"

    data = redis_client.get(key)

    if not data:
        return None

    redis_client.delete(key)

    return json.loads(data)

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

auth_api_bp = Blueprint('auth_api', __name__, url_prefix='/auth')


@auth_api_bp.route('/ping', methods=['GET'])
@csrf.exempt
@limiter.exempt
def ping():
    """Healthcheck Docker — retourne 200 si l'app est démarrée."""
    return jsonify({'status': 'ok'}), 200


@auth_api_bp.route('/login', methods=['POST'])
@limiter.limit('5 per minute')
@csrf.exempt
def login():

    data = request.get_json()

    if not data:
        current_app.logger.debug("Pas d'informations dans JSON créé à login()")
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Les champs n\'ont pas été remplis'
            }
        }), 400

    identifier = data.get('identifier')
    password = data.get('password')
    remember = data.get('remember', False)

    if not identifier or not password:
        return jsonify({
            'success': False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Identifiant ou mot de passe requis'
            }
        }), 400

    if len(password) > 200:
        return jsonify({
            'success': False, 
            'feedback': {
                'level' : 'warning',
                'message' : 'Identifiants incorrects'
            }
        }), 401

    user = db.session.query(User).filter(
        or_(User.username == identifier, User.email == identifier)).first()

    if user:
        valid = user.check_password(password)
    else :
        valid = False

    if not valid:

        # Cas OAuth sans password
        if user and user.oauth_provider and not user.password_hash:
            current_app.logger.debug('Utilisateur OAuth sans mot de passe')
            return jsonify({
                'success': False,
                'code': 'SHOW_PASSWORD_SET_LINK',
                'feedback': {
                    'level': 'info',
                    'message': 'Cet email utilise Google. Ajouter un mot de passe ?'
                },
                'data': {
                    'password_email': user.email
                }
            }), 400

        # Mauvais identifiants
        return jsonify({
            'success': False,
            'feedback': {
                'level': 'warning',
                'message': 'Identifiants incorrects.'
            }
        }), 401


    if user.account_status != 'active':
        current_app.logger.debug('utilisateur supprimé ou désactivé')
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'error',
                'message' : 'compte désactivé ou suspendu.'
            }
        }), 403

    if not user.email_verified:
        current_app.logger.debug('Utilisateur non vérifié par email')
        return jsonify({
            'success' : False,
            'code' : 'SHOW_EMAIL_CONFIRMATION_LINK',
            'feedback' : {
                'level' : 'warning',
                'message' : 'veuillez vérifier votre email avant de vous connecter. Renvoyer le mail de confirmation ?'
            }, 

            'data' : {
                'confirmation_email' : user.email
            }
        }), 403

        
    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    decoded = decode_token(refresh_token)
    jti = decoded['jti']
    exp = decoded['exp']
    ttl = int(exp - time.time())
    store_refresh_token(user.id, jti, ttl)

    if not user.user_type_selected:
        current_app.logger.debug("l'utilisateur doit choisir un rôle")
        return jsonify({
            'success' : True,
            'code' : 'SHOW_SELECT_ROLE',
            'feedback' : {
                'level' : 'info',
                'message' : 'Choisissez votre rôle (modifiable à tout moment dans votre profil)'
            },
            'data' : {
                'tokens' : {
                    'access_token' : access_token,
                    'refresh_token' : refresh_token
                },
                'user' : {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'profile_image': user.profile_image,
                    'roles' : {
                        'is_admin': user.is_admin,
                        'is_beatmaker': user.is_beatmaker,
                        'is_mix_engineer': user.is_mix_engineer,
                        'is_artist': user.is_artist,
                    },
                    'user_type_selected': user.user_type_selected,
                    'email_verified': user.email_verified,
                    'notif_count' : notification_service.get_unread_count(user.id)
                }
            }
        }), 200

    current_app.logger.debug('Utilisateur entièrement connecté avec succès')
    return jsonify({
        'success' : True,
        'feedback' : {
            'level' : 'info',
            'message' : f'Bienvenue {user.username} !'
        },
        'data' : {
            'tokens' : {
                'access_token' : access_token,
                'refresh_token' : refresh_token
            },
            'user' : {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'profile_image': user.profile_image,
                'roles' : {
                    'is_admin': user.is_admin,
                    'is_beatmaker': user.is_beatmaker,
                    'is_mix_engineer': user.is_mix_engineer,
                    'is_artist': user.is_artist,
                },
                'user_type_selected': user.user_type_selected,
                'email_verified': user.email_verified,
                'notif_count' : notification_service.get_unread_count(user.id)
            }
        }
    }), 200


@auth_api_bp.route('/me', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_identity():

    try:
        user_id = int(get_jwt_identity())
        user = db.get_or_404(User, user_id)

        return jsonify({
            'success' : True,
            'data' : {
                'user' : {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'profile_image': user.profile_image,
                    'roles' : {
                        'is_admin': user.is_admin,
                        'is_beatmaker': user.is_beatmaker,
                        'is_mix_engineer': user.is_mix_engineer,
                        'is_artist': user.is_artist,
                    },
                    'user_type_selected': user.user_type_selected,
                    'email_verified': user.email_verified,
                    'notif_count' : notification_service.get_unread_count(user.id)
                }
            }
        }), 200

    except Exception as e:
        current_app.logger.warning(f'get_identity() n`est pas parvenu à identifier l`utilisateur {e}')
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'error',
                'message' : 'Session expirée. Déconnecté.'
            }
        }), 500


@auth_api_bp.route('/logout', methods=['POST'])
@jwt_required(optional=True)
@csrf.exempt
def logout():

    from models import TokenBlocklist

    jwt_data = get_jwt()
    jti      = jwt_data.get('jti') if jwt_data else None
    user_id  = get_jwt_identity()

    if jti and user_id:
        try:
            # Blocklist l'access token courant
            entry = TokenBlocklist(jti=jti, created_at=datetime.utcnow())
            db.session.add(entry)
            db.session.commit()
            # Révoquer tous les refresh tokens Redis
            revoke_all_refresh_tokens(int(user_id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Erreur blocklist logout user #{user_id} : {e}')

    if user_id:
        current_app.logger.debug(f'Déconnexion utilisateur #{user_id}')

    return jsonify({
        'success' : True,
        'feedback' : {
            'level' : 'info',
            'message' : 'déconnecté avec succès.'
        }
    }), 200


@auth_api_bp.route('/register', methods=['POST'])
def register_user():

    data = request.get_json()

    if not data:
        current_app.logger.debug("Pas d'information dans le json register_user()")
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'les champs n`ont pas été correctement remplis.'
            }
        }), 400

    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    password_confirm = data.get('password_confirm')
    signature = data.get('signature')

    if not all([username, email, password, password_confirm]):
        return jsonify({
            'success': False, 
            'feedback' : {
                'level' : 'warning',
                'message': 'Tous les champs sont requis.'}
            }), 400

    if len(password) > 200:
        return jsonify({
            'success': False, 
            'feedback' : {
                'level' : 'warning',
                'message': 'Mot de passe trop long.'
                }
            }), 400

    checks = [
        re.search(r"[a-z]", password),
        re.search(r"[A-Z]", password),
        re.search(r"[0-9]", password),
    ]

    try:
        email = validate_email(email).email
    except EmailNotValidError as e:
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'email invalide.'
            }
        }), 400

    # Validations
    if len(username) < 3 or len(username) > 20:
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' :'nom d`utilisateur trop court ou trop long (entre 3 et 20 caractères).'
            }
        }), 400

    if not re.match(r'^[\w]+$', username):
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Lettres, chiffres et _ uniquement.'
            }
        }), 400

    if len(password) < 9:
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Mot de passe trop court. 9 caractères minimum.'
            }
        }), 400

    if not password == password_confirm:
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Les mots de passe ne correspondent pas.'
            }
        }), 400

    if not all(checks):
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Mot de passe non conforme. Il doit contenir au moins une minuscule, une majuscule et un chiffre.'
            }
            
        }), 400

    # Validation CGU
    accept_terms = data.get('accept_terms')
    if not accept_terms:
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'Veuillez accepter les termes et conditions.'
            }
        }), 400

    # Validation de la signature
    if not signature or len(signature.strip()) == 0:
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'une signature est nécessaire.'
            }
        }), 400

    if db.session.query(User).filter_by(username=username).first():
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'nom d\'utilisateur déjà pris ou invalide.'
            }
        }), 400

    if db.session.query(User).filter_by(email=email).first():
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'warning',
                'message' : 'email déjà utilisé.'
            }
        }), 400

    new_user = User(
        username=username,
        email=email,
        signature=sanitize_html(signature.strip()),
        terms_accepted_at=datetime.now()
    )

    new_user.set_password(password)

    try:
        db.session.add(new_user)
        db.session.commit()

        if not email_service.send_verification_email(new_user):
            current_app.logger.error(f"Échec envoi email vérification pour user #{new_user.id}, {new_user.email}")
            return jsonify({
                'success' : False,
                'feedback' : {
                    'level' : 'error',
                    'message' : 'Erreur lors de l\'envoi de l\'email de vérification. Contactez le support.'
                },
                'code' : 'SEND_CONFIRM_EMAIL_MESSAGE'
            }), 500

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur création utilisateur : {e}", exc_info=True)
        return jsonify({
            'success' : False,
            'feedback' : {
                'level' : 'error',
                'message' : 'Erreur à la création de l`utilisateur'
            },
        }), 500

    return jsonify({
        'success' : True,
        'feedback' : {
            'level' : 'info',
            'message' : f'Veuillez confirmez votre adresse mail avant de vous connecter. {new_user.username}.  Vérifiez vos spams dans votre boîte mail: {new_user.email}'
        },
        'code' : 'SHOW_CONFIRM_EMAIL_MESSAGE',
        'data' : {
            'user' : {
                'username' : new_user.username,
                'email' : new_user.email
            }
        }
    }), 200


# ═══════════════════════════════════════════════════════════════════════════════
# SÉLECTION DU RÔLE
# ═══════════════════════════════════════════════════════════════════════════════

@auth_api_bp.route('/select-role', methods=['POST'])
@jwt_required()
@csrf.exempt
def select_role():
    """
    Sélection du/des rôle(s) utilisateur (obligatoire après inscription).
    Body JSON : { is_artist, is_beatmaker, is_mix_engineer }
    """
    user_id = int(get_jwt_identity())
    user    = db.get_or_404(User, user_id)

    data            = request.get_json() or {}
    is_artist       = bool(data.get('is_artist',       False))
    is_beatmaker    = bool(data.get('is_beatmaker',    False))
    is_mix_engineer = bool(data.get('is_mix_engineer', False))

    if not (is_artist or is_beatmaker or is_mix_engineer):
        return jsonify({
            'success':  False,
            'feedback': {'level': 'warning',
                         'message': 'Vous devez sélectionner au moins un rôle.'},
        }), 400

    try:
        user.is_artist          = is_artist
        user.is_beatmaker       = is_beatmaker
        user.is_mix_engineer    = is_mix_engineer
        user.user_type_selected = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'select_role error: {e}', exc_info=True)
        return jsonify({
            'success':  False,
            'feedback': {'level': 'error', 'message': 'Erreur serveur.'},
        }), 500

    # Mix/master → page de soumission d'échantillon ; sinon → accueil
    next_page = 'submit-sample' if is_mix_engineer else '/'

    return jsonify({
        'success':  True,
        'feedback': {'level': 'info', 'message': 'Profil mis à jour avec succès !'},
        'data': {
            'user': _user_payload(user),
            'next': next_page,
        },
    }), 200


# ═══════════════════════════════════════════════════════════════════════════════
# GOOGLE OAUTH
# ═══════════════════════════════════════════════════════════════════════════════

def _user_payload(user):
    """Sérialise un User en dict pour la réponse JWT."""
    
    current_app.logger.debug(f'_user_payload() called {user}')

    return {
        'id':                user.id,
        'username':          user.username,
        'email':             user.email,
        'profile_image':     user.profile_image,
        'roles': {
            'is_admin':        user.is_admin,
            'is_beatmaker':    user.is_beatmaker,
            'is_mix_engineer': user.is_mix_engineer,
            'is_artist':       user.is_artist,
        },
        'user_type_selected': user.user_type_selected,
        'email_verified':     user.email_verified,
        'notif_count':        0,
    }


@auth_api_bp.route('/submit-mixmaster-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
def submit_mixmaster_sample():
    """Soumet un échantillon audio pour la certification Mix/Master Engineer."""
    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)

    if not user or not user.is_mix_engineer:
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Rôle Mix/Master Engineer requis.'}}), 403

    # ── Tarifs ──────────────────────────────────────────────────────────────
    try:
        reference_price = float(request.form.get('reference_price', 0))
        if not (10 <= reference_price <= 500):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Prix de référence invalide (10€–500€).'}}), 422

    try:
        price_min = float(request.form.get('price_min', 0))
        min_required   = round(reference_price * 0.35, 2)
        max_allowed    = round(reference_price * 0.65, 2)
        if price_min < min_required or price_min > max_allowed:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': f'Prix minimum invalide (35%–65% du prix de référence).'}}), 422

    # ── Bio ─────────────────────────────────────────────────────────────────
    bio = (request.form.get('bio') or '').strip()
    if not bio:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'La bio est requise.'}}), 422

    # ── Fichiers ─────────────────────────────────────────────────────────────
    raw_file       = request.files.get('sample_raw')
    processed_file = request.files.get('sample_processed')

    if not raw_file or not processed_file or \
       raw_file.filename == '' or processed_file.filename == '':
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Les deux fichiers audio sont requis.'}}), 422

    allowed_ext = {'wav', 'mp3'}

    def _allowed(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_ext

    if not _allowed(raw_file.filename) or not _allowed(processed_file.filename):
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Format non autorisé (.wav ou .mp3 uniquement).'}}), 422

    MAX_SIZE = 50 * 1024 * 1024

    def _check_size(f):
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        return size <= MAX_SIZE

    if not _check_size(raw_file) or not _check_size(processed_file):
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Fichier trop volumineux (max 50 MB).'}}), 422

    # ── Sauvegarde ───────────────────────────────────────────────────────────
    try:
        config.MIXMASTER_SAMPLES_FOLDER.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        raw_name  = f"{user_id}_{ts}_raw_{secure_filename(raw_file.filename)}"
        proc_name = f"{user_id}_{ts}_processed_{secure_filename(processed_file.filename)}"

        raw_file.save(config.MIXMASTER_SAMPLES_FOLDER / raw_name)
        processed_file.save(config.MIXMASTER_SAMPLES_FOLDER / proc_name)

        raw_path  = Path('static', 'mixmaster', 'samples', raw_name).as_posix()
        proc_path = Path('static', 'mixmaster', 'samples', proc_name).as_posix()

        user.mixmaster_reference_price   = reference_price
        user.mixmaster_price_min         = price_min
        user.mixmaster_bio               = bio
        user.mixmaster_sample_raw        = raw_path
        user.mixmaster_sample_processed  = proc_path
        user.mixmaster_sample_submitted  = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'submit_mixmaster_sample error: {e}', exc_info=True)
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    current_app.logger.info(f'Mixmaster sample submitted by user #{user_id}')
    return jsonify({
        'success': True,
        'feedback': {'level': 'info',
                     'message': 'Candidature soumise ! Notre équipe évaluera votre travail.'},
    }), 200


@auth_api_bp.route('/google/login')
@csrf.exempt
def google_login():
    """Démarre le flux OAuth Google — redirige le navigateur vers Google."""
    
    
    current_app.logger.debug('google_login() called. User should see Google interface.')
    
    redirect_uri = url_for('auth_api.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_api_bp.route('/google/callback')
@csrf.exempt
def google_callback():
    """
    Callback Google OAuth.
    Crée / retrouve l'utilisateur, génère un code court-durée et redirige
    vers la SPA Angular qui l'échangera contre les JWT.
    """
    angular_base = current_app.config.get('ANGULAR_BASE_URL', 'http://localhost:4200')

    current_app.logger.debug('google_callback() called')

    try:
        token      = oauth.google.authorize_access_token()
        resp       = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info  = resp.json()

        google_id      = user_info.get('sub')
        email          = user_info.get('email')
        given_name     = user_info.get('given_name', '')
        picture        = user_info.get('picture')
        email_verified = user_info.get('email_verified', False)

        # ── CAS 1 : google_id connu ──────────────────────────────────────────
        user = db.session.query(User).filter_by(google_id=google_id).first()

        if user:
            if picture and getattr(user, 'profile_picture_url', None) != picture:
                user.profile_picture_url = picture
                db.session.commit()

            if user.account_status == 'deleted':
                return redirect(f'{angular_base}/login?error=account_deleted')

            access_token  = create_access_token(identity=str(user.id))
            refresh_token = create_refresh_token(identity=str(user.id))
            decoded = decode_token(refresh_token)
            store_refresh_token(user.id, decoded['jti'], int(decoded['exp'] - time.time()))

            if not user.user_type_selected:
                code = _store_oauth_code({
                    'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
                    'user':   _user_payload(user),
                    'next':   'select-role',
                })
                return redirect(f'{angular_base}/oauth-callback?code={code}')

            code = _store_oauth_code({
                'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
                'user':   _user_payload(user),
                'next':   '/',
            })
            return redirect(f'{angular_base}/oauth-callback?code={code}')

        current_app.logger.debug(f'user: {user}, authorize_access_token ?: {token}, resp ? {resp}.')

        # ── CAS 2 : google_id inconnu ────────────────────────────────────────
        user_by_email = db.session.query(User).filter_by(email=email).first()

        if user_by_email:
            if user_by_email.oauth_provider is None:
                # Lier le compte classique à Google
                user_by_email.google_id           = google_id
                user_by_email.oauth_provider      = 'google'
                user_by_email.profile_picture_url = picture
                user_by_email.email_verified      = user_by_email.email_verified or email_verified
                if user_by_email.email_verified:
                    user_by_email.account_status = 'active'
                db.session.commit()

                access_token  = create_access_token(identity=str(user_by_email.id))
                refresh_token = create_refresh_token(identity=str(user_by_email.id))
                decoded = decode_token(refresh_token)
                store_refresh_token(user_by_email.id, decoded['jti'], int(decoded['exp'] - time.time()))

                next_page = 'select-role' if not user_by_email.user_type_selected else '/'
                code = _store_oauth_code({
                    'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
                    'user':   _user_payload(user_by_email),
                    'next':   next_page,
                })
                return redirect(f'{angular_base}/oauth-callback?code={code}')

            # Déjà lié à un autre OAuth
            return redirect(f'{angular_base}/login?error=oauth_conflict')

        # ── CAS 3 : nouvel utilisateur ───────────────────────────────────────
        new_user = User(
            email                = email,
            username             = None,
            google_id            = google_id,
            oauth_provider       = 'google',
            profile_picture_url  = picture,
            email_verified       = email_verified,
            account_status       = 'pending_completion',
        )
        db.session.add(new_user)
        db.session.commit()
        db.session.refresh(new_user)

        # Token temporaire (scope limité — seulement pour compléter le profil)
        access_token  = create_access_token(identity=str(new_user.id),
                                            additional_claims={'oauth_incomplete': True})
        refresh_token = create_refresh_token(identity=str(new_user.id))
        decoded = decode_token(refresh_token)
        store_refresh_token(new_user.id, decoded['jti'], int(decoded['exp'] - time.time()))

        safe_name = re.sub(r"[^\w\s\-']", '', given_name.strip())[:100] if given_name else ''

        code = _store_oauth_code({
            'tokens':           {'access_token': access_token, 'refresh_token': refresh_token},
            'user':             _user_payload(new_user),
            'next':             'complete-profile',
            'suggested_name':   safe_name,
        })
        return redirect(f'{angular_base}/oauth-callback?code={code}')

    except Exception as e:
        current_app.logger.error(f'Erreur OAuth Google: {type(e).__name__}: {e}', exc_info=True)
        return redirect(f'{angular_base}/login?error=oauth_failed')


@auth_api_bp.route('/token-exchange', methods=['GET'])
@csrf.exempt
def token_exchange():
    """
    Échange un code OAuth court-durée contre les tokens JWT.
    GET /auth/token-exchange?code=XXX
    """
    code  = request.args.get('code', '')
    entry = _pop_oauth_code(code)

    current_app.logger.debug(f'token_exchange() called code: {code}, entry: {entry}')

    if not entry:
        return jsonify({
            'success':  False,
            'feedback': {'level': 'error', 'message': 'Code invalide ou expiré.'},
        }), 400

    return jsonify({
        'success':  True,
        'data': {
            'tokens':         entry['tokens'],
            'user':           entry['user'],
            'next':           entry.get('next', '/'),
            'suggested_name': entry.get('suggested_name', ''),
        },
    }), 200


@auth_api_bp.route('/refresh', methods=['POST'])
@csrf.exempt
@jwt_required(refresh=True)
def jwt_token_refresh():
    user_id = int(get_jwt_identity())


    jwt_data = get_jwt()
    jti = jwt_data['jti']

    if not is_refresh_token_valid(user_id, jti):
        current_app.logger.warning(f"Token refresh rejeté pour l'utilisateur #{user_id} (jti: {jti})")
        return jsonify({
            'success': False,
            'feedback': {
                'level': 'error',
                'message': 'Refresh token invalide ou expiré. Veuillez vous reconnecter.'
            },
        }), 401

    user = db.get_or_404(User, user_id)
    current_app.logger.debug(f'refreshing via jwt_token_refresh() for {user}')

    access_token = create_access_token(identity=str(user.id))

    return jsonify({
        'success': True,
        'data': {
            'access_token': access_token
        }
    }), 200

@auth_api_bp.route('/complete-oauth-profile', methods=['POST'])
@jwt_required()
@csrf.exempt
def complete_oauth_profile():
    """
    Finalise le profil d'un utilisateur créé via Google OAuth.
    Appelé une seule fois par les nouveaux comptes Google (account_status = pending_completion).
    Body JSON : { username, signature, accept_terms }
    """

    user_id = int(get_jwt_identity())
    user    = db.get_or_404(User, user_id)

    current_app.logger.debug(f'complete_oauth_profile() called {user}')

    if user.account_status != 'pending_completion':
        return jsonify({
            'success':  False,
            'feedback': {'level': 'warning', 'message': 'Profil déjà complété.'},
        }), 400

    data = request.get_json() or {}
    username     = (data.get('username') or '').strip()
    signature    = (data.get('signature') or '').strip()
    accept_terms = data.get('accept_terms', False)

    if not username or len(username) < 3 or len(username) > 20:
        return jsonify({'success': False,
                        'feedback': {'level': 'warning',
                                     'message': 'Nom d\'utilisateur : 3-20 caractères.'}}), 400

    if not re.match(r'^[\w]+$', username):
        return jsonify({'success': False,
                        'feedback': {'level': 'warning',
                                     'message': 'Lettres, chiffres et _ uniquement.'}}), 400

    if not signature or len(signature) < 3:
        return jsonify({'success': False,
                        'feedback': {'level': 'warning',
                                     'message': 'Signature légale requise (min. 3 caractères).'}}), 400

    if not accept_terms:
        return jsonify({'success': False,
                        'feedback': {'level': 'warning',
                                     'message': 'Veuillez accepter les conditions d\'utilisation.'}}), 400

    if db.session.query(User).filter(User.username == username, User.id != user_id).first():
        return jsonify({'success': False,
                        'feedback': {'level': 'warning',
                                     'message': 'Nom d\'utilisateur déjà pris.'}}), 400

    try:
        user.username          = username
        user.signature         = sanitize_html(signature)
        user.terms_accepted_at = datetime.now()
        user.account_status    = 'active'
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'complete_oauth_profile error: {e}', exc_info=True)
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    # Émettre de nouveaux tokens sans le claim `oauth_incomplete`
    access_token  = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    decoded = decode_token(refresh_token)
    store_refresh_token(user.id, decoded['jti'], int(decoded['exp'] - time.time()))

    return jsonify({
        'success':  True,
        'feedback': {'level': 'info', 'message': f'Bienvenue {user.username} !'},
        'data': {
            'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
            'user':   _user_payload(user),
            'next':   'select-role' if not user.user_type_selected else '/',
        },
    }), 200
