import feedparser
import httpx
import time
from ddgs import DDGS

RSS_FEEDS = [
    "https://www.thereporterethiopia.com/feed/",
    "https://ethiopianmonitor.com/feed/",
    "https://www.fanabc.com/english/feed/",
    "https://www.ezega.com/rss/news.xml",
    "https://www.capitalethiopia.com/feed/",
    "https://borkena.com/feed/",
    "https://www.ethiopiaobserver.com/feed/",
]

DDGO_QUERIES = [
    "Ethiopia tourism news",
    "Ethiopia supply chain disruptions",
    "Ethiopia fuel prices inflation",
    "Ethiopian birr devaluation economic impact",
    "Ethiopia import export news",
    "Addis Ababa manufacturing and logistics",
    "Kuriftu resort Ethiopia",
    "Ethiopia travel trends"
]

def _fetch_rss_feeds() -> list:
    articles = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "")
                summary = entry.get("summary", "")[:300]
                link = entry.get("link", "")
                if title:
                    articles.append({
                        "source": feed_url,
                        "title": title,
                        "summary": summary,
                        "link": link
                    })
            time.sleep(0.5)
        except Exception as e:
            print(f"[news] RSS feed failed for {feed_url}: {e}")
            continue
    return articles

def _fetch_duckduckgo_news() -> list:
    results = []
    ddgs = DDGS()
    for query in DDGO_QUERIES:
        try:
            search_results = ddgs.text(query, max_results=3)
            for r in search_results:
                results.append({
                    "source": "duckduckgo",
                    "query": query,
                    "title": r.get("title", ""),
                    "summary": r.get("body", "")[:300],
                    "link": r.get("href", "")
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"[news] DuckDuckGo failed for query '{query}': {e}")
            time.sleep(5)
            continue
    return results

from decorators import with_retry

@with_retry()
def fetch_news_signal() -> dict:
    print("[news] Fetching RSS feeds...")
    rss_articles = _fetch_rss_feeds()
    
    print("[news] Fetching DuckDuckGo results...")
    ddgo_articles = _fetch_duckduckgo_news()
    
    all_articles = rss_articles + ddgo_articles
    
    if not all_articles:
        return {
            "error": "No news articles retrieved",
            "rss_count": 0,
            "ddgo_count": 0,
            "combined_text": ""
        }
    
    combined_text = "\n\n".join([
        f"Title: {a['title']}\nSummary: {a['summary']}"
        for a in all_articles if a.get('title')
    ])[:6000]
    
    return {
        "rss_count": len(rss_articles),
        "ddgo_count": len(ddgo_articles),
        "total_articles": len(all_articles),
        "combined_text": combined_text,
        "article_titles": [a["title"] for a in all_articles[:20]]
    }
