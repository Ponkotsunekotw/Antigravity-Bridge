package com.antigravity.bridge.push

import android.content.Context
import android.content.Intent
import com.antigravity.bridge.data.BridgeClient
import com.antigravity.bridge.data.SettingsStore
import com.antigravity.bridge.ui.BridgeNotificationHelper
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class BridgeFirebaseMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        saveFcmToken(applicationContext, token)
        CoroutineScope(Dispatchers.IO).launch {
            syncTokenToServer(applicationContext, token)
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        val data = message.data
        if (data["type"] == "server_url_update") {
            val newUrl = (data["server_url"] ?: "").trim().trimEnd('/')
            if (newUrl.isNotBlank()) {
                SettingsStore(applicationContext).serverUrl = newUrl
                sendBroadcast(
                    Intent(ACTION_SERVER_URL_UPDATED)
                        .setPackage(packageName)
                        .putExtra(EXTRA_SERVER_URL, newUrl)
                )
            }
            return
        }

        val title = data["title"]
            ?: message.notification?.title
            ?: "Antigravity 提醒"
        val body = data["body"]
            ?: message.notification?.body
            ?: "收到一則新的遠端指揮推播"

        BridgeNotificationHelper.notifyTaskStatus(
            context = applicationContext,
            title = title,
            body = body,
            notificationId = (System.currentTimeMillis() % Int.MAX_VALUE).toInt()
        )
    }

    companion object {
        const val ACTION_SERVER_URL_UPDATED = "com.antigravity.bridge.SERVER_URL_UPDATED"
        const val EXTRA_SERVER_URL = "server_url"
        private const val PREFS_NAME = "fcm_prefs"
        private const val KEY_FCM_TOKEN = "fcm_token"

        fun isFirebaseConfigured(context: Context): Boolean {
            return runCatching { FirebaseApp.getApps(context).isNotEmpty() }.getOrDefault(false)
        }

        fun getSavedToken(context: Context): String? {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(KEY_FCM_TOKEN, null)
        }

        fun saveFcmToken(context: Context, token: String) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_FCM_TOKEN, token)
                .apply()
        }

        fun fetchAndSyncToken(
            context: Context,
            onTokenReady: (token: String?, error: String?) -> Unit = { _, _ -> }
        ) {
            if (!isFirebaseConfigured(context)) {
                onTokenReady(null, "尚未設定 google-services.json")
                return
            }
            runCatching {
                FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                    if (task.isSuccessful) {
                        val token = task.result
                        if (!token.isNullOrBlank()) {
                            saveFcmToken(context, token)
                            CoroutineScope(Dispatchers.IO).launch {
                                syncTokenToServer(context, token)
                            }
                            onTokenReady(token, null)
                            return@addOnCompleteListener
                        }
                        onTokenReady(getSavedToken(context), "取得空的 FCM Token")
                    } else {
                        val errMsg = task.exception?.localizedMessage ?: "Firebase 連線失敗"
                        onTokenReady(getSavedToken(context), errMsg)
                    }
                }
            }.onFailure { err ->
                onTokenReady(getSavedToken(context), err.localizedMessage ?: "Firebase 初始化失敗")
            }
        }

        suspend fun syncTokenToServer(context: Context, token: String): Boolean {
            val store = SettingsStore(context)
            val serverUrl = store.serverUrl.trim()
            val authToken = store.authToken.trim()
            if (serverUrl.isBlank() || authToken.isBlank()) return false
            return BridgeClient().registerFcmToken(serverUrl, authToken, token)
        }
    }
}
