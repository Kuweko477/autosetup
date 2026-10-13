"""AutoSetup - set up a fresh Windows install: drivers (Windows Update) and apps (Scoop / winget)."""
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QSettings, Qt, QThread, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QProgressBar, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

# ───────────────────────────── Theme ─────────────────────────────
ACCENT = "#fdf6e3"
BG = "#0b0b0d"
SIDEBAR = "#0f0f12"
CARD = "#141418"
CARD_HOVER = "#18181d"
BORDER = "#222228"
MUTED = "#8b887d"
OK = "#a8d5a2"
ERR = "#e8908a"

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
VERSION = "2.0"


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


LOGO = resource_path("logo.png")


# ───────────────────────────── Data ─────────────────────────────
@dataclass(frozen=True)
class App:
    name: str
    package: str
    category: str
    desc: str
    manager: str = "scoop"      # "scoop" | "winget"
    bucket: str = ""            # scoop bucket (main by default)

    @property
    def key(self) -> str:
        return self.package


# Verify ids with `scoop search <name>` - some may live in other buckets.
APPS = [
    App("Visual Studio Code", "vscode", "Development", "Code editor by Microsoft", bucket="extras"),
    App("VS Code Insiders", "vscode-insiders", "Development", "Nightly build of VS Code", bucket="extras"),
    App("Git", "git", "Development", "Distributed version control"),
    App("NodeJS LTS", "nodejs-lts", "Development", "JavaScript runtime, long-term support"),
    App("Python 3.11", "python311", "Development", "Python interpreter", bucket="versions"),
    App(".NET SDK 8.0", "dotnet-sdk", "Development", "Microsoft .NET software development kit"),
    App("CMake", "cmake", "Development", "Cross-platform build system"),
    App("Opencode", "opencode", "Development", "AI coding agent for the terminal"),
    App("VLC Media Player", "vlc", "Media", "Plays almost any audio or video", bucket="extras"),
    App("ffmpeg", "ffmpeg", "Media", "Convert and stream audio and video"),
    App("yt-dlp", "yt-dlp", "Media", "Download video from the web"),
    App("Firefox", "firefox", "Browsers", "Privacy-minded browser by Mozilla", bucket="extras"),
    App("Google Chrome", "googlechrome", "Browsers", "Browser by Google", bucket="extras"),
    App("LibreWolf", "librewolf", "Browsers", "Hardened Firefox fork", bucket="extras"),
    App("Thorium", "thorium", "Browsers", "Fast Chromium fork", bucket="extras"),
    App("Microsoft Edge", "Microsoft.Edge", "Browsers", "Browser by Microsoft (winget)", manager="winget"),
    App("Obsidian", "obsidian", "Productivity", "Markdown knowledge base", bucket="extras"),
    App("Telegram Desktop", "telegram", "Productivity", "Fast and secure messaging", bucket="extras"),
    App("PowerToys", "powertoys", "Productivity", "Windows power-user utilities", bucket="extras"),
    App("7-Zip", "7zip", "Productivity", "File archiver"),
]
CATEGORIES = ["All", "Development", "Media", "Browsers", "Productivity", "Custom"]

DEFAULT_SELECTION = {
    "vscode", "vscode-insiders", "vlc", "nodejs-lts", "cmake", "python311", "opencode",
    "obsidian", "thorium", "Microsoft.Edge", "telegram", "dotnet-sdk", "ffmpeg", "yt-dlp",
}
PRESETS = {
    "Original list": DEFAULT_SELECTION,
    "Developer": {"vscode", "git", "nodejs-lts", "python311", "dotnet-sdk", "cmake", "opencode"},
    "Everyday": {"firefox", "vlc", "7zip", "telegram", "obsidian", "powertoys"},
    "Media": {"vlc", "ffmpeg", "yt-dlp"},
}


# ───────────────────────────── System helpers ─────────────────────────────
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ps_cmd(command: str) -> list[str]:
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]


def scoop_env() -> dict:
    env = os.environ.copy()
    shims = os.path.join(os.path.expanduser("~"), "scoop", "shims")
    env["PATH"] = shims + os.pathsep + env.get("PATH", "")
    return env


def has_scoop() -> bool:
    return shutil.which("scoop", path=scoop_env()["PATH"]) is not None


def has_winget() -> bool:
    return shutil.which("winget") is not None


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def system_info() -> dict:
    info = {}
    try:
        build = sys.getwindowsversion().build
        info["os"] = ("Windows 11" if build >= 22000 else "Windows 10", f"Build {build}")
    except Exception:
        info["os"] = (platform.system(), platform.release())
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
    except Exception:
        cpu = platform.processor() or "Unknown CPU"
    info["cpu"] = (cpu, f"{os.cpu_count()} threads")
    try:
        m = _MemStatus(); m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        total = m.ullTotalPhys / 2**30
        info["ram"] = (f"{total:.1f} GB", int(m.dwMemoryLoad), f"{m.dwMemoryLoad}% in use")
    except Exception:
        info["ram"] = ("n/a", 0, "")
    try:
        d = shutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        pct = int(d.used / d.total * 100)
        info["disk"] = (f"{d.free / 2**30:.0f} GB free", pct, f"of {d.total / 2**30:.0f} GB")
    except Exception:
        info["disk"] = ("n/a", 0, "")
    return info


# ───────────────────────────── Workers ─────────────────────────────
class Task(QThread):
    log = Signal(str)
    progress = Signal(int, int, str)       # value, total (0 = busy), label
    item_state = Signal(str, str)          # key, running|ok|fail
    done = Signal(list, bool)              # failed names, cancelled
    cancellable = True

    def __init__(self):
        super().__init__()
        self._cancel = False
        self._proc = None

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def cancel(self):
        self._cancel = True
        p = self._proc
        if p and p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           creationflags=NO_WINDOW, capture_output=True)

    def run_ps(self, command: str) -> tuple[int, str]:
        out = []
        self._proc = subprocess.Popen(
            ps_cmd(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=NO_WINDOW, env=scoop_env())
        for line in self._proc.stdout:
            line = line.rstrip()
            out.append(line)
            self.log.emit(line)
        return self._proc.wait(), "\n".join(out)

    def ensure_scoop(self) -> bool:
        if has_scoop():
            self.log.emit("Scoop is ready.")
        else:
            self.log.emit("Installing Scoop...")
            admin = " -RunAsAdmin" if is_admin() else ""
            code, _ = self.run_ps("Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force; "
                                  f"iex \"& {{$(irm get.scoop.sh)}}{admin}\"")
            if code != 0:
                return False
        if not shutil.which("git", path=scoop_env()["PATH"]):
            self.run_ps("scoop install git")   # required to add buckets
        return True


class AppTask(Task):
    def __init__(self, apps: list[App], mode: str):
        super().__init__()
        self.apps, self.mode = apps, mode      # install | uninstall | update

    def run(self):
        failed: list[str] = []
        if self.mode == "update":
            self.progress.emit(0, 0, "Updating installed apps")
            if not has_scoop():
                self.log.emit("[x] Scoop is not installed.")
                self.done.emit(["Scoop"], False); return
            self.run_ps("scoop update; scoop update *")
            self.done.emit([], self.cancelled); return

        if self.mode == "install" and any(a.manager == "scoop" for a in self.apps):
            self.progress.emit(0, 0, "Preparing Scoop")
            if not self.ensure_scoop():
                self.log.emit("[x] Scoop installation failed.")
                self.done.emit([a.name for a in self.apps], False); return
            for b in sorted({a.bucket for a in self.apps if a.bucket and a.manager == "scoop"}):
                self.log.emit(f"Adding bucket '{b}'...")
                self.run_ps(f"scoop bucket add {b}")

        total = len(self.apps)
        verb = "Installing" if self.mode == "install" else "Removing"
        for n, app in enumerate(self.apps):
            if self.cancelled:
                break
            self.progress.emit(n, total, f"{verb} {app.name}")
            self.item_state.emit(app.key, "running")
            self.log.emit(f"\n=== {verb} {app.name} ===")
            if app.manager == "scoop":
                cmd = f"scoop {self.mode} {app.package}"
            elif self.mode == "install":
                cmd = (f"winget install -e --id {app.package} --silent "
                       "--accept-package-agreements --accept-source-agreements")
            else:
                cmd = f"winget uninstall -e --id {app.package} --silent"
            code, _ = self.run_ps(cmd)
            if self.cancelled:
                self.item_state.emit(app.key, "fail"); break
            ok = code == 0
            if not ok:
                failed.append(app.name)
            self.log.emit(f"[{'OK' if ok else 'FAILED'}] {app.name}" + ("" if ok else f" (exit code {code})"))
            self.item_state.emit(app.key, "ok" if ok else "fail")
        self.progress.emit(total, total, "Finished")
        self.done.emit(failed, self.cancelled)


class DriverTask(Task):
    cancellable = False

    def __init__(self, install: bool, restore_point: bool, auto_reboot: bool):
        super().__init__()
        self.install, self.restore_point, self.auto_reboot = install, restore_point, auto_reboot

    def run(self):
        tmp = tempfile.mkdtemp(prefix="autosetup_")
        log_p, code_p, script_p = (os.path.join(tmp, n) for n in ("out.log", "exit.txt", "run.ps1"))
        reboot = "-AutoReboot" if self.auto_reboot else "-IgnoreReboot"
        action = f"Get-WindowsUpdate -AcceptAll {reboot} -Install" if self.install else "Get-WindowsUpdate"
        restore = ("try { Enable-ComputerRestore -Drive $env:SystemDrive; "
                   "Checkpoint-Computer -Description 'AutoSetup' -RestorePointType MODIFY_SETTINGS; "
                   "'Restore point created.' } catch { \"Restore point skipped: $($_.Exception.Message)\" }"
                   if self.install and self.restore_point else "")
        script = f"""
$code = 1
try {{
  & {{
    {restore}
    Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force
    Install-Module PSWindowsUpdate -Force
    Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force
    Import-Module PSWindowsUpdate -Force
    {action}
  }} *>&1 | Out-File -FilePath '{log_p}' -Append -Encoding utf8
  $code = 0
}} catch {{ $_ | Out-File -FilePath '{log_p}' -Append -Encoding utf8 }}
Set-Content -Path '{code_p}' -Value $code
"""
        with open(script_p, "w", encoding="utf-8") as f:
            f.write(script)
        open(log_p, "w").close()

        self.progress.emit(0, 0, "Installing updates" if self.install else "Scanning for updates")
        self.log.emit("Requesting administrator privileges (UAC)...")
        launcher = subprocess.Popen(ps_cmd(
            "Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait "
            f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{script_p}\"'"),
            creationflags=NO_WINDOW)
        with open(log_p, encoding="utf-8-sig", errors="replace") as f:
            while True:
                line = f.readline()
                if line:
                    self.log.emit(line.rstrip()); continue
                if launcher.poll() is not None:
                    break
                time.sleep(0.3)
            for line in f:
                self.log.emit(line.rstrip())
        try:
            code = int(open(code_p).read().strip())
        except Exception:
            code = 1
        self.done.emit([] if code == 0 else ["Windows Update"], False)


class StatusTask(QThread):
    result = Signal(set)

    def run(self):
        found: set[str] = set()
        env = scoop_env()
        try:
            if has_scoop():
                out = subprocess.run(ps_cmd("scoop export"), capture_output=True, text=True,
                                     encoding="utf-8", errors="replace",
                                     creationflags=NO_WINDOW, env=env).stdout
                try:
                    data = json.loads(out[out.index("{"):])
                    for a in data.get("apps", []):
                        found.add((a.get("Name") or a.get("name") or "").lower())
                except Exception:
                    found.update(a.package.lower() for a in APPS if a.manager == "scoop"
                                 and a.package.lower() in out.lower())
            if has_winget():
                for a in APPS:
                    if a.manager == "winget":
                        r = subprocess.run(["winget", "list", "--id", a.package, "-e",
                                            "--accept-source-agreements"], capture_output=True,
                                           creationflags=NO_WINDOW)
                        if r.returncode == 0:
                            found.add(a.package.lower())
        except Exception:
            pass
        self.result.emit(found)


# ───────────────────────────── Widgets ─────────────────────────────
def repolish(w: QWidget):
    w.style().unpolish(w); w.style().polish(w)


def avatar_color(text: str) -> str:
    h = int(hashlib.md5(text.encode()).hexdigest()[:4], 16) % 360
    return QColor.fromHsl(h, 70, 170).name()


class Toast(QLabel):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.fx = QGraphicsOpacityEffect(self); self.setGraphicsEffect(self.fx)
        self.anim = QPropertyAnimation(self.fx, b"opacity", self)
        self.timer = QTimer(self, singleShot=True, timeout=self.fade_out)
        self.hide()

    def show_msg(self, text: str):
        self.setText(text); self.adjustSize()
        p = self.parentWidget()
        self.move(p.width() - self.width() - 32, p.height() - self.height() - 96)
        self.raise_(); self.show()
        self.anim.stop(); self.anim.setDuration(180)
        self.anim.setStartValue(0.0); self.anim.setEndValue(1.0); self.anim.start()
        self.timer.start(3200)

    def fade_out(self):
        self.anim.stop(); self.anim.setDuration(300)
        self.anim.setStartValue(1.0); self.anim.setEndValue(0.0)
        self.anim.finished.connect(self._hide_once); self.anim.start()

    def _hide_once(self):
        self.anim.finished.disconnect(self._hide_once); self.hide()


def page_header(title: str, subtitle: str, right: QWidget | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    col = QVBoxLayout(); col.setSpacing(4)
    t = QLabel(title); t.setObjectName("h1")
    s = QLabel(subtitle); s.setObjectName("muted")
    col.addWidget(t); col.addWidget(s)
    row.addLayout(col); row.addStretch()
    if right:
        row.addWidget(right)
    return row


class StatCard(QFrame):
    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("panel")
        l = QVBoxLayout(self); l.setContentsMargins(20, 18, 20, 18); l.setSpacing(4)
        self.lab = QLabel(label.upper()); self.lab.setObjectName("overline")
        self.value = QLabel("-"); self.value.setObjectName("statValue"); self.value.setWordWrap(True)
        self.sub = QLabel(""); self.sub.setObjectName("muted")
        self.bar = QProgressBar(); self.bar.setObjectName("meter"); self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4); self.bar.hide()
        l.addWidget(self.lab); l.addWidget(self.value); l.addWidget(self.sub); l.addStretch(); l.addWidget(self.bar)

    def set(self, value: str, sub: str = "", pct: int | None = None):
        self.value.setText(value); self.sub.setText(sub)
        if pct is not None:
            self.bar.setValue(pct); self.bar.show()


class ActionCard(QFrame):
    clicked = Signal()

    def __init__(self, num: str, title: str, desc: str, accent: bool = False):
        super().__init__()
        self.setObjectName("action"); self.setProperty("accent", accent)
        self.setProperty("hover", False); self.setCursor(Qt.PointingHandCursor)
        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 22); l.setSpacing(4)
        n = QLabel(num); n.setObjectName("overline")
        t = QLabel(title); t.setObjectName("h2")
        d = QLabel(desc); d.setObjectName("muted"); d.setWordWrap(True)
        l.addWidget(n); l.addStretch(); l.addWidget(t); l.addWidget(d)
        self.setMinimumHeight(112)

    def enterEvent(self, e): self.setProperty("hover", True); repolish(self)
    def leaveEvent(self, e): self.setProperty("hover", False); repolish(self)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class AppCard(QFrame):
    toggled = Signal()

    def __init__(self, app: App):
        super().__init__()
        self.app = app
        self.setObjectName("appCard"); self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", False); self.setProperty("state", "")
        self.setMinimumHeight(88)
        h = QHBoxLayout(self); h.setContentsMargins(16, 14, 16, 14); h.setSpacing(14)
        av = QLabel(app.name[0].upper()); av.setFixedSize(42, 42); av.setAlignment(Qt.AlignCenter)
        av.setStyleSheet(f"background: {avatar_color(app.name)}; color: #15151a; border-radius: 12px;"
                         "font-size: 17px; font-weight: 700;")
        col = QVBoxLayout(); col.setSpacing(2)
        self.name = QLabel(app.name); self.name.setObjectName("cardName")
        self.desc = QLabel(app.desc); self.desc.setObjectName("muted"); self.desc.setWordWrap(True)
        col.addStretch(); col.addWidget(self.name); col.addWidget(self.desc); col.addStretch()
        right = QVBoxLayout(); right.setSpacing(6)
        self.check = QLabel(""); self.check.setObjectName("check"); self.check.setFixedSize(20, 20)
        self.check.setAlignment(Qt.AlignCenter); self.check.setProperty("on", False)
        self.badge = QLabel(""); self.badge.setObjectName("badge"); self.badge.setProperty("state", "")
        right.addWidget(self.check, alignment=Qt.AlignRight); right.addStretch()
        right.addWidget(self.badge, alignment=Qt.AlignRight)
        h.addWidget(av); h.addLayout(col, 1); h.addLayout(right)

    @property
    def selected(self) -> bool:
        return bool(self.property("selected"))

    def set_selected(self, v: bool):
        self.setProperty("selected", v); self.check.setProperty("on", v)
        self.check.setText("\u2713" if v else "")
        repolish(self); repolish(self.check)

    def set_state(self, state: str):
        labels = {"installed": "Installed", "running": "Working...", "ok": "Done", "fail": "Failed", "": ""}
        self.badge.setText(labels.get(state, "")); self.badge.setProperty("state", state)
        self.badge.setVisible(bool(state)); repolish(self.badge)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.set_selected(not self.selected); self.toggled.emit()


# ───────────────────────────── Main window ─────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoSetup"); self.resize(1120, 580); self.setMinimumSize(980, 520)
        self.setWindowIcon(QIcon(LOGO))
        self.settings = QSettings("AutoSetup", "AutoSetup")
        self.task: Task | None = None
        self.status_task: StatusTask | None = None
        self.installed: set[str] = set()
        self.chain_apps = False
        self.cards: dict[str, AppCard] = {}
        self.custom_apps: list[App] = []
        self.category = "All"
        self.log_doc = QPlainTextEdit(); self.log_doc.setReadOnly(True)
        self.log_doc.setMaximumBlockCount(5000)

        self.load_custom()
        root = QWidget(); root.setObjectName("root"); self.setCentralWidget(root)
        outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self.build_sidebar())
        right = QVBoxLayout(); right.setSpacing(0)
        self.stack = QStackedWidget()
        for page in (self.build_dashboard(), self.build_apps(), self.build_drivers(), self.build_activity()):
            self.stack.addWidget(page)
        right.addWidget(self.stack, 1)
        right.addWidget(self.build_statusbar())
        outer.addLayout(right, 1)
        self.toast = Toast(root)

        self.restore_selection()
        self.refresh_info()
        self.refresh_status()
        self.switch_page(0)

    # ── layout builders ──
    def build_sidebar(self) -> QWidget:
        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(230)
        l = QVBoxLayout(side); l.setContentsMargins(18, 20, 18, 16); l.setSpacing(4)
        head = QHBoxLayout(); head.setSpacing(12)
        logo = QLabel(); logo.setFixedSize(42, 42)
        pm = QPixmap(LOGO)
        if not pm.isNull():
            logo.setPixmap(pm.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        names = QVBoxLayout(); names.setSpacing(0)
        brand = QLabel("AutoSetup"); brand.setObjectName("brand")
        tag = QLabel("Windows provisioning"); tag.setObjectName("muted")
        names.addWidget(brand); names.addWidget(tag)
        head.addWidget(logo); head.addLayout(names); head.addStretch()
        l.addLayout(head); l.addSpacing(18)
        self.nav_group = QButtonGroup(self); self.nav_group.setExclusive(True)
        for i, name in enumerate(("Dashboard", "Applications", "Drivers", "Activity")):
            b = QPushButton(name); b.setObjectName("nav"); b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.nav_group.addButton(b, i); l.addWidget(b)
        self.nav_group.idClicked.connect(self.switch_page)
        l.addStretch()
        self.admin_label = QLabel("Administrator" if is_admin() else "Standard user")
        self.admin_label.setObjectName("pill"); self.admin_label.setProperty("on", is_admin())
        l.addWidget(self.admin_label, alignment=Qt.AlignLeft)
        v = QLabel(f"Version {VERSION}"); v.setObjectName("muted"); l.addWidget(v)
        return side

    def build_dashboard(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(36, 24, 36, 16); l.setSpacing(14)
        l.addLayout(page_header("Dashboard", "Overview of this machine and quick actions."))
        grid = QHBoxLayout(); grid.setSpacing(16)
        self.stat_os, self.stat_cpu, self.stat_ram, self.stat_disk = (
            StatCard("System"), StatCard("Processor"), StatCard("Memory"), StatCard("Storage"))
        for s in (self.stat_os, self.stat_cpu, self.stat_ram, self.stat_disk):
            s.setMinimumHeight(104); grid.addWidget(s)
        l.addLayout(grid)

        tools = QFrame(); tools.setObjectName("panel")
        tl = QHBoxLayout(tools); tl.setContentsMargins(20, 14, 20, 14); tl.setSpacing(12)
        lab = QLabel("TOOLING"); lab.setObjectName("overline"); tl.addWidget(lab)
        self.pill_scoop, self.pill_winget, self.pill_admin = QLabel(), QLabel(), QLabel()
        for p in (self.pill_scoop, self.pill_winget, self.pill_admin):
            p.setObjectName("pill"); tl.addWidget(p)
        tl.addStretch()
        self.selected_label = QLabel(""); self.selected_label.setObjectName("muted"); tl.addWidget(self.selected_label)
        l.addWidget(tools)

        row = QHBoxLayout(); row.setSpacing(16)
        full = ActionCard("01", "Full setup", "Update drivers, then install every selected application.", accent=True)
        apps = ActionCard("02", "Applications", "Browse, select and install apps with Scoop and winget.")
        drv = ActionCard("03", "Drivers", "Scan and install drivers through Windows Update.")
        full.clicked.connect(self.full_setup)
        apps.clicked.connect(lambda: self.switch_page(1))
        drv.clicked.connect(lambda: self.switch_page(2))
        for c in (full, apps, drv):
            row.addWidget(c)
        l.addLayout(row); l.addStretch()
        return w

    def build_apps(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(36, 24, 36, 12); l.setSpacing(12)

        more = QPushButton("More"); more.setObjectName("ghostBtn")
        menu = QMenu(self)
        menu.addAction("Add custom Scoop package...", self.add_custom)
        menu.addAction("Export selection...", self.export_selection)
        menu.addAction("Import selection...", self.import_selection)
        menu.addSeparator()
        menu.addAction("Refresh installed status", self.refresh_status)
        more.setMenu(menu)
        l.addLayout(page_header("Applications", "Pick what you need. Installed apps are detected automatically.", more))

        bar = QHBoxLayout(); bar.setSpacing(10)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search apps")
        self.search.setClearButtonEnabled(True); self.search.setMinimumWidth(240)
        self.search.textChanged.connect(self.reflow)
        bar.addWidget(self.search)
        self.chips = QButtonGroup(self); self.chips.setExclusive(True)
        for i, c in enumerate(CATEGORIES):
            b = QPushButton(c); b.setObjectName("chip"); b.setCheckable(True); b.setChecked(i == 0)
            self.chips.addButton(b, i); bar.addWidget(b)
        self.chips.idClicked.connect(self.on_category)
        bar.addStretch()
        preset = QPushButton("Presets"); preset.setObjectName("ghostBtn")
        pm = QMenu(self)
        for name, keys in PRESETS.items():
            pm.addAction(name, lambda k=keys: self.apply_selection(set(k)))
        pm.addSeparator()
        pm.addAction("Select all", lambda: self.apply_selection({c.app.key for c in self.cards.values()}))
        pm.addAction("Select not installed", lambda: self.apply_selection(
            {k for k, c in self.cards.items() if k.lower() not in self.installed}))
        pm.addAction("Clear", lambda: self.apply_selection(set()))
        preset.setMenu(pm); bar.addWidget(preset)
        l.addLayout(bar)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget(); holder.setObjectName("holder")
        self.grid = QGridLayout(holder); self.grid.setContentsMargins(0, 0, 8, 0); self.grid.setSpacing(12)
        scroll.setWidget(holder); l.addWidget(scroll, 1)
        for app in APPS + self.custom_apps:
            self.add_card(app)
        self.empty_label = QLabel("No app matches your search."); self.empty_label.setObjectName("muted")
        self.empty_label.setAlignment(Qt.AlignCenter); self.empty_label.hide()
        l.addWidget(self.empty_label)

        foot = QHBoxLayout(); foot.setSpacing(10)
        self.count_label = QLabel(""); self.count_label.setObjectName("muted")
        foot.addWidget(self.count_label); foot.addStretch()
        self.btn_update = QPushButton("Update apps"); self.btn_update.clicked.connect(lambda: self.run_apps("update"))
        self.btn_remove = QPushButton("Uninstall selected"); self.btn_remove.clicked.connect(lambda: self.run_apps("uninstall"))
        self.btn_install = QPushButton("Install selected"); self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(lambda: self.run_apps("install"))
        for b in (self.btn_update, self.btn_remove, self.btn_install):
            foot.addWidget(b)
        l.addLayout(foot)
        return w

    def build_drivers(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(36, 24, 36, 12); l.setSpacing(12)
        l.addLayout(page_header("Drivers", "Windows Update delivers manufacturer drivers and system updates."))
        opts = QFrame(); opts.setObjectName("panel")
        ol = QVBoxLayout(opts); ol.setContentsMargins(22, 18, 22, 18); ol.setSpacing(10)
        t = QLabel("OPTIONS"); t.setObjectName("overline"); ol.addWidget(t)
        self.opt_restore = QCheckBox("Create a system restore point before installing")
        self.opt_reboot = QCheckBox("Reboot automatically when required")
        self.opt_restore.setChecked(self.settings.value("opt_restore", True, type=bool))
        self.opt_reboot.setChecked(self.settings.value("opt_reboot", False, type=bool))
        ol.addWidget(self.opt_restore); ol.addWidget(self.opt_reboot)
        note = QLabel("Administrator rights are requested through a UAC prompt."); note.setObjectName("muted")
        ol.addWidget(note)
        l.addWidget(opts)
        console = QPlainTextEdit(); console.setObjectName("console"); console.setReadOnly(True)
        console.setDocument(self.log_doc.document()); self.drv_console = console
        l.addWidget(console, 1)
        row = QHBoxLayout(); row.addStretch()
        self.btn_scan = QPushButton("Scan for updates"); self.btn_scan.clicked.connect(lambda: self.run_drivers(False))
        self.btn_drivers = QPushButton("Install updates"); self.btn_drivers.setObjectName("primary")
        self.btn_drivers.clicked.connect(lambda: self.run_drivers(True))
        row.addWidget(self.btn_scan); row.addWidget(self.btn_drivers)
        l.addLayout(row)
        return w

    def build_activity(self) -> QWidget:
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(36, 24, 36, 12); l.setSpacing(12)
        row = QHBoxLayout(); row.setSpacing(8)
        save = QPushButton("Save log..."); save.clicked.connect(self.save_log)
        clear = QPushButton("Clear"); clear.clicked.connect(self.log_doc.clear)
        row.addWidget(clear); row.addWidget(save)
        holder = QWidget(); holder.setLayout(row)
        l.addLayout(page_header("Activity", "Live output of every task.", holder))
        console = QPlainTextEdit(); console.setObjectName("console"); console.setReadOnly(True)
        console.setDocument(self.log_doc.document()); l.addWidget(console, 1)
        return w

    def build_statusbar(self) -> QWidget:
        self.status = QFrame(); self.status.setObjectName("statusbar"); self.status.hide()
        h = QHBoxLayout(self.status); h.setContentsMargins(44, 12, 44, 12); h.setSpacing(16)
        self.status_text = QLabel(""); self.status_text.setMinimumWidth(240)
        self.progress = QProgressBar(); self.progress.setObjectName("meter"); self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.clicked.connect(self.cancel_task)
        h.addWidget(self.status_text); h.addWidget(self.progress, 1); h.addWidget(self.btn_cancel)
        return self.status

    # ── navigation ──
    def switch_page(self, i: int):
        self.nav_group.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        page = self.stack.currentWidget()
        fx = QGraphicsOpacityEffect(page); page.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", page)
        anim.setDuration(240); anim.setStartValue(0.0); anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._anim = anim

    # ── dashboard data ──
    def refresh_info(self):
        info = system_info()
        self.stat_os.set(*info["os"])
        self.stat_cpu.set(*info["cpu"])
        self.stat_ram.set(info["ram"][0], info["ram"][2], info["ram"][1])
        self.stat_disk.set(info["disk"][0], info["disk"][2], info["disk"][1])
        for pill, text, on in ((self.pill_scoop, "Scoop " + ("ready" if has_scoop() else "not installed"), has_scoop()),
                               (self.pill_winget, "winget " + ("ready" if has_winget() else "missing"), has_winget()),
                               (self.pill_admin, "Elevated" if is_admin() else "Standard user", is_admin())):
            pill.setText(text); pill.setProperty("on", on); repolish(pill)

    # ── app grid ──
    def add_card(self, app: App):
        c = AppCard(app); c.toggled.connect(self.on_selection_changed)
        self.cards[app.key] = c
        self.reflow()

    def reflow(self, *_):
        while self.grid.count():
            self.grid.takeAt(0)
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        n = 0
        for card in self.cards.values():
            a = card.app
            ok = (self.category in ("All", a.category)) and (not q or q in a.name.lower() or q in a.desc.lower())
            card.setVisible(ok)
            if ok:
                self.grid.addWidget(card, n // 2, n % 2); n += 1
        self.grid.setRowStretch(n // 2 + 1, 1)
        for c in range(2):
            self.grid.setColumnStretch(c, 1)
        if hasattr(self, "empty_label"):
            self.empty_label.setVisible(n == 0)

    def on_category(self, i: int):
        self.category = CATEGORIES[i]; self.reflow()

    def selected_apps(self) -> list[App]:
        return [c.app for c in self.cards.values() if c.selected]

    def apply_selection(self, keys: set[str]):
        for k, c in self.cards.items():
            c.set_selected(k in keys)
        self.on_selection_changed()

    def on_selection_changed(self):
        n = len(self.selected_apps())
        self.count_label.setText(f"{n} selected")
        self.selected_label.setText(f"{n} apps selected")
        self.settings.setValue("selected", [a.key for a in self.selected_apps()])

    def restore_selection(self):
        saved = self.settings.value("selected", None)
        keys = set(saved) if isinstance(saved, list) else (set(saved.split()) if isinstance(saved, str) else DEFAULT_SELECTION)
        self.apply_selection(keys)

    def update_badges(self):
        for k, c in self.cards.items():
            c.set_state("installed" if k.lower() in self.installed else "")

    def refresh_status(self):
        if self.status_task and self.status_task.isRunning():
            return
        self.status_task = StatusTask()
        self.status_task.result.connect(lambda s: (setattr(self, "installed", s), self.update_badges()))
        self.status_task.start()

    # ── custom apps / import / export ──
    def load_custom(self):
        try:
            raw = json.loads(self.settings.value("custom", "[]"))
            self.custom_apps = [App(r["name"], r["package"], "Custom", f"Scoop package {r['package']}",
                                    bucket=r.get("bucket", "")) for r in raw]
        except Exception:
            self.custom_apps = []

    def add_custom(self):
        text, ok = QInputDialog.getText(self, "Add custom package",
                                        "Scoop package, e.g. 'ripgrep' or 'extras/zoom':")
        text = text.strip()
        if not ok or not text:
            return
        bucket, _, pkg = text.rpartition("/")
        app = App(pkg, pkg, "Custom", f"Scoop package {text}", bucket=bucket)
        if app.key in self.cards:
            self.toast.show_msg("Already in the list"); return
        self.custom_apps.append(app)
        self.settings.setValue("custom", json.dumps(
            [{"name": a.name, "package": a.package, "bucket": a.bucket} for a in self.custom_apps]))
        self.add_card(app); self.cards[app.key].set_selected(True); self.on_selection_changed()
        self.toast.show_msg(f"Added {pkg}")

    def export_selection(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export selection", "autosetup.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"apps": [a.key for a in self.selected_apps()]}, f, indent=2)
            self.toast.show_msg("Selection exported")

    def import_selection(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import selection", "", "JSON (*.json)")
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    self.apply_selection(set(json.load(f)["apps"]))
                self.toast.show_msg("Selection imported")
            except Exception:
                self.toast.show_msg("Invalid selection file")

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save log", "autosetup.log", "Log (*.log *.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_doc.toPlainText())
            self.toast.show_msg("Log saved")

    # ── task orchestration ──
    def busy(self) -> bool:
        if self.task and self.task.isRunning():
            self.toast.show_msg("A task is already running"); return True
        return False

    def start_task(self, task: Task):
        self.task = task
        task.log.connect(self.log_doc.appendPlainText)
        task.progress.connect(self.on_progress)
        task.item_state.connect(lambda k, s: self.cards[k].set_state(s) if k in self.cards else None)
        task.done.connect(self.on_done)
        self.btn_cancel.setVisible(task.cancellable)
        self.status.show(); self.set_buttons(False)
        task.start()

    def set_buttons(self, enabled: bool):
        for b in (self.btn_install, self.btn_remove, self.btn_update, self.btn_scan, self.btn_drivers):
            b.setEnabled(enabled)

    def on_progress(self, v: int, total: int, text: str):
        self.status_text.setText(text)
        self.progress.setRange(0, total); self.progress.setValue(v)

    def cancel_task(self):
        if self.task:
            self.btn_cancel.setEnabled(False); self.status_text.setText("Cancelling...")
            self.task.cancel()

    def run_apps(self, mode: str):
        if self.busy():
            return
        apps = self.selected_apps()
        if mode != "update" and not apps:
            self.toast.show_msg("Select at least one app"); return
        if mode == "uninstall":
            apps = [a for a in apps if a.key.lower() in self.installed] or apps
        self.log_doc.appendPlainText(f"\n--- {mode.upper()} ---")
        self.start_task(AppTask(apps, mode))

    def run_drivers(self, install: bool):
        if self.busy():
            return
        self.settings.setValue("opt_restore", self.opt_restore.isChecked())
        self.settings.setValue("opt_reboot", self.opt_reboot.isChecked())
        self.log_doc.appendPlainText("\n--- DRIVERS ---")
        self.start_task(DriverTask(install, self.opt_restore.isChecked(), self.opt_reboot.isChecked()))

    def full_setup(self):
        if self.busy():
            return
        if not self.selected_apps():
            self.toast.show_msg("Select at least one app first"); self.switch_page(1); return
        self.chain_apps = True
        self.run_drivers(True)

    def on_done(self, failed: list, cancelled: bool):
        self.btn_cancel.setEnabled(True)
        self.set_buttons(True)
        if self.chain_apps and not cancelled and isinstance(self.task, DriverTask):
            self.chain_apps = False
            self.log_doc.appendPlainText("\nDrivers done. Continuing with applications...")
            QTimer.singleShot(300, lambda: self.run_apps("install")); return
        self.chain_apps = False
        self.status.hide()
        if cancelled:
            msg = "Task cancelled"
        elif failed:
            msg = "Finished with errors: " + ", ".join(failed[:3]) + ("..." if len(failed) > 3 else "")
        else:
            msg = "Everything completed successfully"
        self.log_doc.appendPlainText(f"\n{msg}.")
        self.toast.show_msg(msg)
        self.refresh_info(); self.refresh_status()

    # ── window events ──
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.move(self.centralWidget().width() - self.toast.width() - 32,
                            self.centralWidget().height() - self.toast.height() - 96)

    def closeEvent(self, e):
        for t in (self.task, self.status_task):
            if t and t.isRunning():
                if isinstance(t, Task):
                    t.cancel()
                if not t.wait(2500):
                    t.terminate(); t.wait(500)
        super().closeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        try:   # native dark title bar (Windows 10 20H1+ / 11)
            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(0x000D0B0B)), 4)
        except Exception:
            pass


# ───────────────────────────── Stylesheet ─────────────────────────────
STYLE = f"""
* {{ font-family: 'Segoe UI Variable Text', 'Segoe UI'; color: {ACCENT}; outline: none; font-size: 13px; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QStackedWidget, QStackedWidget > QWidget, QWidget#holder, QScrollArea {{ background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#h1 {{ font-size: 28px; font-weight: 600; }}
QLabel#h2 {{ font-size: 19px; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#overline {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 2px; }}
QLabel#statValue {{ font-size: 18px; font-weight: 600; }}
QLabel#cardName {{ font-size: 14px; font-weight: 600; }}
QLabel#brand {{ font-size: 21px; font-weight: 700; letter-spacing: 1px; }}

QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QPushButton#nav {{
  text-align: left; padding: 11px 16px; border: none; border-radius: 10px;
  color: {MUTED}; font-size: 14px; background: transparent;
}}
QPushButton#nav:hover {{ background: rgba(253,246,227,0.05); color: {ACCENT}; }}
QPushButton#nav:checked {{ background: rgba(253,246,227,0.10); color: {ACCENT}; font-weight: 600; }}

QLabel#pill {{
  padding: 4px 12px; border-radius: 11px; border: 1px solid {BORDER}; color: {MUTED}; font-size: 12px;
}}
QLabel#pill[on="true"] {{ border-color: rgba(253,246,227,0.45); color: {ACCENT}; background: rgba(253,246,227,0.06); }}

QFrame#panel {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#panel QLabel {{ border: none; }}
QFrame#action {{
  background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #17171c, stop:1 #121215);
  border: 1px solid {BORDER}; border-radius: 16px;
}}
QFrame#action[hover="true"] {{ border-color: rgba(253,246,227,0.6); }}
QFrame#action[accent="true"] {{
  background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #fdf6e3, stop:1 #e9dfc2); border: 1px solid #fdf6e3;
}}
QFrame#action[accent="true"] QLabel {{ color: #1a1810; }}
QFrame#action[accent="true"] QLabel#overline {{ color: #6e6850; }}
QFrame#action QLabel {{ border: none; }}

QFrame#appCard {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#appCard:hover {{ background: {CARD_HOVER}; border-color: #34343c; }}
QFrame#appCard[selected="true"] {{ border: 1px solid rgba(253,246,227,0.75); background: #18181a; }}
QFrame#appCard QLabel {{ border: none; }}
QLabel#check {{ border: 1px solid #3a3a42; border-radius: 10px; color: #15151a; font-size: 12px; font-weight: 700; }}
QLabel#check[on="true"] {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#badge {{ font-size: 11px; padding: 2px 9px; border-radius: 9px; color: {MUTED}; border: 1px solid {BORDER}; }}
QLabel#badge[state="installed"] {{ color: {OK}; border-color: rgba(168,213,162,0.4); }}
QLabel#badge[state="ok"] {{ color: {OK}; border-color: rgba(168,213,162,0.4); }}
QLabel#badge[state="fail"] {{ color: {ERR}; border-color: rgba(232,144,138,0.4); }}
QLabel#badge[state="running"] {{ color: {ACCENT}; border-color: rgba(253,246,227,0.5); }}

QPushButton {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; padding: 9px 20px;
}}
QPushButton:hover {{ border-color: rgba(253,246,227,0.5); }}
QPushButton:pressed {{ background: #1c1c21; }}
QPushButton:disabled {{ color: #55534c; border-color: #1a1a1e; background: #101013; }}
QPushButton#primary {{
  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #fdf6e3, stop:1 #eadfc0);
  color: #1a1810; border: none; font-weight: 600; padding: 10px 26px;
}}
QPushButton#primary:hover {{ background: #ffffff; }}
QPushButton#primary:disabled {{ background: #2a2923; color: #6d6b60; }}
QPushButton#ghostBtn {{ background: transparent; }}
QPushButton#ghostBtn::menu-indicator {{ width: 0; }}
QPushButton#chip {{ padding: 6px 14px; border-radius: 15px; background: transparent; color: {MUTED}; }}
QPushButton#chip:hover {{ color: {ACCENT}; }}
QPushButton#chip:checked {{ background: rgba(253,246,227,0.12); color: {ACCENT}; border-color: rgba(253,246,227,0.4); }}

QLineEdit {{
  background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; padding: 9px 14px;
  selection-background-color: {ACCENT}; selection-color: #1a1810;
}}
QLineEdit:focus {{ border-color: rgba(253,246,227,0.6); }}

QPlainTextEdit {{ background: #09090b; border: 1px solid {BORDER}; border-radius: 12px; padding: 12px;
  font-family: 'Cascadia Mono', Consolas; font-size: 12px; color: #cfc9b6;
  selection-background-color: {ACCENT}; selection-color: #1a1810; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid #3a3a42; border-radius: 5px; background: transparent; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QProgressBar#meter {{ background: #232328; border: none; border-radius: 2px; }}
QProgressBar#meter::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QFrame#statusbar {{ background: {SIDEBAR}; border-top: 1px solid {BORDER}; }}
QLabel#toast {{
  background: #1d1d22; border: 1px solid rgba(253,246,227,0.4); border-radius: 12px; padding: 12px 20px;
}}

QMenu {{ background: #16161a; border: 1px solid #2c2c33; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 26px 8px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(253,246,227,0.12); }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 8px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c2c33; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #44444d; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: transparent; }}
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(LOGO))
    try:   # own taskbar identity so Windows shows our icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("autosetup.app")
    except Exception:
        pass
    win = MainWindow(); win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
