import { Component, OnInit, signal, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TagsService, Tag } from '../../services/tags.service';
import { CudTrackService } from '../../services/cud-track.service';
import { AuthService } from '../../services/auth.service';
import { MUSICAL_KEYS } from '../../services/track.service';
import { UploadStatusService } from '../../services/upload-status.service';
import { Playlist, PlaylistService } from '../../services/playlist.service';



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

  readonly DEFAULT_CONTRACT_PRICES = {
    exclusive: 150, duration3y: 5, duration5y: 10, duration10y: 15, lifetime: 50,
    mechanical: 30, publicShow: 40, arrangement: 10, territoryEu: 5, territoryWorld: 10,
  };

  /* ── Form fields ───────────────────────────────────────────────────────── */
  title         = signal('');
  bpm           = signal<number | null>(null);
  key           = signal('');
  style         = signal('');
  priceMp3      = signal(9.99);
  priceWav      = signal(19.99);
  priceStems    = signal(49.99);
  sacemComposer = signal(50);

  // Prix des droits de contrat (initialisés aux prix standards)
  cpExclusive    = signal(this.DEFAULT_CONTRACT_PRICES.exclusive);
  cpDuration3y   = signal(this.DEFAULT_CONTRACT_PRICES.duration3y);
  cpDuration5y   = signal(this.DEFAULT_CONTRACT_PRICES.duration5y);
  cpDuration10y  = signal(this.DEFAULT_CONTRACT_PRICES.duration10y);
  cpLifetime     = signal(this.DEFAULT_CONTRACT_PRICES.lifetime);
  cpMechanical   = signal(this.DEFAULT_CONTRACT_PRICES.mechanical);
  cpPublicShow   = signal(this.DEFAULT_CONTRACT_PRICES.publicShow);
  cpArrangement  = signal(this.DEFAULT_CONTRACT_PRICES.arrangement);
  cpTerritoryEu  = signal(this.DEFAULT_CONTRACT_PRICES.territoryEu);
  cpTerritoryWorld = signal(this.DEFAULT_CONTRACT_PRICES.territoryWorld);

  /* ── Section states ─────────────────────────────────────────────────────── */
  showCustomPrices = signal(false);
  showPreview      = signal(false);
  showTags         = signal(false);
  showPlaylists    = signal(false);

  /* ── Playlists ──────────────────────────────────────────────────────────── */
  playlists            = signal<Playlist[]>([]);
  selectedPlaylistIds  = signal<number[]>([]);

  hasCustomPrices = computed(() => {
    const d = this.DEFAULT_CONTRACT_PRICES;
    return this.cpExclusive()    !== d.exclusive    ||
           this.cpDuration3y()   !== d.duration3y   ||
           this.cpDuration5y()   !== d.duration5y   ||
           this.cpDuration10y()  !== d.duration10y  ||
           this.cpLifetime()     !== d.lifetime      ||
           this.cpMechanical()   !== d.mechanical    ||
           this.cpPublicShow()   !== d.publicShow    ||
           this.cpArrangement()  !== d.arrangement   ||
           this.cpTerritoryEu()  !== d.territoryEu   ||
           this.cpTerritoryWorld() !== d.territoryWorld;
  });

  /* ── Preview state ──────────────────────────────────────────────────────── */
  previewFormat      = signal<'mp3' | 'wav' | 'stems'>('mp3');
  previewDuration    = signal<'stream' | '3' | '5' | '10' | 'lifetime'>('3');
  previewTerritory   = signal<'France' | 'Europe' | 'Monde entier'>('France');
  previewExclusive   = signal(false);
  previewMechanical  = signal(false);
  previewPublicShow  = signal(false);
  previewArrangement = signal(false);

  previewBasePrice = computed(() => {
    const f = this.previewFormat();
    if (f === 'wav')   return this.priceWav();
    if (f === 'stems') return this.priceStems();
    return this.priceMp3();
  });

  previewExclusiveFee = computed(() =>
    this.previewExclusive() ? this.cpExclusive() : 0
  );

  previewDurationFee = computed(() => {
    const d = this.previewDuration();
    if (d === '3')        return this.cpDuration3y();
    if (d === '5')        return this.cpDuration5y();
    if (d === '10')       return this.cpDuration10y();
    if (d === 'lifetime') return this.cpLifetime();
    return 0;
  });

  previewTerritoryFee = computed(() => {
    const t = this.previewTerritory();
    if (t === 'Europe')       return this.cpTerritoryEu();
    if (t === 'Monde entier') return this.cpTerritoryWorld();
    return 0;
  });

  previewSubtotal = computed(() =>
    this.previewBasePrice() + this.previewExclusiveFee() +
    this.previewDurationFee() + this.previewTerritoryFee()
  );

  previewMechanicalAutoIncluded = computed(() => this.previewSubtotal() >= 199.99);
  previewPublicShowAutoIncluded  = computed(() => this.previewSubtotal() >= 74.99);

  previewMechanicalFee = computed(() =>
    this.previewMechanical() && !this.previewMechanicalAutoIncluded()
      ? this.cpMechanical() : 0
  );

  previewPublicShowFee = computed(() =>
    this.previewPublicShow() && !this.previewPublicShowAutoIncluded()
      ? this.cpPublicShow() : 0
  );

  previewArrangementFee = computed(() =>
    this.previewArrangement() ? this.cpArrangement() : 0
  );

  previewTotal = computed(() =>
    this.previewSubtotal() +
    this.previewMechanicalFee() +
    this.previewPublicShowFee() +
    this.previewArrangementFee()
  );

  applyStandardPrices(): void {
    const d = this.DEFAULT_CONTRACT_PRICES;
    this.cpExclusive.set(d.exclusive);
    this.cpDuration3y.set(d.duration3y);
    this.cpDuration5y.set(d.duration5y);
    this.cpDuration10y.set(d.duration10y);
    this.cpLifetime.set(d.lifetime);
    this.cpMechanical.set(d.mechanical);
    this.cpPublicShow.set(d.publicShow);
    this.cpArrangement.set(d.arrangement);
    this.cpTerritoryEu.set(d.territoryEu);
    this.cpTerritoryWorld.set(d.territoryWorld);
  }

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

  canSubmit = computed(() =>
    !!this.title().trim() &&
    !!this.bpm() && this.bpm()! >= 60 && this.bpm()! <= 220 &&
    !!this.key() &&
    !!this.style() &&
    !!this.fileMp3() &&
    !this.loading(),
  );

  constructor(
    private tagsService:      TagsService,
    private cudTrackService:  CudTrackService,
    private router:           Router,
    readonly auth:            AuthService,
    private uploadStatusSvc:  UploadStatusService,
    private playlistService:  PlaylistService,
  ) {
    effect(() => { if (this.previewMechanicalAutoIncluded()) this.previewMechanical.set(false); });
    effect(() => { if (this.previewPublicShowAutoIncluded())  this.previewPublicShow.set(false); });
  }

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.auth.me().subscribe();

    this.tagsService.getTags().subscribe({
      next: res => {
        if (res.success) {
          this.availableTags.set(res.data.tags);
          this.availableStyles.set(res.data.styles);
        }
      },
    });

    if (this.auth.isBeatmaker()) {
      this.playlistService.getMyPlaylists().subscribe({
        next: res => this.playlists.set(res.data ?? []),
      });
    }
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

  togglePlaylist(id: number): void {
    const current = this.selectedPlaylistIds();
    this.selectedPlaylistIds.set(
      current.includes(id) ? current.filter(p => p !== id) : [...current, id],
    );
  }

  onSubmit(): void {
    if (!this.canSubmit()) return;
    this.loading.set(true);
    this.error.set(null);

    const premiumFields = this.auth.isPremium() ? {
      price_stems:                    this.priceStems(),
      file_stems:                     this.fileStems() ?? undefined,
      contract_price_exclusive:       this.cpExclusive(),
      contract_price_duration_3y:     this.cpDuration3y(),
      contract_price_duration_5y:     this.cpDuration5y(),
      contract_price_duration_10y:    this.cpDuration10y(),
      contract_price_lifetime:        this.cpLifetime(),
      contract_price_mechanical:      this.cpMechanical(),
      contract_price_public_show:     this.cpPublicShow(),
      contract_price_arrangement:     this.cpArrangement(),
      contract_price_territory_eu:    this.cpTerritoryEu(),
      contract_price_territory_world: this.cpTerritoryWorld(),
    } : {};

    this.cudTrackService.postTrack({
      title:                    this.title(),
      bpm:                      this.bpm()!,
      key:                      this.key(),
      style:                    this.style(),
      price_mp3:                this.priceMp3(),
      price_wav:                this.priceWav(),
      sacem_percentage_composer: this.sacemComposer(),
      tag_ids:                  this.selectedTagIds().join(','),
      playlist_ids:             this.selectedPlaylistIds().length ? this.selectedPlaylistIds().join(',') : undefined,
      file_mp3:                 this.fileMp3()!,
      file_wav:                 this.fileWav() ?? undefined,
      file_image:               this.fileImage() ?? undefined,
      ...premiumFields,
    }).subscribe({
      next: res => {
        this.loading.set(false);
        

        if (res.success && res.data?.job_id) {
          this.auth.me().subscribe();  // rafraîchit le compteur de tokens
          this.uploadStatusSvc.startPolling(res.data.job_id, res.data.title, res.data.image_url);
          this.router.navigate(['/']);
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
    this.applyStandardPrices();
    this.selectedTagIds.set([]);
    this.fileMp3.set(null);
    this.fileWav.set(null);
    this.fileStems.set(null);
    this.fileImage.set(null);
    this.error.set(null);
  }
}
