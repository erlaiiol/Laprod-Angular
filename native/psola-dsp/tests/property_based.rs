//! Tests randomisés/property-based — au-delà des fréquences fixes de `rubberband_parity.rs`,
//! vérifie que les propriétés générales (pas de NaN/Inf, amplitude bornée, pas de panic)
//! tiennent sur un large échantillonnage de fréquences/ratios/amplitudes. Graine fixe :
//! reproductible d'une exécution à l'autre.

mod common;

use common::Lcg;
use psola_dsp::{cents_to_ratio, PsolaShifter};
use std::f32::consts::PI;

const SAMPLE_RATE: f64 = 44_100.0;
const ITERATIONS: usize = 300;

fn sine_wave(frequency: f32, count: usize, amplitude: f32) -> Vec<f32> {
    (0..count)
        .map(|i| amplitude * (2.0 * PI * frequency * i as f32 / SAMPLE_RATE as f32).sin())
        .collect()
}

#[test]
fn random_sweep_never_produces_nan_inf_or_unbounded_amplitude() {
    let mut rng = Lcg::new(0xC0FFEE);

    for iter in 0..ITERATIONS {
        let freq = rng.next_f32(80.0, 1200.0);
        let cents = rng.next_f32(-300.0, 300.0); // ±3 demi-tons
        let amplitude = rng.next_f32(0.05, 0.9);
        let formant = iter % 2 == 0; // alterne LPC on/off — les deux chemins doivent tenir

        let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE, formant);
        pitch.set(cents_to_ratio(cents));

        let block_size = 256;
        let total = shifter.latency() + block_size * 8;
        let sine = sine_wave(freq, total, amplitude);

        let mut fed = 0;
        let mut out = vec![0.0f32; block_size];
        while fed < sine.len() {
            let end = (fed + block_size).min(sine.len());
            shifter.process(&sine[fed..end]);
            shifter.retrieve(&mut out);
            fed = end;

            for &s in &out {
                assert!(
                    s.is_finite(),
                    "itération {iter} (freq={freq}, cents={cents}, amp={amplitude}, formant={formant}) : sortie non finie ({s})"
                );
                // Borne dérivée du filet de sécurité réel du moteur (`MAX_OUTPUT_GAIN = 10.0`
                // dans `PsolaShifter::emit_grain`, relatif à l'enveloppe du signal d'entrée
                // BRUT) — le but est de détecter une divergence, pas de vérifier un gain
                // unitaire strict (la préservation des formants a légitimement besoin d'un
                // gain de résonance non trivial, voir `formant_preservation.rs`).
                assert!(
                    s.abs() < amplitude * 11.0 + 1.5,
                    "itération {iter} (freq={freq}, cents={cents}, amp={amplitude}, formant={formant}) : amplitude de sortie non bornée ({s})"
                );
            }
        }
    }
}
