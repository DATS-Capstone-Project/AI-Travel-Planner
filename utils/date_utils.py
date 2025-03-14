import re
import logging
from datetime import datetime, timedelta
from typing import Optional
from dateutil.parser import parse as dateutil_parse
from config.settings import MAX_FUTURE_DAYS  # Ensure MAX_FUTURE_DAYS is set to 180 or similar

# Configure logger
logger = logging.getLogger(__name__)


def parse_date(text: str) -> Optional[str]:
    """
    Parse date from text into YYYY-MM-DD format

    Args:
        text: Date string in any format

    Returns:
        Formatted date string or None if parsing fails
    """
    try:
        # If already in YYYY-MM-DD format, return as is
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            return text

        parsed_date = dateutil_parse(text)

        # If year is not specified in the input, use current year.
        current_year = datetime.now().year
        if parsed_date.year == current_year and text.lower().find(str(current_year)) == -1:
            # If the date has already passed in current year, assume next year
            if parsed_date < datetime.now():
                parsed_date = parsed_date.replace(year=current_year + 1)

        return parsed_date.strftime("%Y-%m-%d")

    except Exception as e:
        logger.error(f"Error parsing date '{text}': {e}")
        return None


def validate_future_date(date_str: str) -> Optional[str]:
    """
    Validate a date string ensuring it is in the future (relative to today)
    and not more than 6 months (approximately 180 days) ahead.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Validated date string in YYYY-MM-DD format or None if the date is invalid.
    """
    try:
        # Convert the input date
        date = datetime.strptime(date_str, "%Y-%m-%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Check that the date is in the future
        if date < today:
            logger.warning(f"Date {date_str} is in the past relative to today.")
            return None

        # Define the maximum allowed future date (6 months from today)
        max_future = today + timedelta(days=180)
        if date > max_future:
            logger.warning(f"Date {date_str} is more than 6 months in the future.")
            return None

        return date.strftime("%Y-%m-%d")
    except Exception as e:
        logger.error(f"Error validating date '{date_str}': {e}")
        return None


def validate_date_range(start_date: str, end_date: str) -> bool:
    """
    Validate that end date is after start date and both are within limits

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        True if date range is valid, False otherwise
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        # End must be after start
        if end <= start:
            return False

        # Check that dates are within allowed range
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        max_future = today + timedelta(days=180)

        return start >= today and end <= max_future

    except Exception:
        return False


def calculate_duration(start_date: str, end_date: str) -> Optional[int]:
    """
    Calculate duration between two dates in days

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Number of days or None if calculation fails
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        return (end - start).days
    except Exception:
        return None

