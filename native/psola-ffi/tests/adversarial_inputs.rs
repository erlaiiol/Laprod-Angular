//! Frontière FFI sous paramètres dégénérés/adversariaux — la question qu'une équipe qui
//! construit un plugin audio commercial (type Antares) se pose systématiquement : "que se
//! passe-t-il si l'hôte (ici Kotlin/AAudio ou ObjC++/AVAudioEngine) nous passe quelque chose
//! d'absurde ?" Pas un scénario hypothétique gratuit — `sample_rate` traverse une frontière
//! AAudio dont la négociation réelle peut échouer de façons non documentées avant d'être
//! validée côté natif (voir `aaudio_engine_create`, qui vérifie déjà `getSampleRate()` après
//! ouverture — cette suite couvre ce qui se passerait si cette vérification n'existait pas, ou
//! si un bug futur la contournait).
//!
//! Contrat vérifié partout ici : jamais de panic, jamais de NaN/Inf qui s'échappe vers la
//! sortie audio, jamais d'écriture hors des bornes documentées — un repli silencieux (silence
//! en sortie / détection négative) est toujours le comportement correct, jamais un crash.

use psola_ffi::{
    psola_available, psola_create, psola_destroy, psola_process, psola_retrieve,
    psola_set_pitch_cents, psola_yin_detect,
};

fn assert_all_finite(buf: &[f32], context: &str) {
    for (i, &s) in buf.iter().enumerate() {
        assert!(
            s.is_finite(),
            "{context} : échantillon non fini à l'index {i} ({s})"
        );
    }
}

// ── psola_create — sample_rate dégénéré ──────────────────────────────────────────────────────

#[test]
fn create_with_zero_sample_rate_never_produces_non_finite_output() {
    unsafe {
        let handle = psola_create(0.0, 1);
        assert!(
            !handle.is_null(),
            "psola_create ne doit jamais paniquer sur sample_rate=0"
        );

        let input = [0.3f32; 512];
        let mut out = [0.0f32; 512];
        for _ in 0..8 {
            psola_process(handle, input.as_ptr(), input.len());
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
        }
        assert_all_finite(&out, "sample_rate=0.0");

        psola_destroy(handle);
    }
}

#[test]
fn create_with_negative_sample_rate_never_produces_non_finite_output() {
    unsafe {
        let handle = psola_create(-44_100.0, 1);
        assert!(!handle.is_null());

        let input = [0.3f32; 512];
        let mut out = [0.0f32; 512];
        for _ in 0..8 {
            psola_process(handle, input.as_ptr(), input.len());
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
        }
        assert_all_finite(&out, "sample_rate négatif");

        psola_destroy(handle);
    }
}

#[test]
fn create_with_nan_sample_rate_never_produces_non_finite_output() {
    unsafe {
        let handle = psola_create(f64::NAN, 1);
        assert!(!handle.is_null());

        let input = [0.3f32; 512];
        let mut out = [0.0f32; 512];
        for _ in 0..8 {
            psola_process(handle, input.as_ptr(), input.len());
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
        }
        assert_all_finite(&out, "sample_rate=NaN");

        psola_destroy(handle);
    }
}

#[test]
fn create_with_infinite_sample_rate_never_produces_non_finite_output() {
    unsafe {
        let handle = psola_create(f64::INFINITY, 1);
        assert!(!handle.is_null());

        let input = [0.3f32; 512];
        let mut out = [0.0f32; 512];
        for _ in 0..8 {
            psola_process(handle, input.as_ptr(), input.len());
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
        }
        assert_all_finite(&out, "sample_rate=+Inf");

        psola_destroy(handle);
    }
}

// ── psola_set_pitch_cents — valeurs non finies ───────────────────────────────────────────────
//
// Un bug de calcul en amont (Kotlin/Swift, division par zéro sur une correction) pourrait en
// théorie produire un NaN avant même d'atteindre cette frontière — le moteur ne doit ni
// paniquer, ni rester "empoisonné" (NaN propagé indéfiniment dans son état interne) après un
// tel appel.

#[test]
fn set_pitch_cents_nan_does_not_poison_subsequent_output() {
    unsafe {
        let handle = psola_create(44_100.0, 1);
        assert!(!handle.is_null());

        psola_set_pitch_cents(handle, f32::NAN);

        let input: Vec<f32> = (0..4096)
            .map(|i| 0.4 * (2.0 * std::f32::consts::PI * 220.0 * i as f32 / 44_100.0).sin())
            .collect();
        let mut out = vec![0.0f32; 512];
        let mut fed = 0;
        while fed < input.len() {
            let end = (fed + 512).min(input.len());
            psola_process(handle, input[fed..end].as_ptr(), end - fed);
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
            assert_all_finite(&out, "après psola_set_pitch_cents(NaN)");
            fed = end;
        }

        // Un ratio cible valide envoyé ENSUITE doit encore produire un effet normal — NaN ne
        // doit pas avoir laissé le moteur dans un état dégradé de façon permanente.
        psola_set_pitch_cents(handle, 0.0);
        for _ in 0..8 {
            psola_process(handle, input[..512].as_ptr(), 512);
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
        }
        assert_all_finite(&out, "après retour à un ratio valide");

        psola_destroy(handle);
    }
}

#[test]
fn set_pitch_cents_infinite_does_not_crash_or_poison_output() {
    unsafe {
        let handle = psola_create(44_100.0, 1);
        assert!(!handle.is_null());

        psola_set_pitch_cents(handle, f32::INFINITY);

        let input = [0.3f32; 4096];
        let mut out = [0.0f32; 512];
        let mut fed = 0;
        while fed < input.len() {
            psola_process(handle, input[fed..fed + 512].as_ptr(), 512);
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
            assert_all_finite(&out, "après psola_set_pitch_cents(+Inf)");
            fed += 512;
        }

        psola_destroy(handle);
    }
}

// ── len=0 — jamais un cas d'erreur, toujours un no-op propre ────────────────────────────────

#[test]
fn process_and_retrieve_with_zero_length_are_clean_no_ops() {
    unsafe {
        let handle = psola_create(44_100.0, 1);
        assert!(!handle.is_null());

        psola_process(handle, [].as_ptr(), 0);
        let before = psola_available(handle);

        let mut out = [7.0f32; 4]; // sentinelle
        psola_retrieve(handle, out.as_mut_ptr(), 0);
        assert_eq!(
            out, [7.0f32; 4],
            "retrieve(len=0) ne doit toucher aucun octet de `output`"
        );
        assert_eq!(
            psola_available(handle),
            before,
            "retrieve(len=0) ne doit rien consommer"
        );

        psola_destroy(handle);
    }
}

// ── psola_yin_detect — fréquences/longueurs dégénérées ───────────────────────────────────────

fn sine_frame(len: usize, sample_rate: f32, freq: f32) -> Vec<f32> {
    (0..len)
        .map(|i| 0.5 * (2.0 * std::f32::consts::PI * freq * i as f32 / sample_rate).sin())
        .collect()
}

#[test]
fn yin_detect_zero_sample_rate_returns_not_detected_not_panic() {
    unsafe {
        let frame = sine_frame(2048, 48_000.0, 440.0);
        let mut out_hz = -1.0f32;
        let found = psola_yin_detect(frame.as_ptr(), frame.len(), 0.0, &mut out_hz);
        assert_eq!(found, 0);
        assert_eq!(
            out_hz, -1.0,
            "out_hz ne doit pas être touché quand rien n'est détecté"
        );
    }
}

#[test]
fn yin_detect_negative_sample_rate_returns_not_detected_not_panic() {
    unsafe {
        let frame = sine_frame(2048, 48_000.0, 440.0);
        let mut out_hz = -1.0f32;
        let found = psola_yin_detect(frame.as_ptr(), frame.len(), -48_000.0, &mut out_hz);
        assert_eq!(found, 0);
    }
}

#[test]
fn yin_detect_nan_sample_rate_returns_not_detected_not_panic() {
    unsafe {
        let frame = sine_frame(2048, 48_000.0, 440.0);
        let mut out_hz = -1.0f32;
        let found = psola_yin_detect(frame.as_ptr(), frame.len(), f32::NAN, &mut out_hz);
        assert_eq!(found, 0);
    }
}

#[test]
fn yin_detect_zero_length_frame_returns_not_detected_not_panic() {
    unsafe {
        let mut out_hz = -1.0f32;
        // pointeur non nul mais longueur 0 — valide en soi (aucun octet réellement lu).
        let dummy = [0.0f32; 1];
        let found = psola_yin_detect(dummy.as_ptr(), 0, 48_000.0, &mut out_hz);
        assert_eq!(found, 0);
    }
}

#[test]
fn yin_detect_length_beyond_max_frame_size_is_rejected_not_panic() {
    unsafe {
        // `frame` pointe réellement vers ces `len` éléments valides (contrat de sécurité
        // documenté dans psola_ffi.h) — la longueur dépasse MAX_FRAME_SIZE (4096), ce qui
        // doit être rejeté par `detect()` lui-même, pas seulement "par chance" parce que le
        // buffer est trop court. Vérifie le rejet à la frontière FFI, en plus du test
        // équivalent déjà présent côté `psola-dsp::yin` (`oversized_frame_is_rejected...`).
        let frame = sine_frame(4096 + 2, 48_000.0, 440.0);
        let mut out_hz = -1.0f32;
        let found = psola_yin_detect(frame.as_ptr(), frame.len(), 48_000.0, &mut out_hz);
        assert_eq!(found, 0, "une longueur > MAX_FRAME_SIZE doit être rejetée");
    }
}
