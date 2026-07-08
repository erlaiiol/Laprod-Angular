import Accelerate
import AVFoundation
import Capacitor

// ── Plugin principal ──────────────────────────────────────────────────────────
//
// Responsabilité unique : gestion du cycle de vie Capacitor (startSession /
// stopSession / permissions / checkHeadphones) et pont vers AudioSession.
//
// La logique DSP est dans ScaleBuilder.swift, YINDetector.swift et
// RubberBandWrapper (ObjC++ — bridging header requis).

@objc(PitchMonitorPlugin)
public class PitchMonitorPlugin: CAPPlugin, CAPBridgedPlugin {

    public let identifier    = "PitchMonitorPlugin"
    public let jsName        = "PitchMonitor"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "startSession",      returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopSession",       returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "checkPermission",   returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestPermission", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "checkHeadphones",   returnType: CAPPluginReturnPromise),
    ]

    private var session: AudioSession?

    // ── startSession ──────────────────────────────────────────────────────────

    @objc func startSession(_ call: CAPPluginCall) {
        guard session == nil else {
            call.reject("Session already active. Call stopSession first.")
            return
        }

        let speedStr  = call.getString("retuneSpeed") ?? "natural"
        let smoothK: Float = speedStr == "robot" ? 0.0 : speedStr == "precise" ? 0.55 : 0.82

        let opts = SessionOptions(
            useMonitor:      call.getBool("useMonitor")      ?? false,
            voiceGain:       call.getFloat("voiceGain")      ?? 1.0,
            reverbWet:       call.getFloat("reverbWet")      ?? 0.15,
            trackKey:        call.getString("trackKey")      ?? "",
            monitorAutotune: call.getBool("monitorAutotune") ?? false,
            smoothK:         smoothK
        )

        do {
            let sess = try AudioSession(options: opts)
            sess.onLevel = { [weak self] rms in
                self?.notifyListeners("level", data: ["rms": rms])
            }
            sess.onPitch = { [weak self] hz, correction in
                self?.notifyListeners("pitch", data: ["hz": hz, "correction": correction])
            }
            sess.onInterrupted = { [weak self] in
                guard let self, let active = self.session else { return }
                let result   = active.stop()
                self.session = nil
                self.notifyListeners("sessionInterrupted", data: [
                    "pcmBase64":  result.pcmBase64,
                    "sampleRate": result.sampleRate,
                    "channels":   1,
                    "format":     "float32",
                    "partial":    true,
                ])
            }
            try sess.start()
            session = sess
            call.resolve()
        } catch {
            call.reject("startSession failed: \(error.localizedDescription)")
        }
    }

    // ── stopSession ───────────────────────────────────────────────────────────

    @objc func stopSession(_ call: CAPPluginCall) {
        guard let sess = session else {
            call.reject("No active session.")
            return
        }
        let result = sess.stop()
        session = nil
        call.resolve([
            "pcmBase64":  result.pcmBase64,
            "sampleRate": result.sampleRate,
            "channels":   1,
            "format":     "float32",
        ])
    }

    // ── Permissions ───────────────────────────────────────────────────────────

    @objc func checkPermission(_ call: CAPPluginCall) {
        let state: String
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:           state = "granted"
        case .denied, .restricted:  state = "denied"
        default:                    state = "prompt"
        }
        call.resolve(["microphone": state])
    }

    @objc func requestPermission(_ call: CAPPluginCall) {
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            call.resolve(["microphone": granted ? "granted" : "denied"])
        }
    }

    // ── checkHeadphones ───────────────────────────────────────────────────────

    @objc func checkHeadphones(_ call: CAPPluginCall) {
        let avSession = AVAudioSession.sharedInstance()
        var hpType    = "none"

        for port in avSession.currentRoute.outputs {
            switch port.portType {
            case .headphones, .headsetMic:
                hpType = "wired"
            case .bluetoothHFP, .bluetoothLE:
                if hpType != "wired" { hpType = "bluetooth" }
            case .bluetoothA2DP:
                if hpType != "wired" && hpType != "bluetooth" { hpType = "bluetooth-a2dp" }
            default:
                break
            }
        }
        call.resolve(["type": hpType])
    }
}

// ── SessionOptions ────────────────────────────────────────────────────────────

struct SessionOptions {
    let useMonitor:      Bool
    let voiceGain:       Float
    let reverbWet:       Float
    let trackKey:        String
    let monitorAutotune: Bool
    let smoothK:         Float   // 0.0=robot  0.55=precise  0.82=natural
}

// ── SessionResult ─────────────────────────────────────────────────────────────

struct SessionResult {
    let pcmBase64:  String
    let sampleRate: Int
}

// ── AudioSession ──────────────────────────────────────────────────────────────
//
// Encapsule AVAudioEngine + détection de hauteur YIN + pitch shift Rubber Band.
//
// Architecture monitoring avec RubberBand :
//
//   [inputNode] ──tap──► ring buffer (via RubberBandWrapper.feedInput)
//                  │
//                  └──► pitchBuf (YIN detection)
//                  └──► pcmData  (PCM recording brut)
//
//   [AVAudioSourceNode] ──pull depuis RubberBand──► gainNode ──► reverbNode ──► output
//
// Le chemin de monitoring est entièrement piloté par l'AVAudioSourceNode :
// son render block lit le ring buffer, passe par RubberBand (formant preservé)
// et écrit dans le graph. L'inputNode ne se connecte à rien dans le graph.

final class AudioSession {

    var onLevel:       ((Float) -> Void)?
    var onPitch:       ((Float, Float) -> Void)?
    var onInterrupted: (() -> Void)?

    private let options:    SessionOptions
    private let scale:      [Float]
    private let engine:     AVAudioEngine
    private var detector:   YINDetector
    private var sampleRate: Double = 48_000

    // Monitoring — nil when !useMonitor
    private var rbWrapper:  RubberBandWrapper?
    private var sourceNode: AVAudioSourceNode?

    // Shared between tap and detection timer
    private let lock     = NSLock()
    private var pcmData  = Data()
    private var pitchBuf = [Float]()

    // Smoothed pitch correction for monitoring
    private var smoothedCents:    Float = 0
    private var lastAppliedCents: Float = 0
    private let MONITOR_CAP_CENTS: Float = 250   // ±2.5 semitones

    private var pitchTimer:        DispatchSourceTimer?
    private var interruptionToken: Any?
    private var routeChangeToken:  Any?

    // ── Init ──────────────────────────────────────────────────────────────────

    init(options: SessionOptions) throws {
        self.options  = options
        self.scale    = ScaleBuilder.frequencies(for: options.trackKey)
        self.engine   = AVAudioEngine()
        // frameSize=2048: tauMax @ 48 kHz for 80 Hz = 600 < half=1024 → detects male voices
        self.detector = YINDetector(frameSize: 2048)

        let avSession = AVAudioSession.sharedInstance()
        try avSession.setCategory(.playAndRecord,
                                  mode: .measurement,
                                  options: [.defaultToSpeaker, .allowBluetooth])
        let ioDuration = options.monitorAutotune ? 0.003 : 0.005
        try avSession.setPreferredIOBufferDuration(ioDuration)
        try avSession.setActive(true)
    }

    // ── Start ─────────────────────────────────────────────────────────────────

    func start() throws {
        let inputNode = engine.inputNode
        let fmt       = inputNode.outputFormat(forBus: 0)
        sampleRate    = fmt.sampleRate

        if options.useMonitor {
            // RubberBand wrapper: real-time, formant-preserving, mono
            let rb        = RubberBandWrapper(sampleRate: sampleRate)
            rbWrapper     = rb

            let reverbNode  = AVAudioUnitReverb()
            reverbNode.loadFactoryPreset(.plate)
            reverbNode.wetDryMix = options.reverbWet * 100

            let gainNode = AVAudioMixerNode()
            gainNode.outputVolume = options.voiceGain

            // AVAudioSourceNode: pulls pitch-shifted audio from RubberBand.
            // Runs on the audio render thread — all operations must be RT-safe.
            // RubberBandWrapper.renderInto uses pre-allocated buffers and a
            // lock-free ring buffer; no heap allocation or locking in the hot path.
            let monoFmt = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                        sampleRate: sampleRate,
                                        channels: 1,
                                        interleaved: false)!
            let src = AVAudioSourceNode(format: monoFmt) { [weak rb] (silence, _, frameCount, outputData) in
                guard let rb else { return noErr }
                let abl = UnsafeMutableAudioBufferListPointer(outputData)
                if let ptr = abl[0].mData?.assumingMemoryBound(to: Float.self) {
                    rb.renderInto(ptr, frameCount: Int(frameCount))
                }
                silence.pointee = false
                return noErr
            }
            sourceNode = src

            for node in [src, gainNode, reverbNode] as [AVAudioNode] { engine.attach(node) }
            engine.connect(src,        to: gainNode,           format: monoFmt)
            engine.connect(gainNode,   to: reverbNode,         format: monoFmt)
            engine.connect(reverbNode, to: engine.mainMixerNode, format: monoFmt)
        }

        // Tap: PCM recording + RMS level + pitch-detection accumulation + RubberBand feed
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buf, _ in
            self?.handleAudioBuffer(buf)
        }

        try engine.start()

        let intervalMs = options.monitorAutotune ? 10 : 100
        startPitchTimer(intervalMs: intervalMs)

        // Interruption : appel entrant, Siri, autre app audio
        interruptionToken = NotificationCenter.default.addObserver(
            forName:  AVAudioSession.interruptionNotification,
            object:   AVAudioSession.sharedInstance(),
            queue:    .main
        ) { [weak self] n in
            guard
                let type = n.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                AVAudioSession.InterruptionType(rawValue: type) == .began
            else { return }
            self?.onInterrupted?()
        }

        // Débranchement du casque — sans ce handler, l'enregistrement iOS
        // bascule silencieusement sur le micro interne sans prévenir l'app.
        routeChangeToken = NotificationCenter.default.addObserver(
            forName:  AVAudioSession.routeChangeNotification,
            object:   AVAudioSession.sharedInstance(),
            queue:    .main
        ) { [weak self] n in
            guard
                let reasonValue = n.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                AVAudioSession.RouteChangeReason(rawValue: reasonValue) == .oldDeviceUnavailable
            else { return }
            self?.onInterrupted?()
        }
    }

    // ── Stop ──────────────────────────────────────────────────────────────────

    func stop() -> SessionResult {
        if let token = interruptionToken { NotificationCenter.default.removeObserver(token) }
        if let token = routeChangeToken  { NotificationCenter.default.removeObserver(token) }
        interruptionToken = nil
        routeChangeToken  = nil

        pitchTimer?.cancel()
        pitchTimer = nil

        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        rbWrapper?.reset()
        rbWrapper  = nil
        sourceNode = nil

        let base64 = lock.withLock { pcmData }.base64EncodedString()
        return SessionResult(pcmBase64: base64, sampleRate: Int(sampleRate))
    }

    // ── Tap handler ───────────────────────────────────────────────────────────

    private func handleAudioBuffer(_ buf: AVAudioPCMBuffer) {
        guard let ch = buf.floatChannelData?[0] else { return }
        let count = Int(buf.frameLength)

        lock.withLock {
            pcmData.append(Data(bytes: ch, count: count * 4))
            pitchBuf.append(contentsOf: UnsafeBufferPointer(start: ch, count: count))
        }

        var rms: Float = 0
        vDSP_measqv(ch, 1, &rms, vDSP_Length(count))
        onLevel?(sqrtf(rms))

        // Feed the raw mic audio to RubberBand (monitoring path).
        // Called on the tap IO thread; RubberBandWrapper.feedInput is SPSC-safe.
        rbWrapper?.feedInput(ch, count: count)
    }

    // ── Timer de détection de hauteur ─────────────────────────────────────────

    private func startPitchTimer(intervalMs: Int) {
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .userInteractive))
        timer.schedule(deadline: .now() + .milliseconds(intervalMs),
                       repeating: .milliseconds(intervalMs),
                       leeway: .milliseconds(2))
        timer.setEventHandler { [weak self] in self?.runPitchDetection() }
        timer.resume()
        pitchTimer = timer
    }

    private func runPitchDetection() {
        let frame: [Float] = lock.withLock {
            guard pitchBuf.count >= detector.frameSize else { return [] }
            let f = Array(pitchBuf.suffix(detector.frameSize))
            // Sliding window: keep the last frameSize samples.
            // Without this, the 10 ms timer fires before 2048 samples accumulate
            // (42 ms @ 48 kHz) and detection never runs.
            if pitchBuf.count > detector.frameSize {
                pitchBuf.removeFirst(pitchBuf.count - detector.frameSize)
            }
            return f
        }
        guard frame.count == detector.frameSize else { return }

        guard let hz           = detector.detect(frame: frame, sampleRate: Float(sampleRate)),
              let rawCorrection = detector.correctionSemitones(detected: hz, scale: scale)
        else { return }

        var correctionCents = rawCorrection * 100

        if options.monitorAutotune {
            smoothedCents = options.smoothK * smoothedCents + (1 - options.smoothK) * correctionCents
            correctionCents = max(-MONITOR_CAP_CENTS, min(MONITOR_CAP_CENTS, smoothedCents))
        }

        // Deadband: robot (smoothK=0) → 1 cent snap; other modes → 3 cents to
        // avoid micro-tremulations when the voice is already on pitch.
        let deadband: Float = options.smoothK == 0 ? 1.0 : 3.0

        if options.monitorAutotune && abs(correctionCents) >= deadband {
            if abs(correctionCents - lastAppliedCents) >= 1 {
                // RubberBandWrapper applies the scale in its next render block.
                // Thread-safe: uses std::atomic internally.
                rbWrapper?.setPitchCents(correctionCents)
                lastAppliedCents = correctionCents
            }
        } else if options.monitorAutotune && lastAppliedCents != 0 {
            rbWrapper?.setPitchCents(0)
            lastAppliedCents = 0
        }
        onPitch?(hz, correctionCents / 100)
    }
}

// ── NSLock convenience ────────────────────────────────────────────────────────

private extension NSLock {
    @discardableResult
    func withLock<T>(_ body: () -> T) -> T {
        lock(); defer { unlock() }
        return body()
    }
}
