// aaudio_jni.c — pont JNI vers aaudio_engine.c (moteur audio bas niveau AAudio).
//
// Volontairement séparé de jni_shim.c (pont JNI du moteur PSOLA seul, utilisé par le chemin
// AudioCaptureLoop/fallback) — voir docs/roadmap.md. Écrit à la main, même discipline que
// jni_shim.c.

#include <jni.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct Engine Engine; // opaque côté JNI — défini dans aaudio_engine.c

Engine *aaudio_engine_create(int32_t sampleRate, bool useMonitor, bool monitorAutotune,
                              float voiceGain, bool formantPreservation);
void aaudio_engine_set_pitch_cents(Engine *e, float cents);
int32_t aaudio_engine_poll_status(Engine *e, float *out_level, float *out_pitch_hz);
size_t aaudio_engine_drain_recorded(Engine *e, float *out, size_t maxSamples);
void aaudio_engine_set_monitor_options(Engine *e, bool useMonitor, bool monitorAutotune,
                                        float voiceGain);
void aaudio_engine_destroy(Engine *e);

JNIEXPORT jlong JNICALL
Java_net_laprod_app_PsolaAudioEngine_nativeCreate(JNIEnv *env, jobject thiz, jint sampleRate,
                                                   jboolean useMonitor, jboolean monitorAutotune,
                                                   jfloat voiceGain, jboolean formantPreservation) {
    (void) env;
    (void) thiz;
    Engine *e = aaudio_engine_create(sampleRate, useMonitor != JNI_FALSE,
                                      monitorAutotune != JNI_FALSE, voiceGain,
                                      formantPreservation != JNI_FALSE);
    return (jlong) (intptr_t) e;
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaAudioEngine_nativeSetPitchCents(JNIEnv *env, jobject thiz, jlong handle,
                                                          jfloat cents) {
    (void) env;
    (void) thiz;
    aaudio_engine_set_pitch_cents((Engine *) (intptr_t) handle, cents);
}

// `outLevelPitch` : FloatArray Kotlin de taille 2, rempli [level, pitchHz] (pitchHz = NaN si
// rien de neuf). Retourne 1 si le flux a été déconnecté depuis le dernier appel, 0 sinon.
JNIEXPORT jint JNICALL
Java_net_laprod_app_PsolaAudioEngine_nativePollStatus(JNIEnv *env, jobject thiz, jlong handle,
                                                       jfloatArray outLevelPitch) {
    (void) thiz;
    float level = 0.0f, pitchHz = 0.0f;
    jint interrupted = aaudio_engine_poll_status((Engine *) (intptr_t) handle, &level, &pitchHz);

    jfloat tmp[2] = {level, pitchHz};
    (*env)->SetFloatArrayRegion(env, outLevelPitch, 0, 2, tmp);
    return interrupted;
}

JNIEXPORT jint JNICALL
Java_net_laprod_app_PsolaAudioEngine_nativeDrainRecorded(JNIEnv *env, jobject thiz, jlong handle,
                                                          jfloatArray out) {
    (void) thiz;
    jsize cap = (*env)->GetArrayLength(env, out);
    jfloat *buf = (*env)->GetFloatArrayElements(env, out, NULL);
    if (!buf) return 0;

    size_t drained =
        aaudio_engine_drain_recorded((Engine *) (intptr_t) handle, buf, (size_t) cap);

    (*env)->ReleaseFloatArrayElements(env, out, buf, 0);
    return (jint) drained;
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaAudioEngine_nativeSetMonitorOptions(JNIEnv *env, jobject thiz,
                                                              jlong handle, jboolean useMonitor,
                                                              jboolean monitorAutotune,
                                                              jfloat voiceGain) {
    (void) env;
    (void) thiz;
    aaudio_engine_set_monitor_options((Engine *) (intptr_t) handle, useMonitor != JNI_FALSE,
                                       monitorAutotune != JNI_FALSE, voiceGain);
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaAudioEngine_nativeDestroy(JNIEnv *env, jobject thiz, jlong handle) {
    (void) env;
    (void) thiz;
    aaudio_engine_destroy((Engine *) (intptr_t) handle);
}
