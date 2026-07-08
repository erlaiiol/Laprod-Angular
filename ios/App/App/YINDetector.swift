import Accelerate

/// Détecteur de hauteur YIN par autocorrélation NSDF, accéléré via vDSP.
///
/// Référence : de Cheveigné & Kawahara, "YIN, a fundamental frequency estimator
/// for speech and music", J. Acoust. Soc. Am. 111(4), 2002.
///
/// Conception :
///   - Tous les buffers intermédiaires sont pré-alloués à l'init → zéro allocation
///     dans le chemin temps-réel (`detect(frame:sampleRate:)`).
///   - La fonction de différence est calculée via `vDSP_vsub` + `vDSP_svesq`
///     (instructions SIMD), ce qui donne ~16-32× la vitesse d'une boucle scalaire.
///   - Interpolation parabolique au pic → précision sub-échantillon.
public struct YINDetector {

    // ── Configuration ──────────────────────────────────────────────────────────

    public let frameSize:      Int
    public let threshold:      Float  // seuil CMND — 0.10 est standard (papier §IV)
    public let minFrequency:   Float  // Hz
    public let maxFrequency:   Float  // Hz
    public let maxSemitoneShift: Float  // clamp sur la correction en semitones

    // ── Buffers pré-alloués ────────────────────────────────────────────────────

    private var diff:    [Float]  // fonction de différence d(τ)
    private var cmnd:    [Float]  // CMND normalisée cumulée
    private var tmp:     [Float]  // vecteur temporaire pour vDSP_vsub

    // ── Init ───────────────────────────────────────────────────────────────────

    public init(
        frameSize:         Int   = 2048,
        threshold:         Float = 0.14,   // 0.10 était trop strict pour les voix non entraînées
        minFrequency:      Float = 80.0,
        maxFrequency:      Float = 1_200.0,
        maxSemitoneShift:  Float = 3.0
    ) {
        self.frameSize        = frameSize
        self.threshold        = threshold
        self.minFrequency     = minFrequency
        self.maxFrequency     = maxFrequency
        self.maxSemitoneShift = maxSemitoneShift

        let half  = frameSize / 2
        diff  = [Float](repeating: 0, count: half)
        cmnd  = [Float](repeating: 0, count: half)
        tmp   = [Float](repeating: 0, count: frameSize)
    }

    // ── Détection ──────────────────────────────────────────────────────────────

    /// Détecte la fréquence fondamentale dans `frame`.
    /// - Parameters:
    ///   - frame: Exactement `frameSize` échantillons PCM Float32 mono.
    ///   - sampleRate: Fréquence d'échantillonnage (Hz).
    /// - Returns: Fréquence fondamentale en Hz, ou `nil` si non détectée.
    public mutating func detect(frame: [Float], sampleRate: Float) -> Float? {
        precondition(frame.count == frameSize,
                     "YINDetector: frame.count (\(frame.count)) ≠ frameSize (\(frameSize))")
        let half = frameSize / 2

        // ── Étape 1 : Fonction de différence ──────────────────────────────────
        // d(τ) = Σ_{j=0}^{W-1} (x[j] - x[j+τ])²
        // Implémentation vDSP : vsub (soustraction SIMD) + svesq (somme des carrés SIMD)
        diff[0] = 0
        frame.withUnsafeBufferPointer { xPtr in
            guard let xBase = xPtr.baseAddress else { return }
            for tau in 1..<half {
                let w = frameSize - tau
                // tmp[j] = x[j+tau] - x[j]
                vDSP_vsub(xBase,        1,   // vecteur A
                          xBase + tau,  1,   // vecteur B
                          &tmp,         1,   // sortie C = B - A
                          vDSP_Length(w))
                // diff[tau] = Σ tmp[j]²
                vDSP_svesq(tmp, 1, &diff[tau], vDSP_Length(w))
            }
        }

        // ── Étape 2 : CMND (Cumulative Mean Normalised Difference) ─────────────
        // cmnd[0] = 1 par convention (papier §II)
        // cmnd[τ] = d(τ) * τ / Σ_{j=1}^{τ} d(j)
        cmnd[0] = 1.0
        var runningSum: Float = 0
        for tau in 1..<half {
            runningSum += diff[tau]
            cmnd[tau] = runningSum > 0 ? diff[tau] * Float(tau) / runningSum : 1.0
        }

        // ── Étape 3 : Premier minimum local sous le seuil ─────────────────────
        // On cherche le tau minimum où cmnd[tau] < threshold ET
        // cmnd[tau] < cmnd[tau-1] ET cmnd[tau] <= cmnd[tau+1]
        let tauMin = Int(ceil(sampleRate / maxFrequency))
        let tauMax = Int(floor(sampleRate / minFrequency))
        guard tauMax < half else { return nil }

        for tau in max(2, tauMin)..<min(half - 1, tauMax + 1) {
            guard cmnd[tau] < threshold else { continue }
            guard cmnd[tau] < cmnd[tau - 1] && cmnd[tau] <= cmnd[tau + 1] else { continue }

            // ── Étape 4 : Interpolation parabolique (précision sub-échantillon) ──
            let s0 = cmnd[tau - 1], s1 = cmnd[tau], s2 = cmnd[tau + 1]
            let denom = 2 * (2 * s1 - s0 - s2)
            let tauRefined: Float
            if abs(denom) > 1e-6 {
                tauRefined = Float(tau) + (s0 - s2) / denom
            } else {
                tauRefined = Float(tau)
            }

            let hz = sampleRate / tauRefined
            if hz >= minFrequency && hz <= maxFrequency { return hz }
        }
        return nil
    }

    // ── Correction de hauteur ──────────────────────────────────────────────────

    /// Correction en semitones pour amener `detectedHz` vers la note cible la plus
    /// proche dans `scale`. Valeur clampée à ±`maxSemitoneShift`.
    /// - Returns: Correction en semitones, ou `nil` si `scale` est vide.
    public func correctionSemitones(detected detectedHz: Float, scale: [Float]) -> Float? {
        guard !scale.isEmpty, detectedHz > 0 else { return nil }

        // Note cible : minimise |log₂(scale[i] / detected)| (distance en semitones)
        let nearest = scale.min(by: {
            abs(log2f($0 / detectedHz)) < abs(log2f($1 / detectedHz))
        })!
        let semitones = 12 * log2f(nearest / detectedHz)
        return max(-maxSemitoneShift, min(maxSemitoneShift, semitones))
    }
}
