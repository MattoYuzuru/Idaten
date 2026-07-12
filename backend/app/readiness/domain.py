from enum import StrEnum


class CheckInPhase(StrEnum):
    POST_RUN = "POST_RUN"
    PRE_RUN = "PRE_RUN"


class CheckInStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CheckInInputSource(StrEnum):
    MANUAL = "MANUAL"
    AI_TEXT = "AI_TEXT"
    AI_VOICE = "AI_VOICE"
    HEALTH_CONNECT = "HEALTH_CONNECT"
    MERGED = "MERGED"
