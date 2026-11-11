from pathlib import Path
import pytest
from busbidder.exceptions import DataError, MissingFieldError
from busbidder.loader import read_csv

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COLUMNS = ["offer_id", "price_eur"]


def write_file(folder: Path, text: str, encoding: str = "utf-8") -> Path:
    path = folder / "offers.csv"
    path.write_text(text, encoding=encoding)
    return path


def test_reads_every_row_as_text(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur\nSOL-MAL-001,32.07\nCAM-MAL-001,57.06\n")
    records = read_csv(path, COLUMNS)
    assert [r.fields for r in records] == [
        {"offer_id": "SOL-MAL-001", "price_eur": "32.07"},
        {"offer_id": "CAM-MAL-001", "price_eur": "57.06"},
    ]


def test_line_numbers_count_the_header_as_line_one(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur\nSOL-MAL-001,32.07\nCAM-MAL-001,57.06\n")
    assert [r.line for r in read_csv(path, COLUMNS)] == [2, 3]


def test_values_are_not_changed_or_trimmed(tmp_path):
    path = write_file(tmp_path, "offer_id,destination\nSOL-COR-914, cordoba \n")
    record = read_csv(path, ["offer_id", "destination"])[0]
    assert record.fields["destination"] == " cordoba "


def test_accented_characters_are_preserved(tmp_path):
    path = write_file(tmp_path, "offer_id,destination\nSOL-COR-915,Córdoba\n")
    assert read_csv(path, ["offer_id", "destination"])[0].fields["destination"] == "Córdoba"


def test_file_saved_by_excel_with_byte_order_mark_is_read(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur\nSOL-MAL-001,32.07\n", encoding="utf-8-sig")
    assert read_csv(path, COLUMNS)[0].fields["offer_id"] == "SOL-MAL-001"


def test_extra_columns_are_kept(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur,note\nSOL-MAL-001,32.07,hello\n")
    assert read_csv(path, COLUMNS)[0].fields["note"] == "hello"


def test_empty_value_is_read_as_empty_text(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur\nSOL-COR-901,\n")
    assert read_csv(path, COLUMNS)[0].fields["price_eur"] == ""


def test_short_row_gives_empty_text_for_missing_values(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur\nSOL-COR-901\n")
    assert read_csv(path, COLUMNS)[0].fields["price_eur"] == ""


def test_file_with_only_a_header_gives_no_records(tmp_path):
    path = write_file(tmp_path, "offer_id,price_eur\n")
    assert read_csv(path, COLUMNS) == []


def test_missing_required_column_raises(tmp_path):
    path = write_file(tmp_path, "offer_id\nSOL-MAL-001\n")
    with pytest.raises(MissingFieldError, match="price_eur"):
        read_csv(path, COLUMNS)


def test_empty_file_raises_missing_columns(tmp_path):
    path = write_file(tmp_path, "")
    with pytest.raises(MissingFieldError):
        read_csv(path, COLUMNS)


def test_missing_file_raises_data_error(tmp_path):
    with pytest.raises(DataError, match="Cannot read"):
        read_csv(tmp_path / "does_not_exist.csv", COLUMNS)


def test_real_offers_file_has_all_generated_and_edge_case_records():
    records = read_csv(DATA_DIR / "offers.csv", ["offer_id"])
    assert len(records) == 245
    assert records[0].fields["offer_id"] == "SOL-BAR-001"
    assert records[-1].fields["offer_id"] == "SOL-COR-920"


def test_real_reference_files_have_expected_sizes():
    assert len(read_csv(DATA_DIR / "companies.csv", ["code", "name"])) == 5
    assert len(read_csv(DATA_DIR / "destinations.csv", ["code", "name"])) == 15