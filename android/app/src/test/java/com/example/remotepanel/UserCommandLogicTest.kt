package com.example.remotepanel

import com.example.remotepanel.data.UserCommand
import com.example.remotepanel.data.UserCommandLogic
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-unit tests for [UserCommandLogic]. The EncryptedSharedPreferences
 * wrapper (UserCommandsStore) is not exercised here — that round-trip needs
 * Robolectric and is intentionally out of scope to keep the test surface
 * JVM-only.
 */
class UserCommandLogicTest {

    @Test
    fun id_regex_accepts_simple_kebab() {
        assertTrue(UserCommandLogic.isValidId("restart-nginx"))
        assertTrue(UserCommandLogic.isValidId("a"))
        assertTrue(UserCommandLogic.isValidId("a1"))
        assertTrue(UserCommandLogic.isValidId("1a"))
        assertTrue(UserCommandLogic.isValidId("foo-bar-baz"))
    }

    @Test
    fun id_regex_rejects_uppercase_underscores_spaces() {
        assertFalse(UserCommandLogic.isValidId(""))
        assertFalse(UserCommandLogic.isValidId("Restart-Nginx"))
        assertFalse(UserCommandLogic.isValidId("restart_nginx"))
        assertFalse(UserCommandLogic.isValidId("restart nginx"))
        assertFalse(UserCommandLogic.isValidId("-leading-dash"))
        assertFalse(UserCommandLogic.isValidId(".dot"))
        assertFalse(UserCommandLogic.isValidId("a".repeat(65)))
    }

    @Test
    fun id_regex_accepts_64_chars() {
        assertTrue(UserCommandLogic.isValidId("a".repeat(64)))
    }

    @Test
    fun append_puts_new_at_end() {
        val start = listOf(UserCommand("a", "A", ""))
        val next = UserCommandLogic.append(start, UserCommand("b", "B", ""))
        assertEquals(listOf("a", "b"), next.map { it.id })
    }

    @Test
    fun append_rejects_duplicate_id() {
        val start = listOf(UserCommand("a", "A", "first"))
        val next = UserCommandLogic.append(start, UserCommand("a", "A2", "second"))
        assertEquals(start, next)
    }

    @Test
    fun append_preserves_order_of_existing() {
        val start = listOf(
            UserCommand("a", "A", ""),
            UserCommand("b", "B", ""),
            UserCommand("c", "C", ""),
        )
        val next = UserCommandLogic.append(start, UserCommand("d", "D", ""))
        assertEquals(listOf("a", "b", "c", "d"), next.map { it.id })
    }

    @Test
    fun removeById_drops_matching_only() {
        val start = listOf(
            UserCommand("a", "A", ""),
            UserCommand("b", "B", ""),
            UserCommand("c", "C", ""),
        )
        val next = UserCommandLogic.removeById(start, "b")
        assertEquals(listOf("a", "c"), next.map { it.id })
    }

    @Test
    fun removeById_is_noop_when_absent() {
        val start = listOf(UserCommand("a", "A", ""))
        val next = UserCommandLogic.removeById(start, "z")
        assertEquals(start, next)
    }
}