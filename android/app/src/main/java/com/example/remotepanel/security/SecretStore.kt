package com.example.remotepanel.security

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Stores the shared HMAC secret + server URL inside EncryptedSharedPreferences.
 *
 * Throws [IllegalStateException] if the keystore is unavailable (the OS will
 * give us a working keystore on every device that supports API 26+).
 */
class SecretStore(context: Context) {

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

    var serverUrl: String?
        get() = prefs.getString(KEY_URL, null)
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_URL) else putString(KEY_URL, value)
            }.apply()
        }

    var secret: String?
        get() = prefs.getString(KEY_SECRET, null)
        set(value) {
            prefs.edit().apply {
                if (value == null) remove(KEY_SECRET) else putString(KEY_SECRET, value)
            }.apply()
        }

    val isConfigured: Boolean
        get() = !serverUrl.isNullOrBlank() && !secret.isNullOrBlank()

    fun clear() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val FILE_NAME = "panel_secure_prefs"
        private const val KEY_URL = "server_url"
        private const val KEY_SECRET = "shared_secret"
    }
}