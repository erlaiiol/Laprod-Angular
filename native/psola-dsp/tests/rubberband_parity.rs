//! Portage 1:1 des assertions de `ios/App/AppTests/RubberBandWrapperTests.swift` contre le
//! nouveau moteur — contrat de non-régression comportementale vis-à-vis de Rubber Band.

use psola_dsp::{cents_to_ratio, PsolaShifter};
use std::f32::consts::PI;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

const SAMPLE_RATE: f64 = 48_000.0;

fn sine_wave(frequency: f32, count: usize, amplitude: f32) -> Vec<f32> {
    (0..count)
        .map(|i| amplitude * (2.0 * PI * frequency * i as f32 / SAMPLE_RATE as f32).sin())
        .collect()
}

fn feed_in_blocks(shifter: &mut PsolaShifter, samples: &[f32], block_size: usize) {
    let mut fed = 0;
    while fed < samples.len() {
        let end = (fed + block_size).min(samples.len());
        shifter.process(&samples[fed..end]);
        fed = end;
    }
}

// ── Init & latence ──────────────────────────────────────────────────────────────────────

#[test]
fn latency_is_positive() {
    let (shifter, _pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    assert!(
        shifter.latency() > 0,
        "le moteur doit annoncer une latence de démarrage positive"
    );
}

#[test]
fn latency_is_reasonably_small() {
    let (shifter, _pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    assert!(
        shifter.latency() <= 2048,
        "latence {} doit rester sous 2048 échantillons (~42ms @ 48kHz)",
        shifter.latency()
    );
}

// ── Rendu avant tout apport ─────────────────────────────────────────────────────────────

#[test]
fn retrieve_before_feed_outputs_zero() {
    let (mut shifter, _pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    let mut out = [1.0f32; 256]; // pré-rempli à une valeur non-nulle pour détecter un no-op
    shifter.retrieve(&mut out);
    assert!(
        out.iter().all(|&s| s == 0.0),
        "la sortie avant tout apport doit être du silence"
    );
}

// ── Chaîne feed → retrieve ──────────────────────────────────────────────────────────────

#[test]
fn output_is_non_zero_after_prefill() {
    let (mut shifter, _pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    let block_size = 512;
    let total_input = shifter.latency() + block_size * 2;
    let sine = sine_wave(440.0, total_input, 0.5);

    feed_in_blocks(&mut shifter, &sine, block_size);

    let mut out = [0.0f32; 512];
    shifter.retrieve(&mut out);
    let max_amp = out.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
    assert!(
        max_amp > 0.01,
        "après préremplissage ({} échantillons), la sortie doit être non-nulle (obtenu {})",
        shifter.latency(),
        max_amp
    );
}

// ── Décalage de hauteur ──────────────────────────────────────────────────────────────────

#[test]
fn set_pitch_cents_does_not_panic() {
    let (_shifter, pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    pitch.set(cents_to_ratio(0.0));
    pitch.set(cents_to_ratio(200.0));
    pitch.set(cents_to_ratio(-200.0));
    pitch.set(cents_to_ratio(250.0)); // ±2.5 demi-tons max applicatif
}

#[test]
fn zero_cents_preserves_amplitude() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    let block_size = 512;
    let prefill = shifter.latency() + block_size * 4;
    let sine = sine_wave(440.0, prefill, 0.5);

    pitch.set(cents_to_ratio(0.0));
    feed_in_blocks(&mut shifter, &sine, block_size);

    let mut out = [0.0f32; 512];
    shifter.retrieve(&mut out);
    let max_amp = out.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
    assert!(
        max_amp > 0.1,
        "un décalage nul doit préserver l'amplitude (attendu ~0.5, obtenu {max_amp})"
    );
}

// ── Reset ────────────────────────────────────────────────────────────────────────────────

#[test]
fn reset_clears_output() {
    let (mut shifter, _pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    let block_size = 512;
    let prefill = shifter.latency() + block_size * 2;
    let sine = sine_wave(440.0, prefill, 0.5);
    feed_in_blocks(&mut shifter, &sine, block_size);

    shifter.reset();

    let mut out = [0.0f32; 512];
    shifter.retrieve(&mut out);
    let max_amp = out.iter().fold(0.0f32, |m, &s| m.max(s.abs()));
    assert!(
        max_amp < 0.01,
        "après reset, la sortie doit redevenir du silence (obtenu {max_amp})"
    );
}

// ── Thread safety (test de fumée) ───────────────────────────────────────────────────────

#[test]
fn concurrent_pitch_updates_do_not_panic() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE, true);
    let done = Arc::new(AtomicBool::new(false));

    let pitch_thread_handle = {
        let pitch = pitch.clone();
        let done = done.clone();
        thread::spawn(move || {
            let mut i = 0;
            while !done.load(Ordering::Relaxed) {
                pitch.set(cents_to_ratio((i % 500) as f32 - 250.0));
                i += 1;
            }
        })
    };

    let block_size = 128;
    let sine = sine_wave(440.0, block_size * 200, 0.5);
    let mut out = [0.0f32; 128];
    let deadline = Instant::now() + Duration::from_secs(2);
    for block in sine.chunks(block_size) {
        if Instant::now() > deadline {
            break;
        }
        shifter.process(block);
        shifter.retrieve(&mut out);
    }

    done.store(true, Ordering::Relaxed);
    pitch_thread_handle
        .join()
        .expect("le thread de mise à jour du pitch ne doit pas paniquer");
}
