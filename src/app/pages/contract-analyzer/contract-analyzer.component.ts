import { ChangeDetectionStrategy, Component, OnDestroy, HostListener, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import {
  ContractAnalyzerService,
  ContractAnalysis,
  ContractSection,
  CriticalArticle,
} from '../../services/contract-analyzer.service';
import { ToastService } from '../../services/toast.service';
import { AuthService } from '../../services/auth.service';
import { PremiumLockComponent } from '../../components/premium-lock/premium-lock.component';

const LOADING_MESSAGES = [
  'Lecture du PDF en cours...',
  'Extraction du contenu juridique...',
  'Analyse avec notre expert IA en droit musical...',
  'Comparaison avec le Code de la Propriété Intellectuelle...',
  'Identification des clauses à risque...',
  'Évaluation de l\'équilibre contractuel...',
  'Finalisation de l\'analyse...',
];

const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 Mo

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-contract-analyzer',
  standalone: true,
  imports: [CommonModule, RouterModule, PremiumLockComponent],
  templateUrl: './contract-analyzer.component.html',
  styleUrl: './contract-analyzer.component.scss',
})
export class ContractAnalyzerComponent implements OnDestroy {

  private auth        = inject(AuthService);
  readonly isPremium  = this.auth.isPremium;
  readonly isLoggedIn = this.auth.isLoggedIn;

  readonly demoAnalysis: ContractAnalysis = {
    contract_type: 'Contrat de licence d\'exploitation — EXEMPLE',
    overall_score: 42,
    risk_level: 'élevé',
    summary: 'Contrat de licence non-exclusive pour l\'exploitation numérique d\'une œuvre musicale. Plusieurs clauses déséquilibrent fortement les droits en faveur du label au détriment de l\'artiste.',
    detected_parties: [
      { role: 'Artiste / Compositeur', name: 'Jean Dupont' },
      { role: 'Label / Éditeur', name: 'Major Music SAS' },
    ],
    critical_articles: [
      {
        article_ref: 'Art. 4.2',
        title: 'Cession de droits patrimoniaux',
        excerpt: 'L\'artiste cède l\'intégralité de ses droits patrimoniaux pour une durée de 70 ans.',
        risk: 'critique',
        legal_analysis: 'La cession de 70 ans équivaut à une cession quasi-définitive. L\'article L.131-3 du CPI impose que toute cession soit limitée dans le temps et l\'espace. Une telle clause expose l\'artiste à une perte totale de contrôle sur son œuvre.',
        legal_references: ['Art. L.131-3 CPI', 'Art. L.122-7 CPI'],
        negotiation_levers: ['Limiter à 5-10 ans renouvelables', 'Prévoir une clause de réversion si exploitation insuffisante'],
      },
    ],
    sections: [
      { title: 'Art. 1 — Objet du contrat', excerpt: 'Le présent contrat a pour objet la licence d\'exploitation numérique.', risk: 'ok', explanation: 'Clause standard, bien formulée.', legal_reference: null, negotiation_tip: null },
      { title: 'Art. 3 — Rémunération', excerpt: 'L\'artiste percevra 8% des revenus nets générés.', risk: 'attention', explanation: 'Le taux de 8% est en dessous des standards du marché (15-20%). La base "revenus nets" peut être manipulée contractuellement.', legal_reference: 'Art. L.131-4 CPI', negotiation_tip: 'Négociez sur les "revenus bruts" et un minimum garanti.' },
      { title: 'Art. 4 — Durée et territoire', excerpt: 'Monde entier, durée 70 ans.', risk: 'critique', explanation: 'Cession trop large en durée et territoire.', legal_reference: 'Art. L.131-3 CPI', negotiation_tip: 'Limitez à 5 ans, France + Europe, avec option de renouvellement.' },
    ],
    missing_clauses: [
      { name: 'Clause de réversion', importance: 'Essentielle', explanation: 'En cas d\'inexploitation pendant 12 mois, les droits doivent revenir à l\'artiste.' },
      { name: 'Reddition de comptes', importance: 'Importante', explanation: 'Aucune obligation de reporting trimestriel sur les streams et revenus.' },
    ],
    positive_points: ['Droit moral préservé', 'Clause d\'audit prévue'],
    career_advice: 'Ce type de contrat est défavorable pour un artiste en début de carrière. Faites-vous accompagner par un avocat spécialisé en droit de la musique avant de signer.',
    negotiation_checklist: ['Réduire la durée de cession à 5 ans', 'Augmenter le taux de royalties à 18%', 'Ajouter une clause de réversion', 'Préciser les territoires'],
  };

  phase            = signal<'upload' | 'loading' | 'result'>('upload');
  analysis         = signal<ContractAnalysis | null>(null);
  selectedSection  = signal<ContractSection | null>(null);
  selectedCritical = signal<CriticalArticle | null>(null);
  loadingMessage   = signal(LOADING_MESSAGES[0]);
  dragOver         = signal(false);
  fileError        = signal<string | null>(null);

  scoreColor = computed(() => {
    const s = this.analysis()?.overall_score ?? 0;
    if (s >= 70) return 'score-good';
    if (s >= 45) return 'score-medium';
    return 'score-bad';
  });

  private msgInterval: ReturnType<typeof setInterval> | null = null;
  private msgIdx = 0;

  constructor(
    private svc:   ContractAnalyzerService,
    private toast: ToastService,
  ) {}

  ngOnDestroy(): void {
    this.clearInterval();
  }

  // ── Drag & Drop ────────────────────────────────────────────────────────────

  @HostListener('window:dragover', ['$event'])
  onWindowDragover(e: DragEvent): void { e.preventDefault(); }

  @HostListener('window:drop', ['$event'])
  onWindowDrop(e: DragEvent): void { e.preventDefault(); }

  onDragover(e: DragEvent): void {
    e.preventDefault();
    this.dragOver.set(true);
  }

  onDragleave(): void {
    this.dragOver.set(false);
  }

  onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragOver.set(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) this.handleFile(file);
  }

  onFileInput(e: Event): void {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (file) this.handleFile(file);
  }

  // ── File handling ──────────────────────────────────────────────────────────

  handleFile(file: File): void {
    this.fileError.set(null);

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      this.fileError.set('Le fichier doit être un PDF (.pdf).');
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      this.fileError.set('Le fichier est trop volumineux (max 10 Mo).');
      return;
    }

    this.startAnalysis(file);
  }

  // ── Analysis ───────────────────────────────────────────────────────────────

  startAnalysis(file: File): void {
    this.phase.set('loading');
    this.selectedSection.set(null);
    this.startLoadingMessages();

    this.svc.analyzeContract(file).subscribe({
      next: res => {
        this.clearInterval();
        if (res.success && res.data) {
          this.analysis.set(res.data.analysis);
          this.phase.set('result');
        } else {
          this.phase.set('upload');
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur d\'analyse.' });
        }
      },
      error: err => {
        this.clearInterval();
        this.phase.set('upload');
        const msg = err?.error?.feedback?.message ?? 'Erreur lors de l\'analyse. Réessayez.';
        this.toast.showToast({ level: 'error', message: msg });
      },
    });
  }

  reset(): void {
    this.phase.set('upload');
    this.analysis.set(null);
    this.selectedSection.set(null);
    this.selectedCritical.set(null);
    this.fileError.set(null);
    this.clearInterval();
  }

  // ── Section detail ─────────────────────────────────────────────────────────

  toggleSection(section: ContractSection): void {
    const current = this.selectedSection();
    this.selectedSection.set(current === section ? null : section);
  }

  toggleCritical(article: CriticalArticle): void {
    const current = this.selectedCritical();
    this.selectedCritical.set(current === article ? null : article);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  riskLabel(risk: string): string {
    return { ok: 'OK', attention: 'Attention', risque: 'Risque', critique: 'Critique' }[risk] ?? risk;
  }

  private startLoadingMessages(): void {
    this.msgIdx = 0;
    this.loadingMessage.set(LOADING_MESSAGES[0]);
    this.msgInterval = setInterval(() => {
      this.msgIdx = (this.msgIdx + 1) % LOADING_MESSAGES.length;
      this.loadingMessage.set(LOADING_MESSAGES[this.msgIdx]);
    }, 5000);
  }

  private clearInterval(): void {
    if (this.msgInterval !== null) {
      clearInterval(this.msgInterval);
      this.msgInterval = null;
    }
  }
}
