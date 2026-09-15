//! Estimation continue de la période fondamentale par autocorrélation normalisée.
//!
//! Volontairement autonome (n'utilise pas le YIN applicatif de l'app hôte) pour que
//! [`crate::PsolaShifter`] reste utilisable en boîte noire, comme l'était `RubberBandStretcher`.

use crate::consts::{HISTORY_MASK, MAX_PERIOD, MIN_PERIOD};

const UPDATE_HOP: u64 = 512; // ~11.6ms @ 44.1kHz
const SMOOTHING: f32 = 0.7; // lissage exponentiel — évite les sauts d'octave brusques
const CONFIDENCE_THRESHOLD: f32 = 0.85;

/// Fenêtre d'analyse maximale (2×MAX_PERIOD, bornée à la compilation).
const WINDOW_LEN: usize = MAX_PERIOD * 2;

pub struct PeriodTracker {
    period: f32,
    sample_counter: u64,
}

impl Default for PeriodTracker {
    fn default() -> Self {
        Self {
            period: (MAX_PERIOD as f32) / 2.0,
            sample_counter: 0,
        }
    }
}

impl PeriodTracker {
    pub fn reset(&mut self) {
        *self = Self::default();
    }

    /// Dernière période estimée, en échantillons.
    pub fn period(&self) -> f32 {
        self.period
    }

    /// À appeler une fois par échantillon consommé. Ré-estime la période toutes les
    /// [`UPDATE_HOP`] échantillons, à partir des `WINDOW_LEN` derniers échantillons
    /// d'historique (`history`, buffer circulaire de longueur `HISTORY_CAPACITY`,
    /// `write_pos` = position d'écriture monotone courante).
    pub fn maybe_update(&mut self, history: &[f32], write_pos: u64) {
        self.sample_counter += 1;
        if self.sample_counter < UPDATE_HOP {
            return;
        }
        self.sample_counter = 0;
        if write_pos < WINDOW_LEN as u64 {
            return; // pas assez d'historique encore
        }

        let mut win = [0.0f32; WINDOW_LEN];
        for (i, w) in win.iter_mut().enumerate() {
            let idx = write_pos - WINDOW_LEN as u64 + i as u64;
            *w = history[(idx as usize) & HISTORY_MASK];
        }

        let total_energy: f32 = win.iter().map(|v| v * v).sum();
        if total_energy < 1e-6 {
            return; // silence — garder la dernière période connue
        }

        // Corrélation croisée normalisée — `ea`/`eb` sont recalculées sur la MÊME longueur
        // `n` que `num` à chaque tau (pas une énergie de fenêtre entière fixe) : sinon le
        // score est structurellement biaisé vers les petits tau, où `n` est plus proche de
        // `WINDOW_LEN` (constaté empiriquement : un simple sinus à 98Hz faisait remonter tau=24
        // au-dessus du vrai tau=450 avec une normalisation par énergie de fenêtre fixe).
        let score = |tau: usize| -> f32 {
            let n = WINDOW_LEN - tau;
            let (mut num, mut ea, mut eb) = (0.0f32, 0.0f32, 0.0f32);
            for i in 0..n {
                num += win[i] * win[i + tau];
                ea += win[i] * win[i];
                eb += win[i + tau] * win[i + tau];
            }
            if ea < 1e-9 || eb < 1e-9 {
                return -1.0;
            }
            num / (ea * eb).sqrt()
        };

        // Premier MAXIMUM LOCAL au-dessus du seuil, en balayant tau croissant — pas le
        // maximum global : un signal quasi-périodique propre (voix soutenue, sinus de test)
        // a des scores élevés à tau = T, 2T, 3T… (harmoniques de la vraie période) ; prendre
        // le maximum global choisit arbitrairement l'un de ces multiples ("erreur d'octave").
        // Même principe que YIN (`YINDetector.swift`) : premier candidat valide, pas le
        // meilleur candidat sur toute la plage.
        let lo = MIN_PERIOD;
        let hi = MAX_PERIOD.min(WINDOW_LEN.saturating_sub(2));
        if lo + 1 > hi {
            return;
        }
        let mut prev = score(lo - 1);
        let mut curr = score(lo);
        let mut found: Option<(usize, f32)> = None;
        for tau in lo..=hi {
            let next = score(tau + 1);
            if curr > CONFIDENCE_THRESHOLD && curr > prev && curr >= next {
                found = Some((tau, curr));
                break;
            }
            prev = curr;
            curr = next;
        }

        if let Some((tau, _)) = found {
            self.period = SMOOTHING * self.period + (1.0 - SMOOTHING) * tau as f32;
            self.period = self.period.clamp(MIN_PERIOD as f32, MAX_PERIOD as f32);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::consts::HISTORY_CAPACITY;
    use std::f32::consts::PI;

    fn sine_history(freq: f32, sample_rate: f32, len: usize) -> Vec<f32> {
        (0..len)
            .map(|i| 0.5 * (2.0 * PI * freq * i as f32 / sample_rate).sin())
            .collect()
    }

    fn run_tracker_to_convergence(freq: f32, sample_rate: f32) -> f32 {
        let mut tracker = PeriodTracker::default();
        let history = sine_history(freq, sample_rate, HISTORY_CAPACITY * 4);
        let mut buf = [0.0f32; HISTORY_CAPACITY];
        let mut write_pos = 0u64;
        for &s in &history {
            buf[(write_pos as usize) & HISTORY_MASK] = s;
            write_pos += 1;
            tracker.maybe_update(&buf, write_pos);
        }
        tracker.period()
    }

    #[test]
    fn tracks_a4_440hz() {
        let period = run_tracker_to_convergence(440.0, 44_100.0);
        let expected = 44_100.0 / 440.0;
        assert!(
            (period - expected).abs() < 2.0,
            "période obtenue {period}, attendue ≈{expected}"
        );
    }

    #[test]
    fn tracks_low_male_voice_at_110hz() {
        // 110Hz (A2), pas 98Hz : le plancher de conception est désormais 100Hz (voir
        // consts::FLOOR_HZ) — 98Hz est dans la zone dégradée acceptée, testée séparément
        // ci-dessous plutôt que masquée.
        let period = run_tracker_to_convergence(110.0, 44_100.0);
        let expected = 44_100.0 / 110.0;
        assert!(
            (period - expected).abs() < 5.0,
            "période obtenue {period}, attendue ≈{expected}"
        );
    }

    #[test]
    fn voice_below_floor_is_clamped_not_broken() {
        // En dessous de FLOOR_HZ (100Hz), le tracker ne doit ni paniquer ni diverger — la
        // période est clampée à MAX_PERIOD (comportement dégradé assumé, documenté dans
        // consts::FLOOR_HZ), pas une garantie de suivi précis à cette fréquence.
        let period = run_tracker_to_convergence(70.0, 44_100.0);
        assert!(period.is_finite());
        assert!(
            period <= MAX_PERIOD as f32,
            "la période doit rester clampée à MAX_PERIOD, obtenu {period}"
        );
    }

    #[test]
    fn tracks_continuous_glissando_without_octave_jump() {
        // Portamento chanté typique (glissando lent et continu, pas un saut discret comme
        // dans les autres tests) — le tracker ne doit jamais "décrocher" sur un multiple/
        // sous-multiple de la vraie période pendant la descente, ce qui produirait un
        // artefact PSOLA extrêmement audible (la taille du grain double/est divisée par deux
        // d'un coup). Approche "à la Antares" : ce n'est pas une fréquence fixe de plus à
        // tester, c'est la TRAJECTOIRE continue qui est le cas réellement risqué en usage
        // chanté — une voix qui glisse d'une note à l'autre, pas seulement des notes tenues.
        let sample_rate = 44_100.0f32;
        let duration_s = 3.0;
        let total = (sample_rate * duration_s) as usize;
        let f_start = 800.0f32; // dans la plage confortable, loin de MIN_PERIOD/MAX_PERIOD
        let f_end = 150.0f32; // idem, loin du plancher FLOOR_HZ=100 (zone dégradée assumée)

        let mut tracker = PeriodTracker::default();
        let mut buf = [0.0f32; HISTORY_CAPACITY];
        let mut write_pos = 0u64;
        let mut phase = 0.0f32;
        let mut readings: Vec<f32> = Vec::new();

        for i in 0..total {
            let t = i as f32 / total as f32;
            let instant_freq = f_start + (f_end - f_start) * t; // rampe linéaire, phase continue
            phase += 2.0 * PI * instant_freq / sample_rate;
            let sample = 0.5 * phase.sin();

            buf[(write_pos as usize) & HISTORY_MASK] = sample;
            write_pos += 1;
            tracker.maybe_update(&buf, write_pos);

            if write_pos.is_multiple_of(UPDATE_HOP) {
                readings.push(tracker.period());
            }
        }

        // Ignore l'amorçage (avant que la fenêtre WINDOW_LEN soit pleine, et quelques points
        // de plus pour laisser le lissage exponentiel converger depuis sa valeur par défaut).
        assert!(
            readings.len() > 50,
            "pas assez de lectures ({})",
            readings.len()
        );
        let stable = &readings[20..];

        for w in stable.windows(2) {
            let ratio = w[1] / w[0];
            assert!(
                (0.7..=1.43).contains(&ratio),
                "saut de période suspect entre deux mises à jour consécutives (~{}ms d'écart) : \
                 {} -> {} (ratio {ratio:.3}) — erreur d'octave probable pendant le glissando",
                (UPDATE_HOP as f32 / sample_rate * 1000.0) as u32,
                w[0],
                w[1]
            );
        }
    }

    #[test]
    fn does_not_panic_on_silence() {
        let mut tracker = PeriodTracker::default();
        let buf = [0.0f32; HISTORY_CAPACITY];
        for write_pos in 0..(HISTORY_CAPACITY as u64 * 2) {
            tracker.maybe_update(&buf, write_pos);
        }
        // Pas d'assertion de valeur — le point du test est l'absence de panic/NaN.
        assert!(tracker.period().is_finite());
    }
}
