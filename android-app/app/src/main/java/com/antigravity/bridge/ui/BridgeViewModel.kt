package com.antigravity.bridge.ui

import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.provider.OpenableColumns
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.antigravity.bridge.BuildConfig
import com.antigravity.bridge.data.AppReleaseInfo
import com.antigravity.bridge.data.BridgeClient
import com.antigravity.bridge.data.BridgeTask
import com.antigravity.bridge.data.ChatMessage
import com.antigravity.bridge.data.ModelConfig
import com.antigravity.bridge.data.ProgressEvent
import com.antigravity.bridge.data.ProjectRoom
import com.antigravity.bridge.data.QuotaUsage
import com.antigravity.bridge.data.SettingsStore
import com.antigravity.bridge.data.TokenUsage
import com.antigravity.bridge.push.BridgeFirebaseMessagingService
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.WebSocket

data class BridgeUiState(
    val serverUrl: String = "",
    val authToken: String = "",
    val themeMode: String = "system",
    val isConnected: Boolean = false,
    val connectionMessage: String = "尚未連線",
    val tasks: List<BridgeTask> = emptyList(),
    val progressEvents: List<ProgressEvent> = emptyList(),
    val rooms: List<ProjectRoom> = emptyList(),
    val activeRoomId: String? = null,
    val messages: List<ChatMessage> = emptyList(),
    val pendingAttachmentUri: Uri? = null,
    val pendingAttachmentName: String? = null,
    val tokenUsage: TokenUsage = TokenUsage(),
    val modelConfig: ModelConfig = ModelConfig(),
    val quotaUsage: QuotaUsage = QuotaUsage(),
    val latestRelease: AppReleaseInfo? = null,
    val fcmConfigured: Boolean = false,
    val fcmToken: String? = null,
    val fcmTokenPreview: String? = null,
    val fcmError: String? = null,
    val isBusy: Boolean = false,
    val bannerMessage: String? = null
) {
    val activeRoom: ProjectRoom?
        get() = rooms.firstOrNull { it.id == activeRoomId } ?: rooms.firstOrNull()
}

class BridgeViewModel(application: Application) : AndroidViewModel(application) {
    private val settings = SettingsStore(application)
    private val client = BridgeClient()

    private val _uiState = MutableStateFlow(
        BridgeUiState(
            serverUrl = settings.serverUrl,
            authToken = settings.authToken,
            themeMode = settings.themeMode
        )
    )
    val uiState: StateFlow<BridgeUiState> = _uiState.asStateFlow()

    private var webSocket: WebSocket? = null
    private var reconnectJob: Job? = null

    private val urlSyncReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            val newUrl = intent?.getStringExtra(BridgeFirebaseMessagingService.EXTRA_SERVER_URL)
                ?.trim()?.trimEnd('/') ?: return
            if (newUrl.isNotBlank()) {
                settings.serverUrl = newUrl
                _uiState.update {
                    it.copy(
                        serverUrl = newUrl,
                        connectionMessage = "已自動同步新網址，連線中...",
                        bannerMessage = "已透過 FCM 自動更新伺服器網址"
                    )
                }
                connectWebSocket()
            }
        }
    }

    init {
        ContextCompat.registerReceiver(
            application,
            urlSyncReceiver,
            IntentFilter(BridgeFirebaseMessagingService.ACTION_SERVER_URL_UPDATED),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        refreshFcmStatus()
        connectWebSocket()
    }

    fun refreshFcmStatus() {
        val ctx = getApplication<Application>()
        val configured = BridgeFirebaseMessagingService.isFirebaseConfigured(ctx)
        val saved = BridgeFirebaseMessagingService.getSavedToken(ctx)
        _uiState.update {
            it.copy(
                fcmConfigured = configured,
                fcmToken = saved,
                fcmTokenPreview = saved?.let { t ->
                    if (t.length > 16) "${t.take(8)}...${t.takeLast(6)}" else t
                }
            )
        }
        if (configured) {
            BridgeFirebaseMessagingService.fetchAndSyncToken(ctx) { token, error ->
                _uiState.update {
                    it.copy(
                        fcmConfigured = true,
                        fcmToken = token ?: it.fcmToken,
                        fcmTokenPreview = (token ?: it.fcmToken)?.let { t ->
                            if (t.length > 16) "${t.take(8)}...${t.takeLast(6)}" else t
                        },
                        fcmError = error
                    )
                }
            }
        }
    }

    fun updateSettingsAndReconnect(url: String, token: String) {
        settings.serverUrl = url
        settings.authToken = token
        _uiState.update {
            it.copy(
                serverUrl = settings.serverUrl,
                authToken = settings.authToken,
                connectionMessage = "正在重新連線..."
            )
        }
        connectWebSocket()
    }

    fun testConnection(url: String, token: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true, bannerMessage = null) }
            val normalized = SettingsStore.normalizeUrl(url)
            val result = client.testConnection(normalized, token.trim())
            _uiState.update {
                it.copy(
                    isBusy = false,
                    bannerMessage = result.getOrElse { err -> "測試失敗：${err.message}" }
                )
            }
        }
    }

    fun connectWebSocket() {
        reconnectJob?.cancel()
        val previousSocket = webSocket
        webSocket = null
        previousSocket?.close(1000, "reconnecting")

        val baseUrl = settings.serverUrl
        val token = settings.authToken

        lateinit var currentSocket: WebSocket
        currentSocket = client.connectWebSocket(
            baseUrl = baseUrl,
            token = token,
            onConnected = {
                if (webSocket === currentSocket) {
                    refreshFcmStatus()
                    _uiState.update {
                        it.copy(isConnected = true, connectionMessage = "已即時連線")
                    }
                }
            },
            onSnapshot = { snapshot ->
                val previousById = _uiState.value.tasks.associateBy { it.id }
                snapshot.tasks.forEach { latest ->
                    val prev = previousById[latest.id]
                    if (prev != null && prev.status != latest.status) {
                        when (latest.status) {
                            "completed" -> BridgeNotificationHelper.notifyTaskStatus(
                                getApplication(),
                                "任務已完成：${latest.title}",
                                latest.currentStep.ifBlank { "點擊查看成果摘要" },
                                latest.id.hashCode()
                            )
                            "waiting_approval" -> BridgeNotificationHelper.notifyTaskStatus(
                                getApplication(),
                                "需要你的確認：${latest.title}",
                                latest.approvalPrompt ?: "請打開 App 核准或拒絕操作",
                                latest.id.hashCode()
                            )
                            "failed" -> BridgeNotificationHelper.notifyTaskStatus(
                                getApplication(),
                                "任務失敗：${latest.title}",
                                latest.currentStep.ifBlank { "請打開 App 查看錯誤詳情" },
                                latest.id.hashCode()
                            )
                        }
                    }
                }
                _uiState.update { state ->
                    val currentRoomId = state.activeRoomId
                        ?.takeIf { id -> snapshot.rooms.any { it.id == id } }
                        ?: snapshot.activeRoomId
                        ?: snapshot.rooms.firstOrNull()?.id
                    state.copy(
                        tasks = snapshot.tasks,
                        progressEvents = snapshot.progress.reversed(),
                        rooms = snapshot.rooms,
                        activeRoomId = currentRoomId,
                        messages = if (currentRoomId == snapshot.activeRoomId) snapshot.messages else state.messages,
                        tokenUsage = snapshot.tokenUsage,
                        modelConfig = snapshot.modelConfig,
                        quotaUsage = snapshot.quotaUsage
                    )
                }
                val selected = _uiState.value.activeRoomId
                if (selected != null && selected != snapshot.activeRoomId) {
                    loadMessagesForRoom(selected)
                }
            },
            onTaskUpdate = { updated ->
                val previous = _uiState.value.tasks.firstOrNull { it.id == updated.id }
                if (previous?.status != updated.status) {
                    when (updated.status) {
                        "completed" -> BridgeNotificationHelper.notifyTaskStatus(
                            getApplication(),
                            "任務已完成：${updated.title}",
                            updated.currentStep.ifBlank { "點擊查看成果摘要" },
                            updated.id.hashCode()
                        )
                        "waiting_approval" -> BridgeNotificationHelper.notifyTaskStatus(
                            getApplication(),
                            "需要你的確認：${updated.title}",
                            updated.approvalPrompt ?: "請打開 App 核准或拒絕操作",
                            updated.id.hashCode()
                        )
                        "failed" -> BridgeNotificationHelper.notifyTaskStatus(
                            getApplication(),
                            "任務失敗：${updated.title}",
                            updated.currentStep.ifBlank { "請打開 App 查看錯誤詳情" },
                            updated.id.hashCode()
                        )
                    }
                }
                _uiState.update { state ->
                    val next = state.tasks.filterNot { it.id == updated.id } + updated
                    state.copy(tasks = next.sortedByDescending { it.updatedAt })
                }
            },
            onProgressEvent = { event ->
                if (event.level == "success" && event.progress == 100 && event.taskId == null) {
                    BridgeNotificationHelper.notifyTaskStatus(
                        getApplication(),
                        "Antigravity 任務完成",
                        event.message,
                        event.id.hashCode()
                    )
                }
                _uiState.update { state ->
                    val next = (listOf(event) + state.progressEvents).take(150)
                    state.copy(progressEvents = next)
                }
            },
            onRoomUpdate = { updatedRoom ->
                _uiState.update { state ->
                    val next = state.rooms.filterNot { it.id == updatedRoom.id } + updatedRoom
                    state.copy(rooms = next.sortedByDescending { it.updatedAt })
                }
            },
            onChatMessage = { msg ->
                _uiState.update { state ->
                    if (msg.roomId == state.activeRoomId && state.messages.none { it.id == msg.id }) {
                        state.copy(messages = state.messages + msg)
                    } else {
                        state
                    }
                }
            },
            onAppUpdate = { release ->
                _uiState.update { state ->
                    val hasNewer = release.available && release.versionCode > BuildConfig.VERSION_CODE
                    state.copy(
                        latestRelease = release,
                        bannerMessage = if (hasNewer) "發現新版本 v${release.versionName}，可至「設定」更新" else state.bannerMessage
                    )
                }
            },
            onTokenUsage = { usage ->
                _uiState.update { it.copy(tokenUsage = usage) }
            },
            onModelConfig = { cfg ->
                _uiState.update { it.copy(modelConfig = cfg) }
            },
            onQuotaUsage = { quota ->
                _uiState.update { it.copy(quotaUsage = quota) }
            },
            onPushAlert = { _, title, body ->
                val ctx = getApplication<Application>()
                BridgeNotificationHelper.notifyTaskStatus(
                    ctx,
                    title,
                    body,
                    (System.currentTimeMillis() % Int.MAX_VALUE).toInt()
                )
            },
            onDisconnected = { reason ->
                if (webSocket === currentSocket) {
                    _uiState.update {
                        it.copy(isConnected = false, connectionMessage = "未連線：$reason")
                    }
                    scheduleReconnect()
                }
            }
        )
        webSocket = currentSocket
    }

    private fun scheduleReconnect() {
        reconnectJob?.cancel()
        reconnectJob = viewModelScope.launch {
            delay(4000)
            connectWebSocket()
        }
    }

    fun selectRoom(roomId: String) {
        _uiState.update { it.copy(activeRoomId = roomId, messages = emptyList()) }
        loadMessagesForRoom(roomId)
    }

    private fun loadMessagesForRoom(roomId: String) {
        viewModelScope.launch {
            val result = client.listMessages(settings.serverUrl, settings.authToken, roomId)
            result.onSuccess { msgs ->
                _uiState.update { state ->
                    if (state.activeRoomId == roomId) state.copy(messages = msgs) else state
                }
            }
        }
    }

    fun createRoom(name: String, description: String) {
        if (name.isBlank()) {
            _uiState.update { it.copy(bannerMessage = "請輸入專案名稱") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true) }
            val result = client.createRoom(settings.serverUrl, settings.authToken, name.trim(), description.trim())
            _uiState.update { state ->
                result.fold(
                    onSuccess = { room ->
                        state.copy(
                            isBusy = false,
                            activeRoomId = room.id,
                            messages = emptyList(),
                            bannerMessage = "已建立並切換到「${room.name}」聊天室"
                        )
                    },
                    onFailure = { err ->
                        state.copy(isBusy = false, bannerMessage = "建立失敗：${err.message}")
                    }
                )
            }
        }
    }

    fun stageAttachment(uri: Uri) {
        val resolver = getApplication<Application>().contentResolver
        val fileName = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(0) else null
        } ?: "attachment.bin"
        _uiState.update {
            it.copy(
                pendingAttachmentUri = uri,
                pendingAttachmentName = fileName
            )
        }
    }

    fun clearPendingAttachment() {
        _uiState.update {
            it.copy(
                pendingAttachmentUri = null,
                pendingAttachmentName = null
            )
        }
    }

    fun sendChatMessage(content: String) {
        val pendingUri = _uiState.value.pendingAttachmentUri
        if (pendingUri != null) {
            uploadAttachment(pendingUri, content.trim())
            return
        }
        val roomId = _uiState.value.activeRoom?.id
        if (roomId == null) {
            _uiState.update { it.copy(bannerMessage = "尚未選擇專案聊天室") }
            return
        }
        if (content.isBlank()) return

        viewModelScope.launch {
            val result = client.sendMessage(settings.serverUrl, settings.authToken, roomId, content.trim())
            result.onFailure { err ->
                _uiState.update { it.copy(bannerMessage = "傳送失敗：${err.message}") }
            }
        }
    }

    private fun uploadAttachment(uri: Uri, note: String) {
        val roomId = _uiState.value.activeRoom?.id
        if (roomId == null) {
            _uiState.update { it.copy(bannerMessage = "尚未選擇專案聊天室") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true) }
            val resolver = getApplication<Application>().contentResolver
            val fileName = _uiState.value.pendingAttachmentName ?: "attachment.bin"
            val mimeType = resolver.getType(uri) ?: "application/octet-stream"
            val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
            if (bytes == null) {
                _uiState.update { it.copy(isBusy = false, bannerMessage = "無法讀取選取的檔案") }
                return@launch
            }
            if (bytes.size > 25 * 1024 * 1024) {
                _uiState.update { it.copy(isBusy = false, bannerMessage = "檔案超過 25 MB 上限") }
                return@launch
            }
            val result = client.uploadFile(settings.serverUrl, settings.authToken, roomId, fileName, bytes, mimeType, note)
            _uiState.update { state ->
                result.fold(
                    onSuccess = {
                        state.copy(
                            isBusy = false,
                            pendingAttachmentUri = null,
                            pendingAttachmentName = null,
                            bannerMessage = "已送出附件與說明：$fileName"
                        )
                    },
                    onFailure = { err ->
                        state.copy(isBusy = false, bannerMessage = "上傳失敗：${err.message}")
                    }
                )
            }
        }
    }

    fun respondApproval(taskId: String, approved: Boolean, note: String = "") {
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true) }
            val result = client.sendApproval(
                baseUrl = settings.serverUrl,
                token = settings.authToken,
                taskId = taskId,
                approved = approved,
                note = note
            )
            _uiState.update { state ->
                state.copy(
                    isBusy = false,
                    bannerMessage = result.fold(
                        onSuccess = { if (approved) "已核准並通知繼續執行" else "已拒絕此操作" },
                        onFailure = { "送出失敗：${it.message}" }
                    )
                )
            }
        }
    }

    fun setThemeMode(mode: String) {
        settings.themeMode = mode
        _uiState.update { it.copy(themeMode = mode) }
    }

    fun updateModelConfig(model: String, thinkingDepth: String) {
        viewModelScope.launch {
            val result = client.updateModelConfig(settings.serverUrl, settings.authToken, model, thinkingDepth)
            _uiState.update { state ->
                result.fold(
                    onSuccess = { cfg -> state.copy(modelConfig = cfg, bannerMessage = "已切換模型：${cfg.model}（${cfg.thinkingDepth}）") },
                    onFailure = { err -> state.copy(bannerMessage = "更新模型設定失敗：${err.message}") }
                )
            }
        }
    }

    fun refreshUsageAndQuota() {
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true) }
            val quotaRes = client.fetchQuota(settings.serverUrl, settings.authToken)
            val usageRes = client.fetchTokenUsage(settings.serverUrl, settings.authToken)
            _uiState.update { state ->
                state.copy(
                    isBusy = false,
                    quotaUsage = quotaRes.getOrDefault(state.quotaUsage),
                    tokenUsage = usageRes.getOrDefault(state.tokenUsage),
                    bannerMessage = if (quotaRes.isSuccess && usageRes.isSuccess) {
                        "已同步最新用量與額度狀態"
                    } else {
                        "手動更新失敗：${quotaRes.exceptionOrNull()?.message ?: usageRes.exceptionOrNull()?.message}"
                    }
                )
            }
        }
    }

    fun checkForUpdate() {
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true) }
            val result = client.checkAppUpdate(settings.serverUrl, settings.authToken)
            _uiState.update { state ->
                result.fold(
                    onSuccess = { release ->
                        val msg = when {
                            !release.available -> "伺服器目前尚未發佈任何 APK 更新"
                            release.versionCode > BuildConfig.VERSION_CODE ->
                                "發現新版本 v${release.versionName} (${release.versionCode})"
                            else -> "目前已是最新版本 v${BuildConfig.VERSION_NAME}"
                        }
                        state.copy(isBusy = false, latestRelease = release, bannerMessage = msg)
                    },
                    onFailure = { err ->
                        state.copy(isBusy = false, bannerMessage = "檢查更新失敗：${err.message}")
                    }
                )
            }
        }
    }

    fun downloadAndHandleAttachment(context: Context, attachmentPath: String, fileName: String) {
        val url = settings.serverUrl
        if (url.isBlank()) {
            _uiState.update { it.copy(bannerMessage = "請先設定伺服器網址") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true, bannerMessage = "正在下載 $fileName...") }
            val dest = java.io.File(context.cacheDir, "downloads/$fileName")
            val result = client.downloadRoomAttachment(url, settings.authToken, attachmentPath, dest)
            _uiState.update { it.copy(isBusy = false) }
            result.fold(
                onSuccess = { file ->
                    if (fileName.lowercase().endsWith(".apk")) {
                        val uri = FileProvider.getUriForFile(
                            context,
                            "${context.packageName}.fileprovider",
                            file
                        )
                        val intent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(uri, "application/vnd.android.package-archive")
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                        context.startActivity(intent)
                        _uiState.update { it.copy(bannerMessage = "下載完成，正在開啟安裝程式") }
                    } else {
                        val savedOk = runCatching {
                            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                                val values = android.content.ContentValues().apply {
                                    put(android.provider.MediaStore.Downloads.DISPLAY_NAME, fileName)
                                    put(android.provider.MediaStore.Downloads.RELATIVE_PATH, android.os.Environment.DIRECTORY_DOWNLOADS + "/Antigravity")
                                }
                                val resolver = context.contentResolver
                                val outUri = resolver.insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                                    ?: error("無法建立下載檔案")
                                resolver.openOutputStream(outUri)?.use { out ->
                                    file.inputStream().use { inp -> inp.copyTo(out) }
                                }
                            } else {
                                @Suppress("DEPRECATION")
                                val dlDir = java.io.File(android.os.Environment.getExternalStoragePublicDirectory(android.os.Environment.DIRECTORY_DOWNLOADS), "Antigravity")
                                dlDir.mkdirs()
                                file.copyTo(java.io.File(dlDir, fileName), overwrite = true)
                            }
                            true
                        }.getOrDefault(false)
                        _uiState.update {
                            it.copy(
                                bannerMessage = if (savedOk) "已下載至 Download/Antigravity/$fileName" else "已下載至暫存區：${file.name}"
                            )
                        }
                    }
                },
                onFailure = { err ->
                    _uiState.update { it.copy(bannerMessage = "下載失敗：${err.message}") }
                }
            )
        }
    }

    fun downloadAndInstallUpdate(context: Context) {
        viewModelScope.launch {
            _uiState.update { it.copy(isBusy = true, bannerMessage = "正在下載新版 APK...") }
            val dest = java.io.File(context.cacheDir, "updates/app-update.apk")
            val result = client.downloadAppApk(settings.serverUrl, settings.authToken, dest)
            _uiState.update { it.copy(isBusy = false) }
            result.fold(
                onSuccess = { file ->
                    val uri = FileProvider.getUriForFile(
                        context,
                        "${context.packageName}.fileprovider",
                        file
                    )
                    val intent = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(uri, "application/vnd.android.package-archive")
                        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    context.startActivity(intent)
                },
                onFailure = { err ->
                    _uiState.update { it.copy(bannerMessage = "下載更新失敗：${err.message}") }
                }
            )
        }
    }

    fun clearBanner() {
        _uiState.update { it.copy(bannerMessage = null) }
    }

    override fun onCleared() {
        super.onCleared()
        runCatching { getApplication<Application>().unregisterReceiver(urlSyncReceiver) }
        reconnectJob?.cancel()
        val socket = webSocket
        webSocket = null
        socket?.close(1000, "closed")
    }
}
