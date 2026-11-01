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
    @Test fun alreadyFlattenedGuideIsSeparatedToo() {
        assertEquals("Adesso · 12:00 Film\nA seguire 13:00 · News",
            LiveGuideFormatting.metadata(listOf("Adesso · 12:00 Film A seguire 13:00 · News")))
        assertEquals("Film\nA seguire · News", LiveGuideFormatting.normalize("Film • A seguire · News"))
    }
    @Test fun normalizationDoesNotAccumulateBlankLines() {
        val guide = "Adesso\nFilm\nA seguire 13:00 · News"
        assertEquals(guide, LiveGuideFormatting.normalize(LiveGuideFormatting.normalize(guide)))
    }
    @Test fun nativeLiveModelKeepsOriginalGuideLines() {
        val plot = "IN ONDA · 12:00\nFilm &amp; altro\nA seguire 13:00 · News"
        val item = ContentItem.fromJson(org.json.JSONObject().put("title", "Canale")
            .put("_app_live", true).put("infoLabels", org.json.JSONObject().put("plot", plot)))
        assertEquals("IN ONDA · 12:00\nFilm & altro\nA seguire 13:00 · News", item.plot)
    }
}
