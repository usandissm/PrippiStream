package com.prippi.stream

import android.os.Build
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.annotation.RequiresApi

/**
 * Keeps API-26 renderer callbacks out of the class loaded on Android 7.
 */
internal fun renderAwareWebViewClient(
    onRenderGone: (WebView) -> Unit,
): WebViewClient = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
    Api26RenderAwareWebViewClient(onRenderGone)
} else {
    WebViewClient()
}

@RequiresApi(Build.VERSION_CODES.O)
private class Api26RenderAwareWebViewClient(
    private val onRenderGone: (WebView) -> Unit,
) : WebViewClient() {
    override fun onRenderProcessGone(
        view: WebView,
        detail: RenderProcessGoneDetail,
    ): Boolean {
        onRenderGone(view)
        return true
    }
}
