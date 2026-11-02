"""Platform-specific utilities for SuperCollider process management."""

import os
import shutil
import subprocess
import sys

_MACOS_SCLANG_PATH = "/Applications/SuperCollider.app/Contents/MacOS/sclang"


def find_sclang() -> str:
    """Locate the sclang binary.

    Resolution order:
        1. PATH lookup (shutil.which)
        2. macOS well-known path (/Applications/SuperCollider.app)

    Returns:
        Absolute path to sclang binary.

    Raises:
        FileNotFoundError: If sclang is not found, with platform-specific guidance.
    """
    path_result = shutil.which("sclang")
    if path_result:
        return path_result

    if sys.platform == "darwin" and os.path.isfile(_MACOS_SCLANG_PATH):
        return _MACOS_SCLANG_PATH

    raise FileNotFoundError(_build_not_found_message())


def _build_not_found_message() -> str:
    """Build a platform-specific error message with resolution guidance."""
    if sys.platform == "darwin":
        return (
            "sclang not found.\n"
            "Searched: PATH, /Applications/SuperCollider.app\n\n"
            "Solutions:\n"
            "  1. Install SuperCollider from https://supercollider.github.io/downloads\n"
            "  2. Add SuperCollider directory to PATH:\n"
            '     export PATH="/Applications/SuperCollider.app/Contents/MacOS:$PATH"'
        )
    elif sys.platform == "win32":
        return (
            "sclang not found.\n"
            "Searched: PATH\n\n"
            "Solutions:\n"
            "  1. Install SuperCollider from https://supercollider.github.io/downloads\n"
            "  2. Ensure the SuperCollider install directory is in your PATH"
        )
    else:
        return (
            "sclang not found.\n"
            "Searched: PATH\n\n"
            "Solutions:\n"
            "  1. Install SuperCollider: sudo apt install supercollider"
        )


def build_sclang_command(startup_file: str | None = None) -> list[str]:
    """Build the sclang command for the current platform.

    Args:
        startup_file: Optional .scd/.sc file to execute on startup.

    Returns:
        Command list suitable for subprocess.Popen.

    Raises:
        FileNotFoundError: If sclang is not found.
    """
    sclang_path = find_sclang()

    if sys.platform == "linux":
        cmd = ["pw-jack", sclang_path]
    else:
        cmd = [sclang_path]

    if startup_file:
        cmd.append(startup_file)
    return cmd


def build_kill_commands(pid: int) -> list[list[str]]:
    """Build platform-specific force-kill commands for sclang.

    Args:
        pid: Process ID to kill.

    Returns:
        List of command lists to execute in order.
    """
    if sys.platform == "linux":
        return [
            ["kill", "-9", str(pid)],
            ["pkill", "-9", "sclang"],
        ]
    elif sys.platform == "darwin":
        return [
            ["kill", "-9", str(pid)],
        ]
    else:  # win32
        return [
            ["taskkill", "/T", "/F", "/PID", str(pid)],
        ]


def cleanup_scsynth() -> None:
    """Kill any remaining scsynth processes (all platforms)."""
    if sys.platform == "win32":
        cmd = ["taskkill", "/F", "/IM", "scsynth.exe"]
    else:
        cmd = ["pkill", "-9", "scsynth"]

    try:
        subprocess.run(cmd, capture_output=True, timeout=2.0)
    except Exception:
        pass


def is_audio_routing_supported() -> bool:
    """Check if PipeWire/PulseAudio audio routing is supported."""
    return sys.platform == "linux"


def get_popen_kwargs() -> dict:
    """Get platform-specific kwargs for subprocess.Popen.

    Returns:
        Dict of kwargs to pass to Popen constructor.
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        return {"start_new_session": True}
