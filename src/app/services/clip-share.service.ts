import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';

import { CLIP_CAMERA, ClipShortcut } from './clip-camera-plugin';
import { AuthService } from './auth.service';
import { environment } from '../../environments/environment';

/**
 * Mode Clip — partage et mesure (docs/roadmap.md § Chantier 4, Passe 3).
 *
 * - Feuille de partage système = voie principale (SMS, WhatsApp, TikTok,
 *   Instagram, YouTube…), avec le FICHIER MP4, jamais une URL.
 * - Raccourcis directs (story Instagram, TikTok) derrière environment.clipShortcuts,
 *   masqués si non configurés ou si l'app cible n'est pas installée.
 * - Légende copiée dans le presse-papiers : les réseaux ignorent souvent le
 *   texte passé avec une vidéo.
 * - Comptage : POST /api/clips/events, sans bloquer l'utilisateur.
 */

/** Lien public toujours absolu (la légende part sur d'autres apps). */
export const CLIP_PUBLIC_URL = 'https://laprod.net';

export type ClipEventAction = 'saved' | 'shared';

export interface ClipShareParams {
  path:        string;
  trackId:     number;
  clipUid:     string;
  beatmaker:   string;
  mode:        string;
  durationSec: number;
}

/** Lien de la légende, avec attribution UTM par plateforme. */
export function clipTrackLink(trackId: number, medium: string): string {
  const m = encodeURIComponent(medium || 'share');
  return `${CLIP_PUBLIC_URL}/track/${trackId}?utm_source=clip&utm_medium=${m}&utm_campaign=mode_clip`;
}

export function clipCaption(beatmaker: string, trackId: number, medium = 'share'): string {
  return `🎤 Sur un beat de @${beatmaker} — fait sur LaProd\n${clipTrackLink(trackId, medium)}`;
}

/** Nom court de la plateforme d'après l'identifiant renvoyé par la feuille de partage. */
export function shareMedium(target: string | undefined): string {
  const t = (target ?? '').toLowerCase();
  if (t.includes('instagram')) return 'instagram';
  if (t.includes('musically') || t.includes('tiktok') || t.includes('ugc.aweme')) return 'tiktok';
  if (t.includes('youtube')) return 'youtube';
  if (t.includes('whatsapp')) return 'whatsapp';
  if (t.includes('sms') || t.includes('message') || t.includes('messaging') || t.includes('mms')) return 'sms';
  if (t.includes('snapchat')) return 'snapchat';
  return 'share';
}

@Injectable()
export class ClipShareService {
  private readonly cam  = inject(CLIP_CAMERA);
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  readonly captionCopied = signal(false);
  readonly shared        = signal(false);
  readonly busy          = signal(false);
  readonly failed        = signal(false);
  readonly shortcuts     = signal<ClipShortcut[]>([]);

  reset(): void {
    this.captionCopied.set(false);
    this.shared.set(false);
    this.failed.set(false);
  }

  /** Raccourcis configurés ET dont l'app cible est installée. */
  async loadShortcuts(): Promise<void> {
    const cfg = environment.clipShortcuts;
    const wanted: ClipShortcut[] = [];
    if (cfg?.instagramAppId) wanted.push('instagram-story');
    if (cfg?.tiktok) wanted.push('tiktok');
    const available: ClipShortcut[] = [];
    for (const target of wanted) {
      const r = await this.cam.canShareTo({ target }).catch(() => ({ available: false }));
      if (r.available) available.push(target);
    }
    this.shortcuts.set(available);
  }

  async copyCaption(beatmaker: string, trackId: number, medium = 'share'): Promise<void> {
    try {
      await navigator.clipboard.writeText(clipCaption(beatmaker, trackId, medium));
      this.captionCopied.set(true);
    } catch {
      this.captionCopied.set(false);   // presse-papiers indisponible : le partage continue
    }
  }

  /** Feuille de partage système avec le MP4. */
  async shareSystem(p: ClipShareParams): Promise<void> {
    this.busy.set(true);
    this.failed.set(false);
    try {
      await this.copyCaption(p.beatmaker, p.trackId);
      const r = await this.cam.share({ path: p.path, text: clipCaption(p.beatmaker, p.trackId) });
      if (r.completed) {
        this.shared.set(true);
        this.track('shared', p, shareMedium(r.target));
      }
    } catch {
      this.failed.set(true);
    } finally {
      this.busy.set(false);
    }
  }

  async shareShortcut(target: ClipShortcut, p: ClipShareParams): Promise<void> {
    this.busy.set(true);
    this.failed.set(false);
    const medium = target === 'instagram-story' ? 'instagram' : 'tiktok';
    try {
      await this.copyCaption(p.beatmaker, p.trackId, medium);
      await this.cam.shareTo({ target, path: p.path, appId: environment.clipShortcuts?.instagramAppId || undefined });
      this.shared.set(true);
      this.track('shared', p, medium);
    } catch {
      this.failed.set(true);
    } finally {
      this.busy.set(false);
    }
  }

  /** Comptage, sans jamais gêner l'utilisateur (échec silencieux). */
  track(action: ClipEventAction, p: Omit<ClipShareParams, 'path' | 'beatmaker'>, target?: string): void {
    if (!this.auth.isLoggedIn()) return;
    this.http.post(`${environment.apiUrl}/api/clips/events`, {
      track_id:   p.trackId,
      clip_uid:   p.clipUid,
      mode:       p.mode,
      action,
      duration_s: Math.min(45, Math.round(p.durationSec)),
      ...(target ? { target } : {}),
    }).subscribe({ error: () => {} });
  }
}
