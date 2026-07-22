"""
Shared YouTube URL → video id extraction.

Lives in services/ (not api/main.py) so BOTH the API and the Celery worker can
use the same parser without a circular import: api/main.py needs it to validate
POST /jobs input, api/worker.py needs it to key the per-video pipeline lock.
frontend/src/lib/youtubeUrl.js mirrors these accepted formats — keep in sync.
"""

from typing import Optional
from urllib.parse import urlparse, parse_qs


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract YouTube video ID from any common URL format:
      https://www.youtube.com/watch?v=CC8V0PwlQ4o
      https://youtu.be/CC8V0PwlQ4o
      https://youtube.com/shorts/CC8V0PwlQ4o
    Returns None if not a recognisable YouTube URL.
    """
    try:
        parsed = urlparse(url)
        # youtu.be/<id>
        if parsed.netloc in ("youtu.be",):
            return parsed.path.lstrip("/").split("/")[0] or None
        # youtube.com/watch?v=<id>
        if "youtube.com" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "v" in qs:
                return qs["v"][0]
            # youtube.com/shorts/<id>  or  youtube.com/embed/<id>
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "v"):
                return parts[1]
    except Exception:
        pass
    return None
