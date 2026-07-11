package com.example.remotepanel

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import com.example.remotepanel.data.ButtonConfig
import com.example.remotepanel.data.ButtonRepository
import com.example.remotepanel.data.SettingsStore
import com.example.remotepanel.network.ApiResult
import com.example.remotepanel.network.PanelApi
import com.example.remotepanel.security.SecretStore
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
        val buttons = ButtonRepository(applicationContext)

        setContent {
            RemotePanelTheme {
                AppContent(settings, buttons)
            }
        }
    }
}

@androidx.compose.runtime.Composable
private fun AppContent(settings: SettingsStore, buttons: ButtonRepository) {
    var isSetup by remember { mutableStateOf(settings.isConfigured()) }
    var buttonsState by remember { mutableStateOf<List<ButtonConfig>>(emptyList()) }
    var pendingConfirmation by remember { mutableStateOf<ButtonConfig?>(null) }
    var lastResult by remember { mutableStateOf<ApiResult?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        buttonsState = buttons.loadButtons()
    }

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

    PanelScreen(
        buttons = buttonsState,
        pendingConfirmation = pendingConfirmation,
        lastResult = lastResult,
        onButtonTapped = { btn -> pendingConfirmation = btn },
        onConfirm = {
            val btn = pendingConfirmation ?: return@PanelScreen
            val nonce = newNonce()
            val api = PanelApi(settings.serverUrl(), settings.secret())
            pendingConfirmation = null
            lastResult = null
            scope.launch {
                lastResult = api.runCommand(btn.id, nonce)
            }
        },
        onCancelConfirm = { pendingConfirmation = null },
        onDismissResult = { lastResult = null },
        onSettingsTapped = {
            settings.clear()
            isSetup = false
        },
    )
}

private fun newNonce(): String {
    val bytes = ByteArray(16)
    SecureRandom().nextBytes(bytes)
    return "n-" + bytes.joinToString("") { "%02x".format(it) }
}
