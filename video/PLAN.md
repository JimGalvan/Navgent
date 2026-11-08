# Reprobe demo video: plan (draft 2)

Hackathon entry. Target length about 4:00, minimum 3:00. It's built and reviewed one part at a time (see "Parts"). Video and audio files stay out of git.

## Settled

| Topic | Decision |
|---|---|
| Story | One bug (RP-214, RoomPilot), checked twice by Reprobe: before the fix and after it. |
| Repeated work | A short beat in Part 1 names the two checks people redo by hand, "Is it still happening?" and "Did the fix work?" Those two labels then become the chapter markers for Reprobe's two runs. |
| Focus | The product. No implementation or technical detail about Reprobe, no models or infrastructure, no repository. The sandbox appears as a product benefit, in plain words. |
| Bug document | RP-214, shown in a clean, unbranded ticket view. Reprobe gets the same text the viewer sees. Dates come from the seeded week on recording day. |
| Voice | Your ElevenLabs clone `CzlzlG52P2Tvaktl7R52`. "Reprobe" is said "REE-probe". |
| RoomPilot framing | Presented as Northstar Workspace's internal booking tool, the world the video happens in. The narration doesn't say it was built for the demo or that the bug was planted. Part 1 is approved apart from that change. |
| Facecam | None. |
| Ending | A text end card, no link. |
| Environment | The live Reprobe. The RoomPilot credential is already saved there, so on camera we only fill in the bug details. RoomPilot's styling loads correctly in the sandbox now, because Reprobe allows a fixed list of public CDNs for page assets. |
| QA's recording as evidence | Only if time allows, and the clip must be under 2 minutes. Not in the base plan. |

## The story

**Problem → uncertainty → investigation → evidence → fix → verification → resolution.**

A meeting shows up twice on a calendar. QA filed it. Checking it by hand means walking the same eight steps once to see if it's real, and again after the fix. Reprobe does both checks from the ticket. The first comes back *Reproduced*, with proof. A small code change follows. The second check comes back *Not reproduced*, and the bug's run history shows both results side by side.

**What people should remember:** one bug, two checks, opposite results, and nobody clicked through the steps.

**Tone:** a developer showing a colleague something they built. Calm, specific, a little dry. Sure about what's on screen and modest about what it proves.

## Parts

Each part is built (script, visuals, voice, rough cut) and reviewed before the next one starts.

| Part | Time | Content | Ends on |
|---|---|---|---|
| **1. The problem** | 0:00–0:59 | Hook on the duplicate meeting, the ticket, the two checks people repeat by hand, what Reprobe is, RoomPilot and Northstar as context | "Let's see if Reprobe can find it." |
| **2. Check 1: is it still happening?** | 0:59–2:20 | Filling in the bug on the New screen, the plan built from the ticket, a plain sandbox line, the sign-in at real speed as the credential containment moment (fields fill with dots, then the "where the saved login lives" picture), then the rest of the run (sped up and labeled) | The agent reaching the calendar |
| **3. The proof** | 1:55–2:25 | Reproduced verdict, the finding frame with the 10 AM block marked, expected vs. observed, the throwaway browser gone | "Now I have a check I can repeat." |
| **4. The fix** | 2:25–2:50 | One small diff in RoomPilot and one sentence on the cause, then a cut through the deploy | Deploy done |
| **5. Check 2: did the fix work?** | 2:50–3:45 | Run again with the same bug, a short retest, *Not reproduced*, the final frame with 10 AM free, the run history | Run history: Reproduced → Not reproduced |
| **6. Close** | 3:45–4:05 | Honest scope, one-click rerun for next time, the QA-comment callback, text end card | End card |

### Where the repeated-work idea pays off

- **Part 1** introduces two labels on screen: **Check 1 · Is it still happening?** and **Check 2 · Did the fix work?**
- **Part 2** opens with the Check 1 label, and **Part 5** opens with the Check 2 label. Same style, same position, so the viewer feels the structure without being told.
- **Part 6** adds the third, ongoing case in one line: when someone touches the calendar code later, the same check is one click away (Run again). We say it; we don't show a third run.

## Part notes (parts 2–6, to be detailed when we reach them)

**Part 2.** Detailed in `part-2/` (SCRIPT, RECORDING, PASTE). Summary: the New screen gets the steps, expected, actual and URL pasted in. The saved RoomPilot credential appears in the picker once the URL is in, with its value never shown. Line: "Exactly what QA wrote. No hints about where the bug is." In the Live screen, the Plan panel fills in and each step shows where it came from. The run is sped up with a visible "3×" label, dropping to real speed when the times change and when the calendar loads. Sandbox line, product-level only: "It runs in a fresh browser that's thrown away when it's done." No runtimes or firewall talk.

**Part 3.** Hold about 2 s on the *Reproduced* badge with no voice. Then the finding frame, the Checks row, and one credibility line: "What it reports as observed has to actually be on the page." Then the cleanup state in the Sandbox panel.

**Part 4.** Editor with the diff only, about 8 s. Cause in one sentence: "Rescheduling added a new calendar entry and never moved the old one." Then a cut through the deploy, with a small "deploy · about 2 min" label. No unit-test shot, to keep the focus on the product.

**Part 5.** Report → **Run again** → same bug. About 20 s sped up, then real speed at the calendar. *Not reproduced*, hold, final frame, run history. Line: "Ten o'clock's free."

**Part 6.** "That's one path, the way QA hit it. It doesn't mean rescheduling is bug-free. But this one's fixed, and the check's still here, one click, next time someone touches the calendar." Then the QA lead's comment, "Keep this in the reservation regression checks", and a text end card: **Reprobe**, plus "Reproduce the bug. Verify the fix."

## Production rules (all parts)

- Footage first, voice written to the footage, then generated one part at a time.
- Real product footage only. Sped-up segments are labeled. No fake dashboards.
- About 25–30% of the runtime has no voice: the live runs, both verdicts, the deploy cut.
- One highlight style: a thin rounded outline, one accent color, 200 ms fade. Straight cuts.
- Music is optional and very quiet, and it drops out under both verdicts.
- Hand-checked captions.
- Both Reprobe runs, the fix deploy, and every RoomPilot shot with a date in it are captured **within one Monday–Sunday week**. Each deploy reseeds, and the seed's Tuesday moves when the week rolls over. See `part-2/RECORDING.md`. The drafts can use earlier footage. The captures are scripted where possible, so they're cheap to redo on recording day.
- Dry runs happen on a separate Reprobe account, so the filmed bug's run history shows only the two real runs.
- Check every frame for the RoomPilot password before export.

## Research summary (from draft 1)

I applied all six references. Storykit: open on a recognizable problem, ask a question the video answers, rule of one, cut words. Vidyard: one story, show don't tell. Wyzowl: problem → solution → benefit, show real software, answer the viewer's obvious questions. Clipchamp: problem in the first 30 s, trim dead time. Where these articles recommend flashy transitions, upbeat music or animated overlays, I followed your brief instead.

## Risks to watch

- **The first live run is the likeliest place to lose people.** Vary the speed, cut to the Plan and Form state panels, and slow down only at the moments that matter.
- **The retest can feel like a rerun.** Keep it short and spend its time on the 10 AM slot.
- **"Not reproduced" is an absence.** If Reprobe's final frame doesn't show it clearly, cut to a RoomPilot calendar capture, clearly labeled.
- **The run on the live deployment hasn't been checked yet.** Run time and the wording of the post-fix verdict need a dry run on the separate account.
