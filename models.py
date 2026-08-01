import hashlib
import enum
from decimal import Decimal, ROUND_HALF_UP
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, time, timedelta
from sqlalchemy import CheckConstraint, and_, or_, func
from sqlalchemy.ext.hybrid import hybrid_property

from utils import plans

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

    # ── Consentement prospection commerciale (RGPD art. 6.1.a / L.34-5 CPCE) ──
    # FAUX par défaut, et c'est structurant : les campagnes des vendeurs sont de
    # la prospection commerciale. Sans acte positif de l'utilisateur, LaProd (le
    # responsable de traitement) est exposé, pas le vendeur qui appuie sur envoyer.
    # Aucun code ne doit lire l'email d'un user pour du marketing sans passer par
    # can_receive_marketing.
    marketing_opt_in    = db.Column(db.Boolean, default=False, nullable=False)
    marketing_opt_in_at = db.Column(db.DateTime, nullable=True)  # preuve horodatée du consentement

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
    is_producer = db.Column(db.Boolean, default=False, nullable=False)  # Producteur/label : gestion de contrats et de roster — auto-déclaré, sans certification (contrairement à is_mixmaster_engineer)

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

    # Token opaque d'abonnement au flux iCal du rétroplanning (planning_event).
    # Régénérable par l'utilisateur — pas de JWT/itsdangerous ici : Apple/Google
    # Calendar pollent l'URL indéfiniment sans header Authorization, il faut un
    # secret révocable dans l'URL elle-même, pas un token à expiration.
    ical_feed_token = db.Column(db.String(64), unique=True, nullable=True, index=True)

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

    # ── Éligibilité au mailing marketing ─────────────────────────────────────

    @hybrid_property
    def can_receive_marketing(self):
        """Seule porte d'entrée autorisée pour cibler un utilisateur en campagne.

        Exige le consentement ET un email vérifié : mailer une adresse non
        vérifiée, c'est envoyer sur une boîte qui n'appartient peut-être pas à
        l'utilisateur, et flinguer la réputation d'expédition du domaine au passage.
        """
        return bool(self.marketing_opt_in) and bool(self.email_verified)

    @can_receive_marketing.expression
    def can_receive_marketing(cls):
        return and_(cls.marketing_opt_in.is_(True), cls.email_verified.is_(True))

    # Premium status check

    @property
    def is_premium_active(self):
        """True si un abonnement payant est en cours (non expiré), quel que soit
        le palier. Ne dit RIEN du niveau : utiliser has_plan_at_least() pour ça."""
        if plans.normalize(self.subscription_plan) == plans.FREE:
            return False
        return self.premium_expires_at is None or self.premium_expires_at >= datetime.now()

    @hybrid_property
    def is_premium(self):
        """Rétrocompatibilité — True si is_premium_active."""
        return self.is_premium_active

    @is_premium.expression
    def is_premium(cls):
        # Volontairement « != free » plutôt qu'une liste de paliers : la requête
        # reste juste quel que soit le nombre de paliers payants ajoutés ensuite.
        return and_(
            cls.subscription_plan != plans.FREE,
            or_(cls.premium_expires_at.is_(None), cls.premium_expires_at >= func.now())
        )

    # ── Capacités dérivées du palier ─────────────────────────────────────────
    # Aucun code métier ne doit comparer subscription_plan à une chaîne : on
    # interroge ces propriétés. Ajouter un palier ne casse alors aucun appelant.

    @property
    def plan(self):
        """Palier canonique (les anciens identifiants sont normalisés)."""
        return plans.normalize(self.subscription_plan)

    def has_plan_at_least(self, minimum) -> bool:
        """Le palier ACTIF est-il au moins `minimum` ? Un abonnement expiré
        retombe à FREE : payer hier ne donne pas de droits aujourd'hui."""
        if not self.is_premium_active:
            return plans.plan_rank(plans.FREE) >= plans.plan_rank(minimum)
        return plans.plan_rank(self.plan) >= plans.plan_rank(minimum)

    @property
    def is_pro(self):
        """Rétrocompatibilité — True si Pro Structuré actif.

        Conservé parce que le contract builder l'utilise déjà partout ; sa
        sémantique (« accès total au contract builder ») reste exacte.
        """
        return self.has_plan_at_least(plans.PRO_STRUCTURE)

    @property
    def can_set_custom_prices(self):
        """Fixer soi-même le prix de chaque droit de ses beats. Premium et +."""
        return self.has_plan_at_least(plans.PREMIUM)

    @property
    def can_offer_exclusive(self):
        """PROPOSER ses beats en exclusivité. Premium et +.

        Côté VENDEUR, jamais côté acheteur : le premium outille celui qui vend,
        il ne dresse pas un péage devant celui qui achète — l'exclusivité est la
        vente la plus chère du site, y mettre un abonnement en obstacle tuerait
        des ventes.
        """
        return self.has_plan_at_least(plans.PREMIUM)

    @property
    def can_use_contract_builder(self):
        """Accès au contract builder (limité en Semi-Pro, total en Pro Structuré)."""
        return self.contract_quota != 0

    @property
    def contract_quota(self):
        """Contrats générables par mois. None = illimité, 0 = aucun accès."""
        if not self.is_premium_active:
            return plans.get(plans.FREE).contract_quota
        return plans.get(self.plan).contract_quota

    @property
    def can_do_mastering(self):
        """Certifié master par admin OU palier Semi-Pro et plus.

        C'est le « badge Mastering Pro » : il atteste d'un abonnement, pas d'une
        validation d'échantillon par un admin — les deux voies coexistent.
        """
        return self.is_certified_master_engineer or self.has_plan_at_least(plans.SEMI_PRO)

    @property
    def can_use_management_contract(self):
        """Contrat de management formel (mandat, commission, exclusivité). Premium et +.

        Le lien roster et le rétroplanning partagé (RosterLink/PlanningEvent) ne
        dépendent eux que du rôle is_producer/is_artist, pas du palier — seule la
        formalisation juridique/financière est réservée aux abonnés.
        """
        return self.has_plan_at_least(plans.PREMIUM)

    @property
    def can_view_royalties(self):
        """Cap-table / splits chiffrés par titre. Premium et +, même seuil que
        can_use_management_contract."""
        return self.has_plan_at_least(plans.PREMIUM)


    # TRACKS ALLOW UPLOAD METHODS


    @property
    def _active_plan(self):
        """Le palier qui s'applique RÉELLEMENT (FREE si l'abonnement a expiré)."""
        return plans.get(self.plan if self.is_premium_active else plans.FREE)

    @property
    def uploads_per_day(self):
        """Nouveaux beats publiables par jour au palier actif. Le catalogue total
        en ligne, lui, n'est jamais plafonné."""
        return self._active_plan.uploads_per_day

    def _reset_daily_uploads(self):
        """Réinitialise les tokens d'upload quotidiennement si nécessaire.

        Les plafonds viennent de utils/plans.py : les recopier ici garantirait
        qu'ils divergent de la grille affichée à l'utilisateur le jour où on
        ajuste un palier.
        """
        today = date.today()
        if self.last_upload_reset < today:
            plan = self._active_plan
            if self.upload_track_tokens < plan.upload_cap:
                self.upload_track_tokens = min(
                    plan.upload_cap, self.upload_track_tokens + plan.upload_gain,
                )
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

        plan = self._active_plan
        if self.is_premium_active:
            return False, f"Plus de tokens. Recharge demain (+{plan.upload_gain} tokens)."
        return False, (
            f"Plus de tokens. Recharge demain (+{plan.upload_gain} token) "
            f"ou passez LaProd+."
        )

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
        """Monte immédiatement les tokens au plafond du palier (activation/renouvellement).

        Un abonné qui paie doit disposer de ses crédits tout de suite, pas attendre
        le reset de minuit — sinon il a payé pour rien pendant une journée.
        """
        today = date.today()
        plan = self._active_plan
        if self.upload_track_tokens < plan.upload_cap:
            self.upload_track_tokens = plan.upload_cap
            self.last_upload_reset = today
        if self.topline_tokens < plan.topline_cap:
            self.topline_tokens = plan.topline_cap
            self.last_topline_reset = today

    # TOPLINE ALLOW UPLOAD METHODS

    def _reset_weekly_toplines(self):
        """Réinitialise les tokens de toplines chaque semaine (plafonds : utils/plans.py)."""
        today = date.today()
        if self.last_topline_reset + timedelta(days=7) <= today:
            plan = self._active_plan
            if self.topline_tokens < plan.topline_cap:
                self.topline_tokens = min(
                    plan.topline_cap, self.topline_tokens + plan.topline_gain,
                )
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
    tags = db.relationship('Tag', back_populates='category_obj', cascade='all, delete-orphan')

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


class SimilarArtist(db.Model):
    """Artiste de référence — liste gérée par l'admin, associée aux tracks par les beatmakers."""
    __tablename__ = 'similar_artist'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(64), unique=True, nullable=False)
    scene      = db.Column(db.String(32), nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    def __repr__(self):
        return f'<SimilarArtist {self.name}>'


# Table association N:M entre Track et SimilarArtist
track_similar_artist = db.Table('track_similar_artist',
    db.Column('track_id',  db.Integer, db.ForeignKey('track.id',          ondelete='CASCADE'), primary_key=True),
    db.Column('artist_id', db.Integer, db.ForeignKey('similar_artist.id', ondelete='CASCADE'), primary_key=True),
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

    # ── Attestations légales (droits voisins / samples) ──────────────────────
    # phonogram_producer_attested : le compositeur atteste être producteur du
    # phonogramme (CPI L.213-1) sur le fichier fourni (ou détenir les droits
    # nécessaires) — condition posée à l'upload pour pouvoir céder ces droits
    # dans le contrat de licence (cf. utils/contract_generator.py).
    phonogram_producer_attested = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    has_third_party_samples     = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    sample_clearance_details    = db.Column(db.Text, nullable=True)

    # Exclusivité vendue
    is_exclusive_sold  = db.Column(db.Boolean, default=False, nullable=False)
    exclusive_sold_at  = db.Column(db.DateTime, nullable=True)
    exclusive_buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relations
    tags             = db.relationship('Tag',           secondary='track_tag',          backref='tracks')
    similar_artists  = db.relationship('SimilarArtist', secondary='track_similar_artist', backref='tracks')
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
        db.Index('idx_track_home', 'is_approved', 'is_exclusive_sold', 'created_at'),
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
    artist_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)   # nullable : guest
    guest_session_id = db.Column(db.String(36), nullable=True, index=True)       # UUID localStorage guest
    guest_expires_at = db.Column(db.DateTime, nullable=True)                     # TTL 24h pour purge

    audio_file = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    is_mobile_processed = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        name = self.artist_user.username if self.artist_id else f"guest:{self.guest_session_id}"
        return f"<Topline by {name} on Track#{self.track_id}>"


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

    #  REMISE (promo code du vendeur)
    # price_paid reste le montant RÉELLEMENT encaissé : platform_fee et
    # composer_revenue en découlent, la commission ne porte donc jamais sur la
    # remise. gross_price garde le prix catalogue pour la réconciliation.
    promo_code_id   = db.Column(db.Integer, db.ForeignKey('promo_code.id', ondelete='SET NULL'), nullable=True)
    gross_price     = db.Column(db.Numeric(10, 2), nullable=True)                        # prix avant remise
    discount_amount = db.Column(db.Numeric(10, 2), default=Decimal('0'), nullable=False) # remise accordée

    # Stripe
    stripe_payment_intent_id = db.Column(db.String(200), unique=True, nullable=False)
    stripe_transfer_id = db.Column(db.String(200), nullable=True)  # ID du transfert au compositeur

    # Contrat généré
    contract_file = db.Column(db.String(200), nullable=True)

    # ── LIFECYCLE DE LICENCE (ajouté v2) ────────────────────────────────────
    is_exclusive   = db.Column(db.Boolean, default=False, nullable=False)
    duration_years = db.Column(db.Integer, nullable=True)        # 3 | 5 | 10 | None (lifetime/streaming)
    is_lifetime    = db.Column(db.Boolean, default=False, nullable=False)
    territory      = db.Column(db.String(100), nullable=True)
    expires_at     = db.Column(db.DateTime, nullable=True)       # None si lifetime ou streaming seul
    license_status = db.Column(db.String(50), default='active', nullable=False)
                     # 'active' | 'expired' | 'renewed' | 'cancelled'

    # Auto-référence pour les renouvellements
    renewed_from_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=True)
    renewed_to_id   = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=True)

    renewed_from = db.relationship('Purchase', foreign_keys=[renewed_from_id], remote_side='Purchase.id',
                                   backref=db.backref('renewed_to_purchase', uselist=False))

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        CheckConstraint('price_paid >= 0', name='ck_purchase_price_positive'),
        CheckConstraint('platform_fee >= 0', name='ck_purchase_fee_positive'),
        CheckConstraint('composer_revenue >= 0', name='ck_purchase_revenue_positive'),
        db.Index('idx_purchase_license_status', 'license_status'),
        db.Index('idx_purchase_buyer_track', 'buyer_id', 'track_id'),
    )

    def calculate_fees(self, total_amount, platform_commission=Decimal('0.10')):
        """Calcule la répartition des revenus.

        `total_amount` est le montant NET encaissé (remise déjà déduite) : la
        commission suit la transaction réelle, jamais le prix catalogue.
        """
        from utils.money import split_platform_fee
        self.platform_fee, self.composer_revenue = split_platform_fee(total_amount, platform_commission)
    
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
    percentage = db.Column(db.Integer, nullable=False)

    signature_place = db.Column(db.String(200), nullable=True)
    signature_date = db.Column(db.String(200), nullable=True)

    contract_file = db.Column(db.String(200), nullable=True)

    # ── LIFECYCLE (ajouté v2) ────────────────────────────────────────────────
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=True)
    status      = db.Column(db.String(50), default='active', nullable=False)
                  # 'active' | 'expired' | 'renewed' | 'cancelled'

    # ── Conformité légale (ajouté v3) ────────────────────────────────────────
    # Snapshot, au moment de la vente, des attestations du Track (cf. plus haut) :
    # figées ici pour que l'édition ultérieure du Track ne réécrive pas
    # rétroactivement ce qui a été représenté à l'acheteur au moment de l'achat.
    phonogram_producer_attested = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    has_third_party_samples     = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    sample_clearance_details    = db.Column(db.Text, nullable=True)

    # Déclaration de l'acheteur au moment de l'achat : a-t-il écrit des paroles
    # originales sur ce titre ? Conditionne la présentation de la répartition
    # SACEM dans le contrat (cf. utils/contract_generator.py) — par défaut,
    # non déclaré = traité comme non-auteur (droits voisins d'artiste-interprète
    # hors périmètre de ce contrat), jamais l'inverse.
    buyer_declares_original_lyrics = db.Column(db.Boolean, default=False, nullable=False, server_default='false')

    # Preuve de consentement (RGPD / art. L.221-28 13° C. conso) : posées
    # côté serveur au moment de la création du Contract, jamais fournies
    # telles quelles par le client — cf. utils/contract_data_builder.py.
    legal_terms_accepted    = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    withdrawal_right_waived = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    consent_recorded_at     = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # Relations
    track    = db.relationship('Track', foreign_keys=[track_id], backref='contracts')
    composer = db.relationship('User', foreign_keys=[composer_id], backref='signed_composer_contracts')
    client   = db.relationship('User', foreign_keys=[client_id], backref='signed_client_contracts')
    purchase = db.relationship('Purchase', foreign_keys=[purchase_id], backref=db.backref('contract', uselist=False))

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

    #  REMISE (promo code de l'ingénieur)
    # total_price est le montant NET (remise déduite). Tous les calculs dérivés
    # — acompte 30 %, transferts de révision, remboursements — partent de
    # total_price et restent donc cohérents avec ce qui a été autorisé chez Stripe.
    promo_code_id   = db.Column(db.Integer, db.ForeignKey('promo_code.id', ondelete='SET NULL'), nullable=True)
    gross_price     = db.Column(db.Numeric(10, 2), nullable=True)                        # prix avant remise
    discount_amount = db.Column(db.Numeric(10, 2), default=Decimal('0'), nullable=False) # remise accordée

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
        from utils.money import to_money, split_platform_fee
        total = to_money(self.total_price)
        self.deposit_amount   = to_money(total * Decimal('0.30'))
        self.remaining_amount = to_money(total - self.deposit_amount)
        self.platform_fee, self.engineer_revenue = split_platform_fee(total, platform_commission)

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


class EngineerView(db.Model):
    """Impression de vue sur la page de commande d'un ingénieur mix/master.

    Miroir de TrackView, côté prestation : c'est l'équivalent d'une vue de fiche
    produit pour un ingénieur. user_id nullable → vues anonymes. ip_hash pour
    dédupliquer les vues uniques (même règle 24h que les tracks).
    """
    __tablename__ = 'engineer_view'

    id          = db.Column(db.Integer, primary_key=True)
    engineer_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    ip_hash     = db.Column(db.String(64), nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.now, nullable=False)

    engineer = db.relationship('User', foreign_keys=[engineer_id], backref='engineer_views')
    viewer   = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.Index('ix_engineer_view_engineer', 'engineer_id'),
        db.Index('ix_engineer_view_ip_date',  'engineer_id', 'ip_hash', 'created_at'),
    )

    def __repr__(self):
        return f"<EngineerView Engineer#{self.engineer_id}>"


class LoginEvent(db.Model):
    """Une connexion authentifiée par utilisateur et par JOUR calendaire.

    Sert uniquement à mesurer la régularité de connexion (admin) — ni IP, ni
    device : le strict minimum pour la stat demandée.

    Pourquoi dédupliquer par jour plutôt que d'enregistrer chaque événement brut :
    /refresh est appelé à la fois PROACTIVEMENT (timer JS toutes les ~55 min tant
    qu'un onglet reste ouvert) et RÉACTIVEMENT (intercepteur 401 quand l'utilisateur
    revient après une absence, avec un access token expiré mais un refresh token
    encore valide jusqu'à 30 jours en mode « se souvenir de moi »). Cette seconde
    voie est en pratique le principal canal de retour d'un utilisateur — un compte
    « remember me » peut ne plus jamais retoucher /login pendant des semaines. Sans
    dédup, un onglet resté ouvert toute une journée gonflerait indéfiniment le
    compteur ; avec dédup au jour, on obtient exactement ce qu'on veut mesurer :
    « sur combien de jours distincts cet utilisateur s'est-il présenté ? ».
    """
    __tablename__ = 'login_event'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    login_date = db.Column(db.Date, nullable=False)   # jour calendaire (clé de dédup)
    source     = db.Column(db.String(20), nullable=False)  # 'password' | 'oauth' | 'refresh'
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    # cascade='all, delete-orphan' (côté COLLECTION User.login_events, via
    # db.backref) : SQLAlchemy supprime lui-même les login_event d'un user AVANT
    # de le supprimer, au lieu de tenter par défaut un UPDATE ... SET user_id=NULL
    # qui échouerait (colonne NOT NULL). Géré au niveau ORM plutôt que délégué au
    # ON DELETE CASCADE de la base : ça marche identiquement quel que soit le
    # moteur (le test suite tourne sur SQLite, qui n'applique ses contraintes FK
    # que si PRAGMA foreign_keys=ON — jamais activé ici — donc s'appuyer sur le
    # seul niveau DB laisserait des lignes orphelines derrière chaque suppression
    # de test). Sans incidence en prod : le RGPD anonymise les User en place et
    # ne les DELETE jamais réellement.
    user = db.relationship('User', backref=db.backref('login_events', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'login_date', name='uq_login_event_user_day'),
        db.Index('ix_login_event_date', 'login_date'),
    )

    @classmethod
    def record(cls, user_id, source):
        """Enregistre une connexion pour aujourd'hui, si pas déjà fait.

        Ne DOIT jamais faire échouer le flux d'authentification appelant : toute
        erreur est avalée après rollback. Un stat manquée n'est jamais aussi grave
        qu'un login cassé par une table d'analytics.
        """
        try:
            today = date.today()
            exists = db.session.query(cls.id).filter_by(
                user_id=user_id, login_date=today,
            ).first()
            if exists:
                return False
            db.session.add(cls(user_id=user_id, login_date=today, source=source))
            db.session.commit()
            return True
        except Exception:
            # Course entre deux requêtes concurrentes sur la même contrainte
            # unique (double onglet, double clic) — ou tout autre souci : on
            # annule proprement et on continue, l'auth ne doit rien en savoir.
            db.session.rollback()
            return False

    def __repr__(self):
        return f"<LoginEvent user={self.user_id} date={self.login_date} source={self.source}>"


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
    # - 'mix_sample_pending' : Rappel de soumission de preview (mix/master engineer)
    # - 'roster_invite' : Invitation à rejoindre un roster (artiste invité)
    # - 'roster_accepted' : Invitation roster acceptée (producteur)
    # - 'roster_declined' : Invitation roster déclinée (producteur)
    # - 'roster_revoked' : Lien roster révoqué (l'autre partie)
    # - 'roster_ended' : Lien roster quitté (l'autre partie)
    # - 'planning_event_created' : Nouvel événement de rétroplanning (l'autre partie)
    # - 'planning_event_confirmed' : Événement confirmé (le créateur)
    # - 'planning_event_cancelled' : Événement annulé (l'autre partie)
    # - 'contract_signature_requested' : Invitation à signer un contrat (destinataire)
    # - 'contract_signed' : Une partie a signé le contrat (propriétaire)
    # - 'contract_fully_executed' : Toutes les parties invitées ont signé (propriétaire)
    # - 'contract_declined' : Signature refusée (propriétaire)
    # - 'contract_invite_cancelled' : Invitation à signer annulée (destinataire)
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
# ROSTER — Lien mutuel producteur ↔ artiste
# =============================================================================

class RosterLinkStatus(enum.Enum):
    invited  = 'invited'   # invitation envoyée, en attente de réponse
    active   = 'active'    # les deux parties sont liées
    declined = 'declined'  # l'invité a refusé
    revoked  = 'revoked'   # invitation annulée avant acceptation, ou lien actif révoqué
    ended    = 'ended'     # l'une des deux parties a quitté un lien actif


class RosterLink(db.Model):
    """Lien mutuel producteur↔artiste : invitation puis acceptation explicite,
    jamais automatique. Aucun contrat requis pour être actif — sert de socle au
    rétroplanning partagé (PlanningEvent) et, plus tard, à un contrat de
    management optionnel (management_contract_id), attachable sur un lien déjà
    actif.

    Unicité stricte sur (producer_id, artist_id) : un couple n'a qu'une seule
    ligne dans le temps. Décliner/révoquer/quitter ne supprime pas la ligne,
    elle change de statut ; une ré-invitation ultérieure réutilise la même
    ligne plutôt que d'en créer une nouvelle.
    """
    __tablename__ = 'roster_link'

    id            = db.Column(db.Integer, primary_key=True)
    producer_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    artist_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status        = db.Column(db.Enum(RosterLinkStatus), nullable=False, default=RosterLinkStatus.invited)
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Contrat de management optionnel, attaché plus tard sur un lien déjà actif.
    # Nullable : le lien roster reste valide sans jamais être formalisé.
    management_contract_id = db.Column(db.Integer, db.ForeignKey('user_contract.id'), nullable=True)

    created_at   = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at   = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    responded_at = db.Column(db.DateTime, nullable=True)   # accept / decline
    ended_at     = db.Column(db.DateTime, nullable=True)   # revoke / quitter

    producer = db.relationship(
        'User', foreign_keys=[producer_id],
        backref=db.backref('roster_as_producer', cascade='all, delete-orphan', lazy=True),
    )
    artist = db.relationship(
        'User', foreign_keys=[artist_id],
        backref=db.backref('roster_as_artist', cascade='all, delete-orphan', lazy=True),
    )
    invited_by = db.relationship('User', foreign_keys=[invited_by_id])
    management_contract = db.relationship('UserContract')

    __table_args__ = (
        db.UniqueConstraint('producer_id', 'artist_id', name='uq_roster_link_pair'),
        db.Index('idx_roster_producer_status', 'producer_id', 'status'),
        db.Index('idx_roster_artist_status', 'artist_id', 'status'),
    )

    def __repr__(self):
        return f"<RosterLink #{self.id} producer={self.producer_id} artist={self.artist_id} ({self.status.value})>"


# =============================================================================
# PLANNING — Rétroplanning partagé sur un lien roster actif
# =============================================================================

class PlanningEventTypeEnum(enum.Enum):
    recording_session    = 'recording_session'     # session d'enregistrement
    writing_session       = 'writing_session'        # session d'écriture / topline
    rehearsal              = 'rehearsal'               # répétition
    concert                  = 'concert'                 # concert / date de tournée
    showcase                   = 'showcase'                # showcase pro (label, diffuseur)
    residency                    = 'residency'               # résidence artistique
    video_shoot                    = 'video_shoot'             # tournage clip
    media_interview                   = 'media_interview'        # interview média / promo
    meeting                              = 'meeting'                # réunion (label, équipe)
    appointment                            = 'appointment'           # rendez-vous générique
    sacem_deposit                             = 'sacem_deposit'        # dépôt SACEM / déclaration d'œuvre
    contractual_deadline                        = 'contractual_deadline'  # échéance contractuelle
    release                                        = 'release'              # date de sortie / mise en ligne
    other                                             = 'other'


class PlanningEventStatus(enum.Enum):
    proposed  = 'proposed'
    confirmed = 'confirmed'
    cancelled = 'cancelled'


class PlanningEvent(db.Model):
    """Événement du rétroplanning — partagé sur un RosterLink actif, OU
    personnel (roster_link_id NULL) si l'utilisateur n'a besoin de personne
    d'autre pour se construire un calendrier. Un événement personnel est
    confirmé dès sa création (aucune autre partie à convaincre) et n'est
    visible que par son créateur — cf. _can_act_on_event dans planning_api.py."""
    __tablename__ = 'planning_event'

    id             = db.Column(db.Integer, primary_key=True)
    roster_link_id = db.Column(db.Integer, db.ForeignKey('roster_link.id'), nullable=True)
    created_by_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    event_type  = db.Column(db.Enum(PlanningEventTypeEnum), nullable=False, default=PlanningEventTypeEnum.other)
    status      = db.Column(db.Enum(PlanningEventStatus), nullable=False, default=PlanningEventStatus.proposed)

    # Convention du projet : datetime naïf partout (cf. User.created_at...). On
    # garde ce style plutôt qu'introduire une première colonne tz-aware isolée,
    # et on ajoute `timezone` (nom IANA) pour l'affichage et la génération .ics.
    start_at = db.Column(db.DateTime, nullable=False)
    end_at   = db.Column(db.DateTime, nullable=True)
    timezone = db.Column(db.String(50), nullable=False, default='Europe/Paris')
    all_day  = db.Column(db.Boolean, nullable=False, default=False)

    location = db.Column(db.String(300), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    roster_link = db.relationship(
        'RosterLink',
        backref=db.backref('planning_events', cascade='all, delete-orphan', lazy=True),
    )
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (
        db.Index('idx_planning_roster_start', 'roster_link_id', 'start_at'),
        CheckConstraint('end_at IS NULL OR end_at >= start_at', name='ck_planning_event_end_after_start'),
    )

    def __repr__(self):
        return f"<PlanningEvent #{self.id} '{self.title}' roster_link={self.roster_link_id} ({self.status.value})>"


# =============================================================================
# ROYALTIES — Cap-table déclarative par titre
# =============================================================================

class TrackSplitRole(enum.Enum):
    topliner     = 'topliner'
    beatmaker    = 'beatmaker'
    mix_engineer = 'mix_engineer'
    label        = 'label'
    producer     = 'producer'
    other        = 'other'


class TrackSplitStatus(enum.Enum):
    declared  = 'declared'    # ajouté par un intervenant, pas encore confirmé par le titulaire de la part
    confirmed = 'confirmed'   # confirmé par le titulaire de la part


class TrackSplit(db.Model):
    """Cap-table déclarative d'un titre : qui possède quel pourcentage, à quel
    titre (topliner, beatmaker, ingé, label, producteur). Purement traçable —
    aucun paiement automatisé (l'intégration Wallet pour un reversement
    automatique est une piste future distincte, hors scope)."""
    __tablename__ = 'track_split'

    id       = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    # Nom affiché, toujours renseigné par la route (même pour une part liée à
    # un compte) : la cap-table doit rester lisible et valide même si le
    # compte lié est supprimé plus tard — même logique que les snapshots
    # composer_address/composer_email sur Contract.
    external_name = db.Column(db.String(200), nullable=False)
    role          = db.Column(db.Enum(TrackSplitRole), nullable=False)
    percentage    = db.Column(db.Numeric(5, 2), nullable=False)
    status        = db.Column(db.Enum(TrackSplitStatus), nullable=False, default=TrackSplitStatus.declared)

    # Qui a ajouté la ligne. Nullable et sans cascade : si ce compte est
    # supprimé plus tard, la ligne (qui décrit les droits d'un AUTRE
    # intervenant) doit survivre — seule la traçabilité de l'auteur se perd.
    added_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    track = db.relationship(
        'Track', backref=db.backref('splits', cascade='all, delete-orphan', lazy=True),
    )
    user     = db.relationship('User', foreign_keys=[user_id])
    added_by = db.relationship('User', foreign_keys=[added_by_id])

    __table_args__ = (
        CheckConstraint('percentage > 0 AND percentage <= 100', name='ck_track_split_percentage_range'),
        db.Index('idx_track_split_track', 'track_id'),
    )

    def __repr__(self):
        return f"<TrackSplit #{self.id} track={self.track_id} role={self.role.value} {self.percentage}%>"


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


class ContractTemplateTypeEnum(enum.Enum):
    """Famille de contrat du builder : exploitation d'œuvre, représentation (live)
    ou mandat de management (add-on optionnel sur un RosterLink actif)."""
    exploitation = 'exploitation'
    performance  = 'performance'
    management   = 'management'


class PartyTypeEnum(enum.Enum):
    physical = 'physical'
    company  = 'company'


class PartyInviteStatus(enum.Enum):
    """État de l'invitation à signer d'une partie de contrat, indépendant du
    statut brouillon/final du contrat lui-même."""
    none     = 'none'
    pending  = 'pending'
    signed   = 'signed'
    declined = 'declined'


class ContractSignatureStatus(enum.Enum):
    """Agrégat de signature au niveau du contrat, recalculé à chaque
    invite/cancel/sign/decline (voir _recompute_signature_status). Ne reflète
    que les parties invitées numériquement — les autres continuent de signer
    hors app (papier), ce qui n'empêche jamais ce statut d'atteindre 'signed'."""
    not_sent = 'not_sent'
    pending  = 'pending'
    declined = 'declined'
    signed   = 'signed'


class ContractClauseGroup(db.Model):
    """Groupes de clauses (sections) du contract builder, gérés par l'admin."""
    __tablename__ = 'contract_clause_group'

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(150), nullable=False)
    contract_type = db.Column(db.Enum(ContractTemplateTypeEnum), nullable=False,
                              default=ContractTemplateTypeEnum.exploitation,
                              server_default='exploitation')
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

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title         = db.Column(db.String(200), nullable=False)
    contract_type = db.Column(db.Enum(ContractTemplateTypeEnum), nullable=False,
                              default=ContractTemplateTypeEnum.exploitation,
                              server_default='exploitation')
    status     = db.Column(db.Enum(UserContractStatus), nullable=False, default=UserContractStatus.draft)
    pdf_file   = db.Column(db.String(300), nullable=True)
    signature_status = db.Column(db.Enum(ContractSignatureStatus), nullable=False,
                                  default=ContractSignatureStatus.not_sent,
                                  server_default='not_sent')
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

    # Lien optionnel vers un compte LaProd réel (ex : contrat de management
    # généré depuis un RosterLink). Nullable pour ne rien changer aux contrats
    # existants ni aux parties externes sans compte (éditeur, distributeur...).
    linked_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Lien optionnel vers la Structure (identité légale B2B) du user courant,
    # utilisé uniquement pour pré-remplir les champs société à la création de
    # la partie — un instantané est copié dans les colonnes ci-dessus, ce champ
    # ne sert qu'à la traçabilité/au pré-remplissage du prochain contrat, jamais
    # à une lecture live (un contrat signé ne doit pas bouger si la structure
    # change d'adresse ensuite).
    linked_structure_id = db.Column(db.Integer, db.ForeignKey('structure.id'), nullable=True)

    # Invitation à signer en ligne. `invited_by_id` est toujours le propriétaire
    # du contrat (audit), `linked_user_id` ci-dessus devient le compte du
    # signataire une fois résolu (recherche pseudo/email ou clic sur le lien
    # email pour un non-inscrit — voir routes/contract_builder_api.py).
    invite_status     = db.Column(db.Enum(PartyInviteStatus), nullable=False,
                                   default=PartyInviteStatus.none, server_default='none')
    invited_at        = db.Column(db.DateTime, nullable=True)
    invited_by_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    signed_at         = db.Column(db.DateTime, nullable=True)
    signature_name    = db.Column(db.String(200), nullable=True)
    # Jamais exposée au frontend (cf. _party_dto) : preuve technique interne.
    signature_ip      = db.Column(db.String(45), nullable=True)
    consent_confirmed = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    declined_at       = db.Column(db.DateTime, nullable=True)

    contract         = db.relationship('UserContract', back_populates='parties')
    linked_user      = db.relationship('User', foreign_keys=[linked_user_id])
    linked_structure = db.relationship('Structure', foreign_keys=[linked_structure_id])
    invited_by       = db.relationship('User', foreign_keys=[invited_by_id])

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


# =============================================================================
# STRUCTURE — Identité légale B2B (SMAC, labels, structures de management)
# =============================================================================

class Structure(db.Model):
    """Identité légale d'une structure B2B (SMAC, label, société de management)
    portée par un compte owner unique en v1 — pas de multi-sièges pour l'instant,
    voir StructureMembership en backlog. Réutilise exactement les mêmes noms de
    champs que la partie "personne morale" de UserContractParty pour rester
    cohérent avec ce qui existe déjà dans un contrat.

    owner_id est unique : un seul Structure par User en v1. Aucun cascade sur
    owner — la suppression d'un compte propriétaire d'une structure ne doit
    jamais être tranchée implicitement, cf. TrackSplit.added_by_id (traçabilité
    seule, pas de cascade).
    """
    __tablename__ = 'structure'

    id       = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)

    name            = db.Column(db.String(200), nullable=False)
    legal_form      = db.Column(db.String(100), nullable=True)
    capital         = db.Column(db.String(80),  nullable=True)
    siren           = db.Column(db.String(20),  nullable=True)
    siret           = db.Column(db.String(25),  nullable=True)
    rcs             = db.Column(db.String(100), nullable=True)
    legal_rep       = db.Column(db.String(200), nullable=True)
    signatory_title = db.Column(db.String(150), nullable=True)
    address         = db.Column(db.Text,        nullable=True)
    email           = db.Column(db.String(120), nullable=True)
    phone           = db.Column(db.String(30),  nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    owner = db.relationship('User', backref=db.backref('structure', uselist=False))

    def __repr__(self):
        return f"<Structure #{self.id} '{self.name}' owner={self.owner_id}>"


# =============================================================================
# PREMIUM PAYMENT — Historique des paiements d'abonnement LaProd+
# =============================================================================

class PremiumPayment(db.Model):
    """Historique des paiements d'abonnement — absent jusqu'ici : User ne
    garde qu'un instantané (premium_price_paid) écrasé à chaque renouvellement.
    Source pour la facture LaProd+ (routes/invoice_api.py) et pour l'export
    compta consolidé d'une Structure (routes/structure_api.py)."""
    __tablename__ = 'premium_payment'

    id      = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)

    plan          = db.Column(db.String(20),     nullable=False)
    amount_paid   = db.Column(db.Numeric(10, 2), nullable=False)
    duration_days = db.Column(db.Integer,        nullable=False)
    is_renewal    = db.Column(db.Boolean, default=False, nullable=False)

    stripe_payment_intent_id    = db.Column(db.String(120), nullable=True)
    stripe_checkout_session_id  = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    user = db.relationship('User', backref='premium_payments')

    def __repr__(self):
        return f"<PremiumPayment #{self.id} user={self.user_id} plan={self.plan} {self.amount_paid}€>"


class LicenseNotificationLog(db.Model):
    """Journal de déduplication des notifications planifiées de licences."""
    __tablename__ = 'license_notification_log'

    id                = db.Column(db.Integer, primary_key=True)
    purchase_id       = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=False)
    user_id           = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    notification_type = db.Column(db.String(80), nullable=False)
                        # 'sole_licensee_monthly' | 'expiry_90d' | 'expiry_30d' | 'expiry_7d' | 'expiry_1d'
    period_key        = db.Column(db.String(30), nullable=False)
                        # '2026-07' pour mensuel, '2026-07-01-90d' pour rappels d'expiration

    sent_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    purchase = db.relationship('Purchase', foreign_keys=[purchase_id],
                               backref=db.backref('notification_logs',
                                                  lazy='dynamic',
                                                  cascade='all, delete-orphan',
                                                  passive_deletes=True))
    user     = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('purchase_id', 'notification_type', 'period_key',
                            name='uq_license_notif_dedup'),
        db.Index('idx_license_notif_log', 'purchase_id', 'notification_type', 'period_key'),
    )

    def __repr__(self):
        return f"<LicenseNotificationLog purchase={self.purchase_id} type={self.notification_type} period={self.period_key}>"


class UserNotificationLog(db.Model):
    """Journal de déduplication des notifications planifiées utilisateur (re-engagement, etc.)."""
    __tablename__ = 'user_notification_log'

    id                = db.Column(db.Integer, primary_key=True)
    user_id           = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    notification_type = db.Column(db.String(80), nullable=False)
    period_key        = db.Column(db.String(30), nullable=False)
    sent_at           = db.Column(db.DateTime, default=datetime.now, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.UniqueConstraint('user_id', 'notification_type', 'period_key',
                            name='uq_user_notif_dedup'),
        db.Index('idx_user_notif_log', 'user_id', 'notification_type'),
    )

    def __repr__(self):
        return f"<UserNotificationLog user={self.user_id} type={self.notification_type} period={self.period_key}>"


class TestimonialRequest(db.Model):
    """Demandes de témoignages soumises par les utilisateurs (feature flag DEV)."""
    __tablename__ = 'testimonial_request'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    email        = db.Column(db.String(120), nullable=False)
    role         = db.Column(db.String(30), nullable=True)   # 'beatmaker', 'artist', 'mix_engineer'
    message      = db.Column(db.Text, nullable=False)
    rating       = db.Column(db.Integer, nullable=True)      # 1-5
    is_verified  = db.Column(db.Boolean, default=False, nullable=False)
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.now, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        return f"<TestimonialRequest id={self.id} email={self.email} published={self.is_published}>"


# =============================================================================
# PROMO CODES — remises créées et pilotées par les vendeurs eux-mêmes
# =============================================================================

# Beats couverts par un code (ignoré si applies_to_all est vrai).
promo_code_track = db.Table(
    'promo_code_track',
    db.Column('promo_code_id', db.Integer, db.ForeignKey('promo_code.id', ondelete='CASCADE'), primary_key=True),
    db.Column('track_id',      db.Integer, db.ForeignKey('track.id',      ondelete='CASCADE'), primary_key=True),
)

# Prestations mix/master couvertes par un code (ignoré si applies_to_all est vrai).
promo_code_service = db.Table(
    'promo_code_service',
    db.Column('promo_code_id', db.Integer, db.ForeignKey('promo_code.id', ondelete='CASCADE'), primary_key=True),
    db.Column('service_key',   db.String(20), primary_key=True),
)


class PromoCodeScope(enum.Enum):
    TRACK     = 'track'      # remise sur l'achat de beats
    MIXMASTER = 'mixmaster'  # remise sur les prestations mix/master


# Clés de service mix/master remisables, alignées sur MixMasterRequest.
# `stems` correspond à has_separated_stems, les autres à service_<clé>.
MIXMASTER_SERVICE_KEYS = ('cleaning', 'effects', 'artistic', 'mastering', 'stems')


class PromoCode(db.Model):
    """Code promo appartenant à un vendeur (beatmaker ou ingénieur).

    Le vendeur fixe librement sa remise ; elle est financée sur sa propre part.
    La commission de 10 % de LaProd porte sur le montant réellement encaissé
    (cf. utils.money.split_platform_fee), elle n'est donc jamais prélevée sur
    de l'argent que personne n'a payé.
    """
    __tablename__ = 'promo_code'

    id       = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    # Toujours stocké en MAJUSCULES (cf. normalize_code) : la contrainte d'unicité
    # est sensible à la casse, sans normalisation "Summer30" et "SUMMER30" seraient
    # deux codes distincts du même vendeur.
    code    = db.Column(db.String(15), nullable=False)
    percent = db.Column(db.Integer, nullable=False)   # 10 | 20 | 30 | 50 | 70
    scope   = db.Column(db.String(20), nullable=False, default=PromoCodeScope.TRACK.value)

    # Vrai = s'applique à tout le catalogue du vendeur (y compris ses futurs beats),
    # sans avoir à re-cocher quoi que ce soit à chaque upload.
    applies_to_all = db.Column(db.Boolean, default=False, nullable=False)

    # Limites facultatives, cumulables (une expiration ET un quota).
    expires_at      = db.Column(db.DateTime, nullable=True)
    max_redemptions = db.Column(db.Integer,  nullable=True)

    # Compteur dénormalisé, incrémenté par un UPDATE atomique conditionnel
    # (cf. try_consume) : un COUNT() sur promo_code_redemption serait sujet à
    # une race entre deux paiements simultanés sur le dernier lot disponible.
    redemption_count = db.Column(db.Integer, default=0, nullable=False)

    # Vrai = un acheteur donné ne peut utiliser le code qu'une seule fois.
    once_per_user = db.Column(db.Boolean, default=False, nullable=False)

    is_active  = db.Column(db.Boolean,  default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    owner    = db.relationship('User', backref=db.backref('promo_codes', cascade='all, delete-orphan'))
    tracks   = db.relationship('Track', secondary=promo_code_track,
                               backref=db.backref('promo_codes', lazy='dynamic'), lazy='selectin')

    __table_args__ = (
        # Unicité par vendeur, pas globale : au checkout on connaît déjà le vendeur
        # (le beat ou l'ingénieur ciblé), donc le code est résolu sans ambiguïté.
        # Deux vendeurs peuvent tous deux avoir « SUMMER30 » sans collision possible.
        db.UniqueConstraint('owner_id', 'code', name='uq_promo_code_owner_code'),
        CheckConstraint('percent IN (10, 20, 30, 50, 70)', name='ck_promo_percent_allowed'),
        CheckConstraint('length(code) BETWEEN 4 AND 15',   name='ck_promo_code_length'),
        CheckConstraint('max_redemptions IS NULL OR max_redemptions > 0', name='ck_promo_max_redemptions_positive'),
        CheckConstraint('redemption_count >= 0',           name='ck_promo_redemption_count_positive'),
        db.Index('idx_promo_owner_active', 'owner_id', 'is_active'),
    )

    # ── Normalisation ────────────────────────────────────────────────────────

    @staticmethod
    def normalize_code(raw: str) -> str:
        """Casse et espaces neutralisés. Utilisé à l'écriture ET à la lecture."""
        return (raw or '').strip().upper()

    # ── Périmètre ────────────────────────────────────────────────────────────

    @property
    def service_keys(self):
        """Clés de service mix/master couvertes (liste de str)."""
        rows = db.session.execute(
            promo_code_service.select().where(promo_code_service.c.promo_code_id == self.id)
        ).all()
        return [r.service_key for r in rows]

    def covers_track(self, track_id) -> bool:
        if self.scope != PromoCodeScope.TRACK.value:
            return False
        if self.applies_to_all:
            return True
        return any(t.id == track_id for t in self.tracks)

    def covers_service(self, service_key) -> bool:
        if self.scope != PromoCodeScope.MIXMASTER.value:
            return False
        if self.applies_to_all:
            return True
        return service_key in self.service_keys

    # ── Validité ─────────────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.now() > self.expires_at

    @property
    def is_exhausted(self) -> bool:
        return self.max_redemptions is not None and (self.redemption_count or 0) >= self.max_redemptions

    @property
    def remaining_redemptions(self):
        if self.max_redemptions is None:
            return None
        return max(0, self.max_redemptions - (self.redemption_count or 0))

    def used_by(self, user_id) -> bool:
        """Cet acheteur a-t-il déjà consommé ce code ?"""
        return db.session.query(
            PromoCodeRedemption.query
            .filter_by(promo_code_id=self.id, user_id=user_id)
            .exists()
        ).scalar()

    def check_usable_by(self, user_id):
        """Renvoie (True, None) ou (False, code_erreur). Ne consomme rien."""
        if not self.is_active:
            return False, 'PROMO_INACTIVE'
        if self.is_expired:
            return False, 'PROMO_EXPIRED'
        if self.is_exhausted:
            return False, 'PROMO_EXHAUSTED'
        if user_id == self.owner_id:
            return False, 'PROMO_OWN_CODE'
        if self.once_per_user and self.used_by(user_id):
            return False, 'PROMO_ALREADY_USED'
        return True, None

    # ── Consommation ─────────────────────────────────────────────────────────

    def try_consume(self, user_id) -> bool:
        """Incrémente le compteur de façon atomique, sous la contrainte du quota.

        Un UPDATE conditionnel en base (et non un read-modify-write en Python) :
        deux paiements concurrents sur la dernière utilisation disponible verraient
        tous deux redemption_count < max_redemptions et dépasseraient le quota.
        Ici le second UPDATE ne touche aucune ligne et renvoie False.

        Ne commit pas : l'appelant l'intègre à la transaction du paiement.
        """
        stmt = (
            PromoCode.__table__.update()
            .where(PromoCode.id == self.id)
            .where(PromoCode.is_active.is_(True))
            .where(or_(
                PromoCode.max_redemptions.is_(None),
                PromoCode.redemption_count < PromoCode.max_redemptions,
            ))
            .values(redemption_count=PromoCode.redemption_count + 1)
        )
        result = db.session.execute(stmt)
        return result.rowcount == 1

    def __repr__(self):
        return f"<PromoCode {self.code} -{self.percent}% owner={self.owner_id}>"


class PromoCodeRedemption(db.Model):
    """Trace d'une utilisation effective d'un code (une ligne = un paiement réussi).

    Sert à deux choses : appliquer once_per_user, et garder une piste d'audit du
    montant réellement remisé — le vendeur comme LaProd doivent pouvoir réconcilier
    un encaissement Stripe avec la remise qui l'explique.
    """
    __tablename__ = 'promo_code_redemption'

    id            = db.Column(db.Integer, primary_key=True)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_code.id', ondelete='CASCADE'), nullable=False)
    user_id       = db.Column(db.Integer, db.ForeignKey('user.id',       ondelete='CASCADE'), nullable=False)

    purchase_id           = db.Column(db.Integer, db.ForeignKey('purchase.id'),           nullable=True)
    mixmaster_request_id  = db.Column(db.Integer, db.ForeignKey('mixmaster_request.id'),  nullable=True)

    gross_amount    = db.Column(db.Numeric(10, 2), nullable=False)  # prix catalogue
    discount_amount = db.Column(db.Numeric(10, 2), nullable=False)  # remise accordée
    net_amount      = db.Column(db.Numeric(10, 2), nullable=False)  # réellement encaissé
    percent_applied = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    promo_code = db.relationship('PromoCode', backref=db.backref('redemptions', cascade='all, delete-orphan'))
    user       = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint('discount_amount >= 0', name='ck_redemption_discount_positive'),
        CheckConstraint('net_amount >= 0',      name='ck_redemption_net_positive'),
        db.Index('idx_redemption_promo_user', 'promo_code_id', 'user_id'),
    )

    def __repr__(self):
        return f"<PromoCodeRedemption promo={self.promo_code_id} user={self.user_id} -{self.discount_amount}€>"


# =============================================================================
# CAMPAGNES DE MAILING — prospection pilotée par les vendeurs (Premium)
# =============================================================================

class CampaignSegment(enum.Enum):
    """Audiences ciblables. L'ordre reflète la qualification décroissante."""
    BUYERS    = 'buyers'      # ont déjà acheté chez ce vendeur
    FAVORITES = 'favorites'   # ont mis un de ses beats en favori
    LISTENERS = 'listeners'   # ont écouté un de ses beats récemment
    # Ne connaissent PAS encore ce vendeur, mais leurs goûts (déduits par l'algo de
    # reco : tags/styles écoutés et mis en favori) collent à son catalogue. C'est
    # l'audience d'expansion : des prospects tièdes qu'aucun autre segment n'atteint.
    AFFINITY  = 'affinity'
    ALL       = 'all'         # toute la plateforme — Super Premium (payant)


class CampaignStatus(enum.Enum):
    DRAFT     = 'draft'       # en cours d'écriture
    SCHEDULED = 'scheduled'   # créneau validé, en attente du job de dispatch
    SENDING   = 'sending'     # dispatch en cours
    SENT      = 'sent'
    FAILED    = 'failed'
    CANCELLED = 'cancelled'


class MarketingCampaign(db.Model):
    """Campagne d'emailing d'un vendeur vers une audience segmentée.

    Une campagne n'est JAMAIS envoyée dans la foulée de sa création : elle est
    planifiée sur un créneau validé (cf. utils.campaign_service.validate_slot),
    puis dispatchée par un job. C'est ce qui empêche le mitraillage de la base.
    """
    __tablename__ = 'marketing_campaign'

    id       = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    subject = db.Column(db.String(120), nullable=False)
    body    = db.Column(db.Text, nullable=False)   # texte brut, échappé au rendu

    segment = db.Column(db.String(20), nullable=False, default=CampaignSegment.BUYERS.value)
    status  = db.Column(db.String(20), nullable=False, default=CampaignStatus.DRAFT.value)

    # Code promo mis en avant. C'est aussi le pivot d'attribution : les
    # redemptions de ce code par les destinataires après l'envoi mesurent la
    # conversion réelle de la campagne (et pas un taux d'ouverture décoratif).
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_code.id', ondelete='SET NULL'), nullable=True)

    # ── Super Premium (segment ALL) ──────────────────────────────────────────
    # Le paiement unique débloque UNE campagne à diffusion totale. Consommé à
    # l'envoi (is_consumed), jamais rejouable sur une seconde campagne.
    stripe_payment_intent_id = db.Column(db.String(200), unique=True, nullable=True)
    amount_paid              = db.Column(db.Numeric(10, 2), nullable=True)

    scheduled_for = db.Column(db.DateTime, nullable=True)  # créneau d'envoi validé
    sent_at       = db.Column(db.DateTime, nullable=True)

    recipient_count = db.Column(db.Integer, default=0, nullable=False)  # audience au moment du dispatch
    sent_count      = db.Column(db.Integer, default=0, nullable=False)  # emails réellement partis
    failed_count    = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    owner      = db.relationship('User', backref=db.backref('campaigns', cascade='all, delete-orphan'))
    promo_code = db.relationship('PromoCode')

    __table_args__ = (
        CheckConstraint("segment IN ('buyers','favorites','listeners','affinity','all')",
                        name='ck_campaign_segment'),
        CheckConstraint('recipient_count >= 0 AND sent_count >= 0 AND failed_count >= 0',
                        name='ck_campaign_counts_positive'),
        db.Index('idx_campaign_owner_status', 'owner_id', 'status'),
        db.Index('idx_campaign_dispatch', 'status', 'scheduled_for'),
    )

    @property
    def requires_payment(self):
        """Le segment « toute la plateforme » est le seul payant."""
        return self.segment == CampaignSegment.ALL.value

    @property
    def is_paid(self):
        return self.stripe_payment_intent_id is not None

    @property
    def is_editable(self):
        # FAILED inclus : une campagne qui n'a atteint personne peut être corrigée
        # et rejouée. Seule une campagne réellement partie est figée — la réécrire
        # rendrait ses statistiques mensongères.
        return self.status in (CampaignStatus.DRAFT.value,
                               CampaignStatus.SCHEDULED.value,
                               CampaignStatus.FAILED.value)

    def __repr__(self):
        return f"<MarketingCampaign #{self.id} {self.segment} {self.status} owner={self.owner_id}>"


class CampaignRecipient(db.Model):
    """Un destinataire d'une campagne (une ligne = un email tenté).

    Sert à trois choses : ne jamais envoyer deux fois le même mail, plafonner la
    fréquence subie par un utilisateur (tous vendeurs confondus), et attribuer
    les conversions — sans cette table, « le code a été utilisé » ne dit pas si
    la campagne y est pour quelque chose.
    """
    __tablename__ = 'campaign_recipient'

    id          = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('marketing_campaign.id', ondelete='CASCADE'), nullable=False)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    sent_at = db.Column(db.DateTime, nullable=True)   # None = échec d'envoi
    error   = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    campaign = db.relationship('MarketingCampaign', backref=db.backref('recipients', cascade='all, delete-orphan'))
    user     = db.relationship('User')

    __table_args__ = (
        # Un utilisateur n'apparaît qu'une fois par campagne — garde-fou en base
        # contre un double dispatch (retry de job, double clic sur « envoyer »).
        db.UniqueConstraint('campaign_id', 'user_id', name='uq_campaign_recipient'),
        db.Index('idx_recipient_user_sent', 'user_id', 'sent_at'),
    )

    def __repr__(self):
        return f"<CampaignRecipient campaign={self.campaign_id} user={self.user_id}>"