//! Frontière FFI en C-ABI plate vers `psola-dsp`.
//!
//! Tout le code `unsafe` du workspace vit exclusivement dans ce fichier — voir
//! `docs/roadmap.md`, section "Discipline d'ingénierie". `include/psola_ffi.h` (ce crate) est
//! LA seule source de vérité pour l'en-tête C — jamais copié, référencé directement par les deux
//! plateformes via leurs chemins de recherche d'en-têtes respectifs (`HEADER_SEARCH_PATHS`
//! Xcode / `target_include_directories` CMake), pour ne jamais avoir deux copies à
//! resynchroniser à la main. Deux consommateurs :
//!   - iOS : `RubberBandWrapper.mm` appelle directement ces fonctions ; le `.a` statique est
//!     (re)compilé par une phase "Run Script" du target Xcode (voir project.pbxproj) avant
//!     chaque build, jamais committé — même principe que le CMake Android ci-dessous.
//!   - Android : `android/app/src/main/cpp/jni_shim.c` (petit pont JNI séparé, PAS dans ce
//!     crate) traduit les types JNI vers ces mêmes fonctions plates ; `CMakeLists.txt` invoque
//!     `cargo build` à chaque build Gradle.
//!
//! Chaque fonction publique enveloppe son corps dans `catch_unwind` : un panic Rust qui
//! traverserait une frontière `extern "C"` vers Kotlin/ObjC++ serait un comportement indéfini
//! (pas juste un crash propre) — voir la discipline documentée dans `docs/roadmap.md`. Un
//! panic intercepté se traduit par un repli sûr (silence en sortie / no-op), jamais par une
//! propagation vers l'appelant natif.

use psola_dsp::{
    cents_to_ratio, yin_detect, PitchTarget, PsolaShifter, YIN_DEFAULT_MAX_FREQUENCY,
    YIN_DEFAULT_MIN_FREQUENCY, YIN_DEFAULT_THRESHOLD, YIN_MAX_FRAME_SIZE,
};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;
use std::sync::Arc;

/// État opaque manipulé par l'appelant natif via un pointeur brut. `pitch` est cloné à part
/// de `shifter` précisément pour que `psola_set_pitch_cents` reste valide à appeler pendant
/// qu'un autre thread détient l'accès `&mut` au `shifter` (voir `PitchTarget` dans
/// `psola-dsp`, dont c'est toute la raison d'être).
pub struct PsolaHandle {
    shifter: PsolaShifter,
    pitch: Arc<PitchTarget>,
}

/// Crée un moteur. `sample_rate` en Hz, `formant_preservation` != 0 pour activer la couche
/// LPC. Retourne un pointeur opaque à passer à toutes les autres fonctions, ou un pointeur
/// nul si la construction a paniqué (ne devrait jamais arriver en usage normal — bornes
/// validées à l'appel, pas de panic attendu ici, mais `catch_unwind` reste la garantie ultime).
///
/// # Safety
/// Le pointeur retourné doit être détruit avec [`psola_destroy`] exactement une fois, et ne
/// doit plus être utilisé après cet appel.
#[no_mangle]
pub extern "C" fn psola_create(sample_rate: f64, formant_preservation: i32) -> *mut PsolaHandle {
    let result = catch_unwind(|| {
        let (shifter, pitch) = PsolaShifter::new(sample_rate, formant_preservation != 0);
        Box::into_raw(Box::new(PsolaHandle { shifter, pitch }))
    });
    result.unwrap_or(std::ptr::null_mut())
}

/// Détruit un moteur créé par [`psola_create`].
///
/// # Safety
/// `handle` doit être un pointeur retourné par [`psola_create`], non encore détruit. `handle`
/// peut être nul (no-op), pour rester tolérant à un appelant qui a déjà géré l'échec de
/// `psola_create`.
#[no_mangle]
pub unsafe extern "C" fn psola_destroy(handle: *mut PsolaHandle) {
    if handle.is_null() {
        return;
    }
    // SAFETY: `handle` provient de `Box::into_raw` dans `psola_create`, jamais libéré
    // ailleurs (contrat documenté ci-dessus) — reconstruire puis laisser tomber le `Box` est
    // l'inverse exact de sa création.
    let _ = catch_unwind(AssertUnwindSafe(|| {
        drop(Box::from_raw(handle));
    }));
}

/// Met à jour la hauteur cible, en cents (1/100 de demi-ton). Thread-safe : peut être appelée
/// depuis un thread différent de celui qui appelle `psola_process`/`psola_retrieve`.
///
/// # Safety
/// `handle` doit être un pointeur valide retourné par [`psola_create]`, non détruit.
#[no_mangle]
pub unsafe extern "C" fn psola_set_pitch_cents(handle: *mut PsolaHandle, cents: f32) {
    if handle.is_null() {
        return;
    }
    let _ = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: `PitchTarget::set` ne prend que `&self` — un accès partagé à travers le
        // pointeur brut est valide même si un autre thread détient concurremment un accès
        // `&mut` au reste de `PsolaHandle`, car `set` ne touche que son propre `AtomicU32`,
        // jamais les champs mutés par `psola_process`/`psola_retrieve`.
        (*handle).pitch.set(cents_to_ratio(cents));
    }));
}

/// Consomme `len` échantillons mono `[-1,1]` depuis `input`. À appeler depuis le thread audio
/// chaud unique (jamais concurremment avec un autre appel à `psola_process`/`psola_retrieve`/
/// `psola_reset` sur le même `handle`).
///
/// # Safety
/// `handle` valide et non détruit. `input` doit pointer vers au moins `len` `f32` valides et
/// rester valide pendant tout l'appel.
#[no_mangle]
pub unsafe extern "C" fn psola_process(handle: *mut PsolaHandle, input: *const f32, len: usize) {
    if handle.is_null() || input.is_null() {
        return;
    }
    let _ = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: contrat documenté ci-dessus (pointeur + longueur fournis par l'appelant
        // natif, garantis valides pour la durée de l'appel par construction du wrapper
        // Kotlin/ObjC++ — même contrat que l'actuel shim JNI C++).
        let slice = slice::from_raw_parts(input, len);
        (*handle).shifter.process(slice);
    }));
}

/// Nombre d'échantillons actuellement disponibles via [`psola_retrieve`].
///
/// # Safety
/// `handle` valide et non détruit.
#[no_mangle]
pub unsafe extern "C" fn psola_available(handle: *mut PsolaHandle) -> i32 {
    if handle.is_null() {
        return 0;
    }
    catch_unwind(AssertUnwindSafe(|| (*handle).shifter.available() as i32)).unwrap_or(0)
}

/// Copie `len` échantillons dans `output` (complété de silence si moins de `len` sont
/// disponibles — jamais d'échantillons non initialisés).
///
/// # Safety
/// `handle` valide et non détruit. `output` doit pointer vers au moins `len` `f32` valides en
/// écriture et rester valide pendant tout l'appel.
#[no_mangle]
pub unsafe extern "C" fn psola_retrieve(handle: *mut PsolaHandle, output: *mut f32, len: usize) {
    if handle.is_null() || output.is_null() {
        return;
    }
    let _ = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: même contrat que psola_process, en écriture.
        let slice = slice::from_raw_parts_mut(output, len);
        (*handle).shifter.retrieve(slice);
    }));
}

/// Latence structurelle du moteur, en échantillons.
///
/// # Safety
/// `handle` valide et non détruit.
#[no_mangle]
pub unsafe extern "C" fn psola_get_latency(handle: *mut PsolaHandle) -> i32 {
    if handle.is_null() {
        return 0;
    }
    catch_unwind(AssertUnwindSafe(|| (*handle).shifter.latency() as i32)).unwrap_or(0)
}

/// Réinitialise l'état interne (silence, pitch à l'unisson).
///
/// # Safety
/// `handle` valide et non détruit.
#[no_mangle]
pub unsafe extern "C" fn psola_reset(handle: *mut PsolaHandle) {
    if handle.is_null() {
        return;
    }
    let _ = catch_unwind(AssertUnwindSafe(|| {
        (*handle).shifter.reset();
    }));
}

/// Détecte la fréquence fondamentale dans `frame` (mono float32, `len` échantillons,
/// `len <= psola_yin_max_frame_size()` et pair) — voir `psola-dsp::yin`. Fonction pure, sans
/// handle : appelable depuis n'importe quel thread, y compris en parallèle d'un moteur PSOLA.
///
/// Écrit la fréquence détectée dans `*out_hz` et retourne 1 si une hauteur a été détectée,
/// 0 sinon (silence, bruit, ou hors bornes) — `*out_hz` n'est pas modifié dans ce cas.
///
/// # Safety
/// `frame` doit pointer vers au moins `len` `f32` valides. `out_hz` doit pointer vers un `f32`
/// valide en écriture. Les deux doivent rester valides pendant tout l'appel.
#[no_mangle]
pub unsafe extern "C" fn psola_yin_detect(
    frame: *const f32,
    len: usize,
    sample_rate: f32,
    out_hz: *mut f32,
) -> i32 {
    if frame.is_null() || out_hz.is_null() {
        return 0;
    }
    let result = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: contrat documenté ci-dessus.
        let slice = slice::from_raw_parts(frame, len);
        yin_detect(
            slice,
            sample_rate,
            YIN_DEFAULT_THRESHOLD,
            YIN_DEFAULT_MIN_FREQUENCY,
            YIN_DEFAULT_MAX_FREQUENCY,
        )
    }));
    match result {
        Ok(Some(hz)) => {
            // SAFETY: `out_hz` valide en écriture (contrat documenté ci-dessus).
            *out_hz = hz;
            1
        }
        _ => 0,
    }
}

/// Taille de trame maximale acceptée par [`psola_yin_detect`] — expose la borne de
/// `psola-dsp::yin::MAX_FRAME_SIZE` sans dupliquer la constante côté C.
#[no_mangle]
pub extern "C" fn psola_yin_max_frame_size() -> usize {
    YIN_MAX_FRAME_SIZE
}
