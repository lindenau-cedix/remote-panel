package com.example.remotepanel.data

import kotlinx.serialization.Serializable

/**
 * One user-authored command entry.
 *
 * The id is what the server's whitelist matches against; the phone sends
 * only the id at run time (see [com.example.remotepanel.network.PanelApi.runCommand]).
 * name and description are display-only on the phone.
 */
@Serializable
data class UserCommand(
    val id: String,
    val name: String,
    val description: String,
)