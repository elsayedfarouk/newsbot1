"""Console progress: numbered pipeline steps with timings and a render bar with fps/ETA."""
import sys
import time
from contextlib import contextmanager

BAR_WIDTH = 28


def fmt_time(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


class Pipeline:
    """Prints `[n/total] title ... done (time)` for each step, plus a summary."""

    def __init__(self, total_steps: int):
        self.total = total_steps
        self.index = 0
        self.started = time.time()
        self.timings = []

    @contextmanager
    def step(self, title: str):
        self.index += 1
        print(f"\n[{self.index}/{self.total}] {title}", flush=True)
        t0 = time.time()
        try:
            yield
        except Exception:
            print(f"    x failed after {fmt_time(time.time() - t0)}", flush=True)
            raise
        elapsed = time.time() - t0
        self.timings.append((title, elapsed))
        print(f"    ok done in {fmt_time(elapsed)}", flush=True)

    def info(self, message: str) -> None:
        print(f"    - {message}", flush=True)

    def summary(self, result: str) -> None:
        print("\n" + "=" * 52)
        for title, elapsed in self.timings:
            print(f"  {title:<34}{fmt_time(elapsed):>8}")
        print("-" * 52)
        print(f"  {'total':<34}{fmt_time(time.time() - self.started):>8}")
        print(f"  output: {result}")
        print("=" * 52, flush=True)


class LiveBar:
    """One progress line: rewritten in place on a TTY, otherwise printed every few seconds."""

    TTY_INTERVAL, LOG_INTERVAL = 0.2, 3.0

    def __init__(self, total: float):
        self.total = total
        self.t0 = time.time()
        self.last_print = 0.0
        self.is_tty = sys.stdout.isatty()
        self.finished = False

    def update(self, done: float) -> None:
        if self.finished:
            return
        now = time.time()
        interval = self.TTY_INTERVAL if self.is_tty else self.LOG_INTERVAL
        finished = done >= self.total
        if not finished and now - self.last_print < interval:
            return
        self.last_print = now
        self.finished = finished
        frac = done / self.total
        rate = done / max(now - self.t0, 1e-6)
        eta = (self.total - done) / rate if rate else 0.0
        filled = int(BAR_WIDTH * frac)
        bar = "#" * filled + "." * (BAR_WIDTH - filled)
        line = f"    [{bar}] {frac * 100:5.1f}%  {self.detail(done, rate)}  ETA {fmt_time(eta)}"
        if self.is_tty:
            print("\r" + line + "   ", end="\n" if finished else "", flush=True)
        else:
            print(line, flush=True)

    def detail(self, done: float, rate: float) -> str:
        raise NotImplementedError


class RenderProgress(LiveBar):
    """Frames rendered -> video time and fps."""

    def __init__(self, total_frames: int, fps: int):
        super().__init__(total_frames)
        self.fps = fps

    def detail(self, done, rate):
        return (f"frame {int(done)}/{int(self.total)}  video {fmt_time(done / self.fps)}/{fmt_time(self.total / self.fps)}"
                f"  {rate:4.1f} fps")


class TransferProgress(LiveBar):
    """Bytes sent -> MB and MB/s."""

    def detail(self, done, rate):
        return f"{done / 1e6:5.1f}/{self.total / 1e6:.1f} MB  {rate / 1e6:4.1f} MB/s"
