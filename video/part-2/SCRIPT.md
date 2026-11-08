# Part 2: Check 1, is it still happening? (0:59–2:20)

**Job of this part:** hand Reprobe the ticket exactly as QA wrote it, show that it plans from the ticket, mention the throwaway browser in plain words, and let the run play. It ends as the agent reaches the calendar, and Part 3 opens on the verdict.

**Footage:** one continuous screen recording on the live Reprobe, from the empty New screen to the finished report. Parts 2 and 3 are cut from the same take (see `RECORDING.md`). Voice timings get adjusted to the real footage. Times below are estimates.

## Shots

| # | Time in part | Visual | Voice | On screen |
|---|---|---|---|---|
| 2A | 0:00–0:03 | **Check 1** card over the first frame of the New screen, dimmed. Same card as Part 1, alone, centered. | — (silent) | Check 1 · Is it still happening? |
| 2B | 0:03–0:20 | New screen. Paste the steps, then Expected, Actual and the App URL. Typing and pasting are trimmed to about a second each. Once the URL is in, the saved RoomPilot credential appears in the picker (name and domain only). Click **Start reproduction**. | **P1** "I'm pasting in exactly what QA wrote. Nothing about where the bug might be." **P2** (as the credential appears) "The test login's already saved, encrypted, and it only shows up because the link matches." | Outline on the credential row. *Optional insert (2.5 s):* the Manage credentials drawer showing the RoomPilot entry with its value hidden and its allowed domain, captured separately. |
| 2C | 0:20–0:32 | Live screen. The Plan panel fills in. Zoom on 2–3 plan items showing their source (for example "written step 5"). Click one so "Why, step N" opens. | **P3** "Before it touches the browser, it turns the ticket into a plan, and every step says where it came from." | Zoom only |
| 2D | 0:32–0:40 | Zoom on the Sandbox panel showing **Running** and the allowed host. | **P4** "The browser it's using is brand new, and it gets thrown away when the run's over." | Outline on the status |
| 2E | 0:40–0:56 | **Sign-in at real speed (the credential containment moment).** The live frame shows RoomPilot's login page, and the agent fills the fields with **dots, not the value** (about 2 s, slight zoom). Then the **"Where the saved login lives"** picture fades in over the dimmed footage and holds about 9 s, before fading back to the run. | **P7** "The login stays encrypted on Reprobe's server, not in the sandbox. The AI only asks for it by name. Reprobe types it in, on this site only, and the AI never sees it." | "real speed" label, then the picture: **AI agent** (gets the name only) → *asks for it by name* → **Reprobe server** (encrypted, key kept apart) → *types it in, this site only* → **Sandbox browser** (masked fields, nothing saved, destroyed after the run) |
| 2F | 0:51–1:16 | The rest of the run. **3×** with a corner label through search and opening the reservation. **Real speed** when the times are typed and Form state shows 1:00 PM / 2:00 PM. 3× through saving and the details page. **Real speed** again as it opens the Calendar, picks Conference Room A and lands on the right week. Cut on the calendar, with both blocks visible in the live frame. | **P5** (early, over 3×) "I'm not clicking any of this." **P6** (at the time fields, *only if Form state shows the values*) "It reads the times back after typing them, which is what I'd do too." Then nothing until the end of the part. | "3×" / "real speed" corner label |

Voice is about 37 s of the 81 s. The run still gets long stretches of silence after sign-in.

## Choices worth reviewing

- **The card is silent.** Part 1 already said "Check 1 · Is it still happening?" out loud. Here the card is enough, and it opens the part on a beat of quiet.
- **Credential containment shows where the login lives.** P2 plants "saved, encrypted" when the credential appears. The payoff is the sign-in at real speed (the fields fill with dots), followed by one picture: the login lives encrypted on Reprobe's server, the AI only ever handles its name, and the value goes out only as typing into the allowed site's field. Each part of the picture is backed by the code:
  - **Reprobe server, encrypted, key kept apart:** AES-256-GCM. The key is generated on the server and kept separately from the database. The database only holds the encrypted login, and deleting a credential wipes it.
  - **AI agent gets the name only:** the agent's credential list holds the name, allowed sites and which fields exist. The value is decrypted in the app at the moment of typing and never passes through the AI.
  - **Typed in, this site only:** the picker filters by host, a fill for any other host is refused, and the field must be on that site and focused before anything is typed.
  - **Sandbox browser, masked, nothing saved:** the field is masked before the value goes in and left out of later page reads. The container gets no keys, files or settings, and it's destroyed after the run.
- **The picture is an illustration, not a screenshot.** The name chip uses the credential's saved name (a render setting, default "RoomPilot test login"), and the encrypted string is a placeholder, not real ciphertext.
- **P4 is the whole sandbox story.** It says what a judge needs to hear (fresh browser, thrown away afterwards) and nothing about how. Part 3 pays it off when the panel reads **Destroyed**.
- **P6 is conditional.** If the real footage doesn't show the read-back clearly, we drop it rather than describe something viewers can't see.
- **The part ends before the verdict.** The calendar arriving in the live frame, both blocks visible, is the cliffhanger. Part 3 opens on the badge.
