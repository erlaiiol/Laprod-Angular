"""
Tests d'intégration — génération réelle du PDF du contract builder
(POST /api/contract-builder/contracts/<id>/generate).

Contrairement à test_contract_builder_api.py (qui couvre l'accès/le gating),
ce fichier vérifie que le PDF est VRAIMENT écrit sur disque, qu'il s'agit d'un
PDF valide et exploitable, et que son contenu textuel reflète fidèlement :
  - le titre, le libellé du type de contrat (exploitation/performance/management)
  - les parties (personne physique ET personne morale)
  - les valeurs de clauses telles qu'enregistrées, y compris le texte déjà
    résolu côté front (substitution des variables [Contractant 1], [l'Œuvre]...
    — cf. builder-form.component.ts::resolveAllBrackets/useExample) : le
    backend ne connaît pas la notion de "variable", il persiste et imprime
    exactement le texte qu'on lui envoie, donc un bracket non résolu qui
    fuiterait jusqu'au PDF révélerait un bug côté front, pas ici — ces tests
    valident que le backend restitue fidèlement ce que le front lui a envoyé.
"""
import os

import pdfplumber
import pytest

import config
from models import ContractClause, ContractClauseGroup, ClauseTypeEnum, ContractTemplateTypeEnum, UserContract


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _pdf_path(filename: str) -> str:
    return str(config.CONTRACTS_FOLDER / 'builder' / filename)


def _pdf_text(filename: str) -> str:
    """Extrait tout le texte du PDF généré (une chaîne, toutes pages concaténées)."""
    with pdfplumber.open(_pdf_path(filename)) as pdf:
        return '\n'.join(page.extract_text() or '' for page in pdf.pages)


@pytest.fixture()
def cleanup_pdfs():
    """Piste les fichiers PDF réellement écrits sur disque pendant le test et les
    supprime en fin de test — ces tests écrivent dans db_assets/contracts/builder/
    (aucun override de CONTRACTS_FOLDER en test), pas question d'y laisser des
    fichiers de test."""
    created: list[str] = []
    yield created
    for filename in created:
        path = _pdf_path(filename)
        if os.path.exists(path):
            os.remove(path)


def _add_clause_group(db, contract_type=ContractTemplateTypeEnum.exploitation, name='Test Group', sort_order=1):
    group = ContractClauseGroup(name=name, sort_order=sort_order, is_active=True, contract_type=contract_type)
    db.session.add(group)
    db.session.flush()
    return group


def _add_clause(db, group, name, ctype, sort_order=1, required=False, legal_ref=None):
    clause = ContractClause(
        group_id=group.id, name=name, clause_type=ClauseTypeEnum(ctype),
        sort_order=sort_order, is_required=required, is_enabled_by_default=True,
        is_active=True, legal_reference=legal_ref,
    )
    db.session.add(clause)
    db.session.flush()
    return clause


def _generate(client, headers, contract_id):
    return client.post(f'/api/contract-builder/contracts/{contract_id}/generate', headers=headers)


def _set_parties_and_values(client, headers, contract_id, parties, values):
    return client.put(
        f'/api/contract-builder/contracts/{contract_id}',
        json={'parties': parties, 'values': values},
        headers=headers,
    )


# ── Génération réelle du fichier ──────────────────────────────────────────────────

class TestPdfFileIsActuallyWritten:

    def test_generate_creates_a_real_pdf_file_on_disk(self, client, auth_headers, user, db, cleanup_pdfs):
        contract = UserContract(user_id=user.id, title='Contrat de test PDF', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(client, auth_headers, contract.id, parties=[
            {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
            {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
        ], values=[])

        resp = _generate(client, auth_headers, contract.id)
        assert resp.status_code == 200
        pdf_url = resp.get_json()['data']['pdf_url']
        assert pdf_url == f'/api/contract-builder/contracts/{contract.id}/download'

        db.session.refresh(contract)
        assert contract.pdf_file is not None
        cleanup_pdfs.append(contract.pdf_file)

        path = _pdf_path(contract.pdf_file)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
        with open(path, 'rb') as f:
            assert f.read(5) == b'%PDF-'   # signature de fichier PDF valide

        db.session.delete(contract)
        db.session.commit()

    def test_generate_marks_contract_as_final(self, client, auth_headers, user, db, cleanup_pdfs):
        from models import UserContractStatus
        contract = UserContract(user_id=user.id, title='Statut final', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(client, auth_headers, contract.id, parties=[
            {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
            {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
        ], values=[])

        _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)

        assert contract.status == UserContractStatus.final

        db.session.delete(contract)
        db.session.commit()

    def test_regenerating_replaces_the_old_file_on_disk(self, client, auth_headers, user, db, cleanup_pdfs):
        contract = UserContract(user_id=user.id, title='Régénération', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(client, auth_headers, contract.id, parties=[
            {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
            {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
        ], values=[])

        _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        first_filename = contract.pdf_file
        first_path = _pdf_path(first_filename)
        assert os.path.exists(first_path)

        _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        second_filename = contract.pdf_file
        cleanup_pdfs.append(second_filename)

        assert second_filename != first_filename
        assert not os.path.exists(first_path), "l'ancien PDF doit être supprimé lors de la régénération"
        assert os.path.exists(_pdf_path(second_filename))

        db.session.delete(contract)
        db.session.commit()


# ── Contenu du PDF ───────────────────────────────────────────────────────────────

class TestPdfContent:

    def test_title_type_label_and_parties_appear_in_the_pdf(self, client, auth_headers, user, db, cleanup_pdfs):
        contract = UserContract(user_id=user.id, title='Nuit Électrique — Licence', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(client, auth_headers, contract.id, parties=[
            {'party_type': 'physical', 'role': 'Auteur-compositeur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
            {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
        ], values=[])

        resp = _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)
        assert resp.status_code == 200

        text = _pdf_text(contract.pdf_file)
        assert "Nuit Électrique" in text
        assert "EXPLOITATION" in text.upper()
        assert "Jean Dupont" in text
        assert "Marie Martin" in text
        assert "Auteur-compositeur" in text

        db.session.delete(contract)
        db.session.commit()

    def test_company_party_renders_siret_and_legal_representative(self, client, auth_headers, user, db, cleanup_pdfs):
        contract = UserContract(user_id=user.id, title='Contrat label', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(client, auth_headers, contract.id, parties=[
            {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
            {
                'party_type': 'company', 'role': 'Éditeur', 'sort_order': 1,
                'company_name': 'Studio Wax SARL', 'siret': '12345678900012',
                'legal_rep': 'Alice Durand', 'signatory_title': 'Gérante',
            },
        ], values=[])

        resp = _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)
        assert resp.status_code == 200

        text = _pdf_text(contract.pdf_file)
        assert "Studio Wax SARL" in text
        assert "12345678900012" in text
        assert "Alice Durand" in text
        assert "Gérante" in text

        db.session.delete(contract)
        db.session.commit()

    def test_clause_text_value_and_frontend_resolved_variables_appear_verbatim(
        self, client, auth_headers, user, db, cleanup_pdfs
    ):
        """Simule ce que produit builder-form.component.ts::resolveAllBrackets() :
        le front remplace [Contractant 1] par le nom réel AVANT d'envoyer la
        valeur au backend. Ce test vérifie que le texte déjà résolu traverse la
        chaîne PUT → generate → PDF sans altération, et qu'aucun bracket
        littéral ne reste (ce qui indiquerait une régression de résolution)."""
        group = _add_clause_group(db, name='Préambule', sort_order=0)
        clause = _add_clause(db, group, 'Contexte et volonté des parties', 'textarea', sort_order=0)
        db.session.commit()

        contract = UserContract(user_id=user.id, title='Résolution variables', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        # Texte "déjà résolu" par le front : [Contractant 1] → Jean Dupont, etc.
        resolved_text = (
            "Jean Dupont, en qualité de Auteur-compositeur, et Marie Martin, "
            "en qualité de Éditeur, ont convenu de formaliser les conditions "
            "d'exploitation de l'œuvre musicale intitulée Nuit Électrique."
        )
        _set_parties_and_values(
            client, auth_headers, contract.id,
            parties=[
                {'party_type': 'physical', 'role': 'Auteur-compositeur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
                {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
            ],
            values=[{'clause_id': clause.id, 'is_enabled': True, 'value': {'text': resolved_text}}],
        )

        resp = _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)
        assert resp.status_code == 200

        text = _pdf_text(contract.pdf_file)
        assert resolved_text in text.replace('\n', ' ')
        assert '[Contractant 1]' not in text
        assert '[l’Œuvre]' not in text and "[l'Œuvre]" not in text

        db.session.delete(contract)
        db.session.query(ContractClause).filter_by(id=clause.id).delete()
        db.session.query(ContractClauseGroup).filter_by(id=group.id).delete()
        db.session.commit()

    def test_percentage_and_legal_reference_are_rendered(self, client, auth_headers, user, db, cleanup_pdfs):
        group = _add_clause_group(db, name='Royalties', sort_order=0)
        clause = _add_clause(
            db, group, 'Taux — streaming (%)', 'percentage', sort_order=0,
            legal_ref='Art. L131-4 CPI',
        )
        db.session.commit()

        contract = UserContract(user_id=user.id, title='Contrat royalties', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(
            client, auth_headers, contract.id,
            parties=[
                {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
                {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
            ],
            values=[{'clause_id': clause.id, 'is_enabled': True, 'value': {'number': 25}}],
        )

        resp = _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)
        assert resp.status_code == 200

        text = _pdf_text(contract.pdf_file)
        assert '25' in text and '%' in text
        assert 'Art. L131-4 CPI' in text

        db.session.delete(contract)
        db.session.query(ContractClause).filter_by(id=clause.id).delete()
        db.session.query(ContractClauseGroup).filter_by(id=group.id).delete()
        db.session.commit()

    def test_management_contract_uses_the_management_type_label(self, client, auth_headers, user, db, cleanup_pdfs):
        """Vérifie le libellé ajouté en Phase 3 (type_labels dans
        contract_builder_api.py::generate_contract) pour le mandat de management."""
        contract = UserContract(user_id=user.id, title='Mandat Jean Dupont', contract_type=ContractTemplateTypeEnum.management)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(
            client, auth_headers, contract.id,
            parties=[
                {'party_type': 'physical', 'role': 'Manager', 'first_name': 'Alice', 'last_name': 'Durand', 'sort_order': 0},
                {'party_type': 'physical', 'role': 'Artiste', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 1},
            ],
            values=[],
        )

        resp = _generate(client, auth_headers, contract.id)
        assert resp.status_code == 200
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)

        text = _pdf_text(contract.pdf_file).upper()
        assert "MANDAT DE MANAGEMENT ARTISTIQUE" in text

        db.session.delete(contract)
        db.session.commit()

    def test_performance_contract_uses_the_performance_type_label(self, client, auth_headers, user, db, cleanup_pdfs):
        contract = UserContract(user_id=user.id, title='Concert Le Trabendo', contract_type=ContractTemplateTypeEnum.performance)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(
            client, auth_headers, contract.id,
            parties=[
                {'party_type': 'physical', 'role': 'Artiste', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
                {'party_type': 'company', 'role': 'Organisateur', 'company_name': 'Salle Live SARL', 'sort_order': 1},
            ],
            values=[],
        )

        resp = _generate(client, auth_headers, contract.id)
        assert resp.status_code == 200
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)

        text = _pdf_text(contract.pdf_file).upper()
        assert "REPRÉSENTATION MUSICALE" in text

        db.session.delete(contract)
        db.session.commit()

    def test_disabled_non_required_clause_is_absent_from_the_pdf(self, client, auth_headers, user, db, cleanup_pdfs):
        group = _add_clause_group(db, name='Options', sort_order=0)
        clause = _add_clause(db, group, 'Clause optionnelle jamais activée', 'toggle', sort_order=0, required=False)
        db.session.commit()

        contract = UserContract(user_id=user.id, title='Sans option', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(
            client, auth_headers, contract.id,
            parties=[
                {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
                {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
            ],
            values=[{'clause_id': clause.id, 'is_enabled': False, 'value': None}],
        )

        resp = _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)
        assert resp.status_code == 200

        text = _pdf_text(contract.pdf_file)
        assert 'Clause optionnelle jamais activée' not in text

        db.session.delete(contract)
        db.session.query(ContractClause).filter_by(id=clause.id).delete()
        db.session.query(ContractClauseGroup).filter_by(id=group.id).delete()
        db.session.commit()

    def test_required_but_disabled_clause_shows_non_applicable(self, client, auth_headers, user, db, cleanup_pdfs):
        group = _add_clause_group(db, name='Garanties', sort_order=0)
        clause = _add_clause(db, group, 'Garantie obligatoire', 'toggle', sort_order=0, required=True)
        db.session.commit()

        contract = UserContract(user_id=user.id, title='Requis non actif', contract_type=ContractTemplateTypeEnum.exploitation)
        db.session.add(contract)
        db.session.commit()

        _set_parties_and_values(
            client, auth_headers, contract.id,
            parties=[
                {'party_type': 'physical', 'role': 'Auteur', 'first_name': 'Jean', 'last_name': 'Dupont', 'sort_order': 0},
                {'party_type': 'physical', 'role': 'Éditeur', 'first_name': 'Marie', 'last_name': 'Martin', 'sort_order': 1},
            ],
            values=[{'clause_id': clause.id, 'is_enabled': False, 'value': None}],
        )

        resp = _generate(client, auth_headers, contract.id)
        db.session.refresh(contract)
        cleanup_pdfs.append(contract.pdf_file)
        assert resp.status_code == 200

        text = _pdf_text(contract.pdf_file)
        assert 'Garantie obligatoire' in text
        assert 'Non applicable' in text

        db.session.delete(contract)
        db.session.query(ContractClause).filter_by(id=clause.id).delete()
        db.session.query(ContractClauseGroup).filter_by(id=group.id).delete()
        db.session.commit()
