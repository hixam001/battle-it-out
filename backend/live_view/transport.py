# SPDX-License-Identifier: AGPL-3.0-only
"""Compile only the optional trusted event transport, never a bot or replacement engine."""
import hashlib
import subprocess
import tempfile
from pathlib import Path
from backend.match_runner import launcher as L

SOURCE = Path(__file__).with_name('transport') / 'battlecode/server/NetServer.java'

def prepare():
    version = L.load_lock()['engine_version']
    jars = sorted((Path.home() / '.gradle/caches/modules-2/files-2.1/org.battlecode/battlecode26-java' / version).glob('*/battlecode26-java-' + version + '.jar'))
    if not jars:
        raise L.LauncherError('The pinned engine JAR is needed for live viewing; provision Gradle dependencies first')
    jar = jars[0]
    digest = hashlib.sha256(SOURCE.read_bytes() + jar.read_bytes()).hexdigest()[:24]
    root = Path(__file__).resolve().parents[1] / '.cache/live-view'
    root.mkdir(parents=True, exist_ok=True)
    target = root / digest
    if not (target / 'battlecode/server/NetServer.class').exists():
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            result = subprocess.run(['javac', '-cp', str(jar), '-d', tmp, str(SOURCE)], capture_output=True, text=True)
            if result.returncode:
                raise L.LauncherError('Live transport compilation failed: ' + result.stderr[:500])
            try:
                Path(tmp).rename(target)
            except FileExistsError:
                pass
    return target
