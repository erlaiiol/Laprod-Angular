import hashlib
import enum
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, time, timedelta
from sqlalchemy import CheckConstraint, and_, or_, func
from sqlalchemy.ext.hybrid import hybrid_property

_TWO_PLACES = Decimal('0.01')

class User(UserMixin, db.Model):
    """Modèle utilisateur avec système de rôles et Stripe Connect"""
    __tablename__ = 'user'
    
    #main fields

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=True, index=True)  # nullable pour OAuth
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=True)  # nullable pour OAuth


    #oauth fields
    oauth_provider = db.Column(db.String(50), nullable=True)  # 'google', 'facebook', etc.
    google_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    profile_picture_url = db.Column(db.String(500), nullable=True)  # URL de l'image de profil OAuth

    #account enabling status REMPLACE IS_ACTIVE VOIR AUTH.PY, ADMIN.PY, CONTRACTS.PY
    account_status=db.Column(
        db.String(50), nullable=False, default='pending_completion',
        index=True
    ) #active, pending_completion, deleted

    #enabling info sources
    terms_accepted_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    #TIMESTAMPS
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Informations profil
    bio = db.Column(db.Text, nullable=True)
    profile_image = db.Column(db.String(200), nullable=True, default='images/default_profile.png')
    
    # Réseaux sociaux
    instagram = db.Column(db.String(100), nullable=True)
    twitter = db.Column(db.String(100), nullable=True)
    youtube = db.Column(db.String(100), nullable=True)
    soundcloud = db.Column(db.String(100), nullable=True)
    
    # Signature numérique pour les contrats
    signature = db.Column(db.String(200), nullable=True)
    
    #  STRIPE CONNECT - pour recevoir les paiements
    stripe_account_id = db.Column(db.String(200), nullable=True, unique=True)
    stripe_account_status = db.Column(db.String(50), nullable=True)  # 'pending', 'active', 'rejected'
    stripe_onboarding_complete = db.Column(db.Boolean, default=False, nullable=False)
    
    # Rôle
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    #  TYPES D'UTILISATEUR (sélection obligatoire après inscription)
    user_type_selected = db.Column(db.Boolean, default=False, nullable=False)  # A-t-il rempli ses rôles?
    is_artist = db.Column(db.Boolean, default=False, nullable=False)  # Interprète/chanteur
    is_beatmaker = db.Column(db.Boolean, default=False, nullable=False)  # Beatmaker/compositeur/producteur
    is_mix_engineer = db.Column(db.Boolean, default=False, nullable=False)  # Mix/master engineer

    #  SYSTÈME MIX/MASTER
    is_mixmaster_engineer = db.Column(db.Boolean, default=False, nullable=False)  # Certifié par admin
    is_certified_producer_arranger = db.Column(db.Boolean, default=False, nullable=False)  # Certifié producteur/arrangeur (intervention artistique)
    mixmaster_reference_price = db.Column(db.Numeric(10, 2), nullable=True)  # Prix de référence (base 100% pour calcul des services)
    mixmaster_price_min       = db.Column(db.Numeric(10, 2), nullable=True)  # Prix minimum (entre 35% et 80% du prix référence : paliers 35/55/80)
    mixmaster_bio = db.Column(db.Text, nullable=True)  # Description de ses compétences
    mixmaster_sample_raw = db.Column(db.String(200), nullable=True)  # Audio brut exemple
    mixmaster_sample_processed = db.Column(db.String(200), nullable=True)  # Audio traité exemple
    mixmaster_sample_submitted = db.Column(db.Boolean, default=False, nullable=False)  # A soumis échantillon?
    producer_arranger_request_submitted = db.Column(db.Boolean, default=False, nullable=False)  # A demandé certification producteur/arrangeur?
    # is_mixmaster_engineer = "Certified Mix Engineer" validé par admin (samples de mixage).
    # is_certified_master_engineer = spécialisation mastering (sample admin OU abonnement Pro).
    is_certified_master_engineer = db.Column(db.Boolean, default=False, nullable=False)
    master_sample_raw = db.Column(db.String(200), nullable=True)       # Audio brut mastering (soumission admin)
    master_sample_processed = db.Column(db.String(200), nullable=True) # Audio masterisé (soumission admin)
    master_sample_submitted = db.Column(db.Boolean, default=False, nullable=False)  # En attente de validation admin

    # ABONNEMENT
    # subscription_plan : 'free' | 'amateur' | 'pro'
    # is_premium est un hybrid_property dérivé (rétrocompatibilité totale)
    subscription_plan    = db.Column(db.String(20),  nullable=False, default='free')
    premium_since        = db.Column(db.DateTime,    nullable=True)
    premium_expires_at   = db.Column(db.DateTime,    nullable=True)
    # 'stripe' = souscription payée | 'admin' = accordé manuellement | None = jamais eu
    premium_source       = db.Column(db.String(20),  nullable=True)
    premium_price_paid   = db.Column(db.Numeric(10, 2), nullable=True)

    #  SYSTÈME DE TOKENS POUR UPLOAD DE BEATS
    upload_track_tokens = db.Column(db.Integer, default=20)  # Nombre de beats uploadables
    last_upload_reset = db.Column(db.Date, default=date.today)  # Date du dernier upload

    #  SYSTÈME DE CRÉDITS POUR TOPLINES
    topline_tokens = db.Column(db.Integer, default=5)  # Free: 5 crédits/semaine
    last_topline_reset = db.Column(db.Date, default=date.today)  # Date dernier reset hebdo

    #  PRÉFÉRENCES D'AFFICHAGE
    preferred_tag_category = db.Column(db.String(50), nullable=True, default=None)

    # Relations
    tracks = db.relationship('Track', foreign_keys='Track.composer_id', backref='composer_user', lazy=True, cascade='all, delete-orphan')
    toplines = db.relationship('Topline', backref='artist_user', lazy=True, cascade='all, delete-orphan')
    purchases = db.relationship('Purchase', backref='buyer_user', lazy=True)
    notifications = db.relationship('Notification', back_populates='recipient_user', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        CheckConstraint('upload_track_tokens >= 0', name='ck_upload_tokens_non_negative'),
        CheckConstraint('topline_tokens >= 0', name='ck_topline_tokens_non_negative'),
    )
    
    # ===========================================
    # UPLOAD QUOTA METHODS
    # ===========================================

    # Premium status check

    @property
    def is_premium_active(self):
        """True si abonnement amateur ou pro en cours (non expiré)."""
        if self.subscription_plan == 'free':
            return False
        return self.premium_expires_at is None or self.premium_expires_at >= datetime.now()

    @hybrid_property
    def is_premium(self):
        """Rétrocompatibilité — True si is_premium_active."""
        return self.is_premium_active

    @is_premium.expression
    def is_premium(cls):
        return and_(
            cls.subscription_plan != 'free',
            or_(cls.premium_expires_at.is_(None), cls.premium_expires_at >= func.now())
        )

    @property
    def is_pro(self):
        """True si abonnement Pro en cours."""
        return self.subscription_plan == 'pro' and self.is_premium_active

    @property
    def can_do_mastering(self):
        """True si certifié master par admin OU abonnement Pro actif."""
        return self.is_certified_master_engineer or self.is_pro

    
    # TRACKS ALLOW UPLOAD METHODS


    def _reset_daily_uploads(self):
        """Réinitialise les tokens d'upload quotidiennement si nécessaire.

        - Free    : +1/jour, cap 2
        - Amateur : +5/jour, cap 15
        - Pro     : +10/jour, cap 30
        """
        today = date.today()
        if self.last_upload_reset < today:
            if self.subscription_plan == 'pro' and self.is_premium_active:
                cap, gain = 30, 10
            elif self.subscription_plan == 'amateur' and self.is_premium_active:
                cap, gain = 15, 5
            else:
                cap, gain = 2, 1
            if self.upload_track_tokens < cap:
                self.upload_track_tokens = min(cap, self.upload_track_tokens + gain)
            self.last_upload_reset = today

    def can_upload_track(self):
        """Vérifie si l'utilisateur peut uploader un nouveau track

        Effectue le reset quotidien automatique avant vérification.

        Returns:
            tuple: (bool, str) - (peut_uploader, message_explicatif)

        Example:
            can_upload, msg = user.can_upload_track()
            if can_upload:
                # Proceed with upload
        """
        # Reset quotidien si nécessaire
        self._reset_daily_uploads()

        # Vérifier tokens
        if self.upload_track_tokens > 0:
            return True, f"✓ {self.upload_track_tokens} token(s) restant(s)"

        if self.subscription_plan == 'pro' and self.is_premium_active:
            return False, "Plus de tokens. Recharge demain (+10 tokens)."
        elif self.is_premium_active:
            return False, "Plus de tokens. Recharge demain (+5 tokens)."
        else:
            return False, "Plus de tokens. Recharge demain (+1 token) ou passez LaProd+."

    def consume_upload_token(self):
        """Consomme un token d'upload après validation réussie

        ️ Appeler uniquement APRÈS vérification avec can_upload_track()
        et APRÈS que l'upload ait réussi.

        Raises:
            ValueError: Si aucun token disponible (ne devrait jamais arriver)

        Example:
            # Dans la route d'upload
            can_upload, msg = current_user.can_upload_track()
            if not can_upload:
                flash(msg, 'error')
                return redirect(url_for('tracks.add_track'))

            # ... upload logic ...
            current_user.consume_upload_token()
            db.session.commit()
        """
        if self.upload_track_tokens <= 0:
            raise ValueError("Tentative de consommer un token alors qu'il n'y en a plus")

        self.upload_track_tokens -= 1

    def upload_track_tokens_promotion(self, additional_tokens):
        """Ajoute des tokens bonus (promo code, admin, événement spécial)

        Bypass du système de caps quotidiens. Permet d'accumuler
        au-delà des limites normales (3 free / 15 premium).

        Args:
            additional_tokens (int): Nombre de tokens à ajouter (doit être > 0)

        Raises:
            ValueError: Si le nombre de tokens n'est pas positif

        Example:
            # Promo "20 uploads gratuits"
            user.upload_track_tokens_promotion(20)
            db.session.commit()
        """
        if additional_tokens <= 0:
            raise ValueError("Le nombre de tokens doit être positif")

        self.upload_track_tokens = (self.upload_track_tokens or 0) + additional_tokens

    def apply_premium_tokens(self):
        """Monte immédiatement les tokens au plafond du plan actif (activation / renouvellement).

        - Amateur : upload cap 15, topline cap 50
        - Pro     : upload cap 30, topline cap 200
        """
        today = date.today()
        upload_cap, topline_cap = (30, 200) if self.subscription_plan == 'pro' else (15, 50)
        if self.upload_track_tokens < upload_cap:
            self.upload_track_tokens = upload_cap
            self.last_upload_reset = today
        if self.topline_tokens < topline_cap:
            self.topline_tokens = topline_cap
            self.last_topline_reset = today

    # TOPLINE ALLOW UPLOAD METHODS

    def _reset_weekly_toplines(self):
        """Réinitialise les tokens de toplines chaque semaine.

        - Free    : +5/semaine, cap 5
        - Amateur : +50/semaine, cap 50
        - Pro     : +200/semaine, cap 200
        """
        today = date.today()
        if self.last_topline_reset + timedelta(days=7) <= today:
            if self.subscription_plan == 'pro' and self.is_premium_active:
                cap, gain = 200, 200
            elif self.subscription_plan == 'amateur' and self.is_premium_active:
                cap, gain = 50, 50
            else:
                cap, gain = 5, 5
            if self.topline_tokens < cap:
                self.topline_tokens = min(cap, self.topline_tokens + gain)
            self.last_topline_reset = today

    @property
    def next_topline_reset_date(self):
        """Retourne la date du prochain reset hebdomadaire des toplines

        Returns:
            date: Date du prochain reset (7 jours après le dernier reset)
        """
        return self.last_topline_reset + timedelta(days=7)
        
    @property
    def days_until_topline_reset(self):
        now = datetime.now()

        reset_dt = self.next_topline_reset_date
        if isinstance(reset_dt, date) and not isinstance(reset_dt, datetime):
            reset_dt = datetime.combine(reset_dt, time.min)

        delta = reset_dt - now

        # Reset déjà passé
        if delta.total_seconds() <= 0:
            return "00:00:00"

        # Plus d'un jour → retourner le nombre de jours
        if delta.days > 1:



            return f'{delta.days} jours'

        # Moins ou égal à 1 jour → HH:MM:SS
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"



    def can_submit_topline(self):
        """Vérifie si l'utilisateur peut soumettre une nouvelle topline

        Effectue le reset hebdomadaire automatique avant vérification.

        Returns:
            tuple: (bool, str) - (peut_soumettre, message_explicatif)

        Example:
            can_submit, msg = user.can_submit_topline()
            if can_submit:
                # Proceed with submission
        """
        # Reset hebdomadaire si nécessaire
        self._reset_weekly_toplines()

        # Vérifier tokens
        if self.topline_tokens > 0:
            return True, f"✓ {self.topline_tokens} token(s) de topline restant(s)"

        # Message différent selon le statut
        if self.is_premium_active:
            return False, "Plus de tokens de topline. Recharge la semaine prochaine (+50 tokens)."
        else:
            return False, "Plus de tokens de topline. Recharge la semaine prochaine (+5 tokens) ou passez Premium."

    def consume_topline_token(self):
        """Consomme un token de topline après soumission réussie

        ️ Appeler uniquement APRÈS vérification avec can_submit_topline()
        et APRÈS que la soumission ait réussi.

        Raises:
            ValueError: Si aucun token disponible (ne devrait jamais arriver)

        Example:
            # Dans la route de soumission de topline
            can_submit, msg = current_user.can_submit_topline()
            if not can_submit:
                flash(msg, 'error')
                return redirect(url_for('tracks.view_track', track_id=track.id))

            # ... submission logic ...
            current_user.consume_topline_token()
            db.session.commit()
        """
        if self.topline_tokens <= 0:
            raise ValueError("Votre compteur de toplines est à zéro. Impossible de soumettre.")

        self.topline_tokens -= 1

    def topline_tokens_promotion(self, additional_tokens):
        """Ajoute des tokens de topline bonus (promo code, admin, événement spécial)

        Bypass du système de caps hebdomadaires. Permet d'accumuler
        au-delà des limites normales (5 free / 50 premium).

        Args:
            additional_tokens (int): Nombre de tokens à ajouter (doit être > 0)
        Raises:
            ValueError: Si le nombre de tokens n'est pas positif
        Example:
            # Promo "10 toplines gratuites"
            user.topline_tokens_promotion(10)
            db.session.commit()
        """
        if additional_tokens <= 0:
            raise ValueError("Le nombre de tokens doit être positif")

        self.topline_tokens = (self.topline_tokens or 0) + additional_tokens



    #PASSWORD METHODS
    def set_password(self, password):
        """Hash le mot de passe"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Vérifie le mot de passe"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    #ACTIVITY METHODS (override UserMixin)
    @property
    def is_active(self):
        """Vérifie si le compte est actif (inclut pending_completion pour permettre la complétion du profil)"""
        return self.account_status in ['active', 'pending_completion']
    
    def is_pending_completion(self):
        """Vérifie si le compte est en attente de complétion"""
        return self.account_status == 'pending_completion'
    
    def complete_profile(self, username, signature=None):
        """
        Complète le profil après OAuth

        Args:
            username (str): Nom d'utilisateur choisi
            signature (str, optional): Signature légale pour les contrats
        """
        self.username = username
        self.account_status = 'active'
        self.terms_accepted_at = datetime.now()
        self.email_verified = True

        # Ajouter la signature si fournie
        if signature:
            self.signature = signature


    # STRIPE METHODS
    def can_receive_payments(self):
        """Vérifie si l'utilisateur peut recevoir des paiements (retrait wallet → Connect)"""
        return self.stripe_onboarding_complete and self.stripe_account_status == 'active'

    def get_or_create_wallet(self):
        """Retourne le wallet de l'utilisateur, le crée s'il n'existe pas encore."""
        if self.wallet is None:
            wallet = Wallet(user_id=self.id)
            db.session.add(wallet)
            db.session.flush()  # Obtenir l'ID sans commit complet
            return wallet       # self.wallet pas encore rafraîchi, on retourne directement
        return self.wallet

    # Represention "who is" the user
    def __repr__(self):
        return f"<User {self.username}{'[ADMIN]' if self.is_admin else ''}>"


class Category(db.Model):
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), unique=True, nullable=False)
    color = db.Column(db.String(7), nullable=True, default='#6b7280')  # Couleur hexadécimale
    description = db.Column(db.Text, nullable=True)
    tags = db.relationship('Tag', back_populates='category_obj')

    def __repr__(self):
        return f"<Category {self.name}>"


class Tag(db.Model):
    __tablename__ = 'tag'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)

    category_obj = db.relationship('Category', back_populates='tags')
    
    def __repr__(self):
        return f"<Tag {self.name}>"


# Table association N:M entre Track et Tag
track_tag = db.Table('track_tag',
    db.Column('track_id', db.Integer, db.ForeignKey('track.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)


class Track(db.Model):
    """Modèle Track avec multi-formats et pourcentage SACEM"""
    __tablename__ = "track"
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    composer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    file_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    
    # Fichiers audio
    audio_file = db.Column(db.String(200), nullable=False)  # Preview watermarké 1:30
    file_mp3 = db.Column(db.String(200), nullable=True)     # MP3 complet pour vente
    file_wav = db.Column(db.String(200), nullable=True)     # WAV complet
    file_stems = db.Column(db.String(200), nullable=True)   # ZIP stems
    
    image_file = db.Column(db.String(200), nullable=True)
    
    # Prix par format
    price_mp3   = db.Column(db.Numeric(10, 2), default=Decimal('9.99'),  nullable=False)
    price_wav   = db.Column(db.Numeric(10, 2), default=Decimal('19.99'), nullable=False)
    price_stems = db.Column(db.Numeric(10, 2), default=Decimal('49.99'), nullable=False)
    
    #  POURCENTAGE SACEM - ce que le compositeur garde (l'acheteur reçoit 100 - sacem_percentage)
    sacem_percentage_composer = db.Column(db.Integer, default=50, nullable=False)  # Entre 0 et 100
    
    # Métadonnées
    bpm = db.Column(db.Integer, nullable=False)
    key = db.Column(db.String(50), nullable=False)
    style = db.Column(db.String(50), nullable=True)
    
    # Modération
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    # Prix des droits de contrat (Integer, nullable → null = utiliser le défaut plateforme)
    contract_price_exclusive      = db.Column(db.Integer, nullable=True)  # défaut: 150
    contract_price_duration_3y    = db.Column(db.Integer, nullable=True)  # défaut: 5
    contract_price_duration_5y    = db.Column(db.Integer, nullable=True)  # défaut: 10
    contract_price_duration_10y   = db.Column(db.Integer, nullable=True)  # défaut: 15
    contract_price_lifetime       = db.Column(db.Integer, nullable=True)  # défaut: 50
    contract_price_mechanical     = db.Column(db.Integer, nullable=True)  # défaut: 30
    contract_price_public_show    = db.Column(db.Integer, nullable=True)  # défaut: 40
    contract_price_arrangement    = db.Column(db.Integer, nullable=True)  # défaut: 10
    contract_price_territory_eu   = db.Column(db.Integer, nullable=True)  # défaut: 5
    contract_price_territory_world = db.Column(db.Integer, nullable=True) # défaut: 10

    # Analyse IA — BPM/gamme/style détectés automatiquement, en attente de validation
    is_ai_suggested = db.Column(db.Boolean, default=False, nullable=False, server_default='false')

    # Exclusivité vendue
    is_exclusive_sold  = db.Column(db.Boolean, default=False, nullable=False)
    exclusive_sold_at  = db.Column(db.DateTime, nullable=True)
    exclusive_buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relations
    tags = db.relationship('Tag', secondary='track_tag', backref='tracks')
    toplines = db.relationship('Topline', backref='track', lazy=True, cascade='all, delete-orphan')
    purchases = db.relationship('Purchase', backref='track', lazy=True)
    exclusive_buyer = db.relationship('User', foreign_keys=[exclusive_buyer_id])

    __table_args__ = (
        CheckConstraint('price_mp3 >= 0', name='ck_track_price_mp3_positive'),
        CheckConstraint('price_wav >= 0', name='ck_track_price_wav_positive'),
        CheckConstraint('price_stems >= 0', name='ck_track_price_stems_positive'),
        CheckConstraint('bpm >= 40 AND bpm <= 300', name='ck_track_bpm_range'),
        CheckConstraint('sacem_percentage_composer >= 0 AND sacem_percentage_composer <= 100', name='ck_sacem_percentage_valid'),
        db.Index('idx_track_composer', 'composer_id'),
    )

    def get_sacem_percentage_buyer(self):
        """Retourne le pourcentage que l'acheteur recevra à la SACEM"""
        return 100 - self.sacem_percentage_composer



    @property
    def purchase_count(self):
        """Retourne le nombre de fois que ce track a été acheté"""
        return len(self.purchases)

    # V2 SOON
    # def can_be_exclusive(self):
    #     """Vérifie si le track peut être vendu en exclusivité"""
    #     if self.purchase_count < 1:
    #         self.available_for_exclusivity = True
    #     else:
    #         self.available_for_exclusivity = False
    #     return self.available_for_exclusivity


    @staticmethod
    def compute_file_hash(file):
        """Calcule le SHA-256 d'un FileStorage sans consommer le curseur"""
        file.seek(0)
        file_hash = hashlib.sha256(file.read()).hexdigest()
        file.seek(0)
        return file_hash

    @staticmethod
    def hash_exists(file_hash):
        """Vérifie si un track avec ce hash existe déjà en BDD"""
        return db.session.query(Track).filter_by(file_hash=file_hash).first() is not None

    def __repr__(self):
        return f"<Track {self.title} by {self.composer_user.username}>"


# ── Playlists ─────────────────────────────────────────────────────────────────

playlist_track = db.Table(
    'playlist_track',
    db.Column('playlist_id', db.Integer, db.ForeignKey('playlist.id', ondelete='CASCADE'), primary_key=True),
    db.Column('track_id',    db.Integer, db.ForeignKey('track.id',    ondelete='CASCADE'), primary_key=True),
    db.Column('position',    db.Integer, default=0),
    db.Column('added_at',    db.DateTime, default=datetime.now),
)


class Playlist(db.Model):
    __tablename__ = 'playlist'

    id           = db.Column(db.Integer, primary_key=True)
    beatmaker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title        = db.Column(db.String(200), nullable=False)
    image_file   = db.Column(db.String(200), nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.now)

    beatmaker = db.relationship('User', backref=db.backref('playlists', cascade='all, delete-orphan'))
    tracks    = db.relationship('Track', secondary=playlist_track, backref='playlists',
                                order_by=playlist_track.c.position)

    def __repr__(self):
        return f"<Playlist '{self.title}' by user#{self.beatmaker_id}>"


class Topline(db.Model):
    """Toplines soumises par les artistes"""
    __tablename__ = 'topline'
    
    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    artist_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    audio_file = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    
    def __repr__(self):
        return f"<Topline by {self.artist_user.username} on Track#{self.track_id}>"


class Purchase(db.Model):
    """Achats de tracks avec commission plateforme"""
    __tablename__ = 'purchase'
    
    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Informations achat
    format_purchased = db.Column(db.String(20), nullable=False)  # 'mp3', 'wav', 'stems'
    price_paid       = db.Column(db.Numeric(10, 2), nullable=False)   # Prix total payé (track + contrat)
    buyer_name       = db.Column(db.String(200), nullable=False)       # Pour le contrat

    #  RÉPARTITION FINANCIÈRE
    contract_price   = db.Column(db.Numeric(10, 2), default=Decimal('0'), nullable=False)  # Prix du contrat uniquement
    track_price      = db.Column(db.Numeric(10, 2), nullable=False)   # Prix du track uniquement
    platform_fee     = db.Column(db.Numeric(10, 2), nullable=False)   # Commission plateforme (10%)
    composer_revenue = db.Column(db.Numeric(10, 2), nullable=False)   # Ce que reçoit le compositeur (90%)
    
    # Stripe
    stripe_payment_intent_id = db.Column(db.String(200), unique=True, nullable=False)
    stripe_transfer_id = db.Column(db.String(200), nullable=True)  # ID du transfert au compositeur
    
    # Contrat généré
    contract_file = db.Column(db.String(200), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
        
    __table_args__ = (
    CheckConstraint('price_paid >= 0', name='ck_purchase_price_positive'),
    CheckConstraint('platform_fee >= 0', name='ck_purchase_fee_positive'),
    CheckConstraint('composer_revenue >= 0', name='ck_purchase_revenue_positive'),
    )

    def calculate_fees(self, total_amount, platform_commission=Decimal('0.10')):
        """Calcule la répartition des revenus"""
        total = Decimal(str(total_amount))
        commission = Decimal(str(platform_commission))
        self.platform_fee     = (total * commission).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        self.composer_revenue = (total - self.platform_fee).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    
    def __repr__(self):
        return f"<Purchase Track#{self.track_id} - {self.format_purchased}>"
    

class Contract(db.Model):
    """Contrats avec pourcentage SACEM"""
    __tablename__ = 'contract'

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    composer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Informations
    composer_address = db.Column(db.String(300), nullable=True)
    composer_email = db.Column(db.String(120), nullable=True)
    composer_credit = db.Column(db.String(200), nullable=True)
    client_address = db.Column(db.String(300), nullable=True)
    client_email = db.Column(db.String(120), nullable=True)
    
    is_exclusive = db.Column(db.Boolean, default=False, nullable=False)
    
    start_date = db.Column(db.String(200), nullable=False)
    end_date = db.Column(db.String(200), nullable=False)
    duration_text = db.Column(db.String(100), nullable=True)
    territory = db.Column(db.String(200), nullable=False)
    
    # Droits
    mechanical_reproduction = db.Column(db.Boolean, default=False, nullable=False)
    public_show = db.Column(db.Boolean, default=False, nullable=False)
    streaming = db.Column(db.Boolean, default=False, nullable=False)
    arrangement = db.Column(db.Boolean, default=False, nullable=False)
    
    #  POURCENTAGES SACEM - stockés dans le contrat pour historique
    sacem_percentage_composer = db.Column(db.Integer, nullable=False)  # % compositeur
    sacem_percentage_buyer = db.Column(db.Integer, nullable=False)  # % acheteur/interprète
    
    price = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Integer, nullable=False)  # Ce champ existe déjà, peut-être redondant ?
    
    signature_place = db.Column(db.String(200), nullable=True)
    signature_date = db.Column(db.String(200), nullable=True)
    
    contract_file = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Relations
    track = db.relationship('Track', foreign_keys=[track_id], backref='contracts')
    composer = db.relationship('User', foreign_keys=[composer_id], backref='signed_composer_contracts')
    client = db.relationship('User', foreign_keys=[client_id], backref='signed_client_contracts')

    __table_args__ = (
    CheckConstraint('price >= 0', name='ck_contract_price_positive'),
    CheckConstraint('percentage >= 0 AND percentage <= 85', name='ck_contract_percentage_valid'),
    )

class MixMasterRequest(db.Model):
    """Demandes de mixage/mastering avec système d'acompte"""
    __tablename__ = 'mixmaster_request'

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(50), default=False, nullable=False)

    artist_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    engineer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Fichiers
    original_file = db.Column(db.String(200), nullable=False)  # Fichier piste par piste envoyé (.zip)
    reference_file = db.Column(db.String(200), nullable=True)  # Maquette/référence de l'artiste
    processed_file = db.Column(db.String(200), nullable=True)  # Fichier traité par l'engineer
    processed_file_preview = db.Column(db.String(200), nullable=True)  # Version coupée en 2 (qualité originale)
    processed_file_preview_full = db.Column(db.String(200), nullable=True)  # Version entière, qualité réduite (60Hz-13kHz)
    archive_file_tree = db.Column(db.JSON, nullable=True)  # Arborescence des fichiers de l'archive (pour vérification engineer)

    # Services sélectionnés par l'artiste
    service_cleaning = db.Column(db.Boolean, default=False, nullable=False)  # Nettoyage et équilibre (+35%)
    service_effects = db.Column(db.Boolean, default=False, nullable=False)  # Mixage avec effets (+45%)
    service_artistic = db.Column(db.Boolean, default=False, nullable=False)  # Intervention artistique (+60%, certif. Producteur requise)
    service_mastering = db.Column(db.Boolean, default=False, nullable=False)  # Mastering final (+20%)

    # Options supplémentaires
    has_separated_stems = db.Column(db.Boolean, default=False, nullable=False)  # Pistes séparées (+20% sur total)
    artist_message = db.Column(db.Text, nullable=True)  # Message d'intention facultatif de l'artiste

    # Briefing détaillé de l'artiste (tous les champs sont facultatifs)
    brief_vocals = db.Column(db.Text, nullable=True)  # Indications sur le rendu de la voix
    brief_backing_vocals = db.Column(db.Text, nullable=True)  # Indications sur les backs
    brief_ambiance = db.Column(db.Text, nullable=True)  # Indications sur les ambiances
    brief_bass = db.Column(db.Text, nullable=True)  # Indications sur les basses
    brief_energy_style = db.Column(db.Text, nullable=True)  # Indications sur l'énergie/style général
    brief_references = db.Column(db.Text, nullable=True)  # Artistes/chansons de référence
    brief_instruments = db.Column(db.Text, nullable=True)  # Indications sur les instruments
    brief_percussion = db.Column(db.Text, nullable=True)  # Indications sur les percussions
    brief_effects = db.Column(db.Text, nullable=True)  # Indications sur les effets souhaités
    brief_structure = db.Column(db.Text, nullable=True)  # Structure du son avec timecodes

    # Statut de la demande
    status = db.Column(db.String(50), default='awaiting_acceptance', nullable=False)
    # 'awaiting_acceptance': demande envoyée, en attente d'acceptation par l'engineer
    # 'accepted': engineer a accepté, acompte versé, deadline activée
    # 'rejected': engineer a refusé la demande
    # 'processing': engineer travaille dessus
    # 'delivered': preview envoyée à l'artiste, en attente de sa décision
    # 'revision1': artiste a demandé la 1ère révision, 10% transféré à l'engineer (partially_captured)
    # 'revision2': artiste a demandé la 2ème révision, 10% supplémentaire transféré (partially_captured)
    # 'completed': artiste a validé, paiement complet effectué (fully_transferred)
    # 'refunded': artiste a refusé la livraison ou délai dépassé — remboursement partiel


    # Finances
    total_price      = db.Column(db.Numeric(10, 2), nullable=False)   # Prix total
    deposit_amount   = db.Column(db.Numeric(10, 2), nullable=False)   # Acompte (30%)
    remaining_amount = db.Column(db.Numeric(10, 2), nullable=False)   # Reste à payer (70%)
    platform_fee     = db.Column(db.Numeric(10, 2), nullable=False)   # Commission plateforme (10%)
    engineer_revenue = db.Column(db.Numeric(10, 2), nullable=False)   # Ce que reçoit l'engineer

    # Stripe - Nouveau système avec Payment Intent
    stripe_payment_intent_id = db.Column(db.String(200), nullable=True)  # ID Payment Intent (autorisation totale)
    stripe_payment_status = db.Column(db.String(50), default='pending')  # pending, authorized, partially_captured, fully_captured, canceled
    stripe_deposit_payment_id = db.Column(db.String(200), nullable=True)  # ID paiement acompte (deprecated)
    stripe_final_payment_id = db.Column(db.String(200), nullable=True)  # ID paiement final (deprecated)
    stripe_deposit_transfer_id = db.Column(db.String(200), nullable=True)  # ID transfert acompte
    stripe_final_transfer_id = db.Column(db.String(200), nullable=True)  # ID transfert final
    stripe_refund_id = db.Column(db.String(200), nullable=True)  # ID remboursement si délai dépassé

    # ========== SYSTÈME DE RÉVISIONS ==========
    revision_count = db.Column(db.Integer, default=0, nullable=False)
    revision1_message = db.Column(db.Text, nullable=True)
    revision2_message = db.Column(db.Text, nullable=True)
    revision1_requested_at = db.Column(db.DateTime, nullable=True)
    revision1_delivered_at = db.Column(db.DateTime, nullable=True)
    revision2_requested_at = db.Column(db.DateTime, nullable=True)
    revision2_delivered_at = db.Column(db.DateTime, nullable=True)
    processed_file_revision1 = db.Column(db.String(200), nullable=True)
    processed_file_revision2 = db.Column(db.String(200), nullable=True)
    stripe_revision1_transfer_id = db.Column(db.String(200), nullable=True)
    stripe_revision2_transfer_id = db.Column(db.String(200), nullable=True)

    # Dates
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    accepted_at = db.Column(db.DateTime, nullable=True)  # Date d'acceptation par l'engineer
    rejected_at = db.Column(db.DateTime, nullable=True)  # Date de refus par l'engineer
    deadline = db.Column(db.DateTime, nullable=True)  # Date limite (7 jours après acceptation)
    delivered_at = db.Column(db.DateTime, nullable=True)  # Date de livraison du preview
    completed_at = db.Column(db.DateTime, nullable=True)  # Date de validation finale par l'artiste

    # Relations
    artist = db.relationship('User', foreign_keys=[artist_id], backref='mixmaster_requests_as_artist')
    engineer = db.relationship('User', foreign_keys=[engineer_id], backref='mixmaster_requests_as_engineer')

    __table_args__ = (
    CheckConstraint('total_price >= 0', name='ck_mixmaster_price_positive'),
    CheckConstraint('deposit_amount >= 0', name='ck_mixmaster_deposit_positive'),
    )

    def reset_deadline(self):
        self.deadline = date.today()

    def calculate_service_price(self, base_price_max):
        """
        Calcule le prix total basé sur les services sélectionnés

        IMPORTANT: Les prix sont arrondis à 2 décimales pour la précision.
        Stripe travaille en centimes donc les décimales sont supportées.

        Grille de prix (% du reference_price) — services individuels :
        - Nettoyage et équilibre : +35%
        - Mixage avec effets     : +45%
        - Mastering final        : +20%
        - Intervention artistique: +60% (requiert is_certified_producer_arranger)
        - Pistes séparées        : +20%

        Paliers combinés standards :
        - Nettoyage seul              : 35%
        - Nettoyage + Mastering       : 55%
        - Nettoyage + Effets          : 80%
        - Nettoyage + Effets + Master : 100%
        - Tous les services           : 160%
        - Tous + pistes séparées      : 180%
        """
        base = Decimal('0')
        ref  = Decimal(str(base_price_max))

        if self.service_cleaning:
            base += (ref * Decimal('0.35')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        if self.service_effects:
            base += (ref * Decimal('0.45')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        if self.service_mastering:
            base += (ref * Decimal('0.20')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        if self.service_artistic:
            base += (ref * Decimal('0.60')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        if self.has_separated_stems:
            base += (ref * Decimal('0.20')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        return base.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def calculate_payments(self, platform_commission=0.10):
        """
        Calcule la répartition des paiements

        IMPORTANT: Tous les montants sont arrondis à 2 décimales.
        Stripe supporte les centimes (montants en cents : 7500 = 75.00€).
        """
        total      = Decimal(str(self.total_price))
        commission = Decimal(str(platform_commission))
        self.deposit_amount   = (total * Decimal('0.30')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        self.remaining_amount = (total - self.deposit_amount).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        self.platform_fee     = (total * commission).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        self.engineer_revenue = (total - self.platform_fee).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def get_total_transferred_to_engineer(self):
        """
        Montant total déjà transféré à l'engineer.
        Inclut l'acompte initial + les acomptes de révision.
        - Acompte initial : 30% × 90% = 27% du total
        - Chaque révision : 10% × 90% = 9% du total
        """
        deposit_net  = (Decimal(str(self.deposit_amount or 0)) * Decimal('0.90')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        revision_net = (Decimal(str(self.total_price or 0)) * Decimal('0.10') * Decimal('0.90') * (self.revision_count or 0)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        return (deposit_net + revision_net).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def get_remaining_for_final_transfer(self):
        """Montant restant à transférer (délégation vers get_final_transfer_amount)"""
        return self.get_final_transfer_amount()

    def can_request_revision(self):
        """
        Vérifie si l'artiste peut demander une révision.
        Returns: tuple (bool, str)
        """
        if self.status != 'delivered':
            return False, "Le fichier n'a pas encore été livré"
        if (self.revision_count or 0) >= 2:
            return False, "Nombre maximum de révisions atteint (2)"
        return True, "OK"

    def get_revision_transfer_amount(self):
        """
        Montant NET à transférer à l'engineer pour une révision.
        10% brut × 90% net = 9% du total.
        """
        return (Decimal(str(self.total_price or 0)) * Decimal('0.10') * Decimal('0.90')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def get_final_transfer_amount(self):
        """
        Montant NET à transférer à l'engineer lors du téléchargement final.
        - 0 révision : 70% × 90% = 63%
        - 1 révision : 60% × 90% = 54%
        - 2 révisions : 50% × 90% = 45%
        """
        gross_remaining_pct = Decimal('0.70') - (Decimal('0.10') * (self.revision_count or 0))
        return (Decimal(str(self.total_price or 0)) * gross_remaining_pct * Decimal('0.90')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def get_refund_amount(self):
        """
        Montant à rembourser à l'artiste en cas de refus de la livraison.
        = total_price × (70% - révisions × 10%)
        L'ingénieur conserve le dépôt initial (30%) + les acomptes de révision (10%/révision)
        déjà crédités dans son wallet.

        - 0 révision  : remboursement 70% du total
        - 1 révision  : remboursement 60% du total
        - 2 révisions : remboursement 50% du total
        """
        remaining_pct = Decimal('0.70') - (Decimal('0.10') * (self.revision_count or 0))
        return (Decimal(str(self.total_price or 0)) * remaining_pct).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def is_expired(self):
        """
        Vérifie si la demande a dépassé le délai de 7 jours.
        Les statuts revision1/revision2 ne sont pas expirables (délai suspendu).
        """
        from datetime import datetime
        expirable_statuses = ['accepted', 'processing', 'delivered']
        return (
            self.deadline is not None
            and datetime.now() > self.deadline
            and self.status in expirable_statuses
        )

    def get_active_requests_count(engineer_id):
        """Retourne le nombre de mix/master en cours pour un engineer (max 5)"""
        return db.session.query(MixMasterRequest).filter(
            MixMasterRequest.engineer_id == engineer_id,
            MixMasterRequest.status.in_(['accepted', 'processing', 'delivered', 'revision1', 'revision2'])
        ).count()

    def can_accept_more_requests(engineer_id):
        """Vérifie si l'engineer peut accepter plus de demandes (limite: 5)"""
        return MixMasterRequest.get_active_requests_count(engineer_id) < 5

    def __repr__(self):
        return f"<MixMasterRequest #{self.id} - {self.status}>"


class PriceChangeRequest(db.Model):
    """Demandes de modification de prix pour les mix/master engineers"""
    __tablename__ = 'price_change_request'

    id = db.Column(db.Integer, primary_key=True)
    engineer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Prix actuels (avant modification)
    old_reference_price = db.Column(db.Numeric(10, 2), nullable=False)
    old_price_min       = db.Column(db.Numeric(10, 2), nullable=False)

    # Nouveaux prix demandés
    new_reference_price = db.Column(db.Numeric(10, 2), nullable=False)
    new_price_min       = db.Column(db.Numeric(10, 2), nullable=False)

    # Statut de la demande
    status = db.Column(db.String(50), default='pending', nullable=False)
    # 'pending': en attente de validation admin
    # 'approved': approuvé par admin, prix mis à jour
    # 'rejected': refusé par admin

    # Dates et traçabilité
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)  # Date d'approbation/rejet
    processed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Admin qui a traité

    # Relations
    engineer = db.relationship('User', foreign_keys=[engineer_id], backref='price_change_requests')
    admin_processor = db.relationship('User', foreign_keys=[processed_by])

    def __repr__(self):
        return f"<PriceChangeRequest #{self.id} - Engineer#{self.engineer_id} - {self.status}>"


class Favorite(db.Model):
    """Tracks mis en favoris par les utilisateurs"""
    __tablename__ = 'favorite'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Relations
    user = db.relationship('User', backref='favorites')
    track = db.relationship('Track', backref='favorited_by')

    # Contrainte unique: un user ne peut favoriser qu'une seule fois un track
    __table_args__ = (db.UniqueConstraint('user_id', 'track_id', name='unique_user_track_favorite'),)

    def __repr__(self):
        return f"<Favorite User#{self.user_id} - Track#{self.track_id}>"


class ListeningHistory(db.Model):
    """Historique des 10 derniers tracks écoutés par utilisateur"""
    __tablename__ = 'listening_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    listened_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Relations
    user = db.relationship('User', backref='listening_history')
    track = db.relationship('Track', backref='listened_by')

    def __repr__(self):
        return f"<ListeningHistory User#{self.user_id} - Track#{self.track_id} at {self.listened_at}>"
    
class ListenEvent(db.Model):
    """Événement d'écoute enrichi pour l'algorithme de recommandation."""
    __tablename__ = 'listen_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    duration_listened = db.Column(db.Float, nullable=False)   # secondes
    track_duration = db.Column(db.Float, nullable=False)      # secondes
    completion_ratio = db.Column(db.Float, nullable=False)    # 0.0–1.0
    source = db.Column(db.String(32), default='home')         # 'home', 'search', 'profile'
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref='listen_events')
    track = db.relationship('Track', backref='listen_events')

    __table_args__ = (
        db.Index('ix_listen_event_user', 'user_id'),
        db.Index('ix_listen_event_track', 'track_id'),
        db.Index('ix_listen_event_user_created', 'user_id', 'created_at'),
    )

    def __repr__(self):
        return f"<ListenEvent User#{self.user_id} Track#{self.track_id} {self.completion_ratio:.0%}>"


class TrackView(db.Model):
    """Impression de vue sur un track (player ou page détail).
    user_id nullable → vues anonymes. ip_hash pour dédupliquer les vues uniques."""
    __tablename__ = 'track_view'

    id       = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id', ondelete='CASCADE'), nullable=False)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    ip_hash  = db.Column(db.String(64), nullable=False)   # SHA-256 tronqué de l'IP
    source   = db.Column(db.String(32), nullable=False, default='player')  # 'player' | 'detail'
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    track = db.relationship('Track', backref='views')
    user  = db.relationship('User',  backref='track_views')

    __table_args__ = (
        db.Index('ix_track_view_track',   'track_id'),
        db.Index('ix_track_view_user',    'user_id'),
        db.Index('ix_track_view_ip_date', 'track_id', 'ip_hash', 'created_at'),
    )

    def __repr__(self):
        return f"<TrackView Track#{self.track_id} source={self.source}>"


class Notification(db.Model):
    """Rappel des 'nouvelles entrées' pour l'utilisateur
    en particulier pour ce qui concerne les ventes & achats"""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Type de notification (pour icônes/style frontend)
    type = db.Column(db.String(50), nullable=False)
    # Types possibles:
    # - 'purchase' : Achat confirmé
    # - 'sale' : Vente d'un de vos tracks
    # - 'track_approved' : Track approuvé par admin
    # - 'track_rejected' : Track refusé
    # - 'mixmaster_request' : Nouvelle demande de mixage (engineer)
    # - 'mixmaster_status' : Changement de statut (artist)
    # - 'tokens_recharged' : Tokens rechargés
    # - 'topline_submitted' : Topline soumise sur votre track (beatmaker)
    # - 'system' : Notification système

    # Content
    title = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(300), nullable=True)

    # Metadata
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    #Relation
    recipient_user=db.relationship('User', back_populates='notifications', lazy=True)

    __table_args__ = (
        db.Index('idx_user_unread', 'user_id', 'is_read'),
        db.Index('idx_user_created', 'user_id', 'created_at'),
    )

    def mark_as_read(self):
        """Marquer la notification comme lue"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.now()

    def __repr__(self):
        return f"<Notification #{self.id} - {self.type} for User #{self.user_id}>"


# =============================================================================
# WALLET — Portefeuille interne (beatmakers & mix engineers)
# =============================================================================

class Wallet(db.Model):
    """Portefeuille interne par utilisateur. Un seul wallet par user."""
    __tablename__ = 'wallet'

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)

    # Soldes en Numeric pour la précision financière (pas de float)
    balance_available = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    balance_pending   = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    # Relations
    user = db.relationship('User', backref=db.backref('wallet', uselist=False, lazy='select'))
    transactions = db.relationship(
        'WalletTransaction', backref='wallet',
        lazy='dynamic', cascade='all, delete-orphan'
    )

    __table_args__ = (
        CheckConstraint('balance_available >= 0', name='ck_wallet_available_non_negative'),
        CheckConstraint('balance_pending >= 0',   name='ck_wallet_pending_non_negative'),
    )

    def __repr__(self):
        return f"<Wallet User#{self.user_id} avail={self.balance_available} pend={self.balance_pending}>"


class WalletTransaction(db.Model):
    """
    Enregistrement de chaque mouvement dans le wallet.

    type    : 'credit_beat_sale' | 'credit_mixmaster_deposit' | 'credit_mixmaster_final'
              | 'withdrawal' | 'expiration'
    status  : 'pending' → 'available' (après 7j) → 'transferred' (après retrait)
              ou 'expired' (après 2 ans sans retrait)
    """
    __tablename__ = 'wallet_transaction'

    id        = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallet.id'), nullable=False)

    type   = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')

    # Date à partir de laquelle le crédit devient retirable (pending → available)
    available_at = db.Column(db.DateTime, nullable=True)

    # Liens optionnels vers la source de la transaction
    purchase_id          = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=True)
    mixmaster_request_id = db.Column(db.Integer, db.ForeignKey('mixmaster_request.id'), nullable=True)

    # Rempli quand le retrait est effectué (stripe.Transfer.id)
    stripe_transfer_id = db.Column(db.String(200), nullable=True)

    description = db.Column(db.String(500), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Relations
    purchase          = db.relationship('Purchase', backref='wallet_transactions', lazy='select')
    mixmaster_request = db.relationship('MixMasterRequest', backref='wallet_transactions', lazy='select')

    __table_args__ = (
        CheckConstraint('amount > 0', name='ck_wallet_transaction_amount_positive'),
        db.Index('idx_wallet_txn_wallet_id', 'wallet_id'),
        db.Index('idx_wallet_txn_status_available_at', 'status', 'available_at'),
        db.Index('idx_wallet_txn_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<WalletTransaction #{self.id} type={self.type} amount={self.amount} status={self.status}>"


class TokenBlocklist(db.Model):
    """Tokens JWT révoqués (logout). Nettoyage périodique via APScheduler."""
    __tablename__ = 'token_blocklist'

    id         = db.Column(db.Integer, primary_key=True)
    jti        = db.Column(db.String(36), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def __repr__(self):
        return f"<TokenBlocklist jti={self.jti}>"


# =============================================================================
# CONTRACT BUILDER — Générateur de contrats d'exploitation musicale
# =============================================================================

class ClauseTypeEnum(enum.Enum):
    text                = 'text'
    textarea            = 'textarea'
    number              = 'number'
    percentage          = 'percentage'
    toggle              = 'toggle'
    toggle_with_details = 'toggle_with_details'
    select              = 'select'
    date                = 'date'
    date_range          = 'date_range'
    territory           = 'territory'
    duration            = 'duration'
    multi_toggle        = 'multi_toggle'


class UserContractStatus(enum.Enum):
    draft = 'draft'
    final = 'final'


class PartyTypeEnum(enum.Enum):
    physical = 'physical'
    company  = 'company'


class ContractClauseGroup(db.Model):
    """Groupes de clauses (sections) du contract builder, gérés par l'admin."""
    __tablename__ = 'contract_clause_group'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    tooltip     = db.Column(db.Text, nullable=True)
    sort_order  = db.Column(db.Integer, nullable=False, default=0)
    is_active   = db.Column(db.Boolean, nullable=False, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    clauses = db.relationship(
        'ContractClause', back_populates='group',
        order_by='ContractClause.sort_order',
        cascade='all, delete-orphan'
    )

    __table_args__ = (
        db.Index('idx_ccg_sort_order', 'sort_order'),
    )

    def __repr__(self):
        return f"<ContractClauseGroup #{self.id} '{self.name}'>"


class ContractClause(db.Model):
    """Clause individuelle configurable par l'admin."""
    __tablename__ = 'contract_clause'

    id                    = db.Column(db.Integer, primary_key=True)
    group_id              = db.Column(db.Integer, db.ForeignKey('contract_clause_group.id'), nullable=False)
    name                  = db.Column(db.String(200), nullable=False)
    description           = db.Column(db.Text, nullable=True)
    tooltip_short         = db.Column(db.String(300), nullable=True)
    tooltip_long          = db.Column(db.Text, nullable=True)
    clause_type           = db.Column(db.Enum(ClauseTypeEnum), nullable=False)
    options               = db.Column(db.JSON, nullable=True)
    default_value         = db.Column(db.JSON, nullable=True)
    is_required           = db.Column(db.Boolean, nullable=False, default=False)
    is_enabled_by_default = db.Column(db.Boolean, nullable=False, default=True)
    sort_order            = db.Column(db.Integer, nullable=False, default=0)
    is_active             = db.Column(db.Boolean, nullable=False, default=True)
    legal_reference       = db.Column(db.String(300), nullable=True)
    example_text          = db.Column(db.Text, nullable=True)
    tooltip_plain         = db.Column(db.Text, nullable=True)
    created_at            = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at            = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    group  = db.relationship('ContractClauseGroup', back_populates='clauses')
    values = db.relationship('UserContractValue', back_populates='clause', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_cc_group_sort', 'group_id', 'sort_order'),
    )

    def __repr__(self):
        return f"<ContractClause #{self.id} '{self.name}' ({self.clause_type.value})>"


class UserContract(db.Model):
    """Contrat d'exploitation créé par un utilisateur premium."""
    __tablename__ = 'user_contract'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    status     = db.Column(db.Enum(UserContractStatus), nullable=False, default=UserContractStatus.draft)
    pdf_file   = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    user    = db.relationship('User', backref='custom_contracts')
    parties = db.relationship(
        'UserContractParty', back_populates='contract',
        order_by='UserContractParty.sort_order',
        cascade='all, delete-orphan'
    )
    values  = db.relationship('UserContractValue', back_populates='contract', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_uc_user_id', 'user_id'),
    )

    def __repr__(self):
        return f"<UserContract #{self.id} '{self.title}' ({self.status.value})>"


class UserContractParty(db.Model):
    """Partie contractante (personne physique ou morale) liée à un UserContract."""
    __tablename__ = 'user_contract_party'

    id         = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('user_contract.id'), nullable=False)
    party_type = db.Column(db.Enum(PartyTypeEnum), nullable=False, default=PartyTypeEnum.physical)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    # Personne physique
    first_name     = db.Column(db.String(100), nullable=True)
    last_name      = db.Column(db.String(100), nullable=True)
    date_of_birth  = db.Column(db.String(20),  nullable=True)
    nationality    = db.Column(db.String(80),  nullable=True)
    pseudonym      = db.Column(db.String(100), nullable=True)
    tax_id         = db.Column(db.String(50),  nullable=True)

    # Personne morale
    company_name     = db.Column(db.String(200), nullable=True)
    legal_form       = db.Column(db.String(100), nullable=True)
    capital          = db.Column(db.String(80),  nullable=True)
    siren            = db.Column(db.String(20),  nullable=True)
    siret            = db.Column(db.String(25),  nullable=True)
    rcs              = db.Column(db.String(100), nullable=True)
    legal_rep        = db.Column(db.String(200), nullable=True)
    signatory_title  = db.Column(db.String(150), nullable=True)

    # Commun
    role    = db.Column(db.String(150), nullable=False)
    address = db.Column(db.Text, nullable=True)
    email   = db.Column(db.String(120), nullable=True)

    contract = db.relationship('UserContract', back_populates='parties')

    def __repr__(self):
        return f"<UserContractParty #{self.id} role='{self.role}' contract={self.contract_id}>"


class UserContractValue(db.Model):
    """Valeur saisie par l'utilisateur pour une clause de son contrat."""
    __tablename__ = 'user_contract_value'

    id          = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('user_contract.id'), nullable=False)
    clause_id   = db.Column(db.Integer, db.ForeignKey('contract_clause.id'), nullable=False)
    is_enabled  = db.Column(db.Boolean, nullable=False, default=True)
    value       = db.Column(db.JSON, nullable=True)

    contract = db.relationship('UserContract', back_populates='values')
    clause   = db.relationship('ContractClause', back_populates='values')

    __table_args__ = (
        db.UniqueConstraint('contract_id', 'clause_id', name='unique_contract_clause'),
        db.Index('idx_ucv_contract_id', 'contract_id'),
    )