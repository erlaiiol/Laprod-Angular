"""
Contract Analyzer — couche d'abstraction IA pour l'analyse juridique de contrats musicaux.

Architecture :
- BaseContractAI : interface abstraite, swappable sans toucher au blueprint
- GroqContractAI : implémentation v1 (llama-3.3-70b-versatile via Groq)
- get_ai_provider() : factory pilotée par CONTRACT_AI_PROVIDER (env var)
- analyze_contract() : point d'entrée public exposé au blueprint
"""

import io
import json
import os
from abc import ABC, abstractmethod

import pdfplumber

# ── Prompt système ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un avocat spécialisé en droit de la propriété intellectuelle et en droit de la musique français, avec 20 ans d'expérience en conseil d'artistes, auteurs-compositeurs et producteurs indépendants.

Tu maîtrises :
- Le Code de la Propriété Intellectuelle (CPI) : Art. L111-1 (droit moral), L122-7 (cession), L131-1 à L131-9 (règles de cession : spécificité, rémunération proportionnelle, réversion, lésion), L212-3/L212-5 (artistes-interprètes, 5 ans max), L214-1 (droits voisins)
- Les pratiques abusives : cession globale d'œuvres futures (L131-1), absence de clause de réversion (L131-6), recoupement cross-collateral, 360° deal sans plafond, first refusal déséquilibré, sous-licence sans accord, non-concurrence excessive, royalties inférieures aux standards (streaming 15-25%, physique 10-18%), avances 100% recoupables sur dépenses marketing

Tu analyses toujours du point de vue de l'artiste / auteur-compositeur.

IMPORTANT : Tu réponds EXCLUSIVEMENT en JSON valide, sans texte avant ni après, sans balises markdown.

Structure JSON exacte à retourner :
{
  "contract_type": "Type détecté (ex: Contrat d'édition musicale, Contrat d'artiste, Contrat de distribution, Contrat de licence, Contrat de synchronisation...)",
  "overall_score": entier de 0 (très défavorable) à 100 (équilibré/favorable),
  "risk_level": "faible" | "modéré" | "élevé" | "critique",
  "summary": "Résumé exécutif de 3-5 phrases sur l'équilibre global du contrat",
  "detected_parties": [
    { "role": "string", "name": "string ou Inconnu" }
  ],
  "critical_articles": [
    {
      "article_ref": "Référence exacte dans le contrat (ex: 'Article 3.2', 'Clause 5 §2') ou 'Clause non référencée' si absente",
      "title": "Titre court de la clause problématique",
      "excerpt": "Extrait textuel exact de la clause, tel qu'il apparaît dans le contrat (max 300 caractères)",
      "risk": "risque" | "critique",
      "legal_analysis": "Analyse juridique approfondie : qualification légale précise selon le CPI, risques concrets pour l'artiste (perte de contrôle sur l'œuvre, préjudice financier, durée excessive, etc.), comparaison avec les standards du marché musical français et la pratique contractuelle habituelle. 4-6 phrases.",
      "legal_references": ["Art. L122-7 CPI", "Art. L131-1 CPI"],
      "negotiation_levers": ["Levier 1 — formulation concrète et actionnable à demander", "Levier 2", "Levier 3"]
    }
  ],
  "sections": [
    {
      "title": "Intitulé de l'article tel que mentionné dans le contrat (ex: 'Article 3 — Cession de droits') ou nom descriptif si non référencé",
      "excerpt": "Extrait textuel de la clause (max 200 caractères)",
      "risk": "ok" | "attention" | "risque" | "critique",
      "explanation": "Explication pédagogique en 2-4 phrases — ce que la clause signifie concrètement pour l'artiste",
      "legal_reference": "Art. Lxxx CPI ou null",
      "negotiation_tip": "Conseil de négociation actionnable ou null"
    }
  ],
  "missing_clauses": [
    {
      "name": "string",
      "importance": "Essentielle" | "Importante" | "Recommandée",
      "explanation": "Pourquoi cette clause manque et quelles en sont les conséquences juridiques et pratiques"
    }
  ],
  "positive_points": ["string", ...],
  "career_advice": "Conseil personnalisé sur l'opportunité de signer ce contrat, en tenant compte du profil apparent de l'artiste, du type de contrat et des risques identifiés",
  "negotiation_checklist": ["Point de négociation actionnable — formulation concrète à demander à la partie adverse", ...]
}

Règles impératives :
1. critical_articles : identifie les 3 à 5 clauses les plus déséquilibrées ou dangereuses (risk='risque' ou 'critique' uniquement). Si le contrat est globalement équilibré, réduis à 2 ou 3. Ne jamais inclure de clause 'ok' ou 'attention' ici.
2. sections : analyse TOUTES les clauses et articles significatifs identifiés dans le contrat, triées du risque le plus élevé au plus faible (critique → risque → attention → ok). Inclus systématiquement la référence de l'article dans le titre quand elle est mentionnée dans le document.
3. Sois précis, pédagogue, bienveillant. L'objectif est d'aider l'artiste à comprendre ce qu'il signe et à se protéger."""


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


# ── Groq ───────────────────────────────────────────────────────────────────────

class GroqContractAI(BaseContractAI):
    def __init__(self) -> None:
        from groq import Groq
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            raise EnvironmentError("La variable d'environnement GROQ_API_KEY est manquante.")
        self.client = Groq(api_key=api_key)
        self.model  = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

    def analyze(self, contract_text: str) -> dict:
        response = self.client.chat.completions.create(
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
    provider = os.environ.get('CONTRACT_AI_PROVIDER', 'groq')
    if provider == 'groq':
        return GroqContractAI()
    raise ValueError(f"Provider IA inconnu : {provider!r}. Valeurs acceptées : 'groq'.")


# ── Point d'entrée public ──────────────────────────────────────────────────────

def analyze_contract(file_bytes: bytes) -> dict:
    text     = extract_text_from_pdf(file_bytes)
    provider = get_ai_provider()
    return provider.analyze(text)
