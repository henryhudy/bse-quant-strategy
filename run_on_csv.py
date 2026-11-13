"""Read permitted A-F CSV files and write decisions for the next session open."""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from strategy import ALL_ASSETS, TRADED_ASSETS, Strategy


def read_history(directory: Path) -> list[tuple[date, dict]]:
    panels = {}
    for asset in TRADED_ASSETS:
        path = directory / f"{asset}.csv"
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            if not {"Date", "Open"} <= fields or not ({"Close", "Close/Last"} & fields):
                raise ValueError(f"{path} needs Date, Open and Close or Close/Last")
            panel = {}
            for row in reader:
                day = date.fromisoformat(row["Date"].strip())
                if day in panel:
                    raise ValueError(f"Duplicate date {day} in {path}")
                panel[day] = row
        if not panel:
            raise ValueError(f"No observations in {path}")
        panels[asset] = panel
    dates = sorted(panels[TRADED_ASSETS[0]])
    if any(set(panel) != set(dates) for panel in panels.values()):
        raise ValueError("All six assets must have exactly matching dates")
    return [(day, {asset: panels[asset][day] for asset in TRADED_ASSETS}) for day in dates]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("allocations.csv"))
    args = parser.parse_args()
    history = read_history(args.data_dir)
    strategy = Strategy()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("Decision_Date", *ALL_ASSETS))
        writer.writeheader()
        for day, rows in history:
            writer.writerow({"Decision_Date": day.isoformat(), **strategy.on_day_close(rows)})
    print(f"Wrote {len(history)} next-open decisions to {args.output}")


if __name__ == "__main__":
    main()
