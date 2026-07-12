"""
Blueprint Authentication - Login, Register, Logout, Google OAuth
"""
import re
import time
from flask import Blueprint, request, redirect, url_for, current_app, jsonify
# NOTE: jsonify kept for /ping healthcheck (non-standard shape)
from werkzeug.utils import secure_filename
from email_validator import validate_email, EmailNotValidError
import os
from datetime import datetime, timedelta
from pathlib import Path
import config
from utils.file_validator import validate_image_file
from sqlalchemy import select, or_

from extensions import db, limiter, oauth, csrf
import extensions as _ext
from models import User, PriceChangeRequest
from helpers import sanitize_html, store_refresh_token, is_refresh_token_valid, revoke_all_refresh_tokens
from utils import email_service, notification_service
from serializers import ok, err, user_auth
from utils.auth_helpers import require_user
from utils.crud_helpers import commit_or_rollback

from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
    jwt_required,
    get_jwt_identity,
    get_jwt
)

# ── Stockage temporaire des codes OAuth (300 s) ───────────────────────────────
# En production, remplacer par Redis.
_oauth_pending: dict = {}  # { code: { expires_at, tokens, user, next } }

def _get_redis():
    """
    Crée une connexion Redis fraîche à chaque appel.
    Contourne les problèmes de pool hérité après fork (gunicorn --preload).
    """
    import redis as _redis_module
    from flask import current_app
    return _redis_module.Redis(
        host=current_app.config['REDIS_HOST'],
        port=current_app.config['REDIS_PORT'],
        db=current_app.config['REDIS_DB'],
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

def _store_oauth_code(payload: dict) -> str:
    """
    Encode le payload OAuth dans un token itsdangerous signé + horodaté.
    Stateless — pas de Redis, fonctionne avec tous les workers gunicorn.
    """
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    token = s.dumps(payload, salt='oauth-code-2026')
    current_app.logger.info(f"[OAuth] code token généré (len={len(token)})")
    return token

def _pop_oauth_code(code: str) -> dict | None:
    """
    Vérifie et décode le token OAuth signé (expire après 300 s).
    Retourne le payload ou None si invalide/expiré.
    """
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
    current_app.logger.info(f"[OAuth] décodage token (len={len(code) if code else 0})")
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        payload = s.loads(code, salt='oauth-code-2026', max_age=300)
        current_app.logger.info(f"[OAuth] token OK → next={payload.get('next')}")
        return payload
    except SignatureExpired:
        current_app.logger.warning("[OAuth] token expiré (>300s)")
        return None
    except BadSignature as exc:
        current_app.logger.warning(f"[OAuth] token signature invalide: {exc}")
        return None
    except Exception as exc:
        current_app.logger.error(f"[OAuth] token decode erreur: {exc}", exc_info=True)
        return None

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

auth_api_bp = Blueprint('auth_api', __name__, url_prefix='/api/auth')


@auth_api_bp.route('/ping', methods=['GET'])
@csrf.exempt
@limiter.exempt
def ping():
    """Healthcheck Docker — retourne 200 si l'app est démarrée. Teste aussi Redis."""
    redis_ok = False
    redis_error = None
    try:
        r = _get_redis()
        r.ping()
        redis_ok = True
    except Exception as exc:
        redis_error = str(exc)
    return jsonify({'status': 'ok', 'redis': redis_ok, 'redis_error': redis_error}), 200


@auth_api_bp.route('/login', methods=['POST'])
@limiter.limit('10 per minute;60 per hour')
@csrf.exempt
def login():

    data = request.get_json()

    if not data:
        current_app.logger.debug("Pas d'informations dans JSON créé à login()")
        return err("Les champs n'ont pas été remplis", level='warning')

    identifier = data.get('identifier')
    password = data.get('password')
    remember = data.get('remember', False)

    if not identifier or not password:
        return err('Identifiant ou mot de passe requis', level='warning')

    # Borne alignée sur l'inscription (≤200) : sans ça, un compte dont le mot de
    # passe fait 51–200 caractères ne pourrait jamais se reconnecter.
    if len(password) > 200:
        return err('Identifiants incorrects', level='warning', status=401)

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
            return err('Cet email utilise Google. Ajouter un mot de passe ?', level='info',
                       code='SHOW_PASSWORD_SET_LINK', data={'password_email': user.email})

        # Mauvais identifiants
        return err('Identifiants incorrects.', level='warning', status=401)


    # Email non vérifié — prioritaire sur le statut du compte
    if not user.email_verified:
        current_app.logger.debug('Utilisateur non vérifié par email')
        return err('Veuillez vérifier votre email avant de vous connecter.', level='warning',
                   code='SHOW_EMAIL_CONFIRMATION_LINK', data={'confirmation_email': user.email}, status=403)

    # Compte en cours de suppression RGPD ou déjà supprimé
    if user.account_status == 'pending_deletion':
        return err('Ce compte est en cours de suppression. Contactez le support si vous pensez qu\'il s\'agit d\'une erreur.', status=403)

    # Compte désactivé / banni (jamais pending_completion ici : déjà géré ci-dessus)
    if user.account_status not in ('active', 'pending_completion'):
        current_app.logger.debug('utilisateur supprimé ou désactivé')
        return err('Compte désactivé ou suspendu.', status=403)

        
    access_token  = create_access_token(identity=str(user.id))
    # remember=True → 30 jours ; remember=False → 1 jour (session courte)
    refresh_delta = timedelta(days=30) if remember else timedelta(days=1)
    refresh_token = create_refresh_token(identity=str(user.id), expires_delta=refresh_delta)

    decoded = decode_token(refresh_token)
    jti = decoded['jti']
    exp = decoded['exp']
    ttl = int(exp - time.time())
    store_refresh_token(user.id, jti, ttl)

    if not user.user_type_selected:
        current_app.logger.debug("l'utilisateur doit choisir un rôle")
        return ok({
            'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
            'user': user_auth(user, notif_count=notification_service.get_unread_count(user.id)),
        }, message='Choisissez votre rôle (modifiable à tout moment dans votre profil)',
           level='info', code='SHOW_SELECT_ROLE')

    current_app.logger.debug('Utilisateur entièrement connecté avec succès')
    return ok({
        'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
        'user': user_auth(user, notif_count=notification_service.get_unread_count(user.id)),
    }, message=f'Bienvenue {user.username} !', level='info')


@auth_api_bp.route('/me', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_identity(current_user):
    return ok({'user': user_auth(current_user, notif_count=notification_service.get_unread_count(current_user.id))})


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

    return ok(message='déconnecté avec succès.', level='info')


@auth_api_bp.route('/register', methods=['POST'])
@limiter.limit('25 per hour')
@csrf.exempt
def register_user():

    data = request.get_json()

    if not data:
        current_app.logger.debug("Pas d'information dans le json register_user()")
        return err("les champs n'ont pas été correctement remplis.", level='warning')

    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    password_confirm = data.get('password_confirm')
    signature = data.get('signature')

    if not all([username, email, password, password_confirm]):
        return err('Tous les champs sont requis.', level='warning')

    if len(password) > 200:
        return err('Mot de passe trop long.', level='warning')

    checks = [
        re.search(r"[a-z]", password),
        re.search(r"[A-Z]", password),
        re.search(r"[0-9]", password),
    ]

    try:
        email = validate_email(email).email
    except EmailNotValidError as e:
        return err('email invalide.', level='warning')

    # Validations
    if len(username) < 3 or len(username) > 20:
        return err('nom d`utilisateur trop court ou trop long (entre 3 et 20 caractères).', level='warning')

    if not re.match(r'^[\w]+$', username):
        return err('Lettres, chiffres et _ uniquement.', level='warning')

    if len(password) < 9:
        return err('Mot de passe trop court. 9 caractères minimum.', level='warning')

    if not password == password_confirm:
        return err('Les mots de passe ne correspondent pas.', level='warning')

    if not all(checks):
        return err('Mot de passe non conforme. Il doit contenir au moins une minuscule, une majuscule et un chiffre.', level='warning')

    # Validation CGU
    accept_terms = data.get('accept_terms')
    if not accept_terms:
        return err('Veuillez accepter les termes et conditions.', level='warning')

    # Validation de la signature
    if not signature or len(signature.strip()) == 0:
        return err('une signature est nécessaire.', level='warning')

    if db.session.query(User).filter_by(username=username).first():
        return err("nom d'utilisateur déjà pris ou invalide.", level='warning')

    existing_email_user = db.session.query(User).filter_by(email=email).first()
    if existing_email_user:
        # Compte créé mais email pas encore vérifié → proposer le renvoi
        if existing_email_user.account_status == 'pending_completion' and not existing_email_user.email_verified:
            return err("Un compte avec cet email existe déjà mais n'a pas encore été vérifié.",
                       level='warning', code='PENDING_EMAIL_VERIFICATION', data={'email': email}, status=409)
        return err('email déjà utilisé.', level='warning')

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
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur création utilisateur : {e}", exc_info=True)
        return err('Erreur à la création du compte. Réessayez.', status=500)

    try:
        email_sent = email_service.send_verification_email(new_user)
    except Exception as e:
        email_sent = False
        current_app.logger.error(f"Erreur envoi email vérification user #{new_user.id}: {e}", exc_info=True)

    if not email_sent:
        current_app.logger.error(f"Échec envoi email vérification pour user #{new_user.id}, {new_user.email}")
        return err('Compte créé mais email de vérification non envoyé. Contactez le support.',
                   code='SEND_CONFIRM_EMAIL_MESSAGE', status=500)

    return ok({'user': {'username': new_user.username, 'email': new_user.email}},
              message=f'Veuillez confirmez votre adresse mail avant de vous connecter. {new_user.username}.  Vérifiez vos spams dans votre boîte mail: {new_user.email}',
              level='info', code='SHOW_CONFIRM_EMAIL_MESSAGE')


# ═══════════════════════════════════════════════════════════════════════════════
# VÉRIFICATION EMAIL
# ═══════════════════════════════════════════════════════════════════════════════

@auth_api_bp.route('/verify-email', methods=['POST'])
@csrf.exempt
def verify_email():
    """Vérifie le token d'email et active le compte."""
    data = request.get_json()
    token = data.get('token') if data else None

    if not token:
        return err('Token manquant.')

    email = email_service.verify_email_token(token)
    if not email:
        return err('Lien de vérification invalide ou expiré.', code='TOKEN_EXPIRED')

    user = db.session.query(User).filter_by(email=email).first()
    if not user:
        return err('Compte introuvable.', status=404)

    if user.email_verified:
        return ok(message='Email déjà vérifié. Vous pouvez vous connecter.', level='info', code='ALREADY_VERIFIED')

    user.email_verified = True
    if user.account_status == 'pending_completion':
        user.account_status = 'active'
    db.session.commit()

    return ok(message='Email vérifié ! Vous pouvez maintenant vous connecter.')


@auth_api_bp.route('/resend-verification', methods=['POST'])
@csrf.exempt
@limiter.limit('25 per hour')
def resend_verification():
    """Renvoie l'email de vérification pour un compte non vérifié.
    Accepte 'identifier' (username ou email) ou 'email' pour la rétrocompatibilité.
    """
    data = request.get_json()
    identifier = (data.get('identifier') or data.get('email')) if data else None

    if not identifier:
        return err('Identifiant requis.')

    user = db.session.query(User).filter(
        or_(User.email == identifier, User.username == identifier)
    ).first()

    # Réponse identique que l'utilisateur existe ou non (évite l'énumération d'emails)
    _ambiguous_msg = 'Si un compte non vérifié existe avec cet email, un nouveau lien a été envoyé.'
    if not user or user.email_verified:
        return ok(message=_ambiguous_msg, level='info')

    try:
        email_sent = email_service.send_verification_email(user)
    except Exception as e:
        email_sent = False
        current_app.logger.error(f"Erreur renvoi email vérification user #{user.id}: {e}", exc_info=True)

    if not email_sent:
        current_app.logger.error(f"Échec renvoi email vérification pour user #{user.id}")
        return err("Erreur lors de l'envoi. Réessayez plus tard.", status=500)

    return ok(message=_ambiguous_msg, level='info')


# ═══════════════════════════════════════════════════════════════════════════════
# SÉLECTION DU RÔLE
# ═══════════════════════════════════════════════════════════════════════════════

@auth_api_bp.route('/select-role', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
@commit_or_rollback
def select_role(current_user):
    """
    Sélection du/des rôle(s) utilisateur (obligatoire après inscription).
    Body JSON : { is_artist, is_beatmaker, is_mix_engineer }
    """
    data            = request.get_json() or {}
    is_artist       = bool(data.get('is_artist',       False))
    is_beatmaker    = bool(data.get('is_beatmaker',    False))
    is_mix_engineer = bool(data.get('is_mix_engineer', False))

    if not (is_artist or is_beatmaker or is_mix_engineer):
        return err('Vous devez sélectionner au moins un rôle.', level='warning')

    first_selection = not current_user.user_type_selected

    current_user.is_artist          = is_artist
    current_user.is_beatmaker       = is_beatmaker
    current_user.is_mix_engineer    = is_mix_engineer
    current_user.user_type_selected = True

    # Notification Stripe Connect à la première sélection de rôle
    if first_selection and (is_beatmaker or is_mix_engineer):
        notification_service.notify_stripe_connect_setup(current_user.id)

    # Notification "preview à soumettre" à la première activation du rôle mix engineer
    if first_selection and is_mix_engineer:
        notification_service.notify_mix_sample_pending(current_user.id)

    db.session.commit()

    if first_selection and is_mix_engineer:
        try:
            email_service.send_mix_sample_pending_email(current_user)
        except Exception as e:
            current_app.logger.error(f"Erreur email mix_sample_pending user #{current_user.id}: {e}")

    # Mix/master → page de soumission d'échantillon ; sinon → accueil
    next_page = 'submit-sample' if is_mix_engineer else '/'

    return ok({'user': _user_payload(current_user), 'next': next_page},
              message='Profil mis à jour avec succès !', level='info')


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
        'profile_image':     user.profile_picture_url or user.profile_image,
        'roles': {
            'is_admin':                       user.is_admin,
            'is_beatmaker':                   user.is_beatmaker,
            'is_mix_engineer':                user.is_mix_engineer,
            'is_artist':                      user.is_artist,
            'is_mixmaster_engineer':          user.is_mixmaster_engineer,
            'is_certified_producer_arranger': user.is_certified_producer_arranger,
            'mixmaster_sample_submitted':     user.mixmaster_sample_submitted,
        },
        'user_type_selected': user.user_type_selected,
        'email_verified':     user.email_verified,
        'notif_count':        0,
    }


@auth_api_bp.route('/submit-mixmaster-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def submit_mixmaster_sample(current_user):
    """Soumet un échantillon audio pour la certification Mix/Master Engineer."""
    if not current_user.is_mix_engineer:
        return err('Rôle Mix/Master Engineer requis.', status=403)

    # ── Tarifs ──────────────────────────────────────────────────────────────
    try:
        reference_price = float(request.form.get('reference_price', 0))
        if not (10 <= reference_price <= 500):
            raise ValueError
    except (ValueError, TypeError):
        return err('Prix de référence invalide (10€–500€).', status=422)

    try:
        price_min = float(request.form.get('price_min', 0))
        min_required   = round(reference_price * 0.35, 2)
        max_allowed    = round(reference_price * 0.80, 2)
        if price_min < min_required or price_min > max_allowed:
            raise ValueError
    except (ValueError, TypeError):
        return err('Prix minimum invalide (35%–80% du prix de référence).', status=422)

    # ── Bio ─────────────────────────────────────────────────────────────────
    bio = (request.form.get('bio') or '').strip()
    if not bio:
        return err('La bio est requise.', status=422)

    # ── Fichiers ─────────────────────────────────────────────────────────────
    raw_file       = request.files.get('sample_raw')
    processed_file = request.files.get('sample_processed')

    if not raw_file or not processed_file or \
       raw_file.filename == '' or processed_file.filename == '':
        return err('Les deux fichiers audio sont requis.', status=422)

    allowed_ext = {'wav', 'mp3'}

    def _allowed(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_ext

    if not _allowed(raw_file.filename) or not _allowed(processed_file.filename):
        return err('Format non autorisé (.wav ou .mp3 uniquement).', status=422)

    MAX_SIZE = 50 * 1024 * 1024

    def _check_size(f):
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        return size <= MAX_SIZE

    if not _check_size(raw_file) or not _check_size(processed_file):
        return err('Fichier trop volumineux (max 50 MB).', status=422)

    # ── Sauvegarde ───────────────────────────────────────────────────────────
    try:
        config.MIXMASTER_SAMPLES_FOLDER.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        raw_name  = f"{current_user.id}_{ts}_raw_{secure_filename(raw_file.filename)}"
        proc_name = f"{current_user.id}_{ts}_processed_{secure_filename(processed_file.filename)}"

        raw_file.save(config.MIXMASTER_SAMPLES_FOLDER / raw_name)
        processed_file.save(config.MIXMASTER_SAMPLES_FOLDER / proc_name)

        raw_path  = Path('db_assets', 'mixmaster', 'samples', raw_name).as_posix()
        proc_path = Path('db_assets', 'mixmaster', 'samples', proc_name).as_posix()

        current_user.mixmaster_reference_price   = reference_price
        current_user.mixmaster_price_min         = price_min
        current_user.mixmaster_bio               = bio
        current_user.mixmaster_sample_raw        = raw_path
        current_user.mixmaster_sample_processed  = proc_path
        current_user.mixmaster_sample_submitted  = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'submit_mixmaster_sample error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    current_app.logger.info(f'Mixmaster sample submitted by user #{current_user.id}')
    return ok(message='Candidature soumise ! Notre équipe évaluera votre travail.', level='info')


@auth_api_bp.route('/submit-master-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def submit_master_sample(current_user):
    """Soumet un échantillon mastering pour la certification is_certified_master_engineer."""
    if not current_user.is_mixmaster_engineer:
        return err('Certification Mix Engineer requise pour soumettre un échantillon mastering.', status=403)

    raw_file       = request.files.get('sample_raw')
    processed_file = request.files.get('sample_processed')

    if not raw_file or not processed_file or \
       raw_file.filename == '' or processed_file.filename == '':
        return err('Les deux fichiers audio sont requis (brut et masterisé).', status=422)

    allowed_ext = {'wav', 'mp3'}

    def _allowed(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_ext

    if not _allowed(raw_file.filename) or not _allowed(processed_file.filename):
        return err('Format non autorisé (.wav ou .mp3 uniquement).', status=422)

    MAX_SIZE = 50 * 1024 * 1024

    def _check_size(f):
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        return size <= MAX_SIZE

    if not _check_size(raw_file) or not _check_size(processed_file):
        return err('Fichier trop volumineux (max 50 MB).', status=422)

    try:
        folder = Path(config.UPLOAD_FOLDER) / 'master_samples'
        folder.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        raw_name  = f"{current_user.id}_{ts}_raw_{secure_filename(raw_file.filename)}"
        proc_name = f"{current_user.id}_{ts}_processed_{secure_filename(processed_file.filename)}"

        raw_file.save(folder / raw_name)
        processed_file.save(folder / proc_name)

        raw_path  = Path('db_assets', 'master_samples', raw_name).as_posix()
        proc_path = Path('db_assets', 'master_samples', proc_name).as_posix()

        current_user.master_sample_raw        = raw_path
        current_user.master_sample_processed  = proc_path
        current_user.master_sample_submitted  = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'submit_master_sample error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    current_app.logger.info(f'Master sample submitted by user #{current_user.id}')
    return ok(message='Candidature mastering soumise ! Notre équipe évaluera votre travail.', level='info')


@auth_api_bp.route('/google/login')
@csrf.exempt
def google_login():
    """
    Démarre le flux OAuth Google.
    Authlib stocke le state CSRF dans Redis (via oauth.init_app(cache=redis))
    — multi-workers safe, pas de dépendance au cookie de session Flask.
    """
    redirect_uri = url_for('auth_api.google_callback', _external=True)
    current_app.logger.info('[OAuth] google_login() → authorize_redirect')
    return oauth.google.authorize_redirect(redirect_uri)


@auth_api_bp.route('/google/callback')
@csrf.exempt
def google_callback():
    """
    Callback Google OAuth.
    Authlib vérifie le state CSRF depuis Redis automatiquement.
    """
    angular_base = current_app.config.get('FRONTEND_URL', 'https://laprod.net')
    if not angular_base.startswith('http'):
        angular_base = f'https://{angular_base}'

    current_app.logger.info("[OAuth] google_callback() called")

    try:
        token      = oauth.google.authorize_access_token()
        resp       = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
        user_info  = resp.json()

        google_id      = user_info.get('sub')
        email          = user_info.get('email')
        given_name     = user_info.get('given_name', '')
        picture        = user_info.get('picture')
        email_verified = user_info.get('email_verified', False)

        # ── CAS 1 : google_id connu (exclut les comptes soft-deleted) ──────────
        user = (db.session.query(User)
                .filter_by(google_id=google_id)
                .filter(User.deleted_at.is_(None))
                .first())

        if user:
            # Ne restaure l'URL Google que si l'utilisateur n'a PAS uploadé
            # de photo personnalisée. Un upload custom efface profile_picture_url
            # (cf. edit_profile) — on ne doit jamais l'écraser en retour.
            _has_custom_image = (
                user.profile_image
                and user.profile_image != 'images/default_profile.png'
                and user.profile_image.startswith('images/profiles/')
            )
            if picture and not _has_custom_image and getattr(user, 'profile_picture_url', None) != picture:
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

        current_app.logger.debug('[OAuth] google_callback — google_id inconnu, passage au cas 2 (email lookup)')

        # ── CAS 2 : google_id inconnu (exclut les comptes soft-deleted) ────────
        user_by_email = (db.session.query(User)
                         .filter_by(email=email)
                         .filter(User.deleted_at.is_(None))
                         .first())

        if user_by_email:
            if user_by_email.oauth_provider is None:
                # Lier le compte classique à Google
                user_by_email.google_id      = google_id
                user_by_email.oauth_provider = 'google'
                # N'écrase pas une photo personnalisée déjà uploadée
                _has_custom = (
                    user_by_email.profile_image
                    and user_by_email.profile_image != 'images/default_profile.png'
                    and user_by_email.profile_image.startswith('images/profiles/')
                )
                if picture and not _has_custom:
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
    Relit toujours l'utilisateur depuis la DB pour garantir des données fraîches.
    """
    code  = request.args.get('code', '')
    entry = _pop_oauth_code(code)

    if not entry:
        return err('Code invalide ou expiré.')

    # ── Valider que l'user existe toujours en DB (token peut être stale) ─────
    user_id = (entry.get('user') or {}).get('id')
    if not user_id:
        current_app.logger.error(f'[OAuth] token_exchange: payload sans user.id')
        return err('Payload OAuth invalide.')

    user = db.session.get(User, user_id)
    if not user:
        current_app.logger.warning(f'[OAuth] token_exchange: user id={user_id} introuvable en DB')
        return err('Compte introuvable. Reconnectez-vous avec Google.', status=404)

    # Rafraîchir le payload depuis la DB (évite username/rôles stale)
    entry['user'] = _user_payload(user)
    current_app.logger.info(f'[OAuth] token_exchange: user id={user_id} username={user.username} OK')

    return ok({
        'tokens':         entry['tokens'],
        'user':           entry['user'],
        'next':           entry.get('next', '/'),
        'suggested_name': entry.get('suggested_name', ''),
    })


@auth_api_bp.route('/refresh', methods=['POST'])
@csrf.exempt
@limiter.limit('30 per minute')
@jwt_required(refresh=True)
def jwt_token_refresh():
    user_id = int(get_jwt_identity())


    jwt_data = get_jwt()
    jti = jwt_data['jti']

    if not is_refresh_token_valid(user_id, jti):
        current_app.logger.warning(f"Token refresh rejeté pour l'utilisateur #{user_id} (jti: {jti})")
        return err('Refresh token invalide ou expiré. Veuillez vous reconnecter.', status=401)

    user = db.get_or_404(User, user_id)
    current_app.logger.debug(f'refreshing via jwt_token_refresh() for {user}')

    access_token = create_access_token(identity=str(user.id))

    return ok({'access_token': access_token})

@auth_api_bp.route('/complete-oauth-profile', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
@commit_or_rollback
def complete_oauth_profile(current_user):
    """
    Finalise le profil d'un utilisateur créé via Google OAuth.
    Appelé une seule fois par les nouveaux comptes Google (account_status = pending_completion).
    Body JSON : { username, signature, accept_terms }
    """
    current_app.logger.debug(f'complete_oauth_profile() called {current_user}')

    if current_user.account_status != 'pending_completion':
        return err('Profil déjà complété.', level='warning')

    data = request.get_json() or {}
    username     = (data.get('username') or '').strip()
    signature    = (data.get('signature') or '').strip()
    accept_terms = data.get('accept_terms', False)

    if not username or len(username) < 3 or len(username) > 20:
        return err("Nom d'utilisateur : 3-20 caractères.", level='warning')

    if not re.match(r'^[\w]+$', username):
        return err('Lettres, chiffres et _ uniquement.', level='warning')

    if not signature or len(signature) < 3:
        return err('Signature légale requise (min. 3 caractères).', level='warning')

    if not accept_terms:
        return err("Veuillez accepter les conditions d'utilisation.", level='warning')

    if db.session.query(User).filter(User.username == username, User.id != current_user.id).first():
        return err("Nom d'utilisateur déjà pris.", level='warning')

    current_user.username          = username
    current_user.signature         = sanitize_html(signature)
    current_user.terms_accepted_at = datetime.now()
    current_user.account_status    = 'active'
    db.session.commit()

    # Émettre de nouveaux tokens sans le claim `oauth_incomplete`
    access_token  = create_access_token(identity=str(current_user.id))
    refresh_token = create_refresh_token(identity=str(current_user.id))
    decoded = decode_token(refresh_token)
    store_refresh_token(current_user.id, decoded['jti'], int(decoded['exp'] - time.time()))

    return ok({
        'tokens': {'access_token': access_token, 'refresh_token': refresh_token},
        'user':   _user_payload(current_user),
        'next':   'select-role' if not current_user.user_type_selected else '/',
    }, message=f'Bienvenue {current_user.username} !', level='info')
