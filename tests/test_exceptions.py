"""Tests for the exception hierarchy."""

import pytest

from busbidder.exceptions import (
    BookingError,
    BusBidderError,
    ConfigError,
    DataError,
    InconsistentRecordError,
    InvalidValueError,
    InvalidWeightsError,
    MissingFieldError,
    NoSeatsAvailableError,
    ProfileNotFoundError,
    UnknownReferenceError,
)


@pytest.mark.parametrize("error_class, family", [
    (MissingFieldError, DataError),
    (InvalidValueError, DataError),
    (UnknownReferenceError, DataError),
    (InconsistentRecordError, DataError),
    (InvalidWeightsError, ConfigError),
    (ProfileNotFoundError, ConfigError),
    (NoSeatsAvailableError, BookingError),
])
def test_each_error_belongs_to_its_family_and_the_base(error_class, family):
    assert issubclass(error_class, family)
    assert issubclass(error_class, BusBidderError)


def test_base_error_can_catch_any_application_error():
    with pytest.raises(BusBidderError):
        raise InvalidWeightsError("weights total 90, must be 100")


def test_data_error_message_includes_line_and_record_id():
    error = InvalidValueError("price_eur must be greater than 0",
                              record_id="SOL-COR-902", line=228)
    assert str(error) == "[line 228, SOL-COR-902] price_eur must be greater than 0"
    assert error.reason == "price_eur must be greater than 0"
    assert error.record_id == "SOL-COR-902"
    assert error.line == 228


def test_data_error_message_without_location():
    error = MissingFieldError("price_eur is missing")
    assert str(error) == "price_eur is missing"
    assert error.record_id is None
    assert error.line is None