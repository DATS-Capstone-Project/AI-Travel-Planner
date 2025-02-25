from dateutil.parser import parse
from datetime import datetime, timedelta
import re


def parse_date(text: str) -> str:
    try:
        return parse(text).strftime("%Y-%m-%d")
    except:
        return None


def validate_dates(start_date: str, end_date: str) -> bool:
    try:
        return datetime.strptime(end_date, "%Y-%m-%d") > datetime.strptime(start_date, "%Y-%m-%d")
    except:
        return False


def extract_trip_details(text: str) -> dict:
    details = {}
    text = text.lower()

    # Improved destination detection
    destination_match = re.search(
        r'\b(?:visit|travel to|go to|plan a trip to)\s+([a-z\s]+?)\s+(?:on|from|between|for|with)\b',
        text, re.I
    )
    if not destination_match:
        destination_match = re.search(r'\bto\s+([a-z\s]+)\b', text, re.I)
    if destination_match:
        details["destination"] = destination_match.group(1).strip().title()

    # Date parsing with duration support
    dates = re.findall(
        r'(\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\d{4}-\d{2}-\d{2})',
        text, re.I
    )

    duration_match = re.search(r'(\d+)\s+days?', text)

    if dates:
        details["start_date"] = parse_date(dates[0])
        if len(dates) > 1:
            details["end_date"] = parse_date(dates[1])
        elif duration_match and details.get("start_date"):
            start = datetime.strptime(details["start_date"], "%Y-%m-%d")
            end = start + timedelta(days=int(duration_match.group(1)))
            details["end_date"] = end.strftime("%Y-%m-%d")

    # Traveler extraction
    travelers_match = re.search(r'(\d+)\s+(?:people|travelers|adults|persons?|of us)\b', text)
    if travelers_match:
        details["travelers"] = int(travelers_match.group(1))

    return details
