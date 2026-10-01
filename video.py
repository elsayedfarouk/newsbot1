"""Parallel frame rendering piped into ffmpeg, then a verification pass."""
import json
import multiprocessing as mp
import os
import subprocess
from pathlib import Path

from planner import FRAME_H, FRAME_W
from progress import RenderProgress
from renderer import FPS, FrameRenderer

_renderer = None


def _init_worker(image_path, font_path, timeline, envelope, duration):
    global _renderer
    _renderer = FrameRenderer(image_path, font_path, timeline, envelope, duration)


def _render_frame(index: int) -> bytes:
    return _renderer.render(index).tobytes()


def ffmpeg_command(wav_path: Path, duration: float, out_path: Path) -> list:
    return [
        "ffmpeg", "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{FRAME_W}x{FRAME_H}", "-r", str(FPS), "-i", "-",
        "-i", str(wav_path), "-map", "0:v", "-map", "1:a", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-maxrate", "6M", "-bufsize", "12M",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(out_path),
    ]


def render_video(image_path, wav_path, font_path, timeline, envelope, duration, out_path) -> None:
    n_frames = round(duration * FPS)
    workers = max(1, os.cpu_count() or 1)
    encoder = subprocess.Popen(ffmpeg_command(wav_path, duration, out_path), stdin=subprocess.PIPE)
    bar = RenderProgress(n_frames, FPS)
    print(f"    rendering {n_frames} frames on {workers} worker(s) - starting workers...", flush=True)
    with mp.Pool(workers, _init_worker, (image_path, font_path, timeline, envelope, duration)) as pool:
        for done, frame in enumerate(pool.imap(_render_frame, range(n_frames), chunksize=4), start=1):
            encoder.stdin.write(frame)
            bar.update(done)
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise RuntimeError("ffmpeg failed")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,duration", "-of", "json", str(path)],
        capture_output=True, check=True, text=True,
    ).stdout
    return json.loads(out)


def verify_video(path: Path, expected_duration: float) -> None:
    streams = probe(path)["streams"]
    video = next(s for s in streams if s["codec_name"] == "h264")
    audio = next(s for s in streams if s["codec_name"] == "aac")
    if (video["width"], video["height"]) != (FRAME_W, FRAME_H):
        raise RuntimeError("wrong resolution")
    for stream in (video, audio):
        if abs(float(stream["duration"]) - expected_duration) > 0.1:
            raise RuntimeError(f"{stream['codec_name']} duration mismatch")
