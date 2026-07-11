package com.example.remotepanel.data

import kotlinx.serialization.Serializable

/**
 * Visible-on-the-phone description of a button. The full argv is never
 * bundled into the APK; it lives only on the server.
 */
@Serializable
data class ButtonConfig(
    val id: String,
    val name: String,
    val description: String,
)
