import json
from ai_client import call_ai_for_json
from database import save_recommendation, save_cache

def generate_recommendation(hotel_profile: dict, location: str, today_signals: dict, weekly_summary: dict) -> dict:
    
    hotel_name = hotel_profile.get("hotel_name", "Unknown Hotel")
    brand_positioning = hotel_profile.get("brand_positioning", "Not specified")
    target_guests = hotel_profile.get("target_guest_segments", "Not specified")
    price_range = hotel_profile.get("price_range", "Not specified")
    room_types = hotel_profile.get("room_types", "Standard rooms")
    amenities = hotel_profile.get("amenities", "Basic amenities")
    
    weekly_context = ""
    if weekly_summary.get("available"):
        weekly_context = f"""
THIS WEEK'S TREND SUMMARY:
Overall sentiment: {weekly_summary.get('overall_weekly_sentiment')}
Positivity ratio: {weekly_summary.get('overall_positivity_ratio')}
"""
    
    prompt = f"""You are Agéiz, a revenue intelligence engine for Ethiopian resorts.

Hotel: {hotel_name}
Location: {location}
Brand Positioning: {brand_positioning}
Target Segments: {target_guests}
Market Tier: {price_range}
Available Amenities: {amenities}
Room Types: {room_types}

TODAY'S MARKET SIGNALS:
{json.dumps(today_signals, indent=2)}

{weekly_context}

Provide specific pricing adjustments for this hotel's assets. 
IMPORTANT: You MUST list EVERY SINGLE AMENITY from the 'Available Amenities' list above in the 'specific_adjustments' array. 
If an amenity does not require a price change based on current signals, set its adjustment to "+0%" and logic to "Stable demand".

Return ONLY this JSON:
{{
  "room_rates": {{
    "standard_rooms": "+X%" or "-X%" or "+0%",
    "suites_and_premium": "+X%" or "-X%" or "+0%",
    "reasoning": "Strategy for rooms"
  }},
  "food_beverage": {{
    "restaurant_menu": "+X%" or "-X%" or "+0%",
    "bar_and_events": "+X%" or "-X%" or "+0%",
    "reasoning": "Strategy for F&B"
  }},
  "amenities_and_facilities": {{
    "specific_adjustments": [
       {{"asset": "Name of EVERY amenity from the list", "adjustment": "+X%", "logic": "reasoning"}},
       ...
    ],
    "reasoning": "Overall facility yield strategy"
  }},
  "overall_confidence": "X%",
  "urgency": "act now" or "act soon" or "hold" or "reduce now",
  "trend_context": "One sentence executive summary",
  "key_drivers": ["driver 1", "driver 2"],
  "risk_factors": ["risk 1", "risk 2"]
}}"""

    try:
        result = call_ai_for_json(prompt, use_heavy_model=True)
        
        # Validate required fields
        required_sections = ["room_rates", "food_beverage", "amenities_and_facilities", "overall_confidence", "urgency"]
        for section in required_sections:
            if section not in result:
                raise ValueError(f"Missing required section: {section}")
        
        valid_urgencies = ["act now", "act soon", "hold", "reduce now"]
        if result.get("urgency") not in valid_urgencies:
            result["urgency"] = "hold"
        
        # Room adjustments for saving
        room_adj = result.get("room_rates", {})
        room_summary = f"Standard: {room_adj.get('standard_rooms')}, Premium: {room_adj.get('suites_and_premium')}"
        
        save_recommendation(
            hotel_id=hotel_profile["id"],
            location=location,
            room_rate_adjustment=room_summary,
            package_adjustment=json.dumps(result.get("amenities_and_facilities", {})),
            confidence=result.get("overall_confidence", "0%"),
            urgency=result["urgency"],
            reasoning=result.get("room_rates", {}).get("reasoning", "") + " | " + result.get("amenities_and_facilities", {}).get("reasoning", ""),
            trend_context=result.get("trend_context", ""),
            signals_snapshot=json.dumps(today_signals)
        )
        
        save_cache(
            hotel_id=hotel_profile["id"],
            location=location,
            cache_type="latest_recommendation",
            data=json.dumps(result)
        )
        
        return result
    
    except Exception as e:
        print(f"[pricing_engine] Failed to generate recommendation: {e}")
        fallback = {
            "room_rates": {"standard_rooms": "0%", "suites_and_premium": "0%", "reasoning": f"System error: {str(e)}"},
            "food_beverage": {"restaurant_menu": "0%", "bar_and_events": "0%", "reasoning": "Fallback"},
            "amenities_and_facilities": {"specific_adjustments": [], "reasoning": "Fallback"},
            "overall_confidence": "0%",
            "urgency": "hold",
            "trend_context": "System failure during intelligence generation",
            "key_drivers": [],
            "risk_factors": [str(e)]
        }
        return fallback
