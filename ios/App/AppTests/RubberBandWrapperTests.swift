import XCTest
@testable import App

// ── RubberBandWrapperTests ────────────────────────────────────────────────────
//
// SETUP: These tests require the Rubber Band Library source to be present.
// See RubberBandWrapper.h for setup instructions.
// Once Rubber Band is compiled into the App target, these tests run as-is.

final class RubberBandWrapperTests: XCTestCase {

    private let sampleRate: Double = 48_000

    // Generates a 440 Hz sine wave at the given amplitude
    private func sineWave(frequency: Float, count: Int, amplitude: Float = 0.5) -> [Float] {
        (0..<count).map { i in
            amplitude * sinf(2 * Float.pi * frequency * Float(i) / Float(sampleRate))
        }
    }

    // ── Init & latency ────────────────────────────────────────────────────────

    func testInitSucceeds() {
        let rb = RubberBandWrapper(sampleRate: sampleRate)
        XCTAssertNotNil(rb)
    }

    func testLatencyIsPositive() {
        let rb = RubberBandWrapper(sampleRate: sampleRate)
        XCTAssertGreaterThan(rb.latencySamples, 0,
            "Rubber Band must report a positive startup latency in real-time mode")
    }

    func testLatencyIsReasonablySmall() {
        // OptionWindowShort targets ~512 samples; allow up to 2048 for safety
        let rb = RubberBandWrapper(sampleRate: sampleRate)
        XCTAssertLessThanOrEqual(rb.latencySamples, 2048,
            "OptionWindowShort should keep latency ≤ 2048 samples (~42 ms @ 48 kHz)")
    }

    // ── Render before feeding ─────────────────────────────────────────────────

    func testRenderBeforeFeedReturnsFrameCount() {
        let rb     = RubberBandWrapper(sampleRate: sampleRate)
        let output = [Float](repeating: 1.0, count: 512)
        let outPtr = UnsafeMutablePointer<Float>.allocate(capacity: 512)
        defer { outPtr.deallocate() }
        outPtr.initialize(from: output, count: 512)

        let n = rb.renderInto(outPtr, frameCount: 512)
        XCTAssertEqual(n, 512, "renderInto must always return frameCount")
    }

    func testRenderBeforeFeedOutputsZero() {
        let rb     = RubberBandWrapper(sampleRate: sampleRate)
        let outPtr = UnsafeMutablePointer<Float>.allocate(capacity: 256)
        defer { outPtr.deallocate() }

        rb.renderInto(outPtr, frameCount: 256)
        let allZero = (0..<256).allSatisfy { outPtr[$0] == 0 }
        XCTAssertTrue(allZero, "Output before any input has been fed must be silence")
    }

    // ── Feed → render pipeline ────────────────────────────────────────────────

    func testOutputIsNonZeroAfterPrefill() {
        let rb        = RubberBandWrapper(sampleRate: sampleRate)
        let blockSize = 512
        // Feed latency + 2 extra blocks to guarantee output is available
        let totalInput = rb.latencySamples + blockSize * 2
        let sine       = sineWave(frequency: 440, count: totalInput)

        sine.withUnsafeBufferPointer { ptr in
            var fed = 0
            while fed < totalInput {
                let chunk = min(blockSize, totalInput - fed)
                rb.feedInput(ptr.baseAddress! + fed, count: chunk)
                fed += chunk
            }
        }

        let outPtr = UnsafeMutablePointer<Float>.allocate(capacity: blockSize)
        defer { outPtr.deallocate() }
        rb.renderInto(outPtr, frameCount: blockSize)

        let maxAmp = (0..<blockSize).map { abs(outPtr[$0]) }.max() ?? 0
        XCTAssertGreaterThan(maxAmp, 0.01,
            "After prefill (\(rb.latencySamples) samples), output must be non-zero")
    }

    // ── Pitch shift ───────────────────────────────────────────────────────────

    func testSetPitchCentsDoesNotCrash() {
        let rb = RubberBandWrapper(sampleRate: sampleRate)
        rb.setPitchCents(0)
        rb.setPitchCents(200)
        rb.setPitchCents(-200)
        rb.setPitchCents(250)    // ±2.5 semitones max in our clamping
    }

    func testZeroCentsPreservesAmplitude() {
        // At 0-cent shift, RubberBand should pass audio through without major attenuation
        let rb        = RubberBandWrapper(sampleRate: sampleRate)
        let blockSize = 512
        let prefill   = rb.latencySamples + blockSize * 4
        let sine      = sineWave(frequency: 440, count: prefill, amplitude: 0.5)

        rb.setPitchCents(0)

        sine.withUnsafeBufferPointer { ptr in
            var fed = 0
            while fed < prefill {
                let chunk = min(blockSize, prefill - fed)
                rb.feedInput(ptr.baseAddress! + fed, count: chunk)
                fed += chunk
            }
        }

        let outPtr = UnsafeMutablePointer<Float>.allocate(capacity: blockSize)
        defer { outPtr.deallocate() }
        rb.renderInto(outPtr, frameCount: blockSize)

        let maxAmp = (0..<blockSize).map { abs(outPtr[$0]) }.max() ?? 0
        XCTAssertGreaterThan(maxAmp, 0.1,
            "0-cent shift must preserve signal amplitude (expected ~0.5, got \(maxAmp))")
    }

    // ── Reset ─────────────────────────────────────────────────────────────────

    func testResetClearsOutput() {
        let rb        = RubberBandWrapper(sampleRate: sampleRate)
        let blockSize = 512
        let prefill   = rb.latencySamples + blockSize * 2
        let sine      = sineWave(frequency: 440, count: prefill)

        sine.withUnsafeBufferPointer { ptr in
            rb.feedInput(ptr.baseAddress!, count: prefill)
        }

        // After reset, output should be silent again
        rb.reset()

        let outPtr = UnsafeMutablePointer<Float>.allocate(capacity: blockSize)
        defer { outPtr.deallocate() }
        rb.renderInto(outPtr, frameCount: blockSize)

        let maxAmp = (0..<blockSize).map { abs(outPtr[$0]) }.max() ?? 0
        XCTAssertLessThan(maxAmp, 0.01,
            "After reset, output must return to silence")
    }

    // ── Thread safety (smoke test) ────────────────────────────────────────────

    func testConcurrentPitchUpdatesDoNotCrash() {
        let rb  = RubberBandWrapper(sampleRate: sampleRate)
        let exp = expectation(description: "concurrent pitch updates")
        exp.expectedFulfillmentCount = 2

        DispatchQueue.global(qos: .userInteractive).async {
            for i in 0..<1000 {
                rb.setPitchCents(Float(i % 500) - 250)
            }
            exp.fulfill()
        }

        DispatchQueue.global(qos: .background).async {
            let blockSize = 128
            let sine      = self.sineWave(frequency: 440, count: blockSize * 100)
            let outPtr    = UnsafeMutablePointer<Float>.allocate(capacity: blockSize)
            defer { outPtr.deallocate() }
            sine.withUnsafeBufferPointer { ptr in
                for block in 0..<100 {
                    rb.feedInput(ptr.baseAddress! + block * blockSize, count: blockSize)
                    rb.renderInto(outPtr, frameCount: blockSize)
                }
            }
            exp.fulfill()
        }

        wait(for: [exp], timeout: 5)
    }
}
