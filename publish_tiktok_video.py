"""Publish a local video to TikTok through Zernio (falls back to Creator Inbox draft when at capacity)."""
import mimetypes
from pathlib import Path

import requests

API_BASE = "https://zernio.com/api/v1"


def is_account_id(value: str) -> bool:
    return bool(value) and len(value) == 24 and all(c in "0123456789abcdefABCDEF" for c in value)


def upload_media(file_path: Path, api_key: str) -> str:
    """Upload via Zernio's presigned-URL flow; returns the public URL."""
    content_type = mimetypes.guess_type(str(file_path))[0] or "video/mp4"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"filename": file_path.name, "contentType": content_type, "size": file_path.stat().st_size}

    presign = requests.post(f"{API_BASE}/media/presign", headers=headers, json=payload, timeout=60)
    presign.raise_for_status()
    urls = presign.json()

    with file_path.open("rb") as handle:
        upload = requests.put(urls["uploadUrl"], data=handle, headers={"Content-Type": content_type}, timeout=600)
    upload.raise_for_status()
    return urls["publicUrl"]


def resolve_account_id(api_key: str, identifier: str = None) -> str:
    """24-char Zernio accountId for TikTok: the identifier itself, a username match, or the first TikTok account."""
    if is_account_id(identifier):
        return identifier
    response = requests.get(f"{API_BASE}/accounts", headers={"Authorization": f"Bearer {api_key}"}, timeout=60)
    response.raise_for_status()
    accounts = response.json().get("accounts", [])
    tiktok = [a for a in accounts if a.get("platform") == "tiktok"]
    if not tiktok:
        connected = [f"{a.get('platform')}: {a.get('username', a.get('_id'))}" for a in accounts]
        raise ValueError(f"No connected TikTok account in Zernio (connected: {connected or 'none'})")

    wanted = (identifier or "").lstrip("@").lower()
    chosen = next((a for a in tiktok if wanted and (a.get("username") or "").lstrip("@").lower() == wanted), tiktok[0])
    print(f"    - TikTok account: @{chosen.get('username')} ({chosen.get('_id')})")
    return chosen["_id"]


def create_post(client, caption: str, video_url: str, account_id: str, draft: bool) -> dict:
    settings = {
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "allow_comment": True,
        "allow_duet": True,
        "allow_stitch": True,
        "content_preview_confirmed": True,
        "express_consent_given": True,
    }
    if draft:
        settings["draft"] = True
    result = client.posts.create_post(
        content=caption,
        media_items=[{"type": "video", "url": video_url}],
        platforms=[{"platform": "tiktok", "accountId": account_id}],
        tiktok_settings=settings,
        publish_now=True,
    )
    return result.get("post", result)


def at_capacity(post: dict) -> bool:
    errors = [(p.get("error") or "").lower() for p in post.get("platforms", [])]
    return post.get("status") == "failed" and any("capacity" in e or "creator inbox" in e for e in errors)


def publish_tiktok_video(video_path, caption: str, api_key: str, account_id: str = None, as_draft: bool = False) -> dict:
    video_file = Path(video_path)
    if not video_file.is_file():
        raise FileNotFoundError(f"Video not found: {video_file}")
    if not api_key:
        raise ValueError("ZERNIO_API_KEY is not set")

    from zernio import Zernio  # lazy: heavy import, only needed when actually publishing

    client = Zernio(api_key=api_key)
    resolved_id = resolve_account_id(api_key, account_id)
    print(f"    - uploading {video_file.name} ({video_file.stat().st_size / 1e6:.1f} MB)")
    video_url = upload_media(video_file, api_key)

    post = create_post(client, caption, video_url, resolved_id, as_draft)
    if at_capacity(post) and not as_draft:
        print("    - TikTok direct posting at capacity, retrying as Creator Inbox draft")
        post = create_post(client, caption, video_url, resolved_id, draft=True)

    print(f"    - post {post.get('_id')} status: {post.get('status')}")
    if post.get("platformPostUrl"):
        print(f"    - live: {post['platformPostUrl']}")
    return post
