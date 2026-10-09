"""Browser GUI for ScriptForge - a local, stdlib-only web app.

Deliberately dependency-free: `http.server` only, so the exact same code runs
on Kali bare-metal, inside a Kali VM, and on Windows. No ports are exposed
beyond loopback, and no data leaves the machine.

Run it with `scriptforge gui` (or press the Desktop icon).
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core.parser import Kind, analyze, scan_directory
from .core.rewriter import rewrite
from .core.runner import ScriptRunner
from .core.vault import Vault
from .ui import theme

DEFAULT_ROOTS = [
    Path.home() / "bin",
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
]


class State:
    """Everything the server needs, shared across request threads."""

    def __init__(self, roots: list[Path] | None = None):
        self.roots = [Path(r) for r in (roots or DEFAULT_ROOTS) if Path(r).is_dir()]
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def list_scripts(self) -> list[dict]:
        seen: set[Path] = set()
        out: list[dict] = []
        for root in self.roots:
            if not root.is_dir():
                continue
            try:
                found = scan_directory(root)
            except Exception:  # noqa: BLE001 - one bad dir must not kill the page
                continue
            for ir in found:
                if ir.kind is Kind.UNKNOWN or ir.path in seen:
                    continue
                seen.add(ir.path)
                out.append(self._summarise(ir))
        out.sort(key=lambda r: (r["kind"], r["name"]))
        return out

    def _summarise(self, ir) -> dict:
        with self._lock:
            self._cache[str(ir.path)] = ir.to_dict()
        return {
            "path": str(ir.path),
            "name": ir.name,
            "kind": ir.kind.value,
            "lang": ir.lang.value,
            "lines": ir.line_count,
            "description": ir.description,
            "prompts": len(ir.prompt_sites),
            "args": len(ir.positional_args),
            "modes": len(ir.subcommands),
            "tools": ir.detected_tools[:6],
        }

    def detail(self, path: str) -> dict:
        try:
            return analyze(path).to_dict()
        except Exception as exc:  # noqa: BLE001
            return {"name": Path(path).name, "path": path,
                    "kind": "unknown", "error": f"{type(exc).__name__}: {exc}"}

    def history(self, limit: int = 25) -> list[dict]:
        try:
            with Vault() as vault:
                return [
                    {"id": r.id, "script": r.script_name, "exit": r.exit_code,
                     "seconds": round(r.duration_s, 2), "when": r.created_at,
                     "kind": r.kind}
                    for r in vault.recent_runs(limit)
                ]
        except Exception:  # noqa: BLE001
            return []


# --------------------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    state: State  # injected by serve()

    server_version = "ScriptForge"

    def log_message(self, *args):  # keep the console clean
        pass

    # ---------------------------------------------------------------- helpers

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:  # noqa: BLE001
            return {}

    # ---------------------------------------------------------------- routing

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        route = url.path

        if route in ("/", "/index.html"):
            return self._send_page()
        if route == "/api/scripts":
            return self._json({"roots": [str(r) for r in self.state.roots],
                               "scripts": self.state.list_scripts()})
        if route == "/api/script":
            target = (parse_qs(url.query).get("path") or [""])[0]
            if not target:
                return self._json({"error": "path is required"}, 400)
            return self._json(self.state.detail(target))
        if route == "/api/history":
            return self._json({"runs": self.state.history()})
        if route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return None
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        payload = self._read_json()

        if route == "/api/forge":
            target = payload.get("path", "")
            if not target:
                return self._json({"error": "path is required"}, 400)
            try:
                ir = analyze(target)
                result = rewrite(ir, force=True)
            except Exception as exc:  # noqa: BLE001
                return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            return self._json({
                "ok": result.ok, "message": result.message,
                "path": str(result.generated), "kind": result.kind,
            })

        if route == "/api/run":
            return self._stream_run(payload)

        self._json({"error": "not found"}, 404)

    # ---------------------------------------------------------------- run (SSE)

    def _stream_run(self, payload: dict) -> None:
        target = payload.get("path", "")
        answers = payload.get("answers") or {}
        extra = payload.get("args") or []
        timeout = int(payload.get("timeout") or 300)
        if not target:
            return self._json({"error": "path is required"}, 400)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event: str, data) -> None:
            try:
                body = json.dumps(data, ensure_ascii=False)
                self.wfile.write(f"event: {event}\ndata: {body}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            ir = analyze(target)
        except Exception as exc:  # noqa: BLE001
            emit("error", f"{type(exc).__name__}: {exc}")
            return

        runner = ScriptRunner(ir.path, answers=answers, timeout=timeout)
        emit("start", {"argv": runner.preview(), "kind": ir.kind.value})

        def emit_wrap(chunk: str) -> None:
            emit("chunk", chunk)

        try:
            if ir.needs_pty and answers:
                result = runner.run_interactive(
                    args=extra, answer_order=list(answers.keys()), on_output=emit_wrap
                )
            else:
                result = runner.run_plain(args=extra, on_output=emit_wrap)
        except Exception as exc:  # noqa: BLE001
            emit("error", f"{type(exc).__name__}: {exc}")
            return
        finally:
            pass

        try:
            with Vault() as vault:
                vault.log_run(str(ir.path), ir.kind.value, result.argv,
                              result.exit_code, result.duration_s,
                              result.output, answers)
        except Exception:  # noqa: BLE001 - logging must never break the run
            pass

        emit("done", {"exit": result.exit_code, "seconds": round(result.duration_s, 2),
                      "timed_out": result.timed_out, "output": result.output})

    def _send_page(self) -> None:
        html = (Path(__file__).parent / "ui" / "web.html").read_text(encoding="utf-8")
        body = html.replace("__VERSION__", theme.VERSION).replace("__AUTHOR__", theme.AUTHOR)
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(roots: list[Path] | None = None, port: int = 0, open_browser: bool = True) -> tuple:
    """Start the GUI. Returns (host, port, server)."""
    state = State(roots)
    handler = type("BoundHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    host, bound = server.server_address[0], server.server_address[1]
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(f"http://{host}:{bound}/")).start()
    return host, bound, server