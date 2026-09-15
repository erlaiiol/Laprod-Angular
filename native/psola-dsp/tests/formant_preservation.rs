//! Test d'acceptation dédié à la décision "LPC-PSOLA plutôt que PSOLA nu" documentée dans
//! `docs/roadmap.md` : un signal de voyelle synthétique (harmoniques de f0, enveloppe
//! spectrale centrée sur un formant F1 fixe) est décalé en hauteur ; le pic spectral de
//! sortie doit rester proche de F1, pas suivre le décalage de pitch (signature de l'effet
//! "chipmunk" qu'on cherche précisément à éviter).
//!
//! Pas de dépendance FFT externe : l'énergie à une fréquence donnée est mesurée via
//! l'algorithme de Goertzel (une poignée de lignes, suffisant pour comparer l'énergie à deux
//! fréquences candidates sans calculer un spectre complet).
//!
//! Historique : la première version de ce test générait le signal via un résonateur IIR
//! excité par un train d'impulsions. Ce générateur s'est révélé lui-même défectueux (vérifié
//! par une DFT brute-force de contrôle : son pic réel dérivait vers un harmonique proche de
//! f0 au lieu du formant demandé, indépendamment du moteur testé) — un faux négatif a
//! initialement fait accuser le moteur PSOLA+LPC d'un bug qui n'existait pas. Remplacé par
//! une synthèse additive directe (harmoniques de f0, pondérées par une enveloppe gaussienne
//! centrée sur F1), dont la position spectrale a été vérifiée indépendamment par DFT brute
//! avant d'être utilisée ici — voir `tests/antares_grade_quality.rs` pour la même leçon
//! appliquée au test à la transposition maximale réellement utilisée par l'app.

use psola_dsp::{cents_to_ratio, PsolaShifter};
use std::f32::consts::PI;

const SAMPLE_RATE: f32 = 44_100.0;

/// Signal de voyelle synthétique : somme d'harmoniques de `f0`, chacune pondérée par une
/// enveloppe gaussienne centrée sur `f1` (le formant) — donne un contrôle précis et
/// vérifiable de la position spectrale de l'énergie, contrairement à un résonateur IIR excité
/// par un train d'impulsions (sujet à des effets d'aliasing harmonique difficiles à prédire
/// analytiquement sans calcul préalable — voir l'historique ci-dessus).
fn vowel_like_signal(f0: f32, f1: f32, bandwidth: f32, count: usize) -> Vec<f32> {
    let mut out = vec![0.0f32; count];
    for h in 1..=12 {
        let hf = f0 * h as f32;
        if hf > SAMPLE_RATE / 2.5 {
            break;
        }
        let w = (-((hf - f1) / bandwidth).powi(2)).exp();
        if w < 0.01 {
            continue;
        }
        for (i, s) in out.iter_mut().enumerate() {
            *s += w * (2.0 * PI * hf * i as f32 / SAMPLE_RATE).sin();
        }
    }
    let max = out.iter().cloned().fold(0.0f32, |a, b| a.max(b.abs()));
    if max > 0.0 {
        for s in out.iter_mut() {
            *s *= 0.5 / max;
        }
    }
    out
}

fn goertzel_energy(signal: &[f32], target_hz: f32, sample_rate: f32) -> f32 {
    let n = signal.len();
    let windowed: Vec<f32> = signal
        .iter()
        .enumerate()
        .map(|(i, &x)| {
            let w = 0.5 - 0.5 * (2.0 * PI * i as f32 / (n as f32 - 1.0)).cos();
            x * w
        })
        .collect();
    let k = (0.5 + n as f32 * target_hz / sample_rate).floor();
    let omega = 2.0 * PI * k / n as f32;
    let coeff = 2.0 * omega.cos();
    let (mut s1, mut s2) = (0.0f32, 0.0f32);
    for &x in &windowed {
        let s0 = x + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    s1 * s1 + s2 * s2 - coeff * s1 * s2
}

#[test]
fn formant_peak_does_not_follow_pitch_shift_when_lpc_enabled() {
    // Mêmes valeurs que `antares_grade_quality.rs::formants_preserved_at_max_app_transposition`
    // (f1 = 5ᵉ harmonique exacte de f0, pic sans ambiguïté) — évite la fragilité rencontrée
    // avec des couples (f0, f1) où f1 tombe entre deux harmoniques : la mesure Goertzel à une
    // fréquence non-harmonique dépend alors fortement de la fenêtre/bande passante choisies,
    // ce qui a produit plusieurs faux négatifs pendant l'écriture de ces tests (voir
    // l'historique en tête de fichier).
    let f0 = 160.0f32;
    let f1 = 800.0f32; // formant fixe à préserver — exactement la 5ᵉ harmonique de f0
    const MONITOR_CAP_CENTS: f32 = 250.0; // plafond réel de l'app (PitchMonitorPlugin.kt)
    let cents = MONITOR_CAP_CENTS;
    let shifted_f0 = f0 * cents_to_ratio(cents);
    let chipmunk_f1 = f1 * shifted_f0 / f0; // ce que donnerait un simple resampling

    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(cents));

    let block_size = 512;
    let total = shifter.latency() + block_size * 40;
    // Bande passante 250Hz : plus large/réaliste qu'une résonance à bande étroite (150Hz),
    // moins sensible à la position exacte d'un seul harmonique dominant de f0 par rapport à
    // f1 (voir `tests/antares_grade_quality.rs::formants_preserved_at_max_app_transposition`,
    // où 150Hz produisait un faux négatif dépendant de la combinaison f0/f1/cents choisie).
    let input = vowel_like_signal(f0, f1, 250.0, total);

    let mut output = Vec::with_capacity(total);
    let mut fed = 0;
    let mut buf = vec![0.0f32; block_size];
    while fed < input.len() {
        let end = (fed + block_size).min(input.len());
        shifter.process(&input[fed..end]);
        shifter.retrieve(&mut buf);
        output.extend_from_slice(&buf);
        fed = end;
    }

    // On ignore le lookahead de latence + amorçage LPC/tracker pour ne mesurer que du signal
    // stabilisé.
    let settle = shifter.latency() * 4;
    let tail = &output[settle.min(output.len())..];
    assert!(
        tail.len() > 4096,
        "pas assez de sortie stabilisée pour mesurer le spectre"
    );

    let energy_at_true_f1 = goertzel_energy(tail, f1, SAMPLE_RATE);
    let energy_at_chipmunk_f1 = goertzel_energy(tail, chipmunk_f1, SAMPLE_RATE);

    assert!(
        energy_at_true_f1 > energy_at_chipmunk_f1,
        "le pic spectral a suivi le décalage de pitch (énergie@{f1}Hz={energy_at_true_f1}, énergie@{chipmunk_f1:.1}Hz={energy_at_chipmunk_f1}) — effet chipmunk non évité"
    );
}
