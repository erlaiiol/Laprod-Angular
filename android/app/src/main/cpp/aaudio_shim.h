// aaudio_shim.h — chargement paresseux d'AAudio via dlopen/dlsym.
//
// AAudio n'existe que depuis l'API 26, mais minSdkVersion=24 (android/variables.gradle) : lier
// directement `-laaudio` empêcherait `libpsola_processor.so` de charger sur API 24-25 (le
// linker dynamique résout tous les symboles requis au chargement). En résolvant chaque
// fonction via dlsym à l'exécution, l'appel échoue proprement (aaudio_shim_load() retourne
// false) sur les appareils sans AAudio, et l'app se rabat sur le chemin AudioRecord/AudioTrack
// existant (AudioCaptureLoop.kt) — voir docs/roadmap.md, chantier latence.
//
// Signatures vérifiées directement contre l'en-tête NDK réel (aaudio/AAudio.h, NDK 27), pas
// recopiées de mémoire.

#ifndef AAUDIO_SHIM_H
#define AAUDIO_SHIM_H

#include <aaudio/AAudio.h>
#include <dlfcn.h>
#include <stdbool.h>

typedef aaudio_result_t (*fn_AAudio_createStreamBuilder)(AAudioStreamBuilder **builder);
typedef void (*fn_AAudioStreamBuilder_setSampleRate)(AAudioStreamBuilder *builder, int32_t sampleRate);
typedef void (*fn_AAudioStreamBuilder_setChannelCount)(AAudioStreamBuilder *builder, int32_t channelCount);
typedef void (*fn_AAudioStreamBuilder_setFormat)(AAudioStreamBuilder *builder, aaudio_format_t format);
typedef void (*fn_AAudioStreamBuilder_setSharingMode)(AAudioStreamBuilder *builder, aaudio_sharing_mode_t mode);
typedef void (*fn_AAudioStreamBuilder_setDirection)(AAudioStreamBuilder *builder, aaudio_direction_t direction);
typedef void (*fn_AAudioStreamBuilder_setPerformanceMode)(AAudioStreamBuilder *builder, aaudio_performance_mode_t mode);
typedef void (*fn_AAudioStreamBuilder_setInputPreset)(AAudioStreamBuilder *builder, aaudio_input_preset_t preset);
typedef void (*fn_AAudioStreamBuilder_setUsage)(AAudioStreamBuilder *builder, aaudio_usage_t usage);
typedef void (*fn_AAudioStreamBuilder_setDataCallback)(AAudioStreamBuilder *builder, AAudioStream_dataCallback callback, void *userData);
typedef void (*fn_AAudioStreamBuilder_setErrorCallback)(AAudioStreamBuilder *builder, AAudioStream_errorCallback callback, void *userData);
typedef aaudio_result_t (*fn_AAudioStreamBuilder_openStream)(AAudioStreamBuilder *builder, AAudioStream **stream);
typedef aaudio_result_t (*fn_AAudioStreamBuilder_delete)(AAudioStreamBuilder *builder);
typedef aaudio_result_t (*fn_AAudioStream_requestStart)(AAudioStream *stream);
typedef aaudio_result_t (*fn_AAudioStream_requestStop)(AAudioStream *stream);
typedef aaudio_result_t (*fn_AAudioStream_close)(AAudioStream *stream);
typedef int32_t (*fn_AAudioStream_getSampleRate)(AAudioStream *stream);
typedef int32_t (*fn_AAudioStream_getFramesPerBurst)(AAudioStream *stream);
typedef const char *(*fn_AAudio_convertResultToText)(aaudio_result_t result);

typedef struct {
    fn_AAudio_createStreamBuilder createStreamBuilder;
    fn_AAudioStreamBuilder_setSampleRate setSampleRate;
    fn_AAudioStreamBuilder_setChannelCount setChannelCount;
    fn_AAudioStreamBuilder_setFormat setFormat;
    fn_AAudioStreamBuilder_setSharingMode setSharingMode;
    fn_AAudioStreamBuilder_setDirection setDirection;
    fn_AAudioStreamBuilder_setPerformanceMode setPerformanceMode;
    fn_AAudioStreamBuilder_setInputPreset setInputPreset;
    fn_AAudioStreamBuilder_setUsage setUsage;
    fn_AAudioStreamBuilder_setDataCallback setDataCallback;
    fn_AAudioStreamBuilder_setErrorCallback setErrorCallback;
    fn_AAudioStreamBuilder_openStream openStream;
    fn_AAudioStreamBuilder_delete deleteBuilder;
    fn_AAudioStream_requestStart requestStart;
    fn_AAudioStream_requestStop requestStop;
    fn_AAudioStream_close closeStream;
    fn_AAudioStream_getSampleRate getSampleRate;
    fn_AAudioStream_getFramesPerBurst getFramesPerBurst;
    fn_AAudio_convertResultToText convertResultToText;
    void *handle; // dlopen handle, pour dlclose (jamais fermé en pratique : durée de vie du process)
} AAudioShim;

// Charge libaaudio.so et résout toutes les fonctions requises. Retourne true si TOUTES ont
// été résolues (chargement partiel = échec propre, jamais un moteur à moitié fonctionnel).
static inline bool aaudio_shim_load(AAudioShim *shim) {
    void *h = dlopen("libaaudio.so", RTLD_NOW);
    if (!h) return false;
    shim->handle = h;

#define LOAD(field, name)                                                                        \
    do {                                                                                          \
        shim->field = (void *) dlsym(h, name);                                                    \
        if (!shim->field) return false;                                                           \
    } while (0)

    LOAD(createStreamBuilder, "AAudio_createStreamBuilder");
    LOAD(setSampleRate, "AAudioStreamBuilder_setSampleRate");
    LOAD(setChannelCount, "AAudioStreamBuilder_setChannelCount");
    LOAD(setFormat, "AAudioStreamBuilder_setFormat");
    LOAD(setSharingMode, "AAudioStreamBuilder_setSharingMode");
    LOAD(setDirection, "AAudioStreamBuilder_setDirection");
    LOAD(setPerformanceMode, "AAudioStreamBuilder_setPerformanceMode");
    LOAD(setInputPreset, "AAudioStreamBuilder_setInputPreset");
    LOAD(setUsage, "AAudioStreamBuilder_setUsage");
    LOAD(setDataCallback, "AAudioStreamBuilder_setDataCallback");
    LOAD(setErrorCallback, "AAudioStreamBuilder_setErrorCallback");
    LOAD(openStream, "AAudioStreamBuilder_openStream");
    LOAD(deleteBuilder, "AAudioStreamBuilder_delete");
    LOAD(requestStart, "AAudioStream_requestStart");
    LOAD(requestStop, "AAudioStream_requestStop");
    LOAD(closeStream, "AAudioStream_close");
    LOAD(getSampleRate, "AAudioStream_getSampleRate");
    LOAD(getFramesPerBurst, "AAudioStream_getFramesPerBurst");
    LOAD(convertResultToText, "AAudio_convertResultToText");

#undef LOAD
    return true;
}

#endif // AAUDIO_SHIM_H
