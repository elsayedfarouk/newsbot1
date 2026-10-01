"""WAV helpers: duration, loudness envelope, word-level alignment."""
import subprocess
import wave
from dataclasses import dataclass

import numpy as np


@dataclass
class Word:
    text: str
    start: float
    end: float


def wav_duration(path) -> float:
    with wave.open(str(path)) as wav:
        return wav.getnframes() / wav.getframerate()


def loudness_envelope(path, fps: int) -> np.ndarray:
    """Per-video-frame RMS loudness, normalised to ~1.0 at the 95th percentile."""
    with wave.open(str(path)) as wav:
        rate = wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32)
    n_frames = round(len(pcm) / rate * fps)
    rms = np.array([np.sqrt(np.mean(pcm[int(i / fps * rate):int((i + 1) / fps * rate)] ** 2) + 1e-9)
                    for i in range(n_frames)])
    rms = rms / np.percentile(rms, 95)
    return np.clip(np.convolve(rms, np.ones(3) / 3, mode="same"), 0, 1.2)


def align_words(path) -> list:
    """Word timestamps via faster-whisper (audio decoded by ffmpeg to avoid PyAV quirks)."""
    from faster_whisper import WhisperModel

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    model = WhisperModel("base.en", compute_type="int8")
    segments, _ = model.transcribe(audio, word_timestamps=True)
    return [Word(w.word.strip(), w.start, w.end) for seg in segments for w in seg.words]
