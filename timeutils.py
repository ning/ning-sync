from datetime import datetime

from iso8601 import iso8601


def now_utc():
    """Return the current datetime with tzinfo set to UTC"""
    return datetime.now(iso8601.Utc())


def add_utc_tzinfo(d):
    """Add a UTC timezone to the given datetime"""
    return d.replace(tzinfo=iso8601.Utc())


def struct_to_datetime(time_struct):
    """Convert the time module's time tuple to a datetime with a UTC tzinfo"""
    entry_datetime = datetime(*time_struct[:6])
    return add_utc_tzinfo(entry_datetime)
