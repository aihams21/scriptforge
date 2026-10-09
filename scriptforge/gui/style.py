"""QSS sheet.

Built from the palette constants rather than written as a static blob so the
launcher, the badge renderer and the window cannot drift apart.
"""

from __future__ import annotations

from . import strings as S


def stylesheet() -> str:
    return f"""
    QWidget {{
        background: {S.BG};
        color: {S.FG};
        font-family: "DejaVu Sans", "Segoe UI", "Noto Naskh Arabic", sans-serif;
        font-size: 13px;
    }}
    QToolBar {{
        background: {S.BG_PANEL};
        border-bottom: 1px solid {S.BORDER};
        padding: 6px 8px;
        spacing: 6px;
    }}
    QToolBar QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 6px 12px;
        color: {S.FG};
    }}
    QToolBar QToolButton:hover  {{ background: {S.BG_RAISED}; border-color: {S.BORDER}; }}
    QToolBar QToolButton:pressed{{ background: {S.BG}; }}
    QToolBar QToolButton#primary {{
        background: {S.ACCENT};
        color: #14161c;
        font-weight: 600;
        border-color: {S.ACCENT_DEEP};
    }}
    QToolBar QToolButton#primary:hover {{ background: #ffb64d; }}
    QToolBar QToolButton#danger {{
        background: {S.BG_RAISED};
        border: 1px solid {S.ERR};
        color: {S.ERR};
    }}
    QToolBar QToolButton#lang {{ color: {S.ACCENT}; font-weight: 600; }}

    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
        background: {S.BG_PANEL};
        border: 1px solid {S.BORDER};
        border-radius: 6px;
        padding: 6px 8px;
        selection-background-color: {S.ACCENT_DEEP};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border-color: {S.ACCENT};
    }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {S.BG_RAISED};
        border: 1px solid {S.BORDER};
        selection-background-color: {S.ACCENT_DEEP};
    }}

    QListWidget {{
        background: {S.BG_PANEL};
        border: 1px solid {S.BORDER};
        border-radius: 8px;
        outline: none;
        padding: 4px;
    }}
    QListWidget::item {{ padding: 0px; border-radius: 6px; margin: 1px 2px; }}
    QListWidget::item:hover    {{ background: {S.BG_RAISED}; }}
    QListWidget::item:selected {{ background: {S.ACCENT_DEEP}; }}

    QTabWidget::pane {{
        border: 1px solid {S.BORDER};
        border-radius: 8px;
        background: {S.BG_PANEL};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {S.FG_DIM};
        padding: 7px 14px;
        margin-right: 2px;
        border: 1px solid transparent;
        border-top-left-radius: 7px;
        border-top-right-radius: 7px;
    }}
    QTabBar::tab:selected {{
        background: {S.BG_PANEL};
        color: {S.FG};
        border-color: {S.BORDER};
        border-bottom-color: {S.BG_PANEL};
    }}
    QTabBar::tab:hover:!selected {{ color: {S.FG}; }}

    QHeaderView {{ background: {S.BG_RAISED}; }}
    QHeaderView::section {{
        background: {S.BG_RAISED};
        color: {S.FG_DIM};
        border: none;
        border-bottom: 1px solid {S.BORDER};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QHeaderView::section:first {{ border-top-left-radius: 7px; }}
    QHeaderView::section:last  {{ border-top-right-radius: 7px; }}
    QTableWidget {{
        background: {S.BG_PANEL};
        border: 1px solid {S.BORDER};
        border-radius: 8px;
        gridline-color: {S.BORDER};
    }}
    QTableWidget::item {{ padding: 4px 6px; }}

    QStatusBar {{
        background: {S.BG_PANEL};
        border-top: 1px solid {S.BORDER};
        color: {S.FG_DIM};
    }}
    QStatusBar::item {{ border: none; }}

    QSplitter::handle {{ background: {S.BORDER}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}

    QScrollBar:vertical   {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {S.BORDER}; border-radius: 5px; min-height: 24px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {S.BORDER}; border-radius: 5px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QCheckBox {{ spacing: 7px; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {S.BORDER};
        border-radius: 4px;
        background: {S.BG_PANEL};
    }}
    QCheckBox::indicator:checked {{ background: {S.ACCENT}; border-color: {S.ACCENT}; }}

    QLabel#h1     {{ font-size: 17px; font-weight: 700; color: {S.FG}; }}
    QLabel#h2     {{ font-size: 11px; font-weight: 700; color: {S.FG_DIM};
                     letter-spacing: 1px; padding-top: 4px; }}
    QLabel#dim    {{ color: {S.FG_DIM}; }}
    QLabel#faint  {{ color: {S.FG_FAINT}; font-size: 12px; }}
    QLabel#key    {{ color: {S.FG_DIM}; font-size: 12px; }}
    QLabel#val    {{ color: {S.FG}; font-family: "DejaVu Sans Mono", "Cascadia Mono", monospace; }}
    QLabel#ok     {{ color: {S.OK}; font-weight: 600; }}
    QLabel#err    {{ color: {S.ERR}; font-weight: 600; }}
    QLabel#warn   {{ color: {S.WARN}; font-weight: 600; }}

    QPushButton#link {{
        background: transparent;
        border: none;
        color: {S.ACCENT};
        padding: 4px 2px;
        text-align: left;
        font-size: 12px;
    }}
    QPushButton#link:hover {{ color: #ffc06a; text-decoration: underline; }}

    QProgressBar {{
        border: 1px solid {S.BORDER};
        border-radius: 5px;
        background: {S.BG_PANEL};
        text-align: center;
        height: 6px;
    }}
    QProgressBar::chunk {{ background: {S.ACCENT}; border-radius: 4px; }}
    """


def console_stylesheet() -> str:
    """Monospace surface for run output.

    Kept separate from the global sheet: run output is fixed-pitch by contract
    (column alignment carries meaning in most CLI tools) while the rest of the
    chrome is proportional.
    """

    return f"""
    QPlainTextEdit {{
        background: #0c0e13;
        border: 1px solid {S.BORDER};
        border-radius: 8px;
        padding: 8px;
        font-family: "DejaVu Sans Mono", "Cascadia Mono", "Consolas", monospace;
        font-size: 12.5px;
        color: #d8dde6;
        selection-background-color: {S.ACCENT_DEEP};
    }}
    """