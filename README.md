# Antigravity 遠端指揮系統（VPN 虛擬內網版）

這套專案包含兩個部分，讓你在手機透過 VPN（如 Tailscale、WireGuard、ZeroTier）連回這台 Windows 電腦，即時接收 Antigravity 工作進度回報、核准敏感操作，並下達新指令：

1. **`server/`**：Python FastAPI + WebSocket 工作區橋接伺服器（綁定 `0.0.0.0:8765`）
2. **`android-app/`**：Android 原生 App（Kotlin + Jetpack Compose + Material 3 + OkHttp WebSocket）

---

## 1. 啟動電腦端橋接伺服器

1. 進入 `server/` 目錄並啟動：
   ```powershell
   cd server
   .\start_server.ps1
   ```
2. 首次啟動會自動建立 `.env`，請務必修改 `BRIDGE_TOKEN` 為你自己的高強度金鑰。
3. 啟動時終端機清單會印出本機的所有 IPv4 位址，請記下你的 **VPN 介面 IP**（例如 Tailscale 的 `100.x.y.z`）。
4. 若 Windows 防火牆跳出提示，請允許 Python 在「私人網路」接收連線（或手動放行 TCP `8765` 埠）。

---

## 2. Antigravity / 本機腳本如何回報進度與讀取指令

伺服器內建 `server/bridge_cli.py`，可直接由 Antigravity 或本機任務腳本呼叫：

```powershell
# 查看手機端傳來的待處理指令
.\.venv\Scripts\python.exe bridge_cli.py pending

# 回報步驟進度（會即時透過 WebSocket 推播到手機）
.\.venv\Scripts\python.exe bridge_cli.py report --task-id task-xxxxxxxx --progress 40 --level step --message "正在重構 API 模組"

# 向手機端請求核准（手機端會顯示「核准繼續 / 拒絕」）
.\.venv\Scripts\python.exe bridge_cli.py ask-approval --task-id task-xxxxxxxx --message "是否允許執行資料庫遷移？"

# 標記任務完成並附上產出檔案（檔案放於 server/bridge_data/outputs/）
.\.venv\Scripts\python.exe bridge_cli.py complete --task-id task-xxxxxxxx --message "已完成實作與測試" --artifact "summary.md"
```

---

## 3. 編譯與安裝 Android App（APK）

目前這台電腦尚未安裝 JDK 17 與 Android SDK，因此有以下兩種方式產生 APK：

### 方式 A：使用 Android Studio（推薦）
1. 安裝並開啟 **Android Studio**。
2. 選擇 **Open** -> 選取本專案的 `android-app/` 資料夾。
3. 等待 Gradle Sync 完成後，點選 **Build > Build Bundle(s) / APK(s) > Build APK(s)**，或直接接上 USB 開啟偵錯點擊 **Run**。

### 方式 B：在本機命令列安裝 JDK 17 + Android SDK
若你希望我直接幫你在這台電腦安裝 JDK 17 與 Android Command-Line Tools 並編譯出 `.apk` 檔案，請告訴我，我可以協助設定環境並產出 Debug APK。

---

## 4. 手機端連線設定

1. 在 Android 手機連線到與電腦相同的 VPN。
2. 開啟 **Antigravity 遠端指揮** App，切換到「**設定**」分頁：
   - **電腦端 VPN 伺服器網址**：填入 `http://<電腦的VPN_IP>:8765`
   - **BRIDGE_TOKEN 驗證金鑰**：填入 `server/.env` 中的 `BRIDGE_TOKEN`
3. 點選「**測試連線**」確認通過後，點選「**儲存並重連**」即可開始使用。
