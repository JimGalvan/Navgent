# Dry run, November 8 (run 7E1E5B39)

Recorded with `video/tools/recorder.py` on the live Reprobe, account galvanjim@gmail.com, right after a fresh RoomPilot seed (meeting on Tuesday, November 10, 10:00–11:00 AM only). The footage is in `video/footage/dry-run/` and stays out of git.

## Result

- **Reproduced in 51 s**, including starting and destroying the sandbox.
- Observed (step 9): "Product Sprint Review Jordan Lee 10:00 AM – 11:00 AM" and "Product Sprint Review Jordan Lee 1:00 PM – 2:00 PM".
- The Checks row says "count how many times Product Sprint Review appears on Tuesday, November 10" → Reproduced, step 9.
- Sandbox lifecycle: Starting (2 s) → Running (4 s) → Destroyed (52 s).

## Timeline (seconds after clicking Start)

| Time | What's on screen | Script beat |
|---|---|---|
| 0.6 | Live screen, "Connecting" | 2C starts |
| 2.1 | Plan fills in (9 items), sandbox Starting | 2C (P3) |
| 3.7 | Running, sandbox Running | 2D (P4) |
| ~8–10 | RoomPilot login. `fill_credential · Email`, then `· Password`, both fields show **dots** | 2E (P7 + picture) |
| 34.8 | Form state: "Search reservations: Product Sprint Review" | 2F, 3× |
| 41.5 | Form state: Start 1:00 PM, End 11:00 AM (mid-edit) | real speed |
| 42.0 | Form state: Start 1:00 PM, End 2:00 PM | P6 lands here |
| 47.1 | Calendar, Conference Room A, week of Nov 9 | real speed, end of Part 2 |
| 51.7 | Completed, verdict block, sandbox Destroyed | Part 3 |

## Containment checks

- **The password appears nowhere:** not in the report page, the run data or the full event log (27 KB). **The login email doesn't appear either.**
- The agent's log shows only `fill_credential · Email` and `fill_credential · Password`, with no values.
- **Both login fields fill with dots in the live frame** (see `signin-masked-zoom.png`). The label under the frame reads `fill_credential · Email · step 1`, which is a good thing to keep in the shot.

## What changes for the real take

1. **Form state and the Sandbox panel are below the fold** on the Live screen, even at 67% zoom. Plan: keep 100% zoom for sharpness. During the run, the recorder script does two short smooth scrolls, triggered by the run's own events: down to the Sandbox panel when it turns Running, and down to Form state when the times are set. It scrolls back up each time before the next thing to watch.
2. **The page title is "1. Sign in as the demo admin account."** on the Live screen, the report and Recent runs, because Reprobe titles a run from the first line of its steps. **Needs a decision** (see below).
3. **In the report, the Sandbox section is a collapsed row**, "Sandbox · Destroyed". The take should click it open so the runtime, limits and allowed host show.
4. **The finding frame's red label sits on the 1:00 PM block**, not the stale 10:00 AM one. Both blocks are visible, and our own outline in the edit points at both.
5. **The New screen shows "Recent runs"** at the bottom, including an earlier "Reproduced" run of this bug, and the header shows galvanjim@gmail.com. Crop or blur both in the edit.
6. The live frame is about 820 px wide, so the dots are readable but soft when zoomed. Reprobe's own WebM of the tab is the sharper source for the sign-in close-up.
7. The run is fast (51 s), so Part 2's 3× sections can be short, and P5/P6 may barely fit. We'll time them to the real take.

## Decision needed: the run's title

Options:
- **A. Add a one-line summary as the first line of Steps**, e.g. "RP-214: Rescheduling Product Sprint Review leaves the meeting in both calendar slots." It's cheap, but it changes the input, so it needs one more dry run (51 s plus a reseed).
- **B. Leave it.** The title reads like a step, which looks odd on the Live screen, the report header and the run history.
- **C. Change Reprobe** to take a title from somewhere better. That's a product change, outside the video work.
