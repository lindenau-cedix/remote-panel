package com.example.remotepanel

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import com.example.remotepanel.data.SettingsStore
import com.example.remotepanel.data.UserCommand
import com.example.remotepanel.data.UserCommandsStore
import com.example.remotepanel.network.ApiResult
import com.example.remotepanel.network.PanelApi
import com.example.remotepanel.security.SecretStore
import com.example.remotepanel.ui.AddCommandDialog
import com.example.remotepanel.ui.ManageCommandsScreen
import com.example.remotepanel.ui.PanelScreen
import com.example.remotepanel.ui.SetupScreen
import com.example.remotepanel.ui.theme.RemotePanelTheme
import kotlinx.coroutines.launch
import java.security.SecureRandom

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val secretStore = SecretStore(applicationContext)
        val settings = SettingsStore(secretStore)
        val commandsStore = UserCommandsStore(applicationContext)

        setContent {
            RemotePanelTheme {
                AppContent(settings, commandsStore)
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun AppContent(
    settings: SettingsStore,
    commandsStore: UserCommandsStore,
) {
    var isSetup by remember { mutableStateOf(settings.isConfigured()) }
    var pendingConfirmation by remember { mutableStateOf<UserCommand?>(null) }
    var lastResult by remember { mutableStateOf<ApiResult?>(null) }
    var showManage by remember { mutableStateOf(false) }
    var showAddDialog by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val commands by commandsStore.commands.collectAsState()

    if (!isSetup) {
        SetupScreen(
            initialUrl = settings.serverUrl(),
            initialSecret = settings.secret(),
            onSave = { url, secret ->
                settings.save(url, secret)
                isSetup = true
            },
        )
        return
    }

    if (showManage) {
        ManageCommandsScreen(
            commands = commands,
            onAdd = { showAddDialog = true },
            onDelete = { id -> scope.launch { commandsStore.delete(id) } },
            onBack = { showManage = false },
        )
    } else {
        PanelScreen(
            commands = commands,
            pendingConfirmation = pendingConfirmation,
            lastResult = lastResult,
            onCommandTapped = { cmd -> pendingConfirmation = cmd },
            onConfirm = {
                val cmd = pendingConfirmation ?: return@PanelScreen
                val nonce = newNonce()
                val api = PanelApi(settings.serverUrl(), settings.secret())
                pendingConfirmation = null
                lastResult = null
                scope.launch {
                    lastResult = api.runCommand(cmd.id, nonce)
                }
            },
            onCancelConfirm = { pendingConfirmation = null },
            onDismissResult = { lastResult = null },
            onSettingsTapped = {
                settings.clear()
                isSetup = false
            },
            onManageCommands = { showManage = true },
            onAddCommand = { showAddDialog = true },
        )
    }

    // Hoisted dialog overlay — works from both PanelScreen (empty-state CTA)
    // and ManageCommandsScreen (FAB). State is app-level, not screen-level.
    if (showAddDialog) {
        AddCommandDialog(
            onDismiss = { showAddDialog = false },
            onSave = { cmd ->
                scope.launch {
                    commandsStore.add(cmd)
                    showAddDialog = false
                }
            },
        )
    }
}

private fun newNonce(): String {
    val bytes = ByteArray(16)
    SecureRandom().nextBytes(bytes)
    return "n-" + bytes.joinToString("") { "%02x".format(it) }
}