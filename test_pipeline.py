from pipeline import run_pipeline
from database import get_connection
import json

def find_test_hotel():
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT id, hotel_name, locations FROM hotel_profiles LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "name": row[1], "locations": row[2]}
        return None
    finally:
        conn.close()

def main():
    print("--- Agéiz Terminal Test Engine ---")
    hotel = find_test_hotel()
    
    if not hotel:
        print("No hotel profile found in database. Please onboard a hotel first via the UI.")
        return

    print(f"Targeting Hotel: {hotel['name']} (ID: {hotel['id']})")
    print(f"Locations: {hotel['locations']}")
    print("-" * 34)
    
    try:
        # Run the pipeline synchronously for testing
        # We don't pass a task_id to avoid updating the tasks table if not needed,
        # or we can create a dummy one.
        result = run_pipeline(hotel['id'])
        
        print("\n--- Pipeline Execution Result ---")
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"Successfully processed {len(result.get('locations_processed', []))} locations.")
            for loc, data in result.get('results', {}).items():
                print(f"\nLocation: {loc}")
                rec = data.get('recommendation', {})
                print(f"  Urgency: {rec.get('urgency')}")
                print(f"  Confidence: {rec.get('overall_confidence')}")
                print(f"  Room Adj: {rec.get('room_rates', {}).get('standard_rooms', 'N/A')}")
                print(f"  Reasoning: {rec.get('room_rates', {}).get('reasoning', 'N/A')[:100]}...")

    except Exception as e:
        print(f"Critical failure during test: {e}")

if __name__ == "__main__":
    main()
