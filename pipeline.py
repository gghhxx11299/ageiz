import json
import time
import asyncio
import traceback
from database import save_signal, save_cache, get_hotel_profile, update_pipeline_task
from signals.weather import fetch_weather, fetch_highland_commodity_signal
from signals.calendar import fetch_calendar_signal
from signals.flights import fetch_flight_signal
from signals.trends import fetch_trends_signal
from signals.news import fetch_news_signal
from signals.reddit import fetch_reddit_signal
from signals.exchange import fetch_exchange_signal
from signals.youtube import fetch_youtube_signal
from interpreter import interpret_signal
from weekly_summary import build_weekly_summary
from pricing_engine import generate_recommendation


def _safe_json(obj, fallback="{}"):
    """JSON serialize with fallback for unserializable objects."""
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        try:
            return json.dumps(str(obj)[:2000])
        except Exception:
            return fallback


def _safe_save_signal(hotel_id, location, signal_type, sentiment, interpretation, raw_data):
    """Wrap save_signal in try/except so one bad signal doesn't crash the pipeline."""
    try:
        save_signal(hotel_id, location, signal_type, sentiment, interpretation, raw_data)
    except Exception as e:
        print(f"[pipeline] ⚠ Failed to save signal '{signal_type}' for {location}: {e}")
        print(traceback.format_exc())


async def run_pipeline(hotel_id: int, task_id: int = None) -> dict:
    print(f"\n[pipeline] Starting parallel pipeline for hotel_id={hotel_id}")
    if task_id:
        try:
            update_pipeline_task(task_id, 'running', progress=5, message='Initializing Parallel Scan', thoughts='Booting multitasking engine...\nOptimizing concurrent data streams.')
        except Exception as e:
            print(f"[pipeline] ⚠ Failed to update task status: {e}")

    # --- Load hotel profile ---
    try:
        hotel_profile = get_hotel_profile(hotel_id)
    except Exception as e:
        print(f"[pipeline] ⚠ Error fetching hotel profile: {e}")
        return {"error": f"Failed to load hotel profile: {str(e)}"}

    if not hotel_profile:
        return {"error": "Hotel profile not found"}

    locations_raw = hotel_profile.get("locations", "")
    try:
        locations = json.loads(locations_raw) if isinstance(locations_raw, str) and locations_raw.startswith('[') else [l.strip() for l in locations_raw.split(",") if l.strip()]
    except Exception as e:
        print(f"[pipeline] ⚠ Failed to parse locations: {e}, treating as single location")
        locations = [locations_raw] if locations_raw else []

    if not locations:
        return {"error": "No locations found"}

    loop = asyncio.get_event_loop()

    # =================================================================
    # 1. FETCH GLOBAL SIGNALS IN PARALLEL
    # =================================================================
    if task_id:
        try:
            update_pipeline_task(task_id, progress=10, message='Fetching Global Market Nodes', thoughts='Synchronizing with international flight nodes...\nScanning global news layers concurrently.')
        except Exception:
            pass

    tasks = {
        "calendar": loop.run_in_executor(None, fetch_calendar_signal),
        "highland": loop.run_in_executor(None, fetch_highland_commodity_signal),
        "flights": loop.run_in_executor(None, fetch_flight_signal),
        "trends": loop.run_in_executor(None, lambda: fetch_trends_signal(hotel_profile)),
        "news": loop.run_in_executor(None, fetch_news_signal),
        "reddit": loop.run_in_executor(None, fetch_reddit_signal),
        "youtube": loop.run_in_executor(None, fetch_youtube_signal),
        "exchange": loop.run_in_executor(None, fetch_exchange_signal)
    }

    task_keys = list(tasks.keys())
    task_values = list(tasks.values())
    try:
        global_results_list = await asyncio.gather(*task_values, return_exceptions=True)
    except Exception as e:
        print(f"[pipeline] ⚠ Global signal gather failed: {e}")
        global_results_list = [{"error": str(e)}] * len(task_keys)

    raw = {}
    for key, result in zip(task_keys, global_results_list):
        if isinstance(result, Exception):
            print(f"[pipeline] ⚠ Signal '{key}' raised exception: {result}")
            raw[key] = {"error": str(result)}
        elif isinstance(result, dict):
            raw[key] = result
        else:
            raw[key] = {"error": f"Unexpected result type: {type(result).__name__}"}

    # =================================================================
    # 2. INTERPRET GLOBAL SIGNALS IN PARALLEL
    # =================================================================
    if task_id:
        try:
            update_pipeline_task(task_id, progress=40, message='Neural Interpretation', thoughts='Applying multi-factor analysis to signal batch.\nCalibrating cross-sector sentiment.')
        except Exception:
            pass

    interpret_tasks = {}
    for key in ["calendar", "flights", "trends", "news", "reddit", "youtube", "exchange"]:
        interpret_tasks[key] = loop.run_in_executor(None, lambda k=key: interpret_signal(k, raw.get(k, {})))

    interpret_keys = list(interpret_tasks.keys())
    interpret_values = list(interpret_tasks.values())
    try:
        interpreted_results_list = await asyncio.gather(*interpret_values, return_exceptions=True)
    except Exception as e:
        print(f"[pipeline] ⚠ Interpretation gather failed: {e}")
        interpreted_results_list = [{"sentiment": "neutral", "strength": "weak", "interpretation": f"Interpretation error: {e}"}] * len(interpret_keys)

    interp = {}
    for key, result in zip(interpret_keys, interpreted_results_list):
        if isinstance(result, Exception):
            print(f"[pipeline] ⚠ Interpretation for '{key}' raised exception: {result}")
            interp[key] = {"sentiment": "neutral", "strength": "weak", "interpretation": f"Failed to interpret: {str(result)}"}
        elif isinstance(result, dict):
            interp[key] = result
        else:
            interp[key] = {"sentiment": "neutral", "strength": "weak", "interpretation": f"Unexpected result: {str(result)[:200]}"}

    # =================================================================
    # 2b. FETCH AND INTERPRET CUSTOM SIGNALS
    # =================================================================
    custom_results = []
    try:
        from database import get_custom_signal_deobfuscated, update_custom_signal_status
        from signals.custom import fetch_custom_signals
        from interpreter import interpret_custom_signal as interpret_custom

        custom_configs = get_custom_signal_deobfuscated(hotel_id)

        if custom_configs:
            enabled_configs = [c for c in custom_configs if c.get("enabled", True)]
            enabled_count = len(enabled_configs)

            if task_id:
                try:
                    update_pipeline_task(task_id, progress=45, message=f'Fetching {enabled_count} Custom Source(s)', thoughts=f'Connecting to {enabled_count} custom data source(s)...\nIntegrating external intelligence layers.')
                except Exception:
                    pass

            print(f"[pipeline] 📡 Fetching {enabled_count} custom signal source(s)...")

            # Fetch all custom signals
            try:
                custom_raw_list = await loop.run_in_executor(None, lambda: fetch_custom_signals(custom_configs))
            except Exception as e:
                print(f"[pipeline] ⚠ Custom signal fetch failed entirely: {e}")
                print(traceback.format_exc())
                # Create error placeholders for all configs
                custom_raw_list = [{"error": f"Fetcher crashed: {str(e)}", "name": c.get("name", "unknown"), "description": c.get("description", "")} for c in custom_configs]

            # Process each custom signal individually with its own try/except
            for idx, (custom_config, custom_data) in enumerate(zip(custom_configs, custom_raw_list)):
                signal_name = f"custom_{custom_config['name'].lower().replace(' ', '_').replace('-', '_')}"

                try:
                    # --- Check for fetch errors ---
                    if "error" in custom_data:
                        error_msg = custom_data.get("error", "Unknown error")
                        print(f"[pipeline] ⚠ Custom source '{custom_config['name']}': fetch error — {error_msg}")

                        # Update DB status
                        try:
                            update_custom_signal_status(custom_config["id"], "error", error_msg)
                        except Exception as db_err:
                            print(f"[pipeline] ⚠ Failed to update custom signal status for '{custom_config['name']}': {db_err}")

                        # Still create a neutral interpretation so the signal appears in the dashboard
                        interp_result = {
                            "sentiment": "neutral",
                            "strength": "weak",
                            "interpretation": f"Source '{custom_config['name']}' unavailable — {error_msg}"
                        }
                    else:
                        print(f"[pipeline] ✅ Custom source '{custom_config['name']}' fetched successfully ({custom_data.get('fetch_time_ms', '?')}ms)")

                        # --- Interpret the custom signal ---
                        try:
                            interp_result = await loop.run_in_executor(None, lambda c=custom_config, d=custom_data: interpret_custom(c, d))
                        except Exception as interp_err:
                            print(f"[pipeline] ⚠ Custom source '{custom_config['name']}': interpretation failed — {interp_err}")
                            print(traceback.format_exc())
                            interp_result = {
                                "sentiment": "neutral",
                                "strength": "weak",
                                "interpretation": f"AI could not interpret '{custom_config['name']}' data: {str(interp_err)[:150]}"
                            }

                        # Update DB status
                        try:
                            update_custom_signal_status(custom_config["id"], "ok", None)
                        except Exception as db_err:
                            print(f"[pipeline] ⚠ Failed to update custom signal status for '{custom_config['name']}': {db_err}")

                    custom_results.append({
                        "config": custom_config,
                        "raw": custom_data,
                        "interpreted": interp_result,
                        "signal_name": signal_name
                    })

                    # Save the custom signal to history (global scope for signal history)
                    try:
                        _safe_save_signal(
                            hotel_id, "global", signal_name,
                            interp_result.get("sentiment", "neutral"),
                            interp_result.get("interpretation", ""),
                            _safe_json(custom_data)
                        )
                    except Exception as save_err:
                        print(f"[pipeline] ⚠ Failed to save custom signal '{signal_name}': {save_err}")

                except Exception as inner_err:
                    print(f"[pipeline] ⚠ Unexpected error processing custom source '{custom_config.get('name', '?')}': {inner_err}")
                    print(traceback.format_exc())
                    # Add a fallback entry so the pipeline doesn't skip it silently
                    custom_results.append({
                        "config": custom_config,
                        "raw": {"error": str(inner_err)},
                        "interpreted": {
                            "sentiment": "neutral",
                            "strength": "weak",
                            "interpretation": f"Unexpected error processing '{custom_config.get('name', '?')}': {str(inner_err)[:150]}"
                        },
                        "signal_name": signal_name
                    })

    except ImportError as ie:
        print(f"[pipeline] ⚠ Custom signals module not available: {ie}")
    except Exception as e:
        print(f"[pipeline] ⚠ Custom signals section crashed entirely: {e}")
        print(traceback.format_exc())

    # =================================================================
    # 3. LOCATION-LEVEL PROCESSING
    # =================================================================
    results = {}
    loc_step = 50 / len(locations) if locations else 0
    current_progress = 50

    for i, location in enumerate(locations):
        if task_id:
            current_progress += loc_step
            try:
                update_pipeline_task(task_id, progress=int(current_progress), message=f'Calibrating {location}', thoughts=f'Localizing weather patterns for {location}.\nFinalizing sector-specific yield adjustments.')
            except Exception:
                pass

        # --- Fetch weather for this location ---
        try:
            weather_raw = await loop.run_in_executor(None, lambda: fetch_weather(location))
        except Exception as e:
            print(f"[pipeline] ⚠ Weather fetch failed for {location}: {e}")
            weather_raw = {"error": str(e), "location": location}

        weather_combined = {"resort_weather": weather_raw, "highland_commodity": raw.get("highland", {})}

        try:
            weather_interp = await loop.run_in_executor(None, lambda: interpret_signal("weather", weather_combined))
        except Exception as e:
            print(f"[pipeline] ⚠ Weather interpretation failed for {location}: {e}")
            weather_interp = {"sentiment": "neutral", "strength": "weak", "interpretation": f"Weather analysis failed: {str(e)[:150]}"}

        # --- Build signals list (built-in + custom) ---
        signals_to_save = [
            ("weather", weather_interp, weather_combined),
            ("calendar", interp.get("calendar", {}), raw.get("calendar", {})),
            ("flights", interp.get("flights", {}), raw.get("flights", {})),
            ("trends", interp.get("trends", {}), raw.get("trends", {})),
            ("news", interp.get("news", {}), raw.get("news", {})),
            ("reddit", interp.get("reddit", {}), raw.get("reddit", {})),
            ("youtube", interp.get("youtube", {}), raw.get("youtube", {})),
            ("exchange", interp.get("exchange", {}), raw.get("exchange", {})),
        ]

        # Append custom signals
        for cr in custom_results:
            signals_to_save.append((cr["signal_name"], cr["interpreted"], cr["raw"]))

        # Save each signal individually with error isolation
        for s_type, s_interp, s_raw in signals_to_save:
            _safe_save_signal(
                hotel_id, location, s_type,
                s_interp.get("sentiment", "neutral"),
                s_interp.get("interpretation", ""),
                _safe_json(s_raw)
            )

        # --- Build today_signals dict for cache ---
        today_signals = {
            "weather": {"sentiment": weather_interp.get("sentiment", "neutral"), "strength": weather_interp.get("strength", "weak"), "interpretation": weather_interp.get("interpretation", "Weather data unavailable")},
            "calendar": {**interp.get("calendar", {}), "nearest_holiday": raw.get("calendar", {}).get("nearest_holiday"), "days_away": raw.get("calendar", {}).get("days_away")},
            "flights": {**interp.get("flights", {}), "opensky_trend": raw.get("flights", {}).get("combined_summary", {}).get("opensky_trend")},
            "trends": {**interp.get("trends", {}), "average_change": raw.get("trends", {}).get("average_weekly_change_percent")},
            "news": {**interp.get("news", {}), "articles_analyzed": raw.get("news", {}).get("total_articles", 0)},
            "reddit": {**interp.get("reddit", {}), "posts_analyzed": raw.get("reddit", {}).get("total_posts", 0)},
            "youtube": {**interp.get("youtube", {}), "videos_this_week": raw.get("youtube", {}).get("total_videos_this_week", 0)},
            "exchange": {**interp.get("exchange", {}), "usd_to_etb": raw.get("exchange", {}).get("usd_to_etb")}
        }

        # Append custom signals to today_signals — treated identically to built-in
        for cr in custom_results:
            interp_r = cr["interpreted"]
            today_signals[cr["signal_name"]] = {
                "sentiment": interp_r.get("sentiment", "neutral"),
                "strength": interp_r.get("strength", "weak"),
                "interpretation": interp_r.get("interpretation", "Custom signal unavailable")
            }

        # Save to cache
        try:
            save_cache(hotel_id, location, "today_signals", json.dumps(today_signals))
        except Exception as e:
            print(f"[pipeline] ⚠ Failed to save cache for {location}: {e}")

        # --- Build weekly summary and recommendation ---
        try:
            weekly = build_weekly_summary(hotel_id, location)
        except Exception as e:
            print(f"[pipeline] ⚠ Weekly summary failed for {location}: {e}")
            weekly = {"available": False, "message": f"Failed to build weekly summary: {str(e)}"}

        try:
            recommendation = generate_recommendation(hotel_profile, location, today_signals, weekly)
        except Exception as e:
            print(f"[pipeline] ⚠ Recommendation generation failed for {location}: {e}")
            recommendation = {
                "room_rates": {"standard_rooms": "0%", "suites_and_premium": "0%", "reasoning": f"Recommendation engine error: {str(e)}"},
                "food_beverage": {"restaurant_menu": "0%", "bar_and_events": "0%", "reasoning": "Fallback due to error"},
                "amenities_and_facilities": {"specific_adjustments": [], "reasoning": "Fallback"},
                "overall_confidence": "0%",
                "urgency": "hold",
                "trend_context": f"Error generating trend analysis: {str(e)[:200]}",
                "key_drivers": [],
                "risk_factors": [str(e)[:200]]
            }

        results[location] = {"signals": today_signals, "weekly_summary": weekly, "recommendation": recommendation}

    # =================================================================
    # DONE
    # =================================================================
    if task_id:
        try:
            update_pipeline_task(task_id, progress=100, message='Intelligence Synchronized', thoughts='Task complete. All location nodes updated.')
        except Exception:
            pass

    custom_summary = ""
    if custom_results:
        ok_count = sum(1 for cr in custom_results if "error" not in cr.get("raw", {}))
        err_count = len(custom_results) - ok_count
        custom_summary = f" Custom: {ok_count} ok, {err_count} failed."

    print(f"\n[pipeline] Parallel Pipeline complete for hotel_id={hotel_id}. Processed {len(locations)} location(s).{custom_summary}")
    return {"hotel_id": hotel_id, "locations_processed": locations, "results": results}
