from enum import StrEnum


class SourceType(StrEnum):
    MANUAL = "MANUAL"
    HEALTH_CONNECT = "HEALTH_CONNECT"
    STRAVA = "STRAVA"
    GPX = "GPX"
    FIT = "FIT"
    TCX = "TCX"
    CSV = "CSV"
    TEXT = "TEXT"
    SCREENSHOT = "SCREENSHOT"
    SAMSUNG_EXPORT = "SAMSUNG_EXPORT"
