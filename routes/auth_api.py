"""
Blueprint Authentication - Login, Register, Logout
"""
import re
import uuid
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

from extensions import db, limiter, oauth, csrf
from models import User, PriceChangeRequest
from helpers import sanitize_html
from utils import email_service, notification_service

from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt
)

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

auth_api_bp = Blueprint('auth_api', __name__, url_prefix='/auth')


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
                    'notif_count' : get_unread_count(user.id)
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
@jwt_required()
@csrf.exempt
def logout():

    from models import TokenBlocklist

    jti     = get_jwt()['jti']
    user_id = int(get_jwt_identity())

    try:
        db.session.add(TokenBlocklist(jti=jti))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Erreur blocklist logout user #{user_id} : {e}')
        return jsonify({'success': False, 'error': 'Erreur lors de la déconnexion.'}), 500

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
