//! Cœur TD-PSOLA : marques d'analyse pitch-synchrones, extraction de grain, resynthèse OLA.
//!
//! Interface calquée sur le sous-ensemble de `RubberBandStretcher` réellement utilisé par les
//! wrappers Android/iOS (`process`, `available`, `retrieve`, `reset`, `latency`) — voir
//! `docs/roadmap.md`. Un seul thread "chaud" doit appeler `process`/`retrieve`/`reset` (accès
//! `&mut self`, imposé par le compilateur) ; [`PitchTarget::set`] est le seul point d'entrée
//! thread-safe, volontairement séparé du reste de l'état (voir sa documentation).

use crate::consts::{
    HISTORY_CAPACITY, HISTORY_MASK, MAX_MARKS_PER_BLOCK, MAX_PERIOD, MAX_SAMPLE_RATE, OUT_CAPACITY,
    OUT_MASK,
};
use crate::lpc::LpcFormant;
use crate::period_tracker::PeriodTracker;
use std::f32::consts::PI;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

/// Ratio de hauteur cible, partagé entre le thread audio (qui le lit) et un thread de
/// détection séparé (qui l'écrit) — seul état de [`PsolaShifter`] muté depuis plus d'un
/// thread. Isolé dans son propre type (et donc sa propre ligne de cache via `align(64)`)
/// pour que ni le compilateur ni un lecteur du code n'aient à deviner quelle partie de l'état
/// est réellement partagée : le type system le dit.
#[repr(C, align(64))]
pub struct PitchTarget {
    ratio_bits: AtomicU32,
}

impl Default for PitchTarget {
    fn default() -> Self {
        Self {
            ratio_bits: AtomicU32::new(1.0f32.to_bits()),
        }
    }
}

impl PitchTarget {
    /// Thread-safe, appelable depuis n'importe quel thread (typiquement le thread de
    /// détection de hauteur, séparé du thread audio).
    pub fn set(&self, ratio: f32) {
        let clamped = ratio.clamp(0.5, 2.0);
        self.ratio_bits.store(clamped.to_bits(), Ordering::Relaxed);
    }

    fn get(&self) -> f32 {
        f32::from_bits(self.ratio_bits.load(Ordering::Relaxed))
    }
}

pub struct PsolaShifter {
    formant_enabled: bool,

    history: Box<[f32; HISTORY_CAPACITY]>,
    residual_history: Box<[f32; HISTORY_CAPACITY]>,
    out_buf: Box<[f32; OUT_CAPACITY]>,

    write_pos: u64,
    out_write: u64,
    /// Filigrane "prêt à être lu" — en retard de la demi-période du dernier grain émis par
    /// rapport à `out_write`, pour ne jamais exposer via `retrieve()` un échantillon dont
    /// l'overlap-add n'a pas encore reçu la contribution du grain suivant (sinon la première
    /// moitié de chaque grain serait lue "à moitié sommée").
    out_ready: u64,
    out_read: u64,

    next_analysis_mark: u64,
    have_analysis_mark: bool,
    synth_accum: f32,

    tracker: PeriodTracker,
    lpc: LpcFormant,

    /// Enveloppe de crête du signal d'entrée BRUT (avant tout traitement LPC/PSOLA) — sert
    /// de référence de confiance, indépendante de tout état interne de filtre, pour borner
    /// défensivement le résidu (voir `process()`). Contrairement à une enveloppe suivie à
    /// l'intérieur de `LpcFormant`, celle-ci ne peut jamais elle-même dériver : elle ne fait
    /// que refléter un signal dont on connaît le contrat (`[-1, 1]`).
    input_envelope: f32,

    /// Version lissée (une constante de temps ~3ms) du ratio cible lu depuis `pitch_target`.
    /// `PitchTarget::set` peut être appelé avec un saut instantané (ex. un correcteur "robot"
    /// à Retune Speed ~0ms, cf. `docs/roadmap.md`) — appliquer ce saut tel quel au budget de
    /// synthèse PSOLA d'un échantillon à l'autre créerait une discontinuité de densité de
    /// grains audible (un clic). Un lissage de quelques millisecondes, largement en-dessous
    /// du seuil de perception d'un délai de réponse pour une correction de hauteur, absorbe
    /// ce saut sans jamais l'exposer comme un artefact — pratique standard pour tout
    /// paramètre temps réel modifié en direct (pas spécifique à ce moteur).
    smoothed_ratio: f32,

    pitch_target: Arc<PitchTarget>,
}

/// Coefficient de lissage par échantillon pour `smoothed_ratio` — constante de temps ~3ms
/// (`RATIO_SMOOTHING_TIME_CONSTANT_SAMPLES` échantillons pour atteindre ~63% de la cible).
const RATIO_SMOOTHING_TIME_CONSTANT_SAMPLES: f32 = 130.0; // ≈3ms @ 44.1kHz

impl PsolaShifter {
    /// Crée un nouveau moteur. Retourne le moteur et une référence partagée vers son ratio de
    /// hauteur cible — c'est ce handle, pas le moteur lui-même, qu'on passe au thread de
    /// détection de hauteur.
    pub fn new(sample_rate: f64, formant_preservation: bool) -> (Self, Arc<PitchTarget>) {
        // Les tailles de buffer (MAX_PERIOD, etc.) sont dimensionnées pour MAX_SAMPLE_RATE ;
        // une fréquence d'échantillonnage supérieure serait silencieusement sous-dimensionnée.
        let _sample_rate = sample_rate.min(MAX_SAMPLE_RATE);
        let pitch_target = Arc::new(PitchTarget::default());
        let shifter = Self {
            formant_enabled: formant_preservation,
            history: Box::new([0.0; HISTORY_CAPACITY]),
            residual_history: Box::new([0.0; HISTORY_CAPACITY]),
            out_buf: Box::new([0.0; OUT_CAPACITY]),
            write_pos: 0,
            out_write: 0,
            out_ready: 0,
            out_read: 0,
            next_analysis_mark: 0,
            have_analysis_mark: false,
            synth_accum: 0.0,
            tracker: PeriodTracker::default(),
            lpc: LpcFormant::default(),
            input_envelope: 0.0,
            smoothed_ratio: 1.0,
            pitch_target: pitch_target.clone(),
        };
        (shifter, pitch_target)
    }

    /// Consomme un bloc d'échantillons mono (`[-1, 1]`). À appeler depuis le thread chaud
    /// unique (audio IO Android / render iOS).
    pub fn process(&mut self, input: &[f32]) {
        for &sample in input {
            self.history[(self.write_pos as usize) & HISTORY_MASK] = sample;
            self.write_pos += 1;

            // Lissage à ~3ms du ratio cible — voir la doc du champ `smoothed_ratio`.
            let target_ratio = self.pitch_target.get();
            self.smoothed_ratio +=
                (target_ratio - self.smoothed_ratio) / RATIO_SMOOTHING_TIME_CONSTANT_SAMPLES;

            // Enveloppe de crête du signal d'entrée brut — attaque instantanée, relâchement
            // lent (~90ms @ 44.1kHz) — référence de confiance pour le clamp défensif du
            // résidu ci-dessous.
            let abs_sample = sample.abs();
            self.input_envelope = if abs_sample > self.input_envelope {
                abs_sample
            } else {
                0.9995 * self.input_envelope + 0.0005 * abs_sample
            };

            let raw_residual = if self.formant_enabled {
                self.lpc.whiten(sample)
            } else {
                sample
            };
            // Filet de sécurité : le résidu blanchi ne devrait jamais s'écarter démesurément
            // de l'amplitude du signal d'entrée réel — un filtre FIR est structurellement
            // stable (pas de rétroaction), mais borner ici avec une référence qui ne peut
            // elle-même jamais dériver (contrairement à une enveloppe suivie à l'intérieur
            // du pipeline LPC/PSOLA) empêche toute amplification pathologique en amont de la
            // chaîne OLA + recoloration, plutôt que de compter uniquement sur le clamp de
            // `LpcFormant::recolor` en aval (voir `docs/roadmap.md` — défense en profondeur).
            const MAX_RESIDUAL_GAIN: f32 = 8.0;
            let ceiling = self.input_envelope * MAX_RESIDUAL_GAIN + 1e-6;
            let residual = raw_residual.clamp(-ceiling, ceiling);
            self.residual_history[((self.write_pos - 1) as usize) & HISTORY_MASK] = residual;

            self.tracker.maybe_update(&*self.history, self.write_pos);
            if self.formant_enabled {
                self.lpc.accumulate(sample);
            }

            self.maybe_emit_grain(self.smoothed_ratio);
        }
    }

    /// Toujours prêt à consommer — PSOLA n'a pas de contrainte de bloc minimal comme
    /// Rubber Band. Conservé pour compatibilité avec le wrapper iOS existant, qui boucle
    /// tant que cette valeur est non nulle.
    pub fn samples_required(&self) -> usize {
        MAX_PERIOD * 2
    }

    pub fn available(&self) -> usize {
        (self.out_ready - self.out_read) as usize
    }

    /// Copie les échantillons disponibles dans `out`. Complète par du silence si moins de
    /// `out.len()` échantillons sont prêts (préférable à des artefacts de zero-padding brut,
    /// même précédent que le wrapper Rubber Band existant).
    pub fn retrieve(&mut self, out: &mut [f32]) {
        let avail = self.available();
        let n = out.len().min(avail);
        for (i, o) in out.iter_mut().enumerate().take(n) {
            *o = self.out_buf[((self.out_read + i as u64) as usize) & OUT_MASK];
        }
        self.out_read += n as u64;
        for o in out.iter_mut().skip(n) {
            *o = 0.0;
        }
    }

    /// Latence structurelle en échantillons — dominée par le lookahead de fenêtrage
    /// (~1.5× période max) + amorçage du tracker de période.
    pub fn latency(&self) -> usize {
        MAX_PERIOD + MAX_PERIOD / 2
    }

    pub fn reset(&mut self) {
        self.history.fill(0.0);
        self.residual_history.fill(0.0);
        self.out_buf.fill(0.0);
        self.write_pos = 0;
        self.out_write = 0;
        self.out_ready = 0;
        self.out_read = 0;
        self.next_analysis_mark = 0;
        self.have_analysis_mark = false;
        self.synth_accum = 0.0;
        self.tracker.reset();
        self.lpc.reset();
        self.input_envelope = 0.0;
        self.smoothed_ratio = 1.0;
        self.pitch_target.set(1.0);
    }

    // ── Interne ──────────────────────────────────────────────────────────────────────────

    /// Avance la comptabilité des marques d'analyse/synthèse et émet des grains tant que le
    /// budget de synthèse (piloté par `ratio`) l'autorise.
    ///
    /// Mécanisme : `synth_accum` compte les périodes d'analyse complétées mais pas encore
    /// "consommées" par une émission de synthèse. `ratio > 1` (hausse de pitch) consomme ce
    /// budget plus vite qu'il ne se remplit → réutilisation du grain le plus récent ;
    /// `ratio < 1` (baisse) le fait s'accumuler → les grains excédentaires sont implicitement
    /// sautés (on ne garde jamais qu'une position de grain, pas une file). Ce choix — sourcer
    /// toujours depuis le grain le plus récent plutôt qu'une file de grains — est une
    /// simplification volontaire pour rester temps-réel-safe (mémoire bornée, pas de file à
    /// gérer), documentée dans `docs/roadmap.md`.
    fn maybe_emit_grain(&mut self, ratio: f32) {
        let t0 = self.tracker.period();

        if !self.have_analysis_mark && self.write_pos >= (t0 as u64) * 2 {
            self.next_analysis_mark = self.write_pos - t0 as u64;
            self.have_analysis_mark = true;
        }
        if !self.have_analysis_mark {
            return;
        }

        while self.write_pos >= self.next_analysis_mark + t0 as u64 {
            self.next_analysis_mark += t0 as u64;
            self.synth_accum += 1.0;
        }

        let budget = 1.0 / ratio.max(0.01);
        let mut emitted = 0;
        while self.synth_accum >= budget && emitted < MAX_MARKS_PER_BLOCK {
            self.synth_accum -= budget;
            let mark = self.next_analysis_mark.saturating_sub(t0 as u64);
            self.emit_grain(mark, t0);
            emitted += 1;
        }
    }

    /// Émet un grain de largeur `2×half` (`half = t0`), centré sur `mark_pos`, fenêtré par
    /// Hann, accumulé par overlap-add dans le buffer de sortie circulaire (sur le résidu
    /// blanchi) ; la recoloration (si formants activés) est appliquée séparément, une fois
    /// la plage de sortie définitivement sommée — voir le commentaire dans le corps.
    fn emit_grain(&mut self, mark_pos: u64, t0: f32) {
        let half = t0 as usize;
        if half == 0 || half > MAX_PERIOD {
            return;
        }

        // Invariant maintenu par construction : out_write avance d'exactement `half` à
        // chaque appel (chevauchement 50%). La moitié [0, half) de la fenêtre de sortie
        // courante a déjà été accumulée par le grain précédent — on n'y touche pas. La
        // moitié [half, 2*half) est un territoire neuf du buffer circulaire, potentiellement
        // porteur de données obsolètes d'un tour précédent (si retrieve() a pris du retard) :
        // on la remet à zéro avant toute accumulation.
        for i in half..2 * half {
            self.out_buf[((self.out_write + i as u64) as usize) & OUT_MASK] = 0.0;
        }

        // OLA du résidu BLANCHI (pas recoloré ici) — voir la note plus bas sur pourquoi la
        // recoloration ne peut pas se faire pendant le parcours d'un grain.
        for i in 0..2 * half {
            let src_idx = mark_pos as i64 - half as i64 + i as i64;
            if src_idx < 0 || src_idx as u64 > self.write_pos {
                break; // grain pas encore entièrement disponible — tronqué
            }
            let src_idx = src_idx as u64;

            let window = 0.5 - 0.5 * (2.0 * PI * i as f32 / (2 * half - 1) as f32).cos();
            let residual = self.residual_history[(src_idx as usize) & HISTORY_MASK] * window;

            let out_idx = ((self.out_write + i as u64) as usize) & OUT_MASK;
            self.out_buf[out_idx] += residual;
        }

        self.out_write += half as u64;
        let new_out_ready = self.out_write - half as u64;

        // Recoloration : appliquée EXACTEMENT une fois par échantillon de sortie, dans
        // l'ordre chronologique de la timeline de SORTIE — jamais dans l'ordre de parcours
        // d'un grain. C'est un point de correction important par rapport à une première
        // version de ce moteur : le filtre IIR de recoloration est intrinsèquement
        // séquentiel (son état dépend de tout ce qu'il a vu avant), alors qu'un même
        // échantillon de résidu peut être visité PLUSIEURS FOIS et dans le désordre pendant
        // l'overlap-add PSOLA (réutilisation de grain en hausse de pitch, chevauchement à
        // 50% entre grains consécutifs) — recolorer pendant ce parcours corrompait l'état du
        // filtre et empêchait la préservation des formants de fonctionner (détecté par le
        // test `formant_preservation.rs`, qui mesurait un déplacement du pic spectral avec
        // le pitch — exactement l'effet que la couche LPC est censée éviter). En ne
        // recolorant qu'au moment où une plage de `out_buf` devient définitivement sommée
        // (`[out_ready, new_out_ready)`, qui n'est plus jamais retouchée après), chaque
        // échantillon de sortie passe dans le filtre IIR exactement une fois, dans l'ordre.
        if self.formant_enabled {
            // Référence de confiance dérivée de l'amplitude d'entrée BRUTE (jamais de
            // l'historique interne du pipeline LPC/PSOLA lui-même — voir la doc de
            // `LpcFormant::recolor` pour la boucle auto-référentielle que ça évite).
            const MAX_OUTPUT_GAIN: f32 = 10.0;
            let max_output = self.input_envelope * MAX_OUTPUT_GAIN + 1e-6;
            for idx in self.out_ready..new_out_ready {
                let out_idx = (idx as usize) & OUT_MASK;
                self.out_buf[out_idx] = self.lpc.recolor(self.out_buf[out_idx], max_output);
            }
        }
        self.out_ready = new_out_ready;
    }
}
