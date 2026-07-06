import { Injectable } from '@angular/core';
import { Filesystem, Directory } from '@capacitor/filesystem';
import { Capacitor } from '@capacitor/core';

const DRAFTS_DIR = 'laprod_drafts';

export interface DraftEntry {
  filename: string;
  path:     string;
  uri:      string;
  mtime:    number;
}

@Injectable({ providedIn: 'root' })
export class DraftSaveService {

  readonly isNative = Capacitor.isNativePlatform();

  /**
   * Sauvegarde un Blob MP3 dans Documents/laprod_drafts/.
   * Retourne l'URI local du fichier, ou null si la plateforme ne supporte pas
   * le Filesystem (ex. navigateur web desktop).
   */
  async saveMp3(blob: Blob, label: string): Promise<string | null> {
    if (!this.isNative) return null;

    try {
      await this._ensureDir();
      const filename = `${label}_${Date.now()}.mp3`;
      const base64   = await this._blobToBase64(blob);

      const result = await Filesystem.writeFile({
        path:      `${DRAFTS_DIR}/${filename}`,
        data:      base64,
        directory: Directory.Documents,
        recursive: true,
      });

      return result.uri;
    } catch (err) {
      console.warn('[DraftSaveService] saveMp3 failed', err);
      return null;
    }
  }

  /** Liste tous les brouillons enregistrés, du plus récent au plus ancien. */
  async listDrafts(): Promise<DraftEntry[]> {
    if (!this.isNative) return [];

    try {
      const { files } = await Filesystem.readdir({
        path:      DRAFTS_DIR,
        directory: Directory.Documents,
      });

      return files
        .filter(f => f.name.endsWith('.mp3'))
        .map(f => ({
          filename: f.name,
          path:     `${DRAFTS_DIR}/${f.name}`,
          uri:      f.uri,
          mtime:    f.mtime ?? 0,
        }))
        .sort((a, b) => b.mtime - a.mtime);
    } catch {
      return [];
    }
  }

  /** Supprime un brouillon par son chemin relatif. */
  async deleteDraft(path: string): Promise<void> {
    if (!this.isNative) return;
    await Filesystem.deleteFile({ path, directory: Directory.Documents }).catch(() => {});
  }

  /** Supprime tous les brouillons plus vieux que `maxAgeDays` jours. */
  async pruneOld(maxAgeDays = 7): Promise<void> {
    const drafts   = await this.listDrafts();
    const cutoffMs = Date.now() - maxAgeDays * 86_400_000;
    await Promise.all(
      drafts.filter(d => d.mtime < cutoffMs).map(d => this.deleteDraft(d.path)),
    );
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  private async _ensureDir(): Promise<void> {
    try {
      await Filesystem.mkdir({
        path:      DRAFTS_DIR,
        directory: Directory.Documents,
        recursive: true,
      });
    } catch (err) {
      // iOS/Android/web formulent différemment mais mentionnent tous "already exist"
      // pour ce cas — à ignorer. Toute autre erreur (permission refusée, disque
      // plein...) doit remonter pour que saveMp3() échoue proprement au lieu
      // d'écrire dans un dossier qui n'existe peut-être pas réellement.
      const alreadyExists = err instanceof Error && /already exist/i.test(err.message);
      if (!alreadyExists) throw err;
    }
  }

  private _blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = () => {
        const result = reader.result as string;
        // "data:audio/mpeg;base64,<data>" → on ne veut que <data>
        resolve(result.split(',')[1]);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }
}
