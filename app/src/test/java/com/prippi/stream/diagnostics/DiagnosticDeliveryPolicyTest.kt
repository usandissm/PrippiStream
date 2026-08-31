package com.prippi.stream.diagnostics

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DiagnosticDeliveryPolicyTest {
    @Test
    fun classifiesCompleteHttpMatrix() {
        listOf(200, 202, 204, 299).forEach {
            assertEquals(SendOutcome.SUCCESS, classifyDiagnosticHttpStatus(it))
        }
        listOf(408, 425, 429, 500, 502, 503, 599).forEach {
            assertEquals(SendOutcome.RETRYABLE_FAILURE, classifyDiagnosticHttpStatus(it))
        }
        listOf(0, 301, 400, 401, 403, 404, 409, 413, 422).forEach {
            assertEquals(SendOutcome.PERMANENT_FAILURE, classifyDiagnosticHttpStatus(it))
        }
    }

    @Test
    fun truncatesByUtf8BytesWithoutBreakingEmoji() {
        val input = "inizio-" + "🙂".repeat(20) + "-fine"
        val result = truncateDiagnosticUtf8Tail(input, maxBytes = 25)

        assertTrue(result.toByteArray(Charsets.UTF_8).size <= 25)
        assertTrue(result.endsWith("-fine"))
        assertFalse(result.contains('\uFFFD'))
    }

    @Test
    fun reportIdIsStableAndContentSensitive() {
        val first = diagnosticReportId("report sanitizzato")
        val repeated = diagnosticReportId("report sanitizzato")
        val changed = diagnosticReportId("report differente")

        assertEquals(64, first.length)
        assertEquals(first, repeated)
        assertFalse(first == changed)
    }
}
