"""A rich, in-place live progress display for classification.

Renders one updating block (not a stream of lines): a config list, a progress bar
with elapsed/ETA, the ok/excluded/failed tally, cumulative usage cost, and a
usage-limit "waiting" status. Falls back to terse plain lines when not on a TTY.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable


def fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


class ProgressReporter:
    """Thread-safe progress state with a rich renderable (`__rich__`)."""

    def __init__(self, config: dict, *, clock: Callable[[], float] = time.time) -> None:
        self.config = config
        self._clock = clock
        self.total = 0
        self.already = 0
        self.done = self.ok = self.excluded = self.failed = 0
        self.cost = 0.0
        self.wait_until: float | None = None
        self.start = clock()
        self._lock = threading.Lock()
        self.interactive = sys.stderr.isatty()
        self._last_plain = 0

    # --- callbacks passed to classify_pending -------------------------------
    def on_start(self, total: int, already: int) -> None:
        with self._lock:
            self.total = total
            self.already = already
            self.start = self._clock()
        if not self.interactive:
            cfg = ", ".join(f"{k}={v}" for k, v in self.config.items())
            print(f"[classify] {cfg}", file=sys.stderr, flush=True)
            print(f"[classify] resume checkpoint: {already} already done · {total} to do",
                  file=sys.stderr, flush=True)

    def on_progress(self, ev: dict) -> None:
        with self._lock:
            self.done = ev["done"]
            self.ok = ev["ok"]
            self.excluded = ev["excluded"]
            self.failed = ev["failed"]
            self.cost = ev["cost"]
            self.wait_until = None
        if not self.interactive and (self.done - self._last_plain >= 25 or self.done == self.total):
            self._last_plain = self.done
            print(f"[classify] {self.done}/{self.total} ok={self.ok} excl={self.excluded} "
                  f"fail={self.failed} ${self.cost:.2f} ETA {fmt_dur(self._eta())}",
                  file=sys.stderr, flush=True)

    def on_wait(self, seconds_left: float, reset_at: int | None) -> None:
        target = float(reset_at) if reset_at else (self._clock() + seconds_left)
        with self._lock:
            self.wait_until = target
        if not self.interactive:
            print(f"[classify] usage limit reached — waiting ~{fmt_dur(seconds_left)} then resuming",
                  file=sys.stderr, flush=True)

    # --- rendering ----------------------------------------------------------
    def _eta(self) -> float | None:
        el = self._clock() - self.start
        if self.done <= 0 or el <= 0:
            return None
        return (self.total - self.done) * (el / self.done)

    def __rich__(self):  # noqa: C901 - presentational
        from rich.console import Group
        from rich.panel import Panel
        from rich.progress_bar import ProgressBar
        from rich.table import Table
        from rich.text import Text

        with self._lock:
            done, total, ok, exc, fail = self.done, self.total, self.ok, self.excluded, self.failed
            cost, wait, already = self.cost, self.wait_until, self.already

        cfg = Table.grid(padding=(0, 2))
        cfg.add_column(style="cyan", justify="right")
        cfg.add_column(style="white")
        for k, v in self.config.items():
            cfg.add_row(k, str(v))
        if already:
            cfg.add_row("resumed", f"{already} already classified")

        el = self._clock() - self.start
        eta = (total - done) * (el / done) if done > 0 and el > 0 else None
        pct = (100 * done / total) if total else 0.0

        stat = Text()
        stat.append(f"{done}/{total}  ", style="bold")
        stat.append(f"{pct:4.1f}%    ")
        stat.append(f"elapsed {fmt_dur(el)}    ")
        stat.append(f"ETA {fmt_dur(eta)}\n", style="cyan")
        stat.append("ok ", style="dim")
        stat.append(f"{ok}   ", style="green")
        stat.append("excl ", style="dim")
        stat.append(f"{exc}   ", style="yellow")
        stat.append("fail ", style="dim")
        stat.append(f"{fail}   ", style="red" if fail else "dim")
        stat.append("usage ", style="dim")
        stat.append(f"${cost:.2f}", style="magenta")

        prog = Table.grid()
        prog.add_column()
        prog.add_row(ProgressBar(total=max(total, 1), completed=done))
        prog.add_row(stat)
        body = [cfg, Text(), prog]
        if wait:
            remaining = max(0.0, wait - self._clock())
            when = time.strftime("%H:%M", time.localtime(wait))
            body.append(Text(
                f"\n⏳ usage limit reached — waiting ~{fmt_dur(remaining)} (resumes ≈{when}); "
                "it continues automatically.",
                style="bold yellow",
            ))
        return Panel(Group(*body), title="Classifying r/EB2_NIW", border_style="blue", padding=(1, 2))
