import logging
import pytest
from busbidder.logging_setup import close_logging, setup_logging


@pytest.fixture(autouse=True)
def release_log_file():
    """Close the log file after each test, so the temporary folder can be removed."""
    yield
    close_logging()


def test_messages_from_any_module_are_written_to_the_log_file(tmp_path):
    log_file = tmp_path / "busbidder.log"
    setup_logging(log_file)

    logging.getLogger("busbidder.validation").warning("Corrected destination")
    close_logging()

    text = log_file.read_text(encoding="utf-8")
    assert "WARNING" in text
    assert "busbidder.validation: Corrected destination" in text


def test_log_folder_is_created_if_missing(tmp_path):
    log_file = tmp_path / "logs" / "busbidder.log"
    setup_logging(log_file)
    logging.getLogger("busbidder").info("started")
    close_logging()
    assert log_file.exists()


def test_messages_below_the_chosen_level_are_not_written(tmp_path):
    log_file = tmp_path / "busbidder.log"
    setup_logging(log_file, level=logging.WARNING)

    logging.getLogger("busbidder.loader").info("Read 245 records")
    logging.getLogger("busbidder.loader").error("Cannot read file")
    close_logging()

    text = log_file.read_text(encoding="utf-8")
    assert "Read 245 records" not in text
    assert "Cannot read file" in text


def test_calling_setup_twice_does_not_duplicate_messages(tmp_path):
    log_file = tmp_path / "busbidder.log"
    setup_logging(log_file)
    setup_logging(log_file)

    logging.getLogger("busbidder").info("only once")
    close_logging()

    assert log_file.read_text(encoding="utf-8").count("only once") == 1


def test_new_runs_are_appended_to_the_existing_log(tmp_path):
    log_file = tmp_path / "busbidder.log"

    setup_logging(log_file)
    logging.getLogger("busbidder").info("first run")
    setup_logging(log_file)
    logging.getLogger("busbidder").info("second run")
    close_logging()

    text = log_file.read_text(encoding="utf-8")
    assert "first run" in text and "second run" in text