package net.laprod.app

import android.Manifest
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.view.Gravity
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.media3.common.util.UnstableApi
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import java.io.File

/**
 * Mode Clip, Android (docs/roadmap.md § Chantier 4) : aperçu sous la WebView,
 * tournage vidéo seule (ClipRecorder), son du tournage horodaté
 * (ClipAudioPlayer), montage (ClipComposer), galerie, partage.
 *
 * Toutes les heures renvoyées au JS sont en secondes CLOCK_MONOTONIC.
 */
@UnstableApi
@CapacitorPlugin(
    name = "ClipCamera",
    permissions = [
        Permission(alias = "camera", strings = [Manifest.permission.CAMERA]),
        // Galerie : permission requise uniquement jusqu'à Android 9 (API 28) ;
        // MediaStore n'en demande aucune ensuite (maxSdkVersion=28 au manifeste).
        Permission(alias = "photos", strings = [Manifest.permission.WRITE_EXTERNAL_STORAGE]),
    ],
)
class ClipCameraPlugin : Plugin() {

    private var recorder: ClipRecorder? = null
    private var previewHost: FrameLayout? = null
    private var player: ClipAudioPlayer? = null
    private var facingFront = true
    /** Fond d'origine de la WebView, restauré à la fin du Mode Clip. */
    private var savedWebBg: Int? = null
    private var shareCall: PluginCall? = null
    private var shareReceiver: BroadcastReceiver? = null
    private val main = Handler(Looper.getMainLooper())

    private val cacheDir: File get() = context.cacheDir

    // ── Permissions ───────────────────────────────────────────────────────────

    private fun permissionPayload(): JSObject = JSObject().apply {
        put("camera", getPermissionState("camera").toString())
        put("photos", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) "granted"
                      else getPermissionState("photos").toString())
    }

    @PluginMethod
    override fun checkPermissions(call: PluginCall) { call.resolve(permissionPayload()) }

    @PluginMethod
    override fun requestPermissions(call: PluginCall) {
        val aliases = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) arrayOf("camera") else arrayOf("camera", "photos")
        requestPermissionForAliases(aliases, call, "onPermissions")
    }

    @PermissionCallback
    private fun onPermissions(call: PluginCall) { call.resolve(permissionPayload()) }

    // ── Aperçu ────────────────────────────────────────────────────────────────

    @PluginMethod
    fun startPreview(call: PluginCall) {
        if (getPermissionState("camera") != PermissionState.GRANTED) { call.reject("Caméra refusée.", "DENIED"); return }
        facingFront = (call.getString("facing") ?: "front") == "front"
        activity.runOnUiThread { openPreview(call) }
    }

    /** SurfaceView au format 9:16 (aspect fit), insérée SOUS la WebView rendue transparente. */
    /** Appel startPreview/flipCamera en attente d'ouverture de la caméra. */
    private var pendingPreviewCall: PluginCall? = null

    private fun settlePreview(err: String?) {
        val c = pendingPreviewCall ?: return
        pendingPreviewCall = null
        if (err != null) c.reject(err) else c.resolve()
    }

    private fun openPreview(call: PluginCall) {
        // Un aperçu remplacé avant d'avoir ouvert sa caméra ne laisse pas de promesse pendante.
        settlePreview("Aperçu remplacé.")
        pendingPreviewCall = call
        val web = bridge.webView
        val parent = web.parent as? ViewGroup ?: run { settlePreview("Aperçu indisponible."); return }
        closeRecorder()
        previewHost?.let { parent.removeView(it) }

        val host = FrameLayout(context).apply { setBackgroundColor(Color.BLACK) }
        val surface = SurfaceView(context)
        val w = parent.width.coerceAtLeast(1)
        val h = minOf(parent.height, w * 16 / 9)
        host.addView(surface, FrameLayout.LayoutParams(h * 9 / 16, h, Gravity.CENTER))
        parent.addView(host, 0, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        previewHost = host
        if (savedWebBg == null) savedWebBg = (web.background as? ColorDrawable)?.color ?: Color.WHITE
        web.setBackgroundColor(Color.TRANSPARENT)

        val size = try {
            ClipRecorder(context).prepareSize(facingFront)
        } catch (e: Exception) {
            settlePreview("Caméra indisponible."); return
        }
        surface.holder.setFixedSize(size.width, size.height)
        surface.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                // Surface recréée au retour d'arrière-plan : on rouvre la caméra ici,
                // une seule fois, et seulement pour l'aperçu courant.
                if (previewHost !== host || recorder != null) return
                val rec = ClipRecorder(context)
                rec.onInterrupted = { reason -> notifyListeners("interrupted", JSObject().put("reason", reason)) }
                recorder = rec
                try {
                    rec.prepareSize(facingFront)
                    rec.open(facingFront, holder.surface) { err ->
                        activity.runOnUiThread {
                            if (err != null) {
                                // Échec : on n'empêche pas une réouverture ultérieure.
                                if (recorder === rec) { rec.close(); recorder = null }
                                settlePreview(err)
                            } else {
                                settlePreview(null)
                                // Réouverture native (retour d'arrière-plan) : le JS réaffiche l'aperçu.
                                notifyListeners("previewReady", JSObject())
                            }
                        }
                    }
                } catch (e: Exception) {
                    // CameraAccessException / SecurityException (caméra désactivée, occupée…)
                    rec.close(); recorder = null
                    settlePreview("Caméra indisponible.")
                }
            }
            override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) {}
            override fun surfaceDestroyed(holder: SurfaceHolder) { if (previewHost === host) closeRecorder() }
        })
    }

    @PluginMethod
    fun stopPreview(call: PluginCall) {
        activity.runOnUiThread {
            settlePreview("Aperçu fermé.")
            closeRecorder()
            previewHost?.let { (it.parent as? ViewGroup)?.removeView(it) }
            previewHost = null
            savedWebBg?.let { bridge.webView.setBackgroundColor(it) }
            savedWebBg = null
            call.resolve()
        }
    }

    @PluginMethod
    fun flipCamera(call: PluginCall) {
        facingFront = (call.getString("facing") ?: "front") == "front"
        activity.runOnUiThread { openPreview(call) }
    }

    private fun closeRecorder() {
        recorder?.close()
        recorder = null
    }

    // ── Tournage ──────────────────────────────────────────────────────────────

    @PluginMethod
    fun startRecording(call: PluginCall) {
        val rec = recorder ?: run { call.reject("Caméra non prête."); return }
        try {
            rec.startWriting(File(cacheDir, "clip-raw-${System.currentTimeMillis()}.mp4"))
            call.resolve()
        } catch (e: Exception) {
            call.reject("Enregistrement vidéo impossible.")
        }
    }

    @PluginMethod
    fun stopRecording(call: PluginCall) {
        val r = recorder?.finishWriting() ?: run { call.reject("Aucune image filmée."); return }
        call.resolve(JSObject().apply {
            put("videoPath", Uri.fromFile(r.file).toString())
            put("firstFrameHostSec", r.firstFrameMonoSec)
            put("durationSec", r.durationSec)
            put("frameCount", r.frameCount)
            put("timestampSource", r.source)
        })
    }

    @PluginMethod
    fun cancelRecording(call: PluginCall) {
        recorder?.cancelWriting()
        call.resolve()
    }

    // ── Son du tournage ───────────────────────────────────────────────────────

    @PluginMethod
    fun playAudio(call: PluginCall) {
        val file = fileOf(call.getString("path")) ?: run { call.reject("Son introuvable."); return }
        player?.stop()
        try {
            player = ClipAudioPlayer(file, call.getInt("delayMs")?.toLong() ?: 0L).also { it.start() }
            call.resolve()
        } catch (e: Exception) {
            call.reject("Lecture impossible.")
        }
    }

    @PluginMethod
    fun stopAudio(call: PluginCall) {
        val r = player?.stop()
        player = null
        call.resolve(JSObject().apply {
            if (r != null) {
                put("anchor", JSObject().put("filePosSec", 0.0).put("hostSec", r.anchorSec))
                put("reportedLatencyMs", r.reportedLatencyMs)
                r.driftMs?.let { put("driftMs", it) }
            } else put("anchor", JSObject.NULL)
        })
    }

    // ── Montage ───────────────────────────────────────────────────────────────

    @PluginMethod
    fun compose(call: PluginCall) {
        val video = fileOf(call.getString("videoPath"))
        val audio = fileOf(call.getString("audioPath"))
        val overlay = fileOf(call.getString("overlayPath"))
        val endCard = fileOf(call.getString("endCardPath"))
        if (video == null || audio == null || overlay == null || endCard == null) { call.reject("Fichiers du clip manquants."); return }
        val duration = call.getDouble("durationSec") ?: 0.0
        if (duration <= 0 || duration > ClipSync.MAX_SECONDS + 0.01) {
            call.reject("Un clip dure 45 secondes au maximum.", "TOO_LONG"); return
        }
        val out = File(cacheDir, "clip-final-${System.currentTimeMillis()}.mp4")
        val endSec = call.getDouble("endCardSec") ?: 1.5
        try {
            ClipComposer(context).compose(ClipComposer.Params(
                video = video, audio = audio, overlay = overlay, endCard = endCard,
                videoTrimStartSec = maxOf(0.0, call.getDouble("videoTrimStartSec") ?: 0.0),
                audioSkipSec = maxOf(0.0, call.getDouble("audioSkipSec") ?: 0.0),
                durationSec = duration,
                endCardSec = endSec,
                output = out,
            )) { result ->
                result.onSuccess {
                    call.resolve(JSObject().put("path", Uri.fromFile(it).toString()).put("durationSec", duration + endSec))
                }.onFailure { call.reject("Le clip n'a pas pu être monté.") }
            }
        } catch (e: Exception) {
            call.reject("Le clip n'a pas pu être monté.")
        }
    }

    // ── Galerie ───────────────────────────────────────────────────────────────

    @PluginMethod
    fun saveToGallery(call: PluginCall) {
        val file = fileOf(call.getString("path")) ?: run { call.reject("Clip introuvable."); return }
        val name = "LaProd-clip-${System.currentTimeMillis()}.mp4"
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.Video.Media.DISPLAY_NAME, name)
                    put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                    put(MediaStore.Video.Media.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/LaProd")
                    put(MediaStore.Video.Media.IS_PENDING, 1)
                }
                val resolver = context.contentResolver
                val uri = resolver.insert(MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
                    ?: run { call.reject("Enregistrement impossible."); return }
                resolver.openOutputStream(uri)?.use { out -> file.inputStream().use { it.copyTo(out) } }
                values.clear(); values.put(MediaStore.Video.Media.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
            } else {
                // Android ≤ 9 : sans WRITE_EXTERNAL_STORAGE, l'écriture échouerait en silence (piège § 4.6.9).
                if (getPermissionState("photos") != PermissionState.GRANTED) {
                    call.reject("Accès à la galerie refusé.", "DENIED"); return
                }
                @Suppress("DEPRECATION")
                val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES), "LaProd").apply { mkdirs() }
                val dest = File(dir, name)
                file.copyTo(dest, overwrite = true)
                MediaScannerConnection.scanFile(context, arrayOf(dest.absolutePath), arrayOf("video/mp4"), null)
            }
            call.resolve()
        } catch (e: Exception) {
            call.reject("Enregistrement impossible.")
        }
    }

    // ── Partage ───────────────────────────────────────────────────────────────

    private fun contentUri(file: File): Uri =
        FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)

    @PluginMethod
    fun share(call: PluginCall) {
        val file = fileOf(call.getString("path")) ?: run { call.reject("Clip introuvable."); return }
        val uri = contentUri(file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "video/mp4"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        // La cible choisie revient par diffusion (EXTRA_CHOSEN_COMPONENT) ; sans
        // choix, le retour au premier plan clôt l'appel avec completed=false.
        val action = "${context.packageName}.CLIP_SHARED"
        unregisterShareReceiver()
        shareReceiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) {
                @Suppress("DEPRECATION")
                val comp = i.getParcelableExtra<ComponentName>(Intent.EXTRA_CHOSEN_COMPONENT)
                shareCall?.resolve(JSObject().put("completed", true).put("target", comp?.packageName ?: ""))
                shareCall = null
                unregisterShareReceiver()
            }
        }
        ContextCompat.registerReceiver(context, shareReceiver, IntentFilter(action), ContextCompat.RECEIVER_NOT_EXPORTED)
        val pi = PendingIntent.getBroadcast(
            context, 0, Intent(action).setPackage(context.packageName),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
        )
        shareCall = call
        call.setKeepAlive(true)
        activity.startActivity(Intent.createChooser(send, null, pi.intentSender))
    }

    override fun handleOnResume() {
        super.handleOnResume()
        val pending = shareCall ?: return
        main.postDelayed({
            if (shareCall === pending) {
                pending.resolve(JSObject().put("completed", false))
                shareCall = null
                unregisterShareReceiver()
            }
        }, 600)
    }

    override fun handleOnPause() {
        super.handleOnPause()
        // Mise en arrière-plan PENDANT un tournage : la caméra est coupée par le système.
        // Une simple pause (boîte de permission, feuille de partage) n'interrompt rien.
        if (shareCall == null && recorder?.isWriting() == true) {
            notifyListeners("interrupted", JSObject().put("reason", "background"))
        }
    }

    private fun unregisterShareReceiver() {
        shareReceiver?.let { runCatching { context.unregisterReceiver(it) } }
        shareReceiver = null
    }

    private val instagramPkg = "com.instagram.android"
    private val tiktokPkgs = listOf("com.zhiliaoapp.musically", "com.ss.android.ugc.trill")

    private fun installed(pkg: String): Boolean = runCatching {
        context.packageManager.getPackageInfo(pkg, 0); true
    }.getOrDefault(false)

    @PluginMethod
    fun canShareTo(call: PluginCall) {
        val ok = when (call.getString("target")) {
            "instagram-story" -> installed(instagramPkg)
            "tiktok" -> tiktokPkgs.any { installed(it) }
            else -> false
        }
        call.resolve(JSObject().put("available", ok))
    }

    @PluginMethod
    fun shareTo(call: PluginCall) {
        val file = fileOf(call.getString("path")) ?: run { call.reject("Clip introuvable."); return }
        val uri = contentUri(file)
        try {
            when (call.getString("target")) {
                "instagram-story" -> {
                    val appId = call.getString("appId") ?: ""
                    if (appId.isEmpty()) { call.reject("Story Instagram indisponible."); return }
                    val intent = Intent("com.instagram.share.ADD_TO_STORY").apply {
                        setDataAndType(uri, "video/mp4")
                        putExtra("source_application", appId)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        setPackage(instagramPkg)
                    }
                    activity.grantUriPermission(instagramPkg, uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    activity.startActivity(intent)
                }
                "tiktok" -> {
                    val pkg = tiktokPkgs.firstOrNull { installed(it) } ?: run { call.reject("TikTok n'est pas installé."); return }
                    activity.startActivity(Intent(Intent.ACTION_SEND).apply {
                        type = "video/mp4"
                        putExtra(Intent.EXTRA_STREAM, uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        setPackage(pkg)
                    })
                }
                else -> { call.reject("Raccourci inconnu."); return }
            }
            call.resolve()
        } catch (e: Exception) {
            call.reject("L'application n'a pas pu s'ouvrir.")
        }
    }

    // ── Cache ─────────────────────────────────────────────────────────────────

    @PluginMethod
    fun clearCache(call: PluginCall) {
        cacheDir.listFiles()?.filter { it.name.startsWith("clip-") }?.forEach { it.delete() }
        call.resolve()
    }

    override fun handleOnDestroy() {
        player?.stop(); player = null
        closeRecorder()
        unregisterShareReceiver()
        super.handleOnDestroy()
    }

    /** URI file:// (Capacitor Filesystem) ou chemin absolu → fichier. */
    private fun fileOf(s: String?): File? {
        if (s.isNullOrEmpty()) return null
        val path = if (s.startsWith("file://")) Uri.parse(s).path else s
        return path?.let { File(it) }?.takeIf { it.exists() }
    }
}
