"""
 Module de Sécurité des Paiements
Validation et calcul sécurisé des prix pour tous les types de paiements
(Tracks, Mix/Master, Premium, etc.)
"""
from flask import request, flash, redirect, url_for, current_app, abort
from flask_login import current_user
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional
from functools import wraps  #  AJOUT : nécessaire pour @wraps
import logging
from extensions import db

logger = logging.getLogger(__name__)


# ============================================
# CLASSES ABSTRAITES ET CALCULATEURS
# ============================================

class PriceCalculator(ABC):
    """Classe abstraite pour le calcul des prix"""
    
    @abstractmethod
    def calculate_base_price(self, resource, **kwargs) -> float:
        """Calcule le prix de base selon la ressource"""
        pass

    @abstractmethod
    def calculate_options_price(self, options: Dict[str, Any]) -> float:
        """Calcule les options de prix disponibles pour la ressource"""
        pass

    def calculate_total(self, resource, options: Dict[str, Any], **kwargs) -> Tuple[float, float, float]:
        """Calcule le prix total en fonction de la ressource et des options"""
        base_price = self.calculate_base_price(resource, **kwargs)
        options_price = self.calculate_options_price(options)
        total_price = round(base_price + options_price, 2)
        return base_price, options_price, total_price
    
    def validate_price(self, total_price: float, min_price: float = 1.0, max_price: float = 10000.0) -> bool:
        """Le prix semble-t-il valide (dans les limites acceptables) ?"""    
        return min_price <= total_price <= max_price


class TrackPriceCalculator(PriceCalculator):
    """Calculateur de prix pour les Tracks"""

    def calculate_base_price(self, resource, **kwargs) -> float:
        """Calcule le prix du track selon le format"""
        format_type = kwargs.get('format_type', 'mp3')

        track_prices = {
            'mp3': resource.price_mp3,
            'wav': resource.price_wav,
            'stems': resource.price_stems
        }

        price = track_prices.get(format_type)

        if price is None:
            raise ValueError(f"Format invalide ou prix non défini: {format_type}")

        return float(price)

    def calculate_total(self, resource, options: Dict[str, Any], **kwargs) -> Tuple[float, float, float]:
        """Calcul total avec passage du base_price aux options (pour seuils)"""
        base_price = self.calculate_base_price(resource, **kwargs)
        # Passer base_price aux options pour le calcul des seuils
        options['base_price'] = base_price
        options_price = self.calculate_options_price(options)
        total_price = round(base_price + options_price, 2)
        return base_price, options_price, total_price

    def calculate_options_price(self, options: Dict[str, Any]) -> float:
        """
        Calcule le prix du contrat selon les options

        IMPORTANT: Appliquer la même logique que le frontend (contract_config.html)
        pour les seuils d'inclusion automatique des droits
        """
        contract_price = 0.0

        # Base price from options (needed for threshold calculation)
        base_price = options.get('base_price', 0.0)

        # Exclusivité
        if options.get('is_exclusive'):
            contract_price += float(current_app.config.get('CONTRACT_EXCLUSIVE_PRICE', 150))

        # Durée
        if options.get('is_lifetime'):
            contract_price += float(current_app.config['CONTRACT_DURATIONS']['lifetime'])
        else:
            years = str(int(options.get('duration_years', 3)))
            contract_price += float(current_app.config['CONTRACT_DURATIONS'].get(years, 5))

        # Territoire
        territory = options.get('territory', 'Monde entier')
        territory_prices = {
            'France': 0,
            'Europe': float(current_app.config.get('CONTRACT_TERRITORY_EUROPE', 5)),
            'Monde entier': float(current_app.config.get('CONTRACT_TERRITORY_WORLD', 10))
        }
        contract_price += territory_prices.get(territory, 0)

        # Arrangement (calculé AVANT les droits dynamiques car il affecte les seuils)
        if options.get('arrangement'):
            contract_price += float(current_app.config.get('CONTRACT_ARRANGEMENT_PRICE', 10))

        #  SEUILS D'INCLUSION AUTOMATIQUE (comme dans le frontend)
        # Calculer le total intermédiaire pour les seuils
        intermediate_total = base_price + contract_price
        MECHANICAL_THRESHOLD = 199.99
        PUBLIC_SHOW_THRESHOLD = 74.99

        # Droits d'exploitation avec logique de seuil
        # Mechanical reproduction: inclus automatiquement si total ≥ 199.99€
        if options.get('mechanical_reproduction'):
            if intermediate_total < MECHANICAL_THRESHOLD:
                # Coché manuellement ET en dessous du seuil → on paye
                contract_price += float(current_app.config.get('CONTRACT_MECHANICAL_REPRODUCTION_PRICE', 30))
            # Sinon: inclus automatiquement, prix = 0

        # Public show: inclus automatiquement si total ≥ 74.99€
        if options.get('public_show'):
            if intermediate_total < PUBLIC_SHOW_THRESHOLD:
                # Coché manuellement ET en dessous du seuil → on paye
                contract_price += float(current_app.config.get('CONTRACT_PUBLIC_SHOW_PRICE', 40))
            # Sinon: inclus automatiquement, prix = 0

        return contract_price


class MixMasterRequestPriceCalculator(PriceCalculator):
    """Calculateur de prix pour les demandes Mix/Master"""
    
    def calculate_base_price(self, resource, **kwargs) -> float:
        """Calcule le prix selon les services sélectionnés"""
        total_percentage = 0.0
        mixmaster_reference_price = float(resource.mixmaster_reference_price or 100)

        services_percentages = {
            'service_cleaning': 0.35,
            'service_effects': 0.45,
            'service_artistic': 0.60,
            'service_mastering': 0.20
        }

        for service, percentage in services_percentages.items():
            if kwargs.get(service):
                total_percentage += percentage

        if total_percentage == 0:
            raise ValueError("Aucun service sélectionné. Veuillez sélectionner un service.")

        base_price = mixmaster_reference_price * total_percentage
        return round(base_price, 2)
    
    def calculate_options_price(self, options: Dict[str, Any]) -> float:
        """Calcule le bonus stems (+20% du prix de référence)"""
        bonus = 0.0

        if options.get('has_separated_stems'):
            reference_price = options.get('reference_price', 0)
            bonus += reference_price * 0.20

        return round(bonus, 2)

    def calculate_total(self, resource, options: Dict[str, Any], **kwargs):
        """Total avec minimum mixmaster_price_min appliqué"""
        base_price = self.calculate_base_price(resource, **kwargs)
        options['base_price'] = base_price
        options['reference_price'] = float(resource.mixmaster_reference_price or 100)
        options_price = self.calculate_options_price(options)

        calculated_total = base_price + options_price
        mixmaster_price_min = float(resource.mixmaster_price_min or 0)
        total_price = max(calculated_total, mixmaster_price_min)

        return base_price, options_price, round(total_price, 2)


# ============================================
# FONCTIONS HELPER (niveau module)
# ============================================

def get_resource(resource_type: str, resource_id: int):
    """
    Récupère la ressource depuis la base de données
    
    Args:
        resource_type: 'track', 'mixmaster', 'mixmasterrequest', 'premium'
        resource_id: ID de la ressource
    
    Returns:
        Objet Track, User (ingénieur), MixMasterRequest, ou None
    """
    from models import Track, User, MixMasterRequest
    
    if resource_type == 'track':
        return db.session.get(Track, resource_id)
    
    elif resource_type == 'mixmaster':
        # Pour Mix/Master, resource_id = engineer_id
        return db.session.get(User, resource_id)
    
    elif resource_type == 'mixmasterrequest':
        # Pour payer une demande existante
        return db.session.get(MixMasterRequest, resource_id)
    
    elif resource_type == 'premium':
        # Pour Premium, pas vraiment de "ressource" à récupérer
        return None
    
    else:
        raise ValueError(f"Type de ressource inconnu: {resource_type}")


def extract_payment_data(request_obj, resource_type: str, **url_params) -> Dict[str, Any]:
    """
    Extrait les données de paiement depuis la requête (form ou JSON)
    
    Args:
        request_obj: Objet Flask request
        resource_type: Type de ressource
    
    Returns:
        Dictionnaire avec 'options', 'kwargs', 'total_price'
    """
    # Récupérer les données (form ou JSON)
    if request_obj.is_json:
        data = request_obj.get_json()
    else:
        data = request_obj.form.to_dict()
    
    # Structure de retour
    result = {
        'options': {},
        'kwargs': {},
        'total_price': None
    }
    
    # ============================================
    # TRACK
    # ============================================
    if resource_type == 'track':
        # format_type vient de l'URL (paramètre de route), pas du formulaire
        result['kwargs'] = {
            'format_type': url_params.get('format_type', 'mp3')
        }

        # Les checkboxes HTML envoient leur value (1) si cochées, rien sinon
        # MAIS attention: certains formulaires peuvent envoyer '0' pour false
        # On vérifie donc que la clé existe ET que la valeur != '0'
        result['options'] = {
            'is_exclusive': 'is_exclusive' in data and data.get('is_exclusive') != '0',
            'is_lifetime': 'is_lifetime' in data and data.get('is_lifetime') == '1',
            'duration_years': int(data.get('duration_years_value', 3)) if data.get('is_lifetime') != '1' else 0,
            'territory': data.get('territory', 'Monde entier'),
            'mechanical_reproduction': 'mechanical_reproduction' in data and data.get('mechanical_reproduction') != '0',
            'public_show': 'public_show' in data and data.get('public_show') != '0',
            'arrangement': 'arrangement' in data and data.get('arrangement') != '0'
        }

        result['total_price'] = float(data.get('total_price')) if data.get('total_price') else None
    
    # ============================================
    # MIX/MASTER
    # ============================================
    elif resource_type == 'mixmaster' or resource_type == 'mixmasterrequest':
        # Les checkboxes HTML envoient leur value si cochées, rien sinon
        # On vérifie donc la présence de la clé dans le dictionnaire
        result['kwargs'] = {
            'service_cleaning': 'service_cleaning' in data,
            'service_effects': 'service_effects' in data,
            'service_artistic': 'service_artistic' in data,
            'service_mastering': 'service_mastering' in data
        }

        result['options'] = {
            'has_separated_stems': 'has_separated_stems' in data
        }

        result['total_price'] = float(data.get('total_price')) if data.get('total_price') else None
    
    # ============================================
    # PREMIUM
    # ============================================
    elif resource_type == 'premium':
        result['kwargs'] = {
            'plan_type': data.get('plan_type', 'monthly')
        }
        result['options'] = {}
        result['total_price'] = float(data.get('total_price')) if data.get('total_price') else None
    
    return result


# ============================================
# DÉCORATEUR
# ============================================

def validate_payment(calculator_class: type, resource_type: str, resource_param: str = None):
    """
    Décorateur pour valider les prix côté serveur avant paiement
    
    Args:
        calculator_class: Classe du calculateur (TrackPriceCalculator, MixMasterRequestPriceCalculator, etc.)
        resource_type: Type de ressource ('track', 'mixmaster', 'mixmaster_request', 'premium')
        resource_param: Nom du paramètre URL contenant l'ID (par défaut: '{resource_type}_id')
    
    Usage:
        @validate_payment(TrackPriceCalculator, 'track')
        def checkout(track_id, format_type, resource, validated_prices):
            # Le prix a déjà été validé ici
            track = resource
            total = validated_prices['total_price']
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Si c'est une requête GET, ne pas valider (affichage du formulaire)
            # La validation ne s'applique que sur POST (soumission du formulaire)
            if request.method != 'POST':
                return f(*args, **kwargs)

            try:
                # 1. Déterminer le nom du paramètre resource
                param_name = resource_param or f"{resource_type}_id"
                
                # 2. Récupérer l'ID de la ressource depuis les kwargs de Flask
                resource_id = kwargs.get(param_name)
                if not resource_id:
                    logger.error(f"Paramètre {param_name} manquant dans l'URL(payment_validator)")
                    abort(400, f"Paramètre {param_name} manquant")
                
                # 3. Récupérer la ressource depuis la DB
                resource = get_resource(resource_type, resource_id)
                if not resource:
                    logger.error(f"{resource_type.capitalize()} {resource_id} introuvable")
                    abort(404, f"{resource_type.capitalize()} introuvable")
                
                # 4. Extraire les données du formulaire/JSON
                # Passer aussi les paramètres URL (comme format_type pour les tracks)
                data = extract_payment_data(request, resource_type, **kwargs)

                # 5. Calculer le prix côté serveur
                calculator = calculator_class()
                base_price, options_price, server_total = calculator.calculate_total(
                    resource=resource,
                    options=data.get('options', {}),
                    **data.get('kwargs', {})
                )
                
                # 6. Récupérer le prix envoyé par le client
                client_total = data.get('total_price')
                
                # 7. Comparer les prix
                if client_total is None:
                    logger.warning("Prix client manquant - calcul serveur utilisé")
                elif abs(server_total - client_total) > 0.01:  # Tolérance de 1 centime
                    logger.error(
                        f"Prix manipulé détecté ! "
                        f"Client: {client_total}€, Serveur: {server_total}€, "
                        f"User: {current_user.id if current_user.is_authenticated else 'Anonyme'}"
                    )
                    flash(" Erreur de validation du prix. Veuillez réessayer.", "danger")
                    abort(403, "Prix invalide")
                
                # 8. Ajouter les prix validés dans kwargs pour la route
                kwargs['validated_prices'] = {
                    'base_price': base_price,
                    'options_price': options_price,
                    'total_price': server_total
                }
                
                # 9. Ajouter la ressource dans kwargs (évite de re-query la DB)
                kwargs['resource'] = resource
                
                logger.info(
                    f"Validation OK - {resource_type} {resource_id}, "
                    f"Prix: {server_total}€, User: {current_user.id if current_user.is_authenticated else 'Anonyme'}"
                )
                
                # 10. Exécuter la route
                return f(*args, **kwargs)
            
            except Exception as e:
                logger.error(f"Erreur validation paiement: {e}", exc_info=True)
                flash(" Erreur lors de la validation du paiement", "danger")
                abort(500, "Erreur serveur")
        
        return wrapper
    return decorator
