import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { MobileMaquetteService, VocalTrack } from './mobile-maquette.service';

// ── Stubs minimaux ────────────────────────────────────────────────────────────

class AuthServiceStub {
  isPremium = () => false;
  getToken  = () => 'tok';
}

class ProcessorStub {
  async processVocalTrack(): Promise<Float32Array> { return new Float32Array(100); }
  async mixAndExport(): Promise<Blob> { return new Blob(['mp3'], { type: 'audio/mpeg' }); }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fakeBlob(): Blob { return new Blob(['pcm'], { type: 'audio/pcm-f32' }); }

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('MobileMaquetteService', () => {

  let svc: MobileMaquetteService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        MobileMaquetteService,
        { provide: 'AuthService',               useClass: AuthServiceStub  },
        { provide: 'MobileAudioProcessorService', useClass: ProcessorStub  },
      ],
    });
    svc = TestBed.inject(MobileMaquetteService);
  });

  // ── addTrack ────────────────────────────────────────────────────────────────

  it('addTrack() crée une piste avec état empty', () => {
    const id = svc.addTrack();
    const track = svc.tracks().find(t => t.id === id);
    expect(track).toBeDefined();
    expect(track!.trackState).toBe('empty');
    expect(track!.rawBlob).toBeNull();
    expect(track!.name).toMatch(/^Voix \d+$/);
  });

  it('addTrack() incrémente le compteur dans le nom', () => {
    svc.addTrack();
    const id2 = svc.addTrack();
    const t2 = svc.tracks().find(t => t.id === id2)!;
    expect(t2.name).toBe('Voix 2');
  });

  it('addTrack() retourne un id unique à chaque appel', () => {
    const id1 = svc.addTrack();
    const id2 = svc.addTrack();
    expect(id1).not.toBe(id2);
  });

  // ── removeTrack ─────────────────────────────────────────────────────────────

  it('removeTrack() supprime la piste correcte', () => {
    const id1 = svc.addTrack();
    const id2 = svc.addTrack();
    svc.removeTrack(id1);
    expect(svc.tracks().find(t => t.id === id1)).toBeUndefined();
    expect(svc.tracks().find(t => t.id === id2)).toBeDefined();
  });

  it('removeTrack() sur id inexistant ne lève pas d\'erreur', () => {
    expect(() => svc.removeTrack('unknown')).not.toThrow();
  });

  // ── canAddTrack ─────────────────────────────────────────────────────────────

  it('canAddTrack() retourne true en dessous de la limite free', () => {
    expect(svc.canAddTrack()).toBe(true);
    svc.addTrack();
    expect(svc.canAddTrack()).toBe(true);
  });

  it('canAddTrack() retourne false à la limite de 2 pistes (compte free)', () => {
    svc.addTrack();
    svc.addTrack();
    expect(svc.canAddTrack()).toBe(false);
  });

  // ── setRecording / setRecorded ───────────────────────────────────────────────

  it('setRecording() passe l\'état à recording', () => {
    const id = svc.addTrack();
    svc.setRecording(id);
    expect(svc.tracks().find(t => t.id === id)!.trackState).toBe('recording');
  });

  it('setRecorded() stocke le blob et la waveform', () => {
    const id    = svc.addTrack();
    const blob  = fakeBlob();
    const wave  = Array(120).fill(0.5);
    svc.setRecorded(id, blob, wave, 42);

    const t = svc.tracks().find(x => x.id === id)!;
    expect(t.trackState).toBe('recorded');
    expect(t.rawBlob).toBe(blob);
    expect(t.waveform).toEqual(wave);
    expect(t.duration).toBe(42);
  });

  it('setRecorded() invalide le processedBlob (re-enregistrement)', () => {
    const id = svc.addTrack();
    // Simuler un processedBlob existant
    svc['_patchTrack'](id, { processedBlob: fakeBlob() });
    expect(svc.tracks().find(t => t.id === id)!.processedBlob).not.toBeNull();

    svc.setRecorded(id, fakeBlob(), [], 10);
    expect(svc.tracks().find(t => t.id === id)!.processedBlob).toBeNull();
  });

  // ── renameTrack ─────────────────────────────────────────────────────────────

  it('renameTrack() met à jour le nom de la piste', () => {
    const id = svc.addTrack();
    svc.renameTrack(id, 'Refrain');
    expect(svc.tracks().find(t => t.id === id)!.name).toBe('Refrain');
  });

  it('renameTrack() trim les espaces', () => {
    const id = svc.addTrack();
    svc.renameTrack(id, '  Couplet  ');
    expect(svc.tracks().find(t => t.id === id)!.name).toBe('Couplet');
  });

  it('renameTrack() ignore un nom vide', () => {
    const id = svc.addTrack();
    const originalName = svc.tracks().find(t => t.id === id)!.name;
    svc.renameTrack(id, '   ');
    expect(svc.tracks().find(t => t.id === id)!.name).toBe(originalName);
  });

  it('renameTrack() ignore un id inconnu sans erreur', () => {
    expect(() => svc.renameTrack('ghost', 'Test')).not.toThrow();
  });

  // ── updateSettings ──────────────────────────────────────────────────────────

  it('updateSettings() met à jour partiellement les settings', () => {
    const id = svc.addTrack();
    const origVol = svc.tracks().find(t => t.id === id)!.settings.volume;
    svc.updateSettings(id, { reverbWet: 0.8 });

    const t = svc.tracks().find(x => x.id === id)!;
    expect(t.settings.reverbWet).toBe(0.8);
    expect(t.settings.volume).toBe(origVol);  // inchangé
  });

  it('updateSettings() préserve le processedBlob quand autotune passe à OFF', () => {
    const id   = svc.addTrack();
    const proc = fakeBlob();
    svc['_patchTrack'](id, { processedBlob: proc, settings: { ...svc.tracks()[0].settings, useAutotune: true } });

    svc.updateSettings(id, { useAutotune: false });
    // processedBlob doit rester en cache pour le prochain toggle ON
    expect(svc.tracks().find(t => t.id === id)!.processedBlob).toBe(proc);
  });

  // ── reset ───────────────────────────────────────────────────────────────────

  it('reset() vide les pistes et les signaux d\'export', () => {
    svc.addTrack();
    svc.addTrack();
    svc['exportPct'].set(75);
    svc['exportStep'].set('Test');

    svc.reset();
    expect(svc.tracks()).toEqual([]);
    expect(svc.exportPct()).toBe(0);
    expect(svc.exportStep()).toBe('');
    expect(svc.isExporting()).toBe(false);
  });

  // ── _patchTrack (interne) ────────────────────────────────────────────────────

  it('_patchTrack() ne modifie que la piste ciblée', () => {
    const id1 = svc.addTrack();
    const id2 = svc.addTrack();
    svc['_patchTrack'](id1, { name: 'Modifiée' });

    expect(svc.tracks().find(t => t.id === id1)!.name).toBe('Modifiée');
    expect(svc.tracks().find(t => t.id === id2)!.name).toBe('Voix 2');
  });

  // ── undo (hasUndoFor / undoLastTake) ────────────────────────────────────────

  it('hasUndoFor retourne false avant tout enregistrement', () => {
    const id = svc.addTrack();
    expect(svc.hasUndoFor(id)).toBe(false);
  });

  it('hasUndoFor retourne false après le premier setRecorded (pas de prise précédente)', () => {
    const id = svc.addTrack();
    svc.setRecorded(id, fakeBlob(), [], 1);
    expect(svc.hasUndoFor(id)).toBe(false);
  });

  it('hasUndoFor retourne true après un deuxième setRecorded sur la même piste', () => {
    const id = svc.addTrack();
    svc.setRecorded(id, fakeBlob(), [], 1);
    svc.setRecorded(id, fakeBlob(), [], 2);
    expect(svc.hasUndoFor(id)).toBe(true);
  });

  it('undoLastTake retourne false si aucun undo disponible', () => {
    const id = svc.addTrack();
    expect(svc.undoLastTake(id)).toBe(false);
  });

  it('undoLastTake restaure le rawBlob, la waveform et la durée précédents', () => {
    const id    = svc.addTrack();
    const blob1 = fakeBlob();
    const wf1   = [0.3, 0.5, 0.2];
    svc.setRecorded(id, blob1, wf1, 10);
    svc.setRecorded(id, fakeBlob(), [0.9], 20);

    expect(svc.undoLastTake(id)).toBe(true);

    const t = svc.tracks().find(x => x.id === id)!;
    expect(t.rawBlob).toBe(blob1);
    expect(t.waveform).toEqual(wf1);
    expect(t.duration).toBe(10);
    expect(t.trackState).toBe('recorded');
  });

  it('undoLastTake restaure le processedBlob s\'il était présent', () => {
    const id       = svc.addTrack();
    const blob1    = fakeBlob();
    const proc1    = fakeBlob();
    svc.setRecorded(id, blob1, [], 1);
    svc['_patchTrack'](id, { processedBlob: proc1 });
    svc.setRecorded(id, fakeBlob(), [], 2);

    svc.undoLastTake(id);
    expect(svc.tracks().find(x => x.id === id)!.processedBlob).toBe(proc1);
  });

  it('un seul niveau d\'undo — le second appel retourne false', () => {
    const id = svc.addTrack();
    svc.setRecorded(id, fakeBlob(), [], 1);
    svc.setRecorded(id, fakeBlob(), [], 2);
    svc.undoLastTake(id);
    expect(svc.undoLastTake(id)).toBe(false);
  });

  it('reset() efface l\'état undo pour toutes les pistes', () => {
    const id = svc.addTrack();
    svc.setRecorded(id, fakeBlob(), [], 1);
    svc.setRecorded(id, fakeBlob(), [], 2);
    svc.reset();
    const id2 = svc.addTrack();
    expect(svc.hasUndoFor(id2)).toBe(false);
  });
});
