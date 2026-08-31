package com.prippi.stream

import android.content.pm.PackageManager
import android.os.Build
import org.junit.Assert.assertEquals
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
}
