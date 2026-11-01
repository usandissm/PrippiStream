package com.prippi.stream

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class LiveQueueStoreTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun largeEventRowTravelsAsSmallKeyAndRetainsOrder() {
        val row = JSONArray()
        repeat(350) { index ->
            row.put(JSONObject().put("title", "Evento $index")
                .put("plot", "x".repeat(4000))
                .put("event_fixture", JSONObject().put("teams", "A vs B"))
                .put("_app_live_row_items", JSONArray().put("must not be nested")))
        }
        val key = LiveQueueStore.put(temporary.root, row)
        assertEquals(36, key.length)
        assertTrue(row.toString().length > 1_000_000)
        val restored = LiveQueueStore.get(temporary.root, key)
        assertEquals(350, restored.length())
        repeat(350) { index ->
            assertEquals("Evento $index", restored.getJSONObject(index).getString("title"))
            assertEquals("A vs B", restored.getJSONObject(index).getJSONObject("event_fixture").getString("teams"))
            assertFalse(restored.getJSONObject(index).has("_app_live_row_items"))
        }
    }

    @Test fun missingInvalidAndCorruptQueuesAreSafe() {
        assertEquals(0, LiveQueueStore.get(temporary.root, "../../secret").length())
        assertEquals(0, LiveQueueStore.get(temporary.root, "00000000-0000-0000-0000-000000000000").length())
        val key = LiveQueueStore.put(temporary.root, JSONArray().put(JSONObject().put("title", "One")))
        java.io.File(temporary.root, "live-queues/$key.json").writeText("broken")
        assertEquals(0, LiveQueueStore.get(temporary.root, key).length())
        assertEquals("", LiveQueueStore.put(temporary.root, JSONArray()))
    }

    @Test fun separateLaunchesDoNotOverwriteEachOther() {
        val one = LiveQueueStore.put(temporary.root, JSONArray().put(JSONObject().put("title", "One")))
        val two = LiveQueueStore.put(temporary.root, JSONArray().put(JSONObject().put("title", "Two")))
        assertNotEquals(one, two)
        assertEquals("One", LiveQueueStore.get(temporary.root, one).getJSONObject(0).getString("title"))
        assertEquals("Two", LiveQueueStore.get(temporary.root, two).getJSONObject(0).getString("title"))
    }
}
