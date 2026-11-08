---
name: Reprobe
description: Dark minimal workspace for reproducing bugs and inspecting evidence.
colors:
  bg: "#0c0c0d"
  surface: "#121214"
  text: "#ececea"
  body-muted: "#cfcfcb"
  muted: "#9a9a96"
  line: "#26262a"
  faint-line: "#1c1c1f"
  input-line: "#3a3a3f"
  lime: "#c6f24e"
  red: "#ff6b5e"
  warning: "#ffb454"
  danger-line: "#5a2a27"
  danger-text: "#ff8a7e"
typography:
  title:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "15px"
    lineHeight: 1.55
  section:
    fontFamily: "Geist, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    letterSpacing: "0.04em"
  mono:
    fontFamily: "Geist Mono, monospace"
    fontSize: "12px"
  status:
    fontFamily: "Geist Mono, monospace"
    fontSize: "13px"
rounded:
  control: "4px"
spacing:
  small: "8px"
  medium: "16px"
  gutter: "24px"
  section: "40px"
  wide: "48px"
components:
  button-primary:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.bg}"
    rounded: "{rounded.control}"
    padding: "10px 24px"
    height: "48px"
  button-secondary:
    backgroundColor: transparent
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    height: "44px"
  button-danger:
    backgroundColor: transparent
    textColor: "{colors.danger-text}"
    rounded: "{rounded.control}"
    height: "44px"
---

# Design System: Reprobe

## Overview

**Creative North Star: "Dark minimal evidence workspace"**

The supplied New reproduction, Live run viewer and Evidence report HTML mocks and the user's global standards are authoritative. The interface uses restrained typography, open space and thin dividers to support entering evidence, following execution and reading results. Preserve this identity on public and account pages while retaining their established layouts.

**Key Characteristics:**

- Flat dark surfaces with a single accent for primary actions and active state.
- Consistent application titles and section labels.
- Clear separation of user claims, planned assertions and observed results.

## Colors

### Primary

Lime marks the primary action, active plan steps, running status, progress and the latest captured frame. Red marks observed bugs, failures and the live feed. Warning is reserved for warning states; destructive controls use the softer danger text and dark danger border.

### Neutral

Background and surface establish the dark ground. Text, body-muted and muted provide the reading hierarchy. Line separates sections, faint-line separates list rows and input-line defines fields and secondary controls. The frontmatter mirrors the CSS custom properties in `server/static/styles.css`.

## Typography

Geist is the UI face; Geist Mono is for run IDs, URLs, timestamps, logs and measured values. Both are locally hosted with their license. Application titles use the title role; subtitles use muted text (14px). Section labels use the section role in uppercase. Status lines use the status role. Comparison values use mono (24px). Numerals in measured data are tabular.

Keep a single compact title hierarchy on the three application screens. Let long titles wrap at narrow widths rather than overflow. Body paragraphs generally have a reading measure of 68 characters; logs and form content can use the available width.

## Layout

The shared application header has horizontal padding (48px), vertical padding (12px), a bottom divider and navigation targets at least 44px tall. New, Live and Reports appear alongside the user's email and Log out. Current navigation uses the primary text color and `aria-current`.

Application pages have top padding (40px), side padding (24px) and bottom padding (80px). Maximum widths, including padding, are New (760px), Live (1240px) and Report (960px). Sections are separated by 40px. The desktop live viewer has a flexible viewport, a 320px sidebar and a 48px gap.

At 1000px the live columns stack. At 640px the header wraps, the email remains visible on its own line, paired form fields and uploads stack, stream rows stack, and the start button fills the available width. Keep long URLs, outputs and filenames within the page; thumbnail strips may scroll internally. Review application screens at 1440px and 390px.

## Elevation & Depth

The application uses no shadows or gradients. Space, 1px dividers and restrained surface changes establish grouping. Avoid enclosing ordinary content in cards.

## Shapes

Buttons use a small control radius. Inputs are transparent with an underline and square corners. Upload targets use compact dashed borders with a minimum height of 88px. Status dots are small circles; they accompany visible text rather than carrying status alone.

## Components

### Shared primitives

The shared header is rendered once in `ui.js`. Application title, section-label, button, field and status treatments live in the shared stylesheet. Primary buttons have a minimum height of 48px; secondary and destructive controls have a minimum height of 44px. Focus uses a lime outline (2px) with an offset (5px); upload focus outlines its entire target. Selection and input carets also use lime. Disabled buttons reduce opacity; empty, loading and inline error states use plain text.

### New reproduction

One form presents optional steps, optional screenshot and video uploads, App URL, Expected and optional Actual. Expected remains required by the user's clarification. Submission requires a URL and at least one evidence source. Existing file previews, removal, ordering, validation and draft persistence remain available. Recent runs are linked rows with a run ID, title, verdict or execution status, and duration.

### Live execution

The browser URL line, streamed frame, current action and captured-frame strip form one reading group. Action type is accented; the latest thumbnail receives the accent border. Plans use plain numbered rows, completed ticks, active color and selectable step detail. Form state and input requests appear only when emitted by the run. The agent stream scrolls automatically and shows a blinking caret while active. Reduced-motion preferences disable animation. The thin progress line reflects known plan completion during execution and is hidden for terminal statuses.

### Evidence report and data limits

Evidence, comparison, verdict, action history, run output, recordings, submitted key frames, evidence plan and downloads render from available run data. Hide sections without data. Label submitted evidence and user-reported actual separately from observed run results. Keep the existing rerun behavior and authenticated routes.

Current downloads are browser screenshot JPEG, tab recordings WebM and run record JSON. Pause/resume, sandbox containment and resource metrics, API-result comparison, console capture, attempt counts, annotated PNG, MP4, HAR and Playwright-script exports have no supporting backend data or operation. Do not display mock values or inactive controls for these. A completed execution is not proof of reproduction; only the saved verdict establishes that result. Preview fixtures remain explicitly labeled.

## Do's and Don'ts

### Do:

- Do use the supplied HTML mocks and user standards as the visual authority.
- Do preserve real forms, authentication, routes, streams and run controls.
- Do keep labels, visible keyboard focus and responsive reading order.
- Do show only supported run data and clearly label claims and fixtures.

### Don't:

- Don't add cards, gradients, icon tiles, pills or shadows to these application screens.
- Don't use oversized application titles or turn measured-data typography into decoration.
- Don't invent sandbox guarantees, observations, metrics, controls or download formats.
- Don't make Expected optional or infer reproduction from execution success.
