import { Component, OnDestroy, HostListener, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  ContractAnalyzerService,
  ContractAnalysis,
  ContractSection,
} from '../../services/contract-analyzer.service';
import { ToastService } from '../../services/toast.service';

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
  selector: 'app-contract-analyzer',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './contract-analyzer.component.html',
  styleUrl: './contract-analyzer.component.scss',
})
export class ContractAnalyzerComponent implements OnDestroy {

  phase           = signal<'upload' | 'loading' | 'result'>('upload');
  analysis        = signal<ContractAnalysis | null>(null);
  selectedSection = signal<ContractSection | null>(null);
  loadingMessage  = signal(LOADING_MESSAGES[0]);
  dragOver        = signal(false);
  fileError       = signal<string | null>(null);

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
    this.fileError.set(null);
    this.clearInterval();
  }

  // ── Section detail ─────────────────────────────────────────────────────────

  toggleSection(section: ContractSection): void {
    const current = this.selectedSection();
    this.selectedSection.set(current === section ? null : section);
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
