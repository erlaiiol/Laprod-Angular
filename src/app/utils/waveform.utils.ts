/**
 * Fonctions pures de manipulation de waveform.
 * Aucune dépendance Angular — testables sans TestBed.
 */

/**
 * Réduit un tableau de valeurs RMS brutes en `n` barres peak-normalisées [0–1].
 * Utilisé pour construire la miniature waveform après un enregistrement.
 */
export function computeWaveform(rms: number[], n: number): number[] {
  if (rms.length === 0) return Array<number>(n).fill(0.1);
  const step   = rms.length / n;
  const result = Array.from({ length: n }, (_, i) => {
    const chunk = rms.slice(Math.floor(i * step), Math.floor((i + 1) * step));
    return chunk.length > 0 ? Math.max(...chunk) : 0;
  });
  const peak = Math.max(...result, 0.001);
  return result.map(v => v / peak);
}

/**
 * Fusionne la waveform de la partie conservée (avant le point de punch-in)
 * avec celle de la nouvelle prise, proportionnellement à leur durée.
 *
 * @param existing  Waveform existante (avant punch-in)
 * @param fromSec   Secondes conservées depuis le début
 * @param totalSec  Durée totale finale
 * @param newWf     Waveform de la nouvelle prise
 * @param points    Nombre de barres cible (défaut : 120)
 */
export function spliceWaveform(
  existing: number[],
  fromSec:  number,
  totalSec: number,
  newWf:    number[],
  points    = 120,
): number[] {
  if (!existing.length) return newWf;
  const ratio     = Math.min(1, fromSec / totalSec);
  const keepN     = Math.round(points * ratio);
  const newN      = points - keepN;
  return [...existing.slice(0, keepN), ...resampleWaveform(newWf, newN)];
}

/**
 * Rééchantillonne une waveform vers une longueur cible par interpolation au
 * plus proche voisin. Retourne un tableau vide si `targetLen <= 0`.
 */
export function resampleWaveform(wf: number[], targetLen: number): number[] {
  if (targetLen <= 0) return [];
  if (wf.length === targetLen) return wf.slice();
  return Array.from({ length: targetLen }, (_, i) =>
    wf[Math.floor((i / targetLen) * wf.length)] ?? 0,
  );
}
