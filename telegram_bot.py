import os
import asyncio
import json
import logging
import random
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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


def _parse_locations(locations_raw: str) -> list:
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
    if update.message:
        return update.message
    if update.callback_query:
        return update.callback_query
    return None


async def _safe_reply(update: Update, text: str, parse_mode: str = None, reply_markup: InlineKeyboardMarkup = None):
    reply_target = _get_reply_target(update)
    if not reply_target:
        logger.error("No reply target available")
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


def _truncate(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit - 20] + "\n\n... (truncated)"


# ============================
# AUTH / ENTRY
# ============================

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
                        user = get_user_by_telegram_id(user_id)
                        if user:
                            await update.message.reply_text("✅ *Neural Link Established*\nAccount synchronized successfully.", parse_mode='Markdown')
                            await show_main_menu(update, context, user)
                        else:
                            await update.message.reply_text("⚠️ Link successful but sync delayed. Send /start again.", parse_mode='Markdown')
                    else:
                        await update.message.reply_text("❌ Link failed. Account no longer exists. Please register again on the web dashboard.", parse_mode='Markdown')
                elif db_user_id == -1:
                    await update.message.reply_text("❌ Code valid but account deleted. Please re-register on the dashboard.", parse_mode='Markdown')
                else:
                    await update.message.reply_text("❌ *Invalid or Expired Code*\nCodes expire after 5 minutes. Generate a new one.", parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    "🔑 *Authentication Required*\n\n"
                    "Send the 4-digit code from your web dashboard to connect.",
                    parse_mode='Markdown')
        else:
            # Check if user is waiting for input (employee creation, report, etc.)
            if user_id in _pending_actions:
                action = _pending_actions[user_id]
                del _pending_actions[user_id]
                if action["type"] == "create_employee":
                    await _process_create_employee(update, context, user, text, action)
                    return
                elif action["type"] == "create_embed":
                    await _process_create_embed(update, context, user, text, action)
                    return
                elif action["type"] == "staff_report":
                    await _process_staff_report(update, context, user, text, action)
                    return

            await handle_ai_chat(update, context, user, text)
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        try:
            await update.message.reply_text("⚠️ An error occurred processing your message.")
        except Exception:
            pass


# ============================
# MAIN MENU
# ============================

_pending_actions = {}


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user):
    try:
        hotel = get_hotel_profile(user["hotel_id"])
        if not hotel:
            await _safe_reply(update, "⚠️ No property profile detected. Please contact support.")
            return

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

        role = user.get("role", "manager")
        role_icon = "📊" if role == "manager" else "📝"

        msg = f"{role_icon} *{hotel['hotel_name']}*\n`Neural Command Center`{signals_count}"

        keyboard = []

        # Location nodes
        for loc in loc_list:
            keyboard.append([InlineKeyboardButton(f"📍 Node: {loc}", callback_data=f"loc_{loc}")])

        # Core actions
        keyboard.append([InlineKeyboardButton("🔄 Synchronize All Nodes", callback_data="refresh_all")])
        keyboard.append([InlineKeyboardButton("💬 Ask Strategy AI", callback_data="ask_ai")])

        if role == "manager":
            # Manager-only features
            keyboard.append([InlineKeyboardButton("👥 Staff Intelligence", callback_data="staff_intel")])
            keyboard.append([InlineKeyboardButton("👤 Employee Management", callback_data="emp_mgmt")])
            keyboard.append([InlineKeyboardButton("🏆 Staff Leaderboard", callback_data="leaderboard")])
            keyboard.append([InlineKeyboardButton("🌐 Embed Forms", callback_data="embed_mgmt")])
            keyboard.append([InlineKeyboardButton("📊 Guest Feedback", callback_data="embed_submissions")])
            keyboard.append([InlineKeyboardButton("⚙️ Custom Signals", callback_data="custom_signals")])

        # For staff
        if role == "staff":
            keyboard.append([InlineKeyboardButton("📝 Submit Report", callback_data="staff_submit")])
            keyboard.append([InlineKeyboardButton("🏆 My Rank & Points", callback_data="my_rank")])

        keyboard.append([InlineKeyboardButton("🌐 Change Language", callback_data="change_language")])
        keyboard.append([InlineKeyboardButton("🚪 Terminate Session", callback_data="unlink")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.message:
            await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            logger.error("show_main_menu called with no message or callback_query")
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")
        await _safe_reply(update, "⚠️ Error loading menu. Send /start to retry.")


# ============================
# CALLBACK ROUTER
# ============================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        user_id = str(update.effective_user.id)
        user = get_user_by_telegram_id(user_id)
        if not user:
            await query.edit_message_text("🔑 Session expired. Send /start to reconnect.")
            return

        data = query.data

        # Route to appropriate handler
        if data.startswith("loc_"):
            await show_location_menu(query, context, user, data[4:])
        elif data.startswith("signals_"):
            await show_signals(query, context, user, data[8:])
        elif data.startswith("rec_"):
            await show_recommendation(query, context, user, data[4:])
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
            await _handle_lang_change(query, context, user, data[5:])
        elif data == "ask_ai":
            await query.edit_message_text("💬 *Strategy AI*\nJust type your question directly to this bot and I'll analyze it with live market data!")
        elif data == "staff_intel":
            await show_staff_intelligence(query, context, user)
        elif data == "emp_mgmt":
            await show_employee_mgmt(query, context, user)
        elif data == "emp_add":
            await _handle_emp_add(query, context, user)
        elif data.startswith("emp_delete_"):
            await _delete_employee(query, context, user, int(data[11:]))
        elif data == "leaderboard":
            await show_leaderboard(query, context, user)
        elif data == "embed_mgmt":
            await show_embed_mgmt(query, context, user)
        elif data == "embed_add":
            await _handle_embed_add(query, context, user)
        elif data.startswith("embed_delete_"):
            await _delete_embed(query, context, user, int(data[13:]))
        elif data == "embed_submissions":
            await show_embed_submissions(query, context, user)
        elif data == "custom_signals":
            await show_custom_signals(query, context, user)
        elif data.startswith("custom_toggle_"):
            await _toggle_custom_signal(query, context, user, int(data[14:]))
        elif data == "staff_submit":
            await _prompt_staff_report(query, context, user)
        elif data == "my_rank":
            await show_my_rank(query, context, user)
        else:
            await query.edit_message_text("❓ Unknown action. Send /start for menu.")

    except Exception as e:
        logger.error(f"Error in handle_callback: {e}")
        try:
            await update.callback_query.edit_message_text("⚠️ Error. Send /start to retry.")
        except Exception:
            pass


# ============================
# LOCATION / SIGNALS / RECOMMENDATIONS
# ============================

async def show_location_menu(query, context, user, location):
    keyboard = [
        [InlineKeyboardButton("📊 Live Signals", callback_data=f"signals_{location}")],
        [InlineKeyboardButton("💰 Yield Strategy", callback_data=f"rec_{location}")],
        [InlineKeyboardButton("⬅️ Return to Nodes", callback_data="main_menu")]
    ]
    await query.edit_message_text(f"📍 Node: *{location}*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def show_signals(query, context, user, location):
    signals_raw = get_cache(user["hotel_id"], location, "today_signals")
    if not signals_raw:
        await query.edit_message_text(f"No signals for *{location}*. Run a refresh first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]), parse_mode='Markdown')
        return

    signals = json.loads(signals_raw)
    text = f"📊 *Live Signals: {location}*\n\n"
    for s_name, s_data in signals.items():
        sentiment = s_data.get("sentiment", "unknown")
        interpretation = s_data.get("interpretation", "N/A")
        emoji = "🟢" if sentiment == "positive" else "🔴" if sentiment == "negative" else "🟡"
        text += f"{emoji} *{s_name.upper()}*\n{interpretation[:150]}\n\n"

    await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"loc_{location}")]]), parse_mode='Markdown')


async def show_recommendation(query, context, user, location):
    rec_raw = get_cache(user["hotel_id"], location, "latest_recommendation")
    if not rec_raw:
        await query.edit_message_text(f"Strategy pending for *{location}*.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"loc_{location}")]]), parse_mode='Markdown')
        return

    rec = json.loads(rec_raw)
    urgency = rec.get("urgency", "unknown")
    urgency_emoji = "🚨" if urgency == "act now" else "⚠️" if urgency == "act soon" else "✅"
    confidence = rec.get("overall_confidence", "N/A")
    trend_context = rec.get("trend_context", "No trend analysis")

    room_rates = rec.get("room_rates", {})
    standard = room_rates.get("standard_rooms", "N/A")
    suites = room_rates.get("suites_and_premium", "N/A")

    text = f"💰 *Strategy: {location}*\n"
    text += f"Status: {urgency_emoji} *{urgency.upper()}*\n"
    text += f"Confidence: {confidence}\n\n"
    text += f"*Rooms:*\nStandard: {standard}\nSuites: {suites}\n\n"
    text += f"*Neural Summary:*\n_{trend_context}"

    await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"loc_{location}")]]), parse_mode='Markdown')


# ============================
# REFRESH / PIPELINE
# ============================

async def run_global_refresh(query, context, user):
    try:
        task_id = create_pipeline_task(user["hotel_id"])
        pipeline_task = asyncio.create_task(run_pipeline(user["hotel_id"], task_id))

        try:
            status_msg = await query.edit_message_text("⚡ *Neural Cycle Initiated*\n`Connecting to market data nodes...`", parse_mode='Markdown')
        except TelegramError:
            status_msg = None

        last_progress = -1
        max_wait = 600
        waited = 0

        while waited < max_wait:
            await asyncio.sleep(3)
            waited += 3

            try:
                task = get_pipeline_task(task_id)
                if not task:
                    break

                progress = task.get('progress', 0)
                message = task.get('message', 'Processing...')

                # Always update if progress changed
                if progress != last_progress and status_msg:
                    try:
                        await status_msg.edit_text(
                            f"⚡ *Neural Cycle: {progress}%*\n`{message}`",
                            parse_mode='Markdown'
                        )
                        last_progress = progress
                    except TelegramError:
                        pass

                if task["status"] == "completed":
                    hotel = get_hotel_profile(user["hotel_id"])
                    if not hotel:
                        if status_msg:
                            await status_msg.edit_text("✅ Pipeline complete. Refresh the web dashboard to see results.")
                        return

                    loc_list = _parse_locations(hotel.get("locations", ""))
                    dashboard_text = f"✅ *Intelligence Synchronized*\n🏢 *{hotel['hotel_name']}*\n\n"

                    for loc in loc_list:
                        signals_raw = get_cache(user["hotel_id"], loc, "today_signals")
                        dashboard_text += f"📍 *{loc}*\n"

                        if signals_raw:
                            try:
                                signals = json.loads(signals_raw)
                                pos_count = sum(1 for s in signals.values() if s.get("sentiment") == "positive")
                                neg_count = sum(1 for s in signals.values() if s.get("sentiment") == "negative")
                                dashboard_text += f"   Signals: 🟢{pos_count} 🔴{neg_count} / {len(signals)}\n"
                                for sig_name in ["weather", "calendar", "flights", "exchange", "staff_intelligence"]:
                                    if sig_name in signals:
                                        sig = signals[sig_name]
                                        emoji = "🟢" if sig.get("sentiment") == "positive" else "🔴" if sig.get("sentiment") == "negative" else "🟡"
                                        interp = sig.get("interpretation", "")[:60]
                                        if interp:
                                            dashboard_text += f"   {emoji} {sig_name.capitalize()}: {interp}\n"
                            except:
                                dashboard_text += f"   ⚠️ Signals corrupted\n"

                        rec_raw = get_cache(user["hotel_id"], loc, "latest_recommendation")
                        if rec_raw:
                            try:
                                rec = json.loads(rec_raw)
                                urgency = rec.get("urgency", "N/A").upper()
                                confidence = rec.get("overall_confidence", "N/A")
                                rooms = rec.get("room_rates", {})
                                dashboard_text += f"   💰 {urgency} · {confidence}\n"
                                std = rooms.get('standard_rooms', '—')
                                suite = rooms.get('suites_and_premium', '—')
                                if std != '—' or suite != '—':
                                    dashboard_text += f"   🏨 Std: {std} | Suite: {suite}\n"
                            except:
                                pass

                        dashboard_text += "\n"

                    dashboard_text += "\n🔄 *The web dashboard is also updated.*"

                    keyboard = []
                    for loc in loc_list:
                        keyboard.append([InlineKeyboardButton(f"📊 {loc} Signals", callback_data=f"signals_{loc}")])
                        keyboard.append([InlineKeyboardButton(f"💰 {loc} Strategy", callback_data=f"rec_{loc}")])
                    keyboard.append([InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    if status_msg:
                        try:
                            safe_text = _truncate(dashboard_text, 3800)
                            await status_msg.edit_text(safe_text, reply_markup=reply_markup, parse_mode='Markdown')
                        except Exception as edit_err:
                            logger.warning(f"Dashboard edit failed: {edit_err}")
                            try:
                                await status_msg.edit_text("✅ *Pipeline Complete!*\n\nOpen the web dashboard or check signals/strategy buttons below.", reply_markup=reply_markup, parse_mode='Markdown')
                            except:
                                pass
                    return

                elif task["status"] == "failed":
                    if status_msg:
                        await status_msg.edit_text(f"❌ *Cycle Failed*\nError: {task.get('error', 'Unknown')[:100]}\n\nTry again.", parse_mode='Markdown')
                    return

            except Exception as e:
                logger.error(f"Error polling pipeline task: {e}")
                continue

        if status_msg:
            await status_msg.edit_text("⏱️ *Cycle Timeout*\nPipeline still running in background. Check the web dashboard.", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in run_global_refresh: {e}")
        try:
            await query.edit_message_text("⚠️ Error during synchronization.")
        except Exception:
            pass


# ============================
# LANGUAGE
# ============================

async def show_language_selection(query, context, user):
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_english")],
        [InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_amharic")],
        [InlineKeyboardButton("🇪🇹 Afaan Oromoo", callback_data="lang_oromoo")],
        [InlineKeyboardButton("🇪🇭 ትግርኛ", callback_data="lang_tigrinya")],
        [InlineKeyboardButton("🇨🇳 中文", callback_data="lang_chinese")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
    ]
    await query.edit_message_text("🌐 *Select Language*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def _handle_lang_change(query, context, user, lang):
    update_user_language(user["id"], lang)
    await query.edit_message_text(f"✅ Language updated to *{lang.title()}*.", parse_mode='Markdown')
    await asyncio.sleep(1)
    user = get_user_by_telegram_id(str(query.from_user.id)) or user
    await show_main_menu(query, context, user)


# ============================
# STAFF INTELLIGENCE (Manager)
# ============================

async def show_staff_intelligence(query, context, user):
    try:
        hotel = get_hotel_profile(user["hotel_id"])
        if not hotel:
            await query.edit_message_text("⚠️ No hotel profile.")
            return

        # Import staff report functions
        from database import get_staff_report_summary, get_staff_reports
        summary = get_staff_report_summary(user["hotel_id"])
        reports = get_staff_reports(user["hotel_id"], limit=10)

        text = f"👥 *Staff Intelligence — {hotel['hotel_name']}*\n\n"

        if summary.get("total_reports", 0) > 0:
            sb = summary.get("sentiment_breakdown", {})
            text += f"📊 Total Reports: {summary['total_reports']}\n"
            text += f"🟢 Positive: {sb.get('positive', 0)}\n"
            text += f"🔴 Negative: {sb.get('negative', 0)}\n"
            text += f"🟡 Neutral: {sb.get('neutral', 0)}\n\n"

            for rtype, rdata in summary.get("latest_by_type", {}).items():
                text += f"📝 *{rtype.upper()}* (latest)\n"
                if rdata.get("summary"):
                    text += f"  {rdata['summary'][:120]}\n"
                if rdata.get("customer_satisfaction"):
                    text += f"  Satisfaction: {rdata['customer_satisfaction']}/5\n"
                text += "\n"
        else:
            text += "No staff reports submitted yet.\n\n"

        if reports:
            text += "*Recent Reports:*\n"
            for r in reports[:5]:
                emoji = "🟢" if r.get("sentiment") == "positive" else "🔴" if r.get("sentiment") == "negative" else "🟡"
                text += f"{emoji} {r['report_type'].upper()} by {r.get('user_email', 'Staff').split('@')[0]}\n"
                if r.get("summary"):
                    text += f"  {r['summary'][:100]}\n"
                text += "\n"

        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in staff intelligence: {e}")
        await query.edit_message_text("⚠️ Error loading staff intelligence.")


# ============================
# EMPLOYEE MANAGEMENT (Manager)
# ============================

async def show_employee_mgmt(query, context, user):
    try:
        import sqlite3
        conn = sqlite3.connect("ageiz.db")
        cursor = conn.execute("""
            SELECT id, email, role, telegram_id, created_at
            FROM users WHERE hotel_id = ?
            ORDER BY created_at DESC
        """, (user["hotel_id"],))
        employees = cursor.fetchall()
        conn.close()

        text = f"👤 *Employee Management*\n\n"
        keyboard = []
        if employees:
            for emp in employees:
                role_icon = "📊" if emp[2] == "manager" else "📝"
                linked = "📱 Linked" if emp[3] else "📴 Not linked"
                text += f"{role_icon} *{emp[1]}* — {linked}\n"
                keyboard.append([InlineKeyboardButton(
                    f"❌ Remove {emp[1].split('@')[0]}",
                    callback_data=f"emp_delete_{emp[0]}"
                )])
            text += f"\nTotal: {len(employees)} employees\n"
        else:
            text += "No employees linked to this hotel.\n"

        text += "\nTap ➕ to add a new employee."

        keyboard.insert(0, [InlineKeyboardButton("➕ Add Employee", callback_data="emp_add")])
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in employee mgmt: {e}")
        await query.edit_message_text("⚠️ Error loading employee management.")


async def _handle_emp_add(query, context, user):
    _pending_actions[str(query.from_user.id)] = {"type": "create_employee"}
    await query.edit_message_text("📧 *Add Employee*\n\nSend the employee's email address:", parse_mode='Markdown')


async def _process_create_employee(update, context, user, text, action):
    email = text.strip().lower()
    if "@" not in email:
        await update.message.reply_text("❌ Invalid email. Send a valid email address.")
        return

    # Generate password
    password = f"staff{random.randint(1000, 9999)}"

    import bcrypt
    from database import get_user_by_email, create_user, update_user_hotel

    existing = get_user_by_email(email)
    if existing:
        await update.message.reply_text(f"❌ {email} is already registered.")
        return

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = create_user(email, password_hash, "staff")
    update_user_hotel(user_id, user["hotel_id"])

    hotel = get_hotel_profile(user["hotel_id"])
    hotel_name = hotel["hotel_name"] if hotel else "your hotel"

    await update.message.reply_text(
        f"✅ *Employee Created*\n\n"
        f"📧 Email: `{email}`\n"
        f"🔑 Password: `{password}`\n"
        f"🏨 Hotel: {hotel_name}\n\n"
        f"Send this to your employee. They can login at the web dashboard.",
        parse_mode='Markdown'
    )
    await show_main_menu(update, context, user)


# ============================
# LEADERBOARD (Manager + Staff)
# ============================

async def show_leaderboard(query, context, user):
    try:
        from database import get_leaderboard
        leaderboard = get_leaderboard(user["hotel_id"], limit=10)

        if not leaderboard:
            await query.edit_message_text("🏆 *Leaderboard*\n\nNo contributions yet.")
            return

        medals = ['🥇', '🥈', '🥉']
        text = "🏆 *Staff Leaderboard*\n\n"
        for emp in leaderboard:
            medal = medals[emp['rank'] - 1] if emp['rank'] <= 3 else f"#{emp['rank']}"
            role_icon = "📊" if emp['role'] == "manager" else "📝"
            text += f"{medal} {role_icon} {emp['email'].split('@')[0]} — *{emp['total_points']} pts* ({emp['report_count']} reports)\n"

        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in leaderboard: {e}")
        await query.edit_message_text("⚠️ Error loading leaderboard.")


async def show_my_rank(query, context, user):
    try:
        from database import get_user_rank, get_leaderboard
        my_rank = get_user_rank(user["hotel_id"], user["id"])
        leaderboard = get_leaderboard(user["hotel_id"], limit=3)

        medals = ['🥇', '🥈', '🥉']
        text = f"🏆 *Your Stats*\n\n"
        text += f"Rank: #{my_rank['rank']}\n"
        text += f"Points: *{my_rank['total_points']}*\n"
        text += f"Reports Filed: {my_rank['report_count']}\n\n"

        if leaderboard:
            text += "*Top 3:*\n"
            for emp in leaderboard[:3]:
                medal = medals[emp['rank'] - 1]
                text += f"{medal} {emp['email'].split('@')[0]} — *{emp['total_points']} pts*\n"

        text += "\n*Points System:*\n"
        text += "📅 Daily report: 10 pts\n"
        text += "📊 Weekly report: 25 pts\n"
        text += "📈 Monthly report: 50 pts\n"
        text += "🤖 AI-structured: +10 bonus\n"

        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in my rank: {e}")
        await query.edit_message_text("⚠️ Error loading rank.")


# ============================
# EMBED FORMS MANAGEMENT (Manager)
# ============================

async def show_embed_mgmt(query, context, user):
    try:
        from database import get_embed_tokens
        tokens = get_embed_tokens(user["hotel_id"])

        text = "🌐 *Embed Forms Management*\n\n"
        keyboard = []
        if tokens:
            for t in tokens:
                form_url = f"https://ageiz.onrender.com/embed/{t['token']}"
                text += f"📝 *{t['label']}*\n  Link: `{form_url}`\n  Created: {t.get('created_at', '')[:10]}\n\n"
                keyboard.append([InlineKeyboardButton(
                    f"🗑️ Delete {t['label'][:20]}",
                    callback_data=f"embed_delete_{t['id']}"
                )])
        else:
            text += "No embed forms created yet.\n\n"

        text += "Tap ➕ to create a new feedback form."

        keyboard.insert(0, [InlineKeyboardButton("➕ Create New Form", callback_data="embed_add")])
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])

        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in embed mgmt: {e}")
        await query.edit_message_text("⚠️ Error loading embed forms.")


async def _handle_embed_add(query, context, user):
    _pending_actions[str(query.from_user.id)] = {"type": "create_embed"}
    await query.edit_message_text("📝 *Create Embed Form*\n\nSend a label name for the feedback form:", parse_mode='Markdown')


async def _process_create_embed(update, context, user, text, action):
    label = text.strip()
    if not label:
        await update.message.reply_text("❌ Label cannot be empty.")
        return

    import secrets
    from database import create_embed_token

    token = create_embed_token(user["hotel_id"], label)
    form_url = f"https://ageiz.onrender.com/embed/{token}"

    await update.message.reply_text(
        f"✅ *Embed Form Created*\n\n"
        f"📝 Label: {label}\n"
        f"🔗 Link: `{form_url}`\n\n"
        f"Share this link with guests or embed as an iframe on your website.",
        parse_mode='Markdown'
    )
    await show_main_menu(update, context, user)


async def _delete_embed(query, context, user, token_id):
    from database import delete_embed_token
    ok = delete_embed_token(token_id, user["hotel_id"])
    if ok:
        await query.edit_message_text("✅ Embed form deleted.")
    else:
        await query.edit_message_text("❌ Failed to delete embed form.")
    await asyncio.sleep(1)
    await show_embed_mgmt(query, context, user)


# ============================
# EMBED SUBMISSIONS (Manager)
# ============================

async def show_embed_submissions(query, context, user):
    try:
        from database import get_embedded_submissions, get_embedded_stats
        submissions = get_embedded_submissions(user["hotel_id"], limit=10)
        stats = get_embedded_stats(user["hotel_id"])

        text = "📊 *Guest Feedback Submissions*\n\n"
        if stats.get("total", 0) > 0:
            text += f"Total: {stats['total']} submissions\n"
            text += f"Avg Overall: {stats.get('avg_overall', '—')}/5 ⭐\n"
            text += f"Recommend Rate: {stats.get('recommend_pct', '—')}%\n\n"

            for sub in submissions[:5]:
                stars = "⭐" * (sub.get("overall_rating") or 0) + "☆" * (5 - (sub.get("overall_rating") or 0))
                text += f"{stars} ({sub.get('overall_rating', '?')}/5)\n"
                if sub.get("room_type"):
                    text += f"  Room: {sub['room_type']} | Guest: {sub.get('guest_type', 'N/A')}\n"
                if sub.get("feedback_text"):
                    text += f"  \"{sub['feedback_text'][:100]}\"\n"
                text += "\n"
        else:
            text += "No guest feedback collected yet.\n"

        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]
        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in embed submissions: {e}")
        await query.edit_message_text("⚠️ Error loading feedback submissions.")


# ============================
# CUSTOM SIGNAL SOURCES (Manager)
# ============================

async def show_custom_signals(query, context, user):
    try:
        from database import get_custom_signals
        signals = get_custom_signals(user["hotel_id"])

        text = "⚙️ *Custom Signal Sources*\n\n"
        keyboard = []
        if signals:
            for s in signals:
                status = "✅" if s.get("last_status") == "ok" else "❌"
                enabled = "🟢 ON" if s.get("enabled") else "🔴 OFF"
                text += f"{status} *{s['name']}* — {enabled}\n"
                if s.get("url"):
                    text += f"  URL: {s['url'][:50]}...\n"
                if s.get("last_error"):
                    text += f"  Error: {s['last_error'][:50]}\n"
                text += "\n"
                keyboard.append([InlineKeyboardButton(
                    f"{'🔴 Disable' if s['enabled'] else '🟢 Enable'} {s['name']}",
                    callback_data=f"custom_toggle_{s['id']}"
                )])
        else:
            text += "No custom signal sources configured.\n\n"
            text += "Add custom APIs via the web dashboard → Settings → Custom Intelligence Sources."

        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="main_menu")])
        await query.edit_message_text(_truncate(text), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in custom signals: {e}")
        await query.edit_message_text("⚠️ Error loading custom signals.")


async def _toggle_custom_signal(query, context, user, signal_id):
    from database import toggle_custom_signal
    toggle_custom_signal(signal_id)
    await query.edit_message_text("✅ Signal source toggled.")
    await asyncio.sleep(1)
    await show_custom_signals(query, context, user)


# ============================
# STAFF REPORT SUBMISSION (Staff)
# ============================

async def _prompt_staff_report(query, context, user):
    text = (
        "📝 *Submit Observation Report*\n\n"
        "Type your observations below. Be specific — mention:\n"
        "• Guest count & satisfaction\n"
        "• Supply issues\n"
        "• Competitor activity\n"
        "• Maintenance issues\n"
        "• Events or bookings\n\n"
        "The AI will structure your report automatically.\n\n"
        "*Send your observation now:*"
    )
    _pending_actions[str(query.from_user.id)] = {"type": "staff_report"}
    await query.edit_message_text(text, parse_mode='Markdown')


async def _process_staff_report(update, context, user, text, action):
    await update.message.reply_text("🤖 *Processing your report...*\nAI is structuring your observation.", parse_mode='Markdown')

    try:
        from ai_client import call_ai_for_json
        import json

        prompt = f"""You are an AI assistant for Agéiz hotel intelligence.
A staff member has submitted a daily observation report.
Extract and structure the information.

Determine:
1. overall sentiment (positive/negative/neutral)
2. customer_satisfaction (1-5 integer, or null)
3. guest_count (integer estimate, or null)
4. occupancy_pct (percentage 0-100, or null)
5. complaints (string summary)
6. supply_issues (string)
7. competitor_activity (string)
8. maintenance_issues (string)
9. events_booked (string)
10. summary (one sentence)
11. ai_insights (one sentence recommendation)

Return ONLY JSON. Use null for fields not mentioned.

Staff observation:
{text}
"""
        structured = call_ai_for_json(prompt, use_heavy_model=False)

        from database import create_staff_report, award_points
        hotel = get_hotel_profile(user["hotel_id"])
        hotel_id = user["hotel_id"] if user["hotel_id"] else 0

        report_id = create_staff_report(
            hotel_id=hotel_id,
            user_id=user["id"],
            report_type="daily",
            raw_input=text,
            structured_data=json.dumps(structured),
            sentiment=structured.get("sentiment", "neutral"),
            customer_satisfaction=structured.get("customer_satisfaction"),
            guest_count=structured.get("guest_count"),
            occupancy_pct=structured.get("occupancy_pct"),
            complaints=structured.get("complaints", ""),
            supply_issues=structured.get("supply_issues", ""),
            competitor_activity=structured.get("competitor_activity", ""),
            maintenance_issues=structured.get("maintenance_issues", ""),
            events_booked=structured.get("events_booked", ""),
            summary=structured.get("summary", ""),
            ai_insights=structured.get("ai_insights", "")
        )

        points = award_points(user["id"], hotel_id, "daily", "ai_structured")

        emoji = "🟢" if structured.get("sentiment") == "positive" else "🔴" if structured.get("sentiment") == "negative" else "🟡"

        response = (
            f"✅ *Report Submitted!*\n\n"
            f"{emoji} Sentiment: {structured.get('sentiment', 'N/A')}\n"
            f"📊 Satisfaction: {structured.get('customer_satisfaction', 'N/A')}/5\n"
            f"👥 Guests: {structured.get('guest_count', 'N/A')}\n"
            f"🏨 Occupancy: {structured.get('occupancy_pct', 'N/A')}%\n\n"
            f"📝 Summary: _{structured.get('summary', 'N/A')}_\n"
            f"💡 Insight: _{structured.get('ai_insights', 'N/A')}_\n\n"
            f"🏆 *+{points} points earned!*"
        )

        await update.message.reply_text(_truncate(response), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error processing staff report: {e}")
        # Save raw report anyway
        try:
            from database import create_staff_report, award_points
            hotel_id = user["hotel_id"] if user["hotel_id"] else 0
            report_id = create_staff_report(
                hotel_id=hotel_id, user_id=user["id"], report_type="daily",
                raw_input=text, sentiment="neutral",
                summary=text[:200]
            )
            points = award_points(user["id"], hotel_id, "daily", "good")
            await update.message.reply_text(f"✅ Report saved (raw). +{points} points. AI structuring failed: {str(e)[:100]}")
        except Exception as e2:
            await update.message.reply_text(f"❌ Failed to save report: {str(e2)[:100]}")

    await show_main_menu(update, context, user)


# ============================
# AI CHAT
# ============================

async def handle_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user, text):
    try:
        reply_target = update.message
        if not reply_target:
            logger.error("handle_ai_chat: no reply target")
            return

        hotel_id = user.get("hotel_id")
        if not hotel_id:
            await reply_target.reply_text("⚠️ Your account is not linked to a hotel property.")
            return

        await reply_target.reply_text("🤖 *Processing...*\nConsulting market intelligence.", parse_mode='Markdown')

        response = await get_chat_response(
            hotel_id=hotel_id,
            user_id=user["id"],
            user_message=text,
            location=None,
            user_language=user.get("language", "english")
        )

        await reply_target.reply_text(response)
    except Exception as e:
        logger.error(f"Error in handle_ai_chat: {e}")


# ============================
# BOT SETUP
# ============================

bot_app = None
_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

async def setup_bot():
    global bot_app
    if not TOKEN:
        logger.info("[telegram] TELEGRAM_BOT_TOKEN not found — bot disabled.")
        return

    try:
        application = ApplicationBuilder().token(TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).build()
    except Exception as e:
        logger.error(f"[telegram] Failed to build Telegram app: {e}")
        return

    bot_app = application
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        error = context.error
        logger.error(f"[telegram] Unhandled error: {error}")

    application.add_error_handler(error_handler)

    try:
        await application.initialize()
        await application.start()

        if _WEBHOOK_URL:
            webhook_url = _WEBHOOK_URL.rstrip("/") + "/telegram/webhook"
            await application.bot.set_webhook(webhook_url)
            logger.info(f"[telegram] Webhook set: {webhook_url}")
        else:
            await application.updater.start_polling(drop_pending_updates=True)
            logger.info("[telegram] Polling mode (dev).")
    except Exception as e:
        error_str = str(e)
        if "Conflict" in error_str or "terminated" in error_str:
            logger.warning("[telegram] ⚠️ Another bot instance detected. Bot disabled. Web app works normally.")
        else:
            logger.error(f"[telegram] Failed to start: {e}")
        try:
            await application.shutdown()
        except Exception:
            pass
        return

    return application
