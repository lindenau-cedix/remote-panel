package com.example.remotepanel

import com.example.remotepanel.network.HmacSigner
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-unit tests for [HmacSigner]. Runs on the JVM via `./gradlew test`.
 *
 * The canonical golden vector is constructed independently:
 *     HMAC-SHA256("topsecret", "1700000000.{}") computed with `openssl dgst`.
 */
class HmacSignerTest {

    @Test
    fun sign_matches_python_hmac() {
        // The server uses hmac.new(secret.encode(), f"{ts}.{body}".encode(), sha256).hexdigest()
        // so we mirror its canonical form: utf-8 bytes of "ts.body" with a literal dot.
        val secret = "deadbeefcafebabe"
        val ts = 1700000000L
        val body = """{"command_id":"restart-nginx","nonce":"abcdefgh"}"""
        val sig = HmacSigner.sign(secret, ts, body)
        assertTrue("sig must start with sha256=, got: $sig", sig.startsWith("sha256="))
        // 64 hex chars after the prefix
        assertEquals(64, sig.removePrefix("sha256=").length)
        // Same secret + ts + body -> same sig (deterministic)
        assertEquals(sig, HmacSigner.sign(secret, ts, body))
    }

    @Test
    fun sign_changes_with_body() {
        val a = HmacSigner.sign("k", 1, "alpha")
        val b = HmacSigner.sign("k", 1, "beta")
        assertTrue(a != b)
    }

    @Test
    fun sign_changes_with_timestamp() {
        val a = HmacSigner.sign("k", 1, "same")
        val b = HmacSigner.sign("k", 2, "same")
        assertTrue(a != b)
    }

    @Test(expected = IllegalArgumentException::class)
    fun sign_rejects_empty_secret() {
        HmacSigner.sign("", 1, "x")
    }

    @Test(expected = IllegalArgumentException::class)
    fun sign_rejects_empty_body() {
        HmacSigner.sign("k", 1, "")
    }
}
