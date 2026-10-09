"""Web GUI tests - the API surface and the SSE run stream."""

import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.web import serve


@pytest.fixture
def server(tmp_path):
    script = tmp_path / "ask.sh"
    script.write_text('#!/bin/bash\necho "target:"\nread -r t\necho "hit $t"\n')
    script.chmod(0o755)

    (tmp_path / "acct").write_text('#!/bin/bash\nsomecli --config /x/settings "$@"\n')
    (tmp_path / "acct").chmod(0o755)

    host, port, srv = serve(roots=[tmp_path], open_browser=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.2)
    yield f"http://{host}:{port}", script
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.status, r.read()


def test_index_serves_the_page(server):
    url, _ = server
    status, body = get(url + "/")
    assert status == 200
    text = body.decode()
    assert "SCRIPTFORGE" in text
    assert "__VERSION__" not in text  # placeholders were substituted


def test_scripts_endpoint(server):
    url, _ = server
    _, body = get(url + "/api/scripts")
    data = json.loads(body)
    names = {s["name"] for s in data["scripts"]}
    assert {"ask.sh", "acct"} <= names
    assert data["roots"]


def test_scripts_carry_a_kind(server):
    url, _ = server
    _, body = get(url + "/api/scripts")
    kinds = {s["name"]: s["kind"] for s in json.loads(body)["scripts"]}
    assert kinds["ask.sh"] == "interactive"
    assert kinds["acct"] == "skeletal"


def test_script_detail(server):
    url, script = server
    _, body = get(url + "/api/script?path=" + urllib.request.quote(str(script)))
    data = json.loads(body)
    assert data["name"] == "ask.sh"
    assert [p["var"] for p in data["prompt_sites"]] == ["t"]


def test_detail_without_path_is_rejected(server):
    url, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(url + "/api/script")
    assert exc.value.code == 400


def test_unknown_route_is_404(server):
    url, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(url + "/api/nope")
    assert exc.value.code == 404


def test_forge_endpoint_never_touches_the_original(server):
    url, _ = server
    _, body = get(url + "/api/scripts")
    acct = next(s for s in json.loads(body)["scripts"] if s["name"] == "acct")
    original = Path(acct["path"])
    before = original.read_bytes()

    req = urllib.request.Request(
        url + "/api/forge",
        data=json.dumps({"path": str(original)}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        assert resp.status == 200
        data = json.loads(resp.read())
    assert data["ok"] is True
    assert original.read_bytes() == before, "forging modified the source script"
    assert Path(data["path"]).exists()


def test_run_stream_answers_prompts(server):
    """SSE: start -> chunk -> done, with the answer actually delivered."""
    url, script = server
    req = urllib.request.Request(
        url + "/api/run",
        data=json.dumps({"path": str(script), "answers": {"t": "10.0.0.1"}}).encode(),
        headers={"Content-Type": "application/json"},
    )

    events = []
    with urllib.request.urlopen(req, timeout=40) as resp:
        current = None
        for raw in resp:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                current = line[7:].strip()
            elif line.startswith("data: "):
                events.append((current, line[6:]))

    kinds = [e for e, _ in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    assert "chunk" in kinds

    payload = "".join(d for e, d in events if e == "chunk")
    assert "hit 10.0.0.1" in payload

    final = json.loads(events[-1][1])
    assert final["exit"] == 0
    assert final["timed_out"] is False


def test_run_records_history(server):
    url, script = server
    req = urllib.request.Request(
        url + "/api/run",
        data=json.dumps({"path": str(script), "answers": {"t": "9.9.9.9"}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        resp.read()

    _, body = get(url + "/api/history")
    runs = json.loads(body)["runs"]
    assert any(r["script"] == "ask.sh" and r["exit"] == 0 for r in runs)


def test_history_endpoint_never_raises(server):
    url, _ = server
    status, _ = get(url + "/api/history")
    assert status == 200


def test_server_binds_loopback_only(server):
    url, _ = server
    assert url.startswith("http://127.0.0.1:")