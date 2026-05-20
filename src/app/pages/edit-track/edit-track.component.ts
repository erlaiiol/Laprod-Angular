import { Component, inject, signal, OnInit } from '@angular/core';
import { CudTrackService } from '../../services/cud-track.service';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MUSICAL_KEYS, TrackDetail, TrackService } from '../../services/track.service';
import { FormsModule } from '@angular/forms';
import { Tag, TagsService } from '../../services/tags.service';

@Component({
  selector: 'app-edit-track',
  imports: [ CommonModule, RouterModule, FormsModule],
  templateUrl: './edit-track.component.html',
  styleUrl: './edit-track.component.scss',
})
export class EditTrackComponent implements OnInit {

  // UI
  loading = signal(true);
  error = signal<string | null>(null);
  success = signal(false);

  // Route param
  trackId : number = 0;


  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private cudTrackService = inject(CudTrackService); 
  private trackService = inject(TrackService);
  private tagsService = inject(TagsService);
  
  readonly DEFAULT_CONTRACT_PRICES = {
    exclusive: 150, duration3y: 5, duration5y: 10, duration10y: 15, lifetime: 50,
    mechanical: 30, publicShow: 40, arrangement: 10, territoryEu: 5, territoryWorld: 10,
  };

  //Form
  track = signal<TrackDetail | null >(null);
  title = signal('');
  bpm = signal<number | null>(null);
  key = signal('');
  style = signal('');
  priceMp3 = signal(0);
  priceWav = signal(0);
  priceStems = signal(0);
  selectedTagIds = signal<number[]>([]);
  fileImage = signal<File | null>(null);
  fileMp3 = signal<File | null>(null)
  fileWav = signal<File | null>(null);
  fileStems = signal<File | null>(null)

  // Prix des droits de contrat
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

  readonly availableKeys = MUSICAL_KEYS;

  availableTags = this.tagsService.tags;


  ngOnInit() : void {

    this.tagsService.loadTags();

    this.trackId = Number(this.route.snapshot.paramMap.get('id'));

    if (!this.trackId) {
      this.error.set('ID du track manquant. Erreur de navigation.');
      this.loading.set(false);
      return;
    }

      this.trackService.getTrackDetail(this.trackId).subscribe({
        next: (res) => {
          const track = res.data.track;

              this.title.set(track.title);
              this.bpm.set(track.bpm);
              this.key.set(track.key);
              this.style.set(track.style);
              this.priceMp3.set(track.price_mp3);
              this.priceWav.set(track.price_wav ?? 0);
              this.priceStems.set(track.price_stems ?? 0);
              this.selectedTagIds.set(track.tags.map(tag => tag.id));
              this.track.set(track);
              if (track.contract_prices) {
                const cp = track.contract_prices;
                this.cpExclusive.set(cp.exclusive);
                this.cpDuration3y.set(cp.duration_3y);
                this.cpDuration5y.set(cp.duration_5y);
                this.cpDuration10y.set(cp.duration_10y);
                this.cpLifetime.set(cp.lifetime);
                this.cpMechanical.set(cp.mechanical);
                this.cpPublicShow.set(cp.public_show);
                this.cpArrangement.set(cp.arrangement);
                this.cpTerritoryEu.set(cp.territory_eu);
                this.cpTerritoryWorld.set(cp.territory_world);
              }
            this.loading.set(false);

          }, error : () => {
            this.error.set('erreur lors du chargement du track');
            this.loading.set(false)
          }
  })

}

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholders/placeholder-track.png';
    return this.trackService.getStaticFileUrl(path);
  }

  toggleTag(id: number): void {
    const current = this.selectedTagIds();
    this.selectedTagIds.set(
      current.includes(id) ? current.filter(x => x !== id) : [...current, id]
    );
  }

  isTagSelected(id: number): boolean {
    return this.selectedTagIds().includes(id);
  }

  onFileSelected(event: Event, field: 'image' | 'wav' | 'stems' | 'mp3'): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (field === 'image') this.fileImage.set(file);
    if (field === 'wav')   this.fileWav.set(file);
    if (field === 'stems') this.fileStems.set(file);
    if (field === 'mp3')   this.fileMp3.set(file);
  }

  onSubmit() : void {
      // Construire le payload

      this.cudTrackService.putTrack(this.trackId, {
        title: this.title(),
        bpm: this.bpm()!,
        key: this.key(),
        style: this.style(),
        price_mp3: this.priceMp3(),
        price_wav: this.priceWav() ?? 0,
        price_stems: this.priceStems() ?? 0,
        tag_ids: this.selectedTagIds().join(','),
        file_mp3: this.fileMp3() ?? undefined,
        file_image: this.fileImage() ?? undefined,
        file_wav: this.fileWav() ?? undefined,
        file_stems: this.fileStems() ?? undefined,
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
      }).subscribe({
        next: res => {
          if (res.success) {
            this.success.set(true);
            setTimeout(() => this.router.navigate(['/track', this.trackId]), 2000);
          } else {
            this.error.set(res.error || 'Erreur inconnue lors de la mise à jour du track.');
          }
        },
        error: () => {
          this.error.set('Erreur lors de la mise à jour du track.');
        }
      })
    }
  }
