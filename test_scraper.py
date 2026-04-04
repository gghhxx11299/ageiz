import asyncio
from scraper import scrape_website_async
import json

async def test_onboard_scraper():
    test_urls = [
        "https://www.kurifturesorts.com/",
        "https://www.hailehotelsandresorts.com/"
    ]
    
    print("--- Agéiz Scraper Test ---")
    
    for url in test_urls:
        print(f"\nTesting URL: {url}")
        try:
            result = await scrape_website_async(url)
            if result["success"]:
                print(f"✅ Success! Method used: {result['method']}")
                text_len = len(result['text'])
                print(f"   Text length retrieved: {text_len} chars")
                print(f"   Snippet: {result['text'][:200]}...")
            else:
                print(f"❌ Failed: {result.get('error', 'Unknown error')}")
        except Exception as e:
            print(f"💥 Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_onboard_scraper())
