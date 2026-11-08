# Part 1: The problem (0:00–0:59)

**Job of this part:** show the bug, name the work people repeat by hand, say what Reprobe is in one breath, and set up RoomPilot and Northstar as the world the rest of the video happens in. It ends on a question that Part 2 answers.

**Draft status:** a rough cut with the real voice. Two shots use stand-ins (marked **DRAFT**), to be replaced with recording-day captures.

## Shots

| # | Time | Visual | Voice | On screen |
|---|---|---|---|---|
| 1A | 0:00–0:08 | RoomPilot calendar, Conference Room A, Tuesday. Slow push-in toward the Tuesday column. An outline lands on the 10 AM block, then on the 1 PM block, each with its line. | **L1** "This meeting is booked at ten. It's also booked at one." *(beat)* "It's one meeting." | Outlines only |
| 1B | 0:08–0:18 | RP-214 ticket view: title, then the Expected and Actual cards outlined one after the other. | **L2** "Someone on QA filed this. You move a meeting to a new time, and its old slot stays booked." | Outlines only |
| 1C | 0:18–0:40 | Ticket steps highlight one by one, quickly, with no voice. The ticket dims and two labels appear one after the other: **Check 1 · Is it still happening?** and **Check 2 · Did the fix work?**, each tagged "8 steps · by hand". | **L3** "Checking that by hand means walking through all of this." *(steps tick, silent)* **L4** "And I'd do it twice. Once now, to find out if it's even still happening. And again after I fix it, to see if the fix actually worked." | The two check labels (these come back in Parts 2 and 5) |
| 1D | 0:35–0:46 | Reprobe New reproduction screen, empty, on the live app. | **L5** "Reprobe does those checks for me. I give it the bug report and a link, it opens a browser, follows the steps, and tells me whether the bug's there, with a recording to show for it." | — |
| 1E | 0:46–0:59 | RoomPilot's clean calendar, the whole page, with a slow push-in. "Northstar Workspace" in the sidebar is outlined as the name is spoken. | **L6** "RoomPilot is how everyone at Northstar books meeting rooms. If the calendar says a room's taken when it isn't, people just go book somewhere else. So… let's see if Reprobe can find it." | Outline on "Northstar Workspace" |

## Choices worth reviewing

- **No title card at the start.** The bug is the opening. The name "Reprobe" first appears at 1D, once the viewer knows what it's for.
- **The steps tick by without voice.** Reading eight steps aloud over a list of eight steps is exactly the "mirroring" the research warns against. The visual makes the "it's a lot of clicking" point by itself.
- **"Once now, to find out if it's even still happening."** This is the first repeated job: an unconfirmed bug. **"And again after I fix it."** This is the second: verifying the fix. The on-screen labels name them the same way, so Parts 2 and 5 can reuse them as chapter markers.
- **RoomPilot and Northstar appear as context, not as a disclosure.** The last line places the app in its fictional company and says why the bug matters there (a room that looks taken when it isn't). Then it hands off to Part 2. The ticket breadcrumb also reads "Northstar / RoomPilot / Issues", so the company is on screen before it's named.

## Stand-ins in this draft

| Shot | Draft source | Final source |
|---|---|---|
| 1A | `RoomPilot/demo/ticket/calendar-after.png`, QA's own attachment (1280 px, upscaled, so a little soft) | Fresh 1080p capture of the calendar after Reprobe's first run, on recording day |
| 1D | A slate | Your screen recording of the live Reprobe New screen (I can't sign in to it) |
| 1E | `RoomPilot/demo/ticket/calendar-before.png`, QA's clean-calendar attachment | Fresh 1080p capture of RoomPilot's calendar after the reseed, before any edit |

The ticket view (`ticket.html`) is final apart from its dates. On recording day it gets re-rendered with that day's seeded week.
