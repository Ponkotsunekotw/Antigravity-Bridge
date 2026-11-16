package com.antigravity.bridge.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.antigravity.bridge.data.BridgeTask
import com.antigravity.bridge.data.ProgressEvent

@Composable
fun DashboardScreen(
    state: BridgeUiState,
    onApprove: (String, Boolean, String) -> Unit,
    onRefreshUsage: () -> Unit
) {
    val activeTasks = state.tasks.filter {
        it.status == "in_progress" || it.status == "waiting_approval" || it.status == "pending"
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            ConnectionBannerCard(state.isConnected, state.connectionMessage)
        }

        item {
            Text(
                text = "進行中與待處理任務 (${activeTasks.size})",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
        }

        if (activeTasks.isEmpty()) {
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = "目前沒有進行中的任務。可前往「下指令」分頁指派新工作。",
                        modifier = Modifier.padding(16.dp),
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
        } else {
            items(activeTasks, key = { it.id }) { task ->
                ActiveTaskCard(task = task, onApprove = onApprove)
            }
        }

        item {
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "即時進度回報",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold
            )
        }

        if (state.progressEvents.isEmpty()) {
            item {
                Text(
                    text = "尚無進度紀錄",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            items(state.progressEvents.take(40), key = { it.id }) { event ->
                ProgressEventRow(event = event)
            }
        }
    }
}

@Composable
private fun ConnectionBannerCard(isConnected: Boolean, message: String) {
    val containerColor = if (isConnected) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.errorContainer
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = containerColor)
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                text = if (isConnected) "伺服器連線中" else "伺服器未連線",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold
            )
            Text(text = message, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun TokenUsageCard(
    state: BridgeUiState,
    onRefreshUsage: () -> Unit
) {
    val usage = state.tokenUsage
    val cfg = state.modelConfig
    val quotaItems = state.quotaUsage.items
    val grouped = quotaItems.groupBy { it.group }

    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "剩餘用量儀表 (Usage)",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        text = "${cfg.model} • ${cfg.thinkingDepth}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                OutlinedButton(
                    onClick = onRefreshUsage,
                    enabled = !state.isBusy
                ) {
                    Text("手動更新")
                }
            }

            if (grouped.isEmpty()) {
                Text(
                    text = "尚無額度資訊",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                grouped.forEach { (groupName, items) ->
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(
                            text = groupName,
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.SemiBold
                        )
                        items.forEach { item ->
                            val ringColor = when {
                                item.percentLeft >= 40 -> Color(0xFF4CAF50)
                                item.percentLeft >= 15 -> Color(0xFFFFB300)
                                else -> Color(0xFFE53935)
                            }
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(text = item.label, style = MaterialTheme.typography.bodySmall)
                                    if (item.resetsIn.isNotBlank()) {
                                        Text(
                                            text = item.resetsIn,
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant
                                        )
                                    }
                                }
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        text = "${item.percentLeft}% left",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = ringColor,
                                        fontWeight = FontWeight.SemiBold
                                    )
                                    Spacer(modifier = Modifier.width(8.dp))
                                    CircularProgressIndicator(
                                        progress = { (item.percentLeft.coerceIn(0, 100)) / 100f },
                                        modifier = Modifier.size(18.dp),
                                        color = ringColor,
                                        trackColor = MaterialTheme.colorScheme.surfaceVariant,
                                        strokeWidth = 3.dp
                                    )
                                }
                            }
                        }
                    }
                }
            }

            HorizontalDivider()
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text("輸入：${usage.inputTokens}", style = MaterialTheme.typography.labelSmall)
                Text("輸出：${usage.outputTokens}", style = MaterialTheme.typography.labelSmall)
                Text("總計：${usage.totalTokens} (${usage.requestsCount} 次)", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

@Composable
private fun ActiveTaskCard(
    task: BridgeTask,
    onApprove: (String, Boolean, String) -> Unit
) {
    var note by remember { mutableStateOf("") }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = task.title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f)
                )
                val statusLabel = when (task.status) {
                    "waiting_approval" -> "待核准"
                    "in_progress" -> "執行中"
                    else -> "排隊中"
                }
                Text(
                    text = statusLabel,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary
                )
            }
            if (task.currentStep.isNotBlank()) {
                Text(
                    text = task.currentStep,
                    style = MaterialTheme.typography.bodySmall
                )
            }
            if (task.status == "waiting_approval") {
                Text(
                    text = "需要你的確認：${task.approvalPrompt ?: "請確認是否繼續"}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    fontWeight = FontWeight.SemiBold
                )
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("補充說明（選填）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = { onApprove(task.id, true, note) },
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("核准繼續")
                    }
                    OutlinedButton(
                        onClick = { onApprove(task.id, false, note) },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("拒絕 / 取消")
                    }
                }
            }
        }
    }
}

@Composable
private fun ProgressEventRow(event: ProgressEvent) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = "[${event.level.uppercase()}] ${event.agent}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(
                    text = formatLocalTimestamp(event.timestamp, includeDateAndSeconds = true),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(text = event.message, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
