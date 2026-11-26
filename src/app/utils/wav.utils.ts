/**
 * Encodage WAV PCM 16 bits entrelacé (mono ou stéréo).
 *
 * Utilisé par le Mode Clip : l'audio du clip part du WAV et non du MP3 du
 * studio, pour éviter un double encodage avec perte (MP3 puis AAC dans le MP4,
 * piège docs/roadmap.md § 4.6.7).
 */
export function encodeWav16(channels: Float32Array[], sampleRate: number): Blob {
  const numCh   = channels.length;
  const frames  = numCh > 0 ? channels[0].length : 0;
  const dataLen = frames * numCh * 2;
  const buf     = new ArrayBuffer(44 + dataLen);
  const view    = new DataView(buf);

  const str = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  };

  str(0, 'RIFF');
  view.setUint32(4, 36 + dataLen, true);
  str(8, 'WAVE');
  str(12, 'fmt ');
  view.setUint32(16, 16, true);                       // taille du bloc fmt (PCM)
  view.setUint16(20, 1, true);                        // format PCM
  view.setUint16(22, numCh, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * numCh * 2, true);   // octets / s
  view.setUint16(32, numCh * 2, true);                // alignement de bloc
  view.setUint16(34, 16, true);                       // bits / échantillon
  str(36, 'data');
  view.setUint32(40, dataLen, true);

  let off = 44;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < numCh; c++) {
      const s = Math.max(-1, Math.min(1, channels[c][i]));
      view.setInt16(off, s < 0 ? s * 32768 : s * 32767, true);
      off += 2;
    }
  }
  return new Blob([buf], { type: 'audio/wav' });
}
