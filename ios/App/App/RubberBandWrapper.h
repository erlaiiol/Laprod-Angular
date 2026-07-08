#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// ObjC wrapper around RubberBand's real-time, formant-preserving pitch shifter.
///
/// Thread model:
///   -setPitchCents:   thread-safe (std::atomic internally), call from detection timer
///   -feedInput:count: call from the AVAudioEngine tap callback (IO thread)
///   -renderInto:frameCount: call from AVAudioSourceNode render block (render thread)
///
/// SETUP — Rubber Band Library v3.x source is required:
///   1. Download from https://breakfastquay.com/rubberband/ (GPL or commercial)
///   2. Unzip and place so that the following header is accessible:
///         ios/App/App/rubberband/rubberband/RubberBandStretcher.h
///   3. In Xcode → App target → Build Settings:
///         Header Search Paths: $(SRCROOT)/App/App/rubberband  (non-recursive)
///   4. Add ALL .cpp files from rubberband/src/ to the App target's Compile Sources.
///      (Run `find rubberband/src -name "*.cpp"` for the full list.)
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

/// RubberBand's startup latency in samples (informational / for tests).
@property (nonatomic, readonly) NSInteger latencySamples;

@end

NS_ASSUME_NONNULL_END
