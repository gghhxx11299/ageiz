import httpx
import time
from datetime import date
from decorators import with_retry

ETHIOPIA_LOCATIONS = {
    "Addis Ababa": {"lat": 9.02, "lon": 38.75, "baseline_rain": 1200, "baseline_temp": 20, "type": "city"},
    "Bishoftu": {"lat": 8.75, "lon": 38.98, "baseline_rain": 900, "baseline_temp": 22, "type": "lake_resort"},
    "Hawassa": {"lat": 7.05, "lon": 38.48, "baseline_rain": 1000, "baseline_temp": 23, "type": "lake_resort"},
    "Bahir Dar": {"lat": 11.59, "lon": 37.39, "baseline_rain": 1400, "baseline_temp": 25, "type": "lake_resort"},
    "Gondar": {"lat": 12.60, "lon": 37.47, "baseline_rain": 1100, "baseline_temp": 23, "type": "historical"},
    "Lalibela": {"lat": 12.03, "lon": 39.03, "baseline_rain": 900, "baseline_temp": 19, "type": "historical"},
    "Jimma": {"lat": 7.67, "lon": 36.83, "baseline_rain": 1600, "baseline_temp": 21, "type": "highland"},
    "Dire Dawa": {"lat": 9.60, "lon": 41.85, "baseline_rain": 600, "baseline_temp": 27, "type": "city"},
    "Mekelle": {"lat": 13.50, "lon": 39.47, "baseline_rain": 500, "baseline_temp": 21, "type": "city"},
    "Arba Minch": {"lat": 6.03, "lon": 37.55, "baseline_rain": 900, "baseline_temp": 26, "type": "lake_resort"},
    "Shashamane": {"lat": 7.20, "lon": 38.60, "baseline_rain": 1100, "baseline_temp": 21, "type": "highland"},
    "Debre Markos": {"lat": 10.35, "lon": 37.73, "baseline_rain": 1300, "baseline_temp": 19, "type": "highland"},
    "Dessie": {"lat": 11.13, "lon": 39.63, "baseline_rain": 800, "baseline_temp": 20, "type": "highland"},
    "Harar": {"lat": 9.31, "lon": 42.12, "baseline_rain": 700, "baseline_temp": 22, "type": "historical"},
    "Axum": {"lat": 14.13, "lon": 38.73, "baseline_rain": 550, "baseline_temp": 20, "type": "historical"},
    "Soddo": {"lat": 6.87, "lon": 37.75, "baseline_rain": 1000, "baseline_temp": 20, "type": "highland"},
    "Wolaita Sodo": {"lat": 6.87, "lon": 37.75, "baseline_rain": 1000, "baseline_temp": 20, "type": "highland"},
    "Debre Birhan": {"lat": 9.68, "lon": 39.53, "baseline_rain": 900, "baseline_temp": 16, "type": "highland"},
    "Adama": {"lat": 8.54, "lon": 39.27, "baseline_rain": 800, "baseline_temp": 24, "type": "city"},
    "Entoto": {"lat": 9.07, "lon": 38.72, "baseline_rain": 1300, "baseline_temp": 17, "type": "highland"},
    # Region-level mappings (fallback)
    "Amhara Highlands": {"lat": 12.00, "lon": 38.00, "baseline_rain": 1200, "baseline_temp": 20, "type": "highland"},
    "Oromia Highlands": {"lat": 8.50, "lon": 38.50, "baseline_rain": 1100, "baseline_temp": 21, "type": "highland"},
    "SNNPR": {"lat": 7.00, "lon": 37.50, "baseline_rain": 1000, "baseline_temp": 22, "type": "highland"},
    "Southern Nations": {"lat": 7.00, "lon": 37.50, "baseline_rain": 1000, "baseline_temp": 22, "type": "highland"},
    "Tigray": {"lat": 14.00, "lon": 39.00, "baseline_rain": 600, "baseline_temp": 21, "type": "historical"},
    "Amhara": {"lat": 11.50, "lon": 38.00, "baseline_rain": 1100, "baseline_temp": 21, "type": "highland"},
    "Oromia": {"lat": 8.50, "lon": 39.00, "baseline_rain": 1000, "baseline_temp": 22, "type": "highland"},
    "Somali": {"lat": 9.50, "lon": 43.00, "baseline_rain": 400, "baseline_temp": 28, "type": "lowland"},
    "Afar": {"lat": 11.50, "lon": 41.00, "baseline_rain": 300, "baseline_temp": 30, "type": "lowland"},
    "Benishangul": {"lat": 10.50, "lon": 35.50, "baseline_rain": 1200, "baseline_temp": 25, "type": "highland"},
    "Gambela": {"lat": 8.00, "lon": 34.50, "baseline_rain": 1400, "baseline_temp": 27, "type": "lowland"},
    "Sidama": {"lat": 6.75, "lon": 38.50, "baseline_rain": 1100, "baseline_temp": 21, "type": "highland"},
    "Kuriftu": {"lat": 8.75, "lon": 38.98, "baseline_rain": 900, "baseline_temp": 22, "type": "lake_resort"},
    "Kuriftu Bishoftu": {"lat": 8.75, "lon": 38.98, "baseline_rain": 900, "baseline_temp": 22, "type": "lake_resort"},
    "Kuriftu Hawassa": {"lat": 7.05, "lon": 38.48, "baseline_rain": 1000, "baseline_temp": 23, "type": "lake_resort"},
    "Kuriftu Bahir Dar": {"lat": 11.59, "lon": 37.39, "baseline_rain": 1400, "baseline_temp": 25, "type": "lake_resort"},
    "Debre Zeyit": {"lat": 8.75, "lon": 38.98, "baseline_rain": 900, "baseline_temp": 22, "type": "lake_resort"},
    "Moucha Island": {"lat": 12.50, "lon": 43.00, "baseline_rain": 200, "baseline_temp": 30, "type": "island"},
    "Djibouti": {"lat": 11.59, "lon": 43.15, "baseline_rain": 150, "baseline_temp": 32, "type": "city"},
}

# Seasonal rainfall baselines for Ethiopia (mm per month)
SEASONAL_RAINFALL_MM = {
    1: 20, 2: 30, 3: 50,   # Dry season (Jan-Mar)
    4: 60, 5: 70,           # Small rains (Apr-May)
    6: 100, 7: 180, 8: 190, # Main rainy season (Jun-Aug)
    9: 130, 10: 50,         # End of rains (Sep-Oct)
    11: 20, 12: 10          # Dry season (Nov-Dec)
}

def resolve_location(location_name: str) -> dict | None:
    """Resolve a location name to coordinates, with fuzzy matching."""
    # Direct match
    if location_name in ETHIOPIA_LOCATIONS:
        return ETHIOPIA_LOCATIONS[location_name]
    
    # Case-insensitive match
    for key, val in ETHIOPIA_LOCATIONS.items():
        if key.lower() == location_name.lower():
            return val
    
    # Partial match - check if any key is contained in the location name
    for key, val in ETHIOPIA_LOCATIONS.items():
        if key.lower() in location_name.lower() or location_name.lower() in key.lower():
            return val
    
    return None

@with_retry()
def fetch_weather(location_name: str) -> dict:
    loc = resolve_location(location_name)
    if loc is None:
        return {"error": f"Location {location_name} not found"}
    
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily=precipitation_sum,temperature_2m_max,temperature_2m_min"
        f"&forecast_days=16&timezone=Africa%2FAddis_Ababa"
    )
    
    try:
        response = httpx.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        daily = data.get("daily", {})
        precipitation = daily.get("precipitation_sum", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        dates = daily.get("time", [])
        
        total_forecast_rain = sum(p for p in precipitation if p is not None)
        avg_daily_rain = total_forecast_rain / len(precipitation) if precipitation else 0
        
        current_month = date.today().month
        seasonal_avg = SEASONAL_RAINFALL_MM.get(current_month, 50)
        seasonal_daily_avg = seasonal_avg / 30
        
        if seasonal_daily_avg > 0:
            rain_ratio = avg_daily_rain / seasonal_daily_avg
        else:
            rain_ratio = 1.0
        
        avg_temp = sum(t for t in temp_max if t is not None) / len(temp_max) if temp_max else 0
        
        # Removed time.sleep(2)
        
        return {
            "location": location_name,
            "location_type": loc["type"],
            "forecast_days": len(dates),
            "total_forecast_precipitation_mm": round(total_forecast_rain, 2),
            "avg_daily_precipitation_mm": round(avg_daily_rain, 2),
            "seasonal_avg_daily_mm": round(seasonal_daily_avg, 2),
            "rainfall_vs_seasonal_ratio": round(rain_ratio, 2),
            "rainfall_deficit_percent": round((1 - rain_ratio) * 100, 1) if rain_ratio < 1 else 0,
            "rainfall_surplus_percent": round((rain_ratio - 1) * 100, 1) if rain_ratio > 1 else 0,
            "avg_max_temperature_c": round(avg_temp, 1),
            "forecast_dates": dates[:16],
            "daily_precipitation": precipitation[:16]
        }
    except Exception as e:
        print(f"[weather] Failed to fetch weather for {location_name}: {e}")
        return {"error": str(e), "location": location_name}

def fetch_highland_commodity_signal() -> dict:
    highland_locations = ["Amhara Highlands", "Oromia Highlands", "SNNPR"]
    results = []
    for loc in highland_locations:
        data = fetch_weather(loc)
        if "error" not in data:
            results.append(data)
        # Removed time.sleep(2)
    
    if not results:
        return {"error": "Could not fetch highland weather data"}
    
    avg_deficit = sum(r.get("rainfall_deficit_percent", 0) for r in results) / len(results)
    avg_surplus = sum(r.get("rainfall_surplus_percent", 0) for r in results) / len(results)
    
    return {
        "highland_locations_checked": highland_locations,
        "average_rainfall_deficit_percent": round(avg_deficit, 1),
        "average_rainfall_surplus_percent": round(avg_surplus, 1),
        "commodity_pressure": "high" if avg_deficit > 30 else "moderate" if avg_deficit > 15 else "low",
        "individual_readings": results
    }
