import os
import asyncio
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError
from dotenv import load_dotenv
from database import (
    verify_otp_code, link_telegram_id, get_user_by_telegram_id,
    get_hotel_profile, get_cache, unlink_telegram_id, save_chat_message,
    get_pipeline_task, create_pipeline_task, update_user_language
)
from chat_agent import get_chat_response
from pipeline import run_pipeline

load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def _parse_locations(locations_raw: str) -> list:
    """Safely parse location strings into a list."""
    if not locations_raw:
        return ["Addis Ababa"]
    try:
        if isinstance(locations_raw, str) and locations_raw.startswith('['):
            parsed = json.loads(locations_raw)
            return parsed if isinstance(parsed, list) and parsed else ["Addis Ababa"]
        loc_list = [l.strip() for l in locations_raw.split(",") if l.strip()]
        return loc_list if loc_list else ["Addis Ababa"]
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning(f"Failed to parse locations: {e}")
        return [locations_raw] if locations_raw else ["Addis Ababa"]


def _get_reply_target(update: Update):
    """Return the appropriate reply target (message or callback_query) from an update."""
    if update.message:
        return update.message
    if update.callback_query:
        return update.callback_query
    return None


async def _safe_reply(update: Update, text: str, parse_mode: str = None, reply_markup: InlineKeyboardMarkup = None):
    """Safely send a message reply, handling errors gracefully."""
    reply_target = _get_reply_target(update)
    if not reply_target:
        logger.error("No reply target available (no message or callback_query)")
        return
    try:
        kwargs = {"text": text, "parse_mode": parse_mode}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        await reply_target.reply_text(**kwargs)
    except TelegramError as e:
        logger.error(f"Failed to send message: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending message: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = get_user_by_telegram_id(str(update.effective_user.id))
        if user:
            await show_main_menu(update, context, user)
        else:
            await _safe_reply(update,
                "🚪 *Session Terminated*\n\n"
                "Your mobile node has been disconnected from the Agéiz web dashboard.\n\n"
                "To reconnect:\n"
                "1. Open your Agéiz web dashboard\n"
                "2. Find the *Telegram Neural Link* section in the sidebar\n"
                "3. Click *Generate Code* to get your 4-digit access key\n"
                "4. Reply to this message with that code",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error in /start handler: {e}")
        await _safe_reply(update, "⚠️ An error occurred. Please try again.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text
        if not text:
            logger.warning("Received message with no text")
            return
        text = text.strip()
        if not text:
            return

        user_id = str(update.effective_user.id)
        user = get_user_by_telegram_id(user_id)

        if not user:
            if text.isdigit() and len(text) == 4:
                db_user_id = verify_otp_code(text)
                if db_user_id and db_user_id > 0:
                    linked = link_telegram_id(db_user_id, user_id)
                    if linked:
                        # Verify the link actually took effect
                        user = get_user_by_telegram_id(user_id)
                        if user:
                            await update.message.reply_text("✅ *Neural Link Established*\nAccount synchronized successfully.", parse_mode='Markdown')
                            await show_main_menu(update, context, user)
                        else:
                            logger.error(f"link_telegram_id returned True but get_user_by_telegram_id({user_id}) returned None")
                            await update.message.reply_text(
                                "⚠️ *Link Partially Successful*\n\n"
                                "Your account was linked, but there was a sync delay. Please send /start again to activate your session.",
                                parse_mode='Markdown'
                            )
                    else:
                        logger.error(f"link_telegram_id failed for db_user_id={db_user_id}, telegram_id={user_id}")
                        await update.message.reply_text(
                            "❌ *Link Failed*\n\n"
                            "The account associated with this code no longer exists. Please log in to the web dashboard again and generate a new code.",
                            parse_mode='Markdown'
                        )
                elif db_user_id == -1:
                    await update.message.reply_text(
                        "❌ *Account Not Found*\n\n"
                        "The access code is valid, but your account no longer exists on the dashboard.\n\n"
                        "Please:\n"
                        "1. Log in to your Agéiz dashboard\n"
                        "2. Go to Settings → Telegram Neural Link\n"
                        "3. Generate a new code",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text("❌ *Invalid or Expired Code*\n\n"
                        "Codes expire after 5 minutes. Please generate a new one on your web dashboard and try again.",
                        parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    "🔑 *Authentication Required*\n\n"
                    "Your session has been terminated. To reconnect:\n\n"
                    "1. Go to your Agéiz web dashboard\n"
                    "2. Click *Generate Code* in the Telegram section\n"
                    "3. Reply to this message with the 4-digit code",
                    parse_mode='Markdown')
        else:
            await handle_ai_chat(update, context, user, text)
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        try:
            await update.message.reply_text("⚠️ An error occurred processing your message.")
        except Exception:
            pass

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    try:
        hotel = get_hotel_profile(user["hotel_id"])
        if not hotel:
            await _safe_reply(update, "⚠️ No property profile detected. Please contact support.")
            return

        # Get latest signals count for context
        loc_list = _parse_locations(hotel.get("locations", ""))
        primary_loc = loc_list[0] if loc_list else None
        signals_count = ""
        if primary_loc:
            signals_raw = get_cache(user["hotel_id"], primary_loc, "today_signals")
            if signals_raw:
                try:
                    signals = json.loads(signals_raw)
                    pos = sum(1 for s in signals.values() if s.get("sentiment") == "positive")
                    signals_count = f"\n📊 {len(signals)} signals active | {pos} positive"
                except:
                    pass

        msg = f"🏢 *{hotel['hotel_name']}*\n`Neural Command Center`{signals_count}"

        keyboard = []
        for loc in loc_list:
            keyboard.append([InlineKeyboardButton(f"📍 Node: {loc}", callback_data=f"loc_{loc}")])

        keyboard.append([InlineKeyboardButton("🔄 Synchronize All Nodes", callback_data="refresh_all")])
        keyboard.append([InlineKeyboardButton("💬 Ask Strategy AI", callback_data="ask_ai")])
        keyboard.append([InlineKeyboardButton("🌐 Change Language", callback_data="change_language")])
        keyboard.append([InlineKeyboardButton("🚪 Terminate Session", callback_data="unlink")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.message:
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
            await update.message.reply_text(
                "💡 *Quick Tip:* You can also just type your question directly to this bot and I'll analyze it with live market data!",
                parse_mode='Markdown'
            )
        else:
            logger.error("show_main_menu called with no message or callback_query")
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")
        await _safe_reply(update, "⚠️ Error loading menu. Please try /start again.")

async def show_language_selection(query, context, user):
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_english")],
        [InlineKeyboardButton("🇪🇹 አማርኛ (Amharic)", callback_data="lang_amharic")],
        [InlineKeyboardButton("🇪🇹 Afaan Oromoo", callback_data="lang_oromoo")],
        [InlineKeyboardButton("🇪🇭 ትግርኛ (Tigrinya)", callback_data="lang_tigrinya")],
        [InlineKeyboardButton("🇨🇳 中文 (Chinese)", callback_data="lang_chinese")],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🌐 *Select Language*\n\nChoose your preferred interface language. This will apply to both Telegram and the web dashboard.", reply_markup=reply_markup, parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        user_id = str(update.effective_user.id)
        user = get_user_by_telegram_id(user_id)
        if not user:
            logger.warning("Callback from unauthenticated user")
            await query.edit_message_text("🔑 Session expired. Send /start to reconnect.")
            return

        data = query.data

        if data.startswith("loc_"):
            location = data.replace("loc_", "", 1)
            await show_location_menu(query, context, user, location)

        elif data.startswith("signals_"):
            location = data.replace("signals_", "", 1)
            await show_signals(query, context, user, location)

        elif data.startswith("rec_"):
            location = data.replace("rec_", "", 1)
            await show_recommendation(query, context, user, location)

        elif data == "refresh_all":
            await run_global_refresh(query, context, user)

        elif data == "unlink":
            unlink_telegram_id(user_id)
            await query.edit_message_text("🚪 Mobile session terminated.")

        elif data == "main_menu":
            await show_main_menu(update, context, user)

        elif data == "change_language":
            await show_language_selection(query, context, user)

        elif data.startswith("lang_"):
            lang = data.replace("lang_", "", 1)
            update_user_language(user["id"], lang)
            # Show success message briefly, then show main menu
            await query.edit_message_text(f"✅ Language updated to *{lang.title()}*.", parse_mode='Markdown')
            await asyncio.sleep(1)
            await show_main_menu(update, context, user)

    except Exception as e:
        logger.error(f"Error in handle_callback: {e}")
        try:
            await update.callback_query.edit_message_text("⚠️ An error occurred. Please try /start again.")
        except Exception:
            pass

async def run_global_refresh(query, context, user):
    try:
        task_id = create_pipeline_task(user["hotel_id"])

        # Run pipeline in background
        pipeline_task = asyncio.create_task(run_pipeline(user["hotel_id"], task_id))

        try:
            status_msg = await query.edit_message_text("⚡ *Neural Cycle Initiated*\n`Connecting to market data nodes...`", parse_mode='Markdown')
        except TelegramError as e:
            logger.error(f"Failed to send initial status message: {e}")
            status_msg = None

        last_thought = ""
        max_wait = 600  # 10 minute timeout (pipeline can take 8-9 min)
        waited = 0

        while waited < max_wait:
            await asyncio.sleep(5)
            waited += 5

            try:
                task = get_pipeline_task(task_id)
                if not task:
                    logger.warning(f"Pipeline task {task_id} disappeared")
                    break

                current_thought = task.get("thoughts", "").split("\n")[-1] if task.get("thoughts") else task.get("message", "Processing")

                if current_thought != last_thought and status_msg:
                    try:
                        await status_msg.edit_text(
                            f"⚡ *Neural Cycle: {task['progress']}%*\n`{current_thought}`",
                            parse_mode='Markdown'
                        )
                        last_thought = current_thought
                    except TelegramError as e:
                        logger.warning(f"Failed to update status message: {e}")

                if task["status"] == "completed":
                    # Fetch fresh data to display
                    hotel = get_hotel_profile(user["hotel_id"])
                    if not hotel:
                        if status_msg:
                            await status_msg.edit_text("⚠️ Pipeline completed but hotel profile not found.")
                        return

                    loc_list = _parse_locations(hotel.get("locations", ""))

                    # Build a detailed results dashboard
                    dashboard_text = f"✅ *Intelligence Synchronized*\n🏢 *{hotel['hotel_name']}*\n\n"

                    for loc in loc_list:
                        signals_raw = get_cache(user["hotel_id"], loc, "today_signals")
                        rec_raw = get_cache(user["hotel_id"], loc, "latest_recommendation")

                        dashboard_text += f"📍 *{loc}*\n"

                        if signals_raw:
                            try:
                                signals = json.loads(signals_raw)
                                pos_count = sum(1 for s in signals.values() if s.get("sentiment") == "positive")
                                neg_count = sum(1 for s in signals.values() if s.get("sentiment") == "negative")
                                neu_count = len(signals) - pos_count - neg_count
                                total_count = len(signals)
                                dashboard_text += f"   Signals: 🟢{pos_count} 🔴{neg_count} 🟡{neu_count} / {total_count}\n"

                                # Highlight key signals
                                for sig_name in ["weather", "calendar", "flights", "exchange"]:
                                    if sig_name in signals:
                                        sig = signals[sig_name]
                                        emoji = "🟢" if sig.get("sentiment") == "positive" else "🔴" if sig.get("sentiment") == "negative" else "🟡"
                                        interp = sig.get("interpretation", "")[:80]
                                        if interp:
                                            dashboard_text += f"   {emoji} *{sig_name.capitalize()}*: {interp}\n"
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse signals for {loc}: {e}")
                                dashboard_text += f"   ⚠️ Signals data corrupted\n"

                        if rec_raw:
                            try:
                                rec = json.loads(rec_raw)
                                urgency = rec.get("urgency", "N/A")
                                urgency_emoji = "🚨" if urgency == "act now" else "⚠️" if urgency == "act soon" else "✅" if urgency == "hold" else "📉"
                                confidence = rec.get("overall_confidence", "N/A")

                                dashboard_text += f"   {urgency_emoji} *Strategy*: {urgency.upper()} | {confidence}\n"

                                # Room rates
                                rooms = rec.get("room_rates", {})
                                std = rooms.get("standard_rooms", "N/A")
                                suite = rooms.get("suites_and_premium", "N/A")
                                dashboard_text += f"   🏨 Standard: {std} | Suites: {suite}\n"

                                # F&B
                                fb = rec.get("food_beverage", {})
                                rest = fb.get("restaurant_menu", "N/A")
                                bar = fb.get("bar_and_events", "N/A")
                                dashboard_text += f"   🍽️ Restaurant: {rest} | Events/Bar: {bar}\n"

                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse recommendation for {loc}: {e}")
                                dashboard_text += f"   ⚠️ Recommendation data corrupted\n"

                        dashboard_text += "\n"

                    # Build inline keyboard with location buttons
                    keyboard = []
                    for loc in loc_list:
                        keyboard.append([InlineKeyboardButton(f"📊 Full Signals: {loc}", callback_data=f"signals_{loc}")])
                        keyboard.append([InlineKeyboardButton(f"💰 Full Strategy: {loc}", callback_data=f"rec_{loc}")])
                    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    if status_msg:
                        try:
                            # Truncate if too long for Telegram's 4096 char limit
                            if len(dashboard_text) > 3500:
                                dashboard_text = dashboard_text[:3490] + "...\n\n(Full details available via buttons below)"
                            await status_msg.edit_text(dashboard_text, reply_markup=reply_markup, parse_mode='Markdown')
                        except TelegramError as e:
                            logger.warning(f"Failed to send dashboard: {e}")
                            # Fallback: send as plain text
                            try:
                                await status_msg.edit_text(dashboard_text[:4000], parse_mode=None)
                            except:
                                pass
                    return

                elif task["status"] == "failed":
                    error_msg = task.get('error', 'Unknown error')
                    if status_msg:
                        await status_msg.edit_text(
                            f"❌ *Cycle Interrupted*\n"
                            f"Error: {error_msg}\n\n"
                            "Try again or contact support.",
                            parse_mode='Markdown'
                        )
                    return

            except Exception as e:
                logger.error(f"Error polling pipeline task: {e}")
                # Continue polling in case of transient errors
                continue

        # Timeout
        if status_msg:
            await status_msg.edit_text("⏱️ *Cycle Timeout*\nThe pipeline is still running in the background. Check back in a few minutes.", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in run_global_refresh: {e}")
        try:
            await query.edit_message_text("⚠️ An error occurred during synchronization.")
        except Exception:
            pass

async def show_location_menu(query, context, user, location):
    try:
        keyboard = [
            [InlineKeyboardButton("📊 Live Signals", callback_data=f"signals_{location}")],
            [InlineKeyboardButton("💰 Yield Strategy", callback_data=f"rec_{location}")],
            [InlineKeyboardButton("⬅️ Return to Nodes", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"📍 Node: *{location}*", reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in show_location_menu: {e}")
        await query.edit_message_text("⚠️ Error loading location menu.")

async def show_signals(query, context, user, location):
    try:
        signals_raw = get_cache(user["hotel_id"], location, "today_signals")
        if not signals_raw:
            await query.edit_message_text(f"No signals found for *{location}*.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]),
                                         parse_mode='Markdown')
            return

        signals = json.loads(signals_raw)
        text = f"📊 *Live Signals: {location}*\n\n"
        for s_name, s_data in signals.items():
            sentiment = s_data.get("sentiment", "unknown")
            interpretation = s_data.get("interpretation", "No interpretation available")
            emoji = "🟢" if sentiment == "positive" else "🔴" if sentiment == "negative" else "🟡"
            text += f"{emoji} *{s_name.upper()}*\n{interpretation[:120]}...\n\n"

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"loc_{location}")]]), parse_mode='Markdown')
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in signals cache: {e}")
        await query.edit_message_text("⚠️ Signals data is corrupted.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]))
    except Exception as e:
        logger.error(f"Error in show_signals: {e}")
        await query.edit_message_text("⚠️ Error loading signals.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]))

async def show_recommendation(query, context, user, location):
    try:
        rec_raw = get_cache(user["hotel_id"], location, "latest_recommendation")
        if not rec_raw:
            await query.edit_message_text(f"Strategy pending for *{location}*.",
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]),
                                         parse_mode='Markdown')
            return

        rec = json.loads(rec_raw)
        urgency = rec.get("urgency", "unknown")
        urgency_emoji = "🚨" if urgency == "act now" else "⚠️" if urgency == "act soon" else "✅"
        confidence = rec.get("overall_confidence", "N/A")
        trend_context = rec.get("trend_context", "No trend analysis available")

        room_rates = rec.get("room_rates", {})
        standard = room_rates.get("standard_rooms", "N/A")
        suites = room_rates.get("suites_and_premium", "N/A")

        text = f"💰 *Strategy: {location}*\n"
        text += f"Status: {urgency_emoji} *{urgency.upper()}*\n"
        text += f"Confidence: {confidence}\n\n"
        text += f"*Rooms:*\nStandard: {standard}\nSuites: {suites}\n\n"
        text += f"*Neural Summary:*\n_{trend_context}_"

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"loc_{location}")]]), parse_mode='Markdown')
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in recommendation cache: {e}")
        await query.edit_message_text("⚠️ Strategy data is corrupted.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]))
    except Exception as e:
        logger.error(f"Error in show_recommendation: {e}")
        await query.edit_message_text("⚠️ Error loading strategy.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]))

async def handle_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user, text):
    try:
        reply_target = update.message
        if not reply_target:
            # Handle callback_query messages too
            if update.callback_query:
                reply_target = update.callback_query
            else:
                logger.error("handle_ai_chat called without a message or callback_query")
                return

        await reply_target.reply_chat_action("typing")

        hotel = get_hotel_profile(user["hotel_id"])
        if not hotel:
            await reply_target.reply_text("⚠️ Hotel profile not found.")
            return

        loc_list = _parse_locations(hotel.get("locations", ""))
        primary_loc = loc_list[0]

        # Get signals context to include in the response
        signals_raw = get_cache(user["hotel_id"], primary_loc, "today_signals")
        signals = json.loads(signals_raw) if signals_raw else {}
        signals_summary = ""
        if signals:
            pos = sum(1 for s in signals.values() if s.get("sentiment") == "positive")
            neg = sum(1 for s in signals.values() if s.get("sentiment") == "negative")
            total = len(signals)
            signals_summary = f"\nCurrent market signals for {primary_loc}: {pos} positive, {neg} negative out of {total} total signals."

        # Build a focused system prompt for Telegram
        system_prompt = f"""You are the Agéiz Strategy AI, an expert revenue management consultant advising the management team and staff of Ethiopian hotels and resorts.
You speak directly to hotel managers, revenue officers, and operational staff — NOT to guests or customers.

HOTEL YOU ARE ADVISING:
- Name: {hotel.get('hotel_name', 'Unknown')}
- Location: {primary_loc}
- Positioning: {hotel.get('brand_positioning', 'Standard')}
- Target Guests: {hotel.get('target_guest_segments', 'Local and Diaspora')}
- Market Tier: {hotel.get('price_range', 'Not specified')}
{signals_summary}

RULES:
- Address the user as a hotel professional, never as a guest.
- Be concise — max 3 short paragraphs or bullet points.
- Give specific pricing recommendations with percentages when possible.
- Reference Ethiopian context (holidays, fasting seasons, diaspora travel).
- If you don't know current data, say so honestly.
- NEVER use Markdown formatting errors — use *bold* and _italic_ only."""

        # Send typing indicator while processing
        typing_msg = await reply_target.reply_text("🤖 *Processing your query...*", parse_mode='Markdown')

        try:
            from ai_client import groq_client
            from database import get_chat_history, save_chat_message

            # Get chat history
            history = get_chat_history(user["hotel_id"], location=None, limit=5)

            messages = [{"role": "system", "content": system_prompt}]
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({"role": "user", "content": text})

            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.7,
                max_tokens=800
            )
            ai_response = completion.choices[0].message.content

            # Save history
            save_chat_message(user["hotel_id"], user["id"], primary_loc, "user", text)
            save_chat_message(user["hotel_id"], user["id"], primary_loc, "assistant", ai_response)

            # Translate if needed
            user_lang = user.get("language", "english")
            if user_lang and user_lang.lower() != "english":
                from translator import translate_text
                translated = translate_text(ai_response, user_lang)
                if translated != ai_response:
                    ai_response = translated

            # Delete typing message and send response
            try:
                await typing_msg.delete_text()
            except:
                pass

            await reply_target.reply_text(f"🤖 *Agéiz Intelligence:*\n\n{ai_response}", parse_mode='Markdown')

        except Exception as groq_err:
            logger.error(f"[telegram] Groq failed: {groq_err}")
            try:
                await typing_msg.edit_text("⚠️ My neural network is experiencing a brief outage. Please try again in a moment.")
            except:
                await reply_target.reply_text("⚠️ Error processing your request. Please try again.")

    except Exception as e:
        logger.error(f"Error in handle_ai_chat: {e}")

bot_app = None

async def setup_bot():
    global bot_app
    if not TOKEN:
        logger.info("[telegram] TELEGRAM_BOT_TOKEN not found in .env — bot disabled.")
        return

    try:
        # Increased timeout for slower networks
        application = ApplicationBuilder().token(TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).build()
    except Exception as e:
        logger.error(f"[telegram] Failed to build Telegram app: {e}")
        return

    bot_app = application
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Add error handler to log all unhandled exceptions
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        logger.error(f"[telegram] Unhandled error: {error}")
        if update and hasattr(update, 'effective_user'):
            logger.error(f"[telegram] Error for user: {update.effective_user.id}")

    application.add_error_handler(error_handler)

    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("[telegram] Agéiz Telegram Bot is active and polling for updates.")
    except Exception as e:
        logger.error(f"[telegram] Failed to start Telegram bot: {e}")
        logger.info("[telegram] Bot is disabled. The web app will continue to work normally.")
        # Keep bot_app so it's not GC'd if that's an issue, but mark as disabled
        return

    return application

if __name__ == '__main__':
    # Improved standalone runner
    app = asyncio.run(setup_bot())
    if app:
        try:
            # Keep the script running while polling is active
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

