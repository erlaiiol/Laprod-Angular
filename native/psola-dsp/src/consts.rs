//! Bornes de compilation partagées par tout le crate.
//!
//! Toutes les tailles de buffer du chemin chaud dérivent de ces constantes — aucune
//! allocation dynamique n'est nécessaire nulle part dans le crate (voir `docs/roadmap.md`,
//! section "Disposition mémoire").

/// Fréquence d'échantillonnage maximale supportée (Android/iOS n'utilisent que 44.1/48kHz).
pub const MAX_SAMPLE_RATE: f64 = 48_000.0;

/// Plancher de fréquence fondamentale supporté par le moteur PSOLA — 100Hz, pas 70Hz.
///
/// Décision produit (pas un oubli) : la latence structurelle du moteur (`~1.5×période`)
/// est dominée par la voix la plus GRAVE qu'il doit pouvoir suivre. Couvrir jusqu'à 70Hz
/// (basse profonde) gonflait la latence pire-cas pour TOUTES les voix, alors que l'immense
/// majorité des utilisateurs chantent au-dessus de 100Hz. Compromis explicite : les voix
/// très graves (<100Hz) ont un suivi PSOLA dégradé (la période réelle dépasse `MAX_PERIOD`,
/// clampée) — acceptée en échange d'une latence bien plus basse pour tout le monde. La
/// détection YIN applicative ([FLOOR_HZ]) et la plage supportée par [MAX_PERIOD] sont
/// volontairement DÉCOUPLÉES : YIN continue de détecter jusqu'à `FLOOR_HZ` pour le report de
/// hauteur à l'app (`onPitch`), seul le pitch-shifting PSOLA lui-même est borné ici.
pub const FLOOR_HZ: f32 = 100.0;

/// Plafond de fréquence fondamentale supporté.
pub const CEIL_HZ: f32 = 1_200.0;

/// Période maximale en échantillons : ceil(48000/100) = 480 — voir [FLOOR_HZ] pour le
/// rationale du choix de 100Hz plutôt que 70Hz (latence pire-cas quasi divisée par 1.5).
pub const MAX_PERIOD: usize = 480;

/// Période minimale en échantillons : ceil(48000/1200) = 40, arrondi avec marge.
pub const MIN_PERIOD: usize = 24;

/// Capacité de l'historique circulaire (puissance de 2, > 4×MAX_PERIOD).
pub const HISTORY_CAPACITY: usize = 4096;
pub const HISTORY_MASK: usize = HISTORY_CAPACITY - 1;

/// Capacité du buffer de sortie circulaire (puissance de 2).
pub const OUT_CAPACITY: usize = 4096;
pub const OUT_MASK: usize = OUT_CAPACITY - 1;

/// Ordre du filtre LPC (formants F1-F4 pour une voix adulte à 44.1/48kHz).
pub const LPC_ORDER: usize = 24;

/// Fenêtre d'analyse LPC (échantillons) et son hop (chevauchement 50%).
pub const LPC_FRAME_SIZE: usize = 1024;
pub const LPC_HOP: usize = 512;

/// Borne défensive anti-boucle-infinie sur le nombre de grains émis par bloc `process()`.
pub const MAX_MARKS_PER_BLOCK: usize = 64;

const _: () = assert!(HISTORY_CAPACITY.is_power_of_two());
const _: () = assert!(OUT_CAPACITY.is_power_of_two());
const _: () = assert!(MAX_PERIOD * 4 < HISTORY_CAPACITY);
