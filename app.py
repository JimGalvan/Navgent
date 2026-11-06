import asyncio
import json

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.context import ToolContext
from navgent.tool_schemas import TOOL_SCHEMAS
from navgent.tools import TOOLS

MODEL = "gpt-4.1-mini"
MAX_STEPS = 3

SYSTEM_PROMPT = """
You are a browser agent. Use the tools to complete the task.
When the task is finished, reply with your answer instead of calling a tool.
"""


async def ask_model(client: AsyncOpenAI, messages: list) -> ChatCompletionMessage:
    response = await client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_SCHEMAS
    )
    return response.choices[0].message


async def execute_tool_call(context: ToolContext, tool_call: ChatCompletionMessageToolCall) -> str:
    print(tool_call.function.name, tool_call.function.arguments)
    tool = TOOLS[tool_call.function.name]
    arguments = json.loads(tool_call.function.arguments)
    return await tool(context, **arguments)


def result_to_message(call: ChatCompletionMessageToolCall, output: str) -> dict:
    return {"role": "tool", "tool_call_id": call.id, "content": output}


async def run(task: str) -> str | None:
    load_dotenv()
    client = AsyncOpenAI()
    browser_manager = BrowserManager(headless=False)
    browser_session = BrowserSession(browser_manager)
    context = ToolContext(browser_session=browser_session)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    try:
        for _ in range(MAX_STEPS):
            message = await ask_model(client, messages)
            messages.append(message)
            if not message.tool_calls:
                return message.content

            for tool_call in message.tool_calls:
                output = await execute_tool_call(context, tool_call)
                message = result_to_message(tool_call, output)
                messages.append(message)
        return None
    finally:
        await browser_session.close()
        await browser_manager.stop()


if __name__ == "__main__":
    answer = asyncio.run(run("Go to https://www.saucedemo.com/ and tell me what the login form asks for."))
    print("Answer:", answer)
