package com.example.remotepanel.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Persists the user's authored commands (id + name + description triples).
 *
 * Lives in its own EncryptedSharedPreferences file (`user_commands_secure_prefs`)
 * — separate from [com.example.remotepanel.security.SecretStore]'s file so
 * `SecretStore.clear()` (which wipes its whole prefs file) cannot destroy
 * the user's authored list when the connection is reset.
 *
 * Encryption here is "be consistent with the rest of the persisted state,"
 * not a security boundary — the server whitelist is the only thing that
 * authorizes argv. The user can write any id locally; the server will
 * reject unknown ids at `/hook` time.
 */
class UserCommandsStore(context: Context) {

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

    private val json = Json { ignoreUnknownKeys = true }

    // Seeded empty so the UI has a value before the first prefs read completes.
    // Lazily populated by [ensureLoaded].
    private val _commands = MutableStateFlow<List<UserCommand>>(emptyList())
    val commands: StateFlow<List<UserCommand>> = _commands.asStateFlow()

    private var loaded = false

    private fun ensureLoaded() {
        if (loaded) return
        loaded = true
        val raw = prefs.getString(KEY_COMMANDS, null).orEmpty()
        // TODO: if JSON corruption becomes a real concern, surface a
        // recovery event instead of silently dropping the user's list.
        val parsed = if (raw.isBlank()) emptyList()
            else runCatching {
                json.decodeFromString(
                    ListSerializer(UserCommand.serializer()),
                    raw,
                )
            }.getOrElse { emptyList() }
        _commands.value = parsed
    }

    /** Synchronous read of the current list. Cheap; the StateFlow already mirrors it. */
    fun list(): List<UserCommand> {
        ensureLoaded()
        return _commands.value
    }

    suspend fun add(command: UserCommand) {
        ensureLoaded()
        val next = UserCommandLogic.append(_commands.value, command)
        persist(next)
    }

    suspend fun delete(id: String) {
        ensureLoaded()
        val next = UserCommandLogic.removeById(_commands.value, id)
        persist(next)
    }

    private fun persist(next: List<UserCommand>) {
        val raw = json.encodeToString(
            ListSerializer(UserCommand.serializer()),
            next,
        )
        prefs.edit().putString(KEY_COMMANDS, raw).apply()
        _commands.value = next
    }

    companion object {
        private const val FILE_NAME = "user_commands_secure_prefs"
        private const val KEY_COMMANDS = "user_commands_json"
    }
}

/**
 * Pure-Kotlin math behind [UserCommandsStore]. Kept separate from the
 * EncryptedSharedPreferences wrapper so the validation / append / remove
 * rules can be unit-tested on the JVM with plain JUnit 4 (no Robolectric).
 */
object UserCommandLogic {

    /** Matches the server-side ID_PATTERN in server/whitelist.py. */
    val ID_REGEX: Regex = Regex("^[a-z0-9][a-z0-9-]{0,63}$")

    fun isValidId(id: String): Boolean = ID_REGEX.matches(id)

    /** Append at end. Reject duplicate id silently (returns input unchanged). */
    fun append(current: List<UserCommand>, command: UserCommand): List<UserCommand> {
        if (current.any { it.id == command.id }) return current
        return current + command
    }

    fun removeById(current: List<UserCommand>, id: String): List<UserCommand> =
        current.filterNot { it.id == id }
}