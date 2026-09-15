//! Détecteur de hauteur YIN — troisième portage fidèle du même algorithme (après
//! `YINDetector.swift` puis `YinPitchDetector.kt`), cette fois en Rust.
//!
//! Référence : de Cheveigné & Kawahara, "YIN, a fundamental frequency estimator for speech and
//! music", J. Acoust. Soc. Am. 111(4), 2002.
//!
//! Raison d'être de ce troisième portage (voir `docs/roadmap.md`, chantier latence) : pour
//! qu'un moteur audio AAudio bas niveau (Android) tienne ses promesses de latence, la boucle
//! chaude capture→détection→correction→sortie doit rester intégralement native — un aller-retour
//! JNI vers Kotlin à chaque bloc pour la détection de hauteur réintroduirait exactly le genre de
//! gigue/latence imprévisible qu'AAudio est censé éliminer. `YinPitchDetector.kt` reste la
//! version utilisée par le chemin `AudioRecord`/`AudioTrack` existant (fallback sur les
//! appareils sans AAudio) ; ce module est utilisé par `psola-ffi` pour le nouveau chemin AAudio.
//!
//! Fonction pure et sans état (contrairement aux deux autres portages qui pré-allouent leurs
//! buffers dans une struct) : les buffers de travail sont alloués sur la pile de l'appelant
//! (taille connue à la compilation) et passés en paramètre, pour rester `#![forbid(unsafe_code)]`
//! et sans allocation dynamique.

use crate::consts::MAX_PERIOD;

/// Taille de fenêtre max supportée par [detect] — les buffers de travail sont dimensionnés
/// dessus. `YinPitchDetector.kt`/`YINDetector.swift` utilisent 2048 ; borne un peu au-dessus
/// pour ne jamais contraindre un futur appelant à cette valeur précise.
pub const MAX_FRAME_SIZE: usize = 4096;
const MAX_HALF: usize = MAX_FRAME_SIZE / 2;

/// Détecte la fréquence fondamentale dans `frame` (mono, `frame.len()` échantillons,
/// `frame.len() <= MAX_FRAME_SIZE` et pair). Retourne `None` si non détectée.
///
/// `threshold` : seuil CMND (0.14 est la valeur par défaut historique des deux autres ports).
/// `min_frequency`/`max_frequency` en Hz.
pub fn detect(
    frame: &[f32],
    sample_rate: f32,
    threshold: f32,
    min_frequency: f32,
    max_frequency: f32,
) -> Option<f32> {
    let frame_size = frame.len();
    if frame_size == 0 || frame_size > MAX_FRAME_SIZE || !frame_size.is_multiple_of(2) {
        return None;
    }
    let half = frame_size / 2;

    // ── Étape 1 : Fonction de différence ────────────────────────────────────
    // d(τ) = Σ_{j=0}^{W-1} (x[j] - x[j+τ])²
    let mut diff = [0.0f32; MAX_HALF];
    for tau in 1..half {
        let w = frame_size - tau;
        let mut sum = 0.0f32;
        for j in 0..w {
            let delta = frame[j + tau] - frame[j];
            sum += delta * delta;
        }
        diff[tau] = sum;
    }

    // ── Étape 2 : CMND (Cumulative Mean Normalised Difference) ─────────────
    let mut cmnd = [0.0f32; MAX_HALF];
    cmnd[0] = 1.0;
    let mut running_sum = 0.0f32;
    for tau in 1..half {
        running_sum += diff[tau];
        cmnd[tau] = if running_sum > 0.0 {
            diff[tau] * tau as f32 / running_sum
        } else {
            1.0
        };
    }

    // ── Étape 3 : Premier minimum local sous le seuil ───────────────────────
    let tau_min = (sample_rate / max_frequency).ceil() as usize;
    let tau_max = (sample_rate / min_frequency).floor() as usize;
    if tau_max >= half {
        return None;
    }

    let lo = tau_min.max(2);
    let hi = (half - 1).min(tau_max + 1);
    for tau in lo..hi {
        if cmnd[tau] < threshold && cmnd[tau] < cmnd[tau - 1] && cmnd[tau] <= cmnd[tau + 1] {
            // ── Étape 4 : Interpolation parabolique (précision sub-échantillon) ──
            let s0 = cmnd[tau - 1];
            let s1 = cmnd[tau];
            let s2 = cmnd[tau + 1];
            let denom = 2.0 * (2.0 * s1 - s0 - s2);
            let tau_refined = if denom.abs() > 1e-6 {
                tau as f32 + (s0 - s2) / denom
            } else {
                tau as f32
            };

            let hz = sample_rate / tau_refined;
            if hz >= min_frequency && hz <= max_frequency {
                return Some(hz);
            }
        }
    }
    None
}

/// Fréquences par défaut alignées sur `PitchMonitorPlugin.kt`/`YinPitchDetector.kt` — évite
/// une divergence de configuration entre le chemin AAudio et le chemin AudioRecord fallback.
pub const DEFAULT_THRESHOLD: f32 = 0.14;
pub const DEFAULT_MIN_FREQUENCY: f32 = 80.0;
pub const DEFAULT_MAX_FREQUENCY: f32 = 1_200.0;

const _: () = assert!(MAX_PERIOD < MAX_HALF);

#[cfg(test)]
mod tests {
    use super::*;
    use std::f32::consts::PI;

    const SAMPLE_RATE: f32 = 48_000.0;
    const FRAME_SIZE: usize = 2048;

    fn sine_wave(frequency: f32, amplitude: f32) -> Vec<f32> {
        (0..FRAME_SIZE)
            .map(|i| amplitude * (2.0 * PI * frequency * i as f32 / SAMPLE_RATE).sin())
            .collect()
    }

    fn silence() -> Vec<f32> {
        vec![1e-7; FRAME_SIZE]
    }

    fn detect_default(frame: &[f32]) -> Option<f32> {
        detect(
            frame,
            SAMPLE_RATE,
            DEFAULT_THRESHOLD,
            DEFAULT_MIN_FREQUENCY,
            DEFAULT_MAX_FREQUENCY,
        )
    }

    #[test]
    fn detects_a4_440hz() {
        let hz = detect_default(&sine_wave(440.0, 0.5));
        assert!(hz.is_some());
        assert!((hz.unwrap() - 440.0).abs() < 5.0);
    }

    #[test]
    fn detects_e4_329hz() {
        let hz = detect_default(&sine_wave(329.63, 0.5));
        assert!(hz.is_some());
        assert!((hz.unwrap() - 329.63).abs() < 5.0);
    }

    #[test]
    fn detects_low_note_g2_98hz() {
        let hz = detect_default(&sine_wave(98.0, 0.5));
        assert!(hz.is_some());
        assert!((hz.unwrap() - 98.0).abs() < 3.0);
    }

    #[test]
    fn detects_high_note_e5_659hz() {
        let hz = detect_default(&sine_wave(659.25, 0.5));
        assert!(hz.is_some());
        assert!((hz.unwrap() - 659.25).abs() < 8.0);
    }

    #[test]
    fn returns_none_on_silence() {
        assert!(detect_default(&silence()).is_none());
    }

    #[test]
    fn frequency_below_min_is_rejected() {
        let hz = detect(&sine_wave(50.0, 0.5), SAMPLE_RATE, 0.14, 80.0, 1_200.0);
        assert!(hz.is_none());
    }

    #[test]
    fn frequency_above_max_stays_within_declared_bounds_if_detected() {
        // Même piège documenté dans YinPitchDetectorTest.kt : un sinus pur au-dessus du
        // plafond peut légitimement aliaser sur un sous-multiple entier dans la plage — pas
        // un bug de ce port (voir le commentaire détaillé côté Kotlin). On vérifie
        // l'invariant réellement garanti : la valeur retournée, si elle existe, reste dans
        // les bornes déclarées.
        if let Some(hz) = detect(&sine_wave(1_800.0, 0.5), SAMPLE_RATE, 0.14, 80.0, 1_200.0) {
            assert!((80.0..=1_200.0).contains(&hz));
        }
    }

    #[test]
    fn detects_male_voice_e2_82hz() {
        let hz = detect(&sine_wave(82.4, 0.5), SAMPLE_RATE, 0.14, 70.0, 1_200.0);
        assert!(
            hz.is_some(),
            "YIN doit détecter E2 (82 Hz) avec frameSize=2048"
        );
        assert!((hz.unwrap() - 82.4).abs() < 4.0);
    }

    #[test]
    fn odd_frame_size_is_rejected_not_panicking() {
        assert!(detect_default(&vec![0.0; 2047]).is_none());
    }

    #[test]
    fn oversized_frame_is_rejected_not_panicking() {
        assert!(detect_default(&vec![0.0; MAX_FRAME_SIZE + 2]).is_none());
    }
}
