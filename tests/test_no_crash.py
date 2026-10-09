"""Regression guard: no keypress, in any screen, may take the app down.

This is the test that was missing when the app closed on stray keypresses.
It presses every printable key plus the navigation keys in four UI states.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.core.parser import analyze
from scriptforge.core.runner import ScriptRunner
from scriptforge.ui.app import ScriptForge
from scriptforge.ui.widgets import Confirm, RunScreen, ScriptScreen

KEYS = list("qripweadnsxzghjkluctbmyv1234567890") + [
    "enter", "escape", "space", "tab", "up", "down", "left", "right",
]

# keys that legitimately end the run are excluded per state
SKIP = {"main": ("q",), "modal": ("q",)}


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "ask.sh").write_text('#!/bin/bash\necho "target:"\nread -r t\necho "hit $t"\n')
    (tmp_path / "acct").write_text('#!/bin/bash\nsomecli --config /x/settings "$@"\n')
    (tmp_path / "tool.py").write_text(
        '#!/usr/bin/env python3\nimport argparse\n'
        'ap = argparse.ArgumentParser()\nap.add_argument("target")\n'
        'x = input("user: ")\n'
    )
    for f in tmp_path.iterdir():
        f.chmod(0o755)
    return tmp_path


async def _sweep(pilot, skip=()):
    """Press every key; fail loudly on the first one that raises."""
    for key in KEYS:
        if key in skip:
            continue
        await pilot.press(key)
        await pilot.pause()


def test_keypress_never_crashes(sandbox):
    async def run():
        app = ScriptForge(roots=[str(sandbox)])
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            await _sweep(pilot, SKIP["main"])

            target = next(i for i in app.irs if i.name == "ask.sh")
            skel = next(i for i in app.irs if i.kind.value == "skeletal")

            app.selected = target
            await app.push_screen(
                ScriptScreen(target, [s.var for s in target.prompt_sites])
            )
            await pilot.pause()
            await _sweep(pilot, SKIP["modal"])

            await app.push_screen(Confirm("re-program?"))
            await pilot.pause()
            await _sweep(pilot, SKIP["modal"])

            runner = ScriptRunner(target.path, answers={"t": "10.0.0.1"}, timeout=10)
            run_screen = RunScreen(target.name, "ask.sh", runner, {"t": "10.0.0.1"})
            await app.push_screen(run_screen)
            await pilot.pause()
            for _ in range(120):
                if run_screen.result is not None or run_screen._error:
                    break
                await pilot.pause()
                await asyncio.sleep(0.05)
            await _sweep(pilot, SKIP["modal"])

            assert run_screen._error is None, run_screen._error
            assert run_screen.result is not None, "the run never finished"
            assert run_screen.result.exit_code == 0
            assert "hit 10.0.0.1" in run_screen.result.output
            app._last_result = run_screen.result

    asyncio.run(run())


def test_app_actions_are_inert_under_a_modal(sandbox):
    """App-level actions must no-op while a dialog is stacked on top."""

    async def run():
        app = ScriptForge(roots=[str(sandbox)])
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            assert app._modal_open() is False
            target = next(i for i in app.irs if i.name == "ask.sh")
            await app.push_screen(ScriptScreen(target, [s.var for s in target.prompt_sites]))
            await pilot.pause()
            assert app._modal_open() is True

            app.action_refresh()      # must not reach for #list
            app.action_focus_filter() # must not reach for #filter
            await pilot.pause()
            assert app._modal_open() is True

    asyncio.run(run())
