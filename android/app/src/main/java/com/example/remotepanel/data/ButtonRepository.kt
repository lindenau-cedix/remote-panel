package com.example.remotepanel.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json

/**
 * Loads the dev button list from assets/buttons.json. Real source of truth is
 * the server's /buttons endpoint, but we ship a static list so the app can
 * render something even before the first request.
 */
class ButtonRepository(private val context: Context) {

    private val json = Json { ignoreUnknownKeys = true }

    suspend fun loadButtons(): List<ButtonConfig> = withContext(Dispatchers.IO) {
        val raw = context.assets.open(BUTTONS_ASSET).use { it.readBytes().toString(Charsets.UTF_8) }
        json.decodeFromString(
            kotlinx.serialization.builtins.ListSerializer(ButtonConfig.serializer()),
            raw,
        )
    }

    companion object {
        private const val BUTTONS_ASSET = "buttons.json"
    }
}
