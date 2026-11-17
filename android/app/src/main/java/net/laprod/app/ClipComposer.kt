package net.laprod.app

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.Effect
import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.effect.BitmapOverlay
import androidx.media3.effect.OverlayEffect
import androidx.media3.effect.Presentation
import androidx.media3.effect.TextureOverlay
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.EditedMediaItemSequence
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.Transformer
import com.google.common.collect.ImmutableList
import java.io.File

/**
 * Mode Clip, Android : montage final avec Media3 Transformer (Apache-2.0 —
 * pas de FFmpeg, docs § 4.1.12).
 *
 * Séquence vidéo : vidéo brute rognée (+ filigrane) puis carte de fin (image).
 * Séquence audio : le WAV du mix final, à partir de audioSkip, carte de fin
 * incluse (fondu déjà rendu dans le WAV). Sortie H.264 + AAC, 1080×1920.
 */
@UnstableApi
class ClipComposer(private val context: Context) {

    data class Params(
        val video: File,
        val audio: File,
        val overlay: File,
        val endCard: File,
        val videoTrimStartSec: Double,
        val audioSkipSec: Double,
        val durationSec: Double,
        val endCardSec: Double,
        val output: File,
    )

    fun compose(p: Params, done: (Result<File>) -> Unit) {
        require(p.durationSec > 0 && p.durationSec <= ClipSync.MAX_SECONDS + 0.01) { "Un clip dure 45 secondes au maximum." }

        val trimMs  = (p.videoTrimStartSec * 1000).toLong()
        val durMs   = (p.durationSec * 1000).toLong()
        val endMs   = (p.endCardSec * 1000).toLong()
        val skipMs  = (p.audioSkipSec * 1000).toLong()
        val toFrame = Presentation.createForWidthAndHeight(1080, 1920, Presentation.LAYOUT_SCALE_TO_FIT_WITH_CROP)

        val overlayBmp = BitmapFactory.decodeFile(p.overlay.absolutePath) ?: run {
            done(Result.failure(IllegalStateException("Filigrane illisible."))); return
        }

        val videoItem = EditedMediaItem.Builder(
            MediaItem.Builder()
                .setUri(Uri.fromFile(p.video))
                .setClippingConfiguration(
                    MediaItem.ClippingConfiguration.Builder()
                        .setStartPositionMs(trimMs)
                        .setEndPositionMs(trimMs + durMs)
                        .build()
                ).build()
        )
            .setRemoveAudio(true)
            .setEffects(Effects(
                ImmutableList.of(),
                ImmutableList.of<Effect>(toFrame, OverlayEffect(ImmutableList.of<TextureOverlay>(BitmapOverlay.createStaticBitmapOverlay(overlayBmp)))),
            ))
            .build()

        val endItem = EditedMediaItem.Builder(
            MediaItem.Builder()
                .setUri(Uri.fromFile(p.endCard))
                .setImageDurationMs(endMs)
                .build()
        )
            .setFrameRate(30)
            .setEffects(Effects(ImmutableList.of(), ImmutableList.of<Effect>(toFrame)))
            .build()

        val audioItem = EditedMediaItem.Builder(
            MediaItem.Builder()
                .setUri(Uri.fromFile(p.audio))
                .setClippingConfiguration(
                    MediaItem.ClippingConfiguration.Builder()
                        .setStartPositionMs(skipMs)
                        .setEndPositionMs(skipMs + durMs + endMs)
                        .build()
                ).build()
        ).build()

        val composition = Composition.Builder(
            EditedMediaItemSequence.Builder(videoItem, endItem).build(),
            EditedMediaItemSequence.Builder(audioItem).build(),
        ).build()

        p.output.delete()
        // Transformer doit être créé et démarré sur un thread avec Looper.
        Handler(Looper.getMainLooper()).post {
            val transformer = Transformer.Builder(context)
                .setVideoMimeType(MimeTypes.VIDEO_H264)
                .setAudioMimeType(MimeTypes.AUDIO_AAC)
                .addListener(object : Transformer.Listener {
                    override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                        done(Result.success(p.output))
                    }
                    override fun onError(composition: Composition, exportResult: ExportResult, exportException: ExportException) {
                        p.output.delete()
                        done(Result.failure(exportException))
                    }
                })
                .build()
            transformer.start(composition, p.output.absolutePath)
        }
    }
}
