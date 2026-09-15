// psola_ffi.h — en-tête C plat pour le crate Rust psola-ffi (voir docs/roadmap.md).
//
// Écrit à la main (pas de cbindgen — cohérent avec la philosophie "zéro dépendance" du
// chantier) ; doit rester synchronisé avec les signatures `extern "C"` de
// native/psola-ffi/src/lib.rs. Utilisé tel quel par android/app/src/main/cpp/jni_shim.c et par
// ios/App/App/RubberBandWrapper.mm (Phase 2).
//
// Le handle est opaque côté C — jamais déréférencé ici, seulement transmis.

#ifndef PSOLA_FFI_H
#define PSOLA_FFI_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PsolaHandle PsolaHandle;

// Crée un moteur. formant_preservation != 0 pour activer la couche LPC. Retourne NULL si la
// construction a paniqué (ne devrait jamais arriver en usage normal).
PsolaHandle *psola_create(double sample_rate, int32_t formant_preservation);

// Détruit un moteur créé par psola_create. handle peut être NULL (no-op).
void psola_destroy(PsolaHandle *handle);

// Met à jour la hauteur cible, en cents (1/100 de demi-ton). Thread-safe : peut être appelée
// depuis un thread différent de celui qui appelle psola_process/psola_retrieve.
void psola_set_pitch_cents(PsolaHandle *handle, float cents);

// Consomme `len` échantillons mono [-1,1] depuis `input`. Thread chaud unique.
void psola_process(PsolaHandle *handle, const float *input, size_t len);

// Nombre d'échantillons actuellement disponibles via psola_retrieve.
int32_t psola_available(PsolaHandle *handle);

// Copie `len` échantillons dans `output` (silence-complété si moins de `len` disponibles).
void psola_retrieve(PsolaHandle *handle, float *output, size_t len);

// Latence structurelle du moteur, en échantillons.
int32_t psola_get_latency(PsolaHandle *handle);

// Réinitialise l'état interne (silence, pitch à l'unisson).
void psola_reset(PsolaHandle *handle);

// Détecte la fréquence fondamentale dans `frame` (mono float32, `len` échantillons, pair,
// <= psola_yin_max_frame_size()). Écrit dans *out_hz et retourne 1 si détectée, 0 sinon (0 =
// *out_hz inchangé). Fonction pure, sans handle, appelable depuis n'importe quel thread.
int32_t psola_yin_detect(const float *frame, size_t len, float sample_rate, float *out_hz);

// Taille de trame maximale acceptée par psola_yin_detect.
size_t psola_yin_max_frame_size(void);

#ifdef __cplusplus
}
#endif

#endif // PSOLA_FFI_H
