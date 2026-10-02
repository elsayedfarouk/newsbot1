"""Hourly entry point: trending story -> Gemini visuals + Kokoro voice -> video -> sheet -> TikTok."""
import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path

import audio
import github_upload
import post_to_facebook
import publish_tiktok_video
import video
from config import Settings, load_settings
from planner import build_timeline
from progress import Pipeline
from renderer import FPS
from trends import SHEET_NAME

CATEGORY = "Trending"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and publish one trending news video.")
    parser.add_argument("--dry-run", action="store_true", help="render only: no sheet row, no TikTok post")
    return parser.parse_args()


def render_news_video(settings: Settings, client, news: dict, image_path: Path, pipe: Pipeline):
    """Visual plan -> voice -> timeline -> mp4. Returns (video_path, duration)."""
    # Heavy imports stay lazy: spawned render workers re-import this module on Windows.
    import gemini_client
    import tts

    narration = news["summary"]
    with pipe.step("Planning visuals with Gemini"):
        plan = gemini_client.generate_plan(client, settings.text_model, news["title"], narration, image_path)
        pipe.info(f'hook: "{plan.hook}"  |  {len(plan.beats)} callouts, {len(plan.focus_points)} focus points')

    wav_path = settings.work_dir / "voice.wav"
    with pipe.step("Recording voice-over (Kokoro)"):
        tts.text_to_wav(narration, wav_path, settings.tts_voice, settings.tts_speed)
        duration = audio.wav_duration(wav_path)
        pipe.info(f"voice-over length: {duration:.2f}s")

    with pipe.step("Aligning words (Whisper)"):
        words = audio.align_words(wav_path)
        pipe.info(f"{len(words)} words timed")

    with pipe.step("Planning scenes and text"):
        seed = int(hashlib.md5(news["link"].encode()).hexdigest()[:8], 16)
        timeline = build_timeline(plan, words, duration, seed)
        envelope = audio.loudness_envelope(wav_path, FPS)
        pipe.info(f"{len(timeline.scenes)} scenes, {len(timeline.texts)} text callouts")

    day_dir = settings.output_dir / datetime.now().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / f"news_{datetime.now():%H%M%S}_{seed:08x}.mp4"
    with pipe.step("Rendering video"):
        video.render_video(image_path, wav_path, settings.font_path, timeline, envelope, duration, out_path)

    with pipe.step("Verifying output"):
        video.verify_video(out_path, duration)
        pipe.info(f"{out_path.stat().st_size / 1e6:.1f} MB, 1080x1920, h264 + aac, {duration:.2f}s")
    return out_path, duration


def upload_to_github(settings: Settings, video_path: Path, pipe: Pipeline) -> str:
    """Public GitHub raw URL of the video; '' when the upload fails so the rest of the run continues."""
    with pipe.step("Uploading video to GitHub"):
        try:
            url = github_upload.upload_video(settings.github_token, settings.github_owner,
                                             settings.github_repo, video_path)
        except Exception as exc:
            pipe.fail(f"GitHub upload failed: {exc}")
            return ""
        pipe.info(url)
        return url


def publish(settings: Settings, processor, news: dict, video_path: Path, video_url: str, pipe: Pipeline) -> None:
    """Copy -> sheet row (with the GitHub video URL) -> TikTok -> Facebook. A failed post never loses the sheet record."""
    with pipe.step("Writing titles/descriptions and saving to Google Sheet"):
        copy = processor.generate_social_copy(news["title"], news["summary"], news["trend"])
        processor.save_to_sheet(news, CATEGORY, video_url, copy)
        pipe.info(f'YouTube: "{copy["youtube_title"]}"')
        pipe.info(f"TikTok caption {len(copy['tiktok_caption'])} chars, Facebook {len(copy['facebook_description'])} chars")
        pipe.info(f"row saved to '{SHEET_NAME}'")

    with pipe.step("Publishing to TikTok"):
        try:
            publish_tiktok_video.publish_tiktok_video(
                video_path, copy["tiktok_caption"], settings.zernio_api_key, settings.tiktok_account_id)
        except Exception as exc:
            pipe.fail(f"TikTok publish failed: {exc}")

    with pipe.step("Posting to Facebook"):
        try:
            result = post_to_facebook.post_video_from_url(
                settings.facebook_token, settings.facebook_page_id, video_url,
                copy["youtube_title"], copy["facebook_description"])
            pipe.info(f"posted, video id {result.get('id')}")
        except Exception as exc:
            pipe.fail(f"Facebook post failed: {exc}")


def main() -> int:
    args = parse_args()
    settings = load_settings()
    pipe = Pipeline(total_steps=7 if args.dry_run else 11)
    print("newsbot - one trending news video" + ("  [dry run]" if args.dry_run else ""))

    import gemini_client
    from trends import TrendingNewsProcessor

    client = gemini_client.make_client(settings.gemini_api_key)
    processor = TrendingNewsProcessor(client, settings.text_model, settings.country)

    with pipe.step("Finding a fresh trending story"):
        story = processor.find_story(settings.work_dir)
        if story is None:
            raise SystemExit("no fresh trending story with article text and image found")
        news, image_path = story
        pipe.info(news["title"])
        pipe.info(f"{news['link']}  |  narration {len(news['summary'])} chars")

    video_path, _ = render_news_video(settings, client, news, image_path, pipe)
    if not args.dry_run:
        video_url = upload_to_github(settings, video_path, pipe)
        publish(settings, processor, news, video_path, video_url, pipe)

    pipe.summary(str(video_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
