// aaudio_engine.c — moteur audio bas niveau AAudio (100% maison, pas d'Oboe) pour le
// monitoring vocal temps réel avec autotune.
//
// Remplace, quand disponible (API 26+, voir aaudio_shim.h), le chemin
// AudioRecord/AudioTrack (AudioCaptureLoop.kt) par des flux AAudio en mode
// AAUDIO_SHARING_MODE_EXCLUSIVE + AAUDIO_PERFORMANCE_MODE_LOW_LATENCY, qui permettent à AAudio
// de négocier le chemin MMAP (3-10ms de latence, contre 10-30ms pour AudioTrack/AudioRecord
// même en LOW_LATENCY — voir docs/roadmap.md, chantier latence, pour les sources).
//
// Toute la boucle chaude (capture → correction PSOLA → sortie) tourne ENTIÈREMENT dans les
// callbacks natifs AAudio, sans aucune traversée JNI vers Kotlin — un aller-retour JNI par bloc
// réintroduirait exactement la gigue/latence imprévisible qu'AAudio est censé éliminer. La
// détection YIN, trop lourde pour un callback de 2–4 ms, n'y tourne PAS : elle est faite par
// aaudio_engine_poll_status sur le thread Kotlin. Kotlin ne fait que : (a) démarrer/arrêter le
// moteur, (b) sonder périodiquement (10–20 ms, hors du chemin chaud) le statut (niveau, hauteur
// détectée, déconnexion) via aaudio_engine_poll_status, (c) appliquer la logique de correction
// musicale existante (PitchCorrectionEngine.kt, smoothing) sur la hauteur détectée et
// repousser le résultat via psola_set_pitch_cents (déjà thread-safe/atomic côté Rust).
//
// Repli : si aaudio_engine_create() échoue pour n'importe quelle raison (API<26, MMAP
// indisponible sur l'appareil, erreur d'ouverture de flux), elle retourne NULL et
// PitchMonitorPlugin.kt retombe sur AudioCaptureLoop (Phase 1, déjà éprouvé) — voir
// PsolaAudioEngine.kt.
//
// Limitation connue et assumée : la reverb (PresetReverb, API Java uniquement) n'est pas
// câblée sur ce chemin — voir docs/roadmap.md. N'affecte que l'esthétique du monitoring, pas
// la latence ni la justesse, jugé hors scope pour cette passe centrée sur la latence.

#include <math.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#include "aaudio_shim.h"
#include "psola_ffi.h"
#include "spsc_ring.h"

// ── Bornes de compilation ───────────────────────────────────────────────────────

#define YIN_FRAME_SIZE 2048u          // aligné sur YinPitchDetector.kt / YINDetector.swift
#define MAX_CALLBACK_FRAMES 4096u     // borne défensive — AAudio ne garantit pas de max fixe
#define PITCH_HIST_CAPACITY 4096u     // puissance de 2, ≥ YIN_FRAME_SIZE
#define BRIDGE_RING_CAPACITY 16384u   // ~370ms @44.1kHz — large marge anti-xrun, pas la latence réelle
#define RECORD_RING_CAPACITY 65536u   // ~1.5s @44.1kHz — marge si le polling Kotlin (~20ms) prend du retard

// Chaîne voix du retour casque (boue / présence / clarté / volume) — coefficients calculés
// côté Kotlin (VoiceFx.kt, seule source des formules) : 4 biquads × (b0,b1,b2,a1,a2) + volume.
#define VOICE_FX_BIQUADS 4u
#define VOICE_FX_COEFS (VOICE_FX_BIQUADS * 5u + 1u)

// ── État du moteur ───────────────────────────────────────────────────────────────

typedef struct Engine {
    AAudioShim shim;
    AAudioStream *inputStream;
    AAudioStream *outputStream; // NULL si !useMonitor

    _Atomic bool useMonitor;
    _Atomic bool monitorAutotune;
    _Atomic float voiceGain;

    int32_t sampleRate;
    PsolaHandle *psola; // NULL si !useMonitor || !monitorAutotune

    SpscRing bridgeRing; // sortie PSOLA/passthrough → callback de sortie
    float bridgeStorage[BRIDGE_RING_CAPACITY];

    SpscRing recordRing; // PCM brut → drainé périodiquement par Kotlin (enregistrement)
    // Mode Clip : index (compteur AAudio) du 1er échantillon livré au callback. En MMAP,
    // AAudio saute en avant au démarrage (rattrapage du serveur) : ce n'est PAS 0.
    _Atomic int64_t firstDeliveredFrame; // -1 tant qu'aucun callback
    float recordStorage[RECORD_RING_CAPACITY];

    // Historique micro pour la détection de hauteur : ÉCRIT par le callback d'entrée (copie
    // seulement), LU par aaudio_engine_poll_status sur le thread Kotlin, qui y fait tourner YIN.
    // YIN sur 2048 échantillons à CHAQUE callback (toutes les 2–4 ms) saturait le thread audio
    // → callbacks en retard → craquements. Lecture sans verrou : une fenêtre copiée pendant une
    // écriture peut contenir une discontinuité, sans conséquence pour estimer une fondamentale.
    float pitchRing[PITCH_HIST_CAPACITY];
    _Atomic uint64_t pitchWritePos;
    uint64_t pitchLastDetectPos;      // thread Kotlin uniquement

    // Thread de sortie uniquement — coussin anti-famine et réglage adaptatif du tampon.
    bool    outPrimed;
    int32_t outXRuns;
    int32_t outBurst;

    // Statut exposé au polling Kotlin (aaudio_engine_poll_status) — jamais lu/écrit ailleurs
    // que via ces atomiques, aucun lock.
    _Atomic float statusLevel;
    _Atomic int32_t statusInterrupted; // 0/1, remis à 0 par aaudio_engine_poll_status
    _Atomic int64_t statusGeneration;

    // Chaîne voix : publiée par aaudio_engine_set_voice_fx (thread Kotlin) via un seqlock —
    // le callback d'entrée ne copie fxPending dans fxActive que si la séquence est paire et
    // inchangée pendant la copie (jamais de coefficients à moitié écrits, aucun lock).
    _Atomic uint32_t fxSeq;
    float fxPending[VOICE_FX_COEFS];
    float fxActive[VOICE_FX_COEFS];   // thread audio uniquement
    uint32_t fxSeen;                  // thread audio uniquement
    float fxState[VOICE_FX_BIQUADS * 2u];
} Engine;

static void voiceFxIdentity(float *c) {
    memset(c, 0, sizeof(float) * VOICE_FX_COEFS);
    for (size_t b = 0; b < VOICE_FX_BIQUADS; b++) c[b * 5u] = 1.0f; // b0 = 1 : passe-tout
    c[VOICE_FX_BIQUADS * 5u] = 1.0f;                                 // volume
}

// Thread audio : récupère d'éventuels nouveaux coefficients puis filtre `buf` en place
// (forme directe II transposée).
static void voiceFxProcess(Engine *e, float *buf, size_t n) {
    uint32_t s1 = atomic_load_explicit(&e->fxSeq, memory_order_acquire);
    if ((s1 & 1u) == 0u && s1 != e->fxSeen) {
        float tmp[VOICE_FX_COEFS];
        memcpy(tmp, e->fxPending, sizeof tmp);
        atomic_thread_fence(memory_order_acquire);
        if (atomic_load_explicit(&e->fxSeq, memory_order_relaxed) == s1) {
            memcpy(e->fxActive, tmp, sizeof tmp);
            e->fxSeen = s1;
        }
    }

    const float *c = e->fxActive;
    for (size_t b = 0; b < VOICE_FX_BIQUADS; b++) {
        const float b0 = c[b * 5u], b1 = c[b * 5u + 1u], b2 = c[b * 5u + 2u];
        const float a1 = c[b * 5u + 3u], a2 = c[b * 5u + 4u];
        float z1 = e->fxState[b * 2u], z2 = e->fxState[b * 2u + 1u];
        for (size_t i = 0; i < n; i++) {
            const float x = buf[i];
            const float y = b0 * x + z1;
            z1 = b1 * x - a1 * y + z2;
            z2 = b2 * x - a2 * y;
            buf[i] = y;
        }
        e->fxState[b * 2u] = z1;
        e->fxState[b * 2u + 1u] = z2;
    }
    const float vol = c[VOICE_FX_BIQUADS * 5u];
    if (vol != 1.0f) for (size_t i = 0; i < n; i++) buf[i] *= vol;
}

// ── Callbacks temps réel ────────────────────────────────────────────────────────

static aaudio_data_callback_result_t onInputData(AAudioStream *stream, void *userData,
                                                  void *audioData, int32_t numFrames) {
    (void) stream;
    Engine *e = (Engine *) userData;
    const float *in = (const float *) audioData;
    if (numFrames <= 0) return AAUDIO_CALLBACK_RESULT_CONTINUE;
    if (atomic_load_explicit(&e->firstDeliveredFrame, memory_order_relaxed) < 0) {
        // framesRead inclut déjà ce bloc quand le callback est appelé.
        int64_t first = e->shim.getFramesRead ? e->shim.getFramesRead(stream) - numFrames : 0;
        atomic_store_explicit(&e->firstDeliveredFrame, first < 0 ? 0 : first, memory_order_relaxed);
    }
    size_t n = (size_t) numFrames;
    if (n > MAX_CALLBACK_FRAMES) n = MAX_CALLBACK_FRAMES; // borne défensive, cf. en-tête

    // Niveau (RMS) + PCM brut pour enregistrement (perte silencieuse si le polling Kotlin a
    // pris trop de retard sur le drain — préférable à bloquer le thread audio).
    float sumSquares = 0.0f;
    for (size_t i = 0; i < n; i++) sumSquares += in[i] * in[i];
    atomic_store_explicit(&e->statusLevel, sqrtf(sumSquares / (float) n), memory_order_relaxed);
    spsc_ring_write(&e->recordRing, in, n);

    // Historique pour la détection de hauteur — simple copie, YIN tourne hors du thread audio
    // (voir aaudio_engine_poll_status).
    uint64_t wp = atomic_load_explicit(&e->pitchWritePos, memory_order_relaxed);
    for (size_t i = 0; i < n; i++) e->pitchRing[(wp + i) & (PITCH_HIST_CAPACITY - 1u)] = in[i];
    atomic_store_explicit(&e->pitchWritePos, wp + n, memory_order_release);

    if (atomic_load_explicit(&e->useMonitor, memory_order_relaxed)) {
        float gain = atomic_load_explicit(&e->voiceGain, memory_order_relaxed);
        float outBuf[MAX_CALLBACK_FRAMES];

        if (atomic_load_explicit(&e->monitorAutotune, memory_order_relaxed) && e->psola) {
            psola_process(e->psola, in, n);
            int32_t avail = psola_available(e->psola);
            if (avail > 0) {
                size_t k = (size_t) avail;
                if (k > MAX_CALLBACK_FRAMES) k = MAX_CALLBACK_FRAMES;
                psola_retrieve(e->psola, outBuf, k);
                for (size_t i = 0; i < k; i++) outBuf[i] *= gain;
                voiceFxProcess(e, outBuf, k);
                spsc_ring_write(&e->bridgeRing, outBuf, k);
            }
        } else {
            for (size_t i = 0; i < n; i++) outBuf[i] = in[i] * gain;
            voiceFxProcess(e, outBuf, n);
            spsc_ring_write(&e->bridgeRing, outBuf, n);
        }
    }

    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

#define FADE_FRAMES 96u   // ~2 ms : fondu des (re)démarrages / famines du retour casque

static void fadeIn(float *buf, size_t n) {
    const size_t f = n < FADE_FRAMES ? n : FADE_FRAMES;
    for (size_t i = 0; i < f; i++) buf[i] *= (float) (i + 1) / (float) (f + 1);
}

static void fadeOutTail(float *buf, size_t n) {
    const size_t f = n < FADE_FRAMES ? n : FADE_FRAMES;
    for (size_t i = 0; i < f; i++) buf[n - f + i] *= (float) (f - i) / (float) (f + 1);
}

static aaudio_data_callback_result_t onOutputData(AAudioStream *stream, void *userData,
                                                   void *audioData, int32_t numFrames) {
    (void) stream;
    Engine *e = (Engine *) userData;
    float *out = (float *) audioData;
    if (numFrames <= 0) return AAUDIO_CALLBACK_RESULT_CONTINUE;
    size_t n = (size_t) numFrames;

    // Réglage adaptatif (principe du LatencyTuner d'Oboe) : chaque sous-alimentation constatée
    // par AAudio agrandit le tampon de sortie d'un burst, jusqu'à sa capacité. On part de la
    // latence minimale et on ne paie que la marge dont CET appareil / CE casque a besoin
    // (une sortie Bluetooth en demande beaucoup plus qu'un filaire).
    if (e->shim.getXRunCount && e->shim.setBufferSizeInFrames && e->shim.getBufferSizeInFrames
        && e->shim.getBufferCapacityInFrames) {
        int32_t xr = e->shim.getXRunCount(stream);
        if (xr > e->outXRuns) {
            e->outXRuns = xr;
            int32_t size = e->shim.getBufferSizeInFrames(stream);
            int32_t cap  = e->shim.getBufferCapacityInFrames(stream);
            int32_t step = e->outBurst > 0 ? e->outBurst : 192;
            if (size + step <= cap) e->shim.setBufferSizeInFrames(stream, size + step);
        }
    }

    // Coussin : combler un manque par du silence EN PLEIN signal produit un craquement. On ne
    // (re)démarre la sortie qu'avec un callback d'avance en réserve ; une famine devient ainsi
    // un court silence propre au lieu d'une rafale de clics.
    //
    // 20/11/2026 — aucune transition franche : démarrage en fondu entrant, famine terminée par
    // un fondu sortant des derniers échantillons. Et les flux d'entrée et de sortie ont deux
    // horloges indépendantes : sans correction, la réserve dérive (famines répétées dans un
    // sens, ring saturé = échantillons perdus et retard qui grimpe dans l'autre). Au-delà d'une
    // réserve maximale, on saute au plus récent en fondu enchaîné sur tout le bloc.
    size_t ready = spsc_ring_available(&e->bridgeRing);
    if (!e->outPrimed) {
        if (ready < n * 2u) {
            memset(out, 0, n * sizeof(float));
            return AAUDIO_CALLBACK_RESULT_CONTINUE;
        }
        e->outPrimed = true;
        spsc_ring_read(&e->bridgeRing, out, n);
        fadeIn(out, n);
        return AAUDIO_CALLBACK_RESULT_CONTINUE;
    }
    if (ready < n) {
        e->outPrimed = false;
        size_t k = spsc_ring_read(&e->bridgeRing, out, ready);
        fadeOutTail(out, k);
        memset(out + k, 0, (n - k) * sizeof(float));
        return AAUDIO_CALLBACK_RESULT_CONTINUE;
    }

    const size_t target   = n * 2u;
    const size_t maxReady = target + n * 2u + (size_t) (e->sampleRate / 50); // + 20 ms
    if (ready > maxReady && n <= MAX_CALLBACK_FRAMES) {
        float fresh[MAX_CALLBACK_FRAMES];
        spsc_ring_read(&e->bridgeRing, out, n);              // suite immédiate de l'ancien
        size_t skip = ready - n - (target + n);              // il restera target après `fresh`
        while (skip > 0) {
            size_t k = skip < MAX_CALLBACK_FRAMES ? skip : MAX_CALLBACK_FRAMES;
            spsc_ring_read(&e->bridgeRing, fresh, k);
            skip -= k;
        }
        spsc_ring_read(&e->bridgeRing, fresh, n);            // le plus récent
        for (size_t i = 0; i < n; i++) {
            const float t = (float) (i + 1) / (float) (n + 1);
            out[i] = out[i] * (1.0f - t) + fresh[i] * t;
        }
        return AAUDIO_CALLBACK_RESULT_CONTINUE;
    }

    spsc_ring_read(&e->bridgeRing, out, n);
    return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

static void onError(AAudioStream *stream, void *userData, aaudio_result_t error) {
    (void) stream;
    (void) error;
    Engine *e = (Engine *) userData;
    // Ne JAMAIS stop/close le flux ici (interdit par la doc AAudio, voir aaudio_shim.h) —
    // on se contente de signaler ; Kotlin réagit au flag via le polling et arrête/détruit le
    // moteur depuis un thread normal (aaudio_engine_stop / aaudio_engine_destroy).
    atomic_store_explicit(&e->statusInterrupted, 1, memory_order_relaxed);
    atomic_fetch_add_explicit(&e->statusGeneration, 1, memory_order_relaxed);
}

// ── Ouverture d'un flux (facteur commun capture/lecture) ─────────────────────────

static aaudio_result_t openStream(Engine *e, aaudio_direction_t direction,
                                   AAudioStream_dataCallback dataCb, AAudioStream **outStream) {
    AAudioStreamBuilder *builder = NULL;
    aaudio_result_t result = e->shim.createStreamBuilder(&builder);
    if (result != AAUDIO_OK || !builder) return result;

    e->shim.setSampleRate(builder, e->sampleRate);
    e->shim.setChannelCount(builder, 1);
    e->shim.setFormat(builder, AAUDIO_FORMAT_PCM_FLOAT);
    e->shim.setDirection(builder, direction);
    e->shim.setSharingMode(builder, AAUDIO_SHARING_MODE_EXCLUSIVE);
    e->shim.setPerformanceMode(builder, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
    if (direction == AAUDIO_DIRECTION_INPUT) {
        e->shim.setInputPreset(builder, AAUDIO_INPUT_PRESET_VOICE_RECOGNITION);
    } else {
        // MEDIA et non VOICE_COMMUNICATION : un flux "appel" est réglé par le volume d'appel,
        // n'est pas éligible au chemin MMAP basse latence sur la plupart des appareils, et peut
        // faire basculer un casque Bluetooth en profil appel (HFP/SCO, son dégradé) — le même
        // piège que celui évité côté iOS (allowBluetoothA2DP sans HFP).
        e->shim.setUsage(builder, AAUDIO_USAGE_MEDIA);
    }
    e->shim.setDataCallback(builder, dataCb, e);
    e->shim.setErrorCallback(builder, onError, e);

    result = e->shim.openStream(builder, outStream);
    e->shim.deleteBuilder(builder);
    return result;
}

// ── API exposée à jni_shim.c ────────────────────────────────────────────────────

// Crée et démarre le moteur. Retourne NULL si AAudio est indisponible (API<26, dlopen/dlsym
// échoué) ou si l'ouverture d'un flux échoue (ex. MMAP exclusif refusé par l'appareil) — dans
// tous les cas, l'appelant doit se rabattre sur AudioCaptureLoop, jamais retenter en boucle.
Engine *aaudio_engine_create(int32_t sampleRate, bool useMonitor, bool monitorAutotune,
                              float voiceGain, bool formantPreservation) {
    Engine *e = (Engine *) calloc(1, sizeof(Engine));
    if (!e) return NULL;

    if (!aaudio_shim_load(&e->shim)) {
        free(e);
        return NULL;
    }

    e->sampleRate = sampleRate;
    atomic_init(&e->useMonitor, useMonitor);
    atomic_init(&e->monitorAutotune, monitorAutotune);
    atomic_init(&e->voiceGain, voiceGain);
    atomic_init(&e->statusLevel, 0.0f);
    atomic_init(&e->statusInterrupted, 0);
    atomic_init(&e->statusGeneration, 0);
    atomic_init(&e->fxSeq, 0u);
    atomic_init(&e->pitchWritePos, 0u);
    atomic_init(&e->firstDeliveredFrame, -1);
    voiceFxIdentity(e->fxPending);
    voiceFxIdentity(e->fxActive);

    spsc_ring_init(&e->bridgeRing, e->bridgeStorage, BRIDGE_RING_CAPACITY);
    spsc_ring_init(&e->recordRing, e->recordStorage, RECORD_RING_CAPACITY);

    // Ouvre l'ENTRÉE en premier, AVANT de créer le moteur PSOLA — AAudio ne garantit PAS
    // d'honorer exactement le sampleRate demandé (voir AAudioStreamBuilder_setSampleRate dans
    // AAudio.h : "the stream may be opened using a different rate"), même en mode EXCLUSIVE.
    // e->sampleRate est la valeur que TOUT le reste (conversion période↔Hz dans psola_yin_detect,
    // et le sampleRate déjà annoncé côté Kotlin/serveur pour l'enregistrement, voir
    // PsolaAudioEngine.kt) suppose exacte. Vérifier plutôt que de faire confiance à la demande
    // évite une désaccord silencieux (ex. correction d'autotune visant la mauvaise fréquence,
    // enregistrement réétiqueté au mauvais sampleRate) — voir docs/roadmap.md, chantier latence.
    if (openStream(e, AAUDIO_DIRECTION_INPUT, onInputData, &e->inputStream) != AAUDIO_OK) {
        free(e);
        return NULL;
    }
    if (e->shim.getSampleRate(e->inputStream) != e->sampleRate) {
        e->shim.closeStream(e->inputStream);
        free(e);
        return NULL;
    }

    if (useMonitor && monitorAutotune) {
        e->psola = psola_create((double) e->sampleRate, formantPreservation ? 1 : 0);
        if (!e->psola) {
            e->shim.closeStream(e->inputStream);
            free(e);
            return NULL;
        }
    }

    if (useMonitor) {
        if (openStream(e, AAUDIO_DIRECTION_OUTPUT, onOutputData, &e->outputStream) != AAUDIO_OK) {
            e->shim.closeStream(e->inputStream);
            if (e->psola) psola_destroy(e->psola);
            free(e);
            return NULL;
        }
        // Même vérification côté sortie : le pont (bridgeRing) et onOutputData supposent que
        // les deux flux tournent au MÊME sampleRate qu'e->psola a été créé avec — un flux de
        // sortie négocié à une fréquence différente lirait/produirait à un débit désaligné du
        // débit d'écriture de onInputData, désynchronisant progressivement le pont.
        if (e->shim.getSampleRate(e->outputStream) != e->sampleRate) {
            e->shim.closeStream(e->outputStream);
            e->shim.closeStream(e->inputStream);
            if (e->psola) psola_destroy(e->psola);
            free(e);
            return NULL;
        }
        // Départ du réglage adaptatif : 2 bursts (double tampon, valeur conseillée par AAudio).
        e->outBurst = e->shim.getFramesPerBurst(e->outputStream);
        if (e->outBurst > 0 && e->shim.setBufferSizeInFrames) {
            e->shim.setBufferSizeInFrames(e->outputStream, e->outBurst * 2);
        }
    }

    // Démarrer la SORTIE avant l'ENTRÉE : évite que le pont (bridgeRing) déborde silencieusement
    // pendant la fenêtre où l'entrée produirait déjà des données sans consommateur actif.
    if (e->outputStream && e->shim.requestStart(e->outputStream) != AAUDIO_OK) {
        e->shim.closeStream(e->outputStream);
        e->shim.closeStream(e->inputStream);
        if (e->psola) psola_destroy(e->psola);
        free(e);
        return NULL;
    }
    if (e->shim.requestStart(e->inputStream) != AAUDIO_OK) {
        if (e->outputStream) {
            e->shim.requestStop(e->outputStream);
            e->shim.closeStream(e->outputStream);
        }
        e->shim.closeStream(e->inputStream);
        if (e->psola) psola_destroy(e->psola);
        free(e);
        return NULL;
    }

    return e;
}

void aaudio_engine_set_pitch_cents(Engine *e, float cents) {
    if (!e || !e->psola) return;
    psola_set_pitch_cents(e->psola, cents);
}

// Sonde le statut courant (niveau, hauteur détectée, déconnexion) — à appeler depuis un thread
// Kotlin normal (polling ~20ms), jamais depuis le thread audio. `*out_pitch_hz` reste NaN si
// rien de neuf depuis le dernier appel. Retourne 1 si le flux a signalé une déconnexion
// (`onError`) depuis le dernier appel — le flag est alors remis à zéro.
int32_t aaudio_engine_poll_status(Engine *e, float *out_level, float *out_pitch_hz) {
    if (!e) return 0;
    *out_level = atomic_load_explicit(&e->statusLevel, memory_order_relaxed);
    *out_pitch_hz = NAN;

    // Détection de hauteur sur la fenêtre la plus récente, ici (thread Kotlin) et non dans le
    // callback audio. Rien de neuf depuis le dernier appel → NaN, comme avant.
    uint64_t wp = atomic_load_explicit(&e->pitchWritePos, memory_order_acquire);
    if (wp >= YIN_FRAME_SIZE && wp != e->pitchLastDetectPos) {
        e->pitchLastDetectPos = wp;
        float frame[YIN_FRAME_SIZE];
        uint64_t start = wp - YIN_FRAME_SIZE;
        for (size_t i = 0; i < YIN_FRAME_SIZE; i++) {
            frame[i] = e->pitchRing[(start + i) & (PITCH_HIST_CAPACITY - 1u)];
        }
        float hz;
        if (psola_yin_detect(frame, YIN_FRAME_SIZE, (float) e->sampleRate, &hz)) *out_pitch_hz = hz;
    }
    return atomic_exchange_explicit(&e->statusInterrupted, 0, memory_order_relaxed);
}

// Draine jusqu'à `maxSamples` échantillons de PCM brut capturé vers `out` (float32
// [-1,1] — la conversion en Int16 pour l'upload reste côté Kotlin, cohérent avec
// AudioCaptureLoop.pcm16BytesToFloats/l'inverse). Retourne le nombre réellement drainé.
size_t aaudio_engine_drain_recorded(Engine *e, float *out, size_t maxSamples) {
    if (!e) return 0;
    return spsc_ring_read(&e->recordRing, out, maxSamples);
}

void aaudio_engine_set_monitor_options(Engine *e, bool useMonitor, bool monitorAutotune,
                                        float voiceGain) {
    if (!e) return;
    atomic_store_explicit(&e->useMonitor, useMonitor, memory_order_relaxed);
    atomic_store_explicit(&e->monitorAutotune, monitorAutotune, memory_order_relaxed);
    atomic_store_explicit(&e->voiceGain, voiceGain, memory_order_relaxed);
}

// Publie de nouveaux coefficients de chaîne voix (VoiceFx.kt) — thread Kotlin unique,
// appliqués par le callback d'entrée au bloc suivant. `count` != VOICE_FX_COEFS → ignoré.
void aaudio_engine_set_voice_fx(Engine *e, const float *coefs, size_t count) {
    if (!e || !coefs || count != VOICE_FX_COEFS) return;
    uint32_t s = atomic_load_explicit(&e->fxSeq, memory_order_relaxed);
    atomic_store_explicit(&e->fxSeq, s + 1u, memory_order_relaxed);   // impair : écriture en cours
    atomic_thread_fence(memory_order_release);
    memcpy(e->fxPending, coefs, sizeof(float) * VOICE_FX_COEFS);
    atomic_store_explicit(&e->fxSeq, s + 2u, memory_order_release);   // pair : publié
}

// Horodatage du flux d'ENTRÉE (Mode Clip) : instant CLOCK_MONOTONIC où la frame
// `*out_frame` a été captée. Le PCM enregistré commence à la frame 0 du flux (le ring
// d'enregistrement reçoit chaque callback depuis le démarrage) : Kotlin en déduit
// l'instant de capture du 1er échantillon. Thread Kotlin uniquement. Retourne 0 si
// indisponible (API sans getTimestamp, flux pas encore démarré).
int32_t aaudio_engine_get_input_timestamp(Engine *e, int64_t *out_frame, int64_t *out_time_ns) {
    if (!e || !e->inputStream || !e->shim.getTimestamp) return 0;
    int64_t first = atomic_load_explicit(&e->firstDeliveredFrame, memory_order_relaxed);
    if (first < 0) return 0;
    if (e->shim.getTimestamp(e->inputStream, CLOCK_MONOTONIC, out_frame, out_time_ns) != AAUDIO_OK) return 0;
    *out_frame -= first;   // position relative au 1er échantillon enregistré
    return 1;
}

// Arrête puis détruit le moteur. À appeler depuis un thread Kotlin normal (jamais depuis
// onError — voir sa doc). Sûr à appeler même si create() avait partiellement échoué avant
// qu'on en soit informé (ne devrait pas arriver : create() nettoie déjà ses échecs partiels).
void aaudio_engine_destroy(Engine *e) {
    if (!e) return;
    if (e->inputStream) {
        e->shim.requestStop(e->inputStream);
        e->shim.closeStream(e->inputStream);
    }
    if (e->outputStream) {
        e->shim.requestStop(e->outputStream);
        e->shim.closeStream(e->outputStream);
    }
    if (e->psola) psola_destroy(e->psola);
    free(e);
}
