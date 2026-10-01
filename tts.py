"""Local text-to-speech with Kokoro (GPU when available, CPU otherwise)."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from kokoro import KModel, KPipeline

SAMPLE_RATE = 24000


@dataclass
class TtsEngine:
    model: KModel
    pipeline: KPipeline
    voice: str
    voice_pack: torch.Tensor
    device: str


def load_engine(voice: str) -> TtsEngine:
    """Load the Kokoro model and voice once; the voice's first letter selects the language."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = KModel().to(device).eval()
    pipeline = KPipeline(lang_code=voice[0], model=False)
    return TtsEngine(model, pipeline, voice, pipeline.load_voice(voice), device)


def run_model(engine: TtsEngine, phonemes: str, speed: float) -> np.ndarray:
    """Synthesize one phoneme chunk, falling back to CPU if the GPU run fails."""
    style = engine.voice_pack[len(phonemes) - 1]
    try:
        audio = engine.model(phonemes, style, speed)
    except Exception:
        if engine.device == "cpu":
            raise
        print("    ! GPU synthesis failed, retrying on CPU")
        engine.model.to("cpu")
        engine.device = "cpu"
        audio = engine.model(phonemes, style.cpu(), speed)
    return audio.cpu().numpy()


def synthesize(engine: TtsEngine, text: str, speed: float = 1.0) -> np.ndarray:
    """Text -> mono waveform at 24 kHz (empty array if nothing was generated)."""
    chunks = [run_model(engine, phonemes, speed)
              for _, phonemes, _ in engine.pipeline(text.strip(), engine.voice, speed)]
    return np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)


def text_to_wav(text: str, wav_path: Path, voice: str = "am_adam", speed: float = 1.0) -> Path:
    """Generate speech for `text` and save it as a WAV file."""
    audio = synthesize(load_engine(voice), text, speed)
    if audio.size == 0:
        raise RuntimeError("Kokoro generated no audio")
    sf.write(str(wav_path), audio, SAMPLE_RATE)
    return wav_path
