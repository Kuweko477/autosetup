import os
import shutil
import subprocess
import sys
from colorama import Fore, init
import ctypes


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


def main():
    init(autoreset=True)
    elevate_if_needed()

    ctypes.windll.kernel32.SetConsoleTitleW(
        "Auto Setup Software - Update all drivers"
    )

    print_user_ascii()
    print(Fore.YELLOW + "[1] - Let's update drivers first...\n")

    # Run all driver update steps in a single elevated PowerShell session
    driver_script = "; ".join([
        "Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force",
        "Install-Module PSWindowsUpdate -Force",
        "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force",
        "Import-Module PSWindowsUpdate -Force",
        "Get-WindowsUpdate -AcceptAll -AutoReboot -Install",
    ])

    exit_code = run_powershell(driver_script)

    if exit_code == 0:
        print("\n" + Fore.GREEN + "[✓] - Drivers successfully updated.")
    else:
        print("\n" + Fore.RED + f"[✗] - Driver update finished with exit code {exit_code}.")

    print(Fore.YELLOW + "We recommend you run app.py (or app.exe) next.")


if __name__ == "__main__":
    main()
