package com.example.remotepanel.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Persists the user's curated set of favorite command ids.
 *
 * Lives in its own EncryptedSharedPreferences file (`favorites_secure_prefs`)
 * — separate from [com.example.remotepanel.security.SecretStore]'s file so
 * that `SecretStore.clear()` (which wipes its whole prefs file) cannot
 * destroy the favorites list when the user resets their connection.
 *
 * Favorites ids are not secrets. Encryption here is "be consistent with the
 * rest of the persisted state," not a security boundary — the server
 * whitelist is the only thing that authorizes argv.
 */
class FavoritesStore(context: Context) {

    private val prefs by lazy {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    // Seeded empty so the UI has a value before the first prefs read on
    // Dispatchers.IO completes. Lazily populated by [ensureLoaded].
    private val _favorites = MutableStateFlow<Set<String>>(emptySet())
    val favorites: StateFlow<Set<String>> = _favorites.asStateFlow()

    private var loaded = false

    private fun ensureLoaded() {
        if (loaded) return
        loaded = true
        val stored = prefs.getStringSet(KEY_IDS, null)
        // Defensive copy into LinkedHashSet for stable iteration; dedup at
        // write time is handled by putStringSet.
        val initial = stored?.let { LinkedHashSet(it) } ?: emptySet()
        _favorites.value = initial
    }

    suspend fun toggle(id: String) {
        ensureLoaded()
        val next = FavoritesLogic.toggle(_favorites.value, id)
        persist(next)
    }

    suspend fun setAll(ids: Set<String>) {
        ensureLoaded()
        val next = FavoritesLogic.replace(_favorites.value, ids)
        persist(next)
    }

    private fun persist(next: Set<String>) {
        prefs.edit().putStringSet(KEY_IDS, next).apply()
        _favorites.value = next
    }

    companion object {
        private const val FILE_NAME = "favorites_secure_prefs"
        private const val KEY_IDS = "favorite_ids"
    }
}

/**
 * Pure-Kotlin math behind [FavoritesStore]. Kept separate from the
 * EncryptedSharedPreferences wrapper so the toggle / replace rules can be
 * unit-tested on the JVM with plain JUnit 4 (no Robolectric).
 */
object FavoritesLogic {
    fun toggle(current: Set<String>, id: String): Set<String> {
        val next = LinkedHashSet(current)
        if (!next.add(id)) next.remove(id)
        return next
    }

    fun replace(current: Set<String>, ids: Set<String>): Set<String> =
        LinkedHashSet(ids)
}