import { Component, input, computed, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface QualityCriteria {
  label:   string;
  points:  number;
  met:     boolean;
  tip:     string;
}

@Component({
  selector: 'app-track-quality-score',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './track-quality-score.component.html',
  styleUrls: ['./track-quality-score.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TrackQualityScoreComponent {

  // ── Inputs ────────────────────────────────────────────────────────────────
  compact        = input<boolean>(false);
  title          = input<string>('');
  bpm            = input<number | null>(null);
  key            = input<string>('');
  style          = input<string>('');
  tagCount       = input<number>(0);
  similarCount   = input<number>(0);
  hasImage       = input<boolean>(false);
  hasWav         = input<boolean>(false);
  hasStems       = input<boolean>(false);
  priceMp3       = input<number>(0);
  priceWav       = input<number>(0);
  priceStems     = input<number>(0);
  sacemShare     = input<number>(50);

  // ── Criteria list ─────────────────────────────────────────────────────────
  readonly criteria = computed<QualityCriteria[]>(() => {
    const pricesOk = this.priceMp3() > 0 && this.priceWav() > 0 && this.priceStems() > 0
      ? this.priceMp3() < this.priceWav() && this.priceWav() < this.priceStems()
      : true;

    return [
      {
        label:  'Titre renseigné',
        points: 5,
        met:    this.title().trim().length > 0,
        tip:    'Ajoute un titre à ton beat.',
      },
      {
        label:  'BPM renseigné',
        points: 10,
        met:    (this.bpm() ?? 0) > 0,
        tip:    'Renseigne le BPM pour apparaître dans les filtres.',
      },
      {
        label:  'Tonalité renseignée',
        points: 10,
        met:    this.key().trim().length > 0,
        tip:    'Indique la tonalité pour faciliter la recherche.',
      },
      {
        label:  'Style renseigné',
        points: 10,
        met:    this.style().trim().length > 0,
        tip:    'Choisis un style pour mieux cibler ton audience.',
      },
      {
        label:  '3 tags minimum',
        points: 15,
        met:    this.tagCount() >= 3,
        tip:    'Ajoute au moins 3 tags pour améliorer ta visibilité.',
      },
      {
        label:  '2 artistes similaires',
        points: 10,
        met:    this.similarCount() >= 2,
        tip:    'Associe des artistes similaires pour les recommandations.',
      },
      {
        label:  'Image de couverture',
        points: 10,
        met:    this.hasImage(),
        tip:    'Upload une cover pour attirer l\'œil dans le catalogue.',
      },
      {
        label:  'Fichier WAV',
        points: 10,
        met:    this.hasWav(),
        tip:    'Propose le WAV pour augmenter ton prix de vente moyen.',
      },
      {
        label:  'Fichier STEMS',
        points: 10,
        met:    this.hasStems(),
        tip:    'Les STEMS sont les plus rentables — ne les oublie pas.',
      },
      {
        label:  'Prix cohérents',
        points: 5,
        met:    pricesOk,
        tip:    'MP3 < WAV < STEMS — assure-toi que tes prix sont croissants.',
      },
      {
        label:  'Part SACEM personnalisée',
        points: 5,
        met:    this.sacemShare() !== 50,
        tip:    'Personnalise ta part SACEM dans les paramètres du contrat.',
      },
    ];
  });

  readonly score = computed(() =>
    this.criteria().filter(c => c.met).reduce((sum, c) => sum + c.points, 0)
  );

  readonly level = computed((): 'incomplete' | 'correct' | 'good' | 'optimized' => {
    const s = this.score();
    if (s <= 40) return 'incomplete';
    if (s <= 70) return 'correct';
    if (s <= 85) return 'good';
    return 'optimized';
  });

  readonly levelLabel = computed(() => ({
    incomplete: 'Incomplet',
    correct:    'Correct',
    good:       'Bon',
    optimized:  'Optimisé',
  }[this.level()]));

  // ── SVG ring ──────────────────────────────────────────────────────────────
  readonly ringR     = 42;
  readonly ringCirc  = computed(() => 2 * Math.PI * this.ringR);
  readonly ringDash  = computed(() =>
    `${(this.score() / 100) * this.ringCirc()} ${this.ringCirc()}`
  );
}
