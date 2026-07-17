
#!/usr/bin/env python3
"""Silver.

A PyQt6 WebEngine browser shell with privacy-first defaults.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote_plus


CHROMIUM_PRIVACY_FLAGS = " ".join(
    [
        "--disable-third-party-cookies",
        "--disable-features=InterestCohort,AdInterestGroupAPI,PrivacySandboxAdsAPIs,AttributionReportingCrossAppWeb",
    ]
)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", CHROMIUM_PRIVACY_FLAGS)

from PyQt6.QtCore import QByteArray, QSize, QStandardPaths, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence, QShortcut
from PyQt6.QtWebEngineCore import (
    QWebEngineCertificateError,
    QWebEngineDownloadRequest,
    QWebEngineFullScreenRequest,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Silver"
ORG_NAME = "CodexLocal"
HOME_URL = "browser://home"
INFO_URL = "browser://info"
SETTINGS_URL = "browser://settings"
THEME_URL = "browser://theme"
MAX_HISTORY_ITEMS = 600
MAX_BLOCK_LOG = 120
DEFAULT_SEARCH_ENGINE = "duckduckgo"
DEFAULT_SEARCH = "https://duckduckgo.com/?q={query}"
SEARCH_ENGINES = {
    "duckduckgo": {
        "name": "DuckDuckGo",
        "template": "https://duckduckgo.com/?q={query}",
        "privacy": "Does not build a personalized search profile.",
    },
    "google": {
        "name": "Google",
        "template": "https://www.google.com/search?q={query}",
        "privacy": "Broad index and account integration; less private than DuckDuckGo.",
    },
}
GENERIC_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


AD_HOSTS = {
    "2mdn.net",
    "adform.net",
    "adnxs.com",
    "adsafeprotected.com",
    "adsrvr.org",
    "advertising.com",
    "amazon-adsystem.com",
    "appnexus.com",
    "doubleclick.net",
    "googleadservices.com",
    "googlesyndication.com",
    "googletagservices.com",
    "moatads.com",
    "openx.net",
    "outbrain.com",
    "pubmatic.com",
    "rubiconproject.com",
    "scorecardresearch.com",
    "taboola.com",
    "yieldmo.com",
}

TRACKER_HOSTS = {
    "amplitude.com",
    "app-measurement.com",
    "chartbeat.com",
    "clarity.ms",
    "clicky.com",
    "contentsquare.net",
    "criteo.com",
    "fullstory.com",
    "google-analytics.com",
    "googletagmanager.com",
    "heap.io",
    "hotjar.com",
    "kissmetrics.io",
    "matomo.cloud",
    "mixpanel.com",
    "newrelic.com",
    "optimizely.com",
    "quantserve.com",
    "segment.com",
    "sentry.io",
    "snowplowanalytics.com",
    "stats.wp.com",
}

SOCIAL_HOSTS = {
    "connect.facebook.net",
    "facebook.com",
    "facebook.net",
    "instagram.com",
    "linkedin.com",
    "platform.twitter.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
}

CRYPTOMINER_HOSTS = {
    "coin-hive.com",
    "coinhive.com",
    "crypto-loot.com",
    "cryptoloot.pro",
    "jsecoin.com",
    "webmine.cz",
}

FINGERPRINT_HOSTS = {
    "fingerprint.com",
    "fingerprintjs.com",
    "fpjs.io",
}

AD_TOKENS = (
    "/ads/",
    "/adserver/",
    "/advert/",
    "/banner/",
    "/banners/",
    "/doubleclick/",
    "adservice",
    "adserver",
    "advertising",
    "googleads",
    "sponsor",
)

TRACKER_TOKENS = (
    "/analytics/",
    "/beacon/",
    "/collect",
    "/pixel",
    "/telemetry/",
    "eventtrack",
    "tracking",
    "utm_source=",
)


def now_ts() -> float:
    return time.time()


def is_local_host(host: str) -> bool:
    host = host.lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def host_matches(host: str, hosts: set[str]) -> bool:
    if not host:
        return False
    host = host.lower().strip(".")
    return any(host == item or host.endswith("." + item) for item in hosts)


def safe_title(title: str, fallback: str = "Untitled") -> str:
    clean = " ".join((title or "").split())
    return clean[:80] or fallback


def elide(text: str, limit: int = 30) -> str:
    text = safe_title(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def app_data_dir() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    candidates = []
    if location:
        candidates.append(Path(location))
    candidates.extend(
        [
            Path.cwd() / ".silver-browser",
            Path("/tmp") / "silver-browser",
        ]
    )
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            continue
    raise RuntimeError("Silver could not create an application data directory.")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def load_json(path: Path, default: dict) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


@dataclass
class PrivacySettings:
    block_ads: bool = True
    block_trackers: bool = True
    block_social: bool = True
    block_cryptominers: bool = True
    block_fingerprinters: bool = True
    https_only: bool = True
    send_dnt: bool = True
    resist_fingerprinting: bool = True
    session_only_cookies: bool = True
    ask_permissions: bool = True
    search_engine: str = DEFAULT_SEARCH_ENGINE
    search_template: str = DEFAULT_SEARCH
    homepage: str = HOME_URL
    theme_mode: str = "light"

    @classmethod
    def from_dict(cls, data: dict) -> "PrivacySettings":
        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in data.items() if key in allowed}
        settings = cls(**values)
        if not isinstance(settings.theme_mode, str) or settings.theme_mode not in {"light", "dark"}:
            settings.theme_mode = "light"
        if "search_engine" not in data and "google.com" in settings.search_template:
            settings.search_engine = "google"
        if settings.search_engine not in SEARCH_ENGINES:
            if "google.com" in settings.search_template:
                settings.search_engine = "google"
            else:
                settings.search_engine = DEFAULT_SEARCH_ENGINE
        settings.search_template = SEARCH_ENGINES[settings.search_engine]["template"]
        return settings


class BrowserStore:
    def __init__(self, path: Path):
        self.path = path
        payload = load_json(path, {"bookmarks": [], "history": [], "settings": {}})
        self.bookmarks: list[dict] = list(payload.get("bookmarks", []))
        self.history: list[dict] = list(payload.get("history", []))
        self.settings = PrivacySettings.from_dict(payload.get("settings", {}))

    def save(self) -> None:
        atomic_write_json(
            self.path,
            {
                "bookmarks": self.bookmarks[:200],
                "history": self.history[:MAX_HISTORY_ITEMS],
                "settings": asdict(self.settings),
            },
        )

    def add_history(self, title: str, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            return
        self.history = [entry for entry in self.history if entry.get("url") != url]
        self.history.insert(
            0,
            {
                "title": safe_title(title, url),
                "url": url,
                "visited": now_ts(),
            },
        )
        del self.history[MAX_HISTORY_ITEMS:]
        self.save()

    def add_bookmark(self, title: str, url: str) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        if any(entry.get("url") == url for entry in self.bookmarks):
            return False
        self.bookmarks.insert(
            0,
            {
                "title": safe_title(title, url),
                "url": url,
                "created": now_ts(),
            },
        )
        del self.bookmarks[200:]
        self.save()
        return True

    def remove_bookmark(self, url: str) -> bool:
        original = len(self.bookmarks)
        self.bookmarks = [entry for entry in self.bookmarks if entry.get("url") != url]
        changed = len(self.bookmarks) != original
        if changed:
            self.save()
        return changed

    def is_bookmarked(self, url: str) -> bool:
        return any(entry.get("url") == url for entry in self.bookmarks)

    def clear_history(self) -> None:
        self.history.clear()
        self.save()


class PrivacyInterceptor(QWebEngineUrlRequestInterceptor):
    blockedRequest = pyqtSignal(str, str, str)
    upgradedRequest = pyqtSignal(str)

    def __init__(self, settings: PrivacySettings):
        super().__init__()
        self.settings = settings
        self.blocked_total = 0
        self.blocked_by_reason: Counter[str] = Counter()
        self.recent_blocks: deque[tuple[str, str, str]] = deque(maxlen=MAX_BLOCK_LOG)

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        scheme = url.scheme().lower()
        host = url.host().lower().strip(".")

        if self.settings.send_dnt:
            info.setHttpHeader(QByteArray(b"DNT"), QByteArray(b"1"))
            info.setHttpHeader(QByteArray(b"Sec-GPC"), QByteArray(b"1"))

        if self.settings.https_only and scheme == "http" and host and not is_local_host(host):
            upgraded = QUrl(url)
            upgraded.setScheme("https")
            info.redirect(upgraded)
            self.upgradedRequest.emit(upgraded.toString())
            return

        reason = self.block_reason(info, url, host)
        if not reason:
            return

        info.block(True)
        full_url = url.toString()
        display_host = host or url.toString()
        self.blocked_total += 1
        self.blocked_by_reason[reason] += 1
        self.recent_blocks.appendleft((display_host, reason, full_url))
        self.blockedRequest.emit(display_host, reason, full_url)

    def block_reason(self, info: QWebEngineUrlRequestInfo, url: QUrl, host: str) -> str | None:
        scheme = url.scheme().lower()
        if scheme not in {"http", "https", "ws", "wss"}:
            return None

        url_text = url.toString().lower()
        resource = info.resourceType()

        if self.settings.block_cryptominers and host_matches(host, CRYPTOMINER_HOSTS):
            return "crypto miner"

        if self.settings.block_fingerprinters and (
            host_matches(host, FINGERPRINT_HOSTS)
            or "fingerprintjs" in url_text
            or "canvasfingerprint" in url_text
        ):
            return "fingerprinter"

        if self.settings.block_social and host_matches(host, SOCIAL_HOSTS):
            return "social tracker"

        if self.settings.block_ads and (
            host_matches(host, AD_HOSTS) or any(token in url_text for token in AD_TOKENS)
        ):
            return "ad"

        if self.settings.block_trackers and (
            host_matches(host, TRACKER_HOSTS) or any(token in url_text for token in TRACKER_TOKENS)
        ):
            return "tracker"

        if (
            self.settings.block_trackers
            and resource
            in {
                QWebEngineUrlRequestInfo.ResourceType.ResourceTypePing,
                QWebEngineUrlRequestInfo.ResourceType.ResourceTypeCspReport,
            }
        ):
            return "telemetry"

        return None


class BrowserPage(QWebEnginePage):
    def __init__(self, window: "BrowserWindow", profile: QWebEngineProfile, parent: QWidget):
        super().__init__(profile, parent)
        self.browser_window = window

    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        if is_main_frame and url.scheme().lower() == "browser":
            QTimer.singleShot(0, lambda: self.browser_window.show_internal_page(self, url))
            return False
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message: str, line_number: int, source_id: str) -> None:
        if source_id.startswith("browser://"):
            return
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class BrowserView(QWebEngineView):
    def __init__(self, window: "BrowserWindow", profile: QWebEngineProfile):
        super().__init__(window)
        self.browser_window = window
        self.setPage(BrowserPage(window, profile, self))
        self.page().featurePermissionRequested.connect(
            lambda origin, feature, page=self.page(): window.handle_permission_request(page, origin, feature)
        )
        self.page().certificateError.connect(window.handle_certificate_error)
        self.page().fullScreenRequested.connect(window.handle_fullscreen_request)

    def createWindow(self, window_type: QWebEnginePage.WebWindowType) -> QWebEngineView:
        background = window_type == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        return self.browser_window.add_tab(background=background)


class PrivacyDialog(QDialog):
    def __init__(self, settings: PrivacySettings, parent: QWidget | None = None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Privacy Controls")
        self.setMinimumWidth(520)

        self.checks: dict[str, QCheckBox] = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "These settings apply to new and existing tabs. Third-party cookie blocking is also "
            "enabled through Chromium startup flags."
        )
        intro.setWordWrap(True)
        intro.setObjectName("MutedLabel")
        layout.addWidget(intro)

        self.add_check(layout, "block_trackers", "Enhanced tracking protection", "Block common analytics and tracking hosts.")
        self.add_check(layout, "block_ads", "Ad blocking", "Block common ad networks and ad-like resource paths.")
        self.add_check(layout, "block_social", "Social tracker blocking", "Block embedded social widgets and trackers.")
        self.add_check(layout, "block_cryptominers", "Cryptominer blocking", "Block known browser mining scripts.")
        self.add_check(layout, "block_fingerprinters", "Fingerprinting script blocking", "Block common fingerprinting services.")
        self.add_check(layout, "https_only", "HTTPS-only upgrades", "Upgrade ordinary HTTP requests to HTTPS when possible.")
        self.add_check(layout, "send_dnt", "Send DNT and GPC", "Attach Do Not Track and Global Privacy Control headers.")
        self.add_check(layout, "resist_fingerprinting", "Resist fingerprinting", "Disable canvas reads, WebGL, WebRTC local IP exposure, and plugin surfaces.")
        self.add_check(layout, "session_only_cookies", "Session-only cookies and cache", "Keep cookies and cache in memory for this app session.")
        self.add_check(layout, "ask_permissions", "Ask for site permissions", "Prompt before allowing location, camera, microphone, desktop capture, notifications, or clipboard access.")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_check(self, layout: QVBoxLayout, key: str, title: str, detail: str) -> None:
        box = QCheckBox(title)
        box.setChecked(bool(getattr(self.settings, key)))
        box.setToolTip(detail)
        self.checks[key] = box
        layout.addWidget(box)

    def accept(self) -> None:
        for key, box in self.checks.items():
            setattr(self.settings, key, box.isChecked())
        super().accept()


class FindBar(QWidget):
    def __init__(self, parent: "BrowserWindow"):
        super().__init__(parent)
        self.browser = parent
        self.setObjectName("FindBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        label = QLabel("Find")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Text on page")
        self.input.setClearButtonEnabled(True)
        prev_btn = QPushButton("Previous")
        next_btn = QPushButton("Next")
        close_btn = QPushButton("Close")

        layout.addWidget(label)
        layout.addWidget(self.input, 1)
        layout.addWidget(prev_btn)
        layout.addWidget(next_btn)
        layout.addWidget(close_btn)

        self.input.textChanged.connect(lambda text: self.find(text))
        self.input.returnPressed.connect(lambda: self.find(self.input.text(), backward=False))
        prev_btn.clicked.connect(lambda: self.find(self.input.text(), backward=True))
        next_btn.clicked.connect(lambda: self.find(self.input.text(), backward=False))
        close_btn.clicked.connect(self.hide)
        self.hide()

    def show_and_focus(self) -> None:
        self.show()
        self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.input.selectAll()

    def find(self, text: str, backward: bool = False) -> None:
        view = self.browser.current_view()
        if not view:
            return
        flags = QWebEnginePage.FindFlag(0)
        if backward:
            flags |= QWebEnginePage.FindFlag.FindBackward
        view.findText(text, flags)


class BrowserWindow(QMainWindow):
    def __init__(self, private: bool = False, start_url: str | None = None):
        super().__init__()
        self.private = private
        self.data_dir = app_data_dir()
        self.store = BrowserStore(self.data_dir / "browser_store.json")
        self.blocked_since_start = 0
        self.upgrades_since_start = 0
        self.normal_geometry = None

        self.profile = self.create_profile()
        self.native_user_agent = self.profile.httpUserAgent()
        self.interceptor = PrivacyInterceptor(self.store.settings)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.interceptor.blockedRequest.connect(self.on_request_blocked)
        self.interceptor.upgradedRequest.connect(self.on_request_upgraded)
        self.profile.downloadRequested.connect(self.handle_download)
        self.apply_privacy_settings()

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self.on_current_tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)

        self.find_bar = FindBar(self)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.tabs)
        central_layout.addWidget(self.find_bar)
        self.setCentralWidget(central)

        self.build_toolbar()
        self.build_menus()
        self.build_statusbar()
        self.apply_style()
        self.install_shortcuts()

        mode = "Private" if self.private else "Standard"
        self.setWindowTitle(f"{APP_NAME} - {mode}")
        self.resize(1320, 860)

        self.add_tab(start_url or self.store.settings.homepage, focus=True)
        QTimer.singleShot(50, self.address_bar.setFocus)

    def create_profile(self) -> QWebEngineProfile:
        if self.private:
            profile = QWebEngineProfile(self)
            profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            return profile

        profile = QWebEngineProfile("SilverProfile", self)
        profile_dir = self.data_dir / "profile"
        cache_dir = self.data_dir / "cache"
        profile.setPersistentStoragePath(str(profile_dir))
        profile.setCachePath(str(cache_dir))
        return profile

    def apply_privacy_settings(self) -> None:
        settings = self.store.settings
        web = self.profile.settings()
        web.setAttribute(QWebEngineSettings.WebAttribute.HyperlinkAuditingEnabled, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.DnsPrefetchEnabled, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.AllowGeolocationOnInsecureOrigins, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.WebRTCPublicInterfacesOnly, True)
        web.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        web.setAttribute(QWebEngineSettings.WebAttribute.ScreenCaptureEnabled, settings.ask_permissions)
        web.setAttribute(QWebEngineSettings.WebAttribute.ReadingFromCanvasEnabled, not settings.resist_fingerprinting)
        web.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, not settings.resist_fingerprinting)
        web.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, not settings.resist_fingerprinting)
        web.setAttribute(QWebEngineSettings.WebAttribute.TouchIconsEnabled, True)
        web.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        web.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)

        if settings.resist_fingerprinting:
            self.profile.setHttpUserAgent(GENERIC_USER_AGENT)
        else:
            self.profile.setHttpUserAgent(self.native_user_agent)

        if self.private or settings.session_only_cookies:
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        else:
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

        self.profile.setHttpAcceptLanguage("en-US,en;q=0.8")
        self.update_privacy_status()

    def build_toolbar(self) -> None:
        toolbar = QToolBar("Navigation")
        toolbar.setObjectName("NavBar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)

        self.back_btn = self.tool_button("Back", QStyle.StandardPixmap.SP_ArrowBack, self.go_back)
        self.forward_btn = self.tool_button("Forward", QStyle.StandardPixmap.SP_ArrowForward, self.go_forward)
        self.reload_btn = self.tool_button("Reload", QStyle.StandardPixmap.SP_BrowserReload, self.reload_current)
        self.home_btn = self.tool_button("Home", QStyle.StandardPixmap.SP_FileDialogStart, self.go_home)
        self.new_tab_btn = self.tool_button("New tab", QStyle.StandardPixmap.SP_FileDialogNewFolder, lambda: self.add_tab(focus=True))

        for button in [self.back_btn, self.forward_btn, self.reload_btn, self.home_btn, self.new_tab_btn]:
            toolbar.addWidget(button)

        self.security_label = QLabel("Local")
        self.security_label.setObjectName("SecurityLabel")
        toolbar.addWidget(self.security_label)

        self.address_bar = QLineEdit()
        self.address_bar.setObjectName("AddressBar")
        self.update_search_placeholder()
        self.address_bar.setClearButtonEnabled(True)
        self.address_bar.returnPressed.connect(self.load_from_address_bar)
        self.address_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar.addWidget(self.address_bar)

        self.bookmark_btn = QPushButton("Bookmark")
        self.bookmark_btn.setObjectName("BookmarkButton")
        self.bookmark_btn.clicked.connect(self.toggle_bookmark_current)
        toolbar.addWidget(self.bookmark_btn)

        self.privacy_btn = QPushButton("Shield")
        self.privacy_btn.setObjectName("PrivacyButton")
        self.privacy_btn.clicked.connect(self.show_privacy_dialog)
        toolbar.addWidget(self.privacy_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(110)
        self.progress.hide()
        toolbar.addWidget(self.progress)

    def tool_button(self, tip: str, icon: QStyle.StandardPixmap, callback: Callable[[], None]) -> QToolButton:
        button = QToolButton()
        button.setToolTip(tip)
        button.setIcon(self.style().standardIcon(icon))
        button.clicked.connect(callback)
        button.setAutoRaise(True)
        return button

    def build_menus(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        self.add_menu_action(file_menu, "New Tab", "Ctrl+T", lambda: self.add_tab(focus=True))
        self.add_menu_action(file_menu, "New Private Window", "Ctrl+Shift+P", self.open_private_window)
        self.add_menu_action(file_menu, "Close Tab", "Ctrl+W", self.close_current_tab)
        file_menu.addSeparator()
        self.add_menu_action(file_menu, "Save Page", "Ctrl+S", self.save_current_page)
        self.add_menu_action(file_menu, "Print", "Ctrl+P", self.print_current_page)
        file_menu.addSeparator()
        self.add_menu_action(file_menu, "Quit", "Ctrl+Q", QApplication.instance().quit)

        privacy_menu = menu_bar.addMenu("&Privacy")
        self.add_menu_action(privacy_menu, "Privacy Controls", "Ctrl+Shift+S", self.show_privacy_dialog)
        self.add_menu_action(privacy_menu, "Search Engine", None, lambda: self.load_target(self.current_view(), SETTINGS_URL))
        self.add_menu_action(privacy_menu, "Clear Browsing Data", "Ctrl+Shift+Delete", self.clear_browsing_data)
        self.recent_blocks_menu = privacy_menu.addMenu("Recent Blocks")
        privacy_menu.addSeparator()
        self.add_menu_action(privacy_menu, "New Private Window", None, self.open_private_window)

        self.bookmarks_menu = menu_bar.addMenu("&Bookmarks")
        self.refresh_bookmarks_menu()

        self.history_menu = menu_bar.addMenu("&History")
        self.refresh_history_menu()

        view_menu = menu_bar.addMenu("&View")
        self.add_menu_action(view_menu, "Find in Page", "Ctrl+F", self.find_bar.show_and_focus)
        self.add_menu_action(view_menu, "Zoom In", "Ctrl++", lambda: self.zoom_current(0.1))
        self.add_menu_action(view_menu, "Zoom Out", "Ctrl+-", lambda: self.zoom_current(-0.1))
        self.add_menu_action(view_menu, "Reset Zoom", "Ctrl+0", self.reset_zoom_current)
        self.add_menu_action(view_menu, "Developer Tools", "F12", self.open_devtools)

        help_menu = menu_bar.addMenu("&Help")
        self.add_menu_action(help_menu, "Silver Info", None, lambda: self.load_target(self.current_view(), INFO_URL))

    def add_menu_action(
        self,
        menu: QMenu,
        label: str,
        shortcut: str | None,
        callback: Callable[[], None],
    ) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def build_statusbar(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("Ready")
        self.privacy_label = QLabel()
        self.privacy_label.setObjectName("PrivacyStatus")
        status.addWidget(self.status_label, 1)
        status.addPermanentWidget(self.privacy_label)
        self.update_privacy_status()

    def install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.focus_address)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.go_forward)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.toggle_bookmark_current)
        QShortcut(QKeySequence("Esc"), self, activated=self.escape_pressed)

    def app_theme_colors(self) -> dict[str, str]:
        if self.is_dark_theme():
            return {
                "window_bg": "#0b1018",
                "text": "#f8fafc",
                "menu_bg": "#111827",
                "menu_border": "#293548",
                "menu_hover": "#1b2533",
                "menu_item_text": "#f8fafc",
                "menu_panel": "#111827",
                "menu_panel_border": "#334155",
                "toolbar_bg": "#111827",
                "toolbar_border": "#293548",
                "tool_bg": "#e5edf6",
                "tool_border": "#526173",
                "tool_hover": "#f8fafc",
                "tool_hover_border": "#93a4ba",
                "tool_pressed": "#cbd5e1",
                "address_bg": "#0f172a",
                "address_focus_bg": "#111827",
                "address_text": "#f8fafc",
                "address_border": "#334155",
                "address_focus": "#7dd3fc",
                "button_bg": "#111827",
                "button_text": "#f8fafc",
                "button_border": "#334155",
                "button_hover": "#1f2937",
                "primary_bg": "#7dd3fc",
                "primary_text": "#06121f",
                "bookmark_bg": "#3b2a11",
                "bookmark_text": "#fde68a",
                "bookmark_border": "#d97706",
                "security": "#cbd5e1",
                "privacy": "#86efac",
                "muted": "#aab6ca",
                "tab_bg": "#182235",
                "tab_text": "#cbd5e1",
                "tab_border": "#334155",
                "tab_selected_bg": "#0f172a",
                "tab_selected_text": "#f8fafc",
                "tab_hover": "#223047",
                "find_bg": "#111827",
                "progress_bg": "#172033",
            }
        return {
            "window_bg": "#eef1f5",
            "text": "#111827",
            "menu_bg": "#f8fafc",
            "menu_border": "#d5dbe4",
            "menu_hover": "#e8edf4",
            "menu_item_text": "#0f172a",
            "menu_panel": "#fdfefe",
            "menu_panel_border": "#ccd3dd",
            "toolbar_bg": "#f8fafc",
            "toolbar_border": "#d5dbe4",
            "tool_bg": "transparent",
            "tool_border": "transparent",
            "tool_hover": "#e8edf4",
            "tool_hover_border": "#c6ced9",
            "tool_pressed": "#dde5ee",
            "address_bg": "#ffffff",
            "address_focus_bg": "#ffffff",
            "address_text": "#0f172a",
            "address_border": "#cbd5e1",
            "address_focus": "#2563eb",
            "button_bg": "#ffffff",
            "button_text": "#111827",
            "button_border": "#cbd5e1",
            "button_hover": "#eef2f7",
            "primary_bg": "#2563eb",
            "primary_text": "#ffffff",
            "bookmark_bg": "#fff7e8",
            "bookmark_text": "#875100",
            "bookmark_border": "#edb458",
            "security": "#475569",
            "privacy": "#166534",
            "muted": "#64748b",
            "tab_bg": "#dde4ee",
            "tab_text": "#334155",
            "tab_border": "#c7d0dc",
            "tab_selected_bg": "#f8fafc",
            "tab_selected_text": "#0f172a",
            "tab_hover": "#edf2f7",
            "find_bg": "#f8fafc",
            "progress_bg": "#e8edf4",
        }

    def apply_style(self) -> None:
        c = self.app_theme_colors()
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {c['window_bg']};
                color: {c['text']};
            }}
            QMenuBar {{
                background: {c['menu_bg']};
                color: {c['text']};
                border-bottom: 1px solid {c['menu_border']};
                padding: 2px 6px;
            }}
            QMenuBar::item {{
                padding: 6px 10px;
                border-radius: 6px;
            }}
            QMenuBar::item:selected {{
                background: {c['menu_hover']};
            }}
            QMenu {{
                background: {c['menu_panel']};
                color: {c['text']};
                border: 1px solid {c['menu_panel_border']};
                padding: 6px;
            }}
            QMenu::item {{
                padding: 6px 24px 6px 14px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background: {c['menu_hover']};
                color: {c['menu_item_text']};
            }}
            QToolBar#NavBar {{
                background: {c['toolbar_bg']};
                border-bottom: 1px solid {c['toolbar_border']};
                spacing: 8px;
                padding: 9px 12px;
            }}
            QToolButton {{
                min-width: 32px;
                min-height: 32px;
                background: {c['tool_bg']};
                border: 1px solid {c['tool_border']};
                border-radius: 8px;
                padding: 2px;
            }}
            QToolButton:hover {{
                background: {c['tool_hover']};
                border-color: {c['tool_hover_border']};
            }}
            QToolButton:pressed {{
                background: {c['tool_pressed']};
            }}
            QLineEdit#AddressBar {{
                background: {c['address_bg']};
                color: {c['address_text']};
                border: 1px solid {c['address_border']};
                border-radius: 8px;
                padding: 9px 13px;
                selection-background-color: {c['address_focus']};
            }}
            QLineEdit#AddressBar:focus {{
                border: 1px solid {c['address_focus']};
                background: {c['address_focus_bg']};
            }}
            QPushButton {{
                border: 1px solid {c['button_border']};
                border-radius: 8px;
                padding: 8px 12px;
                background: {c['button_bg']};
                color: {c['button_text']};
            }}
            QPushButton:hover {{
                background: {c['button_hover']};
            }}
            QPushButton#PrivacyButton {{
                background: {c['primary_bg']};
                color: {c['primary_text']};
                border-color: {c['primary_bg']};
                font-weight: 600;
            }}
            QPushButton#BookmarkButton[bookmarked="true"] {{
                background: {c['bookmark_bg']};
                color: {c['bookmark_text']};
                border-color: {c['bookmark_border']};
            }}
            QLabel#SecurityLabel {{
                color: {c['security']};
                padding: 0 6px;
                min-width: 54px;
            }}
            QLabel#PrivacyStatus {{
                color: {c['privacy']};
                font-weight: 600;
            }}
            QLabel#MutedLabel {{
                color: {c['muted']};
            }}
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background: {c['tab_bg']};
                color: {c['tab_text']};
                border: 1px solid {c['tab_border']};
                border-bottom: none;
                padding: 9px 13px;
                min-width: 150px;
                max-width: 260px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
            QTabBar::tab:selected {{
                background: {c['tab_selected_bg']};
                color: {c['tab_selected_text']};
            }}
            QTabBar::tab:hover {{
                background: {c['tab_hover']};
            }}
            QWidget#FindBar {{
                background: {c['find_bg']};
                border-top: 1px solid {c['toolbar_border']};
            }}
            QStatusBar {{
                background: {c['menu_bg']};
                color: {c['text']};
                border-top: 1px solid {c['toolbar_border']};
            }}
            QProgressBar {{
                border: 1px solid {c['button_border']};
                border-radius: 6px;
                height: 10px;
                text-align: center;
                background: {c['progress_bg']};
            }}
            QProgressBar::chunk {{
                border-radius: 5px;
                background: {c['primary_bg']};
            }}
            """
        )

    def add_tab(self, url: str | None = None, focus: bool = False, background: bool = False) -> BrowserView:
        view = BrowserView(self, self.profile)
        index = self.tabs.addTab(view, "New Tab")
        self.tabs.setTabToolTip(index, "New Tab")

        view.titleChanged.connect(lambda title, v=view: self.on_title_changed(v, title))
        view.urlChanged.connect(lambda qurl, v=view: self.on_url_changed(v, qurl))
        view.iconChanged.connect(lambda icon, v=view: self.on_icon_changed(v, icon))
        view.loadStarted.connect(lambda v=view: self.on_load_started(v))
        view.loadProgress.connect(lambda value, v=view: self.on_load_progress(v, value))
        view.loadFinished.connect(lambda ok, v=view: self.on_load_finished(v, ok))
        view.page().linkHovered.connect(self.status_label.setText)

        if not background:
            self.tabs.setCurrentIndex(index)
        target = url or HOME_URL
        self.load_target(view, target)
        if focus:
            QTimer.singleShot(50, self.focus_address)
        return view

    def current_view(self) -> BrowserView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, BrowserView) else None

    def current_search_engine_key(self) -> str:
        key = self.store.settings.search_engine
        return key if key in SEARCH_ENGINES else DEFAULT_SEARCH_ENGINE

    def current_search_engine_name(self) -> str:
        return SEARCH_ENGINES[self.current_search_engine_key()]["name"]

    def current_search_template(self) -> str:
        key = self.current_search_engine_key()
        template = SEARCH_ENGINES[key]["template"]
        self.store.settings.search_template = template
        return template

    def is_dark_theme(self) -> bool:
        return self.store.settings.theme_mode == "dark"

    def theme_toggle_label(self) -> str:
        return "Light mode" if self.is_dark_theme() else "Dark mode"

    def toggle_theme(self) -> None:
        new_mode = "light" if self.is_dark_theme() else "dark"
        self.store.settings.theme_mode = new_mode
        self.store.save()
        self.apply_style()
        view = self.current_view()
        if view:
            self.update_address_for_view(view)
        if hasattr(self, "status_label"):
            self.status_label.setText(f"{new_mode.title()} mode enabled")

    def search_url(self, query: str) -> str:
        return self.current_search_template().format(query=quote_plus(query))

    def update_search_placeholder(self) -> None:
        if hasattr(self, "address_bar"):
            self.address_bar.setPlaceholderText(
                f"Search with {self.current_search_engine_name()} or enter address"
            )

    def normalize_internal_target(self, target: str) -> QUrl | None:
        clean = (target or "").strip()
        lower = clean.lower()
        if lower in {"", "about:blank", HOME_URL, "browser:home", "home"}:
            return QUrl(HOME_URL)
        if lower in {INFO_URL, "browser://about", "browser:info", "browser:about", "info", "about"}:
            return QUrl(INFO_URL)
        if lower in {
            SETTINGS_URL,
            "browser://search",
            "browser:settings",
            "browser:search",
            "settings",
            "search",
        }:
            return QUrl(SETTINGS_URL)
        if lower in {THEME_URL, "browser:theme", "theme"}:
            return QUrl(THEME_URL)
        if lower.startswith("browser://"):
            return QUrl(clean)
        return None

    def show_internal_page(self, page: QWebEnginePage, url: QUrl) -> None:
        host = url.host().lower()
        if host == "theme":
            self.toggle_theme()
            page.setHtml(self.home_html(), QUrl(HOME_URL))
            return
        if host == "settings":
            params = parse_qs(url.query())
            engine = params.get("engine", [None])[0]
            saved = False
            if engine in SEARCH_ENGINES:
                self.store.settings.search_engine = engine
                self.store.settings.search_template = SEARCH_ENGINES[engine]["template"]
                self.store.save()
                self.update_search_placeholder()
                self.status_label.setText(f"Search engine set to {SEARCH_ENGINES[engine]['name']}")
                saved = True
            page.setHtml(self.settings_html(saved=saved), QUrl(SETTINGS_URL))
            return
        if host in {"info", "about"}:
            page.setHtml(self.info_html(), QUrl(INFO_URL))
            return
        page.setHtml(self.home_html(), QUrl(HOME_URL))

    def load_target(self, view: BrowserView | None, target: str) -> None:
        if not view:
            return
        target = (target or HOME_URL).strip()
        internal_url = self.normalize_internal_target(target)
        if internal_url:
            self.show_internal_page(view.page(), internal_url)
            return
        view.load(self.resolve_input(target))

    def resolve_input(self, text: str) -> QUrl:
        text = text.strip()
        internal_url = self.normalize_internal_target(text)
        if internal_url:
            return internal_url

        local_path = Path(text).expanduser()
        if local_path.exists():
            return QUrl.fromLocalFile(str(local_path.resolve()))

        url = QUrl.fromUserInput(text)
        if text.startswith(("http://", "https://", "file://", "ftp://")) and url.isValid():
            return url

        if " " in text or "." not in text:
            return QUrl(self.search_url(text))

        if not url.scheme():
            return QUrl("https://" + text)
        return url

    def page_theme_tokens(self) -> str:
        if self.is_dark_theme():
            return """
      color-scheme: dark;
      --ink: #f8fafc;
      --muted: #aab6ca;
      --line: #354154;
      --panel: rgba(20,29,42,.90);
      --bg: #0b1018;
      --accent: #7dd3fc;
      --accent-2: #2dd4bf;
      --accent-soft: rgba(125,211,252,.14);
      --warn: #fbbf24;
      --field: #101826;
      --field-border: #40506a;
      --field-shadow: 0 16px 40px rgba(0,0,0,.25);
      --focus-ring: rgba(45,212,191,.18);
      --tile-bg: rgba(20,29,42,.88);
      --tile-shadow: 0 14px 36px rgba(0,0,0,.28);
      --quick-ink: #bae6fd;
      --quick-bg: rgba(14,116,144,.32);
      --quick-border: rgba(125,211,252,.32);
      --nav-ink: #eef6ff;
      --nav-bg: rgba(20,29,42,.82);
      --mark-start: #ecfeff;
      --mark-mid: #64748b;
      --mark-end: #0891b2;
      --glow-primary: rgba(14,165,233,.22);
      --glow-secondary: rgba(45,212,191,.12);
      --button-ink: #06121f;
      --status-ink: #bbf7d0;
      --status-bg: rgba(22,101,52,.28);
      --status-border: rgba(74,222,128,.30);
"""
        return """
      color-scheme: light;
      --ink: #111827;
      --muted: #64748b;
      --line: #d3dae4;
      --panel: rgba(255,255,255,.88);
      --bg: #eef1f5;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --accent-soft: #e8f0ff;
      --warn: #b55f00;
      --field: #ffffff;
      --field-border: #d3dae4;
      --field-shadow: 0 16px 40px rgba(35,49,65,.08);
      --focus-ring: rgba(15,111,97,.12);
      --tile-bg: rgba(255,255,255,.84);
      --tile-shadow: 0 10px 30px rgba(35,49,65,.06);
      --quick-ink: #174ea6;
      --quick-bg: #e8f0ff;
      --quick-border: #c7d7fe;
      --nav-ink: #0f172a;
      --nav-bg: rgba(255,255,255,.75);
      --mark-start: #f8fafc;
      --mark-mid: #9ca3af;
      --mark-end: #2563eb;
      --glow-primary: rgba(37,99,235,.14);
      --glow-secondary: rgba(15,118,110,.08);
      --button-ink: #ffffff;
      --status-ink: #166534;
      --status-bg: #e8f5ed;
      --status-border: #bfe3ca;
"""

    def home_html(self) -> str:
        private_text = "Private window" if self.private else "Privacy browser"
        bookmark_links = []
        for entry in self.store.bookmarks[:8]:
            title = html.escape(safe_title(entry.get("title", ""), entry.get("url", "")))
            url = html.escape(entry.get("url", ""))
            if url:
                bookmark_links.append(f'<a class="quick" href="{url}">{title}</a>')
        quick_links = "\n".join(bookmark_links) or '<span class="empty">No bookmarks yet</span>'
        blocked = html.escape(str(self.interceptor.blocked_total))
        mode = html.escape(private_text)
        engine_name = html.escape(self.current_search_engine_name())
        search_template = json.dumps(self.current_search_template())
        theme_label = html.escape(self.theme_toggle_label())
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Silver Home</title>
  <style>
    :root {{
{self.page_theme_tokens()}    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 15% 5%, var(--glow-primary), transparent 30%),
        linear-gradient(145deg, var(--glow-secondary), transparent 36%),
        var(--bg);
      color: var(--ink);
    }}
    main {{
      width: min(920px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 11vh 0 50px;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
      margin-bottom: 28px;
    }}
    .mark {{
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: linear-gradient(135deg, var(--mark-start), var(--mark-mid) 40%, var(--mark-end));
      box-shadow: 0 12px 34px rgba(37, 99, 235, .20);
    }}
    h1 {{
      margin: 0;
      font-size: 42px;
      line-height: 1;
      letter-spacing: 0;
    }}
    .mode {{
      margin-top: 7px;
      color: var(--muted);
      font-size: 15px;
    }}
    form {{
      display: flex;
      gap: 10px;
      margin-bottom: 22px;
    }}
    input {{
      flex: 1;
      min-width: 0;
      border: 1px solid var(--field-border);
      border-radius: 8px;
      background: var(--field);
      color: var(--ink);
      font-size: 18px;
      padding: 16px 18px;
      box-shadow: var(--field-shadow);
      outline: none;
    }}
    input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 4px var(--focus-ring), var(--field-shadow);
    }}
    button {{
      border: 0;
      border-radius: 8px;
      padding: 0 22px;
      background: var(--accent);
      color: var(--button-ink);
      font-weight: 700;
      font-size: 16px;
      cursor: pointer;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .tile {{
      background: var(--tile-bg);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      min-height: 116px;
      box-shadow: var(--tile-shadow);
    }}
    .tile strong {{
      display: block;
      margin-bottom: 8px;
      font-size: 15px;
    }}
    .tile span, .tile p {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
      margin: 0;
    }}
    .quicklinks {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }}
    .quick {{
      color: var(--quick-ink);
      background: var(--quick-bg);
      border: 1px solid var(--quick-border);
      border-radius: 7px;
      padding: 7px 9px;
      text-decoration: none;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .empty {{
      color: var(--muted);
    }}
    .nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    .nav a {{
      color: var(--nav-ink);
      background: var(--nav-bg);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 11px;
      text-decoration: none;
    }}
    @media (max-width: 980px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 760px) {{
      main {{ width: min(100vw - 24px, 920px); padding-top: 8vh; }}
      h1 {{ font-size: 32px; }}
      form {{ flex-direction: column; }}
      button {{ min-height: 48px; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="brand">
      <div class="mark" aria-hidden="true"></div>
      <div>
        <h1>Silver</h1>
        <div class="mode">{mode}</div>
      </div>
    </section>
    <form id="search">
      <input id="q" name="q" autocomplete="off" autofocus placeholder="Search with {engine_name} or enter a URL">
      <button type="submit">Go</button>
    </form>
    <nav class="nav">
      <a href="{SETTINGS_URL}">Search engine</a>
      <a href="{INFO_URL}">Info</a>
      <a href="{THEME_URL}">{theme_label}</a>
      <a href="https://github.com/tudorioan1">GitHub</a>
    </nav>
    <section class="grid">
      <div class="tile">
        <strong>Protection</strong>
        <p>{blocked} blocked requests this session. HTTPS upgrades, DNT, GPC, ad and tracker blocking are active.</p>
      </div>
      <div class="tile">
        <strong>Bookmarks</strong>
        <div class="quicklinks">{quick_links}</div>
      </div>
      <div class="tile">
        <strong>Search Engine</strong>
        <p>{engine_name} is selected. Change it from the Search Engine page.</p>
      </div>
      <div class="tile">
        <strong>Privacy Mode</strong>
        <p>Session cookies, permission prompts, fingerprinting resistance, and WebRTC local IP limits are enabled by default.</p>
      </div>
    </section>
  </main>
  <script>
    document.getElementById('search').addEventListener('submit', function (event) {{
      event.preventDefault();
      const value = document.getElementById('q').value.trim();
      if (!value) return;
      if (/^(https?:\\/\\/|file:\\/\\/)/i.test(value)) {{
        location.href = value;
      }} else if (/^[\\w.-]+\\.[a-z]{{2,}}([/:?#].*)?$/i.test(value)) {{
        location.href = 'https://' + value;
      }} else {{
        const template = {search_template};
        location.href = template.replace('{{query}}', encodeURIComponent(value));
      }}
    }});
  </script>
</body>
</html>"""

    def internal_page_style(self) -> str:
        return """
    :root {
""" + self.page_theme_tokens() + """    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 8% 4%, var(--glow-primary), transparent 30%),
        linear-gradient(150deg, var(--glow-secondary), transparent 38%),
        var(--bg);
      color: var(--ink);
    }
    main {
      width: min(920px, calc(100vw - 40px));
      margin: 0 auto;
      padding: 9vh 0 56px;
    }
    .topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 24px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .mark {
      width: 42px;
      height: 42px;
      border-radius: 10px;
      background: linear-gradient(135deg, var(--mark-start), var(--mark-mid) 40%, var(--mark-end));
      box-shadow: 0 12px 32px rgba(37, 99, 235, .18);
    }
    h1 {
      margin: 0;
      font-size: 38px;
      line-height: 1.05;
      letter-spacing: 0;
    }
    .sub {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
      max-width: 720px;
    }
    .nav {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    a, .button {
      color: var(--quick-ink);
      text-decoration: none;
    }
    .nav a, .button {
      background: var(--nav-bg);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 12px;
      font-weight: 650;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 22px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      box-shadow: var(--tile-shadow);
    }
    .panel.selected {
      border-color: var(--accent);
      box-shadow: 0 0 0 4px var(--focus-ring), var(--tile-shadow);
    }
    .panel h2 {
      margin: 0 0 8px;
      font-size: 20px;
      letter-spacing: 0;
    }
    .panel p {
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.5;
    }
    .status {
      display: inline-block;
      color: var(--status-ink);
      background: var(--status-bg);
      border: 1px solid var(--status-border);
      border-radius: 8px;
      padding: 8px 10px;
      margin-top: 12px;
      font-weight: 650;
    }
    .meta {
      display: grid;
      grid-template-columns: 180px 1fr;
      gap: 10px;
      margin-top: 18px;
    }
    .meta div {
      padding: 12px 0;
      border-bottom: 1px solid var(--line);
    }
    .meta div:nth-child(odd) {
      color: var(--muted);
    }
    @media (max-width: 760px) {
      main { width: min(100vw - 24px, 920px); padding-top: 7vh; }
      .topline { align-items: flex-start; flex-direction: column; }
      h1 { font-size: 31px; }
      .grid { grid-template-columns: 1fr; }
      .meta { grid-template-columns: 1fr; gap: 0; }
      .meta div:nth-child(odd) { padding-bottom: 0; border-bottom: 0; }
    }
  """

    def settings_html(self, saved: bool = False) -> str:
        current = self.current_search_engine_key()
        cards = []
        for key, engine in SEARCH_ENGINES.items():
            selected = key == current
            name = html.escape(engine["name"])
            privacy = html.escape(engine["privacy"])
            template = html.escape(engine["template"].replace("{query}", "silver browser"))
            state = "Current engine" if selected else f"Use {name}"
            href = SETTINGS_URL if selected else f"{SETTINGS_URL}?engine={key}"
            cards.append(
                f"""
      <article class="panel {'selected' if selected else ''}">
        <h2>{name}</h2>
        <p>{privacy}</p>
        <p>Example: {template}</p>
        <a class="button" href="{href}">{state}</a>
      </article>"""
            )
        notice = '<div class="status">Search engine updated.</div>' if saved else ""
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Silver Search Engine</title>
  <style>{self.internal_page_style()}</style>
</head>
<body>
  <main>
    <section class="topline">
      <div class="brand">
        <div class="mark" aria-hidden="true"></div>
        <div>
          <h1>Search Engine</h1>
          <p class="sub">Choose whether Silver searches from the address bar with Google or DuckDuckGo.</p>
        </div>
      </div>
      <nav class="nav">
        <a href="{HOME_URL}">Home</a>
        <a href="{INFO_URL}">Info</a>
      </nav>
    </section>
    {notice}
    <section class="grid">
      {''.join(cards)}
    </section>
  </main>
</body>
</html>"""

    def info_html(self) -> str:
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>About Silver</title>
  <style>{self.internal_page_style()}</style>
</head>
<body>
  <main>
    <section class="topline">
      <div class="brand">
        <div class="mark" aria-hidden="true"></div>
        <div>
          <h1>Silver</h1>
          <p class="sub">A privacy-focused PyQt6 browser shell built on Qt WebEngine/Chromium.</p>
        </div>
      </div>
      <nav class="nav">
        <a href="{HOME_URL}">Home</a>
        <a href="{SETTINGS_URL}">Search Engine</a>
      </nav>
    </section>
    <section class="panel">
      <h2>Info</h2>
      <div class="meta">
        <div>Made by</div>
        <div>Tudor Ioan</div>
        <div>GitHub</div>
        <div><a href="https://github.com/tudorioan1">tudorioan1</a></div>
        <div>Engine</div>
        <div>Qt WebEngine / Chromium</div>
        <div>Selected search</div>
        <div>{html.escape(self.current_search_engine_name())}</div>
      </div>
    </section>
  </main>
</body>
</html>"""

    def load_from_address_bar(self) -> None:
        view = self.current_view()
        if not view:
            return
        self.load_target(view, self.address_bar.text())

    def focus_address(self) -> None:
        self.address_bar.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.address_bar.selectAll()

    def escape_pressed(self) -> None:
        if self.find_bar.isVisible():
            self.find_bar.hide()
            return
        self.address_bar.clearFocus()

    def go_back(self) -> None:
        view = self.current_view()
        if view:
            view.back()

    def go_forward(self) -> None:
        view = self.current_view()
        if view:
            view.forward()

    def reload_current(self) -> None:
        view = self.current_view()
        if view:
            view.reload()

    def go_home(self) -> None:
        self.load_target(self.current_view(), self.store.settings.homepage)

    def close_tab(self, index: int) -> None:
        if self.tabs.count() == 1:
            self.load_target(self.current_view(), HOME_URL)
            return
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget:
            widget.deleteLater()

    def close_current_tab(self) -> None:
        self.close_tab(self.tabs.currentIndex())

    def on_current_tab_changed(self, index: int) -> None:
        view = self.current_view()
        if not view:
            return
        self.update_address_for_view(view)
        self.update_navigation_state()

    def on_title_changed(self, view: BrowserView, title: str) -> None:
        index = self.tabs.indexOf(view)
        if index >= 0:
            tab_title = elide(title, 34)
            self.tabs.setTabText(index, tab_title)
            self.tabs.setTabToolTip(index, title or view.url().toString())
        if view is self.current_view():
            suffix = " - Private" if self.private else ""
            self.setWindowTitle(f"{safe_title(title, APP_NAME)} - {APP_NAME}{suffix}")
            self.update_bookmark_button()

    def on_icon_changed(self, view: BrowserView, icon: QIcon) -> None:
        index = self.tabs.indexOf(view)
        if index >= 0 and not icon.isNull():
            self.tabs.setTabIcon(index, icon)

    def on_url_changed(self, view: BrowserView, qurl: QUrl) -> None:
        if view is self.current_view():
            self.update_address_for_view(view)
            self.update_navigation_state()

    def on_load_started(self, view: BrowserView) -> None:
        if view is self.current_view():
            self.progress.show()
            self.progress.setValue(0)
            self.status_label.setText("Loading")
            self.reload_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserStop))
            try:
                self.reload_btn.clicked.disconnect()
            except TypeError:
                pass
            self.reload_btn.clicked.connect(view.stop)

    def on_load_progress(self, view: BrowserView, value: int) -> None:
        if view is self.current_view():
            self.progress.show()
            self.progress.setValue(value)

    def on_load_finished(self, view: BrowserView, ok: bool) -> None:
        if view is self.current_view():
            self.progress.hide()
            self.status_label.setText("Done" if ok else "Load failed")
            self.reload_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            try:
                self.reload_btn.clicked.disconnect()
            except TypeError:
                pass
            self.reload_btn.clicked.connect(self.reload_current)
            self.update_navigation_state()
            self.update_bookmark_button()

        if ok and not self.private:
            url = view.url().toString()
            self.store.add_history(view.title(), url)
            self.refresh_history_menu()

    def update_address_for_view(self, view: BrowserView) -> None:
        url = view.url()
        text = url.toString()
        if text.startswith(HOME_URL) or text.startswith("data:text/html"):
            text = ""
        self.address_bar.setText(text)
        self.address_bar.setCursorPosition(0)

        scheme = url.scheme().lower()
        if scheme == "https":
            self.security_label.setText("Secure")
            color = "#5eead4" if self.is_dark_theme() else "#0f6f61"
            self.security_label.setStyleSheet(f"color: {color};")
        elif scheme in {"http", "ws"}:
            self.security_label.setText("Not secure")
            color = "#fbbf24" if self.is_dark_theme() else "#a54800"
            self.security_label.setStyleSheet(f"color: {color};")
        elif scheme == "file":
            self.security_label.setText("File")
            color = "#cbd5e1" if self.is_dark_theme() else "#365062"
            self.security_label.setStyleSheet(f"color: {color};")
        else:
            self.security_label.setText("Local")
            color = "#cbd5e1" if self.is_dark_theme() else "#365062"
            self.security_label.setStyleSheet(f"color: {color};")
        self.update_bookmark_button()

    def update_navigation_state(self) -> None:
        view = self.current_view()
        if not view:
            return
        self.back_btn.setEnabled(view.history().canGoBack())
        self.forward_btn.setEnabled(view.history().canGoForward())

    def update_bookmark_button(self) -> None:
        view = self.current_view()
        url = view.url().toString() if view else ""
        marked = self.store.is_bookmarked(url)
        self.bookmark_btn.setProperty("bookmarked", marked)
        self.bookmark_btn.setText("Bookmarked" if marked else "Bookmark")
        self.bookmark_btn.style().unpolish(self.bookmark_btn)
        self.bookmark_btn.style().polish(self.bookmark_btn)
        self.bookmark_btn.setEnabled(url.startswith(("http://", "https://")))

    def toggle_bookmark_current(self) -> None:
        view = self.current_view()
        if not view:
            return
        url = view.url().toString()
        if not url.startswith(("http://", "https://")):
            self.status_label.setText("Only web pages can be bookmarked")
            return
        if self.store.is_bookmarked(url):
            self.store.remove_bookmark(url)
            self.status_label.setText("Bookmark removed")
        else:
            self.store.add_bookmark(view.title(), url)
            self.status_label.setText("Bookmark saved")
        self.refresh_bookmarks_menu()
        self.update_bookmark_button()

    def refresh_bookmarks_menu(self) -> None:
        if not hasattr(self, "bookmarks_menu"):
            return
        self.bookmarks_menu.clear()
        self.add_menu_action(self.bookmarks_menu, "Bookmark This Page", "Ctrl+D", self.toggle_bookmark_current)
        self.bookmarks_menu.addSeparator()
        if not self.store.bookmarks:
            empty = QAction("No bookmarks yet", self)
            empty.setEnabled(False)
            self.bookmarks_menu.addAction(empty)
            return
        for entry in self.store.bookmarks[:35]:
            title = elide(entry.get("title", entry.get("url", "")), 52)
            url = entry.get("url", "")
            action = QAction(title, self)
            action.setToolTip(url)
            action.triggered.connect(lambda checked=False, link=url: self.load_target(self.current_view(), link))
            self.bookmarks_menu.addAction(action)

    def refresh_history_menu(self) -> None:
        if not hasattr(self, "history_menu"):
            return
        self.history_menu.clear()
        self.add_menu_action(self.history_menu, "Clear History", None, self.clear_history_only)
        self.history_menu.addSeparator()
        if not self.store.history:
            empty = QAction("No history yet", self)
            empty.setEnabled(False)
            self.history_menu.addAction(empty)
            return
        for entry in self.store.history[:40]:
            title = elide(entry.get("title", entry.get("url", "")), 56)
            url = entry.get("url", "")
            action = QAction(title, self)
            action.setToolTip(url)
            action.triggered.connect(lambda checked=False, link=url: self.load_target(self.current_view(), link))
            self.history_menu.addAction(action)

    def refresh_recent_blocks_menu(self) -> None:
        if not hasattr(self, "recent_blocks_menu"):
            return
        self.recent_blocks_menu.clear()
        if not self.interceptor.recent_blocks:
            empty = QAction("No blocked requests yet", self)
            empty.setEnabled(False)
            self.recent_blocks_menu.addAction(empty)
            return
        for host, reason, url in list(self.interceptor.recent_blocks)[:25]:
            action = QAction(f"{reason}: {host}", self)
            action.setToolTip(url)
            action.setEnabled(False)
            self.recent_blocks_menu.addAction(action)

    def on_request_blocked(self, host: str, reason: str, url: str) -> None:
        self.blocked_since_start += 1
        self.status_label.setText(f"Blocked {reason}: {host}")
        self.update_privacy_status()
        self.refresh_recent_blocks_menu()

    def on_request_upgraded(self, url: str) -> None:
        self.upgrades_since_start += 1
        self.update_privacy_status()

    def update_privacy_status(self) -> None:
        if not hasattr(self, "privacy_label"):
            return
        mode = "Private" if self.private else "Strict"
        self.privacy_label.setText(
            f"{mode} protection | blocked {self.interceptor.blocked_total} | HTTPS upgrades {self.upgrades_since_start}"
        )

    def show_privacy_dialog(self) -> None:
        dialog = PrivacyDialog(self.store.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.store.save()
        self.apply_privacy_settings()
        self.status_label.setText("Privacy settings updated")
        view = self.current_view()
        if view:
            view.reload()

    def clear_browsing_data(self) -> None:
        response = QMessageBox.question(
            self,
            "Clear Browsing Data",
            "Clear history, cookies, cache, and visited-link data for Silver?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearAllVisitedLinks()
        self.profile.clearHttpCache()
        self.store.clear_history()
        self.refresh_history_menu()
        cache_dir = self.data_dir / "cache"
        if cache_dir.exists() and not self.private:
            shutil.rmtree(cache_dir, ignore_errors=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.status_label.setText("Browsing data cleared")

    def clear_history_only(self) -> None:
        self.store.clear_history()
        self.profile.clearAllVisitedLinks()
        self.refresh_history_menu()
        self.status_label.setText("History cleared")

    def handle_permission_request(
        self,
        page: QWebEnginePage,
        origin: QUrl,
        feature: QWebEnginePage.Feature,
    ) -> None:
        label = {
            QWebEnginePage.Feature.Notifications: "notifications",
            QWebEnginePage.Feature.Geolocation: "location",
            QWebEnginePage.Feature.MediaAudioCapture: "microphone",
            QWebEnginePage.Feature.MediaVideoCapture: "camera",
            QWebEnginePage.Feature.MediaAudioVideoCapture: "camera and microphone",
            QWebEnginePage.Feature.MouseLock: "mouse lock",
            QWebEnginePage.Feature.DesktopVideoCapture: "screen capture",
            QWebEnginePage.Feature.DesktopAudioVideoCapture: "desktop audio",
            QWebEnginePage.Feature.ClipboardReadWrite: "clipboard",
            QWebEnginePage.Feature.LocalFontsAccess: "local fonts",
        }.get(feature, feature.name)

        if not self.store.settings.ask_permissions:
            page.setFeaturePermission(
                origin,
                feature,
                QWebEnginePage.PermissionPolicy.PermissionDeniedByUser,
            )
            self.status_label.setText(f"Denied {label} for {origin.host()}")
            return

        response = QMessageBox.question(
            self,
            "Site Permission",
            f"Allow {origin.host() or origin.toString()} to access {label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        policy = (
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if response == QMessageBox.StandardButton.Yes
            else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        )
        page.setFeaturePermission(origin, feature, policy)

    def handle_certificate_error(self, error: QWebEngineCertificateError) -> None:
        if not error.isOverridable():
            error.rejectCertificate()
            self.status_label.setText(f"Blocked certificate error: {error.description()}")
            return
        response = QMessageBox.warning(
            self,
            "Certificate Warning",
            f"{error.url().toString()}\n\n{error.description()}\n\nContinue anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response == QMessageBox.StandardButton.Yes:
            error.acceptCertificate()
        else:
            error.rejectCertificate()

    def handle_fullscreen_request(self, request: QWebEngineFullScreenRequest) -> None:
        request.accept()
        if request.toggleOn():
            self.menuBar().hide()
            self.statusBar().hide()
            self.showFullScreen()
        else:
            self.menuBar().show()
            self.statusBar().show()
            self.showNormal()

    def handle_download(self, download: QWebEngineDownloadRequest) -> None:
        default_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if not default_dir:
            default_dir = str(Path.home() / "Downloads")
        suggested = download.suggestedFileName() or download.downloadFileName() or "download"
        target, _ = QFileDialog.getSaveFileName(self, "Save Download", str(Path(default_dir) / suggested))
        if not target:
            download.cancel()
            self.status_label.setText("Download canceled")
            return

        path = Path(target)
        download.setDownloadDirectory(str(path.parent))
        download.setDownloadFileName(path.name)
        download.accept()
        self.status_label.setText(f"Downloading {path.name}")

        download.receivedBytesChanged.connect(
            lambda d=download, name=path.name: self.update_download_status(d, name)
        )
        download.isFinishedChanged.connect(
            lambda d=download, p=path: self.finish_download_status(d, p)
        )

    def update_download_status(self, download: QWebEngineDownloadRequest, name: str) -> None:
        total = download.totalBytes()
        received = download.receivedBytes()
        if total > 0:
            pct = int(received * 100 / total)
            self.status_label.setText(f"Downloading {name}: {pct}%")
        else:
            self.status_label.setText(f"Downloading {name}: {received} bytes")

    def finish_download_status(self, download: QWebEngineDownloadRequest, path: Path) -> None:
        if not download.isFinished():
            return
        if download.state() == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            self.status_label.setText(f"Downloaded {path.name}")
            response = QMessageBox.question(
                self,
                "Download Complete",
                f"Open {path.name}?",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
                QMessageBox.StandardButton.Close,
            )
            if response == QMessageBox.StandardButton.Open:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            self.status_label.setText(f"Download failed: {download.interruptReasonString()}")

    def open_private_window(self) -> None:
        window = BrowserWindow(private=True)
        keep_window(window)
        window.show()

    def save_current_page(self) -> None:
        view = self.current_view()
        if not view:
            return
        view.triggerPageAction(QWebEnginePage.WebAction.SavePage)

    def print_current_page(self) -> None:
        view = self.current_view()
        if not view:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Print to PDF",
            str(Path.home() / "Silver-page.pdf"),
            "PDF files (*.pdf)",
        )
        if not path:
            return
        view.page().printToPdf(path)
        self.status_label.setText(f"Saved PDF to {path}")

    def zoom_current(self, delta: float) -> None:
        view = self.current_view()
        if not view:
            return
        factor = max(0.25, min(5.0, view.zoomFactor() + delta))
        view.setZoomFactor(factor)
        self.status_label.setText(f"Zoom {int(factor * 100)}%")

    def reset_zoom_current(self) -> None:
        view = self.current_view()
        if view:
            view.setZoomFactor(1.0)
            self.status_label.setText("Zoom 100%")

    def open_devtools(self) -> None:
        view = self.current_view()
        if not view:
            return
        dev_window = QMainWindow(self)
        dev_window.setWindowTitle("Developer Tools")
        dev_view = QWebEngineView(dev_window)
        dev_page = QWebEnginePage(self.profile, dev_view)
        dev_view.setPage(dev_page)
        view.page().setDevToolsPage(dev_page)
        dev_window.setCentralWidget(dev_view)
        dev_window.resize(1000, 720)
        dev_window.show()
        keep_window(dev_window)


OPEN_WINDOWS: list[QMainWindow] = []


def keep_window(window: QMainWindow) -> None:
    OPEN_WINDOWS.append(window)

    def remove_window() -> None:
        try:
            OPEN_WINDOWS.remove(window)
        except ValueError:
            pass

    window.destroyed.connect(remove_window)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("url", nargs="?", help="Optional URL, search, or local file to open")
    parser.add_argument("--private", action="store_true", help="Open an off-the-record private window")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv[:1])
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)

    window = BrowserWindow(private=args.private, start_url=args.url)
    keep_window(window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
