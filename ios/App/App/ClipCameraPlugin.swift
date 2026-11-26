import AVFoundation
import Capacitor
import Photos
import UIKit

// ── Mode Clip : caméra, montage, galerie, partage ────────────────────────────
//
// Spécification : docs/roadmap.md § Chantier 4.
//
// Invariants :
//  - la caméra ne capte JAMAIS d'audio, et la session de capture ne touche
//    JAMAIS à l'AVAudioSession (automaticallyConfiguresApplicationAudioSession
//    = false) : sinon elle reconfigure la session et coupe le beat natif et le
//    retour casque de PitchMonitor (piège § 4.6.1) ;
//  - chaque frame est datée sur l'horloge hôte (mach), la même que celle
//    d'AVAudioEngine (beatStartHostSec de PitchMonitor) : la synchro est un
//    calcul exact, jamais une estimation (§ 4.3) ;
//  - le mux suit les PTS réels, jamais frameIndex / 30 (piège § 4.6.4) ;
//  - seuls des chemins de fichiers traversent le pont (piège § 4.6.8) ;
//  - compose() refuse plus de 45 s (double verrou avec le front).

private let CLIP_MAX_SECONDS: Double = 45
private let CLIP_WIDTH  = 1080
private let CLIP_HEIGHT = 1920
private let CLIP_FPS: Int32 = 30
private let CLIP_FILE_PREFIX = "clip-"

@objc(ClipCameraPlugin)
public class ClipCameraPlugin: CAPPlugin, CAPBridgedPlugin {

    public let identifier = "ClipCameraPlugin"
    public let jsName     = "ClipCamera"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "checkPermissions",   returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestPermissions", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startPreview",       returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopPreview",        returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "flipCamera",         returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startRecording",     returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopRecording",      returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "cancelRecording",    returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "playAudio",          returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopAudio",          returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "compose",            returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "saveToGallery",      returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "share",              returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "canShareTo",         returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "shareTo",            returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clearCache",         returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openSettings",       returnType: CAPPluginReturnPromise),
    ]

    private let recorder = ClipRecorder()
    private var previewView: ClipPreviewView?
    /// Apparence d'origine de la WebView, restaurée à la fin du Mode Clip.
    private var savedWebLook: (opaque: Bool, bg: UIColor?, scrollBg: UIColor?)?

    public override func load() {
        recorder.onInterrupted = { [weak self] reason in
            self?.notifyListeners("interrupted", data: ["reason": reason])
        }
    }

    // ── Permissions ───────────────────────────────────────────────────────────

    @objc override public func checkPermissions(_ call: CAPPluginCall) {
        call.resolve(permissionState())
    }

    @objc override public func requestPermissions(_ call: CAPPluginCall) {
        AVCaptureDevice.requestAccess(for: .video) { _ in
            call.resolve(self.permissionState())
        }
    }

    private func permissionState() -> [String: Any] {
        let cam: String
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:             cam = "granted"
        case .denied, .restricted:    cam = "denied"
        default:                      cam = "prompt"
        }
        let photos: String
        switch PHPhotoLibrary.authorizationStatus(for: .addOnly) {
        case .authorized, .limited:   photos = "granted"
        case .denied, .restricted:    photos = "denied"
        default:                      photos = "prompt"
        }
        return ["camera": cam, "photos": photos]
    }

    // ── Aperçu ────────────────────────────────────────────────────────────────

    @objc func startPreview(_ call: CAPPluginCall) {
        let facing = call.getString("facing") ?? "front"
        recorder.configure(front: facing == "front") { [weak self] error in
            guard let self else { return }
            if let error { call.reject(error); return }
            DispatchQueue.main.async {
                self.attachPreview()
                call.resolve()
            }
        }
    }

    @objc func stopPreview(_ call: CAPPluginCall) {
        recorder.stopSession()
        DispatchQueue.main.async {
            self.detachPreview()
            call.resolve()
        }
    }

    @objc func flipCamera(_ call: CAPPluginCall) {
        let facing = call.getString("facing") ?? "front"
        recorder.switchCamera(front: facing == "front") { error in
            if let error { call.reject(error) } else { call.resolve() }
        }
    }

    /// Couche d'aperçu SOUS la WebView, rendue transparente le temps du Mode Clip.
    private func attachPreview() {
        guard let vc = bridge?.viewController, let web = bridge?.webView else { return }
        if previewView == nil {
            let v = ClipPreviewView(session: recorder.session)
            v.frame = vc.view.bounds
            v.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            vc.view.insertSubview(v, belowSubview: web)
            previewView = v
        }
        if savedWebLook == nil {
            savedWebLook = (web.isOpaque, web.backgroundColor, web.scrollView.backgroundColor)
        }
        web.isOpaque = false
        web.backgroundColor = .clear
        web.scrollView.backgroundColor = .clear
    }

    private func detachPreview() {
        previewView?.removeFromSuperview()
        previewView = nil
        if let web = bridge?.webView, let look = savedWebLook {
            web.isOpaque = look.opaque
            web.backgroundColor = look.bg
            web.scrollView.backgroundColor = look.scrollBg
        }
        savedWebLook = nil
    }

    // ── Tournage ──────────────────────────────────────────────────────────────

    @objc func startRecording(_ call: CAPPluginCall) {
        let url = ClipFiles.cacheURL("\(CLIP_FILE_PREFIX)raw-\(Int(Date().timeIntervalSince1970 * 1000)).mp4")
        recorder.startWriting(to: url) { error in
            if let error { call.reject(error) } else { call.resolve() }
        }
    }

    @objc func stopRecording(_ call: CAPPluginCall) {
        recorder.finishWriting { result in
            switch result {
            case .failure(let message): call.reject(message)
            case .success(let r):
                call.resolve([
                    "videoPath":         r.url.absoluteString,
                    "firstFrameHostSec": r.firstFrameHostSec,
                    "durationSec":       r.durationSec,
                    "frameCount":        r.frameCount,
                    "timestampSource":   "host",
                ])
            }
        }
    }

    @objc func cancelRecording(_ call: CAPPluginCall) {
        recorder.cancelWriting()
        call.resolve()
    }

    // iOS : le son du tournage est joué par PitchMonitor (beat natif, même horloge).
    @objc func playAudio(_ call: CAPPluginCall) {
        call.unimplemented("iOS : le son du clip est joué par PitchMonitor.")
    }

    @objc func stopAudio(_ call: CAPPluginCall) {
        call.resolve(["anchor": NSNull()])
    }

    // ── Montage ───────────────────────────────────────────────────────────────

    @objc func compose(_ call: CAPPluginCall) {
        guard
            let videoURL   = ClipFiles.url(call.getString("videoPath")),
            let audioURL   = ClipFiles.url(call.getString("audioPath")),
            let overlayURL = ClipFiles.url(call.getString("overlayPath")),
            let endURL     = ClipFiles.url(call.getString("endCardPath"))
        else { call.reject("Fichiers du clip manquants."); return }

        let duration = call.getDouble("durationSec") ?? 0
        guard duration > 0, duration <= CLIP_MAX_SECONDS + 0.01 else {
            call.reject("Un clip dure 45 secondes au maximum.", "TOO_LONG")
            return
        }
        let job = ClipComposeJob(
            videoURL: videoURL, audioURL: audioURL, overlayURL: overlayURL, endCardURL: endURL,
            videoTrimStart: max(0, call.getDouble("videoTrimStartSec") ?? 0),
            audioSkip: max(0, call.getDouble("audioSkipSec") ?? 0),
            duration: duration,
            endCard: max(0, call.getDouble("endCardSec") ?? 1.5)
        )
        job.run { result in
            switch result {
            case .failure(let message): call.reject(message)
            case .success(let out):
                call.resolve(["path": out.url.absoluteString, "durationSec": out.duration])
            }
        }
    }

    // ── Galerie ───────────────────────────────────────────────────────────────

    @objc func saveToGallery(_ call: CAPPluginCall) {
        guard let url = ClipFiles.url(call.getString("path")) else { call.reject("Clip introuvable."); return }
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { status in
            guard status == .authorized || status == .limited else {
                call.reject("Accès à la photothèque refusé.", "DENIED")
                return
            }
            PHPhotoLibrary.shared().performChanges({
                PHAssetChangeRequest.creationRequestForAssetFromVideo(atFileURL: url)
            }) { ok, error in
                if ok { call.resolve() } else { call.reject(error?.localizedDescription ?? "Enregistrement impossible.") }
            }
        }
    }

    // ── Partage ───────────────────────────────────────────────────────────────

    @objc func share(_ call: CAPPluginCall) {
        guard let url = ClipFiles.url(call.getString("path")) else { call.reject("Clip introuvable."); return }
        DispatchQueue.main.async {
            guard let vc = self.bridge?.viewController else { call.reject("Partage indisponible."); return }
            // Le FICHIER seul : un texte joint fait choisir à certaines apps le texte
            // plutôt que la vidéo. La légende est déjà dans le presse-papiers.
            let sheet = UIActivityViewController(activityItems: [url], applicationActivities: nil)
            sheet.completionWithItemsHandler = { type, completed, _, error in
                if let error { call.reject(error.localizedDescription); return }
                var data: [String: Any] = ["completed": completed]
                if let type { data["target"] = type.rawValue }
                call.resolve(data)
            }
            if let pop = sheet.popoverPresentationController {
                pop.sourceView = vc.view
                pop.sourceRect = CGRect(x: vc.view.bounds.midX, y: vc.view.bounds.maxY - 80, width: 1, height: 1)
            }
            vc.present(sheet, animated: true)
        }
    }

    @objc func canShareTo(_ call: CAPPluginCall) {
        let target = call.getString("target") ?? ""
        DispatchQueue.main.async {
            switch target {
            case "instagram-story":
                let ok = URL(string: "instagram-stories://share").map { UIApplication.shared.canOpenURL($0) } ?? false
                call.resolve(["available": ok])
            default:
                // TikTok iOS : partage direct réservé au SDK officiel (Share Kit) —
                // non intégré, la feuille système couvre TikTok.
                call.resolve(["available": false])
            }
        }
    }

    @objc func shareTo(_ call: CAPPluginCall) {
        guard call.getString("target") == "instagram-story" else {
            call.unimplemented("Raccourci indisponible sur iOS.")
            return
        }
        guard
            let url = ClipFiles.url(call.getString("path")),
            let appId = call.getString("appId"), !appId.isEmpty,
            let data = try? Data(contentsOf: url),
            let open = URL(string: "instagram-stories://share?source_application=\(appId)")
        else { call.reject("Story Instagram indisponible."); return }

        DispatchQueue.main.async {
            UIPasteboard.general.setItems(
                [["com.instagram.sharedSticker.backgroundVideo": data]],
                options: [.expirationDate: Date().addingTimeInterval(300)]
            )
            UIApplication.shared.open(open) { ok in
                if ok { call.resolve() } else { call.reject("Instagram n'a pas pu s'ouvrir.") }
            }
        }
    }

    // ── Cache ─────────────────────────────────────────────────────────────────

    @objc func openSettings(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard let url = URL(string: UIApplication.openSettingsURLString) else { call.resolve(); return }
            UIApplication.shared.open(url) { _ in call.resolve() }
        }
    }

    @objc func clearCache(_ call: CAPPluginCall) {
        ClipFiles.clear()
        call.resolve()
    }
}

// ── Fichiers ──────────────────────────────────────────────────────────────────

enum ClipFiles {
    static var cacheDir: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    }

    static func cacheURL(_ name: String) -> URL { cacheDir.appendingPathComponent(name) }

    /// URI file:// (Capacitor Filesystem) ou chemin absolu → URL fichier.
    static func url(_ s: String?) -> URL? {
        guard let s, !s.isEmpty else { return nil }
        if s.hasPrefix("file://") { return URL(string: s) }
        return URL(fileURLWithPath: s)
    }

    /// Supprime les fichiers du Mode Clip (préfixe clip-) du cache et du tmp.
    static func clear() {
        let fm = FileManager.default
        for dir in [cacheDir, fm.temporaryDirectory] {
            let items = (try? fm.contentsOfDirectory(atPath: dir.path)) ?? []
            for name in items where name.hasPrefix(CLIP_FILE_PREFIX) {
                try? fm.removeItem(at: dir.appendingPathComponent(name))
            }
        }
    }
}

// ── Vue d'aperçu (cadre 9:16, aspect fit) ─────────────────────────────────────

final class ClipPreviewView: UIView {
    private let previewLayer: AVCaptureVideoPreviewLayer

    init(session: AVCaptureSession) {
        previewLayer = AVCaptureVideoPreviewLayer(session: session)
        super.init(frame: .zero)
        backgroundColor = .black
        // Aspect fit : ce qui est visible est exactement le cadre 1080×1920 exporté
        // (même cadre que .clip-frame côté WebView). Miroir automatique en frontale.
        previewLayer.videoGravity = .resizeAspect
        layer.addSublayer(previewLayer)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) non utilisé") }

    override func layoutSubviews() {
        super.layoutSubviews()
        let w = bounds.width
        let h = min(bounds.height, w * 16 / 9)
        let fw = h * 9 / 16
        previewLayer.frame = CGRect(x: (w - fw) / 2, y: (bounds.height - h) / 2, width: fw, height: h)
        if let c = previewLayer.connection, c.isVideoOrientationSupported {
            c.videoOrientation = .portrait
        }
    }
}

// ── Enregistreur (capture vidéo seule → AVAssetWriter) ───────────────────────

struct ClipRecording {
    let url: URL
    let firstFrameHostSec: Double
    let durationSec: Double
    let frameCount: Int
}

enum ClipResult<T> {
    case success(T)
    case failure(String)
}

final class ClipRecorder: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {

    let session = AVCaptureSession()
    var onInterrupted: ((String) -> Void)?

    private let sessionQueue = DispatchQueue(label: "net.laprod.clip.session")
    private let videoQueue   = DispatchQueue(label: "net.laprod.clip.video")
    private let output = AVCaptureVideoDataOutput()
    private var input: AVCaptureDeviceInput?
    private var configured = false
    private var observers: [NSObjectProtocol] = []

    // État d'écriture — accédé uniquement sur videoQueue.
    private var writer: AVAssetWriter?
    private var writerInput: AVAssetWriterInput?
    private var writing = false
    private var firstPTS: CMTime = .invalid
    private var lastPTS:  CMTime = .invalid
    private var frameCount = 0

    func configure(front: Bool, completion: @escaping (String?) -> Void) {
        sessionQueue.async {
            if !self.configured {
                self.session.beginConfiguration()
                // Piège § 4.6.1 : sans cette ligne, la capture reconfigure
                // l'AVAudioSession et coupe le beat natif / le retour casque.
                self.session.automaticallyConfiguresApplicationAudioSession = false
                if self.session.canSetSessionPreset(.hd1920x1080) {
                    self.session.sessionPreset = .hd1920x1080
                }
                self.output.alwaysDiscardsLateVideoFrames = false
                self.output.setSampleBufferDelegate(self, queue: self.videoQueue)
                if self.session.canAddOutput(self.output) { self.session.addOutput(self.output) }
                self.session.commitConfiguration()
                self.configured = true
                self.observe()
            }
            if let err = self.setCamera(front: front) { completion(err); return }
            if !self.session.isRunning { self.session.startRunning() }
            completion(nil)
        }
    }

    func switchCamera(front: Bool, completion: @escaping (String?) -> Void) {
        sessionQueue.async { completion(self.setCamera(front: front)) }
    }

    private func setCamera(front: Bool) -> String? {
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video,
                                                   position: front ? .front : .back)
        else { return "Caméra indisponible." }
        do {
            let newInput = try AVCaptureDeviceInput(device: device)
            session.beginConfiguration()
            if let input { session.removeInput(input) }
            guard session.canAddInput(newInput) else {
                if let input { session.addInput(input) }
                session.commitConfiguration()
                return "Caméra indisponible."
            }
            session.addInput(newInput)
            input = newInput
            // 30 fps seulement si le format actif le permet et si le verrou est obtenu :
            // fixer une durée de frame hors plage lève une NSException (crash).
            let fps = Double(CLIP_FPS)
            let supported = device.activeFormat.videoSupportedFrameRateRanges.contains {
                $0.minFrameRate <= fps && fps <= $0.maxFrameRate
            }
            if supported, (try? device.lockForConfiguration()) != nil {
                device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CLIP_FPS)
                device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CLIP_FPS)
                device.unlockForConfiguration()
            }
            if let c = output.connection(with: .video) {
                // Frames écrites en portrait 1080×1920, JAMAIS en miroir (§ 4.6.5) :
                // l'aperçu est miroir, la vidéo exportée montre la vraie scène.
                if c.isVideoOrientationSupported { c.videoOrientation = .portrait }
                if c.isVideoMirroringSupported {
                    c.automaticallyAdjustsVideoMirroring = false
                    c.isVideoMirrored = false
                }
            }
            session.commitConfiguration()
            return nil
        } catch {
            return "Caméra indisponible."
        }
    }

    func stopSession() {
        sessionQueue.async {
            if self.session.isRunning { self.session.stopRunning() }
        }
    }

    private func observe() {
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(forName: .AVCaptureSessionWasInterrupted, object: session, queue: nil) { [weak self] _ in
            self?.reportInterruption("interrupted")
        })
        observers.append(nc.addObserver(forName: .AVCaptureSessionRuntimeError, object: session, queue: nil) { [weak self] _ in
            self?.reportInterruption("error")
        })
    }

    private func reportInterruption(_ reason: String) {
        videoQueue.async {
            guard self.writing else { return }
            self.onInterrupted?(reason)
        }
    }

    // ── Écriture ──────────────────────────────────────────────────────────────

    func startWriting(to url: URL, completion: @escaping (String?) -> Void) {
        videoQueue.async {
            try? FileManager.default.removeItem(at: url)
            do {
                let w = try AVAssetWriter(outputURL: url, fileType: .mp4)
                let settings: [String: Any] = [
                    AVVideoCodecKey:  AVVideoCodecType.h264,
                    AVVideoWidthKey:  CLIP_WIDTH,
                    AVVideoHeightKey: CLIP_HEIGHT,
                    AVVideoCompressionPropertiesKey: [
                        AVVideoAverageBitRateKey:  12_000_000,
                        AVVideoProfileLevelKey:    AVVideoProfileLevelH264HighAutoLevel,
                        AVVideoExpectedSourceFrameRateKey: CLIP_FPS,
                    ],
                ]
                let i = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
                i.expectsMediaDataInRealTime = true
                guard w.canAdd(i) else { completion("Enregistrement vidéo impossible."); return }
                w.add(i)
                self.writer = w
                self.writerInput = i
                self.firstPTS = .invalid
                self.lastPTS = .invalid
                self.frameCount = 0
                self.writing = true
                completion(nil)
            } catch {
                completion("Enregistrement vidéo impossible.")
            }
        }
    }

    func finishWriting(completion: @escaping (ClipResult<ClipRecording>) -> Void) {
        videoQueue.async {
            guard let w = self.writer, let i = self.writerInput, self.writing, self.firstPTS.isValid else {
                self.reset()
                completion(.failure("Aucune image filmée."))
                return
            }
            self.writing = false
            let first = self.firstPTS, last = self.lastPTS, count = self.frameCount
            i.markAsFinished()
            w.finishWriting {
                let ok = w.status == .completed
                let url = w.outputURL
                self.videoQueue.async { self.reset() }
                guard ok else { completion(.failure("Enregistrement vidéo impossible.")); return }
                let frame = 1.0 / Double(CLIP_FPS)
                completion(.success(ClipRecording(
                    url: url,
                    firstFrameHostSec: self.hostSeconds(first),
                    durationSec: CMTimeGetSeconds(CMTimeSubtract(last, first)) + frame,
                    frameCount: count
                )))
            }
        }
    }

    func cancelWriting() {
        videoQueue.async {
            self.writing = false
            if let w = self.writer, w.status == .writing { w.cancelWriting() }
            if let url = self.writer?.outputURL { try? FileManager.default.removeItem(at: url) }
            self.reset()
        }
    }

    private func reset() {
        writer = nil
        writerInput = nil
        writing = false
        firstPTS = .invalid
        lastPTS = .invalid
        frameCount = 0
    }

    /// PTS caméra (horloge de synchronisation de la session) → horloge hôte, en secondes.
    /// AVAudioTime.seconds(forHostTime:) exprime l'ancre audio dans la même base.
    private func hostSeconds(_ pts: CMTime) -> Double {
        let clock: CMClock?
        if #available(iOS 15.4, *) { clock = session.synchronizationClock } else { clock = session.masterClock }
        guard let clock else { return CMTimeGetSeconds(pts) }
        return CMTimeGetSeconds(CMSyncConvertTime(pts, from: clock, to: CMClockGetHostTimeClock()))
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard writing, let w = writer, let i = writerInput else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if w.status == .unknown {
            guard w.startWriting() else { return }
            // La vidéo commence à la 1re frame reçue ; son instant hôte est l'ancre vidéo.
            w.startSession(atSourceTime: pts)
            firstPTS = pts
        }
        guard w.status == .writing, i.isReadyForMoreMediaData else { return }
        if i.append(sampleBuffer) {
            lastPTS = pts
            frameCount += 1
        }
    }
}

// ── Montage final : vidéo rognée + WAV + filigrane + carte de fin ────────────

struct ClipComposed {
    let url: URL
    let duration: Double
}

final class ClipComposeJob {
    let videoURL: URL, audioURL: URL, overlayURL: URL, endCardURL: URL
    let videoTrimStart: Double, audioSkip: Double, duration: Double, endCard: Double
    private var export: AVAssetExportSession?

    init(videoURL: URL, audioURL: URL, overlayURL: URL, endCardURL: URL,
         videoTrimStart: Double, audioSkip: Double, duration: Double, endCard: Double) {
        self.videoURL = videoURL; self.audioURL = audioURL
        self.overlayURL = overlayURL; self.endCardURL = endCardURL
        self.videoTrimStart = videoTrimStart; self.audioSkip = audioSkip
        self.duration = duration; self.endCard = endCard
    }

    func run(completion: @escaping (ClipResult<ClipComposed>) -> Void) {
        let ts: CMTimeScale = 48_000
        let vAsset = AVURLAsset(url: videoURL, options: [AVURLAssetPreferPreciseDurationAndTimingKey: true])
        let aAsset = AVURLAsset(url: audioURL, options: [AVURLAssetPreferPreciseDurationAndTimingKey: true])
        guard
            let srcV = vAsset.tracks(withMediaType: .video).first,
            let srcA = aAsset.tracks(withMediaType: .audio).first,
            let overlay = UIImage(contentsOfFile: overlayURL.path)?.cgImage,
            let endImg  = UIImage(contentsOfFile: endCardURL.path)?.cgImage
        else { completion(.failure("Fichiers du clip illisibles.")); return }

        let comp = AVMutableComposition()
        guard
            let vTrack = comp.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
            let aTrack = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
        else { completion(.failure("Montage impossible.")); return }

        let body  = CMTime(seconds: duration, preferredTimescale: ts)
        let tail  = CMTime(seconds: endCard,  preferredTimescale: ts)
        let total = CMTimeAdd(body, tail)
        let vAvail = CMTimeSubtract(vAsset.duration, CMTime(seconds: videoTrimStart, preferredTimescale: ts))
        let aAvail = CMTimeSubtract(aAsset.duration, CMTime(seconds: audioSkip, preferredTimescale: ts))
        do {
            try vTrack.insertTimeRange(
                CMTimeRange(start: CMTime(seconds: videoTrimStart, preferredTimescale: ts),
                            duration: CMTimeMinimum(body, vAvail)),
                of: srcV, at: .zero)
            // Carte de fin : segment vide (noir) recouvert par l'image de fin.
            vTrack.insertEmptyTimeRange(CMTimeRange(start: vTrack.timeRange.end, duration: tail))
            try aTrack.insertTimeRange(
                CMTimeRange(start: CMTime(seconds: audioSkip, preferredTimescale: ts),
                            duration: CMTimeMinimum(total, aAvail)),
                of: srcA, at: .zero)
        } catch {
            completion(.failure("Montage impossible."))
            return
        }

        let size = CGSize(width: CLIP_WIDTH, height: CLIP_HEIGHT)
        let videoComp = AVMutableVideoComposition()
        videoComp.renderSize = size
        videoComp.frameDuration = CMTime(value: 1, timescale: CLIP_FPS)
        let instr = AVMutableVideoCompositionInstruction()
        instr.timeRange = CMTimeRange(start: .zero, duration: total)
        let layerInstr = AVMutableVideoCompositionLayerInstruction(assetTrack: vTrack)
        layerInstr.setTransform(srcV.preferredTransform, at: .zero)
        instr.layerInstructions = [layerInstr]
        videoComp.instructions = [instr]

        // Filigrane + carte de fin, dessinés par la WebView (clip-overlay.ts) en PNG.
        let parent = CALayer(); parent.frame = CGRect(origin: .zero, size: size)
        let videoLayer = CALayer(); videoLayer.frame = parent.frame
        let overlayLayer = CALayer(); overlayLayer.frame = parent.frame
        overlayLayer.contents = overlay
        let endLayer = CALayer(); endLayer.frame = parent.frame
        endLayer.contents = endImg
        endLayer.opacity = 0
        let show = CABasicAnimation(keyPath: "opacity")
        show.fromValue = 1; show.toValue = 1
        show.beginTime = AVCoreAnimationBeginTimeAtZero + duration
        show.duration = endCard + 1
        show.isRemovedOnCompletion = false
        show.fillMode = .forwards
        endLayer.add(show, forKey: "endcard")
        parent.addSublayer(videoLayer)
        parent.addSublayer(overlayLayer)
        parent.addSublayer(endLayer)
        videoComp.animationTool = AVVideoCompositionCoreAnimationTool(
            postProcessingAsVideoLayer: videoLayer, in: parent)

        let out = ClipFiles.cacheURL("\(CLIP_FILE_PREFIX)final-\(Int(Date().timeIntervalSince1970 * 1000)).mp4")
        try? FileManager.default.removeItem(at: out)
        guard let ex = AVAssetExportSession(asset: comp, presetName: AVAssetExportPresetHighestQuality) else {
            completion(.failure("Export impossible."))
            return
        }
        ex.outputURL = out
        ex.outputFileType = .mp4
        ex.videoComposition = videoComp
        ex.shouldOptimizeForNetworkUse = true          // moov en tête (faststart)
        ex.timeRange = CMTimeRange(start: .zero, duration: total)
        export = ex
        ex.exportAsynchronously { [self] in
            defer { self.export = nil }
            if ex.status == .completed {
                completion(.success(ClipComposed(url: out, duration: CMTimeGetSeconds(total))))
            } else {
                completion(.failure(ex.error?.localizedDescription ?? "Export impossible."))
            }
        }
    }
}
