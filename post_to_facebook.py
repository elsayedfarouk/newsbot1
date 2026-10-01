"""Post a video to a Facebook Page (public URL or direct file upload) through the Graph API."""
from pathlib import Path

import requests

GRAPH_VERSION = "v19.0"
FACEBOOK_TITLE_MAX = 255


def send_video(access_token: str, page_id: str, fields: dict, video_file=None) -> dict:
    """POST to the page's /videos edge; `video_file` (open binary file) uploads it directly, else fields carry file_url."""
    if not access_token or not page_id:
        raise ValueError("FACEBOOK_PAGE_TOKEN and FACEBOOK_PAGE_ID must be set")
    response = requests.post(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/videos",
        data={"access_token": access_token, **fields},
        files={"source": video_file} if video_file else None,
        timeout=600,
    )
    if not response.ok:
        raise RuntimeError(f"Facebook returned {response.status_code}: {response.text}")
    return response.json()


def post_video_from_url(access_token: str, page_id: str, video_url: str,
                        title: str = "", description: str = "") -> dict:
    """Ask Facebook to fetch a public `video_url` and publish it on the page; returns the API response (video id)."""
    if not video_url:
        raise ValueError("no public video URL to post")
    fields = {"file_url": video_url, "title": title[:FACEBOOK_TITLE_MAX], "description": description}
    return send_video(access_token, page_id, fields)


def post_video_file(access_token: str, page_id: str, video_path, title: str = "", description: str = "") -> dict:
    """Upload a local video file directly to the page (no public URL needed)."""
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    fields = {"title": title[:FACEBOOK_TITLE_MAX], "description": description}
    print(f"    - uploading {path.name} ({path.stat().st_size / 1e6:.1f} MB) to Facebook")
    with path.open("rb") as handle:
        return send_video(access_token, page_id, fields, video_file=handle)


TEST_VIDEO = "output/20261001/news_202722_25d045f8.mp4"


def test_post(video_path: str = TEST_VIDEO) -> None:
    """Upload a local video file to the Facebook Page as a test (path relative to this folder)."""
    from config import ROOT, load_settings

    settings = load_settings()
    path = Path(video_path)
    path = path if path.is_absolute() else ROOT / path
    result = post_video_file(
        settings.facebook_token, settings.facebook_page_id, path,
        title="Test video - safe to delete",
        description="Test post from newsbot. Safe to delete. #test #news",
    )
    print(f"Posted {path.name}. Facebook video id: {result.get('id')}")


if __name__ == "__main__":
    test_post()
