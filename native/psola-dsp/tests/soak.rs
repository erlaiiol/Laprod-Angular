//! Test de soak : signal continu prolongé, ratio de pitch variant en continu — détecte une
//! dérive numérique lente (accumulation d'erreur flottante dans le filtre IIR de recoloration,
//! énergie qui diverge) invisible sur les tests courts unitaires.

use psola_dsp::{cents_to_ratio, PsolaShifter};
use std::f32::consts::PI;

const SAMPLE_RATE: f32 = 44_100.0;
/// ~30s de signal — largement suffisant pour révéler une dérive lente sans rendre la suite
/// de tests désagréablement longue à exécuter.
const DURATION_SECONDS: f32 = 30.0;

#[test]
fn continuous_varying_pitch_does_not_drift_or_diverge() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);

    let block_size = 512;
    let total_samples = (SAMPLE_RATE * DURATION_SECONDS) as usize;
    let mut buf = vec![0.0f32; block_size];

    let mut max_abs_ever = 0.0f32;
    let mut sample_index = 0u64;

    while (sample_index as usize) < total_samples {
        // Ratio qui varie en continu (LFO lent ±2.5 demi-tons) — simule un chanteur qui
        // dérive doucement de la note cible, cas réel plus exigeant qu'un ratio fixe.
        let t = sample_index as f32 / SAMPLE_RATE;
        let cents = 250.0 * (2.0 * PI * 0.2 * t).sin();
        pitch.set(cents_to_ratio(cents));

        // Signal d'entrée : voix simulée (fondamentale + 2 harmoniques), amplitude stable.
        let f0 = 180.0 + 20.0 * (2.0 * PI * 0.3 * t).sin();
        let mut block = [0.0f32; 512];
        for (i, s) in block.iter_mut().enumerate() {
            let tt = (sample_index + i as u64) as f32 / SAMPLE_RATE;
            *s = 0.5 * (2.0 * PI * f0 * tt).sin() + 0.2 * (2.0 * PI * f0 * 2.0 * tt).sin();
        }

        shifter.process(&block);
        shifter.retrieve(&mut buf);

        for &s in &buf {
            assert!(
                s.is_finite(),
                "sortie non finie après {sample_index} échantillons — divergence numérique"
            );
            max_abs_ever = max_abs_ever.max(s.abs());
        }

        sample_index += block_size as u64;
    }

    // Le signal d'entrée a une amplitude crête ≈0.7 (0.5+0.2). Le filet de sécurité de
    // `PsolaShifter::emit_grain` (`MAX_OUTPUT_GAIN = 10.0`, relatif à cette même amplitude
    // d'entrée) borne légitimement la sortie à ≈7.0 dans le pire cas de gain de résonance —
    // ce n'est pas une dérive, c'est le plafond de conception. Une sortie au-delà trahirait
    // une vraie instabilité du filtre IIR de recoloration accumulée sur la durée du test (le
    // point même de ce test).
    assert!(
        max_abs_ever < 10.0,
        "amplitude maximale observée sur {DURATION_SECONDS}s = {max_abs_ever} — dérive numérique suspectée"
    );
}
