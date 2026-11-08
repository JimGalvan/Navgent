"""Write the RP-214 text to paste into Reprobe's New screen, dated for the seeded week.

The seed puts Product Sprint Review on the Tuesday of the week after the seed date.
Use the Tuesday you see on RoomPilot's calendar.

Usage: python video/tools/ticket_text.py 2026-11-17 [--out video/part-2/PASTE.md]
"""

import argparse
from datetime import date, timedelta
from pathlib import Path

APP_URL = "https://roompilot-production.up.railway.app"


def month_day(day: date) -> str:
    return f"{day.strftime('%B')} {day.day}"


def full_date(day: date) -> str:
    return f"{month_day(day)}, {day.year}"


def build_text(tuesday: date) -> str:
    monday = tuesday - timedelta(days=1)
    sunday = tuesday + timedelta(days=5)
    week = f"{month_day(monday)} to {full_date(sunday)}"

    steps = [
        "Sign in as the demo admin account.",
        f"Open Calendar, select Conference Room A, and go to {week}. "
        f"Confirm Product Sprint Review appears only on {month_day(tuesday)} at 10:00 AM to 11:00 AM.",
        'Open Reservations and search for "Product Sprint Review".',
        "Open Jordan Lee's reservation and click Edit Reservation.",
        f"Keep the date {full_date(tuesday)}. Change the start to 1:00 PM and end to 2:00 PM, then click Save changes.",
        "Check the details page. It shows 1:00 PM to 2:00 PM and a successful update message.",
        f"Open Calendar for Conference Room A and the week of {week}.",
        f"Check Tuesday, {month_day(tuesday)}, then refresh the page.",
    ]
    numbered = ""
    for index, step in enumerate(steps, start=1):
        numbered += f"{index}. {step}\n"

    expected = (
        "Product Sprint Review appears only at 1:00 PM to 2:00 PM. "
        "Its original 10:00 AM to 11:00 AM slot is available."
    )
    actual = (
        "The details show 1:00 PM to 2:00 PM. The calendar shows Product Sprint Review twice: "
        "at 10:00 AM and at 1:00 PM. Both remain after a refresh."
    )

    return (
        f"# RP-214 paste sheet (meeting on {tuesday.strftime('%A')}, {full_date(tuesday)})\n\n"
        "Paste each block into the matching field on Reprobe's New screen. Same text as the ticket view.\n\n"
        f"## Steps to reproduce\n\n```text\n{numbered}```\n\n"
        f"## Expected\n\n```text\n{expected}\n```\n\n"
        f"## Actual\n\n```text\n{actual}\n```\n\n"
        f"## App URL\n\n```text\n{APP_URL}\n```\n\n"
        "## Credentials\n\nLeave the saved RoomPilot credential selected. Don't type anything.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tuesday", help="the meeting's Tuesday as YYYY-MM-DD")
    parser.add_argument("--out", default="video/part-2/PASTE.md")
    args = parser.parse_args()

    tuesday = date.fromisoformat(args.tuesday)
    if tuesday.weekday() != 1:
        raise SystemExit(f"{args.tuesday} is not a Tuesday")
    out = Path(args.out)
    out.write_text(build_text(tuesday), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
