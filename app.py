import asyncio
import json

from dotenv import load_dotenv
from openai import AsyncOpenAI

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.context import AgentContext
from navgent.tool_schemas import TOOL_SCHEMAS
from navgent.tools import TOOLS

MODEL = "gpt-4.1-mini"
MAX_STEPS = 3

SYSTEM_PROMPT = """
You are a browser agent. Use the tools to complete the task.
When the task is finished, reply with your answer instead of calling a tool.
"""


async def run(task: str) -> str | None:
    load_dotenv()
    client = AsyncOpenAI()
    browser_manager = BrowserManager(headless=False)
    browser_session = BrowserSession(browser_manager)
    context = AgentContext(browser_session=browser_session)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    try:
        for _ in range(MAX_STEPS):
            response = await client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOL_SCHEMAS
            )
            message = response.choices[0].message
            messages.append(message)
            if not message.tool_calls:
                return message.content

            for call in message.tool_calls:
                print(call.function.name, call.function.arguments)
                tool = TOOLS[call.function.name]
                arguments = json.loads(call.function.arguments)
                output = await tool(context, **arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": output,
                })
        return None
    finally:
        await browser_session.close()
        await browser_manager.stop()


if __name__ == "__main__":
    answer = asyncio.run(run("Go to https://www.saucedemo.com/ and tell me what the login form asks for."))
    print("Answer:", answer)
