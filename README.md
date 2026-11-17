# BusBidder Spain

A command-line Python application that filters, ranks and explains bus offers from Madrid to 15 destinations, based on a travellers requirements and preferences. It also supports simulated bookings.

Final project for ACIT4420 Problem-solving with scripting (2026).

## Requirements

- **Python 3.11 or newer** (developed and tested with Python 3.14.7 on Windows 11)
- **Libraries:** the application uses only the Python standard library. `pytest` is needed to run the tests.
- All dependencies are listed in `requirements.txt`.

## Setup

Run these commands from the folder where you want the project.

```bash
git clone https://github.com/AndreStaalesen/busbidder-spain.git
cd busbidder-spain
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

This installs `pytest` and installs the project itself in editable mode (the `-e .` line), so the `busbidder` package can be run from anywhere.

On Windows, if activation fails with "running scripts is disabled on this system", run this once and try again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## Running the application

**Entry point:** `python -m busbidder` (runs `src/busbidder/__main__.py`, which calls `main()` in `src/busbidder/cli.py`).
After installation, the shorter command `busbidder` does the same.

### Interactive menu

```bash
python -m busbidder
```

The menu lets you search and rank offers, book an offer, look up a booking and list the traveller profiles.

### One-off ranking with arguments

```bash
python -m busbidder --profile budget --destination Malaga --from 2027-07-12 --to 2027-07-14
```

| Option | Meaning |
|---|---|
| `--profile` | Traveller profile: `budget`, `business`, `flexible` or `eco` |
| `--destination` | Destination name or code, e.g. `Malaga` or `MAL` |
| `--from` | Earliest departure date (YYYY-MM-DD) |
| `--to` | Latest departure date (default: same as `--from`) |
| `--weights` | Replace the profile's weights, e.g. `price=50,duration=50` (must total 100) |
| `--top` | Followed by a number, will show only the first (x) offers |
| `--output` | Also save the result to a file |
| `--ignore-bookings` | Use the seat counts in `offers.csv` and ignore stored bookings (gives reproducible results) |

Show all options with `python -m busbidder --help`.

The offers in the dataset depart between **12 and 14 July 2027**.

## Running the tests

```bash
python -m pytest
```

Expected result: `336 passed`. Add `-v` to list every test by name.

## Input files

| File | Contents |
|---|---|
| `data/companies.csv` | The 5 bus companies (code, name, description) |
| `data/destinations.csv` | The 15 destinations (code, name, distance from Madrid in km, coastal) |
| `data/offers.csv` | 245 offer records: 225 generated offers and 20 deliberately invalid or unusual records used to test validation |
| `config/profiles.json` | The traveller profiles: weights, preferred departure window and hard limits |

The program reads these files from the project folder, so it can be started from any working directory.

## Files written by the program

| File | Contents |
|---|---|
| `logs/busbidder.log` | Log of each run: validation decisions, filtering, ranking and bookings |
| `logs/quarantine.csv` | Suspicious records set aside for review, with the reason |
| `bookings/bookings.json` | Saved bookings. `offers.csv` is never changed; stored bookings are subtracted from the seat counts when the program starts |

These folders are not committed to Git. Example copies are in `outputs/`.

## Reproducing the data and the results

The dataset was created by a script with a fixed random seed, so it can be regenerated exactly:

```bash
python scripts/generate_data.py
```

All results used in the report are produced by:

```bash
python scripts/run_experiments.py
```

This writes the experiment results to `outputs/` (summary in `outputs/experiments.md`, one CSV file per table). It ignores stored bookings, so the results are the same on every run.

To check that the files match the original ones:

| File | MD5 hash |
|---|---|
| `data/offers.csv` | `66a248c57b93cc8f9e4290bee98fa599` |
| `outputs/experiments.md` | `581c6a44dbc78a5a0dd8e8f1814852b0` |

```powershell
# Windows
Get-FileHash -Algorithm MD5 data\offers.csv
```

```bash
# macOS / Linux
md5sum data/offers.csv
```

## Project layout

| Path | Contents |
|---|---|
| `src/busbidder/` | Application source code |
| `tests/` | Automated tests (pytest) |
| `data/` | Input data |
| `config/` | Traveller profiles |
| `scripts/` | Data generator and experiment script |
| `outputs/` | Experiment results and example output (session, log, booking) |
| `docs/diagrams/` | Architecture and class diagrams (Mermaid) |

### Source modules

| Module | Responsibility |
|---|---|
| `models.py` | Data classes: Company, Destination, FareConditions, Offer |
| `exceptions.py` | Custom error classes |
| `loader.py` | Reads CSV files |
| `validation.py` | Validates records: reject, correct or quarantine |
| `profiles.py` | Traveller profiles, weights and travel requests |
| `constraints.py` | Hard constraints that remove offers before ranking |
| `criteria.py` | Scoring criteria and the criterion registry |
| `ranking.py` | Weighted ranking and tie-breaking |
| `explain.py` | Generated explanations for each ranked offer |
| `booking.py` | Simulated bookings |
| `logging_setup.py` | Log file configuration |
| `cli.py` | Interactive menu and command-line arguments |
| `__main__.py` | Entry point for `python -m busbidder` |