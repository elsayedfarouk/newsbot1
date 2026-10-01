# newsbot

Hourly: Google Trends -> article (newspaper) -> Gemini summary -> Kokoro voice + Gemini visual plan -> Whisper word timing
-> animated 1080x1920 video in `output/YYYYMMDD/` -> GitHub upload -> Google Sheet row (GitHub video URL + caption) -> TikTok via Zernio.
Duplicates are detected against the sheet (title column 4, link column 9).

## Setup
1. Push this folder as its own repo.
2. Repo secrets: `GEMINI_API_KEY`, `GOOGLE_CREDENTIALS_B64`, `ZERNIO_API_KEY`, `GITHUB_UPLOAD_TOKEN`. Each run also uploads `output/` as an Actions artifact (7 days).
3. Optional env: `COUNTRY`, `TIKTOK_ACCOUNT_ID`, `GITHUB_OWNER`, `GITHUB_REPO`, `GEMINI_TEXT_MODEL`, `KOKORO_VOICE`, `KOKORO_SPEED`.

## Local
```
pip install -r requirements.txt     # plus ffmpeg and espeak-ng on PATH
copy .env.example .env      # then put your GEMINI_API_KEY in .env
python main.py --dry-run    # renders to output/YYYYMMDD/, no sheet row, no TikTok post
```

## Layout
`main.py` orchestration | `trends.py` Trends/article/summary/caption/sheet | `gemini_client.py` Gemini | `tts.py` Kokoro | `audio.py` timing
| `planner.py` scenes + text timeline | `renderer.py` frames | `video.py` ffmpeg | `googlesheet.py` | `publish_tiktok_video.py`
