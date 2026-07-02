import { Component, Input, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LicenseService } from '../../services/license.service';

@Component({
  selector: 'app-license-badge',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './license-badge.component.html',
  styleUrls: ['./license-badge.component.scss'],
})
export class LicenseBadgeComponent {

  @Input() licenseStatus: string = 'active';
  @Input() isLifetime: boolean   = false;
  @Input() expiresAt: string | null = null;
  @Input() isExclusive: boolean  = false;

  get days(): number | null {
    if (!this.expiresAt) return null;
    const diff = new Date(this.expiresAt).getTime() - Date.now();
    return Math.ceil(diff / (1000 * 60 * 60 * 24));
  }

  get urgency(): 'lifetime' | 'streaming' | 'ok' | 'soon' | 'urgent' | 'expired' | 'renewed' | 'cancelled' {
    if (this.licenseStatus === 'renewed')   return 'renewed';
    if (this.licenseStatus === 'cancelled') return 'cancelled';
    if (this.licenseStatus === 'expired')   return 'expired';
    if (this.isLifetime) return 'lifetime';
    if (this.expiresAt === null) return 'streaming';
    const d = this.days;
    if (d === null || d < 0) return 'expired';
    if (d <= 7)  return 'urgent';
    if (d <= 30) return 'soon';
    return 'ok';
  }

  get label(): string {
    switch (this.urgency) {
      case 'lifetime':   return 'Droits à vie';
      case 'streaming':  return 'Streaming illimité';
      case 'renewed':    return 'Renouvelée';
      case 'cancelled':  return 'Annulée';
      case 'expired':    return 'Expirée';
      case 'urgent': {
        const d = this.days ?? 0;
        return d <= 1 ? 'Expire demain !' : `Expire dans ${d}j !`;
      }
      case 'soon':       return `Expire dans ${this.days}j`;
      case 'ok': {
        const d = this.days;
        return d !== null ? `Active — ${d}j` : 'Active';
      }
    }
  }

  get icon(): string {
    switch (this.urgency) {
      case 'lifetime':  return 'bi-infinity';
      case 'streaming': return 'bi-broadcast';
      case 'renewed':   return 'bi-arrow-clockwise';
      case 'cancelled': return 'bi-x-circle';
      case 'expired':   return 'bi-clock-history';
      case 'urgent':    return 'bi-exclamation-triangle-fill';
      case 'soon':      return 'bi-clock';
      case 'ok':        return 'bi-check-circle';
    }
  }
}
