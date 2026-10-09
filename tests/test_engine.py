"""Rewriter + runner tests. Nothing here touches the real ~/bin or the network."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.core.parser import Kind, analyze
from scriptforge.core.rewriter import rewrite
from scriptforge.core.runner import ScriptRunner
from scriptforge.core.vault import Vault


def write(tmp_path: Path, name: str, body: str, executable: bool = True) -> Path:
    p = tmp_path / name
    p.write_text(body)
    p.chmod(0o755)
    return p


# ------------------------------------------------------------------ rewriter


def test_original_is_never_modified(tmp_path):
    original = write(tmp_path, "acct1", '#!/bin/bash\ncline --config /x "$@"\n')
    before = original.read_bytes()
    out = tmp_path / "built"

    result = rewrite(analyze(original), out_dir=out)

    assert result.ok
    assert original.read_bytes() == before, "the source script was modified!"
    assert result.generated.parent == out


def test_generated_wrapper_is_valid_bash(tmp_path):
    original = write(tmp_path, "acct1", '#!/bin/bash\ncline --config /x/settings "$@"\n')
    result = rewrite(analyze(original), out_dir=tmp_path / "built")

    proc = subprocess.run(
        ["bash", "-n", str(result.generated)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_generated_wrapper_runs(tmp_path):
    original = write(tmp_path, "acct1", '#!/bin/bash\ncline --config /x/settings "$@"\n')
    result = rewrite(analyze(original), out_dir=tmp_path / "built")

    proc = subprocess.run(
        ["bash", str(result.generated)], input="0\n", capture_output=True, text=True, timeout=20
    )
    assert proc.returncode == 0, proc.stderr
    assert "acct1" in proc.stdout


def test_generated_wrapper_has_no_unbound_variables(tmp_path):
    """Regression: `set -u` plus an unset $name crashed the first version."""
    original = write(tmp_path, "acct1", '#!/bin/bash\ncline --config /x/settings "$@"\n')
    result = rewrite(analyze(original), out_dir=tmp_path / "built")
    proc = subprocess.run(
        ["bash", str(result.generated)], input="0\n", capture_output=True, text=True, timeout=20
    )
    assert "unbound variable" not in proc.stderr


def test_python_wrapper_generated(tmp_path):
    original = write(tmp_path, "tool.py", "#!/usr/bin/env python3\nimport sys\nprint(len(sys.argv))\n")
    result = rewrite(analyze(original), out_dir=tmp_path / "built")
    assert result.ok
    assert result.generated.read_text().startswith("#!/usr/bin/env python3")
    compile(result.generated.read_text(), str(result.generated), "exec")


def test_opaque_scripts_are_not_rewritten(tmp_path):
    original = write(
        tmp_path, "olefile",
        "#!/usr/bin/env python3\nimport sys\nfrom olefile import main\nsys.exit(main())\n",
    )
    result = rewrite(analyze(original), out_dir=tmp_path / "built")
    assert not result.ok
    assert result.kind == "opaque"


def test_rewrite_is_idempotent_without_force(tmp_path):
    original = write(tmp_path, "acct1", '#!/bin/bash\ntool --flag "$@"\n')
    out = tmp_path / "built"
    first = rewrite(analyze(original), out_dir=out, force=True)
    second = rewrite(analyze(original), out_dir=out, force=False)
    assert first.ok and second.ok
    assert "already generated" in second.message


# ------------------------------------------------------------------ runner


def test_run_plain_captures_output(tmp_path):
    p = write(tmp_path, "hello.sh", "#!/bin/bash\necho hello-world\n")
    result = ScriptRunner(p, timeout=20).run_plain()
    assert result.ok
    assert "hello-world" in result.output


def test_run_uses_the_scripts_own_shebang(tmp_path):
    """Regression: we used to hand '/usr/bin/env bash' to exec and get ENOENT."""
    p = write(tmp_path, "py.py", '#!/usr/bin/env python3\nprint("from python")\n')
    result = ScriptRunner(p, timeout=20).run_plain()
    assert result.ok
    assert "from python" in result.output


def test_run_handles_non_executable_file(tmp_path):
    p = tmp_path / "noexec.sh"
    p.write_text('#!/bin/bash\necho still-ran\n')
    p.chmod(0o644)
    result = ScriptRunner(p, timeout=20).run_plain()
    assert "still-ran" in result.output


def test_run_passes_arguments(tmp_path):
    p = write(tmp_path, "args.sh", '#!/bin/bash\necho "got:$1:$2"\n')
    result = ScriptRunner(p, timeout=20).run_plain(args=["alpha", "beta"])
    assert "got:alpha:beta" in result.output


def test_exit_code_is_captured(tmp_path):
    p = write(tmp_path, "fail.sh", "#!/bin/bash\nexit 42\n")
    result = ScriptRunner(p, timeout=20).run_plain()
    assert result.exit_code == 42
    assert not result.ok


def test_preview_is_shell_quoted(tmp_path):
    p = write(tmp_path, "q.sh", "#!/bin/bash\necho\n")
    preview = ScriptRunner(p).preview(args=["a b", "c;d"])
    assert "'a b'" in preview and "'c;d'" in preview


def test_streaming_callback_receives_output(tmp_path):
    p = write(tmp_path, "s.sh", "#!/bin/bash\necho streamed\n")
    seen: list[str] = []
    ScriptRunner(p, timeout=20, on_output=seen.append).run_plain()
    assert any("streamed" in chunk for chunk in seen)


@pytest.mark.skipif(
    subprocess.run([sys.executable, "-c", "import pexpect"], capture_output=True).returncode != 0,
    reason="pexpect not installed",
)
def test_interactive_answers_are_injected(tmp_path):
    """A script whose `read` prompts print nothing must still be answerable."""
    p = write(tmp_path, "silent.sh", """#!/bin/bash
echo "iface:"
read -r ifc
echo "mode:"
read -r mode
echo "connected:$ifc/$mode"
""")
    runner = ScriptRunner(p, answers={"ifc": "wlan0", "mode": "mon"}, timeout=30)
    result = runner.run_interactive(answer_order=["ifc", "mode"])
    assert result.mode == "pty"
    assert result.ok
    assert "connected:wlan0/mon" in result.output


# ------------------------------------------------------------------ vault


def test_vault_logs_and_lists_runs(tmp_path):
    with Vault(tmp_path / "h.db") as vault:
        rid = vault.log_run("/x/s.sh", "interactive", ["/x/s.sh"], 0, 1.5, "out", {"a": "b"})
        assert rid > 0
        rows = vault.recent_runs()
        assert len(rows) == 1
        assert rows[0].script_name == "s.sh"
        assert rows[0].answers == '{"a": "b"}'
        assert vault.last_run_for("/x/s.sh").exit_code == 0


def test_vault_history_is_newest_first(tmp_path):
    with Vault(tmp_path / "h.db") as vault:
        vault.log_run("/x/a.sh", "skeletal", [], 0, 0.1)
        vault.log_run("/x/b.sh", "skeletal", [], 1, 0.2)
        assert [r.script_name for r in vault.recent_runs()] == ["b.sh", "a.sh"]


def test_vault_cache_roundtrip(tmp_path):
    with Vault(tmp_path / "h.db") as vault:
        assert vault.cache_get("/x/s.sh", 100) is None
        vault.cache_put("/x/s.sh", 100, {"kind": "interactive"})
        assert vault.cache_get("/x/s.sh", 100) == {"kind": "interactive"}
        assert vault.cache_get("/x/s.sh", 999) is None  # stale mtime misses

# ------------------------------------------------------------------ end to end


def test_file_becomes_a_working_app(tmp_path):
    """The core promise: a UI-less script -> generated interface -> runs."""
    from scriptforge.forge import plan

    source = tmp_path / "acct"
    source.write_text('#!/bin/bash\necho "tool --config /x/settings --data-dir /y \\"\\$@\\""\n')

    # 1. it is recognised as needing a re-program
    p = plan(source)
    assert p.action == "rewrite"

    # 2. a wrapper is generated next to it, not over it
    out = tmp_path / "built"
    result = rewrite(p.ir, out_dir=out, force=True)
    assert result.ok
    assert source.read_text() == source.read_text()

    # 3. the wrapper is valid and executable
    assert subprocess.run(["bash", "-n", str(result.generated)]).returncode == 0

    # 4. it runs to completion through the runner
    run = ScriptRunner(result.generated, timeout=20).run_plain(args=[])
    assert run.ok
    assert "acct" in run.output


def test_interactive_script_runs_with_answers_end_to_end(tmp_path):
    from scriptforge.forge import execute

    p = write(tmp_path, "ask.sh", """#!/bin/bash
echo "target:"
read -r t
echo "port:"
read -r p
echo "dialing $t:$p"
""")
    r = execute(p, answers={"t": "10.0.0.1", "p": "445"}, log=False)
    assert r.ok
    assert "dialing 10.0.0.1:445" in r.output


def test_run_is_recorded_in_the_vault(tmp_path, monkeypatch):
    from scriptforge import forge as forge_mod

    db = tmp_path / "v.db"
    monkeypatch.setattr(forge_mod, "Vault", lambda *a, **k: Vault(db))
    p = write(tmp_path, "x.sh", "#!/bin/bash\necho done\n")
    forge_mod.execute(p)
    with Vault(db) as v:
        rows = v.recent_runs()
        assert len(rows) == 1 and rows[0].script_name == "x.sh"
