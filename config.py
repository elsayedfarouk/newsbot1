"""Runtime settings, read once from environment variables (.env supported)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

FONT_CANDIDATES = (
    ROOT / "assets" / "Anton-Regular.ttf",
    Path("C:/Windows/Fonts/impact.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    text_model: str
    tts_voice: str
    tts_speed: float
    country: str
    github_token: str
    github_owner: str
    github_repo: str
    zernio_api_key: str
    tiktok_account_id: str
    facebook_token: str
    facebook_page_id: str
    font_path: Path
    work_dir: Path
    output_dir: Path


def find_font() -> Path:
    override = os.getenv("FONT_PATH")
    for path in ([Path(override)] if override else []) + list(FONT_CANDIDATES):
        if path.exists():
            return path
    raise FileNotFoundError("No usable font found; set FONT_PATH or put Anton-Regular.ttf in assets/")


def first_env(*names: str) -> str:
    """First non-empty environment variable among `names` (lets old variable names keep working)."""
    return next((os.environ[n] for n in names if os.environ.get(n)), "")


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")  # real environment variables (CI secrets) take precedence
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        text_model=os.getenv("GEMINI_TEXT_MODEL", "gemini-3.5-flash-lite"),
        tts_voice=os.getenv("KOKORO_VOICE", "am_adam"),
        tts_speed=float(os.getenv("KOKORO_SPEED", "1.0")),
        country=os.getenv("COUNTRY", "US"),
        github_token=first_env("GH_UPLOAD_TOKEN", "GITHUB_UPLOAD_TOKEN", "token_github", "TOKEN_GITHUB"),
        github_owner=first_env("GH_OWNER", "GITHUB_OWNER") or "elsayedfarouk",
        github_repo=first_env("GH_REPO", "GITHUB_REPO") or "public",
        zernio_api_key=os.getenv("ZERNIO_API_KEY", ""),
        tiktok_account_id=os.getenv("TIKTOK_ACCOUNT_ID", ""),
        facebook_token=first_env("FACEBOOK_PAGE_TOKEN", "token_facebook"),
        facebook_page_id=os.getenv("FACEBOOK_PAGE_ID", ""),
        font_path=find_font(),
        work_dir=ROOT / "work",
        output_dir=ROOT / "output",
    )
