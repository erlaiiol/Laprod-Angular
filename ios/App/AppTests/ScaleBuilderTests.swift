import XCTest
@testable import App

// ── ScaleBuilderTests ─────────────────────────────────────────────────────────
//
// Setup Xcode :
//   File → New → Target → Unit Testing Bundle → nommer "AppTests"
//   Tous les fichiers de ce répertoire sont ajoutés automatiquement au target.
//   Swift Package : aucune dépendance externe requise.

final class ScaleBuilderTests: XCTestCase {

    // ── Parsing de la clé ─────────────────────────────────────────────────────

    func testCMajorParsed() {
        let result = ScaleBuilder.parse(key: "C major")
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.rootIndex, 0)
        XCTAssertEqual(result?.intervals, ScaleBuilder.majorIntervals)
    }

    func testFSharpMinorParsed() {
        let result = ScaleBuilder.parse(key: "F# minor")
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.rootIndex, 6)
        XCTAssertEqual(result?.intervals, ScaleBuilder.minorIntervals)
    }

    func testBbMajorParsed() {
        let result = ScaleBuilder.parse(key: "Bb major")
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.rootIndex, 10)  // Bb = A# = 10
    }

    func testCbIsSameAsBNatural() {
        let cb = ScaleBuilder.parse(key: "Cb major")
        let b  = ScaleBuilder.parse(key: "B major")
        XCTAssertEqual(cb?.rootIndex, b?.rootIndex)
    }

    func testBSharpIsSameAsC() {
        let bs = ScaleBuilder.parse(key: "B# major")
        let c  = ScaleBuilder.parse(key: "C major")
        XCTAssertEqual(bs?.rootIndex, c?.rootIndex)
    }

    func testEmptyKeyReturnsNil() {
        XCTAssertNil(ScaleBuilder.parse(key: ""))
    }

    func testUnknownNoteReturnsNil() {
        XCTAssertNil(ScaleBuilder.parse(key: "Z major"))
    }

    func testMissingModeDefaultsToMajor() {
        // Clé sans mode → mode implicite = major
        let result = ScaleBuilder.parse(key: "A")
        XCTAssertNotNil(result)
        XCTAssertEqual(result?.intervals, ScaleBuilder.majorIntervals)
    }

    func testMinorKeywordCaseInsensitive() {
        let lower = ScaleBuilder.parse(key: "D minor")
        let upper = ScaleBuilder.parse(key: "D MINOR")
        XCTAssertEqual(lower?.intervals, upper?.intervals)
    }

    // ── Contenu de la gamme ───────────────────────────────────────────────────

    func testCMajorContains7IntervalsPerOctave() {
        // Sur 4 octaves (2–5), C major doit avoir 7 × 4 notes en [80, 1200]
        let freqs = ScaleBuilder.frequencies(for: "C major")
        // On ne teste pas exactement 28 car les limites Hz peuvent exclure certaines notes
        XCTAssertGreaterThanOrEqual(freqs.count, 20)
        XCTAssertLessThanOrEqual(freqs.count, 28)
    }

    func testAllFrequenciesInValidRange() {
        for key in ["C major", "F# minor", "Bb major", "G# minor", "Db major"] {
            let freqs = ScaleBuilder.frequencies(for: key)
            for f in freqs {
                XCTAssertGreaterThanOrEqual(f, 80.0,  "\(key): \(f) Hz < 80 Hz")
                XCTAssertLessThanOrEqual(f, 1_200.0,  "\(key): \(f) Hz > 1200 Hz")
            }
        }
    }

    func testFrequenciesAreSorted() {
        let freqs = ScaleBuilder.frequencies(for: "E minor")
        XCTAssertEqual(freqs, freqs.sorted())
    }

    func testA4Is440Hz() {
        // La gamme de A major doit contenir A4 = 440 Hz (± 0.01 Hz pour les flottants)
        let freqs = ScaleBuilder.frequencies(for: "A major")
        let a4 = freqs.min(by: { abs($0 - 440) < abs($1 - 440) })!
        XCTAssertEqual(a4, 440.0, accuracy: 0.1)
    }

    func testEmptyKeyReturnsEmptyArray() {
        XCTAssertTrue(ScaleBuilder.frequencies(for: "").isEmpty)
    }

    func testMajorAndMinorDiffer() {
        let major = ScaleBuilder.frequencies(for: "C major")
        let minor = ScaleBuilder.frequencies(for: "C minor")
        XCTAssertNotEqual(major, minor)
    }

    func testEnharmonicEquivalentsAreIdentical() {
        // F# major et Gb major sont enharmoniques → même gamme
        let fSharp = ScaleBuilder.frequencies(for: "F# major")
        let gFlat  = ScaleBuilder.frequencies(for: "Gb major")
        XCTAssertEqual(fSharp.count, gFlat.count)
        for (a, b) in zip(fSharp, gFlat) {
            XCTAssertEqual(a, b, accuracy: 0.001)
        }
    }

    // ── Fréquences connues dans C major ───────────────────────────────────────

    func testCMajorContainsC4() {
        // C4 (do médium) ≈ 261.63 Hz
        let freqs = ScaleBuilder.frequencies(for: "C major")
        let c4 = freqs.min(by: { abs($0 - 261.63) < abs($1 - 261.63) })!
        XCTAssertEqual(c4, 261.63, accuracy: 0.1)
    }

    func testCMajorDoesNotContainFSharp() {
        // F# (6e degré haussé) n'est pas dans C major
        let freqs = ScaleBuilder.frequencies(for: "C major")
        let fSharp4 = Float(369.99)
        let nearest = freqs.min(by: { abs($0 - fSharp4) < abs($1 - fSharp4) })!
        // La note la plus proche de F#4 en C major est soit F4 (349.23) soit G4 (392)
        let distanceToFSharp = abs(nearest - fSharp4)
        XCTAssertGreaterThan(distanceToFSharp, 10.0,
                             "F# semble être dans C major, ce qui est incorrect")
    }
}
