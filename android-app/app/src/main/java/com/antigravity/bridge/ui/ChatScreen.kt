package com.antigravity.bridge.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.antigravity.bridge.data.ChatMessage
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

internal fun formatLocalTimestamp(isoTimestamp: String, includeDateAndSeconds: Boolean = false): String {
    if (isoTimestamp.isBlank()) return ""
    val zone = ZoneId.systemDefault()
    val zoned = runCatching {
        OffsetDateTime.parse(isoTimestamp).atZoneSameInstant(zone)
    }.recoverCatching {
        Instant.parse(isoTimestamp).atZone(zone)
    }.recoverCatching {
        LocalDateTime.parse(isoTimestamp).atZone(ZoneOffset.UTC).withZoneSameInstant(zone)
    }.getOrNull()

    if (zoned != null) {
        val pattern = when {
            includeDateAndSeconds -> "yyyy-MM-dd HH:mm:ss"
            zoned.toLocalDate() == LocalDate.now(zone) -> "HH:mm"
            else -> "MM/dd HH:mm"
        }
        return zoned.format(DateTimeFormatter.ofPattern(pattern))
    }

    return if (includeDateAndSeconds) {
        isoTimestamp.take(19).replace("T", " ")
    } else if (isoTimestamp.length >= 16) {
        isoTimestamp.substring(11, 16)
    } else {
        isoTimestamp
    }
}

@Composable
fun ChatScreen(
    state: BridgeUiState,
    onSendMessage: (String) -> Unit,
    onStageFile: (Uri) -> Unit,
    onClearStagedFile: () -> Unit,
    onDownloadAttachment: (attachmentPath: String, fileName: String) -> Unit,
    onUpdateModelConfig: (model: String, depth: String) -> Unit
) {
    var draft by remember { mutableStateOf("") }
    var showModelDialog by remember { mutableStateOf(false) }
    val listState = rememberLazyListState()
    val room = state.activeRoom
    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            onStageFile(uri)
        }
    }

    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) {
            listState.animateScrollToItem(state.messages.size - 1)
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        // Active project room header
        Surface(
            tonalElevation = 2.dp,
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = room?.name ?: "尚未選擇專案",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = room?.description?.ifBlank { "即時對話與成果摘要" } ?: "請先在「專案」分頁選擇聊天室",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                OutlinedButton(onClick = { showModelDialog = true }) {
                    Icon(Icons.Default.Tune, contentDescription = "模型與深度")
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("${state.modelConfig.model.substringAfterLast("-")} • ${state.modelConfig.thinkingDepth}")
                }
            }
        }

        // Message stream
        if (state.messages.isEmpty()) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(24.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "在下方輸入指令開始與「${room?.name ?: "專案"}」對話，AI 會直接回覆成果摘要。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                items(state.messages, key = { it.id }) { msg ->
                    ChatBubble(
                        message = msg,
                        isBusy = state.isBusy,
                        onDownloadAttachment = onDownloadAttachment
                    )
                }
            }
        }

        // Bottom input bar
        Surface(tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.fillMaxWidth()) {
                if (state.pendingAttachmentName != null) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        InputChip(
                            selected = true,
                            onClick = {},
                            label = { Text("待傳送附件：${state.pendingAttachmentName}") },
                            trailingIcon = {
                                IconButton(onClick = onClearStagedFile) {
                                    Icon(Icons.Default.Close, contentDescription = "移除附件")
                                }
                            }
                        )
                    }
                }
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 8.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconButton(
                        onClick = { filePicker.launch(arrayOf("*/*")) },
                        enabled = room != null && !state.isBusy
                    ) {
                        Icon(Icons.Default.AttachFile, contentDescription = "附加檔案")
                    }
                    OutlinedTextField(
                        value = draft,
                        onValueChange = { draft = it },
                        placeholder = {
                            Text(
                                if (state.pendingAttachmentName != null) "輸入檔案備註說明後一起傳送..."
                                else "輸入指令或問題..."
                            )
                        },
                        modifier = Modifier.weight(1f),
                        maxLines = 4
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    FilledIconButton(
                        onClick = {
                            val text = draft.trim()
                            if (text.isNotEmpty() || state.pendingAttachmentUri != null) {
                                onSendMessage(text)
                                draft = ""
                            }
                        },
                        enabled = (draft.isNotBlank() || state.pendingAttachmentUri != null) && room != null && !state.isBusy
                    ) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "送出")
                    }
                }
            }
        }
    }

    if (showModelDialog) {
        var selectedModel by remember(state.modelConfig.model) { mutableStateOf(state.modelConfig.model) }
        var selectedDepth by remember(state.modelConfig.thinkingDepth) { mutableStateOf(state.modelConfig.thinkingDepth) }
        val models = listOf(
            Triple("Gemini 4 Argon", "Gemini 4 Argon", true),
            Triple("Gemini 4 Hydrogen", "Gemini 4 Hydrogen", true),
            Triple("Orchestrator (Argon)", "Orchestrator (Argon)", true),
            Triple("Gemini 3.8 Flash", "Gemini 3.8 Flash", true),
            Triple("Claude Opus 5.5", "Claude Opus 5.5", true),
            Triple("Claude Sonnet 5.5", "Claude Sonnet 5.5", true),
            Triple("GPT-OSS 120B", "GPT-OSS 120B", true),
            Triple("Gemini 4 Carbon", "Gemini 4 Carbon (Unavailable)", false)
        )
        val depths = listOf("low" to "Low", "medium" to "Medium", "high" to "High")

        AlertDialog(
            onDismissRequest = { showModelDialog = false },
            title = { Text("選用模型與思考深度") },
            text = {
                Column(
                    modifier = Modifier.verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text("Antigravity 可用模型", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                    models.forEach { (id, label, enabled) ->
                        FilterChip(
                            selected = selectedModel == id,
                            onClick = { if (enabled) selectedModel = id },
                            enabled = enabled,
                            label = { Text(label) },
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                    Text("思考深度", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        depths.forEach { (id, label) ->
                            FilterChip(
                                selected = selectedDepth == id,
                                onClick = { selectedDepth = id },
                                label = { Text(label) }
                            )
                        }
                    }
                }
            },
            confirmButton = {
                Button(onClick = {
                    onUpdateModelConfig(selectedModel, selectedDepth)
                    showModelDialog = false
                }) {
                    Text("套用")
                }
            },
            dismissButton = {
                TextButton(onClick = { showModelDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}

@Composable
private fun ChatBubble(
    message: ChatMessage,
    isBusy: Boolean,
    onDownloadAttachment: (attachmentPath: String, fileName: String) -> Unit
) {
    val isUser = message.sender == "user"
    val alignment = if (isUser) Alignment.End else Alignment.Start
    val containerColor = if (isUser) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    val textColor = if (isUser) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = alignment
    ) {
        Surface(
            color = containerColor,
            shape = RoundedCornerShape(
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp
            ),
            modifier = Modifier.widthIn(max = 310.dp)
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = message.content,
                    color = textColor,
                    style = MaterialTheme.typography.bodyMedium
                )
                val attName = message.attachmentName
                val attPath = message.attachmentPath
                if (!isUser && !attName.isNullOrBlank() && !attPath.isNullOrBlank()) {
                    val isApk = attName.lowercase().endsWith(".apk")
                    Button(
                        onClick = { onDownloadAttachment(attPath, attName) },
                        enabled = !isBusy,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(if (isApk) "下載並安裝 APK" else "手動下載檔案")
                    }
                }
            }
        }
        val formattedTime = formatLocalTimestamp(message.timestamp)
        if (formattedTime.isNotBlank()) {
            Text(
                text = formattedTime,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp)
            )
        }
    }
}
