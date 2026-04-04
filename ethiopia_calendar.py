from datetime import date

ETHIOPIAN_HOLIDAYS_2026 = [
    {"date": "2026-01-07", "name": "Genna (Ethiopian Christmas)", "demand_impact": "very high", "impact_score": 0.95},
    {"date": "2026-01-19", "name": "Timket (Ethiopian Epiphany)", "demand_impact": "very high", "impact_score": 0.95},
    {"date": "2026-03-02", "name": "Adwa Victory Day", "demand_impact": "medium", "impact_score": 0.5},
    {"date": "2026-03-30", "name": "Eid al Fitr", "demand_impact": "high", "impact_score": 0.75},
    {"date": "2026-04-18", "name": "Siklet (Ethiopian Good Friday)", "demand_impact": "high", "impact_score": 0.7},
    {"date": "2026-04-20", "name": "Fasika (Ethiopian Easter)", "demand_impact": "very high", "impact_score": 1.0},
    {"date": "2026-05-01", "name": "International Labour Day", "demand_impact": "low", "impact_score": 0.2},
    {"date": "2026-05-05", "name": "Patriots Victory Day", "demand_impact": "low", "impact_score": 0.2},
    {"date": "2026-05-28", "name": "Downfall of the Derg", "demand_impact": "medium", "impact_score": 0.45},
    {"date": "2026-06-06", "name": "Eid al Adha", "demand_impact": "high", "impact_score": 0.75},
    {"date": "2026-08-26", "name": "Mawlid", "demand_impact": "medium", "impact_score": 0.5},
    {"date": "2026-09-11", "name": "Enkutatash (Ethiopian New Year)", "demand_impact": "very high", "impact_score": 0.95},
    {"date": "2026-09-27", "name": "Meskel", "demand_impact": "very high", "impact_score": 0.9},
]

def get_upcoming_holidays(days_ahead: int = 30) -> list:
    today = date.today()
    upcoming = []
    for h in ETHIOPIAN_HOLIDAYS_2026:
        holiday_date = date.fromisoformat(h["date"])
        days_away = (holiday_date - today).days
        if 0 <= days_away <= days_ahead:
            upcoming.append({
                "date": h["date"],
                "name": h["name"],
                "demand_impact": h["demand_impact"],
                "impact_score": h["impact_score"],
                "days_away": days_away
            })
    return sorted(upcoming, key=lambda x: x["days_away"])

def get_calendar_signal() -> dict:
    upcoming_30 = get_upcoming_holidays(30)
    upcoming_14 = get_upcoming_holidays(14)
    upcoming_7 = get_upcoming_holidays(7)
    
    if upcoming_7:
        nearest = upcoming_7[0]
        urgency = "imminent"
    elif upcoming_14:
        nearest = upcoming_14[0]
        urgency = "approaching"
    elif upcoming_30:
        nearest = upcoming_30[0]
        urgency = "upcoming"
    else:
        return {
            "has_holiday": False,
            "urgency": "none",
            "nearest_holiday": None,
            "days_away": None,
            "demand_impact": "none",
            "impact_score": 0.0,
            "all_upcoming_30_days": []
        }
    
    return {
        "has_holiday": True,
        "urgency": urgency,
        "nearest_holiday": nearest["name"],
        "days_away": nearest["days_away"],
        "demand_impact": nearest["demand_impact"],
        "impact_score": nearest["impact_score"],
        "all_upcoming_30_days": upcoming_30
    }
