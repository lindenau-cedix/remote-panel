package com.example.remotepanel.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Save
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.example.remotepanel.R

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SetupScreen(
    initialUrl: String,
    initialSecret: String,
    onSave: (serverUrl: String, secret: String) -> Unit,
) {
    var serverUrl by remember { mutableStateOf(initialUrl) }
    var secret by remember { mutableStateOf(initialSecret) }
    var urlError by remember { mutableStateOf<String?>(null) }
    var secretError by remember { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text(stringResource(R.string.setup_title)) })
        }
    ) { inner ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(inner)
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "Enter the URL of your Remote Panel server and the shared " +
                    "secret you generated with `openssl rand -hex 32`."
            )
            OutlinedTextField(
                value = serverUrl,
                onValueChange = { serverUrl = it; urlError = null },
                label = { Text(stringResource(R.string.setup_server_label)) },
                singleLine = true,
                isError = urlError != null,
                supportingText = urlError?.let { { Text(it) } },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            OutlinedTextField(
                value = secret,
                onValueChange = { secret = it.trim(); secretError = null },
                label = { Text(stringResource(R.string.setup_secret_label)) },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                isError = secretError != null,
                supportingText = secretError?.let { { Text(it) } },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = {
                    val url = serverUrl.trim()
                    val urlOk = url.startsWith("https://") || url == "http://10.0.2.2"
                    val sOk = secret.length >= 16
                    urlError = if (!urlOk) "Must start with https:// (or http://10.0.2.2 for emulator)" else null
                    secretError = if (!sOk) "Min 16 chars" else null
                    if (urlOk && sOk) onSave(url, secret)
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Filled.Save, contentDescription = null)
                Spacer(Modifier.height(8.dp))
                Text(stringResource(R.string.setup_save))
            }
        }
    }
}
