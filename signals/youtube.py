import httpx
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

YOUTUBE_QUERIES = [
    "Kuriftu resort review",
    "Ethiopia travel vlog",
    "Bishoftu lake resorts",
    "Ethiopia luxury hotels",
    "Visit Ethiopia guide",
    "Addis Ababa sightseeing",
    "Ethiopian tourism spots",
    "Ethiopia resort experience"
]

def _search_videos(query: str, api_key: str, days_back: int = 7) -> list:
    published_after = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    try:
        response = httpx.get(
            YOUTUBE_SEARCH_URL,
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "publishedAfter": published_after,
                "order": "date",
                "maxResults": 10,
                "key": api_key
            },
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        items = data.get("items", [])
        videos = []
        for item in items:
            snippet = item.get("snippet", {})
            videos.append({
                "title": snippet.get("title", ""),
                "description": snippet.get("description", "")[:200],
                "channel": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "video_id": item.get("id", {}).get("videoId", "")
            })
        return videos
    
    except Exception as e:
        print(f"[youtube] Search failed for query '{query}': {e}")
        return []

def _get_video_stats(video_ids: list, api_key: str) -> dict:
    if not video_ids:
        return {}
    
    try:
        response = httpx.get(
            YOUTUBE_VIDEOS_URL,
            params={
                "part": "statistics",
                "id": ",".join(video_ids[:10]),
                "key": api_key
            },
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        
        stats = {}
        for item in data.get("items", []):
            video_id = item.get("id", "")
            statistics = item.get("statistics", {})
            stats[video_id] = {
                "view_count": int(statistics.get("viewCount", 0)),
                "like_count": int(statistics.get("likeCount", 0)),
                "comment_count": int(statistics.get("commentCount", 0))
            }
        return stats
    
    except Exception as e:
        print(f"[youtube] Stats fetch failed: {e}")
        return {}

from decorators import with_retry

@with_retry()
def fetch_youtube_signal() -> dict:
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    
    if not api_key:
        return {
            "error": "YOUTUBE_API_KEY not set",
            "total_videos": 0,
            "combined_text": ""
        }
    
    all_videos = []
    
    for query in YOUTUBE_QUERIES:
        videos = _search_videos(query, api_key, days_back=7)
        for v in videos:
            v["query"] = query
        all_videos.extend(videos)
        time.sleep(0.5)
    
    seen_ids = set()
    unique_videos = []
    for v in all_videos:
        vid_id = v.get("video_id", "")
        if vid_id and vid_id not in seen_ids:
            seen_ids.add(vid_id)
            unique_videos.append(v)
    
    video_ids = [v["video_id"] for v in unique_videos if v.get("video_id")]
    stats = _get_video_stats(video_ids, api_key)
    # Removed time.sleep(2)
    
    total_views = sum(s.get("view_count", 0) for s in stats.values())
    total_videos = len(unique_videos)
    
    combined_text = "\n\n".join([
        f"Title: {v['title']}\nChannel: {v['channel']}\nDescription: {v['description']}"
        for v in unique_videos[:20]
        if v.get("title")
    ])[:5000]
    
    return {
        "total_videos_this_week": total_videos,
        "total_views_on_recent_videos": total_views,
        "queries_searched": YOUTUBE_QUERIES,
        "combined_text": combined_text,
        "video_titles": [v["title"] for v in unique_videos[:15]],
        "high_performing_videos": [
            {
                "title": v["title"],
                "channel": v["channel"],
                "views": stats.get(v["video_id"], {}).get("view_count", 0)
            }
            for v in unique_videos
            if stats.get(v.get("video_id", ""), {}).get("view_count", 0) > 1000
        ][:5]
    }
