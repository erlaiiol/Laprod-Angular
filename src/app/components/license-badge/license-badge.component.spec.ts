/**
 * Tests unitaires — LicenseBadgeComponent
 *
 * Comportements vérifiés :
 *
 * urgency() :
 *   • 'lifetime'  quand is_lifetime=true (droits complets à vie)
 *   • 'streaming' quand is_lifetime=false et expires_at=null (streaming seul)
 *   • 'ok'        quand expires_at dans le futur lointain
 *   • 'soon'      quand expires_at dans 30 jours ou moins
 *   • 'urgent'    quand expires_at dans 7 jours ou moins
 *   • 'expired'   quand expires_at dans le passé
 *   • 'renewed'   quand licenseStatus='renewed'
 *   • 'cancelled' quand licenseStatus='cancelled'
 *
 * label() :
 *   • "Droits à vie"       pour urgency 'lifetime'
 *   • "Streaming illimité" pour urgency 'streaming'
 *   • Pas "Licence à vie"  dans aucun cas
 *
 * icon() :
 *   • 'bi-infinity'   pour lifetime
 *   • 'bi-broadcast'  pour streaming
 */

import { TestBed } from '@angular/core/testing';
import { LicenseBadgeComponent } from './license-badge.component';

function makeComp(overrides: Partial<{
  licenseStatus: string;
  isLifetime: boolean;
  expiresAt: string | null;
  isExclusive: boolean;
}>): LicenseBadgeComponent {
  // reset avant de configurer — certains tests appellent makeComp() plusieurs fois
  // dans le même `it`, or TestBed refuse de reconfigurer un module déjà instancié.
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({ imports: [LicenseBadgeComponent] });
  const fixture = TestBed.createComponent(LicenseBadgeComponent);
  const comp    = fixture.componentInstance;
  comp.licenseStatus = overrides.licenseStatus ?? 'active';
  comp.isLifetime    = overrides.isLifetime    ?? false;
  comp.expiresAt     = overrides.expiresAt     !== undefined ? overrides.expiresAt : null;
  comp.isExclusive   = overrides.isExclusive   ?? false;
  fixture.detectChanges();
  return comp;
}

function futureDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}

function pastDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

// ── urgency() ─────────────────────────────────────────────────────────────────

describe('LicenseBadgeComponent — urgency()', () => {

  afterEach(() => TestBed.resetTestingModule());

  it("retourne 'lifetime' quand is_lifetime=true", () => {
    const c = makeComp({ isLifetime: true, expiresAt: null });
    expect(c.urgency).toBe('lifetime');
  });

  it("retourne 'streaming' quand is_lifetime=false et expires_at=null", () => {
    const c = makeComp({ isLifetime: false, expiresAt: null });
    expect(c.urgency).toBe('streaming');
  });

  it("retourne 'ok' quand expires_at dans le futur lointain", () => {
    const c = makeComp({ isLifetime: false, expiresAt: futureDate(90) });
    expect(c.urgency).toBe('ok');
  });

  it("retourne 'soon' quand expires_at dans 20 jours", () => {
    const c = makeComp({ isLifetime: false, expiresAt: futureDate(20) });
    expect(c.urgency).toBe('soon');
  });

  it("retourne 'urgent' quand expires_at dans 5 jours", () => {
    const c = makeComp({ isLifetime: false, expiresAt: futureDate(5) });
    expect(c.urgency).toBe('urgent');
  });

  it("retourne 'expired' quand expires_at dans le passé", () => {
    const c = makeComp({ isLifetime: false, expiresAt: pastDate(1) });
    expect(c.urgency).toBe('expired');
  });

  it("retourne 'expired' quand licenseStatus='expired' (prioritaire)", () => {
    const c = makeComp({ licenseStatus: 'expired', isLifetime: true, expiresAt: null });
    expect(c.urgency).toBe('expired');
  });

  it("retourne 'renewed' quand licenseStatus='renewed'", () => {
    const c = makeComp({ licenseStatus: 'renewed' });
    expect(c.urgency).toBe('renewed');
  });

  it("retourne 'cancelled' quand licenseStatus='cancelled'", () => {
    const c = makeComp({ licenseStatus: 'cancelled' });
    expect(c.urgency).toBe('cancelled');
  });

});

// ── label() ───────────────────────────────────────────────────────────────────

describe('LicenseBadgeComponent — label()', () => {

  afterEach(() => TestBed.resetTestingModule());

  it("affiche 'Droits sans échéance' pour une licence sans terme", () => {
    const c = makeComp({ isLifetime: true, expiresAt: null });
    expect(c.label).toBe('Droits sans échéance');
  });

  it("n'affiche jamais 'Licence à vie'", () => {
    const lifetime   = makeComp({ isLifetime: true, expiresAt: null });
    const streaming  = makeComp({ isLifetime: false, expiresAt: null });
    expect(lifetime.label).not.toBe('Licence à vie');
    expect(streaming.label).not.toBe('Licence à vie');
  });

  it("affiche 'Streaming illimité' pour une licence streaming seul", () => {
    const c = makeComp({ isLifetime: false, expiresAt: null });
    expect(c.label).toBe('Streaming illimité');
  });

  it("affiche 'Expirée' pour une licence expirée", () => {
    const c = makeComp({ licenseStatus: 'expired' });
    expect(c.label).toBe('Expirée');
  });

  it("affiche 'Renouvelée' pour une licence renouvelée", () => {
    const c = makeComp({ licenseStatus: 'renewed' });
    expect(c.label).toBe('Renouvelée');
  });

  it("affiche 'Annulée' pour une licence annulée", () => {
    const c = makeComp({ licenseStatus: 'cancelled' });
    expect(c.label).toBe('Annulée');
  });

});

// ── icon() ────────────────────────────────────────────────────────────────────

describe('LicenseBadgeComponent — icon()', () => {

  afterEach(() => TestBed.resetTestingModule());

  it("utilise 'bi-infinity' pour lifetime", () => {
    const c = makeComp({ isLifetime: true, expiresAt: null });
    expect(c.icon).toBe('bi-infinity');
  });

  it("utilise 'bi-broadcast' pour streaming", () => {
    const c = makeComp({ isLifetime: false, expiresAt: null });
    expect(c.icon).toBe('bi-broadcast');
  });

  it("utilise 'bi-check-circle' pour ok", () => {
    const c = makeComp({ isLifetime: false, expiresAt: futureDate(90) });
    expect(c.icon).toBe('bi-check-circle');
  });

});
