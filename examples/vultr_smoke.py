"""Check that Vultr Serverless Inference models work with Navgent before deploying anything.

    python examples/vultr_smoke.py tools vultr:glm-5.3 vultr:minimax-m3.1-flash
    python examples/vultr_smoke.py evidence vultr:glm-5.3-flash vultr:qwen3.8-flash-next
    python examples/vultr_smoke.py reproduce --strong vultr:glm-5.3 --fast vultr:glm-5.3-flash --runs 3
    python examples/vultr_smoke.py reproduce ... --ws-endpoint ws://127.0.0.1:49153/
"""

import argparse
import asyncio
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from playwright.async_api import async_playwright

from navgent import AgentSettings, BrowserAgentSession
from navgent.events import (
    InputRequiredEvent,
    ReproductionVerdictEvent,
    RunCompletedEvent,
    RunFailedEvent,
    SensitiveInputRequiredEvent,
)
from navgent.evidence import (
    BugReport,
    ReproBrief,
    analyze_evidence,
    build_reproduction_task,
)
from navgent.evidence.pipeline import build_user_message, collect_frames
from navgent.evidence.prompts import SYSTEM_PROMPT
from navgent.shared.llm import build_evidence_model, build_strong_model

SAUCEDEMO_URL = "https://www.saucedemo.com/"
SAUCEDEMO_HOST = "www.saucedemo.com"
SAUCEDEMO_STEPS = """1. Open https://www.saucedemo.com/
2. Log in with username problem_user and password secret_sauce
3. Add "Sauce Labs Backpack" to the cart
4. Open the cart and click Checkout
5. Type "Tester" in First Name
6. Type "Smith" in Last Name
7. Type "12345" in Zip/Postal Code
8. Click Continue"""
SAUCEDEMO_EXPECTED = "The checkout overview page opens."
SAUCEDEMO_ACTUAL = "The form shows 'Error: Last Name is required' even though a last name was typed."
PRICES = {"backpack": 29.99, "bike light": 9.99}
EXPECTED_TOTAL = 39.98


async def check_tools(model_name: str) -> None:
    calls: list[str] = []
    totals: list[float] = []

    @tool
    def lookup_price(item: str) -> str:
        """Look up the price of one item by name."""
        calls.append(f"lookup_price({item})")
        price = PRICES.get(item.strip().lower())
        if price is None:
            return f"No item named {item}. Known items: {', '.join(PRICES)}"
        return f"{item} costs {price}"

    @tool
    def report_total(total: float) -> str:
        """Report the final total. Call once, at the end."""
        calls.append(f"report_total({total})")
        totals.append(total)
        return "Total recorded. Reply with one word: done."

    agent = create_agent(build_strong_model(model_name), tools=[lookup_price, report_total])
    prompt = (
        "Look up the prices of 'backpack' and 'bike light' with lookup_price, "
        "add them up, then call report_total with the sum."
    )
    started = time.monotonic()
    with get_usage_metadata_callback() as usage:
        await agent.ainvoke({"messages": [("user", prompt)]})
    seconds = time.monotonic() - started
    passed = len(totals) == 1 and abs(totals[0] - EXPECTED_TOTAL) < 0.01
    print(f"{result_label(passed)} tools {model_name} in {seconds:.1f}s, calls: {calls}")
    print(f"     usage: {usage.usage_metadata}")


async def check_evidence(model_name: str, screenshot: Path) -> None:
    report = saucedemo_report((screenshot,))
    messages = [SystemMessage(SYSTEM_PROMPT), build_user_message(report, collect_frames(report))]
    for method in ("json_schema", "function_calling"):
        model = build_evidence_model(model_name).with_structured_output(ReproBrief, method=method)
        started = time.monotonic()
        try:
            brief = await model.ainvoke(messages)
        except Exception as exception:
            print(f"FAIL evidence {model_name} {method}: {type(exception).__name__}: {exception}")
            continue
        seconds = time.monotonic() - started
        print(f"PASS evidence {model_name} {method} in {seconds:.1f}s, {len(brief.steps)} steps")
        print(f"     assertion: {brief.assertion.model_dump()}")


async def check_reproduction(strong: str, fast: str, runs: int, ws_endpoint: str | None) -> None:
    settings = AgentSettings(
        strong_model=strong,
        fast_model=fast,
        evidence_model=fast,
        browser_ws_endpoint=ws_endpoint,
        allowed_hosts=(SAUCEDEMO_HOST,),
    )
    report = saucedemo_report(())
    analysis = await analyze_evidence(report, settings)
    task = build_reproduction_task(report, analysis.brief)
    print(task)
    print()
    for number in range(1, runs + 1):
        await run_reproduction(number, task, settings)


async def run_reproduction(number: int, task: str, settings: AgentSettings) -> None:
    verdict: ReproductionVerdictEvent | None = None
    failure = ""
    started = time.monotonic()
    with get_usage_metadata_callback() as usage:
        async with BrowserAgentSession(settings) as session:
            await session.start(task)
            async for event in session.events():
                if isinstance(event, ReproductionVerdictEvent):
                    verdict = event
                elif isinstance(event, InputRequiredEvent):
                    print(f"     agent asked: {event.question}")
                    await session.answer("Use only the information in the task.")
                elif isinstance(event, SensitiveInputRequiredEvent):
                    print(f"     agent asked for a code: {event.prompt}")
                    await session.decline_sensitive_input(event.request_id)
                elif isinstance(event, RunCompletedEvent):
                    break
                elif isinstance(event, RunFailedEvent):
                    failure = event.error
                    break
    seconds = time.monotonic() - started
    if verdict is None:
        print(f"FAIL run {number} in {seconds:.0f}s, no verdict. {failure}")
    else:
        passed = verdict.verdict == "reproduced"
        print(f"{result_label(passed)} run {number} in {seconds:.0f}s: {verdict.verdict}, observed '{verdict.observed}'")
    print(f"     usage: {usage.usage_metadata}")


async def capture_saucedemo_error(directory: Path) -> Path:
    path = directory / "saucedemo-last-name.png"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1365, "height": 768})
        await page.goto(SAUCEDEMO_URL)
        await page.fill("#user-name", "problem_user")
        await page.fill("#password", "secret_sauce")
        await page.click("#login-button")
        await page.click("#add-to-cart-sauce-labs-backpack")
        await page.click(".shopping_cart_link")
        await page.click("#checkout")
        await page.locator("#first-name").press_sequentially("Tester")
        await page.locator("#last-name").press_sequentially("Smith")
        await page.locator("#postal-code").press_sequentially("12345")
        await page.click("#continue")
        await page.screenshot(path=path)
        await browser.close()
    return path


def saucedemo_report(screenshots: tuple[Path, ...]) -> BugReport:
    return BugReport(
        target_url=SAUCEDEMO_URL,
        expected=SAUCEDEMO_EXPECTED,
        actual=SAUCEDEMO_ACTUAL,
        steps_text=SAUCEDEMO_STEPS,
        screenshot_paths=screenshots,
    )


def result_label(passed: bool) -> str:
    if passed:
        return "PASS"
    return "FAIL"


async def run_checks(args: argparse.Namespace) -> None:
    if args.check == "tools":
        for model_name in args.models:
            await check_tools(model_name)
    elif args.check == "evidence":
        with tempfile.TemporaryDirectory() as directory:
            screenshot = await capture_saucedemo_error(Path(directory))
            for model_name in args.models:
                await check_evidence(model_name, screenshot)
    else:
        await check_reproduction(args.strong, args.fast, args.runs, args.ws_endpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test Vultr models with Navgent.")
    commands = parser.add_subparsers(dest="check", required=True)
    tools = commands.add_parser("tools", help="A two-tool agent loop on each strong model.")
    tools.add_argument("models", nargs="+")
    evidence = commands.add_parser("evidence", help="A ReproBrief from a SauceDemo screenshot.")
    evidence.add_argument("models", nargs="+")
    reproduce = commands.add_parser("reproduce", help="The SauceDemo problem_user bug, end to end.")
    reproduce.add_argument("--strong", required=True)
    reproduce.add_argument("--fast", required=True)
    reproduce.add_argument("--runs", type=int, default=1)
    reproduce.add_argument("--ws-endpoint", help="A Playwright server to run the browser on, such as a sandbox.")
    args = parser.parse_args()
    load_dotenv()
    asyncio.run(run_checks(args))


if __name__ == "__main__":
    main()
