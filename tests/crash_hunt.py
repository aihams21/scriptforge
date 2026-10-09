"""Reproduce the crash: press EVERY key in EVERY state and see what dies.

Run:  python tests/crash_hunt.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.ui.app import ScriptForge
from scriptforge.ui.widgets import Confirm, RunScreen, ScriptScreen
from scriptforge.core.parser import analyze

KEYS = list("qripweadnsxzghjkluctbmyv1234567890") + [
    "enter", "escape", "space", "tab", "up", "down", "left", "right", "f5",
]

SANDBOX = Path(tempfile.mkdtemp())
(SANDBOX / "ask.sh").write_text(
    '#!/bin/bash\necho "target:"\nread -r t\necho "hit $t"\n'
)
(SANDBOX / "acct").write_text('#!/bin/bash\nsomecli --config /x/settings "$@"\n')
(SANDBOX / "tool.py").write_text(
    '#!/usr/bin/env python3\nimport argparse\n'
    'ap = argparse.ArgumentParser()\n'
    'ap.add_argument("target")\n'
    'ap.add_argument("-v", "--verbose")\n'
    'x = input("user: ")\n'
)
for f in SANDBOX.iterdir():
    f.chmod(0o755)

results = {"crash": [], "ok": 0}


def note(state, key, exc):
    line = f"{exc.__class__.__name__}: {exc}"
    results["crash"].append((state, key, line))


async def press_all(pilot, state, skip=()):
    for key in KEYS:
        if key in skip:
            continue
        try:
            await pilot.press(key)
            await pilot.pause()
        except Exception as exc:  # noqa: BLE001
            note(state, key, exc)
            return False
        results["ok"] += 1
    return True


async def _safe_pop(app, state, pilot, note):
    """A keypress may have dismissed the dialog already - that is not a crash."""
    try:
        await app.pop_screen()
        await pilot.pause()
    except Exception as exc:  # noqa: BLE001
        if "ScreenStackError" in type(exc).__name__:
            return  # already dismissed by the key sweep
        note(state, "pop", exc)


async def main():
    app = ScriptForge(roots=[str(SANDBOX)])

    # ---------------------------------------------------- state 1: main list
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        print(f"state: main list ({len(app.irs)} scripts)")
        alive = await press_all(pilot, "main-list", skip=("q",))
        print("  survived:", alive)

        # ------------------------------------------------ state 2: modal form
        target = next(i for i in app.irs if i.name == "ask.sh")
        app.selected = target
        screen = ScriptScreen(target, [s.var for s in target.prompt_sites])
        await app.push_screen(screen)
        await pilot.pause()
        print("state: ScriptScreen open (modal)")
        alive = await press_all(pilot, "script-screen", skip=("q", "escape"))
        print("  survived:", alive)
        await _safe_pop(app, "script-screen", pilot, note)

        # ------------------------------------------------ state 3: confirm
        skel = next(i for i in app.irs if i.kind.value == "skeletal")
        app.selected = skel
        confirm = Confirm(f"re-program {skel.name}?")
        await app.push_screen(confirm)
        await pilot.pause()
        print("state: Confirm dialog open (modal)")
        alive = await press_all(pilot, "confirm", skip=("q",))
        print("  survived:", alive)
        await _safe_pop(app, "confirm", pilot, note)

        # ------------------------------------------------ state 4: run screen
        from scriptforge.core.runner import ScriptRunner

        runner = ScriptRunner(target.path, answers={"t": "10.0.0.1"}, timeout=10)
        run = RunScreen(target.name, "ask.sh", runner, {"t": "10.0.0.1"})
        await app.push_screen(run)
        await pilot.pause()
        for _ in range(80):
            if run.result is not None or run._error:
                break
            await pilot.pause()
            await asyncio.sleep(0.05)
        print("state: RunScreen open (modal, live)")
        print("  runner completed:", run.result is not None, "| exit:",
              run.result.exit_code if run.result else None, "| error:", run._error)
        if run.result is None:
            results["crash"].append(("run-screen", "completion", "run never finished"))
        alive = await press_all(pilot, "run-screen", skip=("q",))
        print("  survived:", alive)

        # ------------------------------------------------ state 5: enter -> forge
        print("state: Enter on a skeletal script (full forge path)")
        app.selected = skel
        await pilot.pause()
        try:
            app.action_forge()  # @work returns a Worker; do not await it
            for _ in range(40):
                await pilot.pause()
                await asyncio.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            note("forge-path", "enter", exc)

    print()
    print("=" * 70)
    if results["crash"]:
        print(f"CRASHES FOUND: {len(results['crash'])}")
        seen = set()
        for state, key, line in results["crash"]:
            sig = (state, line.split(":")[0])
            if sig in seen:
                continue
            seen.add(sig)
            print(f"  [{state}] key={key!r} -> {line}")
    else:
        print("no crashes in this pass")
    print(f"successful key presses: {results['ok']}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())