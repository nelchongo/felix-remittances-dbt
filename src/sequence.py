"""Run a list of steps one after another and show where the sequence is.

In a terminal the screen is split in two: on the left the steps are connected dots that update in place
(● done, ◉ running, ○ waiting, ✗ failed) with a spinner and a timer, and a step whose models dbt builds in
parallel fans out into one branch per group; on the right the tools' output scrolls live (it is also kept in a
log file). Without a terminal (CI, pipes) every step prints a header and the output streams as usual, so CI
logs keep every line.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
DBT_DONE = re.compile(r"Done\. PASS=(\d+) WARN=(\d+) ERROR=(\d+) SKIP=(\d+)")
DBT_MODEL = re.compile(r"(START|OK created|ERROR creating) sql \w+ model (\w+)\.(\w+)")
GREEN, CYAN, RED, DIM, BOLD = "32", "36", "31", "2", "1"
LABEL_WIDTH, DETAIL_WIDTH, STATUS_WIDTH = 18, 19, 9
LEFT_WIDTH = 2 + 2 + LABEL_WIDTH + 1 + DETAIL_WIDTH + 1 + STATUS_WIDTH + 36  # rail column in split view
SPLIT_MIN_COLUMNS = LEFT_WIDTH + 40


@dataclass
class Step:
    label: str
    detail: str  # what runs, e.g. "tag:staging"
    action: Callable[[Sequence], str | None]  # returns a short result; dbt steps fall back to dbt's summary
    branches: dict[str, set[str]] = field(default_factory=dict)  # group → models dbt builds in parallel
    status: str = "pending"  # pending | running | done | failed | skipped
    result: str = ""
    began: float = 0.0
    seconds: float = 0.0
    offset: int = 0  # where this step's output starts in the log


def hyperlink(url: str, text: str | None = None, enabled: bool = True) -> str:
    """A clickable link in terminals that support OSC 8 (iTerm2, VS Code, Windows Terminal, GNOME…);
    elsewhere it is plain text."""
    text = text or url
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\" if enabled else text


class Sequence:
    def __init__(self, title: str, steps: list[Step], log_path: Path):
        self.title, self.steps, self.log_path = title, steps, log_path
        self.live = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
        self.color = self.live and "NO_COLOR" not in os.environ
        self.note = ""  # live detail of the running step (e.g. the month being replayed)
        self._terminal = sys.stdout
        self._lines = 0
        self._frame = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ used by step actions
    def set_note(self, text: str) -> None:
        self.note = text

    def skip_rest(self, reason: str) -> None:
        for step in self.steps:
            if step.status == "pending":
                step.status, step.result = "skipped", reason

    # ------------------------------------------------------------------ running
    def run(self) -> None:
        if os.name == "nt" and self.color:
            os.system("")  # turns on ANSI escape codes in the Windows console
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")
        began = time.monotonic()
        if not self.live:
            print(f"\n{self.title}", flush=True)
        for number, step in enumerate(self.steps, 1):
            if step.status == "pending":
                self._run_step(number, step)
        total = duration(time.monotonic() - began)
        if self.live:
            self._draw()
            self._terminal.write(f"\n  {self._paint('✓ Sequence finished', GREEN, BOLD)} in {total}"
                                 f"  {self._paint('full output: ', DIM)}{self._log_link()}\n")
        else:
            print(f"\n✓ Sequence finished in {total}", flush=True)

    def _run_step(self, number: int, step: Step) -> None:
        step.status, step.began, self.note = "running", time.monotonic(), ""
        step.offset = self.log_path.stat().st_size
        stop = threading.Event()
        if self.live:
            self._draw()
            threading.Thread(target=self._tick, args=(stop,), daemon=True).start()
        else:
            print(f"\n━━ [{number}/{len(self.steps)}] {step.label} · {step.detail}", flush=True)
        try:
            if self.live:
                with (self.log_path.open("a", encoding="utf-8") as log, contextlib.redirect_stdout(log),
                      contextlib.redirect_stderr(log)):
                    result = step.action(self)
            else:
                result = step.action(self)
        except BaseException as exc:  # a failed tool (SystemExit), Ctrl+C or a bug: show where it stopped, re-raise
            stop.set()
            step.status, step.seconds = "failed", time.monotonic() - step.began
            if self.live:
                self._draw()
                reason = None if isinstance(exc, (SystemExit, KeyboardInterrupt)) else f"{type(exc).__name__}: {exc}"
                self._show_error(step, self._output_since(step.offset), reason)
            raise
        stop.set()
        step.seconds = time.monotonic() - step.began
        step.result = result or (dbt_summary(self._output_since(step.offset)) if self.live else "")
        if step.status == "running":
            step.status = "done"
        if not self.live:
            print(f"✓ [{number}/{len(self.steps)}] {step.label} · {duration(step.seconds)}"
                  + (f" · {step.result}" if step.result else ""), flush=True)

    def _output_since(self, offset: int) -> str:
        with self.log_path.open(encoding="utf-8", errors="replace") as log:
            log.seek(offset)
            return ANSI.sub("", log.read())

    def _log_tail(self, count: int) -> list[str]:
        """The last `count` non-empty lines of the log, for the right-hand pane."""
        with self.log_path.open("rb") as log:
            log.seek(max(log.seek(0, os.SEEK_END) - 16_000, 0))
            text = ANSI.sub("", log.read().decode("utf-8", errors="replace"))
        lines = [re.sub(r"^\d\d:\d\d:\d\d\s+", "", line.rstrip()) for line in text.splitlines()]
        return [line.replace("\t", " ") for line in lines if line.strip() and not re.fullmatch(r"\d\d:\d\d:\d\d", line.strip())][-count:]

    def _show_error(self, step: Step, output: str, reason: str | None) -> None:
        """The cause: an unexpected error's message, else the last dbt failure summary, else the last lines."""
        lines = [re.sub(r"^\d\d:\d\d:\d\d\s*", "", line.rstrip()) for line in output.splitlines()]
        lines = [line for line in lines if line.strip()]
        summaries = [i for i, line in enumerate(lines) if "Completed with" in line and "error" in line]
        start = summaries[-1] if summaries else max(len(lines) - 20, 0)
        excerpt = [reason] if reason else lines[start:start + 30]
        self._terminal.write(f"\n  {self._paint(f'✗ {step.label} failed', RED, BOLD)}"
                             f"  {self._paint('full output: ', DIM)}{self._log_link()}\n")
        self._terminal.write("".join(f"    {line}\n" for line in excerpt))
        self._terminal.flush()

    def _log_link(self) -> str:
        with contextlib.suppress(ValueError):
            name = str(self.log_path.relative_to(Path.cwd()))
            return hyperlink(self.log_path.resolve().as_uri(), name, self.color)
        return hyperlink(self.log_path.resolve().as_uri(), str(self.log_path), self.color)

    # ------------------------------------------------------------------ drawing
    def _tick(self, stop: threading.Event) -> None:
        while not stop.wait(0.12):
            self._frame += 1
            self._draw()

    def _draw(self) -> None:
        with self._lock:
            columns, rows = shutil.get_terminal_size((100, 30))
            left = self._render_rail(columns if columns < SPLIT_MIN_COLUMNS else LEFT_WIDTH)
            if columns >= SPLIT_MIN_COLUMNS:
                lines = self._side_by_side(left, columns)
            else:  # narrow terminal: the output goes under the rail
                lines = left + [""] + [f"  {self._paint(clip(line, columns - 3), DIM)}" for line in self._log_tail(6)]
            lines = lines[: max(rows - 1, 10)]
            if self._lines:
                self._terminal.write(f"\x1b[{self._lines}F\x1b[J")  # back to the top, clear below
            self._terminal.write("".join(line + "\n" for line in lines))
            self._terminal.flush()
            self._lines = len(lines)

    def _side_by_side(self, left: list[tuple[str, str]], columns: int) -> list[str]:
        pane = columns - LEFT_WIDTH - 3
        tail = self._log_tail(len(left) - 2)
        right = [self._paint(clip("live output", pane), BOLD), ""]
        right += [self._paint(clip(line, pane), DIM) for line in tail]
        right += [""] * (len(left) - len(right))
        divider = self._paint("│", DIM)
        return [f"{styled}{' ' * max(LEFT_WIDTH - len(plain), 0)} {divider} {pane_line}"
                for (plain, styled), pane_line in zip(left, right, strict=False)]

    def _render_rail(self, width: int) -> list[tuple[str, str]]:
        """Rail lines as (plain text, styled text) pairs: the plain one measures the width."""
        lines = [(f"  {self.title}", f"  {self._paint(self.title, BOLD)}"), ("", "")]
        for index, step in enumerate(self.steps):
            dot, color = {"done": ("●", GREEN), "running": ("◉", CYAN), "failed": ("✗", RED)}.get(step.status, ("○", DIM))
            if step.status == "running":
                status, tail, status_color = f"{SPINNER[self._frame % len(SPINNER)]} {duration(time.monotonic() - step.began)}", self.note, CYAN
            elif step.status == "done":
                status, tail, status_color = f"✓ {duration(step.seconds)}", step.result, GREEN
            elif step.status == "failed":
                status, tail, status_color = f"✗ {duration(step.seconds)}", "", RED
            elif step.status == "skipped":
                status, tail, status_color = "–", step.result, DIM
            else:
                status, tail, status_color = "", "", DIM
            label, detail, status = f"{step.label:<{LABEL_WIDTH}}", f"{step.detail:<{DETAIL_WIDTH}}", f"{status:<{STATUS_WIDTH}}"
            head = f"  {dot} {label} {detail} {status} "
            tail = clip(tail, width - len(head))
            lines.append((head + tail,
                          (f"  {self._paint(dot, color)} {self._paint(label, BOLD if step.status == 'running' else '')}"
                          f" {self._paint(detail, DIM)} {self._paint(status, status_color)} "
                          f"{self._paint(tail, DIM if step.status == 'skipped' else '')}")))
            if step.branches and step.status in ("running", "done", "failed"):
                lines += self._render_branches(step)
            if index < len(self.steps) - 1:
                connector = self._paint("┃", GREEN) if step.status == "done" else self._paint("┊", DIM)
                lines.append(("  ┃", f"  {connector}"))
        return lines

    def _render_branches(self, step: Step) -> list[tuple[str, str]]:
        """One line per group that dbt builds in parallel inside the step, filled in from the log."""
        started, finished, failed = set(), set(), set()
        for event, _, model in DBT_MODEL.findall(self._output_since(step.offset)):
            {"START": started, "OK created": finished, "ERROR creating": failed}[event].add(model)
        lines = []
        for position, (group, models) in enumerate(step.branches.items()):
            done = len(models & finished)
            if models & failed:
                dot, color = "✗", RED
            elif done == len(models) or step.status == "done":
                dot, color, done = "●", GREEN, len(models)
            elif models & started:
                dot, color = "◉", CYAN
            else:
                dot, color = "○", DIM
            elbow = "┗━" if position == len(step.branches) - 1 else "┣━"
            text = f"{group:<12} {done}/{len(models)} model{'s' * (len(models) != 1)}"
            lines.append((f"  {elbow}{dot} {text}",
                          (f"  {self._paint(elbow, GREEN if step.status == 'done' else CYAN)}{self._paint(dot, color)}"
                          f" {self._paint(text, DIM if dot == '○' else '')}")))
        return lines

    def _paint(self, text: str, *codes: str) -> str:
        codes = tuple(code for code in codes if code)
        if not self.color or not codes or not text:
            return text
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"


def dbt_summary(output: str) -> str:
    """'68 passed · 1 warning' from the `Done. PASS=… WARN=…` lines of the step's dbt runs."""
    if not DBT_DONE.search(output):
        return ""
    passed, warned, errors, skipped = (sum(int(match[i]) for match in DBT_DONE.findall(output)) for i in range(4))
    parts = [f"{passed} passed"]
    parts += [f"{warned} warning{'s' * (warned != 1)}"] if warned else []
    parts += [f"{errors} error{'s' * (errors != 1)}"] if errors else []
    parts += [f"{skipped} skipped"] if skipped else []
    return " · ".join(parts)


def duration(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def clip(text: str, room: int) -> str:
    if room <= 1:
        return ""
    return text if len(text) <= room else text[: room - 1] + "…"
