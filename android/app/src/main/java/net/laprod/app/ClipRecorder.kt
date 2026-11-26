package net.laprod.app

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import android.util.Range
import android.util.Size
import android.view.Surface
import java.io.File

/**
 * Mode Clip, Android : caméra Camera2 → encodeur H.264 (surface) → MP4.
 *
 * Pourquoi pas CameraX VideoCapture : son Recorder ne dit pas quel instant
 * capteur correspond à la 1re frame du fichier — or toute la synchro du clip
 * repose sur cet instant (docs § 4.3). Ici, les PTS de l'encodeur SONT les
 * timestamps capteur (surface Camera2) : la 1re frame écrite est datée à la
 * nanoseconde, dans une base convertie en CLOCK_MONOTONIC (ClipSync).
 *
 * Invariants : vidéo SEULE (aucune capture audio : la session micro reste à
 * PitchMonitor), mux sur les PTS réels (piège § 4.6.4), fichier non miroir
 * (le capteur frontal n'est pas miroir ; seul l'aperçu SurfaceView l'est).
 */
class ClipRecorder(private val context: Context) {

    var onInterrupted: ((String) -> Unit)? = null

    data class Result(
        val file: File,
        val firstFrameMonoSec: Double,
        val durationSec: Double,
        val frameCount: Int,
        val source: String,
    )

    private val manager = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var encoder: MediaCodec? = null
    private var encoderSurface: Surface? = null
    private var encoderThread: Thread? = null
    @Volatile private var encoding = false
    private var outputFormat: MediaFormat? = null

    private var previewSurface: Surface? = null
    var videoSize: Size = Size(1920, 1080)
        private set
    private var sensorOrientation = 90
    private var front = true
    /** Annoncé par le capteur (rapporté au JS pour diagnostic ; la base réelle des PTS est déduite des données). */
    private var realtimeSource = false

    // Écriture — protégé par `lock`.
    private val lock = Object()
    private var muxer: MuxState? = null

    private class MuxState(val file: File, val muxer: MediaMuxer, val track: Int) {
        var waitingKeyFrame = true
        var firstPtsUs = -1L
        var firstDrainMonoNs = 0L
        var firstDrainBootNs = 0L
        var lastPtsUs = -1L
        var frames = 0
    }

    fun isFront() = front
    fun isWriting(): Boolean = synchronized(lock) { muxer != null }
    @Volatile private var closed = false

    /** Taille vidéo pour cette caméra — à appeler avant de dimensionner la surface d'aperçu. */
    fun prepareSize(front: Boolean): Size {
        val id = cameraId(front) ?: return videoSize
        videoSize = pickSize(manager.getCameraCharacteristics(id))
        return videoSize
    }

    /** Ouvre la caméra et démarre aperçu + encodeur (l'encodeur tourne à vide jusqu'au tournage). */
    @SuppressLint("MissingPermission")
    fun open(front: Boolean, preview: Surface, onReady: (String?) -> Unit) {
        this.front = front
        this.previewSurface = preview
        val t = HandlerThread("clip-camera").also { it.start() }
        thread = t
        handler = Handler(t.looper)

        val id = cameraId(front) ?: run { onReady("Caméra indisponible."); return }
        val chars = manager.getCameraCharacteristics(id)
        sensorOrientation = chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 90
        realtimeSource = chars.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ==
            CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
        videoSize = pickSize(chars)

        try {
            startEncoder()
        } catch (e: Exception) {
            onReady("Encodeur vidéo indisponible.")
            return
        }

        manager.openCamera(id, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                // Fermé pendant l'ouverture (retour arrière-plan, bascule caméra) : on relâche.
                if (closed) { camera.close(); return }
                device = camera
                createSession(camera, chars, onReady)
            }
            override fun onDisconnected(camera: CameraDevice) {
                camera.close(); device = null
                onInterrupted?.invoke("disconnected")
            }
            override fun onError(camera: CameraDevice, error: Int) {
                camera.close(); device = null
                onInterrupted?.invoke("error")
                onReady("Caméra indisponible.")
            }
        }, handler)
    }

    private fun cameraId(front: Boolean): String? {
        val wanted = if (front) CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        return manager.cameraIdList.firstOrNull {
            manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) == wanted
        }
    }

    private fun pickSize(chars: CameraCharacteristics): Size {
        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP) ?: return Size(1920, 1080)
        val sizes = map.getOutputSizes(MediaCodec::class.java) ?: return Size(1920, 1080)
        sizes.firstOrNull { it.width == 1920 && it.height == 1080 }?.let { return it }
        // Repli : plus grand 16:9 ≤ 1920 (Media3 remet au format 1080×1920 au montage).
        return sizes.filter { it.width <= 1920 && it.width * 9 == it.height * 16 }
            .maxByOrNull { it.width } ?: Size(1280, 720)
    }

    private fun startEncoder() {
        val fmt = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, videoSize.width, videoSize.height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, 12_000_000)
            setInteger(MediaFormat.KEY_FRAME_RATE, 30)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
        }
        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        encoderSurface = codec.createInputSurface()
        codec.start()
        encoder = codec
        encoding = true
        encoderThread = Thread({ drainLoop(codec) }, "clip-encoder").also { it.start() }
    }

    private fun createSession(camera: CameraDevice, chars: CameraCharacteristics, onReady: (String?) -> Unit) {
        val targets = listOfNotNull(previewSurface, encoderSurface)
        @Suppress("DEPRECATION")
        camera.createCaptureSession(targets, object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(s: CameraCaptureSession) {
                session = s
                val req = camera.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                    targets.forEach { addTarget(it) }
                    fpsRange(chars)?.let { set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, it) }
                }.build()
                s.setRepeatingRequest(req, null, handler)
                onReady(null)
            }
            override fun onConfigureFailed(s: CameraCaptureSession) { onReady("Caméra indisponible.") }
        }, handler)
    }

    private fun fpsRange(chars: CameraCharacteristics): Range<Int>? {
        val ranges = chars.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES) ?: return null
        return ranges.firstOrNull { it.lower == 30 && it.upper == 30 } ?: ranges.firstOrNull { it.upper == 30 }
    }

    /** Orientation à inscrire dans le MP4 pour un appareil tenu en portrait. */
    private fun orientationHint(): Int = sensorOrientation

    fun startWriting(file: File) {
        synchronized(lock) {
            val fmt = outputFormat ?: error("Encodeur pas prêt.")
            file.delete()
            val m = MediaMuxer(file.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            m.setOrientationHint(orientationHint())
            val track = m.addTrack(fmt)
            m.start()
            muxer = MuxState(file, m, track)
        }
        // La 1re frame du fichier doit être une image clé.
        encoder?.setParameters(Bundle().apply { putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0) })
    }

    fun finishWriting(): Result? {
        val st = synchronized(lock) { muxer.also { muxer = null } } ?: return null
        runCatching { st.muxer.stop() }
        st.muxer.release()
        if (st.frames == 0 || st.firstPtsUs < 0) { st.file.delete(); return null }
        val firstMonoNs = ClipSync.encoderPtsToMonoNs(st.firstPtsUs * 1000L, st.firstDrainMonoNs, st.firstDrainBootNs)
        return Result(
            file = st.file,
            firstFrameMonoSec = firstMonoNs / 1e9,
            durationSec = (st.lastPtsUs - st.firstPtsUs) / 1e6 + 1.0 / 30,
            frameCount = st.frames,
            source = if (realtimeSource) "realtime" else "unknown",
        )
    }

    fun cancelWriting() {
        val st = synchronized(lock) { muxer.also { muxer = null } } ?: return
        runCatching { st.muxer.stop() }
        st.muxer.release()
        st.file.delete()
    }

    private fun drainLoop(codec: MediaCodec) {
        val info = MediaCodec.BufferInfo()
        while (encoding) {
            val idx = try { codec.dequeueOutputBuffer(info, 10_000) } catch (e: IllegalStateException) { break }
            when {
                idx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> synchronized(lock) { outputFormat = codec.outputFormat }
                idx >= 0 -> {
                    val buf = codec.getOutputBuffer(idx)
                    val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                    if (buf != null && !isConfig && info.size > 0) {
                        synchronized(lock) {
                            val st = muxer
                            if (st != null) {
                                val key = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
                                if (st.waitingKeyFrame && key) st.waitingKeyFrame = false
                                if (!st.waitingKeyFrame && info.presentationTimeUs > st.lastPtsUs) {
                                    if (st.firstPtsUs < 0) {
                                        st.firstPtsUs = info.presentationTimeUs
                                        // Les deux horloges lues au même instant : base des PTS déduite des données.
                                        st.firstDrainMonoNs = System.nanoTime()
                                        st.firstDrainBootNs = SystemClock.elapsedRealtimeNanos()
                                    }
                                    // PTS réels, rebasés sur la 1re frame du fichier.
                                    val out = MediaCodec.BufferInfo().apply {
                                        set(info.offset, info.size, info.presentationTimeUs - st.firstPtsUs, info.flags)
                                    }
                                    buf.position(info.offset); buf.limit(info.offset + info.size)
                                    st.muxer.writeSampleData(st.track, buf, out)
                                    st.lastPtsUs = info.presentationTimeUs
                                    st.frames++
                                }
                            }
                        }
                    }
                    codec.releaseOutputBuffer(idx, false)
                }
            }
        }
    }

    fun close() {
        closed = true
        cancelWriting()
        runCatching { session?.close() }; session = null
        runCatching { device?.close() }; device = null
        encoding = false
        encoderThread?.join(500); encoderThread = null
        runCatching { encoder?.stop() }; runCatching { encoder?.release() }; encoder = null
        encoderSurface?.release(); encoderSurface = null
        outputFormat = null
        thread?.quitSafely(); thread = null; handler = null
    }
}
