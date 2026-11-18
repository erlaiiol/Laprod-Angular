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
        CAPPluginMethod(name: "setBeatVolume",     returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setVoiceFx",        returnType: CAPPluginReturnPromise),
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
            reverbWet:       call.getFloat("reverbWet")      ?? 0,
            trackKey:        call.getString("trackKey")      ?? "",
            monitorAutotune: call.getBool("monitorAutotune") ?? false,
            smoothK:         smoothK,
            beatPath:        call.getString("beatPath"),
            beatStartSec:    call.getDouble("beatStartSec") ?? 0,
            beatVolume:      call.getFloat("beatVolume")   ?? 0.65,
            startDelayMs:    call.getDouble("startDelayMs") ?? 0,
            loopBeat:        call.getBool("loopBeat")      ?? false,
            record:          call.getBool("record")        ?? true,
            fx:              VoiceFx(from: call.getObject("fx").map { $0 as [String: Any] })
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
                var data: [String: Any] = [
                    "pcmBase64":  result.pcmBase64,
                    "sampleRate": result.sampleRate,
                    "channels":   1,
                    "format":     "float32",
                    "partial":    true,
                ]
                if let pos = result.firstSampleBeatSec { data["firstSampleBeatSec"] = pos }
                self.notifyListeners("sessionInterrupted", data: data)
            }
            let info = try sess.start()
            session = sess
            var payload: [String: Any] = [
                "nativeBeat":      info.nativeBeat,
                "startInMs":       info.startInMs,
                "outputLatencyMs": info.outputLatencyMs,
                "inputLatencyMs":  info.inputLatencyMs,
            ]
            if let host = info.beatStartHostSec { payload["beatStartHostSec"] = host }
            call.resolve(payload)
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
        var payload: [String: Any] = [
            "pcmBase64":  result.pcmBase64,
            "sampleRate": result.sampleRate,
            "channels":   1,
            "format":     "float32",
        ]
        if let pos = result.firstSampleBeatSec { payload["firstSampleBeatSec"] = pos }
        call.resolve(payload)
    }

    // ── setBeatVolume ─────────────────────────────────────────────────────────

    @objc func setBeatVolume(_ call: CAPPluginCall) {
        session?.setBeatVolume(call.getFloat("volume") ?? 0.65)
        call.resolve()
    }

    // ── setVoiceFx ────────────────────────────────────────────────────────────
    // Réglages de la piste (boue, présence, clarté, réverb, volume) appliqués au
    // retour casque en temps réel : le changement s'entend immédiatement.

    @objc func setVoiceFx(_ call: CAPPluginCall) {
        session?.applyFx(VoiceFx(from: call.options as? [String: Any]))
        call.resolve()
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
    // Beat joué nativement (même AVAudioEngine que le micro → même horloge).
    let beatPath:        String? // chemin ou URI file:// du beat (nil = pas de beat natif)
    let beatStartSec:    Double  // position du beat à laquelle démarrer la lecture
    let beatVolume:      Float
    let startDelayMs:    Double  // délai avant le départ du beat (décompte 3-2-1 silencieux)
    let loopBeat:        Bool    // échauffement : le beat boucle
    let record:          Bool    // false = retour casque seul, rien n'est stocké
    let fx:              VoiceFx
}

// ── VoiceFx ───────────────────────────────────────────────────────────────────
// Miroir simplifié de la chaîne d'export (mobile-audio-processor.service.ts).

struct VoiceFx {
    var lowCutHz:   Float = 150
    var presenceDb: Float = 3.5
    var clarityDb:  Float = 3.0
    var reverbWet:  Float = 0      // retour casque toujours sec (cf. monitorFx côté front)
    var volume:     Float = 1.0

    init() {}

    init(from obj: [String: Any]?) {
        guard let obj else { return }
        func num(_ k: String) -> Float? {
            if let d = obj[k] as? Double { return Float(d) }
            if let i = obj[k] as? Int    { return Float(i) }
            if let n = obj[k] as? NSNumber { return n.floatValue }
            return nil
        }
        lowCutHz   = num("lowCutHz")   ?? lowCutHz
        presenceDb = num("presenceDb") ?? presenceDb
        clarityDb  = num("clarityDb")  ?? clarityDb
        reverbWet  = num("reverbWet")  ?? reverbWet
        volume     = num("volume")     ?? volume
    }
}

struct StartInfo {
    let nativeBeat:      Bool
    let startInMs:       Double
    let outputLatencyMs: Double
    let inputLatencyMs:  Double
    /// Heure machine (s) du départ programmé du beat natif — ancre du Mode Clip.
    let beatStartHostSec: Double?
}

// ── SessionResult ─────────────────────────────────────────────────────────────

struct SessionResult {
    let pcmBase64:  String
    let sampleRate: Int
    /// Position du beat (s, horloge de rendu, latences NON compensées) qui
    /// correspond au 1er échantillon micro conservé. nil sans beat natif.
    let firstSampleBeatSec: Double?
}

// ── AudioSession ──────────────────────────────────────────────────────────────
//
// Encapsule AVAudioEngine + détection de hauteur YIN + pitch shift Rubber Band.
//
// Architecture monitoring avec RubberBand :
//
//   [inputNode] ──► AVAudioSinkNode (thread temps réel, à chaque cycle matériel)
//        │              └──► ring buffer + historique (RubberBandWrapper.feedInput)
//        │
//        └──tap (~100 ms par paquet, hors temps réel)──► pcmData (enregistrement brut)
//                                                    └──► niveau, pitchBuf sans monitoring
//
//   Le retour casque n'est JAMAIS alimenté par le tap : ses paquets de ~100 ms étaient
//   traités d'un bloc dans un seul cycle de rendu (pic de calcul → craquements) et
//   retardaient la détection de hauteur d'autant.
//
//   [AVAudioSourceNode] ──pull depuis RubberBand──► eq ──► gainNode ──► output
//
//   AUCUNE réverb dans le retour casque (18/11/2026) : l'AVAudioUnitReverb tournait sur le
//   thread temps réel à chaque cycle (charge → craquements possibles) même à 0 % de wet.
//   La réverb n'existe qu'au rendu final (export / Mode Clip, côté WebAudio).
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
    private var sinkNode:   AVAudioSinkNode?
    /// Trame d'analyse réutilisée par la détection (pas d'allocation toutes les 10 ms).
    private var analysisFrame = [Float]()
    private var eqNode:     AVAudioUnitEQ?
    private var gainNode:   AVAudioMixerNode?

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

    // Beat natif — nil sans beatPath
    private var beatPlayer: AVAudioPlayerNode?
    private var beatFile:   AVAudioFile?
    /// Heure machine à laquelle le beat démarre ; les échantillons micro
    /// antérieurs (décompte) sont écartés de l'enregistrement.
    private var beatStartHost: UInt64 = 0
    /// Heure machine du 1er échantillon micro conservé (0 = pas encore).
    private var firstKeptHost: UInt64 = 0
    /// Figé avant engine.start() — lu par le tap sans verrou.
    private var hasNativeBeat = false

    // ── Init ──────────────────────────────────────────────────────────────────

    init(options: SessionOptions) throws {
        self.options  = options
        self.scale    = ScaleBuilder.frequencies(for: options.trackKey)
        self.engine   = AVAudioEngine()
        // frameSize=2048: tauMax @ 48 kHz for 80 Hz = 600 < half=1024 → detects male voices
        self.detector = YINDetector(frameSize: 2048)

        let avSession = AVAudioSession.sharedInstance()
        // - allowBluetoothA2DP (et PAS allowBluetoothHFP) : un casque Bluetooth reste
        //   en A2DP haute qualité pour le beat ; le micro est celui de l'iPhone. Avec
        //   HFP, iOS basculait le casque en profil "appel" (son 16 kHz mono) et la
        //   bascule de route coupait la lecture du beat au début de l'enregistrement.
        // - mixWithOthers : l'activation de la session ne coupe plus l'audio de la
        //   WebView (métronome WebAudio, beat d'aperçu).
        try avSession.setCategory(.playAndRecord,
                                  mode: .measurement,
                                  options: [.defaultToSpeaker, .allowBluetoothA2DP, .mixWithOthers])
        // Tampon matériel : très court en filaire (latence du retour voix), mais plus large
        // en Bluetooth — la liaison ajoute déjà ~150 ms, un tampon de 3 ms n'y gagne rien
        // et fait rater des échéances au thread audio (craquements avec des AirPods).
        let btPorts: Set<AVAudioSession.Port> = [.bluetoothA2DP, .bluetoothLE, .bluetoothHFP]
        let onBluetooth = avSession.currentRoute.outputs.contains { btPorts.contains($0.portType) }
        let ioDuration: TimeInterval = onBluetooth ? 0.010 : (options.monitorAutotune ? 0.003 : 0.005)
        try avSession.setPreferredIOBufferDuration(ioDuration)
        try avSession.setActive(true)
    }

    // ── Start ─────────────────────────────────────────────────────────────────

    func start() throws -> StartInfo {
        let inputNode = engine.inputNode
        let fmt       = inputNode.outputFormat(forBus: 0)
        sampleRate    = fmt.sampleRate

        // ── Beat natif ──────────────────────────────────────────────────────
        // Joué par le même moteur que la capture micro : il ne peut plus être
        // interrompu par la session audio de la WebView, et son horloge est
        // celle des timestamps du tap → alignement voix/beat à l'échantillon.
        if let path = options.beatPath, !path.isEmpty {
            let url  = path.hasPrefix("file://") ? (URL(string: path) ?? URL(fileURLWithPath: path))
                                                 : URL(fileURLWithPath: path)
            let file = try AVAudioFile(forReading: url)
            let node = AVAudioPlayerNode()
            engine.attach(node)
            engine.connect(node, to: engine.mainMixerNode, format: file.processingFormat)
            node.volume = options.beatVolume
            beatFile      = file
            beatPlayer    = node
            hasNativeBeat = true
            scheduleBeat(from: options.beatStartSec)
        }

        if options.useMonitor {
            // RubberBand wrapper: real-time, formant-preserving, mono
            let rb        = RubberBandWrapper(sampleRate: sampleRate)
            rbWrapper     = rb

            let gainNode = AVAudioMixerNode()

            // EQ voix : 2 passe-haut cascadés (24 dB/oct, comme l'export) = "boue",
            // bosse de présence 2,5 kHz, plateau d'air 12 kHz = "clarté".
            let eq = AVAudioUnitEQ(numberOfBands: 4)
            eq.bands[0].filterType = .highPass
            eq.bands[1].filterType = .highPass
            eq.bands[2].filterType = .parametric
            eq.bands[2].frequency  = 2_500
            eq.bands[2].bandwidth  = 1.39          // ≈ Q 1.0, comme l'export
            eq.bands[3].filterType = .highShelf
            eq.bands[3].frequency  = 12_000
            for band in eq.bands { band.bypass = false }

            self.eqNode     = eq
            self.gainNode   = gainNode
            applyFx(options.fx)

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
                    rb.render(into: ptr, frameCount: Int(frameCount))
                }
                silence.pointee = false
                return noErr
            }
            sourceNode = src

            for node in [src, eq, gainNode] as [AVAudioNode] { engine.attach(node) }
            engine.connect(src,      to: eq,                   format: monoFmt)
            engine.connect(eq,       to: gainNode,             format: monoFmt)
            engine.connect(gainNode, to: engine.mainMixerNode, format: monoFmt)

            // Micro → moteur de hauteur, sur le thread temps réel et à chaque cycle
            // matériel : charge constante par cycle, latence minimale. Aucun verrou,
            // aucune allocation dans ce bloc.
            let sink = AVAudioSinkNode { [weak rb] (_, frameCount, audioBufferList) -> OSStatus in
                guard let rb else { return noErr }
                let abl = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: audioBufferList))
                if abl.count > 0, let ptr = abl[0].mData?.assumingMemoryBound(to: Float.self) {
                    rb.feedInput(ptr, count: Int(frameCount))
                }
                return noErr
            }
            sinkNode = sink
            engine.attach(sink)
            engine.connect(inputNode, to: sink, format: fmt)
            analysisFrame = [Float](repeating: 0, count: detector.frameSize)
        }

        // Tap: PCM recording + RMS level (+ pitch-detection accumulation sans monitoring)
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: fmt) { [weak self] buf, when in
            self?.handleAudioBuffer(buf, when: when)
        }

        try engine.start()

        let startDelaySec = max(0.12, options.startDelayMs / 1000)
        if let node = beatPlayer {
            // Départ programmé à une heure machine précise (≥ 120 ms pour laisser
            // le moteur démarrer) — c'est la référence de l'alignement. Tant
            // qu'elle n'est pas posée, le tap n'enregistre rien (cf. handleAudioBuffer).
            let host = mach_absolute_time() + AVAudioTime.hostTime(forSeconds: startDelaySec)
            lock.withLock { beatStartHost = host }
            node.play(at: AVAudioTime(hostTime: host))
        }

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

        let avSession = AVAudioSession.sharedInstance()
        return StartInfo(
            nativeBeat:      beatPlayer != nil,
            startInMs:       beatPlayer != nil ? startDelaySec * 1000 : 0,
            outputLatencyMs: avSession.outputLatency * 1000,
            inputLatencyMs:  avSession.inputLatency  * 1000,
            beatStartHostSec: beatPlayer != nil
                ? AVAudioTime.seconds(forHostTime: lock.withLock { beatStartHost })
                : nil
        )
    }

    // ── Beat ──────────────────────────────────────────────────────────────────

    private func scheduleBeat(from startSec: Double) {
        guard let node = beatPlayer, let file = beatFile else { return }
        let sr         = file.processingFormat.sampleRate
        let startFrame = AVAudioFramePosition(max(0, startSec) * sr)
        if startFrame < file.length {
            node.scheduleSegment(file,
                                 startingFrame: startFrame,
                                 frameCount: AVAudioFrameCount(file.length - startFrame),
                                 at: nil)
        }
        if options.loopBeat { scheduleLoop() }
    }

    /// Échauffement : ré-enfile le fichier complet à chaque fin de lecture
    /// (toujours une passe d'avance pour éviter tout trou à la jointure).
    private func scheduleLoop() {
        guard let node = beatPlayer, let file = beatFile else { return }
        node.scheduleFile(file, at: nil) { [weak self] in
            guard let self, self.beatPlayer != nil else { return }
            self.scheduleLoop()
        }
    }

    func setBeatVolume(_ v: Float) {
        beatPlayer?.volume = max(0, min(1, v))
    }

    /// Paramètres AU modifiables depuis n'importe quel thread : effet au bloc suivant.
    func applyFx(_ fx: VoiceFx) {
        guard let eq = eqNode else { return }
        let lowCut = max(20, min(400, fx.lowCutHz))
        eq.bands[0].frequency = lowCut
        eq.bands[1].frequency = lowCut
        eq.bands[2].gain      = max(-12, min(12, fx.presenceDb))
        eq.bands[3].gain      = max(-12, min(12, fx.clarityDb))
        gainNode?.outputVolume = options.voiceGain * max(0, min(2, fx.volume))
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
        let player = beatPlayer
        beatPlayer = nil          // avant stop() : coupe la boucle de scheduleLoop
        player?.stop()
        engine.stop()
        beatFile   = nil
        rbWrapper?.reset()
        rbWrapper  = nil
        sourceNode = nil
        sinkNode   = nil
        eqNode     = nil
        gainNode   = nil

        // Rend la main : le casque Bluetooth et la WebView retrouvent leur
        // configuration de lecture normale.
        let avSession = AVAudioSession.sharedInstance()
        try? avSession.setActive(false, options: .notifyOthersOnDeactivation)
        try? avSession.setCategory(.playback, mode: .default, options: [])

        let (data, firstHost, startHost) = lock.withLock { (pcmData, firstKeptHost, beatStartHost) }
        var firstBeatSec: Double? = nil
        if player != nil && startHost > 0 && firstHost >= startHost {
            firstBeatSec = options.beatStartSec
                + AVAudioTime.seconds(forHostTime: firstHost - startHost)
        }
        return SessionResult(pcmBase64: data.base64EncodedString(),
                             sampleRate: Int(sampleRate),
                             firstSampleBeatSec: firstBeatSec)
    }

    // ── Tap handler ───────────────────────────────────────────────────────────

    private func handleAudioBuffer(_ buf: AVAudioPCMBuffer, when: AVAudioTime) {
        guard let ch = buf.floatChannelData?[0] else { return }
        let count = Int(buf.frameLength)

        // Avec beat natif, on n'enregistre qu'à partir du départ du beat : les
        // échantillons du décompte sont écartés (le niveau/monitoring restent actifs).
        var skip = 0
        if hasNativeBeat {
            let startHost = lock.withLock { beatStartHost }
            if startHost == 0 || !when.isHostTimeValid {
                skip = count   // départ pas encore programmé : rien à garder
            } else if when.hostTime < startHost {
                let early = AVAudioTime.seconds(forHostTime: startHost - when.hostTime)
                skip = min(count, Int((early * sampleRate).rounded(.up)))
            }
            if skip < count {
                let host = when.hostTime + AVAudioTime.hostTime(forSeconds: Double(skip) / sampleRate)
                lock.withLock { if firstKeptHost == 0 { firstKeptHost = host } }
            }
        }

        lock.withLock {
            if options.record && skip < count {
                pcmData.append(Data(bytes: ch.advanced(by: skip), count: (count - skip) * 4))
            }
            // Avec monitoring, la détection lit l'historique temps réel du wrapper.
            if rbWrapper == nil {
                pitchBuf.append(contentsOf: UnsafeBufferPointer(start: ch, count: count))
            }
        }

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
        // Monitoring : fenêtre la plus récente, lue sans verrou dans l'historique alimenté
        // à chaque cycle matériel — la correction suit la voix au lieu d'avoir ~100 ms de retard.
        if let rb = rbWrapper {
            let ok = analysisFrame.withUnsafeMutableBufferPointer { buf -> Bool in
                guard let base = buf.baseAddress else { return false }
                return rb.copyLatest(into: base, count: buf.count)
            }
            guard ok else { return }
            applyDetection(frame: analysisFrame)
            return
        }

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
        applyDetection(frame: frame)
    }

    private func applyDetection(frame: [Float]) {
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
