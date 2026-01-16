"""Datetime utilities for rd_domain."""

from datetime import datetime, timedelta, timezone

# Moscow timezone (UTC+3)
MSK_TZ = timezone(timedelta(hours=3))


def get_moscow_time_str() -> str:
    """Get current Moscow time as 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S")
