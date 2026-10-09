"""Panel widgets.

Each panel owns its layout and exposes a narrow API (set_script / set_rows /
append) so MainWindow never has to know how a panel draws itself. Panels are
rebuilt wholesale on a language switch rather than retranslated in place:
Arabic flips layout direction and column order, which is not expressible as a
label swap.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.parser import ir as ir_mod
from . import strings as S
from .style import console_stylesheet

# Roles the delegate reads. Kept adjacent to the delegate that consumes them so
# a rename cannot leave one side reading the wrong integer.
ROLE_PATH = QtCore.Qt.UserRole
ROLE_KIND = QtCore.Qt.UserRole + 1
ROLE_NAME = QtCore.Qt.UserRole + 2
ROLE_DIR = QtCore.Qt.UserRole + 3
ROLE_INDEX = QtCore.Qt.UserRole + 4


def fmt_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


def _label(text: str, obj: str = "", wrap: bool = False) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text)
    lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    return lab


def _section(text: str) -> QtWidgets.QLabel:
    return _label(text.upper(), "h2")


def _table(headers: list[str], rows: list[list[str]], stretch_last: bool = True):
    table = QtWidgets.QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            item = QtWidgets.QTableWidgetItem(cell)
            item.setToolTip(cell)
            table.setItem(r, c, item)
    head = table.horizontalHeader()
    head.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
    if stretch_last and len(headers) > 1:
        head.setSectionResizeMode(len(headers) - 1, QtWidgets.QHeaderView.Stretch)
    rows_h = 30 + 28 * max(len(rows), 1)
    table.setFixedHeight(min(rows_h, 320))
    table.verticalHeader().setDefaultSectionSize(28)
    return table


def _empty(title: str, hint: str) -> QtWidgets.QWidget:
    holder = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    head = _label(title, "h1")
    head.setAlignment(QtCore.Qt.AlignCenter)
    lay.addWidget(head)
    sub = _label(hint, "faint", wrap=True)
    sub.setAlignment(QtCore.Qt.AlignCenter)
    lay.addWidget(sub)
    return holder


class ScriptRowDelegate(QtWidgets.QStyledItemDelegate):
    """Row = name on top, directory underneath, kind chip on the right.

    Painted by hand because QListWidget's native item painting offers no hook
    for a coloured chip inside a row; a per-row stylesheet would allocate a
    style rule per entry and defeat view recycling.
    """

    def sizeHint(self, option, index) -> QtCore.QSize:
        return QtCore.QSize(240, 46)

    def paint(self, painter: QtGui.QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if option.state & QtWidgets.QStyle.State_Selected:
            painter.fillRect(option.rect, QtGui.QColor(S.ACCENT_DEEP))

        name = index.data(ROLE_NAME) or "?"
        kind = index.data(ROLE_KIND) or "interactive"
        directory = index.data(ROLE_DIR) or ""

        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        rect = option.rect.adjusted(10, 5, -10, -5)
        chip_w = 66
        text_w = max(rect.width() - chip_w - 10, 30)

        font = painter.font()
        font.setPointSizeF(10.5)
        font.setBold(True)
        painter.setFont(font)
        # On the accent fill the dim greys fall below a readable contrast ratio,
        # so both rows go white while selected.
        painter.setPen(QtGui.QColor("#ffffff" if selected else S.FG))
        painter.drawText(
            QtCore.QRect(rect.left(), rect.top(), text_w, 19),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            name,
        )

        font.setBold(False)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        painter.setPen(QtGui.QColor("#ffe9c9" if selected else S.FG_FAINT))
        fm = painter.fontMetrics()
        painter.drawText(
            QtCore.QRect(rect.left(), rect.top() + 19, text_w, 16),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            fm.elidedText(directory, QtCore.Qt.ElideMiddle, text_w),
        )

        chip = QtCore.QRect(rect.right() - chip_w, rect.top() + 6, chip_w, 18)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(S.KIND_COLOURS.get(kind, S.FG_FAINT)))
        painter.drawRoundedRect(chip, 5, 5)
        painter.setPen(QtGui.QColor("#0f1117"))
        font.setBold(True)
        font.setPointSizeF(8.0)
        painter.setFont(font)
        painter.drawText(chip, QtCore.Qt.AlignCenter, kind[:10])

        painter.restore()


class ScriptList(QtWidgets.QWidget):
    """Filterable script picker."""

    activate = QtCore.Signal()
    selected = QtCore.Signal(object)  # ScriptIR | None

    def __init__(self, s: S.Strings):
        super().__init__()
        self.s = s
        self.irs: list = []

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(s.search_hint)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)

        self.list = QtWidgets.QListWidget()
        self.list.setItemDelegate(ScriptRowDelegate())
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.activate.emit())

        self.count = _label("", "faint")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.count)

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        self.list.clear()
        shown = 0
        for index, script in enumerate(self.irs):
            haystack = f"{script.path.name} {script.path}".lower()
            if needle and needle not in haystack:
                continue
            entry = QtWidgets.QListWidgetItem()
            entry.setData(ROLE_INDEX, index)
            entry.setData(ROLE_PATH, str(script.path))
            entry.setData(ROLE_KIND, script.kind.value)
            entry.setData(ROLE_NAME, script.path.name)
            entry.setData(ROLE_DIR, str(script.path.parent))
            entry.setToolTip(str(script.path))
            self.list.addItem(entry)
            shown += 1
        self.count.setText(f"{shown} {self.s.scripts_found}")
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.selected.emit(None)

    def _row_changed(self, row: int) -> None:
        item = self.list.item(row)
        if item is None:
            self.selected.emit(None)
            return
        self.selected.emit(self.irs[item.data(ROLE_INDEX)])

    def set_scripts(self, irs) -> None:
        self.irs = list(irs)
        self._filter(self.search.text())

    def set_strings(self, s: S.Strings) -> None:
        self.s = s
        self.search.setPlaceholderText(s.search_hint)
        self.count.setText(f"{self.list.count()} {s.scripts_found}")
        self.list.viewport().update()


class OverviewPanel(QtWidgets.QWidget):
    """Static facts plus everything the parser recovered."""

    def __init__(self, s: S.Strings):
        super().__init__()
        self.s = s
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        holder = QtWidgets.QWidget()
        holder.setLayout(self.body)
        self.scroll.setWidget(holder)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        self._render(None)

    def _reset(self) -> None:
        # setParent(None) rather than deleteLater: teardown has to be immediate,
        # because deleteLater waits on an event loop that a headless render (and
        # a language switch mid-repaint) may never run. Until then the old rows
        # stay parented and keep painting at their stale geometry.
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
            elif item.layout():
                self._drain(item.layout())

    def _drain(self, lay) -> None:
        while lay.count():
            inner = lay.takeAt(0)
            if inner.widget():
                inner.widget().setParent(None)
            elif inner.layout():
                self._drain(inner.layout())

    def set_strings(self, s: S.Strings) -> None:
        self.s = s
        self._render(self._current)

    def _render(self, script) -> None:
        s = self.s
        self._reset()
        if script is None:
            self.body.addStretch(1)
            self.body.addWidget(_empty(s.no_selection, s.no_selection_hint))
            self.body.addStretch(1)
            return

        self.body.addWidget(_label(script.path.name, "h1"))

        chip = _label(f"  {script.kind.value}  ", "val")
        colour = S.KIND_COLOURS.get(script.kind.value, S.FG_FAINT)
        chip.setStyleSheet(f"color:{colour}; font-weight:700;")
        self.body.addWidget(chip)

        try:
            stat = script.path.stat()
            size = fmt_size(stat.st_size)
            modified = dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size, modified = "?", "?"

        facts = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(facts)
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for row, (key, value) in enumerate(
            [
                (s.field_path, str(script.path)),
                (s.field_lang, script.lang.value),
                (s.field_size, size),
                (s.field_modified, modified),
            ]
        ):
            grid.addWidget(_label(key, "key"), row, 0)
            val = _label(value, "val")
            val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            grid.addWidget(val, row, 1)
        grid.setColumnStretch(1, 1)
        self.body.addWidget(facts)

        if script.description:
            self.body.addWidget(_label(script.description, "dim", wrap=True))

        def section(title: str, headers: list[str], rows: list[list[str]]) -> None:
            if rows:
                self.body.addWidget(_section(title))
                self.body.addWidget(_table(headers, rows))

        if script.usage_text:
            self.body.addWidget(_section("usage"))
            usage = _label(script.usage_text, "val", wrap=True)
            usage.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.body.addWidget(usage)

        if script.parse_mode == "scan":
            self.body.addWidget(
                _label(f"AST unavailable · recovered by scan · {len(script.warnings)} notes", "faint")
            )

        section(
            s.section_questions,
            ["var", "line", "widget", "choices"],
            [
                [p.var, str(p.line), p.widget.value, ", ".join(p.choices)]
                for p in script.prompt_sites
            ],
        )
        section(
            s.section_args,
            ["name", "index", "help"],
            [[a.name, str(a.index), a.help] for a in script.positional_args],
        )
        section(
            s.section_flags,
            ["short", "long", "value", "help"],
            [[f.short, f.long, "yes" if f.takes_value else "", f.help] for f in script.flags],
        )
        section(
            s.section_commands,
            ["name", "args", "help"],
            [[c.name, ", ".join(a.name for a in c.args), c.help] for c in script.subcommands],
        )
        self.body.addStretch(1)

    def set_script(self, script) -> None:
        self._current = script
        self._render(script)

    _current = None


class InterfacePanel(QtWidgets.QWidget):
    """Generated input form.

    Widget choice follows the IR hint rather than the prompt wording: known
    choices become a combo, a boolean becomes a checkbox, anything else a line
    edit. Guessing from text would mislabel prompts that merely contain the
    letter y.
    """

    def __init__(self, s: S.Strings):
        super().__init__()
        self.s = s
        self.inputs: dict[str, QtWidgets.QWidget] = {}
        self.script = None
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder = QtWidgets.QWidget()
        holder.setLayout(self.body)
        self.scroll.setWidget(holder)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        self._render()

    def _reset(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self.inputs.clear()

    def _render(self) -> None:
        s = self.s
        self._reset()

        if self.script is None:
            self.body.addStretch(1)
            self.body.addWidget(_empty(s.no_selection, s.search_hint))
            self.body.addStretch(1)
            return

        sites = self.script.prompt_sites
        if not sites:
            self.body.addStretch(1)
            self.body.addWidget(_empty(s.no_fields, s.no_fields_hint))
            self.body.addStretch(1)
            return

        self.body.addWidget(_label(f"{len(sites)} {s.section_questions.lower()}", "h1"))
        for site in sites:
            self.body.addWidget(self._row(site))
        self.body.addStretch(1)

    def _row(self, site: ir_mod.PromptSite) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(row)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setHorizontalSpacing(14)

        lab = _label(site.prompt or site.var, "key")
        if site.widget is ir_mod.Widget.CONFIRM:
            widget = QtWidgets.QCheckBox(self.s.field_checkbox)
        elif site.choices:
            widget = QtWidgets.QComboBox()
            for choice in site.choices:
                widget.addItem(choice)
            if site.default and site.default not in site.choices:
                widget.insertItem(0, site.default)
        else:
            widget = QtWidgets.QLineEdit(site.default)
            widget.setPlaceholderText(site.default or site.var)
        widget.setToolTip(f"{site.var}  ·  line {site.line}")
        self.inputs[site.var] = widget

        grid.addWidget(lab, 0, 0)
        grid.addWidget(widget, 0, 1)
        grid.setColumnStretch(1, 1)
        return row

    def set_script(self, script) -> None:
        self.script = script
        self._render()

    def set_strings(self, s: S.Strings) -> None:
        self.s = s
        self._render()

    def answers(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QtWidgets.QComboBox):
                out[key] = widget.currentText().strip()
            elif isinstance(widget, QtWidgets.QCheckBox):
                # y/N is the convention in shell prompts, and an empty answer
                # here would leave the child waiting on read() forever.
                out[key] = "y" if widget.isChecked() else "n"
                continue
            else:
                out[key] = widget.text()
        return {k: v for k, v in out.items() if v}


class RunPanel(QtWidgets.QWidget):
    """Answers plus an append-only console.

    Append-only is deliberate: a live run must not rewrite text the operator is
    reading, which rules out setPlainText on every chunk.
    """

    finished = QtCore.Signal(object)  # RunResult

    def __init__(self, s: S.Strings):
        super().__init__()
        self.s = s

        self.answers_edit = QtWidgets.QTextEdit()
        self.answers_edit.setPlaceholderText("var: value   (one per line)")
        self.answers_edit.setMaximumHeight(90)
        self.answers_edit.setAcceptRichText(False)

        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet(console_stylesheet())
        self.console.setPlaceholderText(s.console_empty)

        self.status = _label(s.console_empty, "dim")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        lay.addWidget(_section(s.answers_label))
        lay.addWidget(self.answers_edit)
        lay.addWidget(_section("output"))
        lay.addWidget(self.console, 1)
        lay.addWidget(self.status)

    def set_strings(self, s: S.Strings) -> None:
        self.s = s
        self.console.setPlaceholderText(s.console_empty)

    def clear(self) -> None:
        self.console.clear()
        self._status(self.s.console_empty, "dim")

    def append(self, text: str) -> None:
        cursor = self.console.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.console.setTextCursor(cursor)
        self.console.insertPlainText(text)
        self.console.moveCursor(QtGui.QTextCursor.End)

    def _status(self, text: str, role: str) -> None:
        self.status.setText(text)
        self.status.setObjectName(role)
        # Re-polish is required for objectName-driven colour to take effect.
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def set_busy(self, busy: bool) -> None:
        self._status(self.s.running if busy else self.s.console_empty, "warn" if busy else "dim")

    def set_result(self, result) -> None:
        if result.timed_out:
            self._status(f"{self.s.timed_out} · {self.s.exit_code} {result.exit_code}", "err")
        elif result.ok:
            self._status(f"{self.s.finished} · 0 · {result.duration_s:.1f}s", "ok")
        else:
            self._status(f"{self.s.exit_code} {result.exit_code} · {result.duration_s:.1f}s", "err")
        self.finished.emit(result)


class HistoryPanel(QtWidgets.QWidget):
    """Run log, read from the same SQLite vault the TUI writes so the two front
    ends stay interchangeable on one machine."""

    def __init__(self, s: S.Strings):
        super().__init__()
        self.s = s
        self.vault_path: Path | None = None
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        head.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

        self.hint = _label(s.history_empty, "faint")
        self.hint.setAlignment(QtCore.Qt.AlignCenter)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.hint)

    def set_strings(self, s: S.Strings) -> None:
        self.s = s
        self.hint.setText(s.history_empty)
        self.reload()

    def set_vault(self, path: Path | None) -> None:
        self.vault_path = Path(path) if path else None

    def reload(self) -> None:
        from ..core.vault import Vault

        try:
            with Vault(self.vault_path) as vault:
                records = vault.recent_runs(limit=200)
        except Exception:
            # A locked or absent vault must not take the window down.
            records = []

        self.table.setRowCount(len(records))
        self.table.setHorizontalHeaderLabels(
            [self.s.col_script, self.s.col_exit, self.s.col_when, self.s.col_seconds]
        )
        for row, rec in enumerate(records):
            when = ""
            if rec.created_at:
                try:
                    when = dt.datetime.fromtimestamp(rec.created_at).strftime("%m-%d %H:%M")
                except (TypeError, ValueError, OSError):
                    when = str(rec.created_at)
            cells = [
                rec.script_name or Path(rec.script or "?").name,
                str(rec.exit_code),
                when,
                f"{rec.duration_s:.1f}s" if rec.duration_s else "",
            ]
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if col == 1:
                    item.setForeground(QtGui.QColor(S.OK if rec.exit_code == 0 else S.ERR))
                self.table.setItem(row, col, item)

        self.table.setVisible(bool(records))
        self.hint.setVisible(not records)