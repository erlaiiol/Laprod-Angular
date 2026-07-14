"""
Construction centralisée des données de contrat (Contract + PDF).

Avant ce module, trois routes (achat, renouvellement, création admin)
construisaient chacune indépendamment le dict `contract_data` passé à
`generate_contract_pdf` et les kwargs du modèle `Contract`, avec des champs
divergents (l'une des trois ne générait même pas de PDF). Ce module est
l'unique source de vérité : toute nouvelle clause légale s'ajoute ici une
seule fois plutôt que dans chacun des trois appelants.

Ne commite jamais — la transaction appartient à l'appelant.
"""
import uuid
from datetime import datetime
from pathlib import Path

from flask import current_app

from extensions import db
from models import Contract
from utils.contract_generator import generate_contract_pdf

# Clés de `build_contract_data()` qui correspondent à des colonnes du modèle
# `Contract` (le reste — track_title, composer_name, ... — n'est utile qu'au PDF).
_CONTRACT_MODEL_KEYS = {
    'track_id', 'composer_id', 'client_id',
    'composer_address', 'composer_email', 'composer_credit',
    'client_address', 'client_email',
    'is_exclusive', 'start_date', 'end_date', 'duration_text', 'territory',
    'mechanical_reproduction', 'public_show', 'streaming', 'arrangement',
    'sacem_percentage_composer', 'sacem_percentage_buyer',
    'price', 'percentage', 'signature_place', 'signature_date',
    'phonogram_producer_attested', 'has_third_party_samples', 'sample_clearance_details',
    'buyer_declares_original_lyrics', 'legal_terms_accepted', 'withdrawal_right_waived',
    'consent_recorded_at',
}


def build_contract_data(
    *, track, composer_user, client_user,
    is_exclusive, start_date, end_date, duration_text, territory,
    mechanical_reproduction, public_show, arrangement, price,
    streaming=True, percentage=0,
    composer_credit=None, composer_address='', client_address='', client_email=None,
    sacem_percentage_composer=None, sacem_percentage_buyer=None,
    signature_place=None, signature_date=None,
    buyer_declares_original_lyrics=False,
    legal_terms_accepted=False, withdrawal_right_waived=False,
) -> dict:
    """
    Snapshot canonique des termes légaux d'un contrat de licence de beat.

    Source de vérité unique pour les champs dérivés (répartition SACEM,
    crédit compositeur) afin que les trois points de vente (achat,
    renouvellement, création admin) produisent des contrats cohérents.

    Les attestations légales du Track (`phonogram_producer_attested`,
    `has_third_party_samples`, `sample_clearance_details`) sont toujours
    lues depuis `track` — jamais acceptées en paramètre — afin qu'elles ne
    puissent pas diverger de ce que le compositeur a réellement déclaré à
    l'upload. `consent_recorded_at` est toujours posé côté serveur, jamais
    fourni par l'appelant, pour constituer une preuve d'horodatage fiable
    du consentement de l'acheteur (charge de la preuve côté professionnel).
    """
    if sacem_percentage_composer is None:
        sacem_percentage_composer = getattr(track, 'sacem_percentage_composer', 50) or 50
    if sacem_percentage_buyer is None:
        sacem_percentage_buyer = 100 - sacem_percentage_composer

    return {
        'track_id':    track.id,
        'composer_id': composer_user.id,
        'client_id':   client_user.id,

        'track_title':      track.title,
        'composer_name':    composer_user.username,
        'composer_address': composer_address or getattr(composer_user, 'address', '') or '',
        'composer_email':   composer_user.email,
        'composer_credit':  composer_credit or f"Prod. par {composer_user.username}",
        'client_name':      client_user.username,
        'client_address':   client_address,
        'client_email':     client_email or client_user.email,

        'is_exclusive':   is_exclusive,
        'start_date':     start_date,
        'end_date':       end_date,
        'duration_text':  duration_text,
        'territory':      territory,

        'mechanical_reproduction': mechanical_reproduction,
        'public_show':             public_show,
        'streaming':                streaming,
        'arrangement':              arrangement,

        'sacem_percentage_composer': sacem_percentage_composer,
        'sacem_percentage_buyer':    sacem_percentage_buyer,

        'price':      price,
        'percentage': percentage,

        'signature_place': signature_place,
        'signature_date':  signature_date or start_date,

        # Snapshot des attestations du Track au moment de la vente.
        'phonogram_producer_attested': bool(track.phonogram_producer_attested),
        'has_third_party_samples':     bool(track.has_third_party_samples),
        'sample_clearance_details':    track.sample_clearance_details or '',

        # Consentement de l'acheteur, capturé au moment de la vente.
        'buyer_declares_original_lyrics': bool(buyer_declares_original_lyrics),
        'legal_terms_accepted':           bool(legal_terms_accepted),
        'withdrawal_right_waived':        bool(withdrawal_right_waived),
        # Horodatage posé uniquement si un consentement a réellement été
        # recueilli — sinon `consent_recorded_at` non nul donnerait l'illusion
        # d'une preuve de consentement sur un contrat où legal_terms_accepted/
        # withdrawal_right_waived valent False (cas admin par défaut).
        'consent_recorded_at': (
            datetime.now() if (legal_terms_accepted or withdrawal_right_waived) else None
        ),
    }


def contract_kwargs_from_data(data: dict, *, purchase_id=None, status='active') -> dict:
    """Mappe le dict canonique vers les kwargs de `Contract(**kwargs)`."""
    kwargs = {k: v for k, v in data.items() if k in _CONTRACT_MODEL_KEYS}
    # Contract.price est une colonne Integer — tronqué uniquement ici, pour la
    # ligne DB. Le PDF (pdf_data_from_contract_data) garde le montant exact.
    if 'price' in kwargs:
        kwargs['price'] = int(kwargs['price'])
    kwargs['purchase_id'] = purchase_id
    kwargs['status'] = status
    return kwargs


def pdf_data_from_contract_data(data: dict, *, platform_commission=10) -> dict:
    """Mappe le dict canonique vers la forme attendue par `generate_contract_pdf`."""
    return {**data, 'platform_commission': platform_commission}


def create_contract_and_pdf(
    *, contract_data: dict, contracts_dir: Path, filename_prefix: str,
    purchase=None, status='active',
):
    """
    Construit le `Contract`, génère son PDF, lie le fichier au `Contract` et
    (si fourni) au `Purchase`. Ne commite pas.

    Best-effort côté construction/PDF, à l'image du comportement historique
    des trois routes remplacées : un incident sur le contrat ne doit jamais
    faire échouer l'achat lui-même. Retourne `None` si la création du
    `Contract` a échoué (dans ce cas il n'y a rien à lier au `Purchase`).
    """
    purchase_id_for_log = purchase.id if purchase is not None else None
    try:
        kwargs = contract_kwargs_from_data(
            contract_data,
            purchase_id=purchase.id if purchase is not None else None,
            status=status,
        )
        contract = Contract(**kwargs)
        # SAVEPOINT : en cas d'échec, seul cet INSERT est annulé — la transaction
        # englobante (qui porte déjà le Purchase flush par l'appelant) doit
        # rester utilisable pour que "un incident sur le contrat ne fait jamais
        # échouer l'achat" (cf. docstring) soit vrai sur PostgreSQL, où une
        # instruction en échec empoisonne sinon toute la transaction en cours.
        with db.session.begin_nested():
            db.session.add(contract)
            db.session.flush()
    except Exception as exc:
        current_app.logger.error(
            f"Erreur création Contract (purchase #{purchase_id_for_log}): {exc}", exc_info=True,
        )
        return None

    try:
        contracts_dir.mkdir(parents=True, exist_ok=True)
        # uuid non-devinable : empêche l'énumération des contrats (PII).
        contract_filename = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.pdf"
        contract_path = contracts_dir / contract_filename

        generate_contract_pdf(str(contract_path), pdf_data_from_contract_data(contract_data))

        contract.contract_file = contract_filename
        if purchase is not None:
            purchase.contract_file = contract_filename
    except Exception as exc:
        current_app.logger.error(
            f"Erreur génération contrat PDF Contract #{contract.id}: {exc}", exc_info=True,
        )
        # Non bloquant : le Contract existe déjà, sans PDF attaché.

    return contract
