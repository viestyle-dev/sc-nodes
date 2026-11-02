# Security Policy

## Reporting a Vulnerability

Please use GitHub's **Private Vulnerability Reporting**
(Security tab → "Report a vulnerability") on this repository.
Do not open public issues for security reports.

## Scope

**Graph definitions can execute code.** `Sclang` starts the SuperCollider
interpreter (`sclang`), writes whatever arrives on the `execute_code`
input to its stdin, and passes the `startup_file` property (a relative or
absolute path) on the command line. Loading a graph that uses this node is
equivalent to running arbitrary SuperCollider code with the engine's
privileges (SuperCollider can run shell commands). Only load graphs from
sources you trust; if you must run untrusted graphs, isolate the engine
process at the OS level.

Stopping the node terminates every `scsynth` process on the host (and every
`sclang` process on Linux), not only the ones it started. With
`enable_audio_routing` enabled (the default) the node also changes the
PipeWire session on Linux (`pactl load-module`, `pw-link`).

## Supported versions

Security fixes target the latest minor release.
