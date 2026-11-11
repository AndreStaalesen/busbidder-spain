"""Custom exceptions for BusBidder.

All errors raised by the application inherit from BusBidderError so a caller
can catch every application error at once, or one family at a time:

    BusBidderError
    ├── DataError          problems in the input data files
    ├── ConfigError        problems in profiles, weights or requests
    └── BookingError       problems while creating a booking
"""


class BusBidderError(Exception):
    """Base class for every error raised by the application."""


class DataError(BusBidderError):
    """A record in an input file is missing, invalid or inconsistent.

    Stores where the problem was found so log messages can point to the
    exact record and line in the file.
    """

    def __init__(self, message: str, record_id: str | None = None,
                 line: int | None = None) -> None:
        self.reason = message
        self.record_id = record_id
        self.line = line

        location = []
        if line is not None:
            location.append(f"line {line}")
        if record_id:
            location.append(record_id)
        prefix = f"[{', '.join(location)}] " if location else ""

        super().__init__(f"{prefix}{message}")









class MissingFieldError(DataError):
    """A required field is empty or absent."""


class InvalidValueError(DataError):
    """A field cannot be parsed, or its value is impossible."""


class UnknownReferenceError(DataError):
    """A record refers to a company or destination that does not exist."""


class InconsistentRecordError(DataError):
    """Fields contradict each other."""


class ConfigError(BusBidderError):
    """A traveller profile, weight set or travel request is invalid."""


class InvalidWeightsError(ConfigError):
    """Weights are negative, refer to unknown criteria, or do not total 100."""


class ProfileNotFoundError(ConfigError):
    """The requested traveller profile does not exist."""


class BookingError(BusBidderError):
    """A booking could not be created."""


class NoSeatsAvailableError(BookingError):
    """The selected offer has no seats left."""