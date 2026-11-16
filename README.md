# Antigravity Bridge（遠端指揮系統）

**Antigravity Bridge** 是一套專為搭配 AI Coding Agent（如 Antigravity）設計的遠端指揮與雙向協作系統，透過 **HTTP/HTTPS + WebSocket + FCM 推播** 運作，**無須額外架設 VPN**，搭配 **ServerHub** 與 **Cloudflare Quick Tunnel** 即可讓手機從任何網路安全連回電腦端工作區。

專案包含兩個核心部分：
1. **`server/`**：Python FastAPI + WebSocket 橋接伺服器（預設監聽 `127.0.0.1:8765`，附帶 `server_manifest.json` 可由 ServerHub 統一託管與穿透）。
2. **`android-app/`**：Android 原生 App（Kotlin + Jetpack Compose + Material 3 + OkHttp WebSocket + Google Code Scanner + FCM）。

---

## ✨ 主要功能

- **免 VPN 公網穿透與 QR Code 快速配對**：透過 ServerHub 啟用 Cloudflare Quick Tunnel（`https://*.trycloudflare.com`），手機端在「設定」頁直接掃描 QR Code 即可自動帶入網址與 Token 完成配對（亦支援局域網 / VPN 直連）。
- **多聊天室與雙向即時通訊**：支援依專案分組的多聊天室（`room-*`），手機端可即時發送文字或夾帶檔案/圖片給 AI Agent。
- **檔案與 APK 傳送／手動下載安裝**：AI Agent 可透過 `/api/rooms/{room_id}/agent-attachment` 上傳 ZIP、檔案或新編譯的 APK 至聊天室，手機端點擊「手動下載檔案」或「下載並安裝 APK」才實際下載。
- **任務進度與核准控制**：支援任務儀表板、步驟進度回報與敏感操作核准確認，並支援從手機端切換模型與推理深度。
- **App 內檢查更新**：支援從 `bridge_data/releases/` 發布新版 APK，透過 `/api/app/notify` 推播更新通知並在手機端一鍵下載更新。
- **Firebase Cloud Messaging (FCM) 推播**：支援背景推播通知與全螢幕提醒。

---

## 1. 啟動電腦端橋接伺服器

### 方式 A：搭配 ServerHub 託管（推薦，免 VPN 自動產生 QR Code）
1. 確保 `server/.env` 已設定（可複製 `server/.env.example` 修改 `BRIDGE_TOKEN` 與 `BRIDGE_PROJECTS_ROOT`）。
2. 將 `server/` 目錄匯入 **ServerHub**（已內建 `server/server_manifest.json`），點擊啟動即可自動啟動 FastAPI、建立 Cloudflare Quick Tunnel 並產生配對 QR Code。

### 方式 B：獨立於終端機啟動（區網 / 本機測試）
```powershell
cd server
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765
```

---

## 2. 與 AI Agent 聯動方式

伺服器提供以下機制讓本機 AI Agent（如 Antigravity）與手機端形成雙向閉環：

- **背景等待新訊息（`server/wait_for_message.py`）**：
  AI Agent 可在背景執行 `wait_for_message.py` 長輪詢新指令；一旦手機端在任一聊天室傳送訊息，腳本立即回傳訊息內容（`room_id`、`content`、附件路徑等）喚醒 Agent 執行任務。
- **CLI 與 HTTP API 回報**：
  - `server/bridge_cli.py`：回報任務進度（`report`）、請求核准（`ask-approval`）、標記完成（`complete`）。
  - `POST /api/rooms/{room_id}/messages`：以 `sender: "assistant"` 回覆文字結果至指定聊天室。
  - `POST /api/rooms/{room_id}/agent-attachment`：上傳產出檔案（如 `.zip`、`.apk`）供手機端手動點擊下載。
  - `POST /api/app/notify`：發布新版 APK 後推播更新提示。

---

## 3. 編譯 Android App（APK）

### 環境需求
- JDK 17（或 Android Studio 內建 JBR）
- Android SDK（`minSdk 26` 以上）
- 若需 FCM 推播，請於 `android-app/app/` 放置 `google-services.json`（並於伺服器資料目錄放置 `serviceAccountKey.json`）

### 編譯指令
```powershell
cd android-app
# Debug 版
.\gradlew.bat assembleDebug

# 正式簽章 Release 版（需於 android-app/keystore.properties 設定簽章金鑰）
.\gradlew.bat assembleRelease
```

---

## 4. 手機端快速連線

1. 在 Android 手機安裝 **Antigravity Bridge** APK。
2. 開啟 App 切換到「**設定**」分頁，點擊「**掃描 ServerHub QR Code**」，對準電腦端 ServerHub 顯示的 QR Code 即可自動完成網址、Token 填入與連線（或手動輸入伺服器網址與 `BRIDGE_TOKEN`）。
