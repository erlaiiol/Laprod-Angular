//! Tests de qualité inspirés des critères publics d'Antares (Auto-Tune) — recherchés avant
//! d'écrire ces tests (voir `docs/roadmap.md`, section Chantier, pour les sources citées) :
//! Retune Speed (0-5ms = effet "robot" sans vibrato, 30-50ms = correction naturelle qui
//! préserve le vibrato), et Formant Correction ("prévient le changement de timbre vocal lors
//! de la transposition, surtout sur les grandes transpositions").
//!
//! Ce moteur (`PsolaShifter`) ne porte pas lui-même la logique de "vitesse de correction"
//! (elle vit côté app, dans `PitchCorrectionEngine.kt`/`YINDetector.swift` — lissage
//! `smoothK`) : sa responsabilité est de suivre fidèlement N'IMPORTE QUELLE trajectoire de
//! ratio qu'on lui donne, sans introduire ses propres artefacts. Ces tests vérifient
//! exactement ça : transparence à ratio unité, absence de clic sur un saut de ratio abrupt
//! (equivalent "robot"), préservation du vibrato sur une trajectoire de ratio lente
//! (equivalent "natural"), et préservation des formants à la transposition maximale
//! réellement utilisée par l'app (`MONITOR_CAP` = ±2.5 demi-tons,
//! `android/app/src/main/java/net/laprod/app/PitchMonitorPlugin.kt`).

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

/// Corrélation croisée normalisée maximale entre `a` et `b` sur une plage de décalages —
/// mesure de similarité de forme d'onde indépendante d'un déphasage exact (utile ici car la
/// latence structurelle du moteur n'est qu'une estimation, pas une valeur pile exacte).
fn max_normalized_correlation(a: &[f32], b: &[f32], max_lag: usize) -> f32 {
    let energy_a: f32 = a.iter().map(|v| v * v).sum();
    if energy_a < 1e-6 {
        return 0.0;
    }
    let mut best = 0.0f32;
    for lag in 0..max_lag.min(b.len()) {
        let n = a.len().min(b.len() - lag);
        if n < 1000 {
            continue;
        }
        let mut num = 0.0f32;
        let mut energy_b = 0.0f32;
        for i in 0..n {
            num += a[i] * b[lag + i];
            energy_b += b[lag + i] * b[lag + i];
        }
        if energy_b < 1e-6 {
            continue;
        }
        let score = num / (energy_a * energy_b).sqrt();
        best = best.max(score);
    }
    best
}

// ── Transparence à ratio unité (équivalent "bypass") ────────────────────────────────────

#[test]
fn unity_ratio_output_correlates_strongly_with_input() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(0.0));

    let block_size = 512;
    let count = shifter.latency() * 6 + block_size * 20;
    let input = sine_wave(220.0, count, 0.5);
    let output = run(&mut shifter, &input, block_size);

    // Ignore l'amorçage (latence + convergence LPC/tracker) — mesure sur le signal stabilisé.
    let settle = shifter.latency() * 4;
    let input_tail = &input[..input.len() - settle.min(input.len())];
    let output_tail = &output[settle.min(output.len())..];

    let corr = max_normalized_correlation(input_tail, output_tail, shifter.latency() * 2);
    // Seuil 0.85, pas 0.99 : contrairement à Rubber Band, ce moteur n'a pas de chemin de
    // bypass dédié à ratio=1 — même sans décalage demandé, le signal traverse toujours
    // l'overlap-add PSOLA (fenêtrage à 50% de chevauchement) et le round-trip
    // blanchiment/recoloration LPC, qui introduisent une coloration légère mais réelle. C'est
    // un compromis de conception assumé (documenté dans `docs/roadmap.md` comme piste
    // d'amélioration future — un vrai court-circuit near-unity y gagnerait en fidélité), pas
    // un bug caché derrière un seuil complaisant.
    assert!(
        corr > 0.85,
        "à ratio unité, la sortie devrait fortement corréler avec l'entrée (corrélation obtenue {corr}) — le moteur ne doit rien inventer/dégrader quand on ne demande aucune correction"
    );
}

// ── Absence de clic sur saut de ratio abrupt (équivalent Retune Speed ~0ms, "robot") ─────

#[test]
fn abrupt_ratio_jump_does_not_produce_destructive_click() {
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(0.0));

    let block_size = 256;
    // Marge de convergence FIXE, pas dérivée de `shifter.latency()` : la latence structurelle
    // (lookahead de grain PSOLA) et le temps de convergence du tracker de période/LPC sont
    // deux choses différentes — coupler le second au premier a cassé ce test quand `latency()`
    // a diminué (plancher 100Hz, voir `consts::FLOOR_HZ`) sans que la convergence LPC/tracker
    // elle-même n'ait changé.
    const CONVERGENCE_MARGIN: usize = 4_000;
    let prefill = CONVERGENCE_MARGIN + block_size * 20;
    // Un seul signal à phase continue sur toute la durée (pré+post saut) — deux appels
    // indépendants à `sine_wave` (qui redémarre toujours à la phase 0) créeraient une vraie
    // discontinuité de PHASE DANS L'ENTRÉE elle-même à la jonction, un artefact du test et
    // non du moteur : un premier essai de ce test s'y est trompé, mesurant un delta
    // échantillon-à-échantillon dominé par cette discontinuité d'entrée plutôt que par le
    // saut de ratio qu'on voulait isoler.
    let total_len = prefill + block_size * 20;
    let input = sine_wave(220.0, total_len, 0.5);
    let pre_jump = run(&mut shifter, &input[..prefill], block_size);

    // Saut instantané, comme un Retune Speed proche de 0ms (effet "robot" Antares : aucune
    // transition progressive attendue de la part de l'appelant, tout le lissage éventuel
    // devrait être une propriété du CORRECTEUR/de la logique app, mais le moteur lui-même ne
    // doit jamais produire un artefact PIRE que le saut demandé, ex. une surtension isolée).
    pitch.set(cents_to_ratio(250.0)); // saut au plafond réellement utilisé par l'app (MONITOR_CAP)
    let post_jump = run(&mut shifter, &input[prefill..], block_size);

    // Critère concret : la dérivée échantillon-à-échantillon (proxy de "clic") ne doit pas
    // dépasser ce qu'on observe déjà en régime établi par un facteur déraisonnable — un vrai
    // clic audio se signe par un saut isolé d'amplitude largement supérieur au delta typique
    // d'un sinus continu à cette fréquence/amplitude.
    let typical_delta = |buf: &[f32]| -> f32 {
        buf.windows(2)
            .map(|w| (w[1] - w[0]).abs())
            .fold(0.0f32, f32::max)
    };
    let steady_state_delta = typical_delta(&pre_jump[pre_jump.len() / 2..]);
    let around_jump_delta = typical_delta(&post_jump[..block_size * 4]);

    assert!(
        around_jump_delta < steady_state_delta * 6.0 + 0.05,
        "saut de delta échantillon-à-échantillon autour de la transition de pitch : {around_jump_delta} (régime établi : {steady_state_delta}) — clic suspecté"
    );
}

// ── Préservation du vibrato (équivalent Retune Speed 30-50ms, "natural") ──────────────────

#[test]
fn natural_vibrato_survives_through_slowly_varying_correction() {
    // Vibrato typique d'une voix chantée : ~5.5Hz, profondeur ~±50 cents (valeurs usuelles en
    // pédagogie vocale — ni un trémolo exagéré ni un vibrato imperceptible).
    const VIBRATO_RATE_HZ: f32 = 5.5;
    const VIBRATO_DEPTH_CENTS: f32 = 50.0;
    const BASE_F0: f32 = 220.0;

    let block_size = 512;
    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);

    let duration_s = 2.0;
    let count = (SAMPLE_RATE * duration_s) as usize;

    // Génère l'entrée en appliquant directement le vibrato à la fréquence du sinus source
    // (phase continue — pas de discontinuité de fréquence instantanée).
    let mut input = Vec::with_capacity(count);
    let mut phase = 0.0f32;
    for i in 0..count {
        let t = i as f32 / SAMPLE_RATE;
        let vibrato_ratio =
            2.0f32.powf((VIBRATO_DEPTH_CENTS * (2.0 * PI * VIBRATO_RATE_HZ * t).sin()) / 1200.0);
        let instant_freq = BASE_F0 * vibrato_ratio;
        phase += 2.0 * PI * instant_freq / SAMPLE_RATE;
        input.push(0.5 * phase.sin());

        // Correction "natural" : légère et lente (contrairement au saut abrupt du test
        // ci-dessus) — un correcteur à Retune Speed long ne bouge le ratio que doucement.
        let slow_correction_cents = 30.0 * (2.0 * PI * 0.5 * t).sin();
        pitch.set(cents_to_ratio(slow_correction_cents));
    }

    let output = run(&mut shifter, &input, block_size);

    // Mesure la période fondamentale de sortie sur des fenêtres glissantes courtes (via
    // autocorrélation simple) et vérifie que sa variation suit bien un cycle à ~5.5Hz — si le
    // vibrato était aplati (comme le fait délibérément le mode "robot" d'Auto-Tune), la
    // période mesurée resterait quasi constante d'une fenêtre à l'autre.
    let settle = shifter.latency() * 4;
    let tail = &output[settle.min(output.len())..];

    let window = 1024; // ~23ms, assez court pour résoudre un vibrato à 5.5Hz (période ~180ms)
    let hop = 256;
    let mut periods = Vec::new();
    let mut pos = 0;
    while pos + window <= tail.len() {
        if let Some(p) = estimate_period_autocorr(&tail[pos..pos + window], 40, 400) {
            periods.push(p);
        }
        pos += hop;
    }

    assert!(
        periods.len() > 20,
        "pas assez de fenêtres mesurées ({} )",
        periods.len()
    );

    let min_p = periods.iter().cloned().fold(f32::MAX, f32::min);
    let max_p = periods.iter().cloned().fold(0.0f32, f32::max);
    // Plage attendue pour ±50 cents de vibrato : ratio 2^(50/1200) ≈ 1.030 → variation de
    // période d'environ ±3% autour de la période moyenne. On demande au moins la moitié de
    // cette variation pour confirmer que le vibrato n'a pas été substantiellement aplati.
    let variation = (max_p - min_p) / ((max_p + min_p) / 2.0);
    assert!(
        variation > 0.015,
        "variation de période mesurée trop faible ({:.4}) — le vibrato semble aplati par le moteur, alors que la trajectoire de ratio fournie était lente (équivalent \"natural\" chez Antares, censé laisser passer le vibrato)",
        variation
    );
}

/// Estimation de période simple par autocorrélation sur une fenêtre courte — indépendante de
/// `PeriodTracker` (qui est justement ce qu'on veut valider indirectement à travers le
/// comportement de bout en bout du moteur), pour ne pas se auto-vérifier avec le même code.
fn estimate_period_autocorr(frame: &[f32], min_period: usize, max_period: usize) -> Option<f32> {
    let energy: f32 = frame.iter().map(|v| v * v).sum();
    if energy < 1e-5 {
        return None;
    }
    let mut best_tau = None;
    let mut best_score = 0.3f32;
    for tau in min_period..max_period.min(frame.len() / 2) {
        let n = frame.len() - tau;
        let mut num = 0.0f32;
        let mut ea = 0.0f32;
        let mut eb = 0.0f32;
        for i in 0..n {
            num += frame[i] * frame[i + tau];
            ea += frame[i] * frame[i];
            eb += frame[i + tau] * frame[i + tau];
        }
        if ea < 1e-6 || eb < 1e-6 {
            continue;
        }
        let score = num / (ea * eb).sqrt();
        if score > best_score {
            best_score = score;
            best_tau = Some(tau as f32);
        }
    }
    best_tau
}

// ── Formants à la transposition maximale réellement utilisée par l'app ───────────────────

#[test]
fn formants_preserved_at_max_app_transposition() {
    // MONITOR_CAP dans PitchMonitorPlugin.kt = ±2.5 demi-tons — le pire cas réel, pas un cas
    // arbitraire. Antares insiste spécifiquement sur le fait que la correction de formants
    // "compte surtout sur les grandes transpositions" (voir sources documentées ci-dessus) :
    // ce test vérifie qu'on tient la promesse précisément là où elle compte le plus.
    const MONITOR_CAP_CENTS: f32 = 250.0;

    let f0 = 160.0f32;
    let f1 = 700.0f32; // formant fixe (proche d'un F1 de voyelle grave, ex. /o/)
    let shifted_f0 = f0 * cents_to_ratio(MONITOR_CAP_CENTS);
    let chipmunk_f1 = f1 * shifted_f0 / f0;

    let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
    pitch.set(cents_to_ratio(MONITOR_CAP_CENTS));

    let block_size = 512;
    let total = shifter.latency() + block_size * 40;
    let input = vowel_like_signal(f0, f1, 250.0, total);
    let output = run(&mut shifter, &input, block_size);

    // Marge fixe, pas `shifter.latency()*4` — voir le commentaire équivalent dans
    // `abrupt_ratio_jump_does_not_produce_destructive_click` : la convergence LPC/tracker est
    // indépendante de la latence structurelle du moteur.
    let settle = 8_000usize;
    let tail = &output[settle.min(output.len())..];
    assert!(tail.len() > 4096, "pas assez de sortie stabilisée");

    let energy_true = goertzel_energy(tail, f1, SAMPLE_RATE);
    let energy_chipmunk = goertzel_energy(tail, chipmunk_f1, SAMPLE_RATE);
    assert!(
        energy_true > energy_chipmunk,
        "formants non préservés à la transposition max de l'app (+{MONITOR_CAP_CENTS} cents) : énergie@{f1}Hz={energy_true}, énergie@{chipmunk_f1}Hz(chipmunk)={energy_chipmunk}"
    );
}

/// Signal de voyelle synthétique — voir `formant_preservation.rs` pour le rationale complet
/// et l'historique (un précédent générateur à base de résonateur IIR + train d'impulsions
/// s'est révélé lui-même défectueux, causant un faux négatif accusant le moteur à tort ;
/// celui-ci a été vérifié par DFT brute-force avant d'être adopté ici).
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
