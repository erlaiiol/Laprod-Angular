import AVFoundation
import Capacitor

// ── Plugin principal ──────────────────────────────────────────────────────────
//
// Responsabilité unique : gestion du cycle de vie Capacitor (startSession /
// stopSession / permissions / checkHeadphones) et pont vers AudioSession.
//
// La logique DSP est dans ScaleBuilder.swift et YINDetector.swift.
// La logique AVAudioEngine est dans AudioSession (classe privée ci-dessous).

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

        // retuneSpeed → facteur de lissage exponentiel (Natural k=0.85, Precise k=0.5)
        let speedStr  = call.getString("retuneSpeed") ?? "natural"
        let smoothK: Float = speedStr == "precise" ? 0.5 : 0.85

        let opts = SessionOptions(
            useMonitor:     call.getBool("useMonitor")     ?? false,
            voiceGain:      call.getFloat("voiceGain")     ?? 1.0,
            reverbWet:      call.getFloat("reverbWet")     ?? 0.15,
            trackKey:       call.getString("trackKey")     ?? "",
            monitorAutotune: call.getBool("monitorAutotune") ?? false,
            smoothK:        smoothK
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
                let result    = active.stop()
                self.session  = nil
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
        case .authorized:            state = "granted"
        case .denied, .restricted:   state = "denied"
        default:                     state = "prompt"
        }
        call.resolve(["microphone": state])
    }

    @objc func requestPermission(_ call: CAPPluginCall) {
        AVCaptureDevice.requestAccess(for: .audio) { granted in
            call.resolve(["microphone": granted ? "granted" : "denied"])
        }
    }

    // ── checkHeadphones ───────────────────────────────────────────────────────
    // Détecte wired / bluetooth / none en inspectant les ports de sortie audio.

    @objc func checkHeadphones(_ call: CAPPluginCall) {
        let session  = AVAudioSession.sharedInstance()
        let outputs  = session.currentRoute.outputs
        var hpType   = "none"

        for port in outputs {
            switch port.portType {
            case .headphones, .headsetMic:
                hpType = "wired"
            case .bluetoothHFP, .bluetoothLE:
                // HFP/LE supporte le monitoring bidirectionnel (SCO)
                if hpType != "wired" { hpType = "bluetooth" }
            case .bluetoothA2DP:
                // A2DP = lecture seule, monitoring micro impossible
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
    let smoothK:         Float   // lissage exponentiel : 0.85=natural, 0.5=precise
}

// ── SessionResult ─────────────────────────────────────────────────────────────

struct SessionResult {
    let pcmBase64:  String
    let sampleRate: Int
}

// ── AudioSession ──────────────────────────────────────────────────────────────
//
// Encapsule AVAudioEngine + détection de hauteur YIN.
// Durée de vie strictement liée à une session start/stop.

final class AudioSession {

    // ── Callbacks ─────────────────────────────────────────────────────────────

    var onLevel:       ((Float) -> Void)?
    var onPitch:       ((Float, Float) -> Void)?
    var onInterrupted: (() -> Void)?

    // ── Internals ─────────────────────────────────────────────────────────────

    private let options:    SessionOptions
    private let scale:      [Float]
    private let engine:     AVAudioEngine
    private let pitchNode:  AVAudioUnitTimePitch
    private var detector:   YINDetector
    private var sampleRate: Double = 48_000

    // Buffers partagés entre le tap et le timer de détection
    private let lock     = NSLock()
    private var pcmData  = Data()
    private var pitchBuf = [Float]()

    // Lissage exponentiel de la correction monitoring (hors zone pour perf)
    private var smoothedCents: Float = 0

    // Caps : monitoring ±1.5 st, post-rec ±3 st (géré dans YINDetector)
    private let MONITOR_CAP_CENTS: Float = 150  // 1.5 semitones × 100 cents

    private var pitchTimer:       DispatchSourceTimer?
    private var interruptionToken: Any?          // NSObjectProtocol pour removeObserver
    private var routeChangeToken:  Any?          // débranchement casque (équivalent AUDIO_BECOMING_NOISY Android)

    // ── Init ──────────────────────────────────────────────────────────────────

    init(options: SessionOptions) throws {
        self.options   = options
        self.scale     = ScaleBuilder.frequencies(for: options.trackKey)
        self.engine    = AVAudioEngine()
        self.pitchNode = AVAudioUnitTimePitch()

        // Mode monitoring autotune : fenêtre 512 samples (10 ms @ 48kHz) pour latence minimale
        // Mode normal : fenêtre 2048 samples (42 ms) — meilleure précision post-enregistrement
        let frameSize = options.monitorAutotune ? 512 : 2048
        self.detector  = YINDetector(frameSize: frameSize)

        let avSession = AVAudioSession.sharedInstance()
        try avSession.setCategory(.playAndRecord,
                                  mode: .measurement,
                                  options: [.defaultToSpeaker, .allowBluetooth])
        try avSession.setPreferredIOBufferDuration(0.005)
        try avSession.setActive(true)
    }

    // ── Start ─────────────────────────────────────────────────────────────────

    func start() throws {
        let inputNode = engine.inputNode
        let fmt       = inputNode.outputFormat(forBus: 0)
        sampleRate    = fmt.sampleRate

        // Construire la chaîne de monitoring si nécessaire
        if options.useMonitor {
            let reverbNode = AVAudioUnitReverb()
            reverbNode.loadFactoryPreset(.plate)
            reverbNode.wetDryMix = options.reverbWet * 100

            let gainNode = AVAudioMixerNode()
            gainNode.outputVolume = options.voiceGain

            for node in [pitchNode, reverbNode, gainNode] as [AVAudioNode] {
                engine.attach(node)
            }
            engine.connect(inputNode,  to: gainNode,   format: fmt)
            engine.connect(gainNode,   to: reverbNode, format: fmt)
            engine.connect(reverbNode, to: pitchNode,  format: fmt)
            engine.connect(pitchNode,  to: engine.mainMixerNode, format: fmt)
        }

        // Tap : collecte PCM + RMS, accumulation pour la détection de hauteur
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buf, _ in
            self?.handleAudioBuffer(buf)
        }

        try engine.start()
        // Monitoring autotune : timer 30 ms (vs 100 ms) pour latence de correction réduite
        let intervalMs = options.monitorAutotune ? 30 : 100
        startPitchTimer(intervalMs: intervalMs)

        // Interruptions (appel entrant, Siri, autre app audio)
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

        // Débranchement du casque filaire (ou perte du device BT actif) — équivalent
        // de ACTION_AUDIO_BECOMING_NOISY côté Android. Sans ça, l'enregistrement iOS
        // continue silencieusement sur le micro/haut-parleur du téléphone sans prévenir
        // l'utilisateur ni l'app (contrairement à Android qui interrompt proprement).
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
        if let token = interruptionToken {
            NotificationCenter.default.removeObserver(token)
            interruptionToken = nil
        }
        if let token = routeChangeToken {
            NotificationCenter.default.removeObserver(token)
            routeChangeToken = nil
        }
        pitchTimer?.cancel()
        pitchTimer = nil

        engine.inputNode.removeTap(onBus: 0)
        engine.stop()

        let base64 = lock.withLock { pcmData }.base64EncodedString()
        return SessionResult(pcmBase64: base64, sampleRate: Int(sampleRate))
    }

    // ── Tap handler ───────────────────────────────────────────────────────────

    private func handleAudioBuffer(_ buf: AVAudioPCMBuffer) {
        guard let ch = buf.floatChannelData?[0] else { return }
        let count = Int(buf.frameLength)

        // Copie PCM brut pour l'enregistrement
        lock.withLock {
            pcmData.append(Data(bytes: ch, count: count * 4))
            pitchBuf.append(contentsOf: UnsafeBufferPointer(start: ch, count: count))
        }

        // Niveau RMS → UI (vDSP)
        var rms: Float = 0
        vDSP_measqv(ch, 1, &rms, vDSP_Length(count))
        onLevel?(sqrtf(rms))
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
            pitchBuf.removeAll(keepingCapacity: true)
            return f
        }
        guard frame.count == detector.frameSize else { return }

        guard let hz = detector.detect(frame: frame, sampleRate: Float(sampleRate)),
              let rawCorrection = detector.correctionSemitones(detected: hz, scale: scale)
        else { return }

        var correctionCents = rawCorrection * 100  // semitones → cents

        if options.monitorAutotune {
            // Lissage exponentiel : smoothed = k*prev + (1-k)*current
            let k = options.smoothK
            smoothedCents = k * smoothedCents + (1 - k) * correctionCents

            // Cap ±1.5 semitones sur le monitoring (correction trop importante = artefact)
            correctionCents = max(-MONITOR_CAP_CENTS, min(MONITOR_CAP_CENTS, smoothedCents))
        }

        // Correction directe sur pitchNode — uniquement si l'autotune monitoring est actif
        if options.monitorAutotune && abs(correctionCents) >= 5 {
            pitchNode.pitch = correctionCents
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
