"""Tests for time parsing utilities."""
import logging
import pytest

from custom_components.heating_control.coordinator import _parse_time_to_minutes, MINUTES_PER_DAY


@pytest.mark.parametrize(
    "time_str,expected",
    [
        # Valid times
        ("00:00", 0),
        ("08:30", 510),
        ("12:00", 720),
        ("23:59", 1439),
        ("01:05", 65),
        # Edge cases
        ("0:0", 0),  # Single digit hours/minutes
        ("9:5", 545),  # Single digit values
    ],
)
def test_parse_valid_time(time_str: str, expected: int):
    """Test parsing of valid time strings."""
    logger = logging.getLogger("test")
    result = _parse_time_to_minutes(time_str, logger)
    assert result == expected


@pytest.mark.parametrize(
    "invalid_time",
    [
        # Invalid formats
        "25:00",  # Invalid hour (>23)
        "12:60",  # Invalid minute (>59)
        "abc:def",  # Non-numeric
        "12",  # Missing colon
        "12:30:45",  # Too many parts
        "",  # Empty string
        ":",  # Only colon
        "12:",  # Missing minutes
        ":30",  # Missing hours
        "-5:30",  # Negative hour
        "12:-5",  # Negative minute
        "24:00",  # Hour = 24 (should be 0-23)
        "12.30",  # Wrong separator
        None,  # None value (will raise AttributeError)
        123,  # Integer instead of string
        "12:30 PM",  # 12-hour format with AM/PM
    ],
)
def test_parse_invalid_time_returns_default(invalid_time):
    """Test that invalid time strings return default (0) and log warning."""
    logger = logging.getLogger("test")
    result = _parse_time_to_minutes(invalid_time, logger)
    assert result == 0  # Should default to midnight


def test_parse_time_boundary_values():
    """Test boundary values for time parsing."""
    logger = logging.getLogger("test")

    # First valid minute
    assert _parse_time_to_minutes("00:00", logger) == 0

    # Last valid minute
    assert _parse_time_to_minutes("23:59", logger) == 1439

    # One past last valid hour should default
    assert _parse_time_to_minutes("24:00", logger) == 0

    # One past last valid minute should default
    assert _parse_time_to_minutes("23:60", logger) == 0


def test_parse_time_result_in_range():
    """Test that all valid results are within expected range."""
    logger = logging.getLogger("test")

    valid_times = [
        "00:00", "06:30", "12:00", "18:45", "23:59"
    ]

    for time_str in valid_times:
        result = _parse_time_to_minutes(time_str, logger)
        assert 0 <= result < MINUTES_PER_DAY
