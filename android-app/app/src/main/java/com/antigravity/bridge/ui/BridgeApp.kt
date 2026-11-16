package com.antigravity.bridge.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.antigravity.bridge.theme.AntigravityBridgeTheme

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BridgeApp(vm: BridgeViewModel = viewModel()) {
    val state by vm.uiState.collectAsState()
    val context = androidx.compose.ui.platform.LocalContext.current
    var selectedTab by remember { mutableIntStateOf(0) }
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(state.bannerMessage) {
        val msg = state.bannerMessage
        if (msg != null) {
            snackbarHostState.showSnackbar(msg)
            vm.clearBanner()
        }
    }

    val tabs = listOf(
        "進度" to Icons.Default.Dashboard,
        "聊天室" to Icons.AutoMirrored.Filled.Chat,
        "專案" to Icons.Default.Forum,
        "設定" to Icons.Default.Settings
    )

    val isDark = when (state.themeMode) {
        "dark" -> true
        "light" -> false
        else -> isSystemInDarkTheme()
    }

    AntigravityBridgeTheme(darkTheme = isDark) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("Antigravity 遠端指揮") }
                )
            },
            snackbarHost = { SnackbarHost(snackbarHostState) },
            bottomBar = {
                NavigationBar {
                    tabs.forEachIndexed { index, (label, icon) ->
                        NavigationBarItem(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            icon = { Icon(icon, contentDescription = label) },
                            label = { Text(label) }
                        )
                    }
                }
            }
        ) { innerPadding ->
            Box(
                modifier = Modifier
                    .padding(innerPadding)
                    .consumeWindowInsets(innerPadding)
                    .imePadding()
            ) {
                when (selectedTab) {
                    0 -> DashboardScreen(
                        state = state,
                        onApprove = vm::respondApproval,
                        onRefreshUsage = vm::refreshUsageAndQuota
                    )
                    1 -> ChatScreen(
                        state = state,
                        onSendMessage = vm::sendChatMessage,
                        onStageFile = vm::stageAttachment,
                        onClearStagedFile = vm::clearPendingAttachment,
                        onDownloadAttachment = { attPath, fileName ->
                            vm.downloadAndHandleAttachment(context, attPath, fileName)
                        },
                        onUpdateModelConfig = vm::updateModelConfig
                    )
                    2 -> RoomsScreen(
                        state = state,
                        onSelectRoom = { roomId ->
                            vm.selectRoom(roomId)
                            selectedTab = 1
                        },
                        onCreateRoom = { name, desc ->
                            vm.createRoom(name, desc)
                            selectedTab = 1
                        }
                    )
                    3 -> SettingsScreen(
                        state = state,
                        onTestConnection = vm::testConnection,
                        onSaveAndReconnect = vm::updateSettingsAndReconnect,
                        onThemeModeChange = vm::setThemeMode,
                        onCheckUpdate = vm::checkForUpdate,
                        onInstallUpdate = vm::downloadAndInstallUpdate,
                        onRefreshFcmToken = vm::refreshFcmStatus,
                        onTestNotification = { ctx ->
                            BridgeNotificationHelper.notifyTaskStatus(
                                ctx,
                                "Antigravity 測試通知",
                                "這是一則測試通知，代表通知權限與音效通道正常。",
                                9002
                            )
                        }
                    )
                }
            }
        }
    }
}
