"""SuperCollider (sclang) node for nonoha-engine."""

import asyncio
import logging
from pathlib import Path

import numpy as np

from nonoha_core.data_type import DataType, PortValueType, PropertyDataType
from nonoha_core.node import BaseNode, NodeDoc
from nonoha_core.port import PortValue, StaticTypeInputPort, StaticTypeOutputPort

from .sclang_process import SclangProcess, SclangState

logger = logging.getLogger(__name__)


class SclangNode(BaseNode):
    """Node for managing a SuperCollider (sclang) process."""

    @classmethod
    def describe(cls, properties=None):
        return NodeDoc(
            description="SuperCollider (sclang) process manager",
            category="Audio",
            inputs={
                "start": "Trigger to start sclang process",
                "stop": "Trigger to stop sclang process",
                "execute_code": "SC code to send to sclang stdin",
            },
            outputs={
                "status": "Process state (0=Stopped, 1=Starting, 2=Running, 3=Stopping)",
                "log": "Log lines from stdout/stderr",
                "error": "Error messages",
            },
        )

    PROPERTIES = {
        "startup_file": {
            "description": "Path to .scd/.sc startup file (relative to the workspace data directory)",
            "default_value": "",
            "data_type": "str",
        },
        "enable_audio_routing": {
            "description": "Enable PipeWire audio routing (Linux only)",
            "default_value": True,
            "data_type": "bool",
        },
    }

    def __init__(self, name: str):
        super().__init__(name, "Sclang")

        # Runtime state (initialized in activate)
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._process: SclangProcess | None = None
        self._audio_router = None

        # Input ports
        input_start = StaticTypeInputPort("start", [PortValueType(DataType.Any)])
        input_start.subscribe(id(self), self._on_input_start)
        self.inputs[input_start.name] = input_start

        input_stop = StaticTypeInputPort("stop", [PortValueType(DataType.Any)])
        input_stop.subscribe(id(self), self._on_input_stop)
        self.inputs[input_stop.name] = input_stop

        input_execute_code = StaticTypeInputPort(
            "execute_code", [PortValueType(DataType.String)]
        )
        input_execute_code.subscribe(id(self), self._on_input_execute_code)
        self.inputs[input_execute_code.name] = input_execute_code

        # Output ports
        self._output_status = StaticTypeOutputPort(
            "status", [PortValueType(DataType.Uint8)]
        )
        self.outputs[self._output_status.name] = self._output_status

        self._output_log = StaticTypeOutputPort("log", [PortValueType(DataType.String)])
        self.outputs[self._output_log.name] = self._output_log

        self._output_error = StaticTypeOutputPort(
            "error", [PortValueType(DataType.String)]
        )
        self.outputs[self._output_error.name] = self._output_error

    def activate(self):
        self._main_loop = asyncio.get_running_loop()
        self._process = SclangProcess(
            on_state_changed=self._on_state_changed_from_thread,
            on_log=self._on_log_from_thread,
            on_error=self._on_error_from_thread,
        )
        self._dispatch_status(SclangState.STOPPED)

    def finalize(self):
        if self._process is not None:
            self._process.shutdown()
            # Input callbacks bail out when _process is None: a start delivered
            # after finalize (e.g. a restart watchdog reacting to the teardown's
            # own status=0 dispatch) must not resurrect sclang.
            self._process = None
        if self._audio_router is not None and self._main_loop is not None:
            try:
                self._main_loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._audio_router.teardown())
                )
            except RuntimeError:
                pass

    # -- Input port callbacks (main loop thread) --

    def _on_input_start(self, values: list[PortValue]):
        if self._process is None:
            return
        startup_file, cwd = self._resolve_startup_file()
        self._process.start(startup_file=startup_file, cwd=cwd)

    def _on_input_stop(self, values: list[PortValue]):
        if self._process is None:
            return
        self._process.stop()

    def _on_input_execute_code(self, values: list[PortValue]):
        if self._process is None:
            return
        code_array = values[0]
        if len(code_array) == 0:
            return
        code = str(code_array[-1])
        self._process.execute_code(code)

    # -- Process callbacks (called from worker thread, dispatched to main loop) --

    def _on_state_changed_from_thread(self, state: SclangState):
        if self._main_loop is None:
            return
        self._main_loop.call_soon_threadsafe(self._dispatch_status, state)

        # Trigger audio routing setup after RUNNING on Linux
        if state == SclangState.RUNNING and self.properties["enable_audio_routing"]:
            from . import platform_utils

            if platform_utils.is_audio_routing_supported():
                self._main_loop.call_soon_threadsafe(self._schedule_audio_setup)

        # Trigger audio routing teardown on STOPPED
        if state == SclangState.STOPPED and self._audio_router is not None:
            self._main_loop.call_soon_threadsafe(self._schedule_audio_teardown)

    def _on_log_from_thread(self, line: str):
        if self._main_loop is None:
            return
        self._main_loop.call_soon_threadsafe(self._dispatch_log, line)

    def _on_error_from_thread(self, message: str):
        if self._main_loop is None:
            return
        self._main_loop.call_soon_threadsafe(self._dispatch_error, message)

    # -- Audio routing (main loop thread) --

    def _schedule_audio_setup(self):
        if self._audio_router is None:
            from .audio_routing import AudioRouter

            self._audio_router = AudioRouter()
        asyncio.ensure_future(self._audio_setup_task())

    async def _audio_setup_task(self):
        if self._audio_router is None:
            return
        await asyncio.sleep(2.0)
        success = await self._audio_router.setup()
        if not success:
            self._dispatch_error("Audio routing setup failed (non-fatal)")

    def _schedule_audio_teardown(self):
        if self._audio_router is not None:
            asyncio.ensure_future(self._audio_router.teardown())

    # -- Dispatch helpers (main loop thread) --

    def _dispatch_status(self, state: SclangState):
        self._output_status.dispatch([np.array([state.value], dtype=np.uint8)])
        if self.parent_graph is not None:
            self.parent_graph.flush_outputs()

    def _dispatch_log(self, line: str):
        self._output_log.dispatch(
            [np.array([line], dtype=np.dtypes.StringDType())]  # type: ignore
        )
        if self.parent_graph is not None:
            self.parent_graph.flush_outputs()

    def _dispatch_error(self, message: str):
        logger.error(f"{self.name}: {message}")
        self._output_error.dispatch(
            [np.array([message], dtype=np.dtypes.StringDType())]  # type: ignore
        )
        if self.parent_graph is not None:
            self.parent_graph.flush_outputs()

    # -- Path resolution --

    def _resolve_startup_file(self) -> tuple[str | None, Path | None]:
        """Resolve startup_file to absolute path and determine cwd."""
        startup_file = self.properties["startup_file"]
        if not startup_file:
            return None, None

        file_path = Path(startup_file)

        if not file_path.is_absolute():
            if self.parent_graph is not None and self.parent_graph.persist is not None:
                data_dir = self.parent_graph.persist.data_dir_path
                file_path = data_dir / startup_file
            else:
                logger.warning(
                    f"{self.name}: Cannot resolve relative path without parent graph"
                )
                return startup_file, None

        if not file_path.exists():
            self._dispatch_error(f"Startup file not found: {file_path}")
            return None, None

        cwd = file_path.parent
        return file_path.name, cwd

    # -- Properties --

    def set_properties(self, properties: dict[str, PropertyDataType]):
        if "startup_file" in properties:
            self.properties["startup_file"] = str(properties["startup_file"])
        if "enable_audio_routing" in properties:
            self.properties["enable_audio_routing"] = bool(
                properties["enable_audio_routing"]
            )
        if self.parent_graph is not None:
            self.parent_graph.notify_node_updated(self)
