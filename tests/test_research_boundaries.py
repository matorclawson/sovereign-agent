"""Real bounded receipt and shell boundaries from the existing review findings."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from sovereign_agent import research_executor as executor


@pytest.mark.parametrize("kind", ["fifo", "symlink", "directory", "oversize"])
def test_receipt_refusal_is_bounded_before_read(tmp_path, kind):
    request = executor.Request(operation="a" * 32, x=0.0, delay=0.0)
    folder = executor.directory(tmp_path, request.operation)
    folder.mkdir(parents=True)
    path = folder / "result.json"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        target = tmp_path / "fifo"
        os.mkfifo(target)
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * 8193)
    script = """
import sys
from pathlib import Path
from sovereign_agent.research_executor import collect
try: collect(Path(sys.argv[1]),sys.argv[2])
except ValueError: raise SystemExit(0)
raise SystemExit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), request.model_dump_json()],
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == 0, result.stderr
    assert path.exists()  # Rejected evidence is retained, never consumed or unlinked.


def test_regular_owned_receipt_remains_collectible(tmp_path):
    request = executor.Request(operation="b" * 32, x=0.0, delay=0.0)
    folder = executor.directory(tmp_path, request.operation)
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(request.model_dump_json())
    executor.execute(folder)
    receipt, digest = executor.collect(tmp_path, request.model_dump_json())
    assert receipt.value == 0.190625 and len(digest) == 64


@pytest.mark.parametrize("failure", ["mktemp", "empty", "child", "success"])
def test_makefile_demo_fails_closed_and_cleans_owned_root(tmp_path, failure):
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
    recipe = (
        "set -eu;"
        + makefile.split("\t@set -eu;", 1)[1].split(
            "\n\t$(UV) run --python 3.12 python scripts/verify_readme", 1
        )[0]
    )
    uv = tmp_path / "uv-fixture"
    uv.write_text(
        "#!/bin/sh\nfor argument do root=$argument; done\n"
        'printf \'%s\\n\' "$root" >> "$DEMO_LOG"\ntouch "$root/owned"\nexit "$CHILD_EXIT"\n'
    )
    uv.chmod(0o700)
    recipe = (
        recipe.replace("$(UV)", shlex.quote(str(uv)))
        .replace("$$", "$")
        .replace("\\\n", "")
        .replace("\t", "")
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if failure in {"mktemp", "empty"}:
        command = bin_dir / "mktemp"
        command.write_text("#!/bin/sh\nexit " + ("42" if failure == "mktemp" else "0") + "\n")
        command.chmod(0o700)
    log = tmp_path / "demo.log"
    env = dict(
        os.environ,
        TMPDIR=str(tmp_path),
        PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
        DEMO_LOG=str(log),
        CHILD_EXIT="7" if failure == "child" else "0",
    )
    roots = []
    for _ in range(2):
        result = subprocess.run(["/bin/sh", "-c", recipe], env=env, capture_output=True, timeout=5)
        assert result.returncode == {"mktemp": 42, "empty": 1, "child": 7, "success": 0}[failure], (
            result.stderr
        )
        if failure in {"mktemp", "empty"}:
            assert not log.exists()
        else:
            roots = log.read_text().splitlines()
            assert all(not Path(root).exists() for root in roots)
    if roots:
        assert len(set(roots)) == 2
