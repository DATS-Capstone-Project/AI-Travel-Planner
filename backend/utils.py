from dateutil.parser import parse
from datetime import datetime


def parse_date(text: str) -> str:
    try:
        return parse(text).strftime("%Y-%m-%d")
    except:
        return None


def validate_dates(start_date: str, end_date: str) -> bool:
    return datetime.strptime(end_date, "%Y-%m-%d") > datetime.strptime(start_date, "%Y-%m-%d")
