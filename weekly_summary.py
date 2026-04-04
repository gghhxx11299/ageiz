from database import get_signal_history
from collections import defaultdict

def build_weekly_summary(hotel_id: int, location: str) -> dict:
    history = get_signal_history(hotel_id, location, days=7)
    
    if not history:
        return {
            "available": False,
            "message": "No weekly history yet — recommendation based on today only",
            "signal_trends": {}
        }
    
    by_signal = defaultdict(list)
    for record in history:
        by_signal[record["signal_type"]].append(record["sentiment"])
    
    signal_trends = {}
    for signal_type, sentiments in by_signal.items():
        positive = sentiments.count("positive")
        negative = sentiments.count("negative")
        neutral = sentiments.count("neutral")
        total = len(sentiments)
        
        if positive > negative and positive > neutral:
            dominant = "positive"
        elif negative > positive and negative > neutral:
            dominant = "negative"
        else:
            dominant = "neutral"
        
        if total >= 3:
            recent = sentiments[-2:]
            early = sentiments[:2]
            recent_positive = recent.count("positive") / len(recent)
            early_positive = early.count("positive") / len(early)
            if recent_positive > early_positive + 0.3:
                trajectory = "improving"
            elif recent_positive < early_positive - 0.3:
                trajectory = "worsening"
            else:
                trajectory = "stable"
        else:
            trajectory = "insufficient_data"
        
        signal_trends[signal_type] = {
            "dominant_sentiment": dominant,
            "trajectory": trajectory,
            "data_points": total,
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral
        }
    
    overall_positive = sum(1 for s in history if s["sentiment"] == "positive")
    overall_negative = sum(1 for s in history if s["sentiment"] == "negative")
    overall_total = len(history)
    
    if overall_total > 0:
        positivity_ratio = overall_positive / overall_total
    else:
        positivity_ratio = 0.5
    
    return {
        "available": True,
        "days_of_data": 7,
        "total_signal_records": overall_total,
        "overall_positivity_ratio": round(positivity_ratio, 2),
        "overall_weekly_sentiment": "positive" if positivity_ratio > 0.6 else "negative" if positivity_ratio < 0.4 else "mixed",
        "signal_trends": signal_trends
    }
