"""Upload a rendered video to a GitHub repo and return its public raw URL (adapted from upload_folder_to_github.py).

Uses the REST contents API directly (instead of PyGithub) so the request body can be streamed with a progress bar.
"""
import base64
import io
import json
import time
from pathlib import Path

import requests

from config import ROOT, load_settings
from progress import TransferProgress

API = "https://api.github.com"
RETRIES, FIRST_DELAY = 3, 5
MAX_BYTES = 100 * 1000 * 1000  # contents API limit per file


class ProgressBody(io.BytesIO):
    """Request body that reports how many bytes have been read (sent) so far."""

    def __init__(self, data: bytes, bar: TransferProgress):
        super().__init__(data)
        self.bar = bar

    def read(self, size=-1):
        chunk = super().read(size)
        self.bar.update(self.tell())
        return chunk


def raw_url(owner: str, repo_name: str, branch: str, repo_path: str) -> str:
    return f"https://github.com/{owner}/{repo_name}/raw/{branch}/{repo_path}"


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def existing_sha(contents_url: str, token: str, branch: str):
    """Blob sha of the file when it already exists (needed to update it), else None."""
    response = requests.get(contents_url, headers=auth_headers(token), params={"ref": branch}, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["sha"]


def put_file(token: str, contents_url: str, repo_path: str, content: bytes, branch: str) -> None:
    """Create or update the file, streaming the JSON body with a progress bar."""
    sha = existing_sha(contents_url, token, branch)
    payload = {"message": f"{'Update' if sha else 'Add'} {repo_path}", "branch": branch,
               "content": base64.b64encode(content).decode()}
    if sha:
        payload["sha"] = sha
    body = json.dumps(payload).encode()
    bar = TransferProgress(len(body))
    response = requests.put(contents_url, data=ProgressBody(body, bar),
                            headers={**auth_headers(token), "Content-Type": "application/json"}, timeout=600)
    response.raise_for_status()


def upload_video(token: str, owner: str, repo_name: str, video_path: Path, branch: str = "main",
                 repo_folder: str = None) -> str:
    """Upload to <repo_folder>/<name>.mp4 (default news_videos/YYYYMMDD, date from the local folder) with retries."""
    if not token:
        raise ValueError("GH_UPLOAD_TOKEN is not set")
    content = video_path.read_bytes()
    if len(content) > MAX_BYTES:
        raise ValueError(f"video is {len(content) / 1e6:.0f} MB; GitHub allows {MAX_BYTES // 10**6} MB per file")
    folder = repo_folder or f"news_videos/{video_path.parent.name}"
    repo_path = f"{folder}/{video_path.name}"
    contents_url = f"{API}/repos/{owner}/{repo_name}/contents/{repo_path}"
    print(f"    uploading {video_path.name} ({len(content) / 1e6:.1f} MB) to {owner}/{repo_name}", flush=True)

    delay = FIRST_DELAY
    for attempt in range(1, RETRIES + 1):
        try:
            put_file(token, contents_url, repo_path, content, branch)
            return raw_url(owner, repo_name, branch, repo_path)
        except Exception as exc:
            if attempt == RETRIES:
                raise RuntimeError(f"upload failed after {RETRIES} attempts: {exc}") from exc
            print(f"\n    - attempt {attempt} failed ({exc}); retrying in {delay}s", flush=True)
            time.sleep(delay)
            delay *= 2


def latest_output_video() -> Path:
    """Most recently modified mp4 under output/."""
    videos = sorted((ROOT / "output").glob("*/*.mp4"), key=lambda p: p.stat().st_mtime)
    if not videos:
        raise FileNotFoundError("no video found in output/ - run main.py --dry-run first")
    return videos[-1]


def test_upload(repo_folder: str = "news_videos/test") -> None:
    """Upload the newest generated video to <repo_folder> and check the public URL answers."""
    settings = load_settings()
    video_path = latest_output_video()
    print(f"Test upload of {video_path}")
    url = upload_video(settings.github_token, settings.github_owner, settings.github_repo,
                       video_path, repo_folder=repo_folder)
    status = requests.head(url, allow_redirects=True, timeout=60).status_code
    print(f"URL: {url}")
    print(f"HTTP status: {status} ({'ok' if status == 200 else 'check repo visibility / token'})")


if __name__ == "__main__":
    test_upload()
