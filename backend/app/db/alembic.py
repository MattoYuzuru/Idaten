def escape_config_percent(value: str) -> str:
    """Escape URL percent encoding for ConfigParser-backed Alembic options."""
    return value.replace("%", "%%")
