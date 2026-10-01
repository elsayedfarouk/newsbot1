"""Google Trends -> article -> Gemini summary/caption -> Google Sheet row (adapted from trendingnow.py)."""
import html
import io
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
warnings.filterwarnings("ignore", message="nltk is not installed")  # NLP extras are not used
from newspaper import Article  # noqa: E402
from PIL import Image

import gemini_client
import googlesheet

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/115.0.0.0 Safari/537.36"}
TRENDS_NS = {"ht": "https://trends.google.com/trending/rss"}
EMPTY_ARTICLE = {"text": "", "top_image": "", "html": "", "canonical_link": "", "title": "", "publish_date": ""}
CTA = "If you like our content, don't forget to like and subscribe to our channel, NEWS TODAY."
MIN_SUMMARY_CHARS, MIN_IMAGE_WIDTH, TIKTOK_MAX_CHARS = 150, 600, 2200
TITLE_COLUMN, LINK_COLUMN = 4, 9
SPREADSHEET_NAME, SHEET_NAME = "TrendingNewsToday", "Trending"

SUMMARY_PROMPT = """You are a professional news anchor.

TASK:
Summarize the following news article as a broadcast-ready news report.

STRICT RULES:
- Output ONLY the summary text.
- Do NOT include introductions, conclusions, explanations, or meta comments.
- Do NOT say phrases like: "Here's a news report", "This article discusses", "In summary", "Good evening", "Good morning".
- Do NOT address the audience.
- Do NOT mention liking, subscribing, or the channel.
- Write in a neutral, professional news anchor tone.
- Ensure smooth flow suitable for text-to-speech.
- Length must be approximately 1000 characters.

OUTPUT FORMAT:
- Plain text only. No quotes. No headings. No extra lines before or after the summary.

NEWS ARTICLE:
{content}
"""

CAPTION_PROMPT = """You are a top social media strategist and SEO expert for a viral TikTok news channel named "NEWS TODAY".

TASK:
Create a highly engaging, SEO-optimized, and visually formatted TikTok video caption based on the following news story.

REQUIREMENTS:
1. LENGTH (STRICT): between 1,980 and 2,150 characters. NEVER exceed 2,200 characters.
2. STRUCTURE:
   - Catchy headline and hook with relevant emojis.
   - Detailed news breakdown: key details, background, facts, implications, as bullet points and short paragraphs.
   - High-engagement call to action: a thought-provoking question, invite comments, follow @NewsToday for daily breaking news.
   - Dense SEO hashtag block (#NewsToday, #BreakingNews, #Trending, topic-specific tags, names, organizations).
3. TONE: professional yet conversational, viral, easy to read on mobile, clean line breaks.

NEWS TITLE:
{title}

TREND / TOPIC:
{trend}

NEWS SUMMARY / CONTEXT:
{summary}

OUTPUT: only the ready-to-post caption text. No explanations, no character-count notes, no markdown fences.
"""


def say(message: str) -> None:
    print(f"    - {message}", flush=True)


def strip_code_fence(text: str) -> str:
    if text.startswith("```") and text.endswith("```"):
        return "\n".join(text.splitlines()[1:-1]).strip()
    return text


def download_image(url: str, dest: Path) -> Path:
    """Download and re-save as JPEG; raises when the image is missing or too small."""
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    if image.width < MIN_IMAGE_WIDTH:
        raise ValueError(f"image too small ({image.width}px wide)")
    image.save(dest, "JPEG", quality=95)
    return dest


class TrendingNewsProcessor:
    def __init__(self, client, model: str, country: str):
        self.client, self.model, self.country = client, model, country

    # ---------- source ----------
    def fetch_trending_items(self) -> list:
        url = f"https://trends.google.com/trending/rss?geo={self.country}"
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        items = ET.fromstring(response.content).findall(".//item")
        say(f"{len(items)} trending topics ({self.country})")
        return items

    def extract_article_content(self, news_url: str) -> dict:
        if not news_url:
            return dict(EMPTY_ARTICLE)
        try:
            article = Article(url=news_url, fetch_images=True, keep_article_html=True)
            article.download()
            article.parse()
            return {
                "text": article.text or "",
                "top_image": article.top_image or "",
                "html": article.article_html or "",
                "canonical_link": article.canonical_link or "",
                "title": article.title or "",
                "publish_date": str(article.publish_date) if article.publish_date else "",
            }
        except Exception as exc:
            say(f"article extraction failed ({news_url}): {exc}")
            return dict(EMPTY_ARTICLE)

    # ---------- Gemini ----------
    def generate_summary(self, content: str):
        try:
            summary = gemini_client.generate_text(self.client, self.model, SUMMARY_PROMPT.format(content=content))
        except Exception as exc:
            say(f"Gemini summary failed: {exc}")
            return None
        return summary or None

    def generate_tiktok_caption(self, title: str, summary: str, trend_keyword: str = "") -> str:
        prompt = CAPTION_PROMPT.format(title=title, trend=trend_keyword, summary=summary)
        try:
            caption = strip_code_fence(gemini_client.generate_text(self.client, self.model, prompt))
        except Exception as exc:
            say(f"Gemini caption failed, using title: {exc}")
            return title
        if not caption:
            return title
        if len(caption) > TIKTOK_MAX_CHARS:
            caption = caption[:TIKTOK_MAX_CHARS - 5].rsplit(" ", 1)[0]
        return caption

    # ---------- processing ----------
    def is_duplicate(self, title: str, link: str) -> bool:
        try:
            return (googlesheet.text_in_column(SPREADSHEET_NAME, SHEET_NAME, title, TITLE_COLUMN)
                    or googlesheet.text_in_column(SPREADSHEET_NAME, SHEET_NAME, link, LINK_COLUMN))
        except Exception as exc:
            say(f"duplicate check failed, assuming new: {exc}")
            return False

    def process_trend_item(self, item):
        """First usable news item of a trend as a dict (title, date, summary, image, website, link, trend); else None."""
        if item is None:
            return None
        keyword = item.findtext("title") or "Unknown Trend"
        traffic = item.findtext("ht:approx_traffic", namespaces=TRENDS_NS) or "N/A"
        rss_picture = item.findtext("ht:picture", namespaces=TRENDS_NS) or ""
        pub_date = item.findtext("pubDate") or ""
        news_items = item.findall("ht:news_item", namespaces=TRENDS_NS)
        say(f"trend '{keyword}' ({traffic} searches, {len(news_items)} articles)")

        for news_item in news_items:
            data = self._build_news_data(news_item, keyword, traffic, rss_picture, pub_date)
            if data:
                return data
        return None

    def _build_news_data(self, news_item, keyword, traffic, rss_picture, pub_date):
        try:
            url = news_item.findtext("ht:news_item_url", namespaces=TRENDS_NS)
            if not url:
                return None
            news_title = html.unescape(news_item.findtext("ht:news_item_title", namespaces=TRENDS_NS) or "")
            snippet = html.unescape(news_item.findtext("ht:news_item_snippet", namespaces=TRENDS_NS) or "")
            source = news_item.findtext("ht:news_item_source", namespaces=TRENDS_NS) or ""

            article = self.extract_article_content(url)
            title = news_title or article["title"] or keyword
            clean_title = title.rsplit("-", 1)[0].strip() if "-" in title else title
            image_url = article["top_image"] or rss_picture
            content = f"{title} {snippet} {article['text']}".strip()
            if not content or not image_url:
                return None
            if self.is_duplicate(clean_title, url):
                say(f"already in sheet, skipping: {clean_title}")
                return None

            summary = self.generate_summary(content)
            if not summary or len(summary.strip()) < MIN_SUMMARY_CHARS:
                say("summary missing or too short, trying next article")
                return None
            return {
                "title": clean_title,
                "date": pub_date or article["publish_date"],
                "summary": f"{summary.strip()} {CTA}",
                "image": image_url,
                "website": urlparse(url).netloc or source,
                "link": url,
                "trend": keyword,
                "traffic": traffic,
            }
        except Exception as exc:
            say(f"news item failed: {exc}")
            return None

    def find_story(self, work_dir: Path, limit: int = 10):
        """First fresh trending story whose image downloads: (news_data, image_path) or None."""
        work_dir.mkdir(parents=True, exist_ok=True)
        for item in self.fetch_trending_items()[:limit]:
            news_data = self.process_trend_item(item)
            if not news_data:
                continue
            try:
                return news_data, download_image(news_data["image"], work_dir / "article.jpg")
            except Exception as exc:
                say(f"image unusable ({exc}), trying next trend")
        return None

    # ---------- output ----------
    def save_to_sheet(self, news_data: dict, category: str, video_path: str, caption: str) -> None:
        values = ["pending", category, self.country, news_data.get("title"), news_data.get("date"),
                  news_data.get("summary"), news_data.get("image"), news_data.get("website"),
                  news_data.get("link"), video_path, caption]
        googlesheet.add_row([str(v) if v is not None else "" for v in values], SPREADSHEET_NAME, SHEET_NAME)
