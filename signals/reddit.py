import time
from ddgs import DDGS

from decorators import with_retry

@with_retry()
def fetch_reddit_signal() -> dict:
    """
    Fetch Reddit context using DuckDuckGo search to avoid direct scraping blocks.
    This provides a much more robust community signal.
    """
    print("[reddit] Fetching Reddit intelligence via Search Intel...")
    
    queries = [
        "site:reddit.com Ethiopia travel experience",
        "site:reddit.com Addis Ababa resorts reviews",
        "site:reddit.com Kuriftu resort experience",
        "site:reddit.com Ethiopia tourism safety news"
    ]
    
    all_results = []
    ddgs = DDGS()
    
    for query in queries:
        try:
            results = ddgs.text(query, max_results=5)
            for r in results:
                all_results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "link": r.get("href", "")
                })
            time.sleep(0.5) # Polite delay
        except Exception as e:
            print(f"[reddit] Search failed for '{query}': {e}")
            continue
            
    if not all_results:
        return {
            "error": "Reddit search signal unavailable",
            "total_posts": 0,
            "combined_text": ""
        }
        
    combined_text = "\n\n".join([
        f"Thread: {r['title']}\nSnippet: {r['snippet']}"
        for r in all_results
    ])[:5000]
    
    return {
        "total_posts": len(all_results),
        "sources_checked": len(queries),
        "combined_text": combined_text,
        "post_titles": [r["title"] for r in all_results[:15]],
        "method": "search_intel"
    }
