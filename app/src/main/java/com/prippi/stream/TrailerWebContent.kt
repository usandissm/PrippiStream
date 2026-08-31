package com.prippi.stream

internal const val TRAILER_PLAYER_ORIGIN = "https://prippistream.app"

internal fun trailerYoutubeId(url: String): String? {
    val patterns = listOf(
        Regex("[?&]v=([A-Za-z0-9_-]{6,})"),
        Regex("youtu\\.be/([A-Za-z0-9_-]{6,})"),
        Regex("youtube(?:-nocookie)?\\.com/embed/([A-Za-z0-9_-]{6,})"),
    )
    return patterns.firstNotNullOfOrNull { it.find(url)?.groupValues?.getOrNull(1) }
}

internal fun trailerPlayerHtml(
    videoIdsJson: String,
    showNativeControls: Boolean,
    muted: Boolean = false,
) = """
    <!doctype html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
      <style>
        html,body,#player { width:100%; height:100%; margin:0; background:#000; overflow:hidden; }
        #status { position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
                  color:#ddd; background:#000; font:16px sans-serif; z-index:2; }
      </style>
    </head>
    <body>
      <div id="status">Caricamento trailer…</div>
      <div id="player"></div>
      <script>
        const ids = $videoIdsJson;
        let index = 0;
        let player;
        let playerCreated = false;
        let didAutoplay = false;
        window.__prippiTrailerPlaying = false;
        const status = document.getElementById('status');
        if (!window.__prippiTrailerApiRequested) {
          window.__prippiTrailerApiRequested = true;
          const api = document.createElement('script');
          api.src = 'https://www.youtube.com/iframe_api';
          document.head.appendChild(api);
        }

        function onYouTubeIframeAPIReady() {
          if (playerCreated) return;
          playerCreated = true;
          player = new YT.Player('player', {
            width: '100%', height: '100%', videoId: ids[index],
            host: 'https://www.youtube.com',
            playerVars: {
              autoplay: 0,
              controls: ${if (showNativeControls) 1 else 0},
              disablekb: ${if (showNativeControls) 0 else 1},
              fs: ${if (showNativeControls) 1 else 0},
              playsinline: 1, rel: 0,
              origin: '$TRAILER_PLAYER_ORIGIN', widget_referrer: '$TRAILER_PLAYER_ORIGIN'
            },
            events: {
              onReady: event => {
                status.style.display = 'none';
                if (${if (muted) "true" else "false"}) event.target.mute();
                if (!didAutoplay) {
                  didAutoplay = true;
                  event.target.playVideo();
                }
              },
              onStateChange: event => {
                if (event.data === YT.PlayerState.PLAYING) {
                  window.__prippiTrailerPlaying = true;
                  status.style.display = 'none';
                }
              },
              onError: event => tryNext(event.data)
            }
          });
        }

        function tryNext(errorCode) {
          console.log('iframe error=' + errorCode + ' candidate=' + (index + 1) + '/' + ids.length);
          index += 1;
          if (index < ids.length) {
            status.textContent = 'Provo un trailer alternativo…';
            status.style.display = 'flex';
            player.loadVideoById(ids[index]);
          } else {
            status.textContent = 'Trailer non riproducibile nel player integrato (' + errorCode + ')';
            status.style.display = 'flex';
          }
        }

        window.PrippiTrailer = {
          pauseTrailer() {
            if (player && player.pauseVideo) player.pauseVideo();
          },
          playTrailer() {
            if (player && player.playVideo) player.playVideo();
          },
          togglePlayback() {
            if (!player || !player.getPlayerState) return;
            const state = player.getPlayerState();
            if (state === YT.PlayerState.PLAYING) player.pauseVideo();
            else player.playVideo();
          },
          seekBy(seconds) {
            if (!player || !player.getCurrentTime || !player.seekTo) return;
            player.seekTo(Math.max(0, player.getCurrentTime() + seconds), true);
          }
        };
      </script>
    </body>
    </html>
""".trimIndent()
