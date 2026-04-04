"""
Migration v3: Add language preference to users table
Run: python migrate_v3.py
"""
import libsql_experimental as libsql
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    url = os.getenv("TURSO_URL", "ageiz.db")
    token = os.getenv("TURSO_TOKEN", "")
    if token:
        return libsql.connect(database=url, auth_token=token)
    return libsql.connect(database=url)

def migrate():
    conn = get_connection()
    try:
        # Check if column already exists
        cursor = conn.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]

        if "language" not in columns:
            print("Adding 'language' column to users table...")
            conn.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'english'")
            conn.commit()
            print("✓ Migration successful: 'language' column added")
        else:
            print("'language' column already exists")

        # Create notifications table if it doesn't exist (from v2)
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
        conn.commit()
        print("✓ Notifications table ensured")

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
