"""Linux audio routing for SuperCollider via PipeWire/PulseAudio.

Creates virtual audio devices and connects SuperCollider outputs
to enable audio capture (e.g., from browser) and hardware output.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class AudioRouter:
    """Manages PipeWire/PulseAudio virtual audio devices for SuperCollider."""

    def __init__(self):
        self._speaker_module_id: int | None = None
        self._mic_module_id: int | None = None

    async def setup(self) -> bool:
        """Create virtual audio devices and connect SuperCollider outputs.

        Returns:
            True on success, False on failure.
        """
        try:
            # Step 1: Create virtual speaker (null sink)
            rc, stdout, _ = await self._run_command([
                "pactl", "load-module", "module-null-sink",
                "sink_name=sc_virtual_speaker",
                'sink_properties=device.description="SC_Virtual_Speaker"',
            ])
            if rc != 0:
                logger.error("Failed to create virtual speaker")
                return False
            self._speaker_module_id = int(stdout.strip())
            logger.info(
                f"Created virtual speaker (module: {self._speaker_module_id})"
            )

            # Step 2: Create virtual microphone (remap source)
            rc, stdout, _ = await self._run_command([
                "pactl", "load-module", "module-remap-source",
                "source_name=sc_virtual_mic",
                "master=sc_virtual_speaker.monitor",
                'source_properties=device.description="SuperCollider_Virtual_Mic"',
            ])
            if rc != 0:
                logger.error("Failed to create virtual microphone")
                return False
            self._mic_module_id = int(stdout.strip())
            logger.info(
                f"Created virtual microphone (module: {self._mic_module_id})"
            )

            # Step 3: Wait for SuperCollider to appear in PipeWire
            if not await self._wait_for_supercollider():
                logger.warning(
                    "SuperCollider not detected in PipeWire; "
                    "skipping pw-link connections"
                )
                return True  # Modules created but links not made

            # Step 4: Connect SuperCollider outputs to virtual speaker
            await self._run_command([
                "pw-link",
                "SuperCollider:out_1",
                "sc_virtual_speaker:playback_FL",
            ])
            await self._run_command([
                "pw-link",
                "SuperCollider:out_2",
                "sc_virtual_speaker:playback_FR",
            ])
            logger.info("Connected SuperCollider outputs to virtual speaker")

            return True

        except Exception as e:
            logger.error(f"Audio routing setup failed: {e}")
            return False

    async def teardown(self) -> None:
        """Unload virtual audio devices in reverse order."""
        try:
            if self._mic_module_id is not None:
                await self._run_command([
                    "pactl", "unload-module", str(self._mic_module_id),
                ])
                logger.info(
                    f"Unloaded virtual mic (module: {self._mic_module_id})"
                )
                self._mic_module_id = None

            if self._speaker_module_id is not None:
                await self._run_command([
                    "pactl", "unload-module", str(self._speaker_module_id),
                ])
                logger.info(
                    f"Unloaded virtual speaker "
                    f"(module: {self._speaker_module_id})"
                )
                self._speaker_module_id = None

        except Exception as e:
            logger.error(f"Audio routing teardown failed: {e}")

    async def _wait_for_supercollider(
        self, max_attempts: int = 10, interval: float = 0.5
    ) -> bool:
        """Poll PipeWire for SuperCollider presence.

        Args:
            max_attempts: Maximum number of poll attempts.
            interval: Seconds between attempts.

        Returns:
            True if SuperCollider is detected.
        """
        for i in range(max_attempts):
            rc, stdout, _ = await self._run_command([
                "pw-cli", "list-objects",
            ])
            if rc == 0 and "SuperCollider" in stdout:
                logger.info(
                    f"SuperCollider detected in PipeWire (attempt {i + 1})"
                )
                return True
            await asyncio.sleep(interval)

        return False

    @staticmethod
    async def _run_command(
        cmd: list[str],
    ) -> tuple[int, str, str]:
        """Run a command asynchronously.

        Returns:
            (returncode, stdout, stderr) tuple.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            return (
                proc.returncode or 0,
                stdout_bytes.decode(errors="replace"),
                stderr_bytes.decode(errors="replace"),
            )
        except FileNotFoundError:
            logger.error(f"Command not found: {cmd[0]}")
            return (1, "", f"Command not found: {cmd[0]}")
        except Exception as e:
            logger.error(f"Command failed: {cmd}: {e}")
            return (1, "", str(e))
