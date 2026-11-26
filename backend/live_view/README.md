# Private live boards (CN-028; BIO-710)

A transport-only adapter receives the existing engine's native FlatBuffer
`EventWrapper` packets, decodes them with the pinned engine's generated schema
classes, and atomically writes a numeric board snapshot. Simulation, GameMaker,
map rules, winners and bot execution remain the existing Battlecode engine.

The pinned upstream NetServer binds an unauthenticated WebSocket listener on all
interfaces, without a bind-address setting. Its event stream includes indicator
and other free-form fields unsuitable for the requested private viewing policy.
The optional adapter shadows **only** `battlecode.server.NetServer` on the Java
classpath and opens **no socket**. Normal Gradle runs disable the upstream
WebSocket. An enabled service worker prepends the adapter classes and supplies a
private `live/{game_id}.json` path. Compilation is cached against both source
bytes and engine JAR bytes; JDK 21+ and the installed pinned JAR are required.

Snapshots include dimensions, round, numeric robots, walls, dirt, cheese and
team score counters. Spawn, death, upgrade, dirt and cheese events update the
board. The generated Java action accessor accepts a FlatBuffer Table even for
upstream-emitted action structs; a narrow cursor adapter uses the unchanged
native struct decoders. No arbitrary indicator strings, labels, package names,
profiler data, bot logs or source are serialized.

Writes are throttled to 10/second, atomically replaced with mode 0600, and use a
private data directory. Snapshot I/O/decoding failure disables the viewer and
never decides/stops the game. This remains a simplified numeric board: traps,
other overlays, action animations, seek/playback and browser replay rendering
are not claimed. Stalled updates are shown as delayed in the UI.

The Django live route validates current tournament membership/assignment on
every poll, returns private/no-store responses and strips unknown fields again.
It does not accept a client-supplied file path, raw engine URL or source ID.
Archived tournaments return 410 for all roles; maintenance removes their retained
board files. History/analytics remain available under their own scope rules.

The new `backend.services.runner worker` enables this transport for tournament
matches. Direct `launcher.run_match(..., live_path=...)` and
`orchestrator.launcher_run_fn(..., live_dir=...)` are the lower-level hooks.
Trial matches do not need live publication.

```bash
backend/.venvs/py3.15/bin/python backend/run_tests.py backend.live_view --integration
```

The real integration test observes changing boards **before game completion**,
checks no listener on port 6175, validates the numeric-only schema and private
file mode, and compares round/result reason with a baseline original-engine
run. The engine's own arbitrary coin-flip winner can vary and is not compared.
This evidence is not a new independent sandbox review or a production load test.
