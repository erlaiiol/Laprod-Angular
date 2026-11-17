/**
 * Prise voix native → Blob PCM prêt pour la maquette.
 *
 * Source unique du recadrage d'une prise, partagée par le studio
 * (_finalizeRecording) et le Mode Clip (prise faite pendant la vidéo) : il
 * n'existe pas de second chemin de recalage (docs/roadmap.md § 4.3).
 */

export interface NativeTakePcm {
  pcmBase64:  string;
  sampleRate: number;
  format:     'float32' | 'int16';
}

export interface CroppedTake {
  /** PCM brut, sample rate natif encodé dans le type MIME (cf. decodeBlob). */
  rawBlob:  Blob;
  /** Durée de la voix conservée (s). */
  voiceSec: number;
  /** RMS par bloc de 1024 échantillons — pour la miniature waveform. */
  rms:      number[];
}

const RMS_BLOCK = 1024;

/** Retire `cropSec` secondes du début de la prise (latences casque, voix captée trop tôt). */
export function cropTake(result: NativeTakePcm, cropSec: number): CroppedTake {
  const raw = Uint8Array.from(atob(result.pcmBase64), c => c.charCodeAt(0));
  const bytesPerSample = result.format === 'float32' ? 4 : 2;
  const cropSamples = Math.max(0, Math.round(cropSec * result.sampleRate));
  const voice    = raw.subarray(Math.min(raw.length, cropSamples * bytesPerSample));
  const voiceSec = voice.length / bytesPerSample / result.sampleRate;

  // Le sample rate natif réel (44,1 kHz Android, variable iOS) est encodé dans le MIME
  // type — decodeBlob() s'en sert pour rééchantillonner vers le SR canonique du pipeline
  // au lieu de supposer 48 kHz à tort (cf. MobileAudioProcessorService.decodeBlob).
  const mime = (result.format === 'float32' ? 'audio/pcm-f32' : 'audio/pcm-i16') + `;rate=${result.sampleRate}`;
  return { rawBlob: new Blob([voice], { type: mime }), voiceSec, rms: pcmRms(voice, result.format) };
}

function pcmRms(bytes: Uint8Array, format: 'float32' | 'int16'): number[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const bps = format === 'float32' ? 4 : 2;
  const n = Math.floor(bytes.byteLength / bps);
  const out: number[] = [];
  for (let start = 0; start < n; start += RMS_BLOCK) {
    const end = Math.min(n, start + RMS_BLOCK);
    let acc = 0;
    for (let i = start; i < end; i++) {
      const v = format === 'float32' ? view.getFloat32(i * 4, true) : view.getInt16(i * 2, true) / 32768;
      acc += v * v;
    }
    out.push(Math.sqrt(acc / Math.max(1, end - start)));
  }
  return out;
}
