from typing import Any
from textwrap import dedent
import asyncio
import json

from attr import dataclass
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_session import BrowserSession
from navgent.browser.models import Observation
from navgent.context import ToolContext
from navgent.tool_schemas import TOOL_SCHEMAS
from navgent.tools import TOOLS, ToolResult

MODEL = "gpt-4.1-mini"
MAX_STEPS = 10

SYSTEM_PROMPT = """
You are a browser agent. Use the tools to complete the task.
When the task is finished, reply with your answer instead of calling a tool.
"""


@dataclass
class PromptData:
    task: str
    history: str
    observation: str


def build_prompt(events: list[str]) -> list[dict]:
    history = "\n\n".join(events)
    user_message = f"{history}\n\nWhat is the next step?"
    print(f"user_message: {user_message}")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


async def ask_model(client: AsyncOpenAI, prompt: str) -> ChatCompletionMessage:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    response = await client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_SCHEMAS, parallel_tool_calls=False
    )
    return response.choices[0].message


async def execute_tool_call(context: ToolContext, tool_call: ChatCompletionMessageToolCall) -> ToolResult:
    print(tool_call.function.name, tool_call.function.arguments)
    tool = TOOLS[tool_call.function.name]
    arguments = json.loads(tool_call.function.arguments)
    return await tool(context, **arguments)


def result_to_event(tool_call: ChatCompletionMessageToolCall, tool_output: str) -> str:
    name = tool_call.function.name
    return f"<{name} arguments={tool_call.function.arguments}>\n{tool_output}\n</{name}>"


def update_prompt(prompt_data: PromptData, prompt_template: str) -> str:
    return prompt_template.format(**prompt_data.__dict__)


def update_prompt_data(tool_result: ToolResult, task: str, history: list[str]) -> PromptData:
    history_text = "\n".join(history)

    match tool_result.tool_name:
        case "observe_page" | "navigate":
            observation: Observation = tool_result.output
            return PromptData(task=task, history=history_text, observation=str(observation))
        case "read_page_text":
            text: str = tool_result.output
            return PromptData(task=task, history=history_text, observation=text)

    return PromptData(task=task, history=history_text, observation="None")


current_prompt = ""


async def run(task: str) -> str | None:
    global current_prompt
    load_dotenv()
    client = AsyncOpenAI()
    browser_manager = BrowserManager(headless=False)
    browser_session = BrowserSession(browser_manager)
    tool_context = ToolContext(browser_session=browser_session)
    prompt_template = dedent("""\
                        <task>{task}</task>
                        <history>
                        {history}
                        </history>
                        <observation>
                        {observation}
                        </observation>
                    """)
    current_prompt = prompt_template.format(task=task, history="None", observation="None")
    history: list[str] = []

    try:
        for _ in range(MAX_STEPS):
            message = await ask_model(client, current_prompt)
            if not message.tool_calls:
                return message.content
            for tool_call in message.tool_calls:
                tool_result = await execute_tool_call(tool_context, tool_call)
                history.append(tool_result.history_record)
                prompt_data = update_prompt_data(tool_result, task, history)
                current_prompt = update_prompt(prompt_data, prompt_template)

                print(f"current_prompt: {current_prompt}")
                print("==========================")
        return None
    finally:
        pass
        # await browser_session.close()
        # await browser_manager.stop()


task = "Go to https://www.saucedemo.com/ and login, add to the Cart an item of $15.99 and go to Checkout, enter random test credentials and complete the purchase."

# task = "Go to https://www.saucedemo.com/ and login"


if __name__ == "__main__":
    answer = asyncio.run(run(task))
    print("Answer:", answer)
