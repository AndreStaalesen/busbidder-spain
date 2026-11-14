import argparse
import json
from dataclasses import replace

import pytest

from busbidder.cli import (
    BusBidderApp,
    InteractiveMenu,
    Paths,
    main,
    parse_weights,
    render_booking,
)


@pytest.fixture
def paths(tmp_path) -> Paths:
    return replace(Paths(), bookings=tmp_path / "bookings.json", log=tmp_path / "busbidder.log",
                   quarantine=tmp_path / "quarantine.csv")


def run_menu(paths: Paths, answers: list[str]) -> str:
    remaining = iter(answers)
    printed: list[str] = []

    def read(prompt: str) -> str:
        printed.append(prompt)
        return next(remaining)

    InteractiveMenu(BusBidderApp(paths), read=read, write=printed.append).run()
    return "\n".join(printed)


MALAGA_ARGS = ["--destination", "Malaga", "--from", "2027-07-12", "--to", "2027-07-14", "--ignore-bookings"]



@pytest.mark.parametrize("profile, winner", [
    ("budget", "#1 SOL-MAL-003"), ("business", "#1 COS-MAL-003"),
    ("flexible", "#1 VER-MAL-003"), ("eco", "#1 VER-MAL-002"),
])
def test_argument_mode_ranks_for_the_chosen_profile(paths, capsys, profile, winner):
    assert main(["--profile", profile, *MALAGA_ARGS], paths=paths) == 0
    assert winner in capsys.readouterr().out


def test_output_shows_hard_constraints_and_preferences_separately(paths, capsys):
    main(["--profile", "budget", *MALAGA_ARGS], paths=paths)
    out = capsys.readouterr().out
    assert "Hard constraints - offers that fail these are NOT ranked:" in out
    assert "  - price at most EUR 40.00" in out
    assert "Preferences - used only to rank the remaining offers:" in out
    assert "not an objectively best offer" in out
    assert "Removed by your limits:" in out


def test_output_can_be_saved_to_a_file(paths, tmp_path, capsys):
    output = tmp_path / "results" / "budget.txt"
    main(["--profile", "budget", *MALAGA_ARGS, "--output", str(output)], paths=paths)
    assert output.read_text(encoding="utf-8") in capsys.readouterr().out


def test_same_command_gives_identical_output(paths, tmp_path):
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    main(["--profile", "eco", *MALAGA_ARGS, "--output", str(first)], paths=paths)
    main(["--profile", "eco", *MALAGA_ARGS, "--output", str(second)], paths=paths)
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_weights_option_replaces_the_profile_weights(paths, capsys):
    main(["--profile", "eco", *MALAGA_ARGS, "--weights", "price=100"], paths=paths)
    out = capsys.readouterr().out
    assert "Eco-conscious traveller (custom weights)" in out
    assert "price 100%" in out


def test_top_limits_the_number_of_offers_shown(paths, capsys):
    main(["--profile", "eco", *MALAGA_ARGS, "--top", "2"], paths=paths)
    out = capsys.readouterr().out
    assert "#2 " in out and "#3 " not in out
    assert "(12 more offers not shown)" in out


def test_no_matching_offers_is_explained(paths, capsys):
    main(["--profile", "eco", "--destination", "Malaga", "--from", "2027-08-01"], paths=paths)
    assert "No offers to Malaga depart in that period." in capsys.readouterr().out


def test_when_limits_remove_everything_the_most_restrictive_limit_is_named(paths, capsys):
    main(["--profile", "business", "--destination", "Cadiz", "--from", "2027-07-12",
          "--to", "2027-07-14", "--ignore-bookings"], paths=paths)
    out = capsys.readouterr().out
    assert "No offers meet all your requirements." in out
    assert "14 removed by your limits (9 duration, 5 transfers)" in out
    assert "The limit that removed most offers is 'duration' (14 offers)" in out




@pytest.mark.parametrize("arguments, message", [
    (["--profile", "student", "--destination", "Malaga", "--from", "2027-07-12"], "No profile called 'student'"),
    (["--profile", "eco", "--destination", "Paris", "--from", "2027-07-12"], "Unknown destination 'Paris'"),
    (["--profile", "eco", "--destination", "Malaga"], "Missing --from"),
    (["--profile", "eco", "--destination", "Malaga", "--from", "2027-07-14", "--to", "2027-07-12"],
     "before earliest date"),
    (["--profile", "eco", "--destination", "Malaga", "--from", "2027-07-12", "--weights", "price=90"],
     "must total exactly 100%"),
    (["--profile", "eco", "--destination", "Malaga", "--from", "2027-07-12", "--weights", "speed=100"],
     "Unknown criteria: speed"),
])
def test_user_errors_give_a_message_and_exit_code_1(paths, capsys, arguments, message):
    assert main(arguments, paths=paths) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [
    ["--from", "2027-13-01"], ["--from", "12/07/2027"], ["--top", "0"], ["--weights", "price"],
])
def test_badly_formatted_arguments_are_rejected_by_argparse(paths, arguments):
    with pytest.raises(SystemExit) as stopped:
        main(arguments, paths=paths)
    assert stopped.value.code == 2


def test_parse_weights():
    assert parse_weights("price=50, duration=50") == {"price": 50.0, "duration": 50.0}
    with pytest.raises(argparse.ArgumentTypeError):
        parse_weights("price=lots")


def test_errors_are_written_to_the_log(paths, capsys):
    main(["--profile", "student", "--destination", "Malaga", "--from", "2027-07-12"], paths=paths)
    log = paths.log.read_text(encoding="utf-8")
    assert "Started in argument mode" in log
    assert "Stopped: No profile called 'student'" in log


def test_quarantined_records_are_written_for_review(paths):
    main(["--profile", "eco", *MALAGA_ARGS], paths=paths)
    assert "SOL-COR-917" in paths.quarantine.read_text(encoding="utf-8")






def test_search_and_book_in_the_menu(paths):
    out = run_menu(paths, [
        "1", "Malaga", "2027-07-12", "2027-07-14", "1",
        "1", "Ana Garcia",
        "q",
    ])
    assert "#1 SOL-MAL-003" in out
    assert "Booking confirmed (simulated - no payment taken)." in out
    stored = json.loads(paths.bookings.read_text(encoding="utf-8"))
    assert stored[0]["offer_id"] == "SOL-MAL-003"
    assert stored[0]["traveller_name"] == "Ana Garcia"


def test_menu_asks_again_after_invalid_answers(paths):
    out = run_menu(paths, [
        "7",
        "1", "Paris", "malaga",
        "12.07.2027", "2027-07-12", "",
        "9", "eco",
        "",
        "q",
    ])
    assert "Please choose 1, 2, 3 or q." in out
    assert "Unknown destination 'Paris'" in out
    assert "is not a date in the format YYYY-MM-DD" in out
    assert "No profile called '9'" in out
    assert "Eco-conscious traveller (eco)" in out


def test_invalid_name_is_rejected_and_empty_name_cancels(paths):
    out = run_menu(paths, ["1", "Malaga", "2027-07-12", "", "1", "1", "R2D2", "", "q"])
    assert "Name may only contain letters" in out
    assert "Booking cancelled." in out
    assert not paths.bookings.exists()


def test_custom_profile_in_the_menu(paths):
    out = run_menu(paths, [
        "1", "Malaga", "2027-07-12", "2027-07-14", "c",
        "evening",
        "50", "50", "0", "0", "10",
        "", "", "", "n", "n",
        "50", "50", "0", "0", "0",
        "35", "", "", "n", "n",
        "",
        "q",
    ])
    assert "Weights total 110%, but must total exactly 100%. Please try again." in out
    assert "Profile:  Custom profile (custom)" in out
    assert "  - price at most EUR 35.00" in out


def test_view_booking_in_the_menu(paths):
    run_menu(paths, ["1", "Malaga", "2027-07-12", "", "1", "1", "Ana Garcia", "q"])
    reference = json.loads(paths.bookings.read_text(encoding="utf-8"))[0]["reference"]

    out = run_menu(paths, ["2", "not-a-reference", reference.lower(), "2", "BB-SOL-ZZZZZZ", "q"])
    assert "A booking reference looks like BB-SOL-7K3Q9X" in out
    assert f"Booking reference: {reference}" in out
    assert "No booking with that reference." in out


def test_bookings_reduce_seats_in_the_next_session(paths):
    app = BusBidderApp(paths)
    seats_before = next(o for o in app.offers if o.offer_id == "SOL-MAL-003").seats_available
    run_menu(paths, ["1", "Malaga", "2027-07-12", "2027-07-14", "1", "1", "Ana Garcia", "q"])

    reopened = BusBidderApp(paths)
    assert next(o for o in reopened.offers if o.offer_id == "SOL-MAL-003").seats_available == seats_before - 1
    ignored = BusBidderApp(paths, use_bookings=False)
    assert next(o for o in ignored.offers if o.offer_id == "SOL-MAL-003").seats_available == seats_before


def test_list_profiles_shows_preferences_and_hard_limits(paths):
    out = run_menu(paths, ["3", "q"])
    assert "Hard limits: at most 0 transfers, journey at most 7h 00m, changeable ticket required" in out
    assert "Hard limits: refundable ticket required" in out


def test_booking_confirmation_text(paths):
    app = BusBidderApp(paths)
    offer = next(o for o in app.offers if o.offer_id == "VER-MAL-002")
    text = render_booking(app.bookings.book(offer, "André Smurfu"))
    assert "Traveller:   André Smurfu" in text
    assert "Conditions:  changeable, refundable, 1 checked bag" in text
    assert "Payment:     simulated - no payment taken" in text