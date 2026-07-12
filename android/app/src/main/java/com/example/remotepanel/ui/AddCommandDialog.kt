package com.example.remotepanel.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.example.remotepanel.R
import com.example.remotepanel.data.UserCommand
import com.example.remotepanel.data.UserCommandLogic

/**
 * Modal dialog for authoring a single [UserCommand]. The id must match
 * [UserCommandLogic.ID_REGEX]; the server validates it again at run time
 * (see server/whitelist.py) but a client-side check gives faster feedback.
 */
@Composable
fun AddCommandDialog(
    onDismiss: () -> Unit,
    onSave: (UserCommand) -> Unit,
) {
    var id by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }

    val idTrimmed = id.trim()
    val nameTrimmed = name.trim()

    val idError: String? = when {
        idTrimmed.isEmpty() -> null  // don't shout on first keystroke
        !UserCommandLogic.isValidId(idTrimmed) -> stringResource(R.string.add_id_error)
        else -> null
    }
    val nameError: String? = if (name.isNotEmpty() && nameTrimmed.isEmpty()) {
        stringResource(R.string.add_name_error)
    } else null

    val isValid = idTrimmed.isNotEmpty() &&
        nameTrimmed.isNotEmpty() &&
        idError == null &&
        nameError == null

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.add_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = id,
                    onValueChange = { id = it },
                    label = { Text(stringResource(R.string.add_id_label)) },
                    singleLine = true,
                    isError = idError != null,
                    supportingText = idError?.let { { Text(it) } },
                    modifier = Modifier,
                )
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text(stringResource(R.string.add_name_label)) },
                    singleLine = true,
                    isError = nameError != null,
                    supportingText = nameError?.let { { Text(it) } },
                    modifier = Modifier,
                )
                OutlinedTextField(
                    value = description,
                    onValueChange = { description = it },
                    label = { Text(stringResource(R.string.add_description_label)) },
                    minLines = 2,
                    modifier = Modifier,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = isValid,
                onClick = {
                    onSave(
                        UserCommand(
                            id = idTrimmed,
                            name = nameTrimmed,
                            description = description.trim(),
                        ),
                    )
                },
            ) {
                Text(stringResource(R.string.add_save))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.add_cancel))
            }
        },
    )
}