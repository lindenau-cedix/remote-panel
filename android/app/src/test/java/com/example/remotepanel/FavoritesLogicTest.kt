package com.example.remotepanel

import com.example.remotepanel.data.FavoritesLogic
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Pure-unit tests for [FavoritesLogic]. The EncryptedSharedPreferences wrapper
 * (FavoritesStore) is not exercised here — that round-trip needs Robolectric
 * and is intentionally out of scope to keep the test surface JVM-only.
 */
class FavoritesLogicTest {

    @Test
    fun toggle_adds_when_absent() {
        val result = FavoritesLogic.toggle(emptySet(), "x")
        assertEquals(setOf("x"), result)
    }

    @Test
    fun toggle_removes_when_present() {
        val result = FavoritesLogic.toggle(setOf("x"), "x")
        assertEquals(emptySet<String>(), result)
    }

    @Test
    fun toggle_preserves_others() {
        val result = FavoritesLogic.toggle(setOf("x", "y"), "x")
        assertEquals(setOf("y"), result)
    }

    @Test
    fun toggle_is_idempotent_after_two_calls() {
        val start: Set<String> = setOf("a", "b")
        val once = FavoritesLogic.toggle(start, "x")
        val twice = FavoritesLogic.toggle(once, "x")
        assertEquals(start, twice)
    }

    @Test
    fun replace_swaps_the_set() {
        val result = FavoritesLogic.replace(setOf("a"), setOf("b", "c"))
        assertEquals(setOf("b", "c"), result)
    }
}