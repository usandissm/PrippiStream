package com.prippi.stream

import org.json.JSONObject

data class ChannelInfo(
    val id: String,
    val title: String,
    val thumbnail: String,
    val fanart: String,
    val categories: List<String>,
    val languages: List<String>,
    val hasSettings: Boolean,
) {
    companion object {
        fun fromJson(json: JSONObject): ChannelInfo = ChannelInfo(
            id = json.optString("id"),
            title = cleanKodiText(json.optString("title")),
            thumbnail = json.optString("thumbnail"),
            fanart = json.optString("fanart"),
            categories = json.optJSONArray("categories")?.let { array ->
                (0 until array.length()).map { array.optString(it) }
            }.orEmpty(),
            languages = json.optJSONArray("language")?.let { array ->
                (0 until array.length()).map { array.optString(it) }
            }.orEmpty(),
            hasSettings = json.optBoolean("has_settings"),
        )
    }
}

data class AppSetting(
    val id: String,
    val channel: String,
    val label: String,
    val type: String,
    val value: String,
    val defaultValue: String,
    val values: List<String>,
    val range: List<Int>,
    val enabled: Boolean,
) {
    val boolValue: Boolean get() = value.equals("true", true) || value == "1"

    companion object {
        fun fromJson(json: JSONObject): AppSetting = AppSetting(
            id = json.optString("id"),
            channel = json.optString("channel"),
            label = json.optString("label").ifBlank { json.optString("id") },
            type = json.optString("type", "text"),
            value = json.opt("value")?.toString().orEmpty(),
            defaultValue = json.opt("default")?.toString().orEmpty(),
            values = json.optJSONArray("values")?.let { array ->
                (0 until array.length()).map { array.optString(it) }
            }.orEmpty(),
            range = json.optJSONArray("range")?.let { array ->
                (0 until array.length()).mapNotNull { array.optString(it).toIntOrNull() }
            }.orEmpty(),
            enabled = json.optBoolean("enabled", true),
        )
    }
}

data class SettingCategory(
    val label: String,
    val settings: List<AppSetting>,
) {
    companion object {
        fun fromJson(json: JSONObject): SettingCategory {
            val array = json.optJSONArray("settings")
            return SettingCategory(
                label = json.optString("label"),
                settings = if (array == null) emptyList() else
                    (0 until array.length()).map { AppSetting.fromJson(array.getJSONObject(it)) },
            )
        }
    }
}

data class BrowseLevel(
    val title: String,
    val channel: String,
    val items: List<ContentItem>,
)
