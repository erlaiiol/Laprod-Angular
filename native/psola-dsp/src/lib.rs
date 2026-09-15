//! psola-dsp — cœur algorithmique du correcteur de hauteur temps réel maison.
//!
//! Remplace `RubberBandStretcher` (GPL-3.0) pour le monitoring vocal live pendant
//! l'enregistrement de toplines. Algorithme : TD-PSOLA (marques pitch-synchrones, extraction
//! de grain, overlap-add) + préservation des formants par LPC (blanchiment avant décalage,
//! recoloration après) — voir `docs/roadmap.md` pour le rationale complet.
//!
//! `#![forbid(unsafe_code)]` : ce crate ne contient et ne contiendra jamais de code `unsafe`.
//! Toute la frontière FFI (pointeurs bruts, JNI, ObjC) vit exclusivement dans le crate sœur
//! `psola-ffi`, jamais ici — voir `docs/roadmap.md`, section "Discipline d'ingénierie".
#![forbid(unsafe_code)]

mod consts;
mod levinson;
mod lpc;
mod period_tracker;
mod psola;
mod yin;

pub use psola::{PitchTarget, PsolaShifter};

pub use consts::{CEIL_HZ, FLOOR_HZ, MAX_PERIOD};
pub use yin::{
    detect as yin_detect, DEFAULT_MAX_FREQUENCY as YIN_DEFAULT_MAX_FREQUENCY,
    DEFAULT_MIN_FREQUENCY as YIN_DEFAULT_MIN_FREQUENCY, DEFAULT_THRESHOLD as YIN_DEFAULT_THRESHOLD,
    MAX_FRAME_SIZE as YIN_MAX_FRAME_SIZE,
};

/// Convertit un décalage en cents (1/100 de demi-ton) vers le ratio de fréquence attendu par
/// [`PitchTarget::set`]. Centralisé ici — pas dans `psola-ffi` ni dupliqué côté Kotlin/ObjC++
/// — pour n'avoir qu'une seule formule à maintenir des deux côtés de la frontière FFI.
pub fn cents_to_ratio(cents: f32) -> f32 {
    2.0f32.powf(cents / 1200.0)
}

#[cfg(test)]
mod cents_tests {
    use super::cents_to_ratio;

    #[test]
    fn zero_cents_is_unity_ratio() {
        assert!((cents_to_ratio(0.0) - 1.0).abs() < 1e-6);
    }

    #[test]
    fn plus_1200_cents_is_one_octave_up() {
        assert!((cents_to_ratio(1200.0) - 2.0).abs() < 1e-4);
    }

    #[test]
    fn minus_1200_cents_is_one_octave_down() {
        assert!((cents_to_ratio(-1200.0) - 0.5).abs() < 1e-4);
    }
}
