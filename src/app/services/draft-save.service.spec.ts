import { TestBed } from '@angular/core/testing';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { DraftSaveService, CAPACITOR_FILESYSTEM, IS_NATIVE_PLATFORM } from './draft-save.service';

// ── Mocks ─────────────────────────────────────────────────────────────────────
//
// Fournis via les tokens d'injection du service (pas vi.mock('@capacitor/...')) :
// remplacer ces modules entiers s'est révélé peu fiable dans la suite complète
// (hoisting Vitest partagé entre fichiers, cf. commentaire dans draft-save.service.ts)
// — l'injection Angular via TestBed est garantie indépendante de l'ordre d'exécution.

const mockMkdir      = vi.fn().mockResolvedValue({});
const mockWriteFile  = vi.fn().mockResolvedValue({ uri: 'file:///Documents/laprod_drafts/x.mp3' });
const mockReaddir    = vi.fn().mockResolvedValue({ files: [] });
const mockDeleteFile = vi.fn().mockResolvedValue({});

function resetMocks(): void {
  mockMkdir.mockClear().mockResolvedValue({});
  mockWriteFile.mockClear().mockResolvedValue({ uri: 'file:///Documents/laprod_drafts/x.mp3' });
  mockReaddir.mockClear().mockResolvedValue({ files: [] });
  mockDeleteFile.mockClear().mockResolvedValue({});
}

function makeBlob(content = 'audio'): Blob {
  return new Blob([content], { type: 'audio/mpeg' });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('DraftSaveService', () => {

  let svc: DraftSaveService;

  beforeEach(() => {
    resetMocks();
    TestBed.configureTestingModule({
      providers: [
        {
          provide: CAPACITOR_FILESYSTEM,
          useValue: {
            mkdir:      mockMkdir,
            writeFile:  mockWriteFile,
            readdir:    mockReaddir,
            deleteFile: mockDeleteFile,
          },
        },
        { provide: IS_NATIVE_PLATFORM, useValue: true },
      ],
    });
    svc = TestBed.inject(DraftSaveService);
  });

  // ── saveMp3 ──────────────────────────────────────────────────────────────

  it('saveMp3 retourne une URI en succès', async () => {
    const uri = await svc.saveMp3(makeBlob(), 'maquette');
    expect(uri).toMatch(/^file:\/\//);
  });

  it('saveMp3 appelle mkdir puis writeFile', async () => {
    await svc.saveMp3(makeBlob(), 'maquette');
    expect(mockMkdir).toHaveBeenCalledTimes(1);
    expect(mockWriteFile).toHaveBeenCalledTimes(1);
  });

  it('saveMp3 inclut le label dans le nom de fichier', async () => {
    await svc.saveMp3(makeBlob(), 'ma_prise');
    const path = mockWriteFile.mock.calls[0][0].path as string;
    expect(path).toMatch(/ma_prise_\d+\.mp3$/);
  });

  it('saveMp3 retourne null si writeFile échoue', async () => {
    mockWriteFile.mockRejectedValueOnce(new Error('disk full'));
    const uri = await svc.saveMp3(makeBlob(), 'maquette');
    expect(uri).toBeNull();
  });

  it('saveMp3 retourne null si mkdir échoue (erreur inattendue)', async () => {
    // mkdir lève si le dossier n'existe pas ET que la création échoue
    mockMkdir.mockRejectedValueOnce(new Error('permission denied'));
    const uri = await svc.saveMp3(makeBlob(), 'maquette');
    expect(uri).toBeNull();
  });

  // ── listDrafts ───────────────────────────────────────────────────────────

  it('listDrafts retourne [] si readdir vide', async () => {
    const drafts = await svc.listDrafts();
    expect(drafts).toEqual([]);
  });

  it('listDrafts filtre les fichiers non-mp3', async () => {
    mockReaddir.mockResolvedValueOnce({
      files: [
        { name: 'maquette_1.mp3', uri: 'file:///1.mp3', mtime: 1000 },
        { name: 'notes.txt',      uri: 'file:///n.txt',  mtime: 2000 },
      ],
    });
    const drafts = await svc.listDrafts();
    expect(drafts).toHaveLength(1);
    expect(drafts[0].filename).toBe('maquette_1.mp3');
  });

  it('listDrafts trie du plus récent au plus ancien', async () => {
    mockReaddir.mockResolvedValueOnce({
      files: [
        { name: 'a.mp3', uri: 'file:///a.mp3', mtime: 1000 },
        { name: 'b.mp3', uri: 'file:///b.mp3', mtime: 3000 },
        { name: 'c.mp3', uri: 'file:///c.mp3', mtime: 2000 },
      ],
    });
    const drafts = await svc.listDrafts();
    expect(drafts.map(d => d.filename)).toEqual(['b.mp3', 'c.mp3', 'a.mp3']);
  });

  it('listDrafts retourne [] si readdir échoue', async () => {
    mockReaddir.mockRejectedValueOnce(new Error('no dir'));
    const drafts = await svc.listDrafts();
    expect(drafts).toEqual([]);
  });

  // ── deleteDraft ──────────────────────────────────────────────────────────

  it('deleteDraft appelle deleteFile avec le chemin fourni', async () => {
    await svc.deleteDraft('laprod_drafts/test.mp3');
    expect(mockDeleteFile).toHaveBeenCalledWith(
      expect.objectContaining({ path: 'laprod_drafts/test.mp3' }),
    );
  });

  it('deleteDraft ne lève pas si deleteFile échoue', async () => {
    mockDeleteFile.mockRejectedValueOnce(new Error('not found'));
    await expect(svc.deleteDraft('missing.mp3')).resolves.not.toThrow();
  });

  // ── pruneOld ─────────────────────────────────────────────────────────────

  it('pruneOld supprime uniquement les fichiers plus vieux que maxAgeDays', async () => {
    const now   = Date.now();
    const old   = now - 8 * 86_400_000;
    const fresh = now - 2 * 86_400_000;
    mockReaddir.mockResolvedValueOnce({
      files: [
        { name: 'old.mp3',   uri: 'file:///old.mp3',   mtime: old   },
        { name: 'fresh.mp3', uri: 'file:///fresh.mp3', mtime: fresh },
      ],
    });
    await svc.pruneOld(7);
    expect(mockDeleteFile).toHaveBeenCalledTimes(1);
    const path = mockDeleteFile.mock.calls[0][0].path as string;
    expect(path).toContain('old.mp3');
  });

  it('pruneOld ne supprime rien si tous les fichiers sont récents', async () => {
    const now = Date.now();
    mockReaddir.mockResolvedValueOnce({
      files: [{ name: 'fresh.mp3', uri: 'file:///f.mp3', mtime: now - 86_400_000 }],
    });
    await svc.pruneOld(7);
    expect(mockDeleteFile).not.toHaveBeenCalled();
  });
});
