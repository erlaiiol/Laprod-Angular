//! Petit outil de vérification manuelle : génère quelques WAV avant/après passage par
//! `PsolaShifter`, pour une écoute humaine avant intégration (voir `docs/roadmap.md`,
//! Phase 0). N'a aucune vocation à être livré dans l'app — outil de développement uniquement.

use psola_dsp::{cents_to_ratio, PsolaShifter};
use std::f32::consts::PI;
use std::fs::File;
use std::io::{self, Write};

const SAMPLE_RATE: u32 = 44_100;

fn write_wav_mono_f32_as_i16(path: &str, samples: &[f32]) -> io::Result<()> {
    let mut f = File::create(path)?;
    let data_bytes = samples.len() as u32 * 2;
    let byte_rate = SAMPLE_RATE * 2;

    f.write_all(b"RIFF")?;
    f.write_all(&(36 + data_bytes).to_le_bytes())?;
    f.write_all(b"WAVE")?;
    f.write_all(b"fmt ")?;
    f.write_all(&16u32.to_le_bytes())?;
    f.write_all(&1u16.to_le_bytes())?; // PCM
    f.write_all(&1u16.to_le_bytes())?; // mono
    f.write_all(&SAMPLE_RATE.to_le_bytes())?;
    f.write_all(&byte_rate.to_le_bytes())?;
    f.write_all(&2u16.to_le_bytes())?; // block align
    f.write_all(&16u16.to_le_bytes())?; // bits per sample
    f.write_all(b"data")?;
    f.write_all(&data_bytes.to_le_bytes())?;

    for &s in samples {
        let clamped = (s.clamp(-1.0, 1.0) * 32767.0) as i16;
        f.write_all(&clamped.to_le_bytes())?;
    }
    Ok(())
}

fn sine_wave(frequency: f32, count: usize, amplitude: f32) -> Vec<f32> {
    (0..count)
        .map(|i| amplitude * (2.0 * PI * frequency * i as f32 / SAMPLE_RATE as f32).sin())
        .collect()
}

fn main() -> io::Result<()> {
    let out_dir = std::env::args().nth(1).unwrap_or_else(|| ".".to_string());

    let f0 = 220.0; // La3
    let duration_s = 3.0;
    let count = (SAMPLE_RATE as f32 * duration_s) as usize;
    let input = sine_wave(f0, count, 0.5);
    write_wav_mono_f32_as_i16(&format!("{out_dir}/input_220hz.wav"), &input)?;

    for cents in [0.0, 150.0, -150.0, 250.0] {
        let (mut shifter, pitch) = PsolaShifter::new(SAMPLE_RATE as f64, true);
        pitch.set(cents_to_ratio(cents));

        let block_size = 512;
        let mut output = Vec::with_capacity(count);
        let mut buf = vec![0.0f32; block_size];
        let mut fed = 0;
        while fed < input.len() {
            let end = (fed + block_size).min(input.len());
            shifter.process(&input[fed..end]);
            shifter.retrieve(&mut buf);
            output.extend_from_slice(&buf);
            fed = end;
        }

        write_wav_mono_f32_as_i16(&format!("{out_dir}/output_{cents}cents.wav"), &output)?;
        println!("écrit {out_dir}/output_{cents}cents.wav");
    }

    Ok(())
}
