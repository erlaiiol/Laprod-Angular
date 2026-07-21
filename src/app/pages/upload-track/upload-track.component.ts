import { ChangeDetectionStrategy, Component, OnInit, signal, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { HttpEventType, HttpResponse } from '@angular/common/http';
import { switchMap } from 'rxjs';
import { TagsService, Tag } from '../../services/tags.service';
import { CudTrackService, UploadResponse } from '../../services/cud-track.service';
import { AuthService } from '../../services/auth.service';
import { MUSICAL_KEYS } from '../../services/track.service';
import { UploadStatusService } from '../../services/upload-status.service';
import { YoutubeTemplateService } from '../../services/youtube-template.service';
import { Playlist, PlaylistService } from '../../services/playlist.service';
import { PromoService, PromoCode } from '../../services/promo.service';
import { SimilarArtistsService, SimilarArtistScene } from '../../services/similar-artists.service';
import { environment } from '../../../environments/environment';
import { TourAnchorDirective } from '../../directives/tour-anchor.directive';
import { TourService } from '../../services/tour.service';



interface TagGroup {
  name:  string;
  color: string;
  tags:  Tag[];
}

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector:    'app-upload-track',
  standalone:  true,
  imports:     [CommonModule, FormsModule, RouterLink, TourAnchorDirective],
  templateUrl: './upload-track.component.html',
  styleUrl:    './upload-track.component.scss',
})
export class UploadTrackComponent implements OnInit {

  readonly DEFAULT_CONTRACT_PRICES = {
    exclusive: 150, duration10y: 15, lifetime: 50,
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

  /* ── Attestations légales (droits voisins / samples) ─────────────────────── */
  phonogramProducerAttested = signal(false);
  hasThirdPartySamples      = signal(false);
  sampleClearanceDetails    = signal('');

  // Prix des droits de contrat (initialisés aux prix standards)
  cpExclusive    = signal(this.DEFAULT_CONTRACT_PRICES.exclusive);
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
  showArtists      = signal(false);
  showPlaylists    = signal(false);

  /* ── Playlists ──────────────────────────────────────────────────────────── */
  playlists            = signal<Playlist[]>([]);
  selectedPlaylistIds  = signal<number[]>([]);

  /* ── Codes promo ─────────────────────────────────────────────────────────── */
  // On ne propose que les codes ciblés : ceux en « tous mes beats » couvrent déjà
  // ce nouveau beat, les rattacher un par un n'aurait aucun sens.
  promoCodes            = signal<PromoCode[]>([]);
  selectedPromoCodeIds  = signal<number[]>([]);
  showPromoCodes        = signal(false);

  selectablePromoCodes = computed(() =>
    this.promoCodes().filter(c => c.scope === 'track' && !c.applies_to_all && c.is_active),
  );
  globalPromoCodes = computed(() =>
    this.promoCodes().filter(c => c.scope === 'track' && c.applies_to_all && c.is_active),
  );

  togglePromoCode(id: number): void {
    this.selectedPromoCodeIds.update(ids =>
      ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id],
    );
  }

  isPromoCodeSelected(id: number): boolean {
    return this.selectedPromoCodeIds().includes(id);
  }

  hasCustomPrices = computed(() => {
    const d = this.DEFAULT_CONTRACT_PRICES;
    return this.cpExclusive()    !== d.exclusive    ||
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
  previewDuration    = signal<'stream' | '10' | 'lifetime'>('stream');
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

  // « Streaming seul » : aucun droit additionnel n'est concédé (même règle que
  // sur la page d'achat réelle, cf. streamOnly dans track-contract-config).
  // Sans ce garde-fou, la simulation montrerait au beatmaker des droits
  // cochables et facturés que l'acheteur n'obtiendrait jamais réellement.
  previewStreamOnly = computed(() => this.previewDuration() === 'stream');

  previewMechanicalAutoIncluded = computed(() => this.previewSubtotal() >= 199.99);
  previewPublicShowAutoIncluded  = computed(() => this.previewSubtotal() >= 74.99);

  previewMechanicalFee = computed(() =>
    !this.previewStreamOnly() && this.previewMechanical() && !this.previewMechanicalAutoIncluded()
      ? this.cpMechanical() : 0
  );

  previewPublicShowFee = computed(() =>
    !this.previewStreamOnly() && this.previewPublicShow() && !this.previewPublicShowAutoIncluded()
      ? this.cpPublicShow() : 0
  );

  previewArrangementFee = computed(() =>
    !this.previewStreamOnly() && this.previewArrangement() ? this.cpArrangement() : 0
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
  readonly availableKeys  = MUSICAL_KEYS;
  availableStyles         = signal<string[]>([]);
  availableTags           = signal<Tag[]>([]);
  selectedTagIds          = signal<number[]>([]);
  availableArtistScenes   = signal<SimilarArtistScene[]>([]);
  selectedArtistIds       = signal<number[]>([]);

  /* ── Auto-suggestion IA ─────────────────────────────────────────────────── */
  autoBpm   = signal(false);
  autoKey   = signal(false);
  autoStyle = signal(false);

  private _randomBpm(): number {
    const values = Array.from({ length: 17 }, (_, i) => 80 + i * 5); // 80..160 step 5
    return values[Math.floor(Math.random() * values.length)];
  }

  private _randomKey(): string {
    return MUSICAL_KEYS[Math.floor(Math.random() * MUSICAL_KEYS.length)];
  }

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

  submitErrors = computed(() => {
    const errs: string[] = [];
    if (!this.title().trim()) errs.push('Titre manquant');

    if (!this.autoBpm()) {
      if (!this.bpm())                                 errs.push('BPM manquant');
      else if (this.bpm()! < 60 || this.bpm()! > 220) errs.push('BPM invalide (60–220)');
    }
    if (!this.autoKey()   && !this.key())   errs.push('Tonalité non sélectionnée');
    if (!this.autoStyle() && !this.style()) errs.push('Style non sélectionné');
    if (!this.fileMp3() && !this.fileWav() && !this.fileStems()) {
      errs.push('Au moins un fichier audio requis (MP3, WAV ou archive stems)');
    }
    if (!this.phonogramProducerAttested()) {
      errs.push('Attestation producteur du phonogramme requise');
    }
    if (this.hasThirdPartySamples() && !this.sampleClearanceDetails().trim()) {
      errs.push('Merci de décrire le statut de clearance des samples');
    }
    return errs;
  });

  canSubmit = computed(() => this.submitErrors().length === 0 && !this.loading());

  stemsOnly = computed(() => !!this.fileStems() && !this.fileMp3() && !this.fileWav());

  constructor(
    private tagsService:           TagsService,
    private cudTrackService:       CudTrackService,
    private router:                Router,
    readonly auth:                 AuthService,
    private uploadStatusSvc:       UploadStatusService,
    private ytTemplateSvc:         YoutubeTemplateService,
    private playlistService:       PlaylistService,
    private similarArtistsSvc:     SimilarArtistsService,
    private tour:                  TourService,
    private promoService:          PromoService,
  ) {
    effect(() => { if (this.previewMechanicalAutoIncluded()) this.previewMechanical.set(false); });
    effect(() => { if (this.previewPublicShowAutoIncluded())  this.previewPublicShow.set(false); });
  }

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.auth.me().subscribe();

    // Délai : laisse le formulaire se peindre et les directives d'ancrage s'enregistrer.
    setTimeout(() => this.tour.maybeAutoStart('upload-track'), 900);

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

      // Codes promo existants du vendeur, pour les rattacher directement au beat.
      // Échec silencieux : la section promo est un bonus, son indisponibilité ne
      // doit jamais empêcher de publier un beat.
      this.promoService.list().subscribe({
        next:  res => this.promoCodes.set(res.data?.promo_codes ?? []),
        error: () => this.promoCodes.set([]),
      });
    }

    this.similarArtistsSvc.getSimilarArtists().subscribe({
      next: res => { if (res.success) this.availableArtistScenes.set(res.data.scenes); },
      error: () => {},
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

  toggleArtist(id: number): void {
    this.selectedArtistIds.update(arr =>
      arr.includes(id) ? arr.filter(x => x !== id) : [...arr, id]
    );
  }

  isArtistSelected(id: number): boolean {
    return this.selectedArtistIds().includes(id);
  }

  togglePlaylist(id: number): void {
    const current = this.selectedPlaylistIds();
    this.selectedPlaylistIds.set(
      current.includes(id) ? current.filter(p => p !== id) : [...current, id],
    );
  }

  /* ── YouTube template ──────────────────────────────────────────────────── */

  youtubeTemplate = computed(() => {
    const bpm = this.bpm();
    const key = this.key();
    const u     = this.auth.currentUser();
    const baseUrl = environment.apiUrl.includes('localhost')
      ? 'https://laprod.net'
      : window.location.origin;
    const trackUrl = `${baseUrl}/track/(ID disponible dans votre profil)`;

    const lines: string[] = [
      `⚠️ conditions et licences ⚠️`,
      ``,
      `Cette instrumentale est gratuite pour un usage non commercial.`,
      `Tu n'es pas autorisé à la diffuser sur les plateformes de streaming.`,
      `Pour toute utilisation sur une plateforme permettant une rémunération,`,
      `l'achat d'une licence est obligatoire: ${trackUrl}`,
      ``,
      `Free for non-commercial use only. Not allowed on streaming platforms.`,
      `A license must be purchased for any monetized use: ${trackUrl}`,
    ];

    if (bpm) lines.push(``, `BPM: ${bpm}`);
    if (key)  lines.push(`Key: ${key}`);

    if (u?.instagram) lines.push(``, `INSTAGRAM: ${u.instagram}`);
    if (u?.twitter)   lines.push(`TWITTER: ${u.twitter}`);
    if (u?.youtube)   lines.push(`YOUTUBE: ${u.youtube}`);
    if (u?.email)     lines.push(`EMAIL: ${u.email}`);

    return lines.join('\n');
  });

  onSubmit(): void {
    if (!this.canSubmit()) return;
    this.loading.set(true);
    this.error.set(null);

    // Pré-remplissage placeholder pour que la DB ne soit pas en attente
    if (this.autoBpm() && !this.bpm()) this.bpm.set(this._randomBpm());
    if (this.autoKey() && !this.key()) this.key.set(this._randomKey());
    if (this.autoStyle() && !this.style() && this.availableStyles().length > 0) {
      this.style.set(this.availableStyles()[0]);
    }

    const contractPrices = this.auth.isPremium() ? {
      contract_price_exclusive:       this.cpExclusive(),
      contract_price_duration_10y:    this.cpDuration10y(),
      contract_price_lifetime:        this.cpLifetime(),
      contract_price_mechanical:      this.cpMechanical(),
      contract_price_public_show:     this.cpPublicShow(),
      contract_price_arrangement:     this.cpArrangement(),
      contract_price_territory_eu:    this.cpTerritoryEu(),
      contract_price_territory_world: this.cpTerritoryWorld(),
    } : {};

    // Ouvrir le toast immédiatement, avec une prévisualisation locale de l'image.
    const localImageUrl = this.fileImage()
      ? URL.createObjectURL(this.fileImage()!)
      : null;
    this.uploadStatusSvc.openForUpload(this.title(), localImageUrl);

    // Rafraîchir le token si proche de l'expiration avant un upload potentiellement long
    this.auth.refreshIfExpiringSoon().pipe(
      switchMap(() => this.cudTrackService.postTrack({
        title:                    this.title(),
        bpm:                      this.bpm()!,
        key:                      this.key(),
        style:                    this.style(),
        price_mp3:                this.priceMp3(),
        price_wav:                this.priceWav(),
        price_stems:              this.priceStems(),
        sacem_percentage_composer: this.sacemComposer(),
        phonogram_producer_attested: this.phonogramProducerAttested(),
        has_third_party_samples:     this.hasThirdPartySamples(),
        sample_clearance_details:    this.sampleClearanceDetails().trim() || undefined,
        tag_ids:                  this.selectedTagIds().join(','),
        similar_artist_ids:       this.selectedArtistIds().length ? this.selectedArtistIds().join(',') : undefined,
        playlist_ids:             this.selectedPlaylistIds().length ? this.selectedPlaylistIds().join(',') : undefined,
        promo_code_ids:           this.selectedPromoCodeIds().length ? this.selectedPromoCodeIds().join(',') : undefined,
        file_mp3:                 this.fileMp3() ?? undefined,
        file_wav:                 this.fileWav() ?? undefined,
        file_stems:               this.fileStems() ?? undefined,
        file_image:               this.fileImage() ?? undefined,
        auto_bpm:                 this.autoBpm(),
        auto_key:                 this.autoKey(),
        auto_style:               this.autoStyle(),
        ...contractPrices,
      })),
    ).subscribe({
      next: event => {
        if (event.type === HttpEventType.UploadProgress) {
          const pct = event.total ? Math.round(event.loaded / event.total * 100) : 0;
          this.uploadStatusSvc.setUploadProgress(pct);

        } else if (event.type === HttpEventType.Response) {
          this.loading.set(false);
          const res = (event as HttpResponse<UploadResponse>).body;
          if (res?.success && res.data?.job_id) {
            this.auth.me().subscribe();
            this.uploadStatusSvc.startPolling(res.data.job_id);
            this.ytTemplateSvc.set(this.youtubeTemplate());
            this.router.navigate(['/']);
          } else {
            this.uploadStatusSvc.stopPolling();
            this.error.set(res?.feedback?.message ?? 'Erreur lors de la soumission.');
          }
        }
      },
      error: err => {
        this.loading.set(false);
        this.uploadStatusSvc.stopPolling();
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
    this.phonogramProducerAttested.set(false);
    this.hasThirdPartySamples.set(false);
    this.sampleClearanceDetails.set('');
    this.applyStandardPrices();
    this.selectedTagIds.set([]);
    this.fileMp3.set(null);
    this.fileWav.set(null);
    this.fileStems.set(null);
    this.fileImage.set(null);
    this.error.set(null);
  }
}
