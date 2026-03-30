import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TagsService, Tag } from '../../services/tags.service';
import { UploadService } from '../../services/upload.service';
import { AuthService } from '../../services/auth.service';

const MUSICAL_KEYS: string[] = [
  'A minor',  'A major',
  'A# minor', 'A# major',
  'B minor',  'B major',
  'C minor',  'C major',
  'C# minor', 'C# major',
  'D minor',  'D major',
  'D# minor', 'D# major',
  'E minor',  'E major',
  'F minor',  'F major',
  'F# minor', 'F# major',
  'G minor',  'G major',
  'G# minor', 'G# major',
];

interface TagGroup {
  name:  string;
  color: string;
  tags:  Tag[];
}

@Component({
  selector:    'app-upload-track',
  standalone:  true,
  imports:     [CommonModule, FormsModule],
  templateUrl: './upload-track.component.html',
  styleUrl:    './upload-track.component.scss',
})
export class UploadTrackComponent implements OnInit {

  /* ── Form fields ───────────────────────────────────────────────────────── */
  title         = signal('');
  bpm           = signal<number | null>(null);
  key           = signal('');
  style         = signal('');
  priceMp3      = signal(9.99);
  priceWav      = signal(19.99);
  priceStems    = signal(49.99);
  sacemComposer = signal(50);

  /* ── Files ─────────────────────────────────────────────────────────────── */
  fileMp3   = signal<File | null>(null);
  fileWav   = signal<File | null>(null);
  fileStems = signal<File | null>(null);
  fileImage = signal<File | null>(null);

  /* ── Options ────────────────────────────────────────────────────────────── */
  readonly availableKeys = MUSICAL_KEYS;
  availableStyles        = signal<string[]>([]);
  availableTags          = signal<Tag[]>([]);
  selectedTagIds         = signal<number[]>([]);

  tagGroups = computed<TagGroup[]>(() => {
    const map    = new Map<string, TagGroup>();
    const groups: TagGroup[] = [];
    for (const tag of this.availableTags()) {
      const key = tag.category.name;
      if (!map.has(key)) {
        const g: TagGroup = { name: key, color: tag.category.color, tags: [] };
        map.set(key, g);
        groups.push(g);
      }
      map.get(key)!.tags.push(tag);
    }
    return groups;
  });

  /* ── State ──────────────────────────────────────────────────────────────── */
  loading = signal(false);
  error   = signal<string | null>(null);
  success = signal(false);

  canSubmit = computed(() =>
    !!this.title().trim() &&
    !!this.bpm() && this.bpm()! >= 60 && this.bpm()! <= 220 &&
    !!this.key() &&
    !!this.style() &&
    !!this.fileMp3() &&
    !this.loading(),
  );

  constructor(
    private tagsService:   TagsService,
    private uploadService: UploadService,
    private router:        Router,
    readonly auth:         AuthService,
  ) {}

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.tagsService.getTags().subscribe({
      next: res => {
        if (res.success) {
          this.availableTags.set(res.data.tags);
          this.availableStyles.set(res.data.styles);
        }
      },
    });
  }

  onFileSelected(event: Event, field: 'mp3' | 'wav' | 'stems' | 'image'): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if      (field === 'mp3')   this.fileMp3.set(file);
    else if (field === 'wav')   this.fileWav.set(file);
    else if (field === 'stems') this.fileStems.set(file);
    else                        this.fileImage.set(file);
  }

  toggleTag(id: number): void {
    const current = this.selectedTagIds();
    this.selectedTagIds.set(
      current.includes(id) ? current.filter(t => t !== id) : [...current, id],
    );
  }

  isTagSelected(id: number): boolean {
    return this.selectedTagIds().includes(id);
  }

  onSubmit(): void {
    if (!this.canSubmit()) return;
    this.loading.set(true);
    this.error.set(null);

    this.uploadService.uploadTrack({
      title:                    this.title(),
      bpm:                      this.bpm()!,
      key:                      this.key(),
      style:                    this.style(),
      price_mp3:                this.priceMp3(),
      price_wav:                this.priceWav(),
      price_stems:              this.priceStems(),
      sacem_percentage_composer: this.sacemComposer(),
      tag_ids:                  this.selectedTagIds().join(','),
      file_mp3:                 this.fileMp3()!,
      file_wav:                 this.fileWav()   ?? undefined,
      file_image:               this.fileImage() ?? undefined,
      file_stems:               this.fileStems() ?? undefined,
    }).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success) {
          this.success.set(true);
        } else {
          this.error.set(res.error ?? 'Erreur lors de l\'upload.');
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur. Réessayez.');
      },
    });
  }

  reset(): void {
    this.title.set('');
    this.bpm.set(null);
    this.key.set('');
    this.style.set('');
    this.priceMp3.set(9.99);
    this.priceWav.set(19.99);
    this.priceStems.set(49.99);
    this.sacemComposer.set(50);
    this.selectedTagIds.set([]);
    this.fileMp3.set(null);
    this.fileWav.set(null);
    this.fileStems.set(null);
    this.fileImage.set(null);
    this.success.set(false);
    this.error.set(null);
  }
}
