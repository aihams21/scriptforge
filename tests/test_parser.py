"""Parser tests - run against fixtures and the real scripts in ~/bin."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scriptforge.core.parser import Kind, analyze, detect_lang, scan_directory
from scriptforge.core.parser.bash_adapter import (
    MAX_PARSE_LINES,
    _usage_subcommands,
    is_source_text,
)

FIXTURES = Path(__file__).parent / "fixtures"


def write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


# ------------------------------------------------------------------ language


def test_detect_lang_by_shebang(tmp_path):
    assert detect_lang(write(tmp_path, "a.sh", "#!/bin/bash\necho hi\n")) == "bash"
    assert detect_lang(write(tmp_path, "b.py", "#!/usr/bin/env python3\nprint(1)\n")) == "python"


def test_detect_lang_by_extension(tmp_path):
    p = tmp_path / "no-shebang.sh"
    p.write_text("echo hi\n")
    assert detect_lang(p) == "bash"


# ------------------------------------------------------------------ interactive


def test_prompts_are_recovered(tmp_path):
    p = write(tmp_path, "ask.sh", """#!/bin/bash
echo "Interface:"
read -r ifc
echo "Mode:"
read -r mode
echo "done"
""")
    ir = analyze(p)
    assert ir.kind is Kind.INTERACTIVE
    assert {s.var for s in ir.prompt_sites} == {"ifc", "mode"}


def test_secret_prompt_is_masked(tmp_path):
    p = write(tmp_path, "pw.sh", "#!/bin/bash\nread -r -s password\n")
    ir = analyze(p)
    assert ir.prompt_sites[0].widget.value == "secret"


def test_prompt_with_inline_text(tmp_path):
    p = write(tmp_path, "inline.sh", "#!/bin/bash\nread -rp 'Enter host: ' host\n")
    ir = analyze(p)
    assert ir.prompt_sites[0].prompt == "Enter host:"  # stripped for display
    assert ir.prompt_sites[0].var == "host"


def test_herestring_read_is_not_a_prompt(tmp_path):
    """`read -r x <<< "$y"` parses data; it is not a human question."""
    p = write(tmp_path, "parse.sh", '#!/bin/bash\nread -r a b <<<"$1"\necho "$a"\n')
    ir = analyze(p)
    assert ir.prompt_sites == []


def test_piped_read_is_not_a_prompt(tmp_path):
    p = write(tmp_path, "piped.sh", "#!/bin/bash\nprintf 'a b\\n' | read -r x y\necho\n")
    ir = analyze(p)
    assert ir.prompt_sites == []


def test_choices_are_extracted_from_menu(tmp_path):
    p = write(tmp_path, "menu.sh", """#!/bin/bash
echo "Pick one:"
echo "  1) sta   2) ap   3) mon"
read -r c
""")
    ir = analyze(p)
    assert set(ir.prompt_sites[0].choices) >= {"sta", "ap"}


def test_duplicate_reads_collapse_to_one_prompt(tmp_path):
    p = write(tmp_path, "loop.sh", """#!/bin/bash
while true; do
  echo "again"
  read -r item || break
done
""")
    ir = analyze(p)
    assert len([s for s in ir.prompt_sites if s.var == "item"]) == 1


# ------------------------------------------------------------------ parametric


def test_usage_block_becomes_subcommands(tmp_path):
    p = write(tmp_path, "acct.sh", """#!/bin/bash
usage() {
  echo "Commands:"
  echo "  list          print the list"
  echo "  switch <n>    switch account"
  echo "  new <n> <name>  make one"
  echo ""
  echo "Examples:"
  echo "  acct switch 2   go"
}
""")
    ir = analyze(p)
    names = [s.name for s in ir.subcommands]
    assert "list" in names and "switch" in names and "new" in names
    assert "acct" not in names  # Examples section must not leak


def test_usage_extraction_stops_at_examples():
    lines = [
        'echo "Commands:"',
        'echo "  run   do it"',
        'echo ""',
        'echo "Examples:"',
        'echo "  tool run   stuff"',
    ]
    assert [n for n, _ in _usage_subcommands(lines)] == ["run"]


def test_getopts_becomes_flags(tmp_path):
    p = write(tmp_path, "flags.sh", '#!/bin/bash\nwhile getopts ":ab:c" opt; do\n  case $opt in\n  esac\ndone\n')
    ir = analyze(p)
    shorts = {f.short for f in ir.flags}
    assert {"-a", "-b", "-c"} <= shorts


def test_argparse_becomes_fields(tmp_path):
    p = write(tmp_path, "tool.py", '''#!/usr/bin/env python3
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("target", help="what to hit")
ap.add_argument("-v", "--verbose", help="chatty")
if __name__ == "__main__":
    ap.parse_args()
''')
    ir = analyze(p)
    assert ir.lang.value == "python"
    assert ir.kind is Kind.PARAMETRIC
    assert [a.name for a in ir.positional_args] == ["target"]
    assert any(f.long == "--verbose" for f in ir.flags)


def test_python_input_is_a_prompt(tmp_path):
    p = write(tmp_path, "ask.py", '#!/usr/bin/env python3\nname = input("Your name: ")\n')
    ir = analyze(p)
    assert ir.kind is Kind.INTERACTIVE
    assert ir.prompt_sites[0].var == "Your name: "


def test_python_getpass_is_secret(tmp_path):
    p = write(tmp_path, "pw.py", '#!/usr/bin/env python3\nimport getpass\np = getpass.getpass("pw: ")\n')
    ir = analyze(p)
    assert ir.prompt_sites[0].widget.value == "secret"


# ------------------------------------------------------------------ skeletal


def test_three_line_wrapper_is_skeletal(tmp_path):
    p = write(tmp_path, "wrap.sh", '#!/bin/bash\ncline --config /x/settings "$@"\n')
    ir = analyze(p)
    assert ir.kind is Kind.SKELETAL
    assert ir.needs_rewrite


def test_python_console_shim_is_opaque(tmp_path):
    p = write(tmp_path, "olefile", '#!/usr/bin/env python3\nimport sys\nfrom olefile import main\nsys.exit(main())\n')
    ir = analyze(p)
    assert ir.kind is Kind.OPAQUE
    assert not ir.buildable


# ------------------------------------------------------------------ robustness


def test_binary_is_rejected_not_parsed(tmp_path):
    p = tmp_path / "blob"
    p.write_bytes(b"\x7fELF\x00\x00\x00" + b"\x00" * 500)
    ir = analyze(p)
    assert ir.kind is Kind.UNKNOWN
    assert not is_source_text(p)


def test_huge_generated_script_does_not_hang(tmp_path):
    """`firebase` is 3.5M lines; bashlex would never return."""
    p = tmp_path / "firebase"
    p.write_text("#!/usr/bin/env bash\n" + ("echo line\n" * (MAX_PARSE_LINES + 100)))
    ir = analyze(p)
    assert ir.parse_mode == "scan"
    assert any("exceeds" in w for w in ir.warnings)


def test_unparseable_bash_falls_back_to_scanner(tmp_path):
    p = write(tmp_path, "weird.sh", "#!/bin/bash\necho 'unterminated\nread -r thing\n")
    ir = analyze(p)
    assert ir.parse_mode in ("ast", "scan")
    assert ir.kind is not Kind.UNKNOWN


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        analyze("/nonexistent/script.sh")


def test_empty_script_is_safe(tmp_path):
    ir = analyze(write(tmp_path, "empty.sh", ""))
    assert ir.kind is Kind.SKELETAL
    assert ir.field_count() == 0


def test_scan_directory_skips_hidden_and_dedupes(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    write(d, "a.sh", "#!/bin/bash\necho\n")
    write(d, ".hidden.sh", "#!/bin/bash\necho\n")
    (d / "link.sh").symlink_to(d / "a.sh")
    irs = scan_directory(d)
    names = [i.name for i in irs]
    assert names.count("a.sh") == 1
    assert ".hidden.sh" not in names


def test_ir_roundtrips_to_json(tmp_path):
    import json

    ir = analyze(write(tmp_path, "j.sh", "#!/bin/bash\nread -r x\n"))
    payload = json.loads(json.dumps(ir.to_dict()))
    assert payload["name"] == "j.sh"
    assert payload["kind"] == "interactive"

# ------------------------------------------------------------------ powershell


def test_powershell_detected_by_extension(tmp_path):
    assert detect_lang(write(tmp_path, "x.ps1", "Write-Host hi\n")) == "powershell"
    assert detect_lang(write(tmp_path, "x.cmd", "@echo off\n")) == "batch"


def test_powershell_param_block_becomes_args(tmp_path):
    p = write(tmp_path, "probe.ps1", """param(
  [string]$Target,
  [int]$Port = 80,
  [switch]$Verbose
)
Write-Host "$Target $Port"
""")
    ir = analyze(p)
    assert ir.lang.value == "powershell"
    assert [a.name for a in ir.positional_args] == ["Target", "Port"]
    assert [f.short for f in ir.flags] == ["-Verbose"]
    assert ir.kind is Kind.PARAMETRIC


def test_powershell_readhost_is_a_prompt(tmp_path):
    p = write(tmp_path, "ask.ps1", 'param([string]$Target)\n$port = Read-Host "port"\n')
    ir = analyze(p)
    assert ir.kind is Kind.INTERACTIVE
    assert ir.prompt_sites[0].var == "port"
    assert ir.prompt_sites[0].prompt == "port"


def test_powershell_secret_prompt(tmp_path):
    p = write(tmp_path, "pw.ps1", '$pw = Read-Host "password" -AsSecureString\n')
    ir = analyze(p)
    assert ir.prompt_sites[0].widget.value == "secret"


def test_batch_set_p_is_a_prompt(tmp_path):
    p = write(tmp_path, "b.cmd", "@echo off\nset /p TARGET=Enter host: \n")
    ir = analyze(p)
    assert ir.lang.value == "batch"
    assert ir.prompt_sites[0].var == "TARGET"


def test_batch_positional_args(tmp_path):
    p = write(tmp_path, "b.cmd", "@echo off\necho %1 %2\n")
    ir = analyze(p)
    assert [a.name for a in ir.positional_args] == ["arg1", "arg2"]


def test_powershell_comment_is_not_the_tag(tmp_path):
    p = write(tmp_path, "d.ps1", "<#\nProbe the target\n#>\nparam([string]$T)\n")
    assert analyze(p).description == "Probe the target"


# --- regression: the bashlex AST path was silently inert --------------------
#
# Every bash script reported "recovered by scan". Three separate shape
# assumptions in the AST walker meant it never contributed anything, so the
# structure it is supposed to own (case menus, select, getopts) was coming from
# the regex scanner by accident.

def _tmp(tmp_path, body, name="s.sh"):
    p = tmp_path / name
    p.write_text(body)
    p.chmod(0o755)
    return p


def test_ast_path_is_actually_used(tmp_path):
    """bashlex.parse returns a LIST for multi-statement scripts.

    The walker read `.kind` off the result directly, which raised AttributeError
    on every script longer than one command, and the blanket except turned that
    into a silent downgrade to the scanner.
    """

    ir = analyze(
        _tmp(
            tmp_path,
            "#!/bin/bash\n"
            "echo one\n"
            'read -rp "host: " host\n'
            "echo two\n",
        )
    )
    assert ir.parse_mode == "ast", ir.warnings


def test_plain_read_has_no_redirect_node(tmp_path):
    """`read -rp "q" v` is a plain command in bashlex; only the explicit
    `< /dev/tty` form becomes a redirect, so a redirect-only walker sees
    nothing."""

    ir = analyze(_tmp(tmp_path, "#!/bin/bash\nread -rp \"who: \" who\necho $who\n"))
    assert [p.var for p in ir.prompt_sites] == ["who"]
    assert ir.prompt_sites[0].prompt == "who:"


def test_read_command_name_is_not_a_variable(tmp_path):
    """`read` itself used to be consumed as the target variable, turning one
    read into four sites (`read`, `target`, `host:`, `host`)."""

    ir = analyze(_tmp(tmp_path, "#!/bin/bash\nread -rp \"target host: \" host\n"))
    assert [p.var for p in ir.prompt_sites] == ["host"]


def test_option_case_labels_are_not_subcommands(tmp_path):
    """`case $opt in v) ... p) ...` is a getopts dispatcher. Its labels must not
    be offered as modes."""

    ir = analyze(
        _tmp(
            tmp_path,
            "#!/bin/bash\n"
            "while getopts \":vp:\" opt; do\n"
            "  case \"$opt\" in\n"
            "    v) verbose=1 ;;\n"
            "    p) port=$OPTARG ;;\n"
            "  esac\n"
            "done\n",
        )
    )
    assert not [c for c in ir.subcommands if c.name in ("v", "p")]
    assert {f.short for f in ir.flags} == {"-v", "-p"}


def test_mode_variable_still_yields_subcommands(tmp_path):
    """The counterpart: a dispatcher on a variable assigned from $1 is a real
    mode menu, and rejecting it would lose start/stop/status."""

    ir = analyze(
        _tmp(
            tmp_path,
            "#!/bin/bash\n"
            'mode="${1:-status}"\n'
            'case "$mode" in\n'
            "  start) echo up ;;\n"
            "  stop)  echo down ;;\n"
            "  status) echo on ;;\n"
            "esac\n",
        )
    )
    assert {c.name for c in ir.subcommands} == {"start", "stop", "status"}


def test_value_switch_labels_are_not_subcommands(tmp_path):
    """`case "$port" in` is a value comparison, not a menu."""

    ir = analyze(
        _tmp(
            tmp_path,
            "#!/bin/bash\n"
            'case "$port" in\n'
            "  22) echo ssh ;;\n"
            "  443) echo tls ;;\n"
            "esac\n",
        )
    )
    assert not [c for c in ir.subcommands if c.name in ("22", "443")]
