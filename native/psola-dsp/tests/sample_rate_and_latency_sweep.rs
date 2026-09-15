//! Fréquence d'échantillonnage réelle × latence × découpage de callback — au-delà de
//! `property_based.rs` (fréquences/ratios/amplitudes, mais toujours à 44.1kHz et toujours par
//! blocs fixes de 256 échantillons).
//!
//! Deux angles couverts ici et absents ailleurs dans la suite :
//!
//! 1. **Échantillonnage** : l'app tourne réellement à DEUX fréquences selon le chemin utilisé
//!    — 44.1kHz sur le chemin de repli `AudioCaptureLoop` (`SAMPLE_RATE` codé en dur côté
//!    Kotlin), et quoi que le device AAudio négocie sur le chemin rapide (vérifié
//!    explicitement égal à la valeur demandée depuis `aaudio_engine.c`, souvent 48kHz sur les
//!    devices Android récents — voir la vérification `getSampleRate` ajoutée dans
//!    `aaudio_engine_create`). Le moteur doit tenir ses garanties (borné, fini, latence sous le
//!    plafond produit) aux DEUX, pas seulement celle testée jusqu'ici.
//! 2. **Latence perçue** : le budget mémoire (`MAX_PERIOD`, donc `PsolaShifter::latency()`) est
//!    dimensionné en ÉCHANTILLONS pour `MAX_SAMPLE_RATE` (voir `consts.rs`) — indépendant de la
//!    fréquence réelle passée à `new()`. Concrètement, plus la fréquence réelle est haute, plus
//!    la même latence-en-échantillons représente MOINS de millisecondes. On vérifie ici le
//!    chiffre qui compte vraiment pour l'utilisateur : la latence structurelle en ms, contre le
//!    plafond que l'utilisateur a lui-même fixé en conversation ("20ms c'est déjà beaucoup pour
//!    s'écouter chanter dans un micro").
//! 3. **Découpage de callback** : AAudio NE GARANTIT PAS de taille de bloc fixe par callback
//!    (contrairement aux 256 échantillons fixes de `property_based.rs`) — voir
//!    `MAX_CALLBACK_FRAMES` dans `aaudio_engine.c`. Le moteur doit produire EXACTEMENT la même
//!    sortie quel que soit le découpage du même flux d'entrée en appels `process()` successifs
//!    — sinon la latence perçue varierait de façon imprévisible selon la charge système du
//!    moment, exactement ce que ce chantier cherche à éviter.

mod common;

use common::Lcg;
use psola_dsp::{cents_to_ratio, PsolaShifter, FLOOR_HZ, MAX_PERIOD};
use std::f32::consts::PI;

/// Les deux fréquences RÉELLEMENT utilisées par l'app (voir le module doc ci-dessus) — pas un
/// échantillonnage arbitraire de fréquences plausibles.
const REAL_WORLD_SAMPLE_RATES: [f64; 2] = [44_100.0, 48_000.0];

/// Plafond de latence perçue fixé par l'utilisateur en conversation (chantier latence,
/// `docs/roadmap.md`) — pas une estimation technique de ma part.
const USER_LATENCY_CEILING_MS: f64 = 20.0;

fn sine_wave(frequency: f32, sample_rate: f64, count: usize, amplitude: f32) -> Vec<f32> {
    (0..count)
        .map(|i| amplitude * (2.0 * PI * frequency * i as f32 / sample_rate as f32).sin())
        .collect()
}

// ── 1. Latence perçue (ms) sous le plafond utilisateur, aux deux fréquences réelles ─────────

#[test]
fn structural_latency_stays_under_user_specified_ceiling_at_both_sample_rates() {
    for &sr in &REAL_WORLD_SAMPLE_RATES {
        let (shifter, _pitch) = PsolaShifter::new(sr, true);
        let latency_samples = shifter.latency();
        let latency_ms = latency_samples as f64 / sr * 1000.0;

        assert!(
            latency_ms > 0.0,
            "latence structurelle nulle à {sr}Hz — suspect (aucun lookahead ?)"
        );
        assert!(
            latency_ms < USER_LATENCY_CEILING_MS,
            "latence structurelle {latency_ms:.1}ms à {sr}Hz dépasse le plafond utilisateur \
             ({USER_LATENCY_CEILING_MS}ms) — voir docs/roadmap.md, chantier latence"
        );
    }
}

// ── 2. La latence-en-échantillons ne s'adapte PAS à la fréquence réelle (comportement connu,
//       documenté dans consts.rs — ce test le PIN explicitement plutôt que de le laisser
//       implicite : si quelqu'un rend un jour MAX_PERIOD dépendant du sample_rate réel, ce
//       test échouera et forcera une décision consciente, pas une régression silencieuse). ────

#[test]
fn structural_latency_in_samples_is_independent_of_requested_sample_rate() {
    // 44.1k/48k : les deux fréquences réellement utilisées par l'app. 16k : nettement hors de
    // cette plage, pour bien démontrer que rien n'adapte MAX_PERIOD à la valeur passée ici.
    let (shifter_44k, _) = PsolaShifter::new(44_100.0, true);
    let (shifter_48k, _) = PsolaShifter::new(48_000.0, true);
    let (shifter_16k, _) = PsolaShifter::new(16_000.0, true);

    assert_eq!(shifter_44k.latency(), shifter_48k.latency());
    assert_eq!(shifter_44k.latency(), shifter_16k.latency());
    assert_eq!(shifter_44k.latency(), MAX_PERIOD + MAX_PERIOD / 2);
}

// ── 3. Plancher de détection réellement atteignable ne doit jamais être PIRE que documenté ──

#[test]
fn real_floor_hz_never_worse_than_documented_floor_at_supported_rates() {
    for &sr in &REAL_WORLD_SAMPLE_RATES {
        // La période la plus longue représentable (MAX_PERIOD échantillons) correspond à la
        // fréquence la plus basse suivable par PSOLA à CETTE fréquence d'échantillonnage —
        // voir le rationale de FLOOR_HZ dans consts.rs (buffers dimensionnés pour
        // MAX_SAMPLE_RATE=48kHz, donc le plancher réel est MEILLEUR, jamais pire, en-dessous).
        let real_floor_hz = sr / MAX_PERIOD as f64;
        assert!(
            real_floor_hz <= FLOOR_HZ as f64 + 1e-6,
            "à {sr}Hz, le plancher réellement atteignable ({real_floor_hz:.2}Hz) est PIRE que \
             le plancher documenté (FLOOR_HZ={FLOOR_HZ}Hz) — régression du rationale de consts.rs"
        );
    }
}

// ── 4. Sweep aléatoire (comme property_based.rs) répété aux deux fréquences réelles ─────────

#[test]
fn random_sweep_stays_finite_and_bounded_at_both_real_world_sample_rates() {
    const ITERATIONS_PER_RATE: usize = 150;

    for &sr in &REAL_WORLD_SAMPLE_RATES {
        let mut rng = Lcg::new(0xBADC0FFEE ^ (sr as u64));

        for iter in 0..ITERATIONS_PER_RATE {
            let freq = rng.next_f32(80.0, 1200.0);
            let cents = rng.next_f32(-300.0, 300.0);
            let amplitude = rng.next_f32(0.05, 0.9);
            let formant = iter % 2 == 0;

            let (mut shifter, pitch) = PsolaShifter::new(sr, formant);
            pitch.set(cents_to_ratio(cents));

            let block_size = 256;
            let total = shifter.latency() + block_size * 8;
            let sine = sine_wave(freq, sr, total, amplitude);

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
                        "sr={sr} itération {iter} (freq={freq}, cents={cents}, amp={amplitude}, \
                         formant={formant}) : sortie non finie ({s})"
                    );
                    assert!(
                        s.abs() < amplitude * 11.0 + 1.5,
                        "sr={sr} itération {iter} (freq={freq}, cents={cents}, amp={amplitude}, \
                         formant={formant}) : amplitude de sortie non bornée ({s})"
                    );
                }
            }
        }
    }
}

// ── 5. Indépendance vis-à-vis du découpage en callbacks (le scénario réel AAudio) ───────────

/// Alimente `shifter` en découpant `input` selon `chunk_sizes` (tronqué à `input.len()`),
/// drainant `retrieve()` après CHAQUE appel `process()` — comme le fait réellement
/// `onInputData`/`onOutputData` dans aaudio_engine.c, jamais en un seul bloc à la fin (le
/// buffer de sortie circulaire, `OUT_CAPACITY=4096`, serait sinon silencieusement écrasé avant
/// d'être lu si on laissait `out_write` courir trop loin devant `out_read`).
fn run_and_drain(shifter: &mut PsolaShifter, input: &[f32], chunk_sizes: &[usize]) -> Vec<f32> {
    let mut out = Vec::with_capacity(input.len());
    let mut pos = 0;
    for &chunk in chunk_sizes {
        if pos >= input.len() {
            break;
        }
        let end = (pos + chunk).min(input.len());
        shifter.process(&input[pos..end]);
        pos = end;

        let avail = shifter.available();
        if avail > 0 {
            let mut buf = vec![0.0f32; avail];
            shifter.retrieve(&mut buf);
            out.extend_from_slice(&buf);
        }
    }
    out
}

fn fixed_chunks(total: usize, size: usize) -> Vec<usize> {
    let mut v = Vec::new();
    let mut remaining = total;
    while remaining > 0 {
        let c = size.min(remaining);
        v.push(c);
        remaining -= c;
    }
    v
}

fn random_chunks(total: usize, rng: &mut Lcg, min: usize, max: usize) -> Vec<usize> {
    let mut v = Vec::new();
    let mut remaining = total;
    while remaining > 0 {
        let c = rng.next_usize(min, max).min(remaining);
        v.push(c);
        remaining -= c;
    }
    v
}

#[test]
fn variable_block_size_feeding_is_bit_identical_to_fixed_block_size_feeding() {
    const SAMPLE_RATE: f64 = 44_100.0;

    for &formant in &[false, true] {
        let (mut shifter_fixed, pitch_fixed) = PsolaShifter::new(SAMPLE_RATE, formant);
        let (mut shifter_variable, pitch_variable) = PsolaShifter::new(SAMPLE_RATE, formant);

        // Ratio identique et FIXE pour les deux (voir la doc de `run_and_drain` : ce test
        // isole l'effet du découpage en callbacks, pas celui d'un ratio qui varierait dans le
        // temps — déjà couvert par `antares_grade_quality.rs`).
        let ratio = cents_to_ratio(150.0);
        pitch_fixed.set(ratio);
        pitch_variable.set(ratio);

        let total = shifter_fixed.latency() + 6_000;
        let input = sine_wave(220.0, SAMPLE_RATE, total, 0.6);

        let fixed = fixed_chunks(total, 256);
        let mut rng = Lcg::new(0x5EED ^ (formant as u64));
        // Bornes réalistes vis-à-vis d'un vrai callback AAudio (voir MAX_CALLBACK_FRAMES dans
        // aaudio_engine.c) — inclut volontairement des blocs de taille 1 (pire cas) et des
        // rafales de plus de 4× un bloc `AudioCaptureLoop` standard.
        let variable = random_chunks(total, &mut rng, 1, 1_024);

        let out_fixed = run_and_drain(&mut shifter_fixed, &input, &fixed);
        let out_variable = run_and_drain(&mut shifter_variable, &input, &variable);

        assert_eq!(
            out_fixed.len(),
            out_variable.len(),
            "formant={formant} : nombre d'échantillons produits différent selon le découpage \
             en callbacks ({} vs {}) — la latence perçue dépendrait alors de la charge système",
            out_fixed.len(),
            out_variable.len()
        );
        for (i, (a, b)) in out_fixed.iter().zip(out_variable.iter()).enumerate() {
            assert_eq!(
                a.to_bits(),
                b.to_bits(),
                "formant={formant} : sortie divergente à l'index {i} selon le découpage en \
                 callbacks ({a} vs {b}) — le moteur ne devrait dépendre QUE du flux \
                 d'échantillons total, jamais de la façon dont il est chunké"
            );
        }
    }
}
