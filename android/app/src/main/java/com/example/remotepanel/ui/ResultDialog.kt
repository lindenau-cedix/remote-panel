package com.example.remotepanel.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.remotepanel.network.ApiResult
import com.example.remotepanel.network.HookResponse

@Composable
fun ResultDialog(result: ApiResult, onDismiss: () -> Unit) {
    val title = when (result) {
        is ApiResult.Success -> if (result.body.ok) "Success" else "Command failed"
        is ApiResult.Failure -> "Request failed"
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("Close") }
        },
        title = { Text(title) },
        text = {
            Column(
                modifier = Modifier
                    .verticalScroll(rememberScrollState())
                    .padding(4.dp),
            ) {
                when (result) {
                    is ApiResult.Success -> ResultBody(result.body)
                    is ApiResult.Failure -> {
                        Text("HTTP ${result.httpStatus}")
                        Spacer(Modifier.height(6.dp))
                        Text(result.message, color = MaterialTheme.colorScheme.error)
                        result.body?.let { ResultBody(it) }
                    }
                }
            }
        },
    )
}

@Composable
private fun ResultBody(body: HookResponse) {
    val ok = body.ok
    val accent = if (ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
    Text(
        "exit code: ${body.exit_code}",
        color = accent,
    )
    Text("duration: ${body.duration_ms} ms")
    if (body.stdout.isNotBlank()) {
        Spacer(Modifier.height(8.dp))
        Text("stdout:", style = MaterialTheme.typography.titleSmall)
        Text(body.stdout)
    }
    if (body.stderr.isNotBlank()) {
        Spacer(Modifier.height(8.dp))
        Text("stderr:", style = MaterialTheme.typography.titleSmall)
        Text(body.stderr, color = MaterialTheme.colorScheme.error)
    }
    body.error?.takeIf { it.isNotBlank() }?.let {
        Spacer(Modifier.height(8.dp))
        Text("error: $it", color = MaterialTheme.colorScheme.error)
    }
}
