package com.prippi.stream

import org.junit.Assert.assertEquals
import org.junit.Test

class LiveGuideFormattingTest {
    @Test fun nextProgrammeStartsOnNewLine() {
        assertEquals("Adesso · 12:00–13:00  •  Film  •  S1 E2\nA seguire 13:00 · Notiziario",
            LiveGuideFormatting.metadata(listOf("Adesso · 12:00–13:00", "Film", "S1 E2", "A seguire 13:00 · Notiziario")))
    }
    @Test fun absentNextProgrammeDoesNotAddBlankLines() {
        assertEquals("Adesso  •  Film", LiveGuideFormatting.metadata(listOf(" Adesso ", "", "Film")))
        assertEquals("", LiveGuideFormatting.metadata(emptyList()))
    }
    @Test fun nextProgrammeAloneHasNoLeadingNewline() {
        assertEquals("a seguire 13:00 · News", LiveGuideFormatting.metadata(listOf("a seguire 13:00 · News")))
    }
}
