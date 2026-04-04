import httpx
from bs4 import BeautifulSoup
import re
from playwright.async_api import async_playwright

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

def _extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r'\s+', ' ', text)
    return text[:8000]

def _level1_scrape(url: str) -> str | None:
    try:
        response = httpx.get(url, timeout=10, follow_redirects=True)
        response.raise_for_status()
        text = _extract_text_from_html(response.text)
        if len(text) > 300:
            print(f"[scraper] Level 1 (basic httpx) succeeded for {url}")
            return text
        return None
    except Exception as e:
        print(f"[scraper] Level 1 failed: {e}")
        return None

def _level2_scrape(url: str) -> str | None:
    try:
        response = httpx.get(url, headers=BROWSER_HEADERS, timeout=15, follow_redirects=True)
        response.raise_for_status()
        text = _extract_text_from_html(response.text)
        if len(text) > 300:
            print(f"[scraper] Level 2 (httpx + headers) succeeded for {url}")
            return text
        return None
    except Exception as e:
        print(f"[scraper] Level 2 failed: {e}")
        return None

async def _level3_scrape(url: str) -> str | None:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=BROWSER_HEADERS["User-Agent"],
                locale="en-US"
            )
            page = await context.new_page()
            await page.goto(url, timeout=25000, wait_until="networkidle")
            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()
        text = _extract_text_from_html(html)
        if len(text) > 300:
            print(f"[scraper] Level 3 (Playwright) succeeded for {url}")
            return text
        return None
    except Exception as e:
        print(f"[scraper] Level 3 failed: {e}")
        return None

from ddgs import DDGS

def _search_intel(url: str) -> str | None:
    print(f"[scraper] Level 4 (Search Intel) attempting for {url}...")
    try:
        # Extract domain name as a search term
        domain = url.split("//")[-1].split("/")[0].replace("www.", "")
        query = f"{domain} hotel profile rooms amenities location"
        
        ddgs = DDGS()
        results = ddgs.text(query, max_results=5)
        
        combined_text = ""
        for r in results:
            combined_text += f"Title: {r.get('title', '')}\nSnippet: {r.get('body', '')}\n\n"
            
        if len(combined_text) > 200:
            print(f"[scraper] Level 4 (Search Intel) succeeded for {url}")
            return combined_text
        return None
    except Exception as e:
        print(f"[scraper] Level 4 failed: {e}")
        return None

async def scrape_website_async(url: str) -> dict:
    if not url.startswith("http"):
        url = "https://" + url
    
    # Try direct scrape levels
    text = _level1_scrape(url)
    if text: return {"success": True, "text": text, "method": "basic"}
    
    text = _level2_scrape(url)
    if text: return {"success": True, "text": text, "method": "headers"}
    
    text = await _level3_scrape(url)
    if text: return {"success": True, "text": text, "method": "playwright"}
    
    # Fail-over to Search Intel
    text = _search_intel(url)
    if text:
        return {"success": True, "text": text, "method": "search_intel"}
    
    print(f"[scraper] All levels failed for {url}")
    return {"success": False, "text": "", "method": "failed"}
