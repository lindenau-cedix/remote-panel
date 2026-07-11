package com.example.remotepanel.network

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * Wire-format types returned by the server.
 *
 * The server returns arbitrary JSON in `stdout` / `stderr` so we keep them as
 * strings, not nested objects.
 */
@Serializable
data class HookResponse(
    val ok: Boolean,
    val stdout: String = "",
    val stderr: String = "",
    val exit_code: Int = 0,
    val duration_ms: Long = 0,
    val command_id: String = "",
    val error: String? = null,
)

/**
 * Result of a /hook call. Encodes the response + transport + http status.
 */
sealed class ApiResult {
    data class Success(val body: HookResponse, val httpStatus: Int) : ApiResult()
    data class Failure(val message: String, val httpStatus: Int, val body: HookResponse? = null) : ApiResult()
}
