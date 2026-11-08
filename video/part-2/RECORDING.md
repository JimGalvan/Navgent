# Recording Check 1 (footage for Parts 2 and 3)

One continuous recording of the live Reprobe, from the empty New screen to the finished report. The cuts happen in editing. The dry run (`DRY-RUN.md`) proved the setup. This is the version for the real take.

## The date rule (read first)

RoomPilot's seed puts Product Sprint Review on **the Tuesday of the week after the seed date**, and every deploy reseeds. So **Check 1, the fix deploy, and Check 2 must all happen in the same Monday–Sunday week.**

- Today (Sunday, November 8) means doing everything today: Check 1, the fix deploy and Check 2, with the meeting on November 10. The paste sheet and Part 1 already use those dates.
- Any day from Monday, November 9 through Sunday, November 15 means the meeting is on November 17. Regenerate the paste sheet and Part 1 first (commands below).
- Railway's clock is probably UTC. Avoid reseeding near midnight UTC.

## Who does what

| Step | You | Me |
|---|---|---|
| Reseed RoomPilot and confirm the meeting appears only at 10–11 AM | ✓ | |
| Recording window (fullscreen, exactly 1920×1080, signed in) | | ✓ already open |
| Start the recorder | | ✓ |
| Paste the four fields and click **Start reproduction** | ✓ (about 20 s, at a normal pace) | |
| During the run: two short scrolls, to the Sandbox panel (opened, showing limits) and to Form state, then back up | | ✓ triggered by the run's events |
| Hands off during the run | ✓ | |
| Report walk: verdict → Finding frame → Checks → Sandbox details opened → back to top | | ✓ |
| Stop the recorder, build the MP4, save the WebM and run record, log the timestamps | | ✓ |

## Commands (mine, for reference)

```bash
.venv/Scripts/python.exe video/tools/ticket_text.py 2026-11-17
```
```bash
.venv/Scripts/python.exe video/tools/recorder.py record <scratch>/check-1
```
```bash
.venv/Scripts/python.exe video/tools/take.py live video/footage/check-1/events.jsonl
```
```bash
.venv/Scripts/python.exe video/tools/take.py report
```
```bash
.venv/Scripts/python.exe video/tools/recorder.py build <scratch>/check-1 video/footage/check-1/check-1.mp4
```

The first command is only needed for a Monday–Sunday recording. `take.py live` waits for your click on Start reproduction, so start it before you paste.

## Known from the dry run

- The run takes about 51 s. Sign-in is at about 9 s, the times are set at about 42 s, and the calendar loads at about 47 s.
- The login fields fill with dots, and no password or login email appears anywhere.
- The title reads "1. Sign in as the demo admin account." We're keeping that.
- "Recent runs" on the New screen and the account email in the header get cropped or blurred in the edit.

## After the take

Leave the report open: Check 2 starts from its **Run again** button after the fix is deployed.
