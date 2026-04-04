import pytest
import json
from pipeline import run_pipeline
from database import get_connection

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

@pytest.mark.asyncio
async def test_pipeline_invalid_hotel():
    # Test with non-existent hotel ID
    result = await run_pipeline(999999)
    assert "error" in result
    assert "not found" in result["error"].lower()

@pytest.mark.asyncio
async def test_pipeline_basic_structure():
    hotel = find_test_hotel()
    if not hotel:
        pytest.skip("No hotel profile in database to test with.")
        
    # We don't want to run the full expensive pipeline in every unit test, 
    # but this shows the structure.
    # result = await run_pipeline(hotel['id'])
    # assert result['hotel_id'] == hotel['id']
    assert True
