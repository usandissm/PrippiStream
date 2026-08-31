package com.prippi.stream.diagnostics

import java.security.MessageDigest

internal const val MAX_DIAGNOSTIC_REPORT_BYTES = 700_000

internal enum class SendOutcome {
    SUCCESS,
    RETRYABLE_FAILURE,
    PERMANENT_FAILURE,
}

internal fun classifyDiagnosticHttpStatus(status: Int): SendOutcome = when (status) {
    in 200..299 -> SendOutcome.SUCCESS
    408, 425, 429 -> SendOutcome.RETRYABLE_FAILURE
    in 500..599 -> SendOutcome.RETRYABLE_FAILURE
    else -> SendOutcome.PERMANENT_FAILURE
}

/**
 * Keeps the newest part of a report while respecting the relay's UTF-8 byte
 * contract and never cutting a surrogate pair.
 */
internal fun truncateDiagnosticUtf8Tail(
    value: String,
    maxBytes: Int = MAX_DIAGNOSTIC_REPORT_BYTES,
): String {
    require(maxBytes >= 0)
    if (value.toByteArray(Charsets.UTF_8).size <= maxBytes) return value

    var low = 0
    var high = value.length
    while (low < high) {
        val middle = (low + high) / 2
        val start = value.safeUtf16Boundary(middle)
        if (value.substring(start).toByteArray(Charsets.UTF_8).size <= maxBytes) {
            high = middle
        } else {
            low = middle + 1
        }
    }
    var start = value.safeUtf16Boundary(low)
    var tail = value.substring(start)
    while (tail.toByteArray(Charsets.UTF_8).size > maxBytes && start < value.length) {
        start = value.safeUtf16Boundary(start + 1)
        tail = value.substring(start)
    }
    return tail
}

internal fun diagnosticReportId(report: String): String =
    MessageDigest.getInstance("SHA-256")
        .digest(report.toByteArray(Charsets.UTF_8))
        .joinToString(separator = "") { byte -> "%02x".format(byte) }

private fun String.safeUtf16Boundary(index: Int): Int {
    val safe = index.coerceIn(0, length)
    return if (
        safe in 1 until length &&
        this[safe].isLowSurrogate() &&
        this[safe - 1].isHighSurrogate()
    ) {
        safe + 1
    } else {
        safe
    }
}
