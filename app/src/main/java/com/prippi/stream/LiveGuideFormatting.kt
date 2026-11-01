package com.prippi.stream

internal object LiveGuideFormatting {
    /** Keep the current programme compact, but give the next one its own line. */
    fun metadata(lines: List<String>): String {
        val clean = lines.map(String::trim).filter(String::isNotBlank)
        val next = clean.indexOfFirst { it.startsWith("A seguire", ignoreCase = true) }
        if (next < 0) return clean.joinToString("  •  ")
        return listOf(clean.take(next).joinToString("  •  "),
            clean.drop(next).joinToString("\n")).filter(String::isNotBlank).joinToString("\n")
    }
}
