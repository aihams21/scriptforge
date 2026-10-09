"""Headless TUI smoke test - boots the app, walks the UI, opens the dialogs."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.ui.app import ScriptForge
from scriptforge.ui.widgets import Confirm, ScriptScreen

ROOT = "/home/aiham/bin"


async def main() -> None:
    app = ScriptForge(roots=[ROOT])
    async with app.run_test() as pilot:
        await pilot.pause()
        count = len(app.irs)
        opts = app.query_one("#list").option_count
        print(f"mounted OK  scripts={count}  options={opts}")
        assert count > 0 and opts == count

        for _ in range(3):
            await pilot.press("down")
            await pilot.pause()
            print(f"  selected -> {app.selected.name} / {app.selected.kind.value}")

        interactive = [i for i in app.irs if i.kind.value == "interactive"]
        if interactive:
            t = interactive[0]
            app.selected = t
            sc = ScriptScreen(t, [s.var for s in t.prompt_sites])
            await app.push_screen(sc)
            await pilot.pause()
            print(f"ScriptScreen {t.name}  widgets={len(sc.query('*'))}")
            await pilot.press("escape")
            await pilot.pause()
            print("escape from form OK")

        skeletal = [i for i in app.irs if i.kind.value == "skeletal"]
        if skeletal:
            c = Confirm(f"re-program {skeletal[0].name}?")
            await app.push_screen(c)
            await pilot.pause()
            print(f"Confirm dialog widgets={len(c.query('*'))}")
            await pilot.press("escape")
            await pilot.pause()
            print("confirm dismissed OK")

        app.query_one("#root_0").press()
        await pilot.pause()
        print(f"rescan OK  scripts={len(app.irs)}")

        app.query_one("#filter").value = "wifi"
        await pilot.pause()
        print(f"filter 'wifi' -> options={app.query_one('#list').option_count}")
        app.query_one("#filter").value = ""
        await pilot.pause()
        print(f"filter cleared -> options={app.query_one('#list').option_count}")

    print("ALL TUI CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())