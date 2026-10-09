"""Orchestrator: the path from "a file" to "a usable app".

Used by both the TUI and the CLI so behaviour can never drift between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core.parser import Kind, ScriptIR, analyze
from .core.rewriter import BUILT_DIR, RewriteResult, rewrite
from .core.runner import RunResult, ScriptRunner
from .core.vault import Vault


@dataclass
class ForgePlan:
    """What we would do with a script, before we do it."""

    ir: ScriptIR
    action: str  # "wrap" | "rewrite" | "launch"
    reason: str
    fields: list[str]

    @property
    def title(self) -> str:
        return f"{self.ir.name}  [{self.ir.kind.value}] → {self.action}"


def plan(script: Path | str) -> ForgePlan:
    ir = analyze(script)

    if ir.kind is Kind.SKELETAL:
        return ForgePlan(ir, "rewrite", "no interface found; generate a wrapper", [])
    if ir.kind is Kind.FULLSCREEN:
        return ForgePlan(ir, "launch", "full-screen TUI; embed the raw terminal", [])
    if ir.kind is Kind.OPAQUE:
        return ForgePlan(ir, "launch", "package shim; freeform arguments", [])
    if ir.kind is Kind.INTERACTIVE:
        names = [s.var for s in ir.prompt_sites]
        return ForgePlan(ir, "wrap", f"{len(names)} prompt(s) recovered", names)
    if ir.kind is Kind.PARAMETRIC:
        names = [a.name for a in ir.positional_args]
        return ForgePlan(ir, "wrap", f"{len(ir.subcommands)} mode(s), {len(names)} arg(s)", names)
    return ForgePlan(ir, "launch", "unrecognised interface", [])


def forge(script: Path | str, force: bool = False) -> RewriteResult:
    ir = analyze(script)
    return rewrite(ir, force=force)


def execute(
    script: Path | str,
    answers: dict[str, str] | None = None,
    args: list[str] | None = None,
    timeout: int = 600,
    log: bool = True,
) -> RunResult:
    ir = analyze(script)
    runner = ScriptRunner(ir.path, answers=answers or {}, timeout=timeout)
    payload = list(args or [])

    if ir.needs_pty and answers:
        result = runner.run_interactive(args=payload, answer_order=list(answers.keys()))
    else:
        result = runner.run_plain(args=payload)

    if log:
        with Vault() as vault:
            vault.log_run(
                str(ir.path), ir.kind.value, result.argv,
                result.exit_code, result.duration_s, result.output, answers or {},
            )
    return result


def built_dir() -> Path:
    return BUILT_DIR