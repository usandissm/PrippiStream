#!/usr/bin/env python3
"""Static release gates for the current Android release."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


view_model = read("app/src/main/java/com/prippi/stream/MainViewModel.kt")
show_downloads = view_model.split("fun showDownloads()", 1)[1].split(
    "fun refreshDownloads", 1
)[0]
assert "repository.downloads()" in show_downloads
assert "resumeInterrupted" not in show_downloads

main = read("app/src/main/java/com/prippi/stream/MainActivity.kt")
assert "restoreInterrupted = true" in main
assert '"waiting_network" -> "In attesa della rete' in main
assert "DiagnosticSanitizer.sanitize(reportBody)" in main
assert ".setSingleChoiceItems(labels, selectedIndex)" in main
assert "DownloadPreparationActivity::class.java" in main
manifest = read("app/src/main/AndroidManifest.xml")
assert 'android:name=".PrippiApplication"' in manifest
assert 'android:name=".DownloadPreparationActivity"' in manifest
assert 'android:theme="@style/Theme.PrippiStream.DownloadPreparation"' in manifest

service = read(
    "app/src/main/java/com/prippi/stream/DownloadForegroundService.kt"
)
assert "registerDefaultNetworkCallback" in service
assert "NET_CAPABILITY_VALIDATED" in service
assert '"waiting_network" -> "In attesa della rete' in service

models = read("app/src/main/java/com/prippi/stream/DownloadModels.kt")
assert '"waiting_network"' in models

manager = read(
    "app/src/main/python/engine/platformcode/download_manager.py"
)
for marker in (
    "duplicate ignored",
    "NetworkUnavailableError",
    "waiting_network",
    "get_resumable()",
    "_stall_deadline",
    "_dbg_seg[0] < 20",
):
    assert marker in manager

database = read("app/src/main/python/engine/platformcode/downloads_db.py")
assert "migrate_legacy_network_errors" in database
assert "repair_completed" in database
resumable = database.split("def get_resumable", 1)[1].split(
    "def get_active", 1
)[0]
assert "paused" in resumable.split('"""', 2)[1]  # documented exclusion
assert "'paused'" not in resumable.split('"""', 2)[2]

jsontools = read("app/src/main/python/engine/core/jsontools.py")
assert "isinstance(data, (str, bytes)) and data" in jsontools

mediaset = read("app/src/main/python/engine/channels/mediasetplay.py")
assert "for it in (res.get('items') or []):" in mediaset

animeunity = read("app/src/main/python/engine/channels/animeunity.py")
assert "logger.info('[AnimeUnity] peliculas: no records" in animeunity

corsaro = read("app/src/main/python/engine/channels/ilcorsaronero.py")
assert 'support.logger.error("search except:' in corsaro

requests_sessions = read("app/src/main/python/engine/lib/requests/sessions.py")
assert "transport returned no HTTP response" in requests_sessions

xbmc = read("app/src/main/python/xbmc_shim/xbmc.py")
assert "isoformat(timespec='milliseconds')" in xbmc
assert "first_newline = tail.find" in xbmc

gradle = read("app/build.gradle.kts")
assert 'versionCode = 72' in gradle
assert 'versionName = "0.9.17"' in gradle
assert "prippiRequireDiagnosticsRelay" in gradle
assert "PRIPPI_REQUIRE_DIAGNOSTICS_RELAY" in gradle

delivery = read(
    "app/src/main/java/com/prippi/stream/diagnostics/DiagnosticDelivery.kt"
)
assert "nuovo tentativo automatico" in delivery
for marker in (
    "api.telegram.org",
    "sendDocument",
    "TELEGRAM_TOKEN_OBF",
    'JSONObject(response).optBoolean("ok")',
    "ZipOutputStream",
    "launchFallback(context, fallbackFile)",
):
    assert marker in delivery

remote_registry = read("app/src/main/python/engine/platformcode/remote_registry.py")
for marker in (
    "MAX_REGISTRY_BYTES",
    "MIN_REFRESH_INTERVAL_SECONDS",
    "validate(remote_text)",
    "_atomic_write",
    "os.fsync",
):
    assert marker in remote_registry

diagnostics = read("app/src/main/java/com/prippi/stream/AppDiagnostics.kt")
for marker in (
    "Thread.setDefaultUncaughtExceptionHandler",
    "last-crash.log",
    '\"/diagnostics\"',
    "PrippiDiagnosticsServer",
    "maxSizePercent(if (profile.isLowPower) 0.06 else 0.20)",
):
    assert marker in diagnostics

sanitizer = read(
    "app/src/main/java/com/prippi/stream/diagnostics/DiagnosticSanitizer.kt"
)
for secret in ("token", "api[_-]?key", "authorization", "signature"):
    assert secret in sanitizer

android_engine = ROOT / "app/src/main/python/engine"
python_payload = "\n".join(
    path.read_text(encoding="utf-8", errors="replace")
    for path in android_engine.rglob("*.py")
)
assert not re.search(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", python_payload)
legacy_settings = read("app/src/main/python/engine/specials/setting.py")
assert "_TG_TOKEN_OBF = ''" in legacy_settings
assert "_TG_CHAT_ID = ''" in legacy_settings

player_activity = read("app/src/main/java/com/prippi/stream/PlayerActivity.kt")
assert "window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)" in player_activity
assert "enterPictureInPictureMode(params)" in player_activity
assert "resumePlaybackAfterBackground = retainedPlayer.playWhenReady" in player_activity
assert "if (!isInPictureInPictureMode) retainedPlayer.pause()" in player_activity
assert "pictureInPictureSessionActive || isInPictureInPictureMode" in player_activity
assert "if (pictureInPictureClosed && !isFinishing)" in player_activity
assert "persistProgress(synchronous = true)" in player_activity

watch_progress = read("app/src/main/java/com/prippi/stream/WatchProgressStore.kt")
assert "fun saveNow(" in watch_progress
assert "if (!editor.commit())" in watch_progress

main_view_model = read("app/src/main/java/com/prippi/stream/MainViewModel.kt")
assert 'cw_home stored=${stored.size} rendered=${items.size}' in main_view_model
assert "clearBootstrapCallbacks()" in player_activity
assert "liveRowItems.length() == 0 && startPositionMs > 0" in player_activity
assert "resolveLiveCandidate(candidate, remainingMs)" in player_activity

python_bridge = read("app/src/main/java/com/prippi/stream/PythonBridge.kt")
assert "PAYLOAD_MARKER" in python_bridge
assert "ensureRuntimePayload(context, runtimeDir)" in python_bridge
assert "fun prewarm(context: Context)" in python_bridge

main_view_model = read("app/src/main/java/com/prippi/stream/MainViewModel.kt")
assert "foregroundTaskJob?.cancel()" in main_view_model
assert "if (uiPaused || state.page != AppPage.HOME) return@launch" in main_view_model

update_manager = read("app/src/main/java/com/prippi/stream/AppUpdateManager.kt")
assert "MAX_APK_BYTES" in update_manager
assert "directory.usableSpace" in update_manager

delivery = read(
    "app/src/main/java/com/prippi/stream/diagnostics/DiagnosticDelivery.kt"
)
assert "notifyManualBackup(applicationContext, report)" in delivery

bridge = read("app/src/main/python/bridge.py")
assert "max_workers=2 if _APP_LOW_POWER else None" in bridge
assert "max_new_rows=None" in bridge
assert "existing_labels=[label for label, _items in sc_rows]" in bridge
assert "'complete': False" in bridge
assert "home complete: %d rows" in bridge
home_engine = read("app/src/main/python/engine/platformcode/prippihome.py")
assert "max_workers=None, max_new_rows=None" in home_engine
assert "int(max_workers) <= 1" in home_engine
assert "pending_entries = [" in home_engine
assert "SC_MAX_ROWS        = 64" in home_engine

print("Current release invariants: OK")
