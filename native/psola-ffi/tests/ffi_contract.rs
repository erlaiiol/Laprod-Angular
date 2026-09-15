//! Tests de la frontière FFI elle-même — c'est ici, pas dans `psola-dsp`, que vit tout le
//! `unsafe` du workspace (voir `docs/roadmap.md`, "Discipline d'ingénierie"). Valide le
//! contrat C-ABI tel qu'un appelant Kotlin/ObjC++ l'utiliserait réellement : pointeurs bruts,
//! gestion du cycle de vie du handle, comportement sur entrées invalides (nul).

use psola_ffi::{
    psola_available, psola_create, psola_destroy, psola_get_latency, psola_process, psola_reset,
    psola_retrieve, psola_set_pitch_cents, psola_yin_detect, psola_yin_max_frame_size,
};

#[test]
fn create_destroy_round_trip_does_not_crash() {
    unsafe {
        let handle = psola_create(44_100.0, 1);
        assert!(!handle.is_null());
        psola_destroy(handle);
    }
}

#[test]
fn destroy_null_is_a_safe_no_op() {
    unsafe {
        psola_destroy(std::ptr::null_mut());
    }
}

#[test]
fn calls_on_null_handle_do_not_crash_and_return_sane_defaults() {
    unsafe {
        let null = std::ptr::null_mut();
        psola_set_pitch_cents(null, 100.0);
        assert_eq!(psola_available(null), 0);
        assert_eq!(psola_get_latency(null), 0);
        psola_reset(null);

        let mut buf = [1.0f32; 16]; // valeur sentinelle non nulle
        psola_retrieve(null, buf.as_mut_ptr(), buf.len());
        // Doit rester inchangé (no-op), pas planter ni écrire n'importe quoi.
        assert_eq!(buf, [1.0f32; 16]);

        let input = [0.0f32; 16];
        psola_process(null, input.as_ptr(), input.len());
    }
}

#[test]
fn full_pipeline_through_raw_pointers_produces_output() {
    unsafe {
        let handle = psola_create(44_100.0, 1);
        assert!(!handle.is_null());

        psola_set_pitch_cents(handle, 100.0);

        let latency = psola_get_latency(handle) as usize;
        assert!(latency > 0);

        // Sinus 440Hz — même signal que les tests d'intégration de psola-dsp.
        let total = latency + 512 * 4;
        let input: Vec<f32> = (0..total)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * 440.0 * i as f32 / 44_100.0).sin())
            .collect();

        let block_size = 512;
        let mut fed = 0;
        let mut out = vec![0.0f32; block_size];
        let mut ever_non_zero = false;
        while fed < input.len() {
            let end = (fed + block_size).min(input.len());
            let chunk = &input[fed..end];
            psola_process(handle, chunk.as_ptr(), chunk.len());
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
            if out.iter().any(|&s| s != 0.0) {
                ever_non_zero = true;
            }
            fed = end;
        }
        assert!(
            ever_non_zero,
            "le pipeline complet via pointeurs bruts doit produire du son"
        );

        psola_reset(handle);
        psola_destroy(handle);
    }
}

#[test]
fn yin_detect_through_raw_pointers_finds_a4() {
    unsafe {
        let sample_rate = 48_000.0f32;
        let n = 2048usize;
        let frame: Vec<f32> = (0..n)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * 440.0 * i as f32 / sample_rate).sin())
            .collect();

        let mut out_hz: f32 = -1.0;
        let found = psola_yin_detect(frame.as_ptr(), frame.len(), sample_rate, &mut out_hz);
        assert_eq!(found, 1);
        assert!((out_hz - 440.0).abs() < 5.0, "obtenu {out_hz}");
    }
}

#[test]
fn yin_detect_returns_zero_on_null_frame() {
    unsafe {
        let mut out_hz: f32 = -1.0;
        let found = psola_yin_detect(std::ptr::null(), 2048, 48_000.0, &mut out_hz);
        assert_eq!(found, 0);
        assert_eq!(
            out_hz, -1.0,
            "out_hz ne doit pas être touché quand frame est nul"
        );
    }
}

#[test]
fn yin_max_frame_size_matches_documented_bound() {
    assert_eq!(psola_yin_max_frame_size(), 4096);
}

// SAFETY (test uniquement) : un pointeur brut vers le handle opaque ne porte aucune donnée
// thread-local — `unsafe impl Send` reflète le contrat réel de la frontière FFI : plusieurs
// threads peuvent en détenir une copie tant qu'un seul à la fois appelle
// `psola_process`/`psola_retrieve`/`psola_reset` (voir la doc de `psola_set_pitch_cents`,
// seule fonction conçue pour être appelée concurremment depuis un autre thread).
struct SendPtr(*mut psola_ffi::PsolaHandle);
unsafe impl Send for SendPtr {}
impl SendPtr {
    // Un appel de méthode force la capture de `self` en entier par la closure (captures
    // disjointes de Rust 2021) — un accès direct à `.0` capturerait le champ brut
    // `*mut PsolaHandle` isolément, contournant silencieusement le `unsafe impl Send`
    // ci-dessus.
    fn get(&self) -> *mut psola_ffi::PsolaHandle {
        self.0
    }
}

#[test]
fn concurrent_pitch_updates_through_raw_pointer_do_not_crash() {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::thread;

    unsafe {
        let handle = psola_create(44_100.0, 1);
        assert!(!handle.is_null());

        let done = Arc::new(AtomicBool::new(false));
        let pitch_thread = {
            let done = done.clone();
            let h = SendPtr(handle);
            thread::spawn(move || {
                let mut i = 0;
                while !done.load(Ordering::Relaxed) {
                    psola_set_pitch_cents(h.get(), (i % 400) as f32 - 200.0);
                    i += 1;
                }
            })
        };

        let input = [0.1f32; 256];
        let mut out = [0.0f32; 256];
        for _ in 0..200 {
            psola_process(handle, input.as_ptr(), input.len());
            psola_retrieve(handle, out.as_mut_ptr(), out.len());
        }

        done.store(true, Ordering::Relaxed);
        pitch_thread.join().unwrap();
        psola_destroy(handle);
    }
}
