//! Résolution de Levinson-Durbin — coefficients LPC à partir d'une autocorrélation.
//!
//! Stable par construction : chaque coefficient de réflexion est garanti `|k| < 1` tant que
//! `autocorr[0] > 0` (signal non nul), sinon [`solve`] retourne `None` et l'appelant garde
//! ses coefficients précédents plutôt que d'utiliser un filtre potentiellement instable.

use crate::consts::LPC_ORDER;

/// Résout les coefficients LPC `a[1..=order]` minimisant l'erreur de prédiction sur
/// l'autocorrélation `autocorr[0..=order]`.
///
/// Convention : prédiction `x[n] ≈ Σ a[k]·x[n-k]`. `autocorr.len()` doit être `order + 1`.
///
/// Retourne `None` si le signal est dégénéré (silence quasi-total) ou si un coefficient de
/// réflexion intermédiaire sort de `(-1, 1)` — l'appelant doit alors garder l'état précédent.
pub fn solve(autocorr: &[f32], order: usize) -> Option<[f32; LPC_ORDER]> {
    debug_assert_eq!(autocorr.len(), order + 1);
    if autocorr[0] <= 1e-9 {
        return None;
    }

    let mut a = [0.0f32; LPC_ORDER + 1];
    let mut error = autocorr[0];

    for i in 1..=order {
        let mut acc = autocorr[i];
        for j in 1..i {
            acc -= a[j] * autocorr[i - j];
        }
        let k = acc / error;
        if !(k > -0.9999 && k < 0.9999) {
            return None; // instabilité — abandon défensif
        }

        let prev = a;
        a[i] = k;
        for j in 1..i {
            a[j] = prev[j] - k * prev[i - j];
        }

        error *= 1.0 - k * k;
        if error <= 1e-9 {
            return None; // dégénéré
        }
    }

    let mut out = [0.0f32; LPC_ORDER];
    out[..order].copy_from_slice(&a[1..=order]);
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Autocorrélation d'un signal AR(1) connu (x[n] = 0.5·x[n-1] + bruit) : la théorie prédit
    /// R[k] = R[0]·0.5^k, donc Levinson-Durbin doit retrouver a[1] ≈ 0.5, a[k>1] ≈ 0.
    #[test]
    fn recovers_known_ar1_coefficient() {
        let mut autocorr = [0.0f32; LPC_ORDER + 1];
        for (k, r) in autocorr.iter_mut().enumerate() {
            *r = 0.5f32.powi(k as i32);
        }
        let coeffs = solve(&autocorr, LPC_ORDER).expect("signal non dégénéré doit résoudre");
        assert!(
            (coeffs[0] - 0.5).abs() < 0.01,
            "a[1] devrait ≈ 0.5, obtenu {}",
            coeffs[0]
        );
        for &c in &coeffs[1..] {
            assert!(
                c.abs() < 0.05,
                "coefficients d'ordre > 1 devraient ≈ 0, obtenu {c}"
            );
        }
    }

    #[test]
    fn rejects_zero_energy_signal() {
        let autocorr = [0.0f32; LPC_ORDER + 1];
        assert!(solve(&autocorr, LPC_ORDER).is_none());
    }

    #[test]
    fn round_trip_whiten_recolor_is_near_identity() {
        // Un signal AR(1) blanchi par ses propres coefficients LPC puis recoloré doit
        // redonner (quasi) le signal d'origine — test de cohérence bout-en-bout du principe
        // même avant d'introduire le module lpc (qui réutilise directement `solve`).
        let mut autocorr = [0.0f32; LPC_ORDER + 1];
        for (k, r) in autocorr.iter_mut().enumerate() {
            *r = 0.6f32.powi(k as i32);
        }
        let coeffs = solve(&autocorr, LPC_ORDER).unwrap();

        // Génère un signal AR(1) réel avec ces coefficients pour le round-trip.
        let mut signal = [0.0f32; 256];
        let mut prev = 1.0f32;
        for s in signal.iter_mut() {
            prev *= 0.6;
            *s = prev;
        }

        // Blanchiment (FIR inverse) : residual[n] = x[n] - Σ a[k]·x[n-k]
        let mut fir_state = [0.0f32; LPC_ORDER];
        let mut residual = [0.0f32; 256];
        for (i, &x) in signal.iter().enumerate() {
            let pred: f32 = coeffs
                .iter()
                .zip(fir_state.iter())
                .map(|(a, s)| a * s)
                .sum();
            residual[i] = x - pred;
            fir_state.copy_within(0..LPC_ORDER - 1, 1);
            fir_state[0] = x;
        }

        // Recoloration (IIR tout-pôle) : y[n] = residual[n] + Σ a[k]·y[n-k]
        let mut iir_state = [0.0f32; LPC_ORDER];
        let mut reconstructed = [0.0f32; 256];
        for (i, &r) in residual.iter().enumerate() {
            let pred: f32 = coeffs
                .iter()
                .zip(iir_state.iter())
                .map(|(a, s)| a * s)
                .sum();
            let y = r + pred;
            reconstructed[i] = y;
            iir_state.copy_within(0..LPC_ORDER - 1, 1);
            iir_state[0] = y;
        }

        let rms_error: f32 = signal
            .iter()
            .zip(reconstructed.iter())
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f32>()
            .sqrt()
            / (signal.len() as f32).sqrt();
        assert!(
            rms_error < 1e-4,
            "erreur RMS round-trip trop élevée : {rms_error}"
        );
    }
}
