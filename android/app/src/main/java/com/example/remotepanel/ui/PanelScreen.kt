package com.example.remotepanel.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.remotepanel.data.ButtonConfig
import com.example.remotepanel.network.ApiResult

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PanelScreen(
    buttons: List<ButtonConfig>,
    pendingConfirmation: ButtonConfig?,
    lastResult: ApiResult?,
    onButtonTapped: (ButtonConfig) -> Unit,
    onConfirm: () -> Unit,
    onCancelConfirm: () -> Unit,
    onDismissResult: () -> Unit,
    onSettingsTapped: () -> Unit,
) {
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Remote Panel") },
                actions = {
                    IconButton(onClick = onSettingsTapped) {
                        Icon(Icons.Filled.Settings, contentDescription = "Settings")
                    }
                },
            )
        }
    ) { inner ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(inner)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Spacer(Modifier.height(4.dp))
            LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(items = buttons, key = { it.id }) { btn ->
                    ButtonCard(btn, onClick = { onButtonTapped(btn) })
                }
            }
        }
    }

    if (pendingConfirmation != null) {
        AlertDialog(
            onDismissRequest = onCancelConfirm,
            title = { Text("Run command?") },
            text = {
                Column {
                    Text(pendingConfirmation.name, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(4.dp))
                    Text(pendingConfirmation.description)
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "id: ${pendingConfirmation.id}",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = onConfirm) { Text("Run") }
            },
            dismissButton = {
                TextButton(onClick = onCancelConfirm) { Text("Cancel") }
            },
        )
    }

    if (lastResult != null) {
        ResultDialog(lastResult, onDismissResult)
    }
}

@Composable
private fun ButtonCard(btn: ButtonConfig, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(),
        elevation = CardDefaults.elevatedCardElevation(),
        onClick = onClick,
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(btn.name, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(btn.description, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
