// jsdom n'implémente pas le Web Audio API (OfflineAudioContext, AudioBuffer...),
// utilisé par MobileAudioProcessorService pour décoder/mixer le PCM natif iOS/Android.
// node-web-audio-api fournit une implémentation Rust fidèle (via NAPI) — on l'injecte
// en global pour que ces tests s'exécutent contre un vrai moteur de rendu audio
// plutôt qu'un mock qui masquerait de vraies régressions (ex. le sample rate).
import * as WebAudio from 'node-web-audio-api';

(globalThis as any).OfflineAudioContext     = WebAudio.OfflineAudioContext;
(globalThis as any).AudioContext            = WebAudio.AudioContext;
(globalThis as any).AudioBuffer             = WebAudio.AudioBuffer;
(globalThis as any).AudioBufferSourceNode   = WebAudio.AudioBufferSourceNode;
(globalThis as any).GainNode                = WebAudio.GainNode;
(globalThis as any).BiquadFilterNode        = WebAudio.BiquadFilterNode;
(globalThis as any).ConvolverNode           = WebAudio.ConvolverNode;
(globalThis as any).DynamicsCompressorNode  = WebAudio.DynamicsCompressorNode;
(globalThis as any).WaveShaperNode          = WebAudio.WaveShaperNode;
