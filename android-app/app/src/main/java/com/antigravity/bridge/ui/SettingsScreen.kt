package com.antigravity.bridge.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.antigravity.bridge.BuildConfig
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import org.json.JSONObject

@Composable
fun SettingsScreen(
    state: BridgeUiState,
    onTestConnection: (String, String) -> Unit,
    onSaveAndReconnect: (String, String) -> Unit,
    onThemeModeChange: (String) -> Unit,
    onCheckUpdate: () -> Unit,
    onInstallUpdate: (android.content.Context) -> Unit,
    onRefreshFcmToken: () -> Unit,
    onTestNotification: (android.content.Context) -> Unit
) {
    var url by remember(state.serverUrl) { mutableStateOf(state.serverUrl) }
    var token by remember(state.authToken) { mutableStateOf(state.authToken) }
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            text = "遠端伺服器連線設定",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold
        )

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it },
                    label = { Text("電腦端伺服器網址") },
                    placeholder = { Text("https://xxxx.trycloudflare.com") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("BRIDGE_TOKEN 驗證金鑰") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = { onTestConnection(url, token) },
                        enabled = !state.isBusy,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("測試連線")
                    }
                    Button(
                        onClick = { onSaveAndReconnect(url, token) },
                        enabled = !state.isBusy,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("儲存並重連")
                    }
                }
                OutlinedButton(
                    onClick = {
                        val scanner = GmsBarcodeScanning.getClient(context)
                        scanner.startScan()
                            .addOnSuccessListener { barcode ->
                                val raw = barcode.rawValue.orEmpty()
                                runCatching {
                                    val obj = JSONObject(raw)
                                    val scannedUrl = obj.optString("url", "").trim().trimEnd('/')
                                    val scannedTok = obj.optString("token", "").trim()
                                    if (scannedUrl.isNotBlank()) {
                                        url = scannedUrl
                                        if (scannedTok.isNotBlank()) token = scannedTok
                                        onSaveAndReconnect(url, token)
                                        Toast.makeText(context, "QR Code 配對成功！正在連線...", Toast.LENGTH_SHORT).show()
                                    } else {
                                        Toast.makeText(context, "QR Code 格式不符", Toast.LENGTH_SHORT).show()
                                    }
                                }.onFailure {
                                    Toast.makeText(context, "無法解析 QR Code 內容", Toast.LENGTH_SHORT).show()
                                }
                            }
                            .addOnFailureListener { e ->
                                Toast.makeText(context, "掃碼失敗：${e.message}", Toast.LENGTH_SHORT).show()
                            }
                    },
                    enabled = !state.isBusy,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("掃描 ServerHub QR Code 快速配對")
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("外觀主題（暗黑模式）", fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("system" to "跟隨系統", "light" to "淺色", "dark" to "暗黑").forEach { (mode, label) ->
                        FilterChip(
                            selected = state.themeMode == mode,
                            onClick = { onThemeModeChange(mode) },
                            label = { Text(label) }
                        )
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("App 版本與線上更新", fontWeight = FontWeight.Bold)
                Text(
                    text = "目前版本：v${BuildConfig.VERSION_NAME} (code ${BuildConfig.VERSION_CODE})",
                    style = MaterialTheme.typography.bodySmall
                )
                val release = state.latestRelease
                val hasNewer = release != null && release.available && release.versionCode > BuildConfig.VERSION_CODE
                if (release != null && release.available) {
                    Text(
                        text = if (hasNewer) {
                            "發現新版本：v${release.versionName} (code ${release.versionCode})\n${release.notes}"
                        } else {
                            "伺服器最新版本：v${release.versionName} (已最新)"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = if (hasNewer) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = onCheckUpdate,
                        enabled = !state.isBusy,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("檢查更新")
                    }
                    Button(
                        onClick = { onInstallUpdate(context) },
                        enabled = !state.isBusy && (release?.available == true),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text(if (hasNewer) "下載並更新" else "重新安裝")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text("FCM 推播與通知測試", fontWeight = FontWeight.Bold)
                Text(
                    text = if (state.fcmConfigured) {
                        when {
                            state.fcmTokenPreview != null -> "FCM 狀態：已開通 (${state.fcmTokenPreview})"
                            state.fcmError != null -> "FCM 取得失敗：${state.fcmError}"
                            else -> "FCM 狀態：已開通 (正在取得 Token...)"
                        }
                    } else {
                        "FCM 狀態：尚未開通（請將包含 com.antigravity.bridge 的 google-services.json 放入 android-app/app/ 並重新編譯），目前可先測試本地通知與鬧鐘。"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = if (state.fcmConfigured && state.fcmError == null) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = onRefreshFcmToken,
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("重新取得 Token")
                    }
                    OutlinedButton(
                        onClick = {
                            val tok = state.fcmToken
                            if (!tok.isNullOrBlank()) {
                                val clipboard = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                                clipboard.setPrimaryClip(android.content.ClipData.newPlainText("FCM Token", tok))
                                android.widget.Toast.makeText(context, "已複製 FCM Token", android.widget.Toast.LENGTH_SHORT).show()
                            }
                        },
                        enabled = !state.fcmToken.isNullOrBlank(),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("複製 FCM Token")
                    }
                }
                OutlinedButton(
                    onClick = { onTestNotification(context) },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("測試一般通知")
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text("使用提示", fontWeight = FontWeight.Bold)
                Text(
                    text = "1. 在電腦端啟動 server\\main.py 與 Cloudflare Tunnel。\n" +
                        "2. 將網址設為對應的 HTTPS 通道位址，並填入 .env 中的 BRIDGE_TOKEN。\n" +
                        "3. 推播通知改由 Firebase Cloud Messaging (FCM) 官方通道送達，不需開啟背景保活服務。",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
    }
}
