"""SuperCollider (sclang) process lifecycle management."""

import logging
import signal
import subprocess
import sys
import threading
from enum import Enum
from pathlib import Path
from typing import Callable

from . import platform_utils

logger = logging.getLogger(__name__)


class SclangState(Enum):
    STOPPED = 0
    STARTING = 1
    RUNNING = 2
    STOPPING = 3


class SclangProcess:
    """Manages the sclang subprocess lifecycle.

    This class is independent of the nonoha node system.
    State changes and log output are communicated via callbacks.
    """

    def __init__(
        self,
        on_state_changed: Callable[[SclangState], None],
        on_log: Callable[[str], None],
        on_error: Callable[[str], None],
    ):
        self._on_state_changed = on_state_changed
        self._on_log = on_log
        self._on_error = on_error

        self._state = SclangState.STOPPED
        self._process: subprocess.Popen | None = None
        self._worker_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def state(self) -> SclangState:
        return self._state

    def start(
        self,
        startup_file: str | None = None,
        cwd: Path | None = None,
    ) -> None:
        """Request sclang process start. Non-blocking.

        Args:
            startup_file: Optional .scd/.sc file to execute.
            cwd: Working directory for sclang process.
        """
        with self._lock:
            if self._state != SclangState.STOPPED:
                self._on_error(
                    f"Cannot start: current state is {self._state.name}"
                )
                return

            self._set_state(SclangState.STARTING)

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker,
            args=(startup_file, cwd),
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self) -> None:
        """Request sclang process stop. Non-blocking."""
        with self._lock:
            if self._state not in (SclangState.RUNNING, SclangState.STARTING):
                return

            self._set_state(SclangState.STOPPING)

        self._stop_event.set()

    def execute_code(self, code: str) -> None:
        """Send SC code to sclang stdin.

        Args:
            code: SuperCollider code string.
        """
        with self._lock:
            if self._state != SclangState.RUNNING:
                self._on_error(
                    f"Cannot execute code: state is {self._state.name}"
                )
                return
            process = self._process

        if process is None or process.stdin is None:
            self._on_error("No stdin available")
            return

        try:
            process.stdin.write(code + "\n")
            process.stdin.flush()
            self._on_log(f"[EXEC] {code}")
        except (BrokenPipeError, OSError) as e:
            self._on_error(f"Failed to write to stdin: {e}")

    def shutdown(self, timeout: float = 5.0) -> None:
        """Synchronous shutdown for finalize(). Blocks until stopped.

        Args:
            timeout: Maximum time to wait for worker thread to finish.
        """
        self._stop_event.set()

        with self._lock:
            process = self._process

        if process is not None and process.poll() is None:
            self._terminate_process(process)

        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)

        self._join_reader_threads(timeout=2.0)

        with self._lock:
            self._process = None
            if self._state != SclangState.STOPPED:
                self._set_state(SclangState.STOPPED)

    # -- Worker thread --

    def _worker(
        self,
        startup_file: str | None,
        cwd: Path | None,
    ) -> None:
        """Main worker thread: start process, monitor, handle stop."""
        process: subprocess.Popen | None = None

        try:
            # Build command
            cmd = platform_utils.build_sclang_command(startup_file)
            popen_kwargs = platform_utils.get_popen_kwargs()

            self._on_log(f"Starting sclang: {' '.join(cmd)}")
            if cwd:
                self._on_log(f"Working directory: {cwd}")

            # Spawn process
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=True,
                **popen_kwargs,
            )

            with self._lock:
                self._process = process

            # Start output readers
            self._start_reader_threads(process)

            self._on_log(f"sclang started (PID: {process.pid})")

            with self._lock:
                self._set_state(SclangState.RUNNING)

        except FileNotFoundError as e:
            self._on_error(f"sclang not found: {e}")
            with self._lock:
                self._set_state(SclangState.STOPPED)
            return
        except Exception as e:
            self._on_error(f"Failed to start sclang: {e}")
            with self._lock:
                self._set_state(SclangState.STOPPED)
            return

        # Monitor loop
        while not self._stop_event.is_set():
            exit_code = process.poll()
            if exit_code is not None:
                # Process exited unexpectedly
                self._on_error(
                    f"sclang exited unexpectedly (code: {exit_code})"
                )
                self._join_reader_threads(timeout=1.0)
                with self._lock:
                    self._process = None
                    self._set_state(SclangState.STOPPED)
                return

            self._stop_event.wait(0.1)

        # Stop requested — graceful shutdown
        self._terminate_process(process)
        self._join_reader_threads(timeout=2.0)

        with self._lock:
            self._process = None
            self._set_state(SclangState.STOPPED)

    def _terminate_process(self, process: subprocess.Popen) -> None:
        """Graceful shutdown: 0.exit, then terminate, then force kill."""
        if process.poll() is not None:
            platform_utils.cleanup_scsynth()
            return

        # Step 1: Send 0.exit via stdin (what the SuperCollider IDE does on stop)
        try:
            if process.stdin is not None:
                process.stdin.write("0.exit\n")
                process.stdin.flush()
                self._on_log("Sent 0.exit to sclang")
        except (BrokenPipeError, OSError):
            pass

        # Step 2: Wait 1 second for graceful exit
        try:
            process.wait(timeout=1.0)
            self._on_log("sclang exited gracefully")
            platform_utils.cleanup_scsynth()
            return
        except subprocess.TimeoutExpired:
            pass

        # Step 3: SIGTERM (Unix) — on Windows, skip to force kill
        if sys.platform != "win32":
            try:
                process.send_signal(signal.SIGTERM)
                self._on_log("Sent SIGTERM to sclang")
            except (ProcessLookupError, OSError):
                platform_utils.cleanup_scsynth()
                return

            # Step 4: Wait 200ms
            try:
                process.wait(timeout=0.2)
                self._on_log("sclang terminated after SIGTERM")
                platform_utils.cleanup_scsynth()
                return
            except subprocess.TimeoutExpired:
                pass

        # Step 5: Force kill sclang
        pid = process.pid
        self._on_log(f"Force killing sclang (PID: {pid})")

        kill_commands = platform_utils.build_kill_commands(pid)
        for cmd in kill_commands:
            try:
                subprocess.run(cmd, capture_output=True, timeout=2.0)
            except Exception:
                pass

        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self._on_error("Failed to kill sclang process")

        # Step 6: Always cleanup scsynth (may remain as orphan)
        platform_utils.cleanup_scsynth()

    # -- Output reader threads --

    def _start_reader_threads(self, process: subprocess.Popen) -> None:
        """Start daemon threads for reading stdout and stderr."""
        if process.stdout is not None:
            self._stdout_thread = threading.Thread(
                target=self._read_output,
                args=(process.stdout, "stdout"),
                daemon=True,
            )
            self._stdout_thread.start()

        if process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._read_output,
                args=(process.stderr, "stderr"),
                daemon=True,
            )
            self._stderr_thread.start()

    def _join_reader_threads(self, timeout: float = 2.0) -> None:
        """Wait for reader threads to finish."""
        if self._stdout_thread is not None and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=timeout)
        self._stdout_thread = None

        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=timeout)
        self._stderr_thread = None

    def _read_output(self, stream, stream_name: str) -> None:
        """Read lines from a process output stream and forward via callback."""
        try:
            for line in stream:
                line = line.rstrip("\n\r")
                if line:
                    self._on_log(f"[{stream_name}] {line}")
        except (ValueError, OSError):
            # Stream closed
            pass

    # -- State management --

    def _set_state(self, new_state: SclangState) -> None:
        """Update state and notify via callback. Must be called with lock held."""
        self._state = new_state
        self._on_state_changed(new_state)
