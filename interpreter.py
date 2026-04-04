import json
from ai_client import call_ai_for_json

SIGNAL_MODELS = {
    "weather": False,
    "calendar": False,
    "flights": False,
    "trends": False,
    "exchange": False,
    "news": True,
    "reddit": False,
    "youtube": False,
}

SIGNAL_PROMPTS = {
    "weather": """You are analyzing weather data for an Ethiopian resort pricing intelligence system.

You understand these specific Ethiopian market dynamics:
- Rainfall deficit in Oromia and Amhara highlands means pasture stress, livestock weight loss, and reduced milk production — beef, lamb, and dairy costs rise 2-4 weeks later at resort kitchens
- Heavy rainfall during June-August Kiremt season reduces leisure travel from Addis Ababa — families stay home, weekend resort bookings drop significantly
- Dry sunny weather October through January is Ethiopia's peak tourism season — demand naturally higher across all resort categories
- Extreme heat in lowland areas like Awash reduces guest comfort — guests prefer highland resorts during hot periods
- Good highland rains mean abundant teff, vegetables, and grain supply — F&B input costs lower for the coming month
- Drought conditions correlate with broader food inflation nationally — affects all menu costs not just meat
- Unexpected cold snaps on Entoto mountain affect heating costs and guest comfort expectations
- Flooding risk during heavy rain affects road access to lake resorts like Bishoftu

Raw weather data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence explaining what this specific weather pattern means for this resort's pricing and costs — be specific about which commodities or guest behaviors are affected and the likely timeframe"
}}""",

    "calendar": """You are analyzing the Ethiopian Orthodox and public holiday calendar for resort pricing intelligence.

You understand these specific Ethiopian holiday dynamics:
- Fasika (Ethiopian Easter) is the single highest demand event for lake resorts — Bishoftu sees 300%+ occupancy, book out weeks in advance
- Timket (Epiphany, January 19) involves water blessing ceremonies — lake resorts are especially popular, diaspora travel peaks
- Genna (Ethiopian Christmas, January 7) brings diaspora visitors home from US, Europe, and Middle East — premium spending, 2-3 week stay patterns
- Enkutatash (Ethiopian New Year, September 11) is a major domestic tourism event — families travel together, resort packages sell well
- Meskel (September 27) involves outdoor celebrations — resort grounds and outdoor dining areas at premium
- Eid al Fitr and Eid al Adha bring Muslim Ethiopian travelers and diaspora — significant market segment
- Ethiopian Orthodox fasting covers 180+ days per year — during fasting periods meat and dairy revenue drops sharply, vegetarian dishes dominate F&B revenue
- Post-fasting periods (after Fasika, after Genna) see massive surge in meat consumption — F&B margins improve sharply
- Long weekends created by public holidays drive spontaneous Addis Ababa resident bookings to nearby resorts
- Patriots Victory Day (May 5) and other national holidays create 3-day weekend patterns

Raw calendar data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about upcoming holiday demand pressure — name the specific holiday, its specific impact on this type of resort, and the urgency of pricing action"
}}""",

    "flights": """You are analyzing flight arrival data at Addis Ababa Bole International Airport for resort pricing intelligence.

You have two data sources:
1. OpenSky: Real-time arrival counts and weekly trends (Primary for volume)
2. Amadeus: Search intent and "inspiration" (Secondary for intent)

If Amadeus data shows an error or is unavailable, IGNORE it and base your entire analysis on the OpenSky arrival trends. Do not report a failure if OpenSky data is present.

Ethiopian aviation dynamics:
- Ethiopian Airlines is the dominant carrier; route expansions signal new tourist markets.
- Diaspora travelers from DC, London, Dubai are the highest-spending resort guests.
- Arrivals surge before Christmas (Jan), Timket (Jan), Fasika (April), and Enkutatash (Sept).
- Rising arrival trends at Bole (HAAB) directly correlate with resort demand 3-10 days later.

Raw flight data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about arrival trends — specify if volume is rising/falling based on OpenSky and what that means for booking pressure"
}}""",

    "trends": """You are analyzing Google Trends search interest data for Ethiopian tourism and resort pricing intelligence.

You understand these specific search behavior dynamics in the Ethiopian market:
- Ethiopians in the diaspora search for Ethiopian resorts 3-4 weeks before their planned travel dates
- "Kuriftu resort" search spikes directly correlate with bookings 7-14 days later
- "Bishoftu lake" searches spike before long weekends and Orthodox holidays
- "Ethiopia travel" searches from US and European IP addresses signal diaspora holiday planning
- Search interest for "Ethiopia hotel" from Gulf countries signals Muslim diaspora travel around Eid periods
- Rising searches for "Ethiopia tourism" in general media often follow positive international press coverage
- Search volume dropping below seasonal baseline is an early warning signal for slow periods
- "Ethiopian Airlines booking" search volume correlates with overall inbound travel intent

Raw trends data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about search interest trend — specify which keywords are moving, what traveler segment they represent, and what booking behavior this predicts in the next 1-2 weeks"
}}""",

    "exchange": """You are analyzing currency exchange rate data for Ethiopian resort pricing intelligence.

You understand these specific Ethiopian currency dynamics:
- Birr depreciation (weakening) makes Ethiopia cheaper for USD, EURholders — diaspora guests have larger discount effectively.
- Birr appreciation (strengthening) increases local purchasing power but makes diaspora spend less relative to before.
- NBE periodic adjustments can cause sudden movements.
- Parallel vs Official market gaps affect cash behavior.

Raw exchange data (includes 30-day historical comparison):
{raw_data}

Analyze the trend (strengthening vs weakening) and the magnitude of the change.
Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" (weakening) or "negative" (strengthening) or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about what the current Birr trend means for your pricing — if Birr is strengthening, local guests have more power; if weakening, diaspora are the key target."
}}""",

    "news": """You are analyzing news articles about Ethiopian tourism and hospitality for resort pricing intelligence.

You understand these specific Ethiopian news dynamics:
- Positive international travel features about Ethiopia in BBC, CNN Travel, Lonely Planet directly drive diaspora and foreign bookings
- Ethiopian Airlines route announcements signal new tourist source markets opening within 3-6 months
- Political stability news directly affects foreign tourist confidence — foreign ministry travel advisories are major demand suppressors
- Ethiopian government tourism campaigns and visa-on-arrival expansions boost inbound tourism
- Local Ethiopian news about infrastructure improvements near resorts signals upcoming demand growth
- Food inflation news signals F&B cost pressure across the hospitality sector
- Fuel price increase news signals higher transport costs — reduces spontaneous weekend trips from Addis
- Coverage of Ethiopian cultural events, film festivals, or sports events drives short-term demand spikes
- Security incidents anywhere in Ethiopia suppress bookings even if the resort location is unaffected
- Positive Kuriftu-specific press coverage drives direct bookings within 1-2 weeks

Raw news data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence summarizing the dominant news theme and its specific likely impact on resort bookings — name the specific news factor driving the sentiment"
}}""",

    "reddit": """You are analyzing Reddit posts about Ethiopia travel and resorts for pricing intelligence.

You understand these specific Reddit dynamics for Ethiopia:
- r/Ethiopia and r/AddisAbaba are small communities — even 5-10 posts about a resort is a meaningful signal
- Post volume about Ethiopian travel is more important than individual post content given small community size
- Diaspora Ethiopians in r/Ethiopia frequently discuss travel home plans — seasonal patterns visible in post timing
- Positive experience posts about specific resorts drive referral bookings among diaspora communities
- Complaints about Ethiopian hospitality in Reddit are visible to diaspora deciding where to stay
- r/travel posts about Ethiopia signal mainstream international tourist interest — different segment from diaspora
- Post engagement (upvotes, comments) indicates how much the Ethiopian travel topic is resonating
- Absence of posts is also a signal — low buzz means low organic interest this week

Raw Reddit data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about social media buzz level and sentiment — be honest if data is thin and explain what the volume itself signals even if individual posts are not highly relevant"
}}""",

    "youtube": """You are analyzing YouTube video data about Ethiopian tourism and resorts for pricing intelligence.

You understand these specific YouTube dynamics for Ethiopia:
- Travel vloggers posting about Kuriftu or Bishoftu drive bookings from their audience within 1-2 weeks of posting
- High view counts on recent Ethiopia travel videos signal rising mainstream international interest
- Ethiopian diaspora YouTube creators posting about home visits influence diaspora travel decisions significantly
- Ethiopian Airlines travel content and destination videos drive awareness of specific resort locations
- Multiple creators posting about Ethiopia in the same week signals a coordinated travel trend or press trip
- Low video upload frequency about Ethiopia travel signals a quiet period with lower organic demand
- Videos about specific Ethiopian holidays signal diaspora travel intent for that holiday period
- International travel channel coverage of Ethiopia reaches audiences that Reddit and social media do not

Raw YouTube data:
{raw_data}

Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about YouTube content trends for Ethiopian tourism — specify video volume, view performance, and what creator activity signals for upcoming resort demand"
}}"""
}

NEUTRAL_FALLBACK = {
    "sentiment": "neutral",
    "strength": "weak",
    "interpretation": "Signal unavailable — excluded from analysis due to data retrieval failure"
}

def interpret_signal(signal_type: str, raw_data: dict) -> dict:
    if not raw_data:
        print(f"[interpreter] Signal {signal_type} returned empty data — using neutral fallback")
        return NEUTRAL_FALLBACK.copy()
    
    if "error" in raw_data and len(raw_data) == 1:
        print(f"[interpreter] Signal {signal_type} has only error — using neutral fallback")
        return NEUTRAL_FALLBACK.copy()
    
    prompt_template = SIGNAL_PROMPTS.get(signal_type)
    if not prompt_template:
        print(f"[interpreter] No prompt template for signal type {signal_type} — using neutral fallback")
        return NEUTRAL_FALLBACK.copy()
    
    raw_data_str = json.dumps(raw_data, indent=2)[:3000]
    prompt = prompt_template.replace("{raw_data}", raw_data_str)
    
    use_heavy = SIGNAL_MODELS.get(signal_type, False)
    
    try:
        result = call_ai_for_json(prompt, use_heavy_model=use_heavy)
        
        if "sentiment" not in result or "interpretation" not in result:
            print(f"[interpreter] Incomplete response for {signal_type} — using fallback")
            return NEUTRAL_FALLBACK.copy()
        
        if result["sentiment"] not in ["positive", "negative", "neutral"]:
            result["sentiment"] = "neutral"
        
        if result.get("strength") not in ["strong", "moderate", "weak"]:
            result["strength"] = "moderate"

        print(f"[interpreter] {signal_type}: {result['sentiment']} ({result['strength']}) — {result['interpretation'][:80]}...")
        return result

    except Exception as e:
        print(f"[interpreter] Failed to interpret {signal_type}: {e}")
        return NEUTRAL_FALLBACK.copy()


def interpret_custom_signal(config: dict, raw_data: dict) -> dict:
    """Interpret a custom signal source using AI, guided by the user's description.
    Returns a safe result dict even if AI call fails.
    """
    name = config.get("name", "Unknown")
    description = config.get("description", "")

    if "error" in raw_data:
        return {
            "sentiment": "neutral",
            "strength": "weak",
            "interpretation": f"Custom source '{name}' unavailable — {raw_data['error']}"
        }

    prompt = f"""You are analyzing a custom data source for Ethiopian resort pricing intelligence.

Source: {name}
Purpose: {description}

Raw data from this source:
{json.dumps(raw_data, indent=2, default=str)[:2000]}

Based on the PURPOSE described above, analyze what this data means for hotel pricing, demand, or costs.
Return ONLY this JSON with no other text:
{{
  "sentiment": "positive" or "negative" or "neutral",
  "strength": "strong" or "moderate" or "weak",
  "interpretation": "one clear sentence about what this custom data source means for resort pricing or demand — be specific about the Ethiopian context"
}}"""

    try:
        result = call_ai_for_json(prompt, use_heavy_model=False)
        if "sentiment" not in result:
            result["sentiment"] = "neutral"
        if "interpretation" not in result:
            result["interpretation"] = f"Custom source '{name}' returned data but AI could not produce an interpretation"
        if result.get("strength") not in ["strong", "moderate", "weak"]:
            result["strength"] = "moderate"

        print(f"[interpreter] custom_{name}: {result['sentiment']} ({result['strength']}) — {result['interpretation'][:80]}...")
        return result
    except Exception as e:
        print(f"[interpreter] ⚠ Failed to interpret custom source '{name}': {e}")
        # Return a safe fallback — never crash the pipeline
        return {
            "sentiment": "neutral",
            "strength": "weak",
            "interpretation": f"Custom source '{name}' interpretation failed: {str(e)[:150]}"
        }
