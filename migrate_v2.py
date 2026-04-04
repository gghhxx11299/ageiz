from database import get_connection

def migrate():
    conn = get_connection()
    print("Starting database migration for Language and Notifications...")
    
    # Add language column to users
    try:
        conn.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'english'")
        conn.commit()
        print("✅ Added language column to users table.")
    except Exception as e:
        print(f"ℹ️ Language column check: {e}")

    # Create notifications table
    try:
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
        print("✅ Ensured notifications table exists.")
    except Exception as e:
        print(f"❌ Error creating notifications table: {e}")

    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
