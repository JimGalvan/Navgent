import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback

from navgent import AgentSettings
from navgent.evidence import BugReport, analyze_evidence, build_reproduction_task


async def run(report: BugReport) -> None:
    with get_usage_metadata_callback() as usage:
        analysis = await analyze_evidence(report, AgentSettings())
    print("Frames sent:")
    for frame in analysis.frames:
        print(f"- {frame.label} ({len(frame.jpeg) // 1024} KB)")
    print()
    print(analysis.brief.model_dump_json(indent=2))
    print()
    print(build_reproduction_task(report, analysis.brief))
    print()
    print("Usage:", usage.usage_metadata)


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn bug evidence into a reproduction brief.")
    parser.add_argument("--url", required=True, help="The target app URL.")
    parser.add_argument("--expected", required=True, help="What should happen.")
    parser.add_argument("--actual", required=True, help="What happened instead.")
    parser.add_argument("--steps", default="", help="Written reproduction steps.")
    parser.add_argument("--screenshot", action="append", default=[], type=Path, help="A screenshot, repeatable.")
    parser.add_argument("--video", type=Path, help="A screen recording.")
    args = parser.parse_args()
    load_dotenv()
    report = BugReport(
        target_url=args.url,
        expected=args.expected,
        actual=args.actual,
        steps_text=args.steps,
        screenshot_paths=tuple(args.screenshot),
        video_path=args.video,
    )
    asyncio.run(run(report))


if __name__ == "__main__":
    main()
