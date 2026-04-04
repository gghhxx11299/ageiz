import sqlite3
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ageiz.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = None  # Use tuple rows
    return conn

def init_db():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                hotel_id INTEGER,
                telegram_id TEXT UNIQUE,
                language TEXT DEFAULT 'english',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS hotel_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                hotel_name TEXT NOT NULL,
                website_url TEXT,
                locations TEXT,
                room_types TEXT,
                amenities TEXT,
                brand_positioning TEXT,
                target_guest_segments TEXT,
                price_range TEXT,
                unique_selling_points TEXT,
                business_objectives TEXT,
                raw_scraped_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                location TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                interpretation TEXT NOT NULL,
                raw_data TEXT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                location TEXT NOT NULL,
                room_rate_adjustment TEXT NOT NULL,
                package_adjustment TEXT NOT NULL,
                confidence TEXT NOT NULL,
                urgency TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                trend_context TEXT,
                signals_snapshot TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                location TEXT NOT NULL,
                cache_type TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(hotel_id, location, cache_type)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                message TEXT,
                thoughts TEXT,
                result TEXT,
                error TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                location TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_signal_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hotel_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                url TEXT,
                api_key TEXT,
                api_key_label TEXT,
                headers TEXT,
                request_method TEXT DEFAULT 'GET',
                request_body TEXT,
                response_path TEXT,
                enabled INTEGER DEFAULT 1,
                last_status TEXT DEFAULT 'ok',
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (hotel_id) REFERENCES hotel_profiles(id)
            )
        """)

        conn.commit()
    finally:
        conn.close()

def save_hotel_profile(
    user_id: int, hotel_name: str, website_url: str = None, locations: str = None,
    room_types: str = None, amenities: str = None, brand_positioning: str = None,
    target_guest_segments: str = None, price_range: str = None,
    unique_selling_points: str = None, business_objectives: str = None,
    raw_scraped_text: str = None
) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            INSERT INTO hotel_profiles (
                user_id, hotel_name, website_url, locations, room_types, 
                amenities, brand_positioning, target_guest_segments, 
                price_range, unique_selling_points, business_objectives, raw_scraped_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, hotel_name, website_url, locations, room_types,
            amenities, brand_positioning, target_guest_segments,
            price_range, unique_selling_points, business_objectives,
            raw_scraped_text
        ))
        hotel_id = cursor.lastrowid
        conn.commit()
        return hotel_id
    finally:
        conn.close()

def get_hotel_profile(hotel_id: int) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM hotel_profiles WHERE id = ?", (hotel_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "user_id": row[1], "hotel_name": row[2],
            "website_url": row[3], "locations": row[4], "room_types": row[5],
            "amenities": row[6], "brand_positioning": row[7],
            "target_guest_segments": row[8], "price_range": row[9],
            "unique_selling_points": row[10], "business_objectives": row[11],
            "raw_scraped_text": row[12]
        }
    finally:
        conn.close()

def save_signal(hotel_id: int, location: str, signal_type: str, sentiment: str, interpretation: str, raw_data: str):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO signal_history (hotel_id, location, signal_type, sentiment, interpretation, raw_data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (hotel_id, location, signal_type, sentiment, interpretation, raw_data))
        conn.commit()
    finally:
        conn.close()

def get_signal_history(hotel_id: int, location: str, days: int = 7) -> list:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT signal_type, sentiment, interpretation, recorded_at, raw_data
            FROM signal_history 
            WHERE hotel_id = ? AND location = ? 
            AND recorded_at >= datetime('now', '-' || ? || ' days')
            ORDER BY recorded_at DESC
        """, (hotel_id, location, days))
        rows = cursor.fetchall()
        return [
            {"signal_type": r[0], "sentiment": r[1], "interpretation": r[2], "recorded_at": r[3], "raw_data": r[4]}
            for r in rows
        ]
    finally:
        conn.close()

def save_recommendation(
    hotel_id: int, location: str, room_rate_adjustment: str, 
    package_adjustment: str, confidence: str, urgency: str, 
    reasoning: str, trend_context: str = "", signals_snapshot: str = None
):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO recommendations (
                hotel_id, location, room_rate_adjustment, package_adjustment, 
                confidence, urgency, reasoning, trend_context, signals_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hotel_id, location, room_rate_adjustment, package_adjustment,
            confidence, urgency, reasoning, trend_context, signals_snapshot
        ))
        conn.commit()
    finally:
        conn.close()

def get_recommendation_history(hotel_id: int, location: str, limit: int = 5) -> list:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT * FROM recommendations 
            WHERE hotel_id = ? AND location = ? 
            ORDER BY created_at DESC LIMIT ?
        """, (hotel_id, location, limit))
        rows = cursor.fetchall()
        return [
            {
                "id": r[0], "hotel_id": r[1], "location": r[2],
                "room_rate_adjustment": r[3], "package_adjustment": r[4],
                "confidence": r[5], "urgency": r[6], "reasoning": r[7],
                "trend_context": r[8], "created_at": r[10]
            }
            for r in rows
        ]
    finally:
        conn.close()

def save_cache(hotel_id: int, location: str, cache_type: str, data: str):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO cache (hotel_id, location, cache_type, data, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (hotel_id, location, cache_type, data))
        conn.commit()
    finally:
        conn.close()

def get_cache(hotel_id: int, location: str, cache_type: str) -> str | None:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT data FROM cache WHERE hotel_id = ? AND location = ? AND cache_type = ?
        """, (hotel_id, location, cache_type))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def create_pipeline_task(hotel_id: int) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("INSERT INTO pipeline_tasks (hotel_id) VALUES (?)", (hotel_id,))
        task_id = cursor.lastrowid
        conn.commit()
        return task_id
    finally:
        conn.close()

def update_pipeline_task(task_id: int, status: str = None, progress: int = None, message: str = None, thoughts: str = None, result: str = None, error: str = None):
    conn = get_connection()
    try:
        if status == 'running':
            conn.execute("UPDATE pipeline_tasks SET status = ?, started_at = CURRENT_TIMESTAMP WHERE id = ?", (status, task_id))
        elif status == 'completed':
            conn.execute("UPDATE pipeline_tasks SET status = ?, progress = 100, completed_at = CURRENT_TIMESTAMP, result = ? WHERE id = ?", (status, result, task_id))
        elif status == 'failed':
            conn.execute("UPDATE pipeline_tasks SET status = ?, error = ? WHERE id = ?", (status, error, task_id))
        else:
            updates = []
            params = []
            if progress is not None:
                updates.append("progress = ?")
                params.append(progress)
            if message is not None:
                updates.append("message = ?")
                params.append(message)
            if thoughts is not None:
                updates.append("thoughts = ?")
                params.append(thoughts)
            if updates:
                params.append(task_id)
                conn.execute(f"UPDATE pipeline_tasks SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()
    finally:
        conn.close()

def get_pipeline_task(task_id: int) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM pipeline_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "hotel_id": row[1], "status": row[2],
            "progress": row[3], "message": row[4], "thoughts": row[5],
            "result": row[6], "error": row[7], 
            "started_at": row[8], "completed_at": row[9], "created_at": row[10]
        }
    finally:
        conn.close()

def get_latest_pipeline_task(hotel_id: int) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT * FROM pipeline_tasks 
            WHERE hotel_id = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (hotel_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "hotel_id": row[1], "status": row[2],
            "progress": row[3], "message": row[4], "thoughts": row[5],
            "result": row[6], "error": row[7], 
            "started_at": row[8], "completed_at": row[9], "created_at": row[10]
        }
    finally:
        conn.close()

def get_pending_pipeline_task() -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM pipeline_tasks WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "hotel_id": row[1], "status": row[2]
        }
    finally:
        conn.close()

def get_user_by_email(email: str) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "password_hash": row[2], "hotel_id": row[3], "telegram_id": row[4], "language": row[5] if len(row) > 5 else "english", "created_at": row[6]}
    finally:
        conn.close()

def create_user(email: str, password_hash: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, password_hash))
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    finally:
        conn.close()

def update_user_hotel(user_id: int, hotel_id: int):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET hotel_id = ? WHERE id = ?", (hotel_id, user_id))
        conn.commit()
    finally:
        conn.close()

def save_chat_message(hotel_id: int, user_id: int, location: str, role: str, content: str):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO chat_messages (hotel_id, user_id, location, role, content)
            VALUES (?, ?, ?, ?, ?)
        """, (hotel_id, user_id, location, role, content))
        conn.commit()
    finally:
        conn.close()

def get_chat_history(hotel_id: int, location: str = None, limit: int = 20) -> list:
    conn = get_connection()
    try:
        if location:
            cursor = conn.execute("""
                SELECT role, content FROM chat_messages 
                WHERE hotel_id = ? AND location = ? 
                ORDER BY created_at ASC LIMIT ?
            """, (hotel_id, location, limit))
        else:
            cursor = conn.execute("""
                SELECT role, content FROM chat_messages 
                WHERE hotel_id = ? 
                ORDER BY created_at ASC LIMIT ?
            """, (hotel_id, limit))
        rows = cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]
    finally:
        conn.close()

def save_otp_code(user_id: int, code: str):
    conn = get_connection()
    try:
        expires_at = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("DELETE FROM otp_codes WHERE user_id = ?", (user_id,))
        conn.execute("INSERT INTO otp_codes (user_id, code, expires_at) VALUES (?, ?, ?)", (user_id, code, expires_at))
        conn.commit()
    finally:
        conn.close()

def verify_otp_code(code: str) -> int | None:
    """Verify an OTP code and return the user_id if valid.
    Also verifies the user still exists in the users table.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT user_id FROM otp_codes
            WHERE code = ? AND expires_at > ?
        """, (code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        row = cursor.fetchone()
        if not row:
            print(f"[database] OTP code not found in database")
            return None

        user_id = row[0]

        # Verify the user still exists before returning
        user_cursor = conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,))
        user_row = user_cursor.fetchone()
        if not user_row:
            print(f"[database] OTP code is valid but user_id={user_id} does NOT exist in users table!")
            all_users = conn.execute("SELECT id, email FROM users").fetchall()
            print(f"[database] Current users in DB: {all_users}")
            # Return -1 as a sentinel: OTP is valid but user is gone
            return -1

        # OTP valid and user exists — consume the OTP
        conn.execute("DELETE FROM otp_codes WHERE user_id = ?", (user_id,))
        conn.commit()
        print(f"[database] OTP verified for user_id={user_id} ({user_row[1]})")
        return user_id
    finally:
        conn.close()

def link_telegram_id(user_id: int, telegram_id: str) -> bool:
    """Link a Telegram ID to a user. Returns True on success, False on failure."""
    conn = get_connection()
    try:
        # First verify the user exists
        cursor = conn.execute("SELECT id, email, telegram_id FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()

        if not user_row:
            print(f"[database] link_telegram_id: user_id={user_id} does NOT exist in users table")
            all_users = conn.execute("SELECT id, email FROM users").fetchall()
            print(f"[database] Current users in DB: {all_users}")
            return False

        # Clear this telegram_id from any other user to prevent unique constraint issues
        conn.execute("UPDATE users SET telegram_id = NULL WHERE telegram_id = ?", (telegram_id,))

        # Perform the link
        result = conn.execute("UPDATE users SET telegram_id = ? WHERE id = ?", (telegram_id, user_id))
        conn.commit()

        if result.rowcount == 0:
            print(f"[database] link_telegram_id: UPDATE affected 0 rows for user_id={user_id}")
            return False

        print(f"[database] user_id={user_id} ({user_row[1]}) linked to telegram_id={telegram_id}")
        return True
    finally:
        conn.close()

def unlink_telegram_id(telegram_id: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET telegram_id = NULL WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
    finally:
        conn.close()

def get_user_by_telegram_id(telegram_id: str) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1], "password_hash": row[2], "hotel_id": row[3], "telegram_id": row[4], "language": row[5] if len(row) > 5 else "english", "created_at": row[6]}
    finally:
        conn.close()

def update_user_language(user_id: int, language: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET language = ? WHERE id = ?", (language, user_id))
        conn.commit()
    finally:
        conn.close()

def create_notification(user_id: int, n_type: str, message: str):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO notifications (user_id, type, message)
            VALUES (?, ?, ?)
        """, (user_id, n_type, message))
        conn.commit()
    finally:
        conn.close()

def get_notifications(user_id: int, unread_only: bool = True) -> list:
    conn = get_connection()
    try:
        query = "SELECT id, type, message, created_at FROM notifications WHERE user_id = ?"
        if unread_only:
            query += " AND is_read = 0"
        query += " ORDER BY created_at DESC"
        
        cursor = conn.execute(query, (user_id,))
        rows = cursor.fetchall()
        return [
            {"id": r[0], "type": r[1], "message": r[2], "created_at": r[3]}
            for r in rows
        ]
    finally:
        conn.close()

def mark_notifications_read(user_id: int):
    conn = get_connection()
    try:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# --- Custom Signal Sources ---
# XOR obfuscation for API key storage (prevents casual exposure)

_SECRET_KEY = os.getenv("SECRET_KEY", "ageiz-local-dev-secret-key-change-in-production").encode()

def _obfuscate(value: str) -> str:
    """XOR obfuscate a string for storage."""
    if not value:
        return ""
    key_bytes = _SECRET_KEY
    val_bytes = value.encode()
    xored = bytes([val_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(val_bytes))])
    return xored.hex()

def _deobfuscate(hex_value: str) -> str:
    """Deobfuscate a hex string back to plaintext."""
    if not hex_value:
        return ""
    try:
        key_bytes = _SECRET_KEY
        xored = bytes.fromhex(hex_value)
        return bytes([xored[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(xored))]).decode()
    except Exception:
        return ""


def create_custom_signal(hotel_id: int, name: str, description: str, url: str = None,
                         api_key: str = None, api_key_label: str = "Authorization",
                         headers: str = None, method: str = "GET", body: str = None,
                         response_path: str = None) -> int:
    conn = get_connection()
    try:
        obfuscated_key = _obfuscate(api_key) if api_key else None
        cursor = conn.execute("""
            INSERT INTO custom_signal_sources (
                hotel_id, name, description, url, api_key, api_key_label,
                headers, request_method, request_body, response_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hotel_id, name, description, url, obfuscated_key, api_key_label,
            headers, method, body, response_path
        ))
        signal_id = cursor.lastrowid
        conn.commit()
        return signal_id
    finally:
        conn.close()

def get_custom_signals(hotel_id: int) -> list:
    """Get all custom signal sources for a hotel. API keys returned obfuscated."""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT * FROM custom_signal_sources WHERE hotel_id = ?
            ORDER BY created_at DESC
        """, (hotel_id,))
        rows = cursor.fetchall()
        return [
            {
                "id": r[0], "hotel_id": r[1], "name": r[2], "description": r[3],
                "url": r[4], "api_key": r[5], "api_key_label": r[6],
                "headers": r[7], "method": r[8], "body": r[9],
                "response_path": r[10], "enabled": bool(r[11]),
                "last_status": r[12], "last_error": r[13],
                "created_at": r[14], "updated_at": r[15]
            }
            for r in rows
        ]
    finally:
        conn.close()

def get_custom_signal_deobfuscated(hotel_id: int) -> list:
    """Get all custom signal sources with API keys deobfuscated (for pipeline use)."""
    signals = get_custom_signals(hotel_id)
    for s in signals:
        if s.get("api_key"):
            s["api_key"] = _deobfuscate(s["api_key"])
    return signals

def get_custom_signal(signal_id: int) -> dict | None:
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT * FROM custom_signal_sources WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "hotel_id": row[1], "name": row[2], "description": row[3],
            "url": row[4], "api_key": row[5], "api_key_label": row[6],
            "headers": row[7], "method": row[8], "body": row[9],
            "response_path": row[10], "enabled": bool(row[11]),
            "last_status": row[12], "last_error": row[13],
            "created_at": row[14], "updated_at": row[15]
        }
    finally:
        conn.close()

def update_custom_signal(signal_id: int, **kwargs):
    """Update fields on a custom signal source. Only provided fields are changed."""
    allowed = {"name", "description", "url", "api_key", "api_key_label",
               "headers", "method", "body", "response_path", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return

    conn = get_connection()
    try:
        # Obfuscate API key if being updated
        if "api_key" in updates and updates["api_key"]:
            updates["api_key"] = _obfuscate(updates["api_key"])
        elif "api_key" in updates and updates["api_key"] == "":
            updates["api_key"] = None

        set_parts = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [signal_id]
        conn.execute(f"UPDATE custom_signal_sources SET {set_parts}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()

def delete_custom_signal(signal_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM custom_signal_sources WHERE id = ?", (signal_id,))
        conn.commit()
    finally:
        conn.close()

def toggle_custom_signal(signal_id: int):
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE custom_signal_sources
            SET enabled = 1 - enabled, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (signal_id,))
        conn.commit()
    finally:
        conn.close()

def update_custom_signal_status(signal_id: int, status: str, error: str = None):
    """Update last_status and last_error fields after a fetch attempt."""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE custom_signal_sources
            SET last_status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, error, signal_id))
        conn.commit()
    finally:
        conn.close()
