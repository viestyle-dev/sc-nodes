# sc-nodes

A nonoha-engine plugin for SuperCollider (sclang) process management, providing real-time audio synthesis control with automatic PipeWire audio routing on Linux.

## Overview

This plugin provides a node for launching and managing the SuperCollider language interpreter (sclang) within the nonoha-engine visual programming environment. It handles the full process lifecycle including startup file execution, live code evaluation via stdin, and graceful shutdown with scsynth cleanup. On Linux, it optionally creates PipeWire virtual audio devices to route SuperCollider audio output.

## Features

### Nodes Provided

- **Sclang**: SuperCollider (sclang) process manager
  - Start/stop sclang with optional .scd/.sc startup file execution
  - Send SuperCollider code to sclang stdin for live evaluation
  - Automatic sclang binary discovery (PATH, macOS app bundle)
  - Graceful shutdown sequence matching SC IDE behavior (`0.exit` → SIGTERM → force kill)
  - Orphaned scsynth process cleanup on all platforms
  - PipeWire audio routing with virtual speaker/microphone creation (Linux only)

## Installation

### From the Repository

```sh
pip install git+https://github.com/viestyle-dev/sc-nodes.git
```

Requires Python 3.11+. `nonoha-core` is provided by the host runtime (the
nonoha engine), so it is not a runtime dependency of this package.

### As a Dependency in nonoha-engine Workspace

1. Add `sc-nodes` to your workspace's `pyproject.toml`:

```toml
[project]
dependencies = [
    "sc-nodes",
    # other dependencies...
]

[tool.uv.sources]
sc-nodes = { path = "./plugins/sc-nodes", editable = false }
```

2. Install dependencies using uv:

```bash
uv sync
```

### As a Built-in Plugin

To include sc-nodes as a built-in plugin in your nonoha-engine instance:

1. Import the plugin in your `src/main.py`:

```python
import sc_nodes
```

2. Add to RuntimeConfig:

```python
from nonoha_engine.runtime_config import RuntimeConfig

config = RuntimeConfig(
    builtin_plugins=[
        sc_nodes,
        # other built-in plugins...
    ]
)
```

## Usage

Once installed, the Sclang node will appear in the nonoha-engine node palette. You can:

1. Drag and drop the Sclang node into your visual programming workspace
2. Configure properties (startup file path, audio routing toggle)
3. Connect a trigger to the `start` input to launch sclang
4. Send SuperCollider code via the `execute_code` input for live evaluation
5. Monitor process status, logs, and errors via the output ports

## Requirements

- Python >= 3.11
- nonoha-core (nonoha-engine core library)
- numpy (array processing)
- SuperCollider installed and accessible via PATH

### Linux Audio Routing (Optional)

- PipeWire with PulseAudio compatibility (`pactl`)
- `pw-jack` (for JACK audio routing)
- `pw-link`, `pw-cli` (for PipeWire device connection)

## Development

To contribute or modify the plugin:

```bash
uv sync        # also installs the dev dependency group (pytest, nonoha-core)
uv run pytest
```

## SuperCollider

<https://supercollider.github.io/>

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Pull requests require signing the [nonoha CLA](CLA.md) (a one-time
comment on your first PR, shared across the nonoha repositories).

## Security

The `Sclang` node executes SuperCollider code supplied by the graph; treat
graph files like scripts (details in [SECURITY.md](SECURITY.md)).

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
