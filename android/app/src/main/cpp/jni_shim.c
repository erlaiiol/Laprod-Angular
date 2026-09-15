// jni_shim.c — pont JNI vers le crate Rust psola-ffi.
//
// Volontairement minimal et séparé du crate Rust lui-même (voir docs/roadmap.md, workspace à
// deux crates) : ce fichier traduit les types/conventions JNI (jlong, jfloatArray...) vers
// l'API C plate de psola_ffi.h, sans logique propre. Écrit à la main — pas de crate `jni`
// côté Rust, cohérent avec la philosophie "zéro dépendance" du chantier.
//
// Miroir du shim C++ historique (rubberband_processor.cpp, supprimé) : mêmes 8 fonctions
// JNI, même contrat côté Kotlin (PsolaProcessor.kt).

#include <jni.h>
#include "psola_ffi.h"

JNIEXPORT jlong JNICALL
Java_net_laprod_app_PsolaProcessor_nativeCreate(JNIEnv *env, jobject thiz, jint sampleRate) {
    (void) env;
    (void) thiz;
    // Formants toujours activés en production (miroir de OptionFormantPreserved sur l'ancien
    // shim Rubber Band) — pas de chemin sans LPC exposé côté app.
    PsolaHandle *handle = psola_create((double) sampleRate, 1);
    return (jlong) (intptr_t) handle;
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaProcessor_nativeDestroy(JNIEnv *env, jobject thiz, jlong handle) {
    (void) env;
    (void) thiz;
    psola_destroy((PsolaHandle *) (intptr_t) handle);
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaProcessor_nativeSetPitchCents(JNIEnv *env, jobject thiz,
                                                        jlong handle, jfloat cents) {
    (void) env;
    (void) thiz;
    psola_set_pitch_cents((PsolaHandle *) (intptr_t) handle, cents);
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaProcessor_nativeProcess(JNIEnv *env, jobject thiz,
                                                  jlong handle, jfloatArray input) {
    (void) thiz;
    jsize len = (*env)->GetArrayLength(env, input);
    jfloat *buf = (*env)->GetFloatArrayElements(env, input, NULL);
    if (!buf) return;

    psola_process((PsolaHandle *) (intptr_t) handle, buf, (size_t) len);

    // JNI_ABORT : lecture seule côté natif, aucune modification à recopier vers la JVM.
    (*env)->ReleaseFloatArrayElements(env, input, buf, JNI_ABORT);
}

JNIEXPORT jint JNICALL
Java_net_laprod_app_PsolaProcessor_nativeAvailable(JNIEnv *env, jobject thiz, jlong handle) {
    (void) env;
    (void) thiz;
    return psola_available((PsolaHandle *) (intptr_t) handle);
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaProcessor_nativeRetrieve(JNIEnv *env, jobject thiz,
                                                   jlong handle, jfloatArray output) {
    (void) thiz;
    jsize len = (*env)->GetArrayLength(env, output);
    jfloat *buf = (*env)->GetFloatArrayElements(env, output, NULL);
    if (!buf) return;

    psola_retrieve((PsolaHandle *) (intptr_t) handle, buf, (size_t) len);

    // 0 (pas JNI_ABORT) : les échantillons produits doivent être recopiés vers la JVM.
    (*env)->ReleaseFloatArrayElements(env, output, buf, 0);
}

JNIEXPORT jint JNICALL
Java_net_laprod_app_PsolaProcessor_nativeGetLatency(JNIEnv *env, jobject thiz, jlong handle) {
    (void) env;
    (void) thiz;
    return psola_get_latency((PsolaHandle *) (intptr_t) handle);
}

JNIEXPORT void JNICALL
Java_net_laprod_app_PsolaProcessor_nativeReset(JNIEnv *env, jobject thiz, jlong handle) {
    (void) env;
    (void) thiz;
    psola_reset((PsolaHandle *) (intptr_t) handle);
}
