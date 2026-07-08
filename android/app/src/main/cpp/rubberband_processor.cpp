#include <jni.h>
#include "rubberband/rubberband/RubberBandStretcher.h"
#include <atomic>
#include <cmath>
#include <vector>
#include <android/log.h>

#define TAG "RubberBandProcessor"

using namespace RubberBand;

// ── Processor ─────────────────────────────────────────────────────────────────
//
// One instance per AudioRecordingSession. All DSP calls (process / retrieve)
// come from TarsosDSP's IO coroutine — single-threaded. Only setPitchCents is
// called from a different thread (the pitch-detection handler), hence the atomic.

struct Processor {
    RubberBandStretcher stretcher;
    std::atomic<float>  pitchCents{0.0f};
    float               lastCents{0.0f};

    explicit Processor(int sampleRate)
        : stretcher(
            static_cast<size_t>(sampleRate),
            1,           // mono
            RubberBandStretcher::OptionProcessRealTime
          | RubberBandStretcher::OptionFormantPreserved
          | RubberBandStretcher::OptionPitchHighConsistency
          | RubberBandStretcher::OptionWindowShort
          | RubberBandStretcher::OptionThreadingNever,
            1.0,         // timeRatio = 1 (pitch-only, no time stretch)
            1.0          // initial pitch scale = unity
        )
    {}
};

// ── JNI helpers ───────────────────────────────────────────────────────────────

static inline Processor *toProc(jlong handle) {
    return reinterpret_cast<Processor *>(handle);
}

extern "C" {

// ── Create / destroy ──────────────────────────────────────────────────────────

JNIEXPORT jlong JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeCreate(JNIEnv *, jobject, jint sampleRate) {
    return reinterpret_cast<jlong>(new Processor(sampleRate));
}

JNIEXPORT void JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeDestroy(JNIEnv *, jobject, jlong handle) {
    delete toProc(handle);
}

// ── Pitch (any thread) ────────────────────────────────────────────────────────

JNIEXPORT void JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeSetPitchCents(JNIEnv *, jobject,
                                                             jlong handle, jfloat cents) {
    toProc(handle)->pitchCents.store(cents, std::memory_order_relaxed);
}

// ── Process (audio IO thread) ─────────────────────────────────────────────────

JNIEXPORT void JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeProcess(JNIEnv *env, jobject,
                                                       jlong handle, jfloatArray input) {
    Processor *p = toProc(handle);

    // Apply any pending pitch change at the start of each block
    float cents = p->pitchCents.load(std::memory_order_relaxed);
    if (cents != p->lastCents) {
        p->lastCents = cents;
        p->stretcher.setPitchScale(std::pow(2.0, static_cast<double>(cents) / 1200.0));
    }

    jsize   len  = env->GetArrayLength(input);
    jfloat *buf  = env->GetFloatArrayElements(input, nullptr);
    if (!buf) return;

    const float *ch[1] = { buf };
    p->stretcher.process(ch, static_cast<size_t>(len), false);

    env->ReleaseFloatArrayElements(input, buf, JNI_ABORT);
}

// ── Query available output ────────────────────────────────────────────────────

JNIEXPORT jint JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeAvailable(JNIEnv *, jobject, jlong handle) {
    return static_cast<jint>(toProc(handle)->stretcher.available());
}

// ── Retrieve output (audio IO thread) ────────────────────────────────────────

JNIEXPORT void JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeRetrieve(JNIEnv *env, jobject,
                                                        jlong handle, jfloatArray output) {
    jsize   len  = env->GetArrayLength(output);
    jfloat *buf  = env->GetFloatArrayElements(output, nullptr);
    if (!buf) return;

    float *ch[1] = { buf };
    toProc(handle)->stretcher.retrieve(ch, static_cast<size_t>(len));

    env->ReleaseFloatArrayElements(output, buf, 0);  // 0 = commit changes back to Java
}

// ── Latency ───────────────────────────────────────────────────────────────────

JNIEXPORT jint JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeGetLatency(JNIEnv *, jobject, jlong handle) {
    return static_cast<jint>(toProc(handle)->stretcher.getLatency());
}

// ── Reset ─────────────────────────────────────────────────────────────────────

JNIEXPORT void JNICALL
Java_net_laprod_app_RubberBandProcessor_nativeReset(JNIEnv *, jobject, jlong handle) {
    Processor *p   = toProc(handle);
    p->stretcher.reset();
    p->lastCents   = 0.0f;
    p->pitchCents.store(0.0f, std::memory_order_relaxed);
}

} // extern "C"
