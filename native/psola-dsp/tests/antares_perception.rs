//! Tests de perception complémentaires à `antares_grade_quality.rs` — mêmes critères "à la
//! Antares" (transparence, absence d'artefact introduit par le moteur lui-même), sur trois
//! angles pas encore couverts : la préservation des formants est-elle symétrique (grave ET
//! aigu), le moteur introduit-il une coloration harmonique mesurable même sans décalage
//! demandé, un onset brutal produit-il un pré-écho (défaut classique des techniques à base de
//! grain/fenêtrage type PSOLA), et le moteur reste-t-il numériquement sain sur un signal quasi
//! silencieux prolongé (le cas le plus fréquent en usage réel : le chanteur entre les phrases).

use psola_dsp::{cents_to_ratio, PsolaShifter};
use std::f32::consts::PI;

const SAMPLE_RATE: f32 = 44_100.0;

fn sine_wave(frequency: f32, count: usize, amplitude: f32) -> Vec<f32> {
    (0..count)
        .map(|i| amplitude * (2.0 * PI * frequency * i as f32 / SAMPLE_RATE).sin())
        .collect()
}

fn run(shifter: &mut PsolaShifter, input: &[f32], block_size: usize) -> Vec<f32> {
    let mut output = Vec::with_capacity(input.len());
    let mut buf = vec![0.0f32; block_size];
    let mut fed = 0;
    while fed < input.len() {
        let end = (fed + block_size).min(input.len());
        shifter.process(&input[fed..end]);
        shifter.retrieve(&mut buf);
        output.extend_from_slice(&buf);
        fed = end;
    }
    output
}

fn goertzel_energy(signal: &[f32], target_hz: f32, sample_rate: f32) -> f32 {
    let k = (0.5 + signal.len() as f32 * target_hz / sample_rate).floor();
    let omega = 2.0 * PI * k / signal.len() as f32;
    let coeff = 2.0 * omega.cos();
    let (mut s1, mut s2) = (0.0f32, 0.0f32);
    for &x in signal {
        let s0 = x + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    s1 * s1 + s2 * s2 - coeff * s1 * s2
}

fn rms(signal: &[f32]) -> f32 {
    if signal.is_empty() {
        return 0.0;
    }
    (signal.iter().map(|v| v * v).sum::<f32>() / signal.len() as f32).sqrt()
}

/// Signal de voyelle synthétique — même générateur (vérifié par DFT brute-force) que
/// `antares_grade_quality.rs`/`formant_preservation.rs`, dupliqué ici (voir leur commentaire
/// pour le rationale complet ; ce fichier suit la même convention "chaque test d'intégration
/// est autonome" déjà établie dans le crate plutôt que d'introduire un module partagé).
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

// ── Formants préservés symétriquement — grave (down-shift) ET aigu (up-shift) ───────────────
//
// `formants_preserved_at_max_app_transposition` (antares_grade_quality.rs) ne couvre que la
// transposition vers le haut (+250 cents, effet "chipmunk" si les formants suivaient). Une
// correction d'autotune descend tout autant qu'elle monte — l'effet symétrique ("Darth Vader",
// formants qui suivent une baisse de pitch) est tout aussi audible et tout aussi couvert par
// la même couche LPC, mais n'était testé nulle part avant cette passe.

#[test]
fn formants_preserved_on_downward_shift() {
    const MONITOR_CAP_CENTS: f32 = -250.0; // même magnitude que le test up-shift, signe opposé

    let f0 = 220.0f32;
    let f1 = 900.0f32;
    let shifted_f0 = f0 * cents_to_ratio(MONITOR_CAP_CENTS);
    let darth_vader_f1 = f1 * shifted_f0 / f0; // formant qui aurait suivi la baisse de pitch

    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(MONITOR_CAP_CENTS));

    let block_size = 512;
    let total = shifter.latency() + block_size * 40;
    let input = vowel_like_signal(f0, f1, 250.0, total);
    let output = run(&mut shifter, &input, block_size);

    let settle = 8_000usize;
    let tail = &output[settle.min(output.len())..];
    assert!(tail.len() > 4096, "pas assez de sortie stabilisée");

    let energy_true = goertzel_energy(tail, f1, SAMPLE_RATE);
    let energy_darth_vader = goertzel_energy(tail, darth_vader_f1, SAMPLE_RATE);
    assert!(
        energy_true > energy_darth_vader,
        "formants non préservés en baisse de pitch ({MONITOR_CAP_CENTS} cents) : \
         énergie@{f1}Hz={energy_true}, énergie@{darth_vader_f1}Hz(suivrait la baisse)={energy_darth_vader}"
    );
}

// ── Pureté spectrale à ratio unité (mesure plus stricte que la corrélation) ──────────────────
//
// `unity_ratio_output_correlates_strongly_with_input` (antares_grade_quality.rs) mesure une
// similarité de forme d'onde globale — une corrélation de 0.85 tolère une coloration
// harmonique non négligeable sans la quantifier. Ce test mesure directement l'énergie ajoutée
// aux harmoniques d'un ton pur, qui est l'axe sur lequel un banc d'essai type Antares jugerait
// la "transparence" d'un pitch-shifter à l'unisson.

#[test]
fn unity_ratio_output_has_bounded_harmonic_distortion() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(0.0));

    // Fondamentale basse : laisse plusieurs harmoniques (2f, 3f, 4f) confortablement sous
    // Nyquist, pour que la mesure ne soit jamais faussée par du repliement.
    let f0 = 220.0f32;
    let block_size = 512;
    let total = shifter.latency() * 6 + block_size * 40;
    let input = sine_wave(f0, total, 0.5);
    let output = run(&mut shifter, &input, block_size);

    let settle = shifter.latency() * 4;
    let tail = &output[settle.min(output.len())..];
    assert!(tail.len() > 8192, "pas assez de sortie stabilisée");

    let fundamental = goertzel_energy(tail, f0, SAMPLE_RATE);
    let h2 = goertzel_energy(tail, f0 * 2.0, SAMPLE_RATE);
    let h3 = goertzel_energy(tail, f0 * 3.0, SAMPLE_RATE);
    let h4 = goertzel_energy(tail, f0 * 4.0, SAMPLE_RATE);
    assert!(
        fundamental > 1e-6,
        "fondamentale quasi nulle — signal perdu ?"
    );

    // Seuil généreux (10% d'énergie relative par harmonique, ≈ -20dB) : ce moteur n'a pas de
    // chemin de bypass dédié à ratio=1 (voir la note équivalente dans antares_grade_quality.rs)
    // — l'overlap-add PSOLA et le round-trip LPC introduisent une coloration réelle, mais elle
    // doit rester mineure comparée à la fondamentale, pas dominante.
    for (name, h) in [
        ("2ème harmonique", h2),
        ("3ème harmonique", h3),
        ("4ème harmonique", h4),
    ] {
        let ratio = h / fundamental;
        assert!(
            ratio < 0.10,
            "{name} trop énergique à ratio unité : {ratio:.4} de la fondamentale (seuil 0.10) \
             — coloration harmonique excessive pour un cas censé être quasi-transparent"
        );
    }
}

// ── Absence de pré-écho sur un onset brutal (défaut classique du grain/fenêtrage type PSOLA) ─
//
// Un algorithme à base de grains centrés sur des marques d'analyse peut, mal implémenté,
// laisser filtrer de l'énergie AVANT l'instant réel où le signal d'entrée cesse d'être
// silencieux — perçu comme un "souffle" ou un pré-écho juste avant une attaque, un défaut que
// les moteurs commerciaux (Antares compris) traitent comme un bug de premier ordre, pas un
// détail cosmétique.

#[test]
fn sudden_onset_does_not_leak_energy_before_the_true_onset() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(150.0)); // pas seulement le cas transparent — avec correction active

    let block_size = 512;
    let latency = shifter.latency();
    // Marge généreuse : silence largement plus long que la latence structurelle déclarée, pour
    // pouvoir isoler une région qui DOIT rester silencieuse dans la sortie même en tenant
    // compte du lookahead légitime du moteur.
    let pre_silence = latency * 3 + 4_000;
    let post_tone = block_size * 30;

    let mut input = vec![0.0f32; pre_silence];
    input.extend(sine_wave(220.0, post_tone, 0.6));

    let output = run(&mut shifter, &input, block_size);

    // Zone qui DOIT rester silencieuse : bien avant que l'onset réel (à `pre_silence`) ne
    // puisse légitimement se refléter dans la sortie (marge d'une période max de plus, au-delà
    // du lookahead déjà compté dans `latency`).
    let must_be_silent_end = pre_silence.saturating_sub(latency + 1_000);
    assert!(
        must_be_silent_end > 4096,
        "marge de test insuffisante, ajuster pre_silence"
    );
    let silent_zone = &output[..must_be_silent_end];

    let silent_rms = rms(silent_zone);
    assert!(
        silent_rms < 0.01,
        "énergie détectée AVANT l'onset réel (RMS={silent_rms:.5}) — pré-écho suspecté, le \
         moteur semble anticiper l'attaque au-delà de sa latence déclarée ({latency} échantillons)"
    );

    // Sanity check : le ton arrive bien plus tard, pour confirmer que le test n'est pas
    // trivialement vrai parce que le moteur ne produit jamais rien.
    let tail_rms = rms(&output[output.len() - block_size * 4..]);
    assert!(
        tail_rms > 0.05,
        "le ton attendu en fin de signal est quasi absent (RMS={tail_rms:.5}) — le test lui-même \
         serait invalide sans un vrai onset à mesurer"
    );
}

// ── Stabilité numérique sur signal quasi silencieux prolongé ────────────────────────────────
//
// Le cas le plus fréquent en usage réel n'est pas un ton fort soutenu : c'est le silence ou
// le bruit de fond entre deux phrases chantées. Un moteur qui borne son gain relativement à
// l'enveloppe d'entrée (voir `MAX_RESIDUAL_GAIN`/`MAX_OUTPUT_GAIN` dans `psola.rs`) doit rester
// stable même quand cette enveloppe est proche de zéro pendant longtemps — pas de division par
// une quasi-zéro qui exploserait, pas de NaN qui s'installerait silencieusement.

#[test]
fn near_silent_input_stays_finite_over_extended_duration() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(100.0));

    // Bruit de fond très faible mais non nul — un vrai silence numérique (zéro exact) ne
    // stresserait pas la clause `+ 1e-6` dans `input_envelope` autant qu'un signal réellement
    // proche du plancher.
    let mut lcg_state = 0x1234_5678u64;
    let mut next = || {
        lcg_state = lcg_state.wrapping_mul(6364136223846793005).wrapping_add(1);
        ((lcg_state >> 40) as f32 / (1u64 << 24) as f32 - 0.5) * 2.0
    };
    let count = 5 * SAMPLE_RATE as usize; // 5s
    let input: Vec<f32> = (0..count).map(|_| next() * 0.0005).collect();

    let block_size = 512;
    let output = run(&mut shifter, &input, block_size);

    for (i, &s) in output.iter().enumerate() {
        assert!(
            s.is_finite(),
            "échantillon non fini à l'index {i} sur signal quasi silencieux"
        );
    }
    // Borne de sécurité : même en régime de gain relatif élevé (MAX_OUTPUT_GAIN=10), un signal
    // d'entrée à ±0.0005 ne doit jamais produire une sortie proche de la pleine échelle.
    let peak = output.iter().cloned().fold(0.0f32, |a, b| a.max(b.abs()));
    assert!(
        peak < 0.5,
        "pic de sortie suspect ({peak}) pour une entrée quasi silencieuse (±0.0005) — \
         amplification disproportionnée sur signal proche du plancher de bruit"
    );
}
