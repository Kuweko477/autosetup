import os
import shutil
import subprocess
import sys
from colorama import Fore, init
import ctypes


# ── List of apps to install (display name, choco package id) ──────────────────
APPS = [
    ("Visual Studio Code",          "vscode.install"),
    ("Visual Studio Code Insiders", "vscode-insiders"),
    ("VLC Media Player",            "vlc"),
    ("NodeJS LTS",                  "nodejs-lts"),
    ("CMake",                       "cmake"),
    ("Python 3.11",                 "python311"),
    ("Opencode",                    "opencode"),
    ("Obsidian",                    "obsidian"),
    ("Thorium",                     "thorium"),
    ("Microsoft Edge",              "microsoft-edge"),
    ("Telegram Desktop",            "telegram"),
    ("Dotnet SDK 8.0",              "dotnet-sdk"),
    ("ffmpeg",                      "ffmpeg"),
    ("yt-dlp",                      "yt-dlp"),
]


def is_admin():
    """Check if the script is running with administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate_if_needed():
    """Re-launch the script as admin if not already elevated."""
    if not is_admin():
        print("Requesting administrator privileges...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit(0)


def run_powershell(command):
    """
    Runs a PowerShell command in the current (already elevated) process.
    Streams output in real time and returns the exit code.
    """
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command", command,
        ],
        check=False,
    )
    return result.returncode


def print_user_ascii():
    print("\n\n")
    ascii_art = r"""
     █████╗ ██╗   ██╗████████╗ ██████╗     ███████╗███████╗████████╗██╗   ██╗██████╗ 
    ██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗    ██╔════╝██╔════╝╚══██╔══╝██║   ██║██╔══██╗
    ███████║██║   ██║   ██║   ██║   ██║    ███████╗█████╗     ██║   ██║   ██║██████╔╝
    ██╔══██║██║   ██║   ██║   ██║   ██║    ╚════██║██╔══╝     ██║   ██║   ██║██╔═══╝ 
    ██║  ██║╚██████╔╝   ██║   ╚██████╔╝    ███████║███████╗   ██║   ╚██████╔╝██║     
    ╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝     ╚══════╝╚══════╝   ╚═╝    ╚═════╝ ╚═╝     
    """
    try:
        terminal_size = shutil.get_terminal_size().columns
    except Exception:
        terminal_size = 80

    for line in ascii_art.splitlines():
        print(line.center(terminal_size))

    print("\n\n")


def print_progress(done: list[str], remaining: list[str]):
    """Print installed (green ✓) and pending (yellow) apps."""
    for name in done:
        print(Fore.GREEN + f"\t✓ {name}")
    for name in remaining:
        print(Fore.YELLOW + f"\t  {name}")
    print()


def main():
    init(autoreset=True)
    elevate_if_needed()

    ctypes.windll.kernel32.SetConsoleTitleW(
        "Auto Setup Software - Install all necessary apps"
    )

    print_user_ascii()

    # ── Step 1: Install Chocolatey ─────────────────────────────────────────────
    print(Fore.GREEN + "First, let's install Chocolatey...\n")
    choco_script = (
        "Set-ExecutionPolicy Bypass -Scope Process -Force; "
        "[System.Net.ServicePointManager]::SecurityProtocol = "
        "[System.Net.ServicePointManager]::SecurityProtocol -bor 3072; "
        "iex ((New-Object System.Net.WebClient).DownloadString("
        "'https://community.chocolatey.org/install.ps1'))"
    )
    run_powershell(choco_script)

    os.system("cls")
    print_user_ascii()

    # ── Step 2: Install apps one by one ───────────────────────────────────────
    app_names = [name for name, _ in APPS]
    print(Fore.CYAN + "The following apps will be installed:\n")
    print_progress(done=[], remaining=app_names)

    installed: list[str] = []
    failed: list[str] = []

    for display_name, choco_id in APPS:
        print(Fore.CYAN + f"Installing {display_name}...")
        exit_code = run_powershell(f"choco install -y {choco_id}")

        if exit_code == 0:
            installed.append(display_name)
            print(Fore.GREEN + f"[✓] {display_name} installed.\n")
        else:
            installed.append(f"{display_name} (FAILED — code {exit_code})")
            failed.append(display_name)
            print(Fore.RED + f"[✗] {display_name} failed (exit code {exit_code}).\n")

        remaining = [n for n in app_names if n not in installed and n not in failed]
        print_progress(done=installed, remaining=remaining)

    # ── Summary ────────────────────────────────────────────────────────────────
    if not failed:
        print(Fore.GREEN + "\n\nAll apps installed successfully!")
    else:
        print(Fore.YELLOW + "\n\nInstallation complete with some errors:")
        for name in failed:
            print(Fore.RED + f"  ✗ {name}")
        print(Fore.YELLOW + "Try re-running for the failed apps, or install them manually.")


if __name__ == "__main__":
    main()
