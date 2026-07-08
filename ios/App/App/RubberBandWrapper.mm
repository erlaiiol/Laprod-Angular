#import "RubberBandWrapper.h"

// ── Rubber Band ───────────────────────────────────────────────────────────────
// See RubberBandWrapper.h for SETUP instructions before compiling.
#include "rubberband/rubberband/RubberBandStretcher.h"

#include <atomic>
#include <vector>
#include <algorithm>
#include <cstring>
#include <cmath>

using namespace RubberBand;

// ── Lock-free SPSC ring buffer ────────────────────────────────────────────────
//
// Single-producer (tap IO thread) / single-consumer (render thread).
// Capacity is a power of 2 so index wrapping is a bitmask (no modulo).
// Uses acquire/release semantics to ensure cross-thread visibility.

namespace {

template <size_t kCapacity>
struct SPSCRing {
    static_assert((kCapacity & (kCapacity - 1)) == 0,
                  "SPSCRing capacity must be a power of 2");
    static constexpr size_t kMask = kCapacity - 1;

    size_t write(const float *src, size_t n) noexcept {
        const size_t w     = _w.load(std::memory_order_relaxed);
        const size_t r     = _r.load(std::memory_order_acquire);
        const size_t free_ = kCapacity - (w - r);
        const size_t k     = std::min(n, free_);
        for (size_t i = 0; i < k; ++i) _buf[(w + i) & kMask] = src[i];
        _w.store(w + k, std::memory_order_release);
        return k;
    }

    size_t read(float *dst, size_t n) noexcept {
        const size_t r     = _r.load(std::memory_order_relaxed);
        const size_t w     = _w.load(std::memory_order_acquire);
        const size_t avail = w - r;
        const size_t k     = std::min(n, avail);
        for (size_t i = 0; i < k; ++i) dst[i] = _buf[(r + i) & kMask];
        _r.store(r + k, std::memory_order_release);
        return k;
    }

    size_t available() const noexcept {
        return _w.load(std::memory_order_acquire) -
               _r.load(std::memory_order_acquire);
    }

    void reset() noexcept {
        _r.store(0, std::memory_order_relaxed);
        _w.store(0, std::memory_order_relaxed);
    }

private:
    alignas(64) float               _buf[kCapacity]{};
    alignas(64) std::atomic<size_t> _w{0};
    alignas(64) std::atomic<size_t> _r{0};
};

} // namespace

// ── RubberBandWrapper ─────────────────────────────────────────────────────────

@implementation RubberBandWrapper {
    RubberBandStretcher        *_rb;
    std::atomic<float>          _pitchCents;
    float                       _lastCents;     // render-thread-local

    // 8 192 samples ≈ 170 ms @ 48 kHz — accommodates tap/render jitter
    SPSCRing<8192>              _ring;

    // Pre-allocated scratch buffer avoids heap allocation in the render thread.
    // Sized to 8 192 (well above any realistic getSamplesRequired() response).
    std::vector<float>          _inBuf;
}

- (instancetype)initWithSampleRate:(double)sampleRate {
    self = [super init];
    if (!self) return nil;

    // Options rationale:
    //   OptionProcessRealTime    — disables look-ahead; mandatory for live monitoring
    //   OptionFormantPreserved   — shifts glottal pulses without touching vocal-tract
    //                              resonances → no chipmunk / barrel artifacts
    //   OptionPitchHighConsistency — smooth scale transitions (vs HighSpeed which snaps)
    //   OptionWindowShort        — 512-sample processing window → ~10 ms startup latency
    //   OptionThreadingNever     — we handle threading via the ring buffer
    const int options = RubberBandStretcher::OptionProcessRealTime
                      | RubberBandStretcher::OptionFormantPreserved
                      | RubberBandStretcher::OptionPitchHighConsistency
                      | RubberBandStretcher::OptionWindowShort
                      | RubberBandStretcher::OptionThreadingNever;

    _rb = new RubberBandStretcher(
        static_cast<size_t>(sampleRate),
        1,      // mono
        options,
        1.0,    // timeRatio = 1 (pitch-only, no time stretch)
        1.0     // initial pitch scale = unity
    );

    _pitchCents.store(0.0f, std::memory_order_relaxed);
    _lastCents = 0.0f;
    _inBuf.reserve(8192);

    return self;
}

- (void)dealloc {
    delete _rb;
}

// ── Pitch update (any thread) ─────────────────────────────────────────────────

- (void)setPitchCents:(float)cents {
    _pitchCents.store(cents, std::memory_order_relaxed);
}

// ── Feed input (tap IO thread) ────────────────────────────────────────────────

- (void)feedInput:(const float *)input count:(NSInteger)count {
    // Overflows are silently discarded: if the ring is full, the render thread
    // is behind. Oldest unprocessed samples are the least relevant.
    _ring.write(input, static_cast<size_t>(count));
}

// ── Render (AVAudioSourceNode render block — audio render thread) ─────────────

- (NSInteger)renderInto:(float *)output frameCount:(NSInteger)frameCount {
    // Apply any pending pitch change (compare to render-thread-local _lastCents;
    // no lock needed since this method is always called from the same render thread)
    float cents = _pitchCents.load(std::memory_order_relaxed);
    if (cents != _lastCents) {
        _lastCents = cents;
        _rb->setPitchScale(std::pow(2.0, static_cast<double>(cents) / 1200.0));
    }

    // Feed as much as RubberBand currently requests from the ring buffer.
    // Feeding only what RubberBand needs keeps its internal state balanced
    // and prevents accumulating excess latency.
    size_t needed = _rb->getSamplesRequired();
    if (needed > 0) {
        size_t ringAvail = _ring.available();
        size_t toRead    = std::min({needed, ringAvail, static_cast<size_t>(8192)});
        if (toRead > 0) {
            _inBuf.resize(toRead);
            _ring.read(_inBuf.data(), toRead);
            const float *ch[1] = { _inBuf.data() };
            _rb->process(ch, toRead, false);
        }
        // If ring is insufficient we simply process fewer samples; RubberBand
        // will produce less output, resulting in brief silence — preferable
        // to injecting zero-padding artifacts.
    }

    // Retrieve available output; zero-fill the rest (startup latency / underrun)
    std::memset(output, 0, static_cast<size_t>(frameCount) * sizeof(float));
    int avail = _rb->available();
    if (avail > 0) {
        size_t toGet = std::min(static_cast<size_t>(avail),
                                static_cast<size_t>(frameCount));
        float *ch[1] = { output };
        _rb->retrieve(ch, toGet);
    }
    return frameCount;
}

// ── Reset ─────────────────────────────────────────────────────────────────────

- (void)reset {
    _ring.reset();
    _rb->reset();
    _lastCents = 0.0f;
}

// ── Latency ───────────────────────────────────────────────────────────────────

- (NSInteger)latencySamples {
    return static_cast<NSInteger>(_rb->getLatency());
}

@end
