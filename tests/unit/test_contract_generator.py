"""
Tests unitaires — utils/contract_generator.py : generate_contract_pdf

Génère un vrai PDF (reportlab) dans un répertoire temporaire et en relit le
texte (pdfplumber) pour vérifier la présence/absence des clauses légales
introduites lors de la correction des failles identifiées à l'audit :
  - Cession des droits voisins (producteur de phonogramme)
  - Répartition SACEM conditionnée à la déclaration d'auteur de l'acheteur
  - Clauses distinctes L.131-4 (forfait) / L.131-5 (lésion)
  - Réserve du droit moral sur l'autorisation d'arrangement
  - Reformulation "durée légale de protection" (plus de "perpétuel"/"à vie" nu)
  - Garantie renforcée (samples tiers) en article 9
"""
import re

import pdfplumber
import pytest

from utils.contract_generator import generate_contract_pdf


def _base_contract_data(**overrides) -> dict:
    data = {
        'track_title':   'Midnight Drive',
        'composer_name': 'DJ Composer',
        'composer_address': '',
        'composer_email':   'composer@test.laprod.fr',
        'composer_credit':  'Prod. par DJ Composer',
        'client_name':    'Artist Client',
        'client_address': '',
        'client_email':   'artist@test.laprod.fr',
        'is_exclusive':   False,
        'start_date':     '01/01/2026',
        'end_date':       '31/12/2028',
        'duration_text':  '3 ans',
        'territory':      'France',
        'mechanical_reproduction': False,
        'public_show':    False,
        'streaming':      True,
        'arrangement':    False,
        'price':          15,
        'platform_commission': 10,
        'signature_date': '01/01/2026',
        'sacem_percentage_composer': 50,
        'sacem_percentage_buyer':    50,
        'phonogram_producer_attested':   False,
        'has_third_party_samples':       False,
        'sample_clearance_details':      '',
        'buyer_declares_original_lyrics': False,
    }
    data.update(overrides)
    return data


def _extract_text(pdf_path) -> str:
    """Texte du PDF, espaces normalisés pour ignorer les retours à la ligne
    de mise en page qui peuvent couper une phrase testée en sous-chaîne."""
    with pdfplumber.open(pdf_path) as pdf:
        raw = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    return re.sub(r'\s+', ' ', raw)


class TestDroitsVoisinsClause:

    def test_neighbouring_rights_clause_present(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data())
        text = _extract_text(out)
        assert 'droits voisins' in text.lower()
        assert 'L.213-1' in text

    def test_warning_shown_when_producer_not_attested(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(phonogram_producer_attested=False))
        text = _extract_text(out)
        assert 'dans la limite des droits dont le Compositeur dispose effectivement' in text

    def test_no_warning_when_producer_attested(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(phonogram_producer_attested=True))
        text = _extract_text(out)
        assert 'dans la limite des droits dont le Compositeur dispose effectivement' not in text


class TestSacemClauseGating:

    def test_sacem_table_shown_when_lyrics_declared(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(buyer_declares_original_lyrics=True))
        text = _extract_text(out)
        assert 'ne lie pas la SACEM' in text
        assert "Part de l'Interprète/Auteur" in text or "Part de l" in text

    def test_sacem_table_hidden_when_lyrics_not_declared(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(buyer_declares_original_lyrics=False))
        text = _extract_text(out)
        assert "n'a pas déclaré être l'auteur" in text
        assert 'ADAMI' in text
        assert 'ne lie pas la SACEM' not in text


class TestForfaitEtLesionClauses:

    def test_both_clauses_present_and_distinct(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data())
        text = _extract_text(out)
        assert 'L.131-4' in text
        assert 'L.131-5' in text
        assert 'RÉMUNÉRATION FORFAITAIRE' in text
        assert 'ACTION EN RÉVISION POUR LÉSION' in text


class TestDroitMoralArrangement:

    def test_moral_right_reservation_shown_when_arrangement_true(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(arrangement=True))
        text = _extract_text(out)
        assert 'L.121-1' in text
        assert 'dénaturation' in text

    def test_moral_right_reservation_absent_when_arrangement_false(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(arrangement=False))
        text = _extract_text(out)
        assert 'dénaturation' not in text


class TestStreamingWording:

    def test_streaming_only_wording_has_no_bare_perpetuel(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(duration_text="Streaming seul — durée légale de protection (vie de l'auteur + 70 ans)"))
        text = _extract_text(out)
        assert 'perpétuel' not in text.lower()
        assert '70 ans' in text

    def test_time_limited_contract_streaming_note_has_no_bare_perpetuel(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(duration_text='3 ans'))
        text = _extract_text(out)
        assert 'perpétuel' not in text.lower()
        assert '70 ans' in text


class TestGarantiesRenforcees:

    def test_no_undisclosed_samples_warranty_by_default(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(has_third_party_samples=False))
        text = _extract_text(out)
        assert 'ne pas avoir utilisé' in text
        assert 'indemniser' in text

    def test_disclosed_samples_shown_with_details(self, tmp_path):
        out = tmp_path / 'contract.pdf'
        generate_contract_pdf(str(out), _base_contract_data(
            has_third_party_samples=True,
            sample_clearance_details='Sample vocal cleared via Tracklib, licence #1234.',
        ))
        text = _extract_text(out)
        assert 'Tracklib' in text
        assert 'indemniser' in text
