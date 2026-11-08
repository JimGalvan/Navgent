# Reprobe interface critique

Reviewed November 8, 2026. Scope: the desktop bug submission, live run, reports list, and saved report interfaces in `app/server/static`.

## Direction

Keep the current dark palette, restrained lime accent, typography, and verdict-first report structure. The strongest opportunity is to make the evidence explain the result and support the same bug through repeated tests on different environments.

The report's verdict → proof and steps → checks → supporting details hierarchy suits developer QA. Distinguishing submitted expectations from agent observations is particularly valuable. Status labels, clear primary actions, and visible keyboard focus provide a useful foundation.

## Approved implementation scope

The user selected the top three remaining fixes after excluding mobile:

1. **P1 — Explain the finding in the proof frame.** Display a frame from the finding's recorded moment, with the observation highlighted, its explanation, expected/observed values, and a link to the relevant reproduction step. Retain the original final frame when annotated proof is unavailable; do not apply historical coordinates to a later screenshot.
2. **P1 — Rerun on another URL without splitting bug history.** Keep the existing one-click repeat action. Add an inline alternate-URL form that reuses submitted evidence and expectations. Persist a stable bug identity across environments and show the run's environment in its history.
3. **P2 — Explain evidence requirements before submission.** State that at least one of written steps, screenshots, or a recording is required. Show errors beside the evidence group, announce them, focus the affected input, and name rejected files and their rejection reason.

## Deferred findings

- **Mobile is outside the current scope.** The checks table has a 640px minimum width, placing Observed and Result outside the initial narrow viewport. A future mobile pass should stack these values. No mobile redesign or mobile-specific verification is part of this implementation.
- **P2 — Align product names and capability claims.** Reprobe instructions sometimes refer to Navgent. The landing page says media analysis is in development while the submission interface describes analyzing uploads. Align these claims with the shipped capabilities in a later copy pass.
- Smaller refinements: enlarge history markers, collapse Files by default, and clarify Live navigation when there is no recent run.

## Provisional design health

| Heuristic | Score / 4 | Main finding |
|---|---:|---|
| System status | 3 | Useful run states and progress |
| Familiar language | 2 | Reprobe/Navgent naming conflict |
| User control | 3 | Stop/retry paths; limited environment editing |
| Consistency | 2 | Capability messaging disagrees |
| Error prevention | 2 | Evidence requirement appears late |
| Recognition | 3 | Clear labels and visible history |
| Efficiency | 2 | Environment retesting adds friction |
| Visual hierarchy | 3 | Strong desktop report structure |
| Error recovery | 2 | Some upload errors lack specifics |
| Help and guidance | 2 | Examples help; requirements need clarification |
| **Total** | **24 / 40** | **Provisional source and capture assessment** |

## User impact

Developers verifying a fix need to change the environment while retaining a bug's evidence and history. First-time users need to understand the collective evidence requirement before submitting. A clear verdict creates confidence; an unexplained screenshot weakens that confidence at the moment users assess the result.

## Evidence and limitations

The critique inspected current source and recent desktop/mobile report captures in `app/.cache/report-workspace`, generated after the relevant source modifications. These captures use synthetic test data; missing recordings in those fixtures do not establish a recording failure. Expanded disclosures in some captures reflect test interactions rather than defaults.

Two independent reviewers were authorized, but both stopped at the account usage limit; the completed critique used a single-context fallback. Native browser inspection was blocked by URL verification. The Impeccable context, detector, and critique-history helpers were unavailable because their engine could not be verified/downloaded. No detector findings or live overlay are claimed. There was no critique ignore list. The temporary review server and files were cleaned up.

## Verification plan

Use local fixtures and fake agents for ownership, persistence, legacy history migration, changed-target reruns, and proof-frame selection. Check encoded proof pixels against the finding moment, exclude superseded verdicts, and preserve raw evidence. Exercise the desktop form, annotated report, alternate-URL flow, and failure/retry states with existing UI test infrastructure. No provider calls or real bug executions are necessary for these checks.

## Implementation delivered

- Saved reports select an annotated finding frame when a positioned finding and recording exist. The frame is decoded from the finding's recorded moment, includes the selected annotation, and is accompanied by expected/observed values and a link to the corresponding step. Video remains available. Original screenshots and recordings remain separate downloadable artifacts. Unavailable annotations fall back to the original evidence without invented highlights.
- An inline **Run on another URL** form reuses the saved evidence and expectations, validates HTTP(S) targets, retains the entered URL after errors, and supports cancellation. The backend uses the new URL in the reproduction task and copied bug report. The source run is preserved.
- Every new bug has a persistent identity shared by its reruns. Existing databases acquire the identity on initialization, preserving the earlier grouping by owner and exact task. Run history displays each environment's hostname; the full URL is available on the history link.
- Submission states the collective evidence requirement above the inputs. Missing evidence is announced beside that group and focuses Steps. Rejected uploads name the file, format/size/count problem, and recovery, while retaining accepted files.

Verification used the application's existing Python environment. Relevant annotation/export, evidence integration, proof-frame, and application tests passed. Desktop UI tests covered existing report/video behavior plus the new form, history grouping, validation, and annotated proof. Encoded-image checks verified highlighted pixels and the observed recording moment rather than the recording's final frame. Desktop captures were visually inspected. Lint and whitespace checks passed. Mobile-specific cases were excluded, and no provider-backed reproduction or deployment was performed.

## Follow-up: report header density

The supplied report screenshot showed the verdict competing with the bug title, repeated status/date/environment links wrapping across the header, and three actions extending the header before proof appeared.

The desktop header leads with the bug title and uses a smaller verdict label. Only the target hostname remains below the explanation. The two rerun actions sit together at the right. The duplicate All reports action was removed; Reports in the primary navigation still opens the list. Following the user's second screenshot, the recorded timestamp, duration, and run ID moved into a collapsed Run details disclosure in Details, below the proof and checks. Run history also moved into Details, collapsed behind its count; it expands into aligned rows showing each result, timestamp, full target URL, and the currently viewed run. Single-run reports omit the unnecessary history disclosure. History-loading errors remain available in the disclosure. Mobile refinement remains deferred.

Desktop report tests cover history expansion by keyboard, navigation to earlier runs, error disclosure, the alternate-URL form, and constant collapsed-header height as history grows from four runs to twenty. Opening run details or history must not shift the proof section. Desktop collapsed and expanded captures were inspected.
