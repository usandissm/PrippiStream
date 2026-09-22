package com.prippi.stream

import android.content.pm.PackageManager
import android.os.Build
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AppUpdateManagerTest {
    @Suppress("DEPRECATION")
    @Test
    fun legacyAndroidQueriesLegacySignaturesOnly() {
        val flags = signatureQueryFlags(Build.VERSION_CODES.O_MR1)

        assertTrue(flags and PackageManager.GET_SIGNATURES != 0)
        assertEquals(0, flags and PackageManager.GET_SIGNING_CERTIFICATES)
    }

    @Suppress("DEPRECATION")
    @Test
    fun modernAndroidQueriesBothSignatureRepresentations() {
        val flags = signatureQueryFlags(Build.VERSION_CODES.P)

        assertTrue(flags and PackageManager.GET_SIGNATURES != 0)
        assertTrue(flags and PackageManager.GET_SIGNING_CERTIFICATES != 0)
    }

    @Test
    fun vendorRomFallsBackToLegacyCertificates() {
        assertEquals(
            listOf("legacy-cert"),
            preferSigningCertificates(emptyList(), listOf("legacy-cert")),
        )
    }

    @Test
    fun modernCertificatesRemainPreferred() {
        assertEquals(
            listOf("modern-cert"),
            preferSigningCertificates(listOf("modern-cert"), listOf("legacy-cert")),
        )
    }

    @Test
    fun updateProgressReportsRealFraction() {
        val progress = AppUpdateProgress(
            downloadedBytes = 25L,
            totalBytes = 100L,
            bytesPerSecond = 10L,
            remainingSeconds = 7L,
        )

        assertEquals(0.25f, progress.fraction!!, 0.0001f)
    }

    @Test
    fun updateProgressHandlesUnknownLengthAndClampsOverflow() {
        assertNull(AppUpdateProgress(25L, -1L, 0L, null).fraction)
        assertEquals(1f, AppUpdateProgress(125L, 100L, 0L, 0L).fraction!!, 0f)
    }
}
