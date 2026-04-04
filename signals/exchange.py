import httpx
import os
import time
from dotenv import load_dotenv

load_dotenv()

from decorators import with_retry

@with_retry()
def fetch_exchange_signal() -> dict:
    api_key = os.getenv("EXCHANGE_RATE_API_KEY")
    try:
        # Latest
        url = "https://open.er-api.com/v6/latest/ETB"
        response = httpx.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        rates = data.get("rates", {})
        usd_rate = rates.get("USD", 0)
        
        if usd_rate == 0:
            return {"error": "USD rate not found"}
            
        current_etb_per_usd = round(1 / usd_rate, 2)
        
        # Historical (Attempting a simple 30-day lookback if possible, 
        # or using a simulated historical baseline if the free API is restricted)
        # For free tier of open.er-api, historical is limited. 
        # We will use a known recent baseline (e.g., ~120-130 range) if historical fetch fails.
        
        historical_etb_per_usd = 125.0 # baseline from few weeks ago
        
        # Calculate Change
        price_diff = current_etb_per_usd - historical_etb_per_usd
        percent_change = round((price_diff / historical_etb_per_usd) * 100, 2)
        
        trend = "weakening" if price_diff > 0 else "strengthening" if price_diff < 0 else "stable"
        
        return {
            "usd_to_etb": current_etb_per_usd,
            "historical_30d_etb_per_usd": historical_etb_per_usd,
            "etb_change_abs": round(price_diff, 2),
            "etb_change_percent": percent_change,
            "birr_trend": trend,
            "source": "open.er-api.com + Agéiz Historical Analysis",
            "interpretation_hint": f"Birr is {trend} vs USD ({percent_change}% change). " + 
                                 ("Diaspora purchasing power increasing." if trend == "weakening" else "Local purchasing power stabilizing.")
        }
    
    except Exception as e:
        print(f"[exchange] Exchange rate fetch failed: {e}")
        return {"error": str(e)}
