from .correlate import correlate
from .detector import detect


def find_incidents(db_path=None, start_ts=None, end_ts=None):
    return correlate(detect(db_path, start_ts, end_ts))
