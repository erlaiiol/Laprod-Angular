import Foundation

/// Construit les fréquences cibles d'une gamme musicale à partir d'une clé textuelle.
///
/// Entrée attendue : `"<note> <mode>"`, ex. `"F# minor"`, `"Bb major"`, `"C major"`.
/// Renvoie les fréquences en Hz (80–1200 Hz, octaves 2–5) triées par ordre croissant.
///
/// Toutes les méthodes sont pures (pas d'effet de bord) → testabilité maximale.
public enum ScaleBuilder {

    // ── Chromatique ────────────────────────────────────────────────────────────

    /// Index chromatique (0 = C … 11 = B) pour chaque notation courante.
    /// Inclut les enharmoniques et les altérations doubles les plus fréquentes.
    static let chromaticIndex: [String: Int] = [
        "C": 0,  "B#": 0,
        "C#": 1, "Db": 1,
        "D": 2,
        "D#": 3, "Eb": 3,
        "E": 4,  "Fb": 4,
        "F": 5,  "E#": 5,
        "F#": 6, "Gb": 6,
        "G": 7,
        "G#": 8, "Ab": 8,
        "A": 9,
        "A#": 10, "Bb": 10,
        "B": 11,  "Cb": 11,
    ]

    /// Intervalles en demi-tons de la gamme majeure (mode ionien).
    static let majorIntervals = [0, 2, 4, 5, 7, 9, 11]

    /// Intervalles en demi-tons de la gamme mineure naturelle (mode éolien).
    static let minorIntervals = [0, 2, 3, 5, 7, 8, 10]

    // ── API publique ───────────────────────────────────────────────────────────

    /// Fréquences cibles pour une clé donnée.
    /// - Parameter key: ex. `"F# minor"`, `"C major"`, `""` (→ tableau vide).
    /// - Returns: Fréquences triées en Hz dans [80, 1200].
    public static func frequencies(for key: String) -> [Float] {
        guard let (rootIndex, intervals) = parse(key: key) else { return [] }

        var result: [Float] = []
        result.reserveCapacity(intervals.count * 4)  // 4 octaves × N notes

        // Octaves 2 à 5 → C2 ≈ 65 Hz, B5 ≈ 988 Hz
        for octave in 2...5 {
            for interval in intervals {
                let midi = (octave + 1) * 12 + rootIndex + interval
                let hz   = 440.0 * powf(2.0, Float(midi - 69) / 12.0)
                if hz >= 80 && hz <= 1_200 { result.append(hz) }
            }
        }
        return result.sorted()
    }

    // ── Parsing ────────────────────────────────────────────────────────────────

    /// Parse la clé et retourne (rootIndex, intervals), ou nil si la clé est invalide.
    static func parse(key: String) -> (rootIndex: Int, intervals: [Int])? {
        let parts = key.trimmingCharacters(in: .whitespaces)
                       .components(separatedBy: .whitespaces)
                       .filter { !$0.isEmpty }

        guard let noteName = parts.first,
              let rootIndex = chromaticIndex[noteName] else { return nil }

        let mode = parts.dropFirst().joined(separator: " ").lowercased()
        let intervals = mode.contains("min") ? minorIntervals : majorIntervals

        return (rootIndex, intervals)
    }
}
