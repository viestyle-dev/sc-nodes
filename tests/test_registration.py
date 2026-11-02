"""Registration and configuration tests that never start SuperCollider.

Process start/stop is deliberately not exercised here: the shutdown path
kills every scsynth/sclang on the host, which would terminate a
developer's live SuperCollider session.
"""

import shutil
import sys

import pytest
from nonoha_core.node_registry import NodeRegistry

import sc_nodes
from sc_nodes import platform_utils
from sc_nodes.sclang_node import SclangNode


def test_register_nodes_registers_sclang():
    registry = NodeRegistry()
    sc_nodes.register_nodes(registry)

    node = registry.create_node("Sclang", "sc")
    assert isinstance(node, SclangNode)
    assert node.type == "Sclang"


def test_sclang_node_ports_and_defaults():
    node = SclangNode("sc")

    # BaseNode adds one "@<property>" input port per property; compare the
    # data ports only.
    data_inputs = {name for name in node.inputs if not name.startswith("@")}
    assert data_inputs == {"start", "stop", "execute_code"}
    assert set(node.outputs) == {"status", "log", "error"}
    assert node.properties["startup_file"] == ""
    assert node.properties["enable_audio_routing"] is True

    doc = SclangNode.describe()
    assert set(doc.inputs) == data_inputs
    assert set(doc.outputs) == set(node.outputs)


def test_build_sclang_command_uses_path_lookup(monkeypatch, tmp_path):
    fake = tmp_path / "sclang"
    fake.write_text("")
    monkeypatch.setattr(
        shutil, "which", lambda name: str(fake) if name == "sclang" else None
    )

    cmd = platform_utils.build_sclang_command("startup.scd")
    if sys.platform == "linux":
        assert cmd == ["pw-jack", str(fake), "startup.scd"]
    else:
        assert cmd == [str(fake), "startup.scd"]
    assert platform_utils.build_sclang_command() == cmd[:-1]


def test_find_sclang_raises_with_guidance(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(platform_utils.os.path, "isfile", lambda path: False)

    with pytest.raises(FileNotFoundError, match="sclang not found"):
        platform_utils.find_sclang()
