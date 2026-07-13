package com.prippi.stream

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.TrackSelectionParameters
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.exoplayer.dash.DashMediaSource
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.ui.PlayerView
import org.json.JSONObject

/**
 * Player nativo Media3. Consuma i dati di bridge.resolve():
 * url + manifest_type (hls/mpd) + headers + audio_language (traccia audio ITA).
 */
class PlayerActivity : ComponentActivity() {

    private var player: ExoPlayer? = null

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val url = intent.getStringExtra("url") ?: return finish()
        val manifest = intent.getStringExtra("manifest") ?: "hls"
        val audioLang = intent.getStringExtra("audio") ?: "it"
        val headers = parseHeaders(intent.getStringExtra("headers"))

        val view = PlayerView(this)
        setContentView(view)

        val http = DefaultHttpDataSource.Factory().apply {
            if (headers.isNotEmpty()) setDefaultRequestProperties(headers)
            setAllowCrossProtocolRedirects(true)
        }

        val source: MediaSource = when {
            manifest == "mpd" -> DashMediaSource.Factory(http)
                .createMediaSource(MediaItem.fromUri(Uri.parse(url)))
            else -> HlsMediaSource.Factory(http)
                .createMediaSource(MediaItem.fromUri(Uri.parse(url)))
        }

        player = ExoPlayer.Builder(this)
            .setMediaSourceFactory(DefaultMediaSourceFactory(http))
            .build().also { p ->
                view.player = p
                // preferenza traccia audio ITA (la stessa che su Kodi richiedeva l'hack del locale)
                p.trackSelectionParameters = TrackSelectionParameters.Builder(this)
                    .setPreferredAudioLanguage(audioLang)
                    .build()
                p.setMediaSource(source)
                p.playWhenReady = true
                p.prepare()
            }
    }

    private fun parseHeaders(s: String?): Map<String, String> {
        if (s.isNullOrBlank() || s == "{}") return emptyMap()
        return try {
            val o = JSONObject(s)
            o.keys().asSequence().associateWith { o.getString(it) }
        } catch (e: Exception) { emptyMap() }
    }

    override fun onStop() {
        super.onStop()
        player?.release(); player = null
    }
}
