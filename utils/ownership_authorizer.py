from abc import ABC, abstractmethod
from functools import wraps
from flask import abort
from flask_login import current_user
from extensions import db
from models import Topline, Track, MixMasterRequest, Purchase, Contract


# ===========================================
# Abstract Class : Authorization strategy
# ===========================================

class OwnershipStrategy(ABC):
    """
    Classe abstraite définissant le contrat pour vérifier la propriété

    Chaque type de ressource (Track, Topline, Mixmaster) implémente sa propre logique
    """

    @abstractmethod
    def get_resource(self, resource_id):
        """Récuperer la ressource depuis la base de donnée
        args:
            resource_id L'ID de la ressource

        returns: L'ojet resource (Track, Topline, etc..)
        """
        pass

    @abstractmethod
    def check_ownership(self, resource):
        """Vérifier si l'utilisateur actuel a les permission sur la dite resource
        Args:
            resource: L'objet resource récuperé

        Returns:
            bool: True si autorisé, False sinon
        """
        pass

    @abstractmethod
    def get_param_name(self):
        """Retourner le nom du paramètre dans l'URL (ex: 'track_id', 'topline_id',)
        Returns:
        str: nom du pramètre
        """
        pass

    def get_error_message(self):
        """Message d'erreur personnalisé (optionnel, peut être override)
        
        Returns:
            str: message d'erreur"""
        return "Accès refusé: vous n'êtes pas autorisé à accéder à cette ressource"
    

    # ==========================================================
    # CONCRETE IMPLEMENTATION
    # ==========================================================

class ToplineOwnership(OwnershipStrategy):
    """
    Stratégie d'autorisation pour les toplines
    Autorise: l'artiste créateur, le compositeur du track parent ou un admin
    """

    def get_resource(self, resource_id):
        return db.get_or_404(Topline, resource_id)
    
    def check_ownership(self, topline):
        is_artist = current_user.id == topline.artist_id
        is_admin = current_user.is_admin

        return is_artist or is_admin
    
    def get_param_name(self):
        return 'topline_id'
    
    def get_error_message(self):
        return "Vous n'êtes pas le créateur de cette topline"

class TrackOwnership(OwnershipStrategy):
    """Stratégie d'autorisation pour les tracks
    Autorise: le compositeur ou l'admin"""

    def get_resource(self, resource_id):
        return db.get_or_404(Track, resource_id)
    
    def check_ownership(self, track):
        is_composer = current_user.id == track.composer_id
        is_admin = current_user.is_admin

        return is_composer or is_admin
    
    def get_param_name(self):
        return 'track_id'
    
    def get_error_message(self):
        return "Vous n'êtes pas le compositeur de ce track"
    
class MixMasterArtistBuyerOwnership(OwnershipStrategy):
    """Stratégie d'autorisation pour les demandes MixMaster (côté artiste)
    Autorise: l'artiste demandeur ou un admin"""

    def get_resource(self, resource_id):
        return db.get_or_404(MixMasterRequest, resource_id)
    
    def check_ownership(self, mixMasterRequest):
        is_artist = current_user.id == mixMasterRequest.artist_id
        is_admin = current_user.is_admin

        return is_artist or is_admin
    
    def get_param_name(self):
        return 'request_id'
    
    def get_error_message(self):
        return "vous n'êtes pas l'artiste/acheteur de cette demande"
    
class MixMasterEngineerSellerOwnership(OwnershipStrategy):
    """Stratégie d'autorisation pour les 'offres' Mixmaster (côté engineer)
    Autorise: l'engineer vendeur ou un admin"""

    def get_resource(self, resource_id):
        return db.get_or_404(MixMasterRequest, resource_id)
    
    def check_ownership(self, mixMasterRequest):
        is_engineer = current_user.id == mixMasterRequest.engineer_id
        is_admin = current_user.is_admin

        return is_engineer or is_admin
    def get_param_name(self):
        return 'request_id'
    
    def get_error_message(self):
        return "vous n'êtes pas l'ingénieur/vendeur de cette demande"

class PurchaseOwnership(OwnershipStrategy):
    """Stratégie d'autorisation pour les achats(tracks)
    Autorise: l'acheteur, le vendeur, l'admin"""

    def get_resource(self, resource_id):
        return db.get_or_404(Purchase, resource_id)
    
    def check_ownership(self, purchase):
        is_buyer = current_user.id == purchase.buyer_id
        is_seller = current_user.id == purchase.track.composer_id
        is_admin = current_user.is_admin

        return is_buyer or is_seller or is_admin
    
    def get_param_name(self):
        return 'purchase_id'
    
    def get_error_message(self):
        return "vous n'êtes pas impliqué dans cette transaction"
    
class ContractOwnership(OwnershipStrategy):
    """
    Stratégie d'autorisation pour les contrats(de tracks)
    Autorise: le compositeur, l'artiste et l'admin
    """

    def get_resource(self, resource_id):
        return db.get_or_404(Contract, resource_id)

    def check_ownership(self, contract):
        is_client = current_user.id == contract.client_id
        is_composer = current_user.id == contract.composer_id
        is_admin = current_user.is_admin

        return is_client or is_composer or is_admin
    
    def get_param_name(self):
        return 'contract_id'
    
    def get_error_message(self):
        return "vous n'êtes pas signataire de ce contrat"
    

# =============================================
# DECORATEUR GENERIQUE
# =============================================


def requires_ownership(strategy_class):
    """
    Décorateur générique qui utilise une stratégie d'autorisation
    
    Exemple:
    @requires_ownership(ToplineOwnership)
        def delete_topline(topline_id, topline=None):
            # topline est injecté automatiquement par le décorateur
            ...

    Args:
        strategy_class: Classe de stratégie (ToplineOwnership, TrackOwnership ...)

    Returns: 
        Décorateur configuré avec la stratégie spécifiée
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Instancier la stratégie
            strategy = strategy_class()

            # Récuperer l'ID de la ressource depuis les paramètres de la route
            param_name = strategy.get_param_name()
            resource_id = kwargs.get(param_name)

            # Verifier les permissions
            if not resource_id:
                abort(400, f"Paramètre {param_name} manquant (requires_ownership)")

            #Récupérer la resource
            resource = strategy.get_resource(resource_id)

            # Vérifier les permissions
            if not strategy.check_ownership(resource):
                abort (403, strategy.get_error_message())

            # Mapping explicite pour plus de clarté
            RESOURCE_NAME_MAPPING = {
                'ToplineOwnership': 'topline',
                'TrackOwnership': 'track',
                'MixMasterArtistBuyerOwnership': 'request_obj',
                'MixMasterEngineerSellerOwnership': 'request_obj',
                'PurchaseOwnership': 'purchase',
                'ContractOwnership': 'contract'
            }

            resource_var_name = RESOURCE_NAME_MAPPING.get(
                strategy.__class__.__name__,
                strategy.__class__.__name__.replace('Ownership', '').lower()
            )


            kwargs[resource_var_name] = resource

            return f(*args, **kwargs)
        
        return wrapper
    return decorator