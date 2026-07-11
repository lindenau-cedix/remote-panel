package com.example.remotepanel.data

import com.example.remotepanel.security.SecretStore

/**
 * Thin wrapper around [SecretStore] exposing flow-shaped reads for Compose.
 * Reads are blocking-by-design — they touch EncryptedSharedPreferences which
 * is fast in practice. Keep the secret out of logs.
 */
class SettingsStore(private val secrets: SecretStore) {
    fun serverUrl(): String = secrets.serverUrl.orEmpty()
    fun secret(): String = secrets.secret.orEmpty()
    fun isConfigured(): Boolean = secrets.isConfigured

    fun save(serverUrl: String, secret: String) {
        secrets.serverUrl = serverUrl.trim()
        secrets.secret = secret.trim()
    }

    fun clear() = secrets.clear()
}
