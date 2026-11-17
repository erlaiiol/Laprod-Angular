import { cropTake } from './take.utils';
import { encodeWav16 } from './wav.utils';

function b64(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

describe('cropTake', () => {
  it('retire exactement cropSec du début (float32)', () => {
    const sr = 1000;
    const pcm = new Float32Array(2000).map((_, i) => i / 2000);
    const r = cropTake({ pcmBase64: b64(new Uint8Array(pcm.buffer)), sampleRate: sr, format: 'float32' }, 0.25);
    expect(r.voiceSec).toBeCloseTo(1.75, 9);
    expect(r.rawBlob.type).toBe('audio/pcm-f32;rate=1000');
    expect(r.rms.length).toBe(Math.ceil(1750 / 1024));
  });

  it('int16 et recadrage plus long que la prise', () => {
    const pcm = new Int16Array(100).fill(1000);
    const r = cropTake({ pcmBase64: b64(new Uint8Array(pcm.buffer)), sampleRate: 100, format: 'int16' }, 5);
    expect(r.voiceSec).toBe(0);
  });
});

describe('encodeWav16', () => {
  it('en-tête RIFF stéréo correct', async () => {
    const blob = encodeWav16([new Float32Array([0, 1, -1]), new Float32Array([0.5, 0, 0])], 48000);
    const v = new DataView(await blob.arrayBuffer());
    const str = (o: number) => String.fromCharCode(v.getUint8(o), v.getUint8(o + 1), v.getUint8(o + 2), v.getUint8(o + 3));
    expect(str(0)).toBe('RIFF');
    expect(str(8)).toBe('WAVE');
    expect(v.getUint16(22, true)).toBe(2);
    expect(v.getUint32(24, true)).toBe(48000);
    expect(v.getUint32(40, true)).toBe(3 * 2 * 2);
    expect(v.getInt16(44 + 2, true)).toBe(16383);   // canal droit, 1re frame (0.5)
    expect(v.getInt16(44 + 4, true)).toBe(32767);   // canal gauche, 2e frame (1)
  });
});
