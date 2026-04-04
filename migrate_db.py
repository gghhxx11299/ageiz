from database import get_connection

def migrate():
    conn = get_connection()
    print("Starting database migration...")
    
    # Add telegram_id to users
    try:
        conn.execute("ALTER TABLE users ADD COLUMN telegram_id TEXT")
        conn.commit()
        print("✅ Added telegram_id column to users table.")
    except Exception as e:
        if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
            print("ℹ️ telegram_id column already exists.")
        else:
            print(f"❌ Error adding column: {e}")

    # Ensure otp_codes table exists
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
        print("✅ Ensured otp_codes table exists.")
    except Exception as e:
        print(f"❌ Error creating otp_codes: {e}")

    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
