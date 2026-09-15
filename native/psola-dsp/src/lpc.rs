//! Préservation des formants : blanchit le signal (résidu ≈ plat spectralement) avant le
//! décalage de hauteur PSOLA, recolore après — l'enveloppe spectrale (formants) reste
//! indépendante du décalage de hauteur, contrairement à un PSOLA nu.

use crate::consts::{LPC_FRAME_SIZE, LPC_HOP, LPC_ORDER};
use crate::levinson;

pub struct LpcFormant {
    coeffs: [f32; LPC_ORDER],
    fir_state: [f32; LPC_ORDER],
    iir_state: [f32; LPC_ORDER],
    has_coeffs: bool,

    analysis_buf: [f32; LPC_FRAME_SIZE],
    analysis_pos: usize,
}

impl Default for LpcFormant {
    fn default() -> Self {
        Self {
            coeffs: [0.0; LPC_ORDER],
            fir_state: [0.0; LPC_ORDER],
            iir_state: [0.0; LPC_ORDER],
            has_coeffs: false,
            analysis_buf: [0.0; LPC_FRAME_SIZE],
            analysis_pos: 0,
        }
    }
}

impl LpcFormant {
    pub fn reset(&mut self) {
        *self = Self::default();
    }

    /// Accumule un échantillon d'entrée dans la fenêtre d'analyse ; recalcule les
    /// coefficients tous les [`LPC_HOP`] échantillons. À appeler une fois par échantillon,
    /// avant [`Self::whiten`].
    pub fn accumulate(&mut self, sample: f32) {
        self.analysis_buf[self.analysis_pos % LPC_FRAME_SIZE] = sample;
        self.analysis_pos += 1;
        if self.analysis_pos.is_multiple_of(LPC_HOP) && self.analysis_pos >= LPC_FRAME_SIZE {
            self.update_coefficients();
        }
    }

    /// Filtre FIR inverse (blanchiment) : `residual[n] = x[n] - Σ a[k]·x[n-k]`.
    /// Renvoie `sample` inchangé tant qu'aucun coefficient n'a encore été estimé — mais
    /// alimente `fir_state` même en passthrough : sinon, à l'activation des tout premiers
    /// coefficients, l'état du filtre (encore à zéro) ne refléterait pas le passé réel du
    /// signal et produirait un pic de résidu erroné le temps de "rattraper" `LPC_ORDER`
    /// échantillons — transitoire détecté par `tests/property_based.rs` (amplitude de
    /// sortie explosant juste après la première estimation de coefficients).
    pub fn whiten(&mut self, sample: f32) -> f32 {
        if !self.has_coeffs {
            push_state(&mut self.fir_state, sample);
            return sample;
        }
        let pred: f32 = self
            .coeffs
            .iter()
            .zip(self.fir_state.iter())
            .map(|(a, s)| a * s)
            .sum();
        let residual = sample - pred;
        push_state(&mut self.fir_state, sample);
        residual
    }

    /// Filtre IIR tout-pôle (recoloration) : `y[n] = residual[n] + Σ a[k]·y[n-k]`. Même
    /// raisonnement que [`Self::whiten`] pour l'alimentation de `iir_state` en passthrough.
    ///
    /// `max_output` est le filet de sécurité défensif : `y` y est borné. L'expansion de
    /// bande passante (`apply_bandwidth_expansion`) garantit une marge théorique de
    /// stabilité, mais un ajustement LPC sur un contenu à faible entropie spectrale (sinus
    /// quasi pur, note tenue très aiguë proche du plancher de période supporté) peut encore
    /// produire un gain transitoire très élevé le temps que les coefficients se
    /// stabilisent — observé concrètement sur `tests/property_based.rs`. Une équipe senior
    /// ne s'appuierait pas uniquement sur une preuve de stabilité théorique pour un système
    /// temps réel : ce clamp est la garantie *pratique*, complémentaire.
    ///
    /// `max_output` est fourni par l'appelant plutôt que suivi en interne : une première
    /// version de ce filet suivait sa propre enveloppe de crête *sur le résidu qu'il
    /// recevait déjà*, ce qui créait une boucle auto-référentielle — un premier pic
    /// exceptionnel faisait gonfler l'enveloppe, qui autorisait ensuite des pics tout aussi
    /// grands, sans jamais redescendre complètement (détecté par `tests/soak.rs` : amplitude
    /// restant à plusieurs dizaines pendant 30 s au lieu de retomber). `max_output`, dérivé
    /// par l'appelant de l'amplitude du signal d'entrée BRUT (qui ne peut par construction
    /// jamais dériver, borné à `[-1,1]`), casse cette boucle.
    pub fn recolor(&mut self, residual: f32, max_output: f32) -> f32 {
        if !self.has_coeffs {
            push_state(&mut self.iir_state, residual);
            return residual;
        }
        let pred: f32 = self
            .coeffs
            .iter()
            .zip(self.iir_state.iter())
            .map(|(a, s)| a * s)
            .sum();
        let y = residual + pred;
        let y_clamped = y.clamp(-max_output, max_output);

        push_state(&mut self.iir_state, y_clamped);
        y_clamped
    }

    fn update_coefficients(&mut self) {
        // Fenêtre de Hamming, relue dans l'ordre chronologique via analysis_pos (buffer
        // circulaire) — `base` = plus ancien échantillon du buffer.
        let base = self.analysis_pos % LPC_FRAME_SIZE;
        let mut windowed = [0.0f32; LPC_FRAME_SIZE];
        for (i, w) in windowed.iter_mut().enumerate() {
            let s = self.analysis_buf[(base + i) % LPC_FRAME_SIZE];
            let win = 0.54
                - 0.46
                    * (2.0 * std::f32::consts::PI * i as f32 / (LPC_FRAME_SIZE - 1) as f32).cos();
            *w = s * win;
        }

        let mut autocorr = [0.0f32; LPC_ORDER + 1];
        for (lag, r) in autocorr.iter_mut().enumerate() {
            let mut sum = 0.0f32;
            for i in 0..(LPC_FRAME_SIZE - lag) {
                sum += windowed[i] * windowed[i + lag];
            }
            *r = sum;
        }

        if let Some(mut new_coeffs) = levinson::solve(&autocorr, LPC_ORDER) {
            apply_bandwidth_expansion(&mut new_coeffs);
            // Remplacement direct, pas de lissage inter-trames : un lissage exponentiel des
            // coefficients bruts a été essayé puis abandonné — il dégradait nettement la
            // précision de suivi des formants (`tests/formant_preservation.rs` échouait,
            // le pic spectral décroché de sa position réelle), l'interpolation linéaire de
            // coefficients LPC bruts n'étant pas garantie interpoler entre deux filtres
            // stables de façon spectralement neutre. Le transitoire d'activation (première
            // estimation, passthrough→filtré) est géré séparément et correctement par
            // l'alimentation de `fir_state`/`iir_state` même en passthrough (voir
            // `whiten`/`recolor`) et par le filet de sécurité `max_output` de `recolor`.
            self.coeffs = new_coeffs;
            self.has_coeffs = true;
        }
        // Sinon : coefficients précédents conservés (trame dégénérée, ex. silence pur).
    }
}

fn push_state(state: &mut [f32; LPC_ORDER], newest: f32) {
    state.copy_within(0..LPC_ORDER - 1, 1);
    state[0] = newest;
}

/// Expansion de bande passante (`a'[k] = a[k]·γ^k`) — technique standard des codecs vocaux
/// (CELP et dérivés) pour garantir une marge de stabilité, pas seulement `|k| < 1` strict.
///
/// Levinson-Durbin garantit que chaque coefficient de réflexion individuel reste `|k| < 1`
/// (voir `levinson.rs`), ce qui suffit en théorie à garantir un filtre tout-pôle stable — mais
/// un ajustement sur un signal à faible entropie spectrale (ex. un sinus pur, quasi-tonal, ou
/// une note tenue très aiguë) peut produire des coefficients individuellement valides mais
/// combinés en un filtre à très haut facteur de qualité (pôles extrêmement proches du cercle
/// unité) : mathématiquement stable, mais avec un temps de décroissance si long qu'il se
/// comporte, sur toute fenêtre finie, comme une instabilité — c'est exactement ce qu'a révélé
/// `tests/property_based.rs` (amplitude de sortie explosant à plusieurs centaines sur un
/// sinus pur à 1149Hz). `γ ≈ 0.98` recule chaque pôle radialement vers l'origine d'environ 2%
/// par ordre — négligeable sur la position des formants réels (bien plus larges qu'un sinus
/// pur), mais garantit une marge de décroissance minimale dans tous les cas.
fn apply_bandwidth_expansion(coeffs: &mut [f32; LPC_ORDER]) {
    const GAMMA: f32 = 0.98;
    let mut factor = GAMMA;
    for c in coeffs.iter_mut() {
        *c *= factor;
        factor *= GAMMA;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reset_clears_filter_energy() {
        let mut lpc = LpcFormant::default();
        // Force des coefficients non triviaux + de l'énergie dans les filtres.
        for i in 0..2000 {
            let s = (i as f32 * 0.3).sin();
            lpc.accumulate(s);
            let r = lpc.whiten(s);
            let _ = lpc.recolor(r, 1000.0);
        }
        assert!(
            lpc.has_coeffs,
            "les coefficients auraient dû converger sur ce signal"
        );

        lpc.reset();
        assert!(!lpc.has_coeffs);
        assert_eq!(lpc.fir_state, [0.0; LPC_ORDER]);
        assert_eq!(lpc.iir_state, [0.0; LPC_ORDER]);

        // Après reset, whiten/recolor doivent repasser en passthrough (pas de coefficients).
        assert_eq!(lpc.whiten(1.0), 1.0);
        assert_eq!(lpc.recolor(1.0, 1000.0), 1.0);
    }

    #[test]
    fn whiten_then_recolor_round_trip_is_close_on_voiced_signal() {
        let mut lpc = LpcFormant::default();
        // Signal quasi-périodique (proche d'une voyelle) pour laisser les coefficients
        // converger avant de mesurer le round-trip.
        let signal: Vec<f32> = (0..4000)
            .map(|i| {
                let t = i as f32 / 44_100.0;
                0.6 * (2.0 * std::f32::consts::PI * 150.0 * t).sin()
                    + 0.2 * (2.0 * std::f32::consts::PI * 450.0 * t).sin()
            })
            .collect();

        let mut max_abs_error = 0.0f32;
        for &s in &signal {
            lpc.accumulate(s);
            let residual = lpc.whiten(s);
            let reconstructed = lpc.recolor(residual, 1000.0);
            // whiten() et recolor() partagent le même LpcFormant donc ne sont pas un vrai
            // round-trip indépendant ici (les états FIR/IIR divergent) — ce test vérifie
            // surtout l'absence de divergence explosive (stabilité), pas l'exactitude fine
            // (couverte séparément par le test round-trip de levinson.rs).
            max_abs_error = max_abs_error.max((s - reconstructed).abs());
        }
        assert!(
            max_abs_error < 10.0,
            "divergence excessive : {max_abs_error}"
        );
    }
}
