package com.example.remotepanel.network

import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * HMAC-SHA256 over `timestamp + "." + body`. Trivially small but kept here so
 * tests can exercise it without spinning up the rest of the app.
 */
object HmacSigner {

    private const val ALGO = "HmacSHA256"

    fun sign(secret: String, timestampSeconds: Long, body: String): String {
        require(secret.isNotEmpty()) { "secret must not be empty" }
        require(body.isNotEmpty()) { "body must not be empty" }
        val mac = Mac.getInstance(ALGO)
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), ALGO))
        val data = "$timestampSeconds.$body".toByteArray(Charsets.UTF_8)
        val raw = mac.doFinal(data)
        return "sha256=" + raw.toHex()
    }

    private fun ByteArray.toHex(): String {
        val sb = StringBuilder(size * 2)
        for (b in this) {
            val v = b.toInt() and 0xFF
            sb.append(HEX_CHARS[v ushr 4])
            sb.append(HEX_CHARS[v and 0x0F])
        }
        return sb.toString()
    }

    private val HEX_CHARS = "0123456789abcdef".toCharArray()

    // Exposed for unit tests.
    fun sha256HexOf(input: String): String {
        val md = MessageDigest.getInstance("SHA-256")
        val raw = md.digest(input.toByteArray(Charsets.UTF_8))
        return raw.toHex()
    }
}
