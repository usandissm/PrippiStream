package com.prippi.stream

import android.annotation.SuppressLint
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import org.json.JSONArray

class TrailerActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private var television = false
    private var destroyed = false
    private var controlsOverlay: View? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val hideControls = Runnable {
        controlsOverlay?.animate()
            ?.alpha(0f)
            ?.setDuration(CONTROLS_FADE_MILLIS)
            ?.start()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val urls = runCatching {
            val array = JSONArray(intent.getStringExtra(EXTRA_URLS).orEmpty())
            (0 until array.length()).map(array::getString)
        }.getOrDefault(emptyList())
        val videoIds = urls.mapNotNull(::trailerYoutubeId).distinct()
        if (videoIds.isEmpty()) return finish()

        television = DeviceProfile.detect(this).isTelevision

        webView = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.allowContentAccess = false
            settings.allowFileAccess = false
            webViewClient = renderAwareWebViewClient { failedView ->
                android.util.Log.w(
                    "PrippiTrailer",
                    "Renderer trailer terminato; chiusura sicura",
                )
                destroyed = true
                (failedView.parent as? ViewGroup)?.removeView(failedView)
                failedView.destroy()
                finish()
            }
            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    android.util.Log.d("PrippiTrailer", message.message())
                    return true
                }
            }
        }
        if (television) {
            setContentView(createTelevisionPlayer(intent.getStringExtra(EXTRA_TITLE).orEmpty()))
        } else {
            setContentView(
                FrameLayout(this).apply {
                    addView(
                        webView,
                        FrameLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT,
                        ),
                    )
                    addPersistentBrandOverlay(this, television = false)
                },
            )
        }
        hideSystemUi()
        webView.loadDataWithBaseURL(
            "$TRAILER_PLAYER_ORIGIN/",
            trailerPlayerHtml(
                JSONArray(videoIds).toString(),
                showNativeControls = !television,
            ),
            "text/html",
            "UTF-8",
            null,
        )

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = finish()
        })
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if (!television) return super.onKeyDown(keyCode, event)
        showControls()
        if (event.repeatCount > 0) return true
        return when (keyCode) {
            KeyEvent.KEYCODE_DPAD_LEFT,
            KeyEvent.KEYCODE_MEDIA_REWIND,
            -> {
                runPlayerCommand("seekBy(-$SEEK_SECONDS)")
                true
            }
            KeyEvent.KEYCODE_DPAD_RIGHT,
            KeyEvent.KEYCODE_MEDIA_FAST_FORWARD,
            -> {
                runPlayerCommand("seekBy($SEEK_SECONDS)")
                true
            }
            KeyEvent.KEYCODE_DPAD_CENTER,
            KeyEvent.KEYCODE_ENTER,
            KeyEvent.KEYCODE_NUMPAD_ENTER,
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
            -> {
                runPlayerCommand("togglePlayback()")
                true
            }
            KeyEvent.KEYCODE_MEDIA_PLAY -> {
                runPlayerCommand("playTrailer()")
                true
            }
            KeyEvent.KEYCODE_MEDIA_PAUSE -> {
                runPlayerCommand("pauseTrailer()")
                true
            }
            KeyEvent.KEYCODE_MENU,
            KeyEvent.KEYCODE_DPAD_UP,
            KeyEvent.KEYCODE_DPAD_DOWN,
            -> true
            else -> super.onKeyDown(keyCode, event)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemUi()
    }

    override fun onPause() {
        if (::webView.isInitialized && !destroyed) {
            runPlayerCommand("pauseTrailer()")
            webView.onPause()
        }
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        if (::webView.isInitialized && !destroyed) {
            webView.onResume()
            hideSystemUi()
        }
    }

    override fun onDestroy() {
        mainHandler.removeCallbacksAndMessages(null)
        if (::webView.isInitialized && !destroyed) {
            destroyed = true
            webView.stopLoading()
            webView.loadUrl("about:blank")
            (webView.parent as? ViewGroup)?.removeView(webView)
            webView.removeAllViews()
            webView.destroy()
        }
        super.onDestroy()
    }

    private fun createTelevisionPlayer(title: String): View {
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            addView(
                webView,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        val overlay = FrameLayout(this).apply {
            isClickable = false
            isFocusable = false
        }
        overlay.addView(
            gradientView(
                intArrayOf(0xE6000000.toInt(), 0x99000000.toInt(), Color.TRANSPARENT),
            ),
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(140),
                Gravity.TOP,
            ),
        )
        overlay.addView(
            gradientView(
                intArrayOf(Color.TRANSPARENT, 0xB3000000.toInt(), 0xF2000000.toInt()),
            ),
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(130),
                Gravity.BOTTOM,
            ),
        )

        val back = televisionLabel("‹  Indietro", 18f).apply {
            isClickable = true
            setOnClickListener { finish() }
            setPadding(dp(10), dp(6), dp(10), dp(6))
        }
        overlay.addView(
            back,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP or Gravity.START,
            ).apply {
                leftMargin = dp(42)
                topMargin = dp(26)
            },
        )

        val safeTitle = title.trim().ifEmpty { "Trailer" }
        overlay.addView(
            televisionLabel(safeTitle, 25f).apply {
                maxLines = 1
                ellipsize = TextUtils.TruncateAt.END
            },
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.TOP,
            ).apply {
                leftMargin = dp(44)
                rightMargin = dp(44)
                topMargin = dp(74)
            },
        )
        overlay.addView(
            televisionLabel(
                "◀  −${SEEK_SECONDS}s     OK  Pausa/Riprendi     +${SEEK_SECONDS}s  ▶",
                16f,
            ).apply {
                gravity = Gravity.CENTER
                setTextColor(0xFFE6E6E6.toInt())
            },
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM,
            ).apply {
                leftMargin = dp(36)
                rightMargin = dp(36)
                bottomMargin = dp(34)
            },
        )
        root.addView(
            overlay,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        addPersistentBrandOverlay(root, television = true)
        controlsOverlay = overlay
        showControls()
        return root
    }

    private fun televisionLabel(text: String, sizeSp: Float) = TextView(this).apply {
        this.text = text
        textSize = sizeSp
        setTextColor(Color.WHITE)
        includeFontPadding = false
    }

    private fun gradientView(colors: IntArray) = View(this).apply {
        background = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, colors)
    }

    private fun showControls() {
        val overlay = controlsOverlay ?: return
        mainHandler.removeCallbacks(hideControls)
        overlay.animate().cancel()
        overlay.alpha = 1f
        mainHandler.postDelayed(hideControls, CONTROLS_VISIBLE_MILLIS)
    }

    private fun runPlayerCommand(command: String) {
        if (!::webView.isInitialized || destroyed) return
        webView.evaluateJavascript(
            "if (window.PrippiTrailer) { window.PrippiTrailer.$command; }",
            null,
        )
    }

    @Suppress("DEPRECATION")
    private fun hideSystemUi() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.run {
                hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                systemBarsBehavior =
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        }
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val SEEK_SECONDS = 10
        private const val CONTROLS_VISIBLE_MILLIS = 4_000L
        private const val CONTROLS_FADE_MILLIS = 220L
        const val EXTRA_URLS = "trailer_urls"
        const val EXTRA_TITLE = "trailer_title"
    }
}
