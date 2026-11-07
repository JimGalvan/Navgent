import argparse
import asyncio
from getpass import getpass

from dotenv import load_dotenv

from navgent import AgentSettings, BrowserAgentSession
from navgent.events import (
    AgentMessageDeltaEvent,
    InputRequiredEvent,
    RunCompletedEvent,
    RunFailedEvent,
    SensitiveInputRequiredEvent,
)
from navgent.log import Log


async def run_task(task: str, headless: bool) -> None:
    Log.write("Task:", task)
    async with BrowserAgentSession(AgentSettings(headless=headless)) as session:
        await session.start(task)
        inline = False
        async for event in session.events():
            if isinstance(event, AgentMessageDeltaEvent):
                print(event.text, end="", flush=True)
                inline = not event.text.endswith("\n")
                continue
            if inline:
                print()
                inline = False
            print(event, flush=True)
            Log.write(event)
            if isinstance(event, InputRequiredEvent):
                answer = await asyncio.to_thread(input, f"{event.question}\n> ")
                await session.answer(answer)
            elif isinstance(event, SensitiveInputRequiredEvent):
                code = await asyncio.to_thread(getpass, f"{event.prompt} (empty to decline): ")
                if code:
                    await session.submit_sensitive_input(event.request_id, code)
                else:
                    await session.decline_sensitive_input(event.request_id)
            elif isinstance(event, RunCompletedEvent):
                print(event.output)
                return
            elif isinstance(event, RunFailedEvent):
                raise SystemExit(event.error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a browser task and stream its events.")
    parser.add_argument("task", nargs="*", help="The task for the browser agent.")
    parser.add_argument("--headless", action="store_true", help="Hide the browser window.")
    args = parser.parse_args()
    if not args.task:
        parser.print_help()
        return
    load_dotenv()
    asyncio.run(run_task(" ".join(args.task), args.headless))


if __name__ == "__main__":
    main()
