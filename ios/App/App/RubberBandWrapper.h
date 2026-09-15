#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// ObjC wrapper around the in-house real-time, formant-preserving pitch shifter — replaces
/// Rubber Band Library (GPL-3.0/commercial). See docs/roadmap.md for the full rationale.
///
/// The pitch shifter itself lives in the Rust workspace at the repo root
/// (native/psola-dsp + native/psola-ffi) — this file is now only an Objective-C++ bridge to
/// its plain C API (psola_ffi.h). The Rust static library is (re)built for the current
/// platform/architecture by an Xcode "Run Script" build phase on the App target (see
/// project.pbxproj) before this file is compiled — no binary is committed to the repo, mirroring
/// how the Android CMake build invokes `cargo build` on every Gradle build.
///
/// Thread model (unchanged from the Rubber Band version):
///   -setPitchCents:   thread-safe (atomic internally, on the Rust side), call from detection timer
///   -feedInput:count: call from the AVAudioEngine tap callback (IO thread)
///   -renderInto:frameCount: call from AVAudioSourceNode render block (render thread)
@interface RubberBandWrapper : NSObject

- (instancetype)initWithSampleRate:(double)sampleRate;

/// Thread-safe pitch update; may be called from any thread.
- (void)setPitchCents:(float)cents;

/// Feed raw mono float32 PCM to the pitch shifter. Call from the tap IO thread.
- (void)feedInput:(const float *)input count:(NSInteger)count;

/// Produce pitch-shifted output into `output` (mono float32, `frameCount` samples).
/// Returns `frameCount` always; the buffer is silence-padded during startup latency.
/// Must be called from the AVAudioSourceNode render block.
- (NSInteger)renderInto:(float *)output frameCount:(NSInteger)frameCount;

/// Reset internal state; call when the engine restarts.
- (void)reset;

/// The engine's structural startup latency in samples (informational / for tests).
@property (nonatomic, readonly) NSInteger latencySamples;

@end

NS_ASSUME_NONNULL_END
