package com.prippi.stream

internal object LiveGuideFormatting {
    private val nextProgramme = Regex(
        """(?:\s*[•·|]\s*|\s+)(?=\bA[ \t]+seguire(?:[ \t]+\d{1,2}:\d{2}|[ \t]*[·•]))""",
        RegexOption.IGNORE_CASE,
    )

    fun normalize(text: String): String = text.replace(nextProgramme, "\n").trim()

    /** Keep the current programme compact, but give the next one its own line. */
    fun metadata(lines: List<String>): String {
        val clean = normalize(lines.joinToString("\n")).lineSequence()
            .map(String::trim).filter(String::isNotBlank).toList()
        val next = clean.indexOfFirst { it.startsWith("A seguire", ignoreCase = true) }
        if (next < 0) return clean.joinToString("  •  ")
        return listOf(clean.take(next).joinToString("  •  "),
            clean.drop(next).joinToString("\n")).filter(String::isNotBlank).joinToString("\n")
    }
}
