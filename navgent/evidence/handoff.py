from navgent.evidence.models import BugReport, ReproBrief


def build_reproduction_task(report: BugReport, brief: ReproBrief) -> str:
    lines = [f"Reproduce this bug on {report.target_url}.", "", "<steps>"]
    for number, step in enumerate(brief.steps, start=1):
        lines.append(f"{number}. {step.instruction}")
    assertion = brief.assertion
    lines.extend([
        "</steps>",
        "",
        "<assertion>",
        f"Check: {assertion.check}",
        f"Expected: {assertion.expected}",
        f"Reported actual: {assertion.reported_actual}",
        f"Look in: {assertion.look_in}",
        "</assertion>",
    ])
    if brief.unknowns:
        lines.extend(["", "<unknowns>"])
        for unknown in brief.unknowns:
            lines.append(f"- {unknown}")
        lines.append("</unknowns>")
    return "\n".join(lines)
