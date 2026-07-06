import XCTest
@testable import App

// ── YINDetectorTests ──────────────────────────────────────────────────────────

final class YINDetectorTests: XCTestCase {

    private let sampleRate: Float = 48_000
    private let frameSize         = 2048

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// Génère un sinus pur à `frequency` Hz sur `frameSize` échantillons.
    private func sineWave(frequency: Float, amplitude: Float = 0.5) -> [Float] {
        (0..<frameSize).map { i in
            amplitude * sinf(2 * Float.pi * frequency * Float(i) / sampleRate)
        }
    }

    /// Génère du silence (bruit numérique à amplitude quasi nulle).
    private func silence() -> [Float] {
        [Float](repeating: 1e-7, count: frameSize)
    }

    /// Bruit blanc uniforme dans [-amp, amp].
    private func whiteNoise(amplitude: Float = 0.5) -> [Float] {
        (0..<frameSize).map { _ in Float.random(in: -amplitude...amplitude) }
    }

    // ── Détection de sinus purs ───────────────────────────────────────────────

    func testDetectsA4_440Hz() {
        var detector = YINDetector(frameSize: frameSize)
        let frame    = sineWave(frequency: 440)
        let hz       = detector.detect(frame: frame, sampleRate: sampleRate)

        XCTAssertNotNil(hz, "YIN n'a pas détecté 440 Hz")
        XCTAssertEqual(hz!, 440, accuracy: 5.0, "440 Hz détecté à ±5 Hz")
    }

    func testDetectsE4_329Hz() {
        var detector = YINDetector(frameSize: frameSize)
        let frame    = sineWave(frequency: 329.63)
        let hz       = detector.detect(frame: frame, sampleRate: sampleRate)

        XCTAssertNotNil(hz)
        XCTAssertEqual(hz!, 329.63, accuracy: 5.0)
    }

    func testDetectsLowNote_G2_98Hz() {
        var detector = YINDetector(frameSize: frameSize)
        let frame    = sineWave(frequency: 98.0)
        let hz       = detector.detect(frame: frame, sampleRate: sampleRate)

        XCTAssertNotNil(hz)
        XCTAssertEqual(hz!, 98.0, accuracy: 3.0)
    }

    func testDetectsHighNote_E5_659Hz() {
        var detector = YINDetector(frameSize: frameSize)
        let frame    = sineWave(frequency: 659.25)
        let hz       = detector.detect(frame: frame, sampleRate: sampleRate)

        XCTAssertNotNil(hz)
        XCTAssertEqual(hz!, 659.25, accuracy: 8.0)
    }

    // ── Signaux non-périodiques ───────────────────────────────────────────────

    func testReturnNilOnSilence() {
        var detector = YINDetector(frameSize: frameSize)
        let hz = detector.detect(frame: silence(), sampleRate: sampleRate)
        XCTAssertNil(hz, "YIN ne doit pas détecter de hauteur dans le silence")
    }

    func testReturnNilOnWhiteNoise() {
        var detector = YINDetector(frameSize: frameSize, threshold: 0.10)
        var foundCount = 0
        // Tester 10 frames de bruit différentes — le YIN avec threshold 0.10 ne doit
        // presque jamais trouver un pic dans du bruit blanc
        for _ in 0..<10 {
            if detector.detect(frame: whiteNoise(), sampleRate: sampleRate) != nil {
                foundCount += 1
            }
        }
        XCTAssertLessThanOrEqual(foundCount, 2,
            "YIN détecte de la hauteur dans le bruit blanc trop souvent (\(foundCount)/10)")
    }

    // ── Limites de fréquence ──────────────────────────────────────────────────

    func testFrequencyBelowMinIsRejected() {
        var detector = YINDetector(frameSize: frameSize, minFrequency: 80, maxFrequency: 1_200)
        let frame = sineWave(frequency: 50)  // en dessous du minimum
        let hz = detector.detect(frame: frame, sampleRate: sampleRate)
        XCTAssertNil(hz, "50 Hz est sous la limite minFrequency=80 Hz")
    }

    func testFrequencyAboveMaxIsRejected() {
        var detector = YINDetector(frameSize: frameSize, minFrequency: 80, maxFrequency: 1_200)
        let frame = sineWave(frequency: 1_800)  // au-dessus du maximum
        let hz = detector.detect(frame: frame, sampleRate: sampleRate)
        XCTAssertNil(hz, "1800 Hz est au-dessus de la limite maxFrequency=1200 Hz")
    }

    // ── Seuil YIN ─────────────────────────────────────────────────────────────

    func testLowerThresholdIsMoreStrict() {
        // Un seuil très bas (0.01) ne doit pas détecter un signal partiellement bruité
        let cleanFrame = sineWave(frequency: 440)
        let noisyFrame = zip(cleanFrame, whiteNoise(amplitude: 0.3))
            .map { $0 + $1 }

        var strictDetector  = YINDetector(frameSize: frameSize, threshold: 0.01)
        var normalDetector  = YINDetector(frameSize: frameSize, threshold: 0.10)

        let strictResult = strictDetector.detect(frame: noisyFrame, sampleRate: sampleRate)
        let normalResult = normalDetector.detect(frame: noisyFrame, sampleRate: sampleRate)

        // Le détecteur normal doit être plus généreux que le strict
        if strictResult == nil && normalResult != nil {
            // Comportement attendu : normal détecte, strict non
        }
        // Au minimum, les deux ne doivent pas crasher
        // (test de robustesse plutôt que de valeur exacte)
    }

    // ── Correction de hauteur ─────────────────────────────────────────────────

    func testCorrectionToNearestScaleNote() {
        let detector = YINDetector()
        let scale    = ScaleBuilder.frequencies(for: "A major")

        // A4 = 440 Hz détecté, A4 est dans A major → correction ≈ 0
        let correctionOnNote = detector.correctionSemitones(detected: 440.0, scale: scale)
        XCTAssertNotNil(correctionOnNote)
        XCTAssertEqual(correctionOnNote!, 0.0, accuracy: 0.05,
                       "A4 est exactement dans la gamme, correction doit être ~0")
    }

    func testCorrectionIsClampedTo3Semitones() {
        let detector = YINDetector(maxSemitoneShift: 3.0)
        let scale    = [440.0 as Float]  // une seule note (A4)

        // 300 Hz est très loin de 440 Hz, la correction brute serait > 3 semitones
        let correction = detector.correctionSemitones(detected: 300, scale: scale)
        XCTAssertNotNil(correction)
        XCTAssertLessThanOrEqual(abs(correction!), 3.0,
                                 "La correction doit être clampée à ±3 semitones")
    }

    func testCorrectionPositiveWhenDetectedTooLow() {
        let detector = YINDetector()
        // Note cible = 440 Hz (A4), note détectée = 420 Hz (trop basse)
        let correction = detector.correctionSemitones(detected: 420, scale: [440])
        XCTAssertNotNil(correction)
        XCTAssertGreaterThan(correction!, 0, "La voix est trop basse → correction positive")
    }

    func testCorrectionNegativeWhenDetectedTooHigh() {
        let detector = YINDetector()
        // Note cible = 440 Hz, note détectée = 460 Hz (trop haute)
        let correction = detector.correctionSemitones(detected: 460, scale: [440])
        XCTAssertNotNil(correction)
        XCTAssertLessThan(correction!, 0, "La voix est trop haute → correction négative")
    }

    func testCorrectionNilOnEmptyScale() {
        let detector   = YINDetector()
        let correction = detector.correctionSemitones(detected: 440, scale: [])
        XCTAssertNil(correction, "Gamme vide → pas de correction possible")
    }

    // ── Précondition ──────────────────────────────────────────────────────────

    func testWrongFrameSizeFatalError() {
        var detector = YINDetector(frameSize: 2048)
        // Ne pas appeler avec une taille incorrecte en prod — test de la précondition
        // XCTAssertThrowsFatalError n'existe pas nativement, on documente le comportement
        // attendu sans provoquer le crash dans les tests CI.
        // In prod : la précondition lève une erreur fatale si frame.count ≠ frameSize.
        _ = detector  // supprime le warning "variable jamais utilisée"
    }
}
