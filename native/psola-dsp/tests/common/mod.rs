//! Utilitaires partagés entre les fichiers de tests d'intégration.

/// Petit LCG (générateur congruentiel linéaire) reproductible — évite une dépendance externe
/// (`rand`) pour rester cohérent avec la philosophie "zéro dépendance" du crate, y compris
/// dans les tests (un dev-dependency n'atterrit jamais dans le binaire livré, mais autant
/// rester simple : ce générateur suffit largement pour un sweep de test).
pub struct Lcg {
    state: u64,
}

impl Lcg {
    pub fn new(seed: u64) -> Self {
        Self { state: seed }
    }

    fn next_u64(&mut self) -> u64 {
        // Constantes Numerical Recipes — pas de prétention cryptographique, juste une
        // distribution suffisamment étalée pour un sweep de test reproductible.
        self.state = self
            .state
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.state
    }

    /// f32 uniforme dans `[min, max)`.
    pub fn next_f32(&mut self, min: f32, max: f32) -> f32 {
        let unit = (self.next_u64() >> 40) as f32 / (1u64 << 24) as f32; // [0,1)
        min + unit * (max - min)
    }

    /// usize uniforme dans `[min, max]` (bornes incluses) — pour des tailles de bloc de
    /// callback aléatoires (voir `sample_rate_and_latency_sweep.rs`).
    ///
    /// `#[allow(dead_code)]` : `common/mod.rs` est recompilé séparément pour CHAQUE binaire de
    /// test d'intégration (chacun est son propre crate) — un binaire qui n'utilise pas cette
    /// méthode la verrait sinon signalée "jamais utilisée", alors qu'elle l'est bien par un
    /// autre binaire de la suite.
    #[allow(dead_code)]
    pub fn next_usize(&mut self, min: usize, max: usize) -> usize {
        min + (self.next_u64() as usize) % (max - min + 1)
    }
}
