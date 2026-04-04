import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MixmasterService, MixEngineerPublic } from '../../../services/mixmaster.service';
import { AuthService } from '../../../services/auth.service';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-mixmaster-engineers',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './engineers.component.html',
  styleUrls: ['./engineers.component.scss'],
})
export class MixmasterEngineersComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  engineers = signal<MixEngineerPublic[]>([]);

  readonly auth    = inject(AuthService);
  private mixSvc   = inject(MixmasterService);

  ngOnInit(): void {
    this.mixSvc.getEngineers().subscribe({
      next: (res) => {
        if (res.success) this.engineers.set(res.data!.engineers);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de charger la liste des ingénieurs.');
        this.loading.set(false);
      },
    });
  }

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-avatar.png';
  }

  audioUrl(url: string | null): string {
    return url ? `${environment.apiUrl}${url}` : '';
  }

  priceRange(e: MixEngineerPublic): string {
    const ref = e.mixmaster_reference_price;
    const max = Math.round((ref * 0.35 + ref * 0.45 + ref * 0.20 + ref * 0.20 + (e.is_certified_producer_arranger ? ref * 0.60 : 0)) * 100) / 100;
    return `${e.mixmaster_price_min.toFixed(2)}€ — ${max.toFixed(2)}€`;
  }
}
