import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from busbidder.exceptions import DataError, MissingFieldError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawRecord:
    line: int
    fields: dict[str, str]


def read_csv(path: Path, required_columns: list[str]) -> list[RawRecord]:
    """Read every row of a CSV file as text.

    Raises DataError if the file cannot be opened, and MissingFieldError if
    the header row lacks any of the required columns.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            header = reader.fieldnames or []

            missing = [column for column in required_columns if column not in header]
            if missing:
                raise MissingFieldError(
                    f"{path.name} is missing required column(s): {', '.join(missing)}"
                )

            records = []
            for row in reader:
                fields = {key: value if value is not None else ""
                          for key, value in row.items() if key is not None}
                records.append(RawRecord(line=reader.line_num, fields=fields))

    except OSError as error:
        raise DataError(f"Cannot read {path}: {error.strerror}") from error

    logger.info("Read %d records from %s", len(records), path.name)
    return records