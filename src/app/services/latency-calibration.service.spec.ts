import { TestBed } from '@angular/core/testing';
import { LatencyCalibrationService } from './latency-calibration.service';

describe('LatencyCalibrationService', () => {

  let svc: LatencyCalibrationService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [LatencyCalibrationService] });
    svc = TestBed.inject(LatencyCalibrationService);
  });

  afterEach(() => localStorage.clear());

  // ── Lecture sans entrée ──────────────────────────────────────────────────

  it('getEntry() retourne null si rien n\'est sauvegardé', () => {
    expect(svc.getEntry()).toBeNull();
  });

  it('latencyMs retourne 0 si non calibré', () => {
    expect(svc.latencyMs).toBe(0);
  });

  it('hasCalibration() retourne false si rien n\'est sauvegardé', () => {
    expect(svc.hasCalibration()).toBe(false);
  });

  it('deviceType retourne null si non calibré', () => {
    expect(svc.deviceType).toBeNull();
  });

  // ── Écriture + lecture ───────────────────────────────────────────────────

  it('save() persiste la latence et le type', () => {
    svc.save(187, 'bluetooth');
    const entry = svc.getEntry();
    expect(entry).not.toBeNull();
    expect(entry!.latencyMs).toBe(187);
    expect(entry!.deviceType).toBe('bluetooth');
  });

  it('latencyMs retourne la valeur sauvegardée', () => {
    svc.save(220, 'bluetooth');
    expect(svc.latencyMs).toBe(220);
  });

  it('deviceType retourne le type sauvegardé', () => {
    svc.save(10, 'wired');
    expect(svc.deviceType).toBe('wired');
  });

  it('hasCalibration() retourne true après save()', () => {
    svc.save(150, 'bluetooth');
    expect(svc.hasCalibration()).toBe(true);
  });

  it('save() écrase une entrée existante', () => {
    svc.save(100, 'bluetooth');
    svc.save(250, 'bluetooth');
    expect(svc.latencyMs).toBe(250);
  });

  it('save() inclut un timestamp récent', () => {
    const before = Date.now();
    svc.save(100, 'bluetooth');
    const after  = Date.now();
    expect(svc.getEntry()!.ts).toBeGreaterThanOrEqual(before);
    expect(svc.getEntry()!.ts).toBeLessThanOrEqual(after);
  });

  // ── Suppression ──────────────────────────────────────────────────────────

  it('clear() supprime l\'entrée', () => {
    svc.save(150, 'bluetooth');
    svc.clear();
    expect(svc.getEntry()).toBeNull();
    expect(svc.latencyMs).toBe(0);
    expect(svc.hasCalibration()).toBe(false);
  });

  // ── Résilience JSON corrompu ─────────────────────────────────────────────

  it('getEntry() retourne null si le JSON est corrompu', () => {
    localStorage.setItem('laprod_audio_latency_v1', 'NOT_JSON{{{');
    expect(svc.getEntry()).toBeNull();
  });
});
