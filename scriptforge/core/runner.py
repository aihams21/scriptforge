"""Drive a real script over a PTY and inject answers into its prompts.

pexpect is optional: when it is missing we fall back to subprocess pipes,
which still works for non-interactive runs and dry-run previews.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

IS_WINDOWS = os.name == "nt"

try:
    import pexpect

    HAS_PEXPECT = not IS_WINDOWS
except Exception:  # pragma: no cover
    HAS_PEXPECT = False


def _as_text(value) -> str:
    """TimeoutExpired carries bytes even when the call used text=True."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


@dataclass
class RunResult:
    argv: list[str]
    exit_code: int
    output: str
    duration_s: float
    answers: dict[str, str] = field(default_factory=dict)
    timed_out: bool = False
    mode: str = "pipes"  # "pty" | "pipes"

    @property
    def ok(self) -> int:
        return self.exit_code == 0


class ScriptRunner:
    """Runs one script, optionally answering its prompts from a dict."""

    def __init__(
        self,
        script: Path | str,
        answers: dict[str, str] | None = None,
        timeout: int = 300,
        env: dict[str, str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ):
        self.script = Path(script).expanduser().resolve()
        self.answers = dict(answers or {})
        self.timeout = timeout
        self.on_output = on_output
        self.env = {**os.environ, **(env or {})}
        self._child = None  # set while a PTY run is live, so Stop can kill it
        self._prepared = None  # (argv, child) forked by prepare()

    # --------------------------------------------------------------- building argv

    def build_argv(self, args: Iterable[str] = (), flags: Iterable[str] = ()) -> list[str]:
        argv: list[str] = list(flags)
        argv.extend(args)
        # Prefer the kernel's own shebang handling: execve() runs the file
        # directly when it is executable. Only fall back to parsing the
        # shebang when the file lost its +x bit.
        interp = self._interpreter()
        if interp in ("powershell.exe", "cmd.exe"):
            # Windows has no shebang and no +x bit; the shell needs flags too.
            lead = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"] if interp == "powershell.exe" else ["/c"]
            argv[0:0] = lead
        if os.access(self.script, os.X_OK) and not IS_WINDOWS:
            argv.insert(0, str(self.script))
        else:
            argv.insert(0, interp)
            if interp not in ("powershell.exe", "cmd.exe"):
                argv.insert(1, str(self.script))
            else:
                argv.append(str(self.script))
        return argv

    def _interpreter(self) -> str:
        """The program that can execute this file directly."""
        if self.script.suffix.lower() in (".ps1", ".psm1"):
            return "powershell.exe"
        if self.script.suffix.lower() in (".bat", ".cmd"):
            return "cmd.exe"
        first = self.script.open(errors="replace").readline().strip()
        if first.startswith("#!"):
            parts = shlex.split(first[2:].strip())
            return parts[0] if parts else str(self.script)
        return str(self.script)

    def preview(self, args: Iterable[str] = (), flags: Iterable[str] = ()) -> str:
        return " ".join(shlex.quote(a) for a in self.build_argv(args, flags))

    # --------------------------------------------------------------- execution

    def prepare(self, args: Iterable[str] = (), flags: Iterable[str] = ()):
        """Fork the child now, on the caller's (UI) thread.

        `pexpect` uses `forkpty()`. Forking from inside a worker thread of an
        already multi-threaded process can deadlock the child on an inherited
        lock, so the UI thread does the fork and the worker only does reads.
        Returns the child, or None when this platform has no pexpect.
        """
        if not HAS_PEXPECT:
            return None
        if getattr(self, "_prepared", None) is not None:
            return self._prepared[1]
        argv = self.build_argv(args, flags)
        try:
            child = pexpect.spawn(
                argv[0], argv[1:], env=self.env, encoding="utf-8",
                codec_errors="replace", timeout=0.5, echo=False,
            )
        except Exception:  # noqa: BLE001 - reported later by the run itself
            return None
        self._prepared = (argv, child)
        return child

    def run_plain(
        self,
        args: Iterable[str] = (),
        flags: Iterable[str] = (),
        timeout: int | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> RunResult:
        """Non-interactive run. Returns combined stdout/stderr."""
        argv = self.build_argv(args, flags)
        started = time.monotonic()
        emit = on_output or self._emit
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                env=self.env,
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            partial = _as_text(exc.stdout) + _as_text(exc.stderr)
            return RunResult(argv, 124, partial, time.monotonic() - started,
                              self.answers, True, "pipes")
        except FileNotFoundError as exc:
            return RunResult(argv, 127, str(exc), time.monotonic() - started, self.answers, False, "pipes")

        output = proc.stdout + proc.stderr
        emit(output)
        return RunResult(argv, proc.returncode, output, time.monotonic() - started, self.answers, False, "pipes")

    def run_interactive(
        self,
        args: Iterable[str] = (),
        flags: Iterable[str] = (),
        answer_order: list[str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> RunResult:
        """Run over a PTY, feeding `self.answers` into each prompt.

        `read -rp "q: "` prints its prompt with NO trailing newline, so we
        cannot drive this line-by-line. Instead we watch for a prompt-like
        buffer tail (`...:` / `...?` at the end of what we have read) and
        answer it. Once the queue drains we simply stream to EOF.
        """
        argv = self.build_argv(args, flags)
        started = time.monotonic()

        if not HAS_PEXPECT:
            return self.run_plain(args, flags)

        order = list(answer_order or self.answers.keys())
        queue = [self.answers[k] for k in order if self.answers.get(k) not in (None, "")]
        collected: list[str] = []
        emit = on_output or self._emit

        prepared = getattr(self, "_prepared", None)
        if prepared is not None:
            argv, child = prepared
            self._prepared = None
        else:
            try:
                child = pexpect.spawn(
                    argv[0], argv[1:], env=self.env, encoding="utf-8",
                    codec_errors="replace", timeout=0.5, echo=False,
                )
            except Exception as exc:  # noqa: BLE001
                return RunResult(argv, 127, f"spawn failed: {exc}",
                                 time.monotonic() - started, self.answers, False, "pty")

        self._child = child
        deadline = started + self.timeout
        prompt_re = re.compile(r"[^\n]*[:?]\s*\Z")
        timed_out = False
        idle_ticks = 0
        eof_sent = False

        try:
            while child.isalive():
                if time.monotonic() > deadline:
                    timed_out = True
                    child.terminate(force=True)
                    break
                try:
                    idx = child.expect([prompt_re, pexpect.EOF, pexpect.TIMEOUT], timeout=0.4)
                except (pexpect.EOF, pexpect.TIMEOUT):
                    idx = 2
                    if not child.isalive():
                        break

                # prompt_re matches to the end of the buffer, so the matched
                # text lands in `after` and `before` is empty. Capturing only
                # `before` is why the prompt never showed up in the console.
                chunk = (child.before or "") if idx != 0 else (child.before or "") + (child.after or "")
                if chunk and idx != 2:
                    # On a timeout tick `before` still holds unconsumed data,
                    # so capturing there would duplicate output.
                    collected.append(chunk)
                    emit(chunk)

                if idx == 1:  # EOF
                    break

                if idx == 0:
                    # A prompt is on screen. Answer it if we have something left,
                    # otherwise hand it EOF.
                    #
                    # EOF has to be re-sent per prompt: Ctrl-D only closes a read
                    # while the input buffer is empty, so a script with three
                    # prompts and no answers needs three of them. Sending one
                    # left the child blocked in read() until the run timeout.
                    if queue:
                        child.sendline(queue.pop(0))
                        idle_ticks = 0
                    else:
                        # Deliberately not latched by eof_sent: Ctrl-D only closes
                        # a read while the input buffer is empty, so every
                        # unanswered prompt needs its own. Latching it left the
                        # second prompt of a no-answer script blocking until the
                        # run timeout.
                        #
                        # The method is `sendeof`, not `seteof`; the wrong name
                        # raises AttributeError and a blanket except would
                        # swallow it.
                        for send_eof in (
                            lambda: child.sendeof(),
                            lambda: child.sendcontrol("d"),
                        ):
                            try:
                                send_eof()
                                break
                            except Exception:  # noqa: BLE001
                                continue
                elif not queue:
                    # Nothing left to give and no prompt in sight: close stdin
                    # once so a script blocked on an unmarked read also ends.
                    if idx == 2 and not eof_sent:
                        eof_sent = True
                        try:
                            child.sendeof()
                        except Exception:  # noqa: BLE001
                            pass
                    if idx == 2 and not child.isalive():
                        break
                    continue
                else:
                    # No marker (plain `read -r x` prints nothing). Treat two
                    # consecutive idle ticks as "the script is waiting on me".
                    idle_ticks += 1
                    if idle_ticks >= 2:
                        child.sendline(queue.pop(0))
                        idle_ticks = 0
        finally:
            # Drain whatever is still buffered. If the child died during a
            # timeout tick we broke out before consuming the last output, and
            # `child.before` would otherwise swallow it silently.
            try:
                while True:
                    more = child.read_nonblocking(4096, timeout=0.2)
                    if not more:
                        break
                    collected.append(more)
                    emit(more)
            except Exception:  # noqa: BLE001 - EOF or a dead pty; we are done
                pass
            try:
                if child.isalive():
                    child.terminate(force=True)
                child.close(force=True)
            except Exception:  # noqa: BLE001
                pass
            self._child = None

        code = child.exitstatus if child.exitstatus is not None else child.signalstatus
        code = int(code) if code is not None else 1
        return RunResult(argv, code, "".join(collected),
                         time.monotonic() - started, self.answers, timed_out, "pty")

    # --------------------------------------------------------------- helpers

    def _emit(self, chunk: str) -> None:
        if self.on_output and chunk:
            self.on_output(chunk)


def run_argv(argv: list[str], timeout: int = 120, on_output: Callable[[str], None] | None = None) -> RunResult:
    """Run a raw argv (already fully resolved). Used by the vault replay."""
    started = time.monotonic()
    env = dict(os.environ)
    env.setdefault("TERM", "xterm-256color")
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=env,
            preexec_fn=os.setsid if HAS_PEXPECT else None,
        )
    except FileNotFoundError as exc:
        return RunResult(argv, 127, str(exc), time.monotonic() - started)

    chunks: list[str] = []
    timed_out = False

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            chunks.append(line)
            if on_output:
                on_output(line)

    import threading

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if HAS_PEXPECT and not IS_WINDOWS:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except Exception:  # noqa: BLE001
            proc.terminate()
    t.join(timeout=2)
    return RunResult(
        argv, proc.returncode if proc.returncode is not None else 124, "".join(chunks),
        time.monotonic() - started, {}, timed_out, "pipes",
    )