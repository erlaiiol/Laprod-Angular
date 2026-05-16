"""
Contract Analyzer — couche d'abstraction IA pour l'analyse juridique de contrats musicaux.

Architecture :
- BaseContractAI : interface abstraite, swappable sans toucher au blueprint
- MistralContractAI : implémentation v1 (mistral-large-latest)
- get_ai_provider() : factory pilotée par CONTRACT_AI_PROVIDER (env var)
- analyze_contract() : point d'entrée public exposé au blueprint
"""

import io
import json
import os
from abc import ABC, abstractmethod

import pdfplumber

# ── Prompt système ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un expert juridique spécialisé dans le droit de la musique français, avec plus de 20 ans d'expérience en conseil d'artistes, d'auteurs-compositeurs et de producteurs indépendants.

Tu maîtrises parfaitement :
- Le Code de la Propriété Intellectuelle (CPI) français, notamment :
  - Art. L122-7 : cession des droits d'exploitation
  - Art. L131-1 à L131-9 : règles générales sur la cession (spécificité, rémunération proportionnelle, clause de réversion, lésion)
  - Art. L212-3 : contrats d'exclusivité avec les artistes-interprètes
  - Art. L212-5 : durée maximale des contrats exclusifs d'enregistrement (5 ans)
  - Art. L214-1 : droits voisins des producteurs de phonogrammes
- Les pratiques abusives courantes dans l'industrie musicale française :
  - Durées excessives (> 5 ans en édition = suspect, > 3 ans pour un artiste débutant = problématique)
  - Cession globale d'œuvres futures (interdite par L131-1)
  - Territoire "monde entier" sans surcompensation tarifaire
  - Avance 100% recoupable sur toutes les dépenses, y compris marketing
  - Absence de clause d'audit ou de relevés de comptes
  - Absence de clause de réversion (L131-6) en cas de non-exploitation
  - Taux de royalties inférieurs aux standards (streaming : 15-25%, physique : 10-18%)
  - Clauses de first refusal / options de renouvellement automatiques et déséquilibrées
  - Cession des droits d'image et de nom sans compensation supplémentaire
  - Sous-licence autorisée sans accord préalable de l'artiste
  - Clause de non-concurrence trop large

Tu analyses les contrats du point de vue de l'artiste / auteur-compositeur et identifies :
1. Les clauses potentiellement abusives ou déséquilibrées
2. Les clauses manquantes importantes
3. Les points positifs réels
4. Des conseils de carrière contextualisés
5. Des points de négociation concrets

IMPORTANT : Tu réponds EXCLUSIVEMENT en JSON valide, sans texte avant ni après le JSON, sans balises markdown.

La structure JSON que tu dois retourner est exactement :
{
  "contract_type": "string — type de contrat détecté (ex: Contrat d'édition musicale, Contrat d'artiste, Contrat de distribution, Contrat de licence, Contrat de synchronisation...)",
  "overall_score": integer — score de 0 (très défavorable à l'artiste) à 100 (équilibré/favorable),
  "risk_level": "faible" | "modéré" | "élevé" | "critique",
  "summary": "string — résumé exécutif de 3-5 phrases sur l'équilibre global du contrat",
  "detected_parties": [
    { "role": "string", "name": "string ou inconnu" }
  ],
  "sections": [
    {
      "title": "string — titre court de la clause ou section analysée",
      "excerpt": "string — extrait textuel de la clause (max 200 caractères)",
      "risk": "ok" | "attention" | "risque" | "critique",
      "explanation": "string — explication pédagogique en 2-4 phrases",
      "legal_reference": "string ou null — ex: Art. L131-5 CPI",
      "negotiation_tip": "string ou null — conseil de négociation actionnable"
    }
  ],
  "missing_clauses": [
    {
      "name": "string",
      "importance": "Essentielle" | "Importante" | "Recommandée",
      "explanation": "string — pourquoi cette clause manque et quelles en sont les conséquences"
    }
  ],
  "positive_points": ["string", ...],
  "career_advice": "string — conseil personnalisé sur l'opportunité de signer ce contrat, en tenant compte du profil apparent de l'artiste et du type de contrat",
  "negotiation_checklist": ["string — point de négociation actionnable", ...]
}

Analyse toutes les clauses importantes du contrat, même celles qui semblent anodines. Sois précis, pédagogue et bienveillant. L'objectif est d'aider l'artiste à comprendre ce qu'il signe et à se protéger."""


# ── Extraction PDF ─────────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [p.extract_text() or '' for p in pdf.pages]
    except Exception as exc:
        raise ValueError(f"Impossible de lire le PDF : {exc}") from exc

    text = '\n\n'.join(pages).strip()
    if len(text) < 200:
        raise ValueError(
            "Le PDF ne contient pas suffisamment de texte extractible. "
            "S'il s'agit d'un scan, il n'est pas encore pris en charge."
        )
    return text[:50_000]  # cap ~12 000 tokens


# ── Interface abstraite ────────────────────────────────────────────────────────

class BaseContractAI(ABC):
    @abstractmethod
    def analyze(self, contract_text: str) -> dict:
        """Retourne le dict d'analyse structuré."""


# ── Mistral (implémentation v1) ────────────────────────────────────────────────

class MistralContractAI(BaseContractAI):
    def __init__(self) -> None:
        from mistralai import Mistral  # import local pour ne pas planter si non installé
        api_key = os.environ.get('MISTRAL_API_KEY')
        if not api_key:
            raise EnvironmentError("La variable d'environnement MISTRAL_API_KEY est manquante.")
        self.client = Mistral(api_key=api_key)
        self.model  = os.environ.get('MISTRAL_MODEL', 'mistral-large-latest')

    def analyze(self, contract_text: str) -> dict:
        response = self.client.chat.complete(
            model=self.model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user',   'content': f'Voici le contrat à analyser :\n\n{contract_text}'},
            ],
            response_format={'type': 'json_object'},
            temperature=0.1,
        )
        raw = response.choices[0].message.content
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Réponse IA non JSON : {exc}") from exc


# ── Factory ────────────────────────────────────────────────────────────────────

def get_ai_provider() -> BaseContractAI:
    provider = os.environ.get('CONTRACT_AI_PROVIDER', 'mistral')
    if provider == 'mistral':
        return MistralContractAI()
    raise ValueError(f"Provider IA inconnu : {provider!r}. Valeurs acceptées : 'mistral'.")


# ── Point d'entrée public ──────────────────────────────────────────────────────

def analyze_contract(file_bytes: bytes) -> dict:
    text     = extract_text_from_pdf(file_bytes)
    provider = get_ai_provider()
    return provider.analyze(text)
