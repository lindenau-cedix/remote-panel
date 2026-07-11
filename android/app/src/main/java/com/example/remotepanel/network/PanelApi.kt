package com.example.remotepanel.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Thin OkHttp client that wraps the webhook server.
 *
 * Why OkHttp instead of Retrofit? We have one endpoint and three lines of
 * request body. A Ktor client would also work, but OkHttp is a single
 * 200-KB dep with no codegen and no coroutine adapter required.
 */
class PanelApi(
    private val serverUrl: String,
    private val secret: String,
    private val client: OkHttpClient = defaultClient(),
) {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    /**
     * Trigger a whitelisted command on the server.
     *
     * @param commandId id from the server's whitelist
     * @param nonce a fresh random string (>= 8 chars). Caller is responsible
     *              for uniqueness within the timestamp window.
     */
    suspend fun runCommand(commandId: String, nonce: String): ApiResult =
        withContext(Dispatchers.IO) {
            val body = json.encodeToString(
                HookRequestBody.serializer(),
                HookRequestBody(commandId, nonce),
            )
            val timestamp = System.currentTimeMillis() / 1000
            val signature = HmacSigner.sign(secret, timestamp, body)

            val url = serverUrl.trimEnd('/') + "/hook"
            val request = Request.Builder()
                .url(url)
                .post(body.toRequestBody(JSON))
                .header("X-Panel-Signature", signature)
                .header("X-Panel-Timestamp", timestamp.toString())
                .header("X-Panel-Nonce", nonce)
                .build()

            try {
                client.newCall(request).execute().use { resp ->
                    val raw = resp.body?.string() ?: ""
                    val parsed = runCatching { json.decodeFromString(HookResponse.serializer(), raw) }
                        .getOrElse { HookResponse(ok = false, error = "could not parse server response") }
                    if (resp.isSuccessful) {
                        ApiResult.Success(parsed, resp.code)
                    } else {
                        ApiResult.Failure(
                            parsed.error ?: "HTTP ${resp.code}",
                            resp.code,
                            parsed,
                        )
                    }
                }
            } catch (e: IOException) {
                ApiResult.Failure("network: ${e.message ?: e::class.simpleName}", -1)
            } catch (e: IllegalArgumentException) {
                ApiResult.Failure("invalid request: ${e.message}", -1)
            }
        }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }
}

@kotlinx.serialization.Serializable
internal data class HookRequestBody(val command_id: String, val nonce: String)
