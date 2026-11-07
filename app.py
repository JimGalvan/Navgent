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
from navgent.log import Log
from navgent.tool_schemas import TOOL_SCHEMAS
from navgent.tools import TOOLS, ToolResult

MODEL = "gpt-4.1-mini"
MAX_STEPS = 25

SYSTEM_PROMPT = """
You are a browser agent. Use the tools to complete the task.
Only use element indexes listed in the observation. If the element you need is not listed, scroll to find it.
<viewport-text> only shows the text visible on the screen, and may be shortened where it says "chars omitted". If you need text that is off screen or omitted, call read_page_text instead of guessing.
When the task is finished, reply with your answer instead of calling a tool.
"""


@dataclass
class PromptData:
    task: str
    history: str
    observation: Observation | str


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
    Log.write(tool_call.function.name, tool_call.function.arguments)
    tool = TOOLS[tool_call.function.name]
    arguments = json.loads(tool_call.function.arguments)
    return await tool(context, **arguments)


def result_to_event(tool_call: ChatCompletionMessageToolCall, tool_output: str) -> str:
    name = tool_call.function.name
    return f"<{name} arguments={tool_call.function.arguments}>\n{tool_output}\n</{name}>"


def update_prompt(prompt_data: PromptData, prompt_template: str) -> str:
    observation: Observation = prompt_data.observation
    return prompt_template.format(task=prompt_data.task, history=prompt_data.history, observation=str(observation))


def add_to_history(history: list[str], record: str) -> None:
    last_record = history[-1] if history else ""
    repeated_prefix = f"{record} (repeated "
    if last_record == record:
        history[-1] = f"{record} (repeated 2 times)"
    elif last_record.startswith(repeated_prefix):
        previous_count = int(last_record.removeprefix(repeated_prefix).split()[0])
        history[-1] = f"{record} (repeated {previous_count + 1} times)"
    else:
        history.append(record)


def format_history(history: list[str]) -> str:
    lines = []
    for number, record in enumerate(history, start=1):
        record = record.replace("\n", "\n   ")
        is_last_step = len(history) == number
        if is_last_step:
            lines.append(f"{number}.(last step) {record}")
        else:
            lines.append(f"{number}. {record}")
    return "\n".join(lines)


def create_prompt_data(tool_result: ToolResult, task: str, history: list[str]) -> PromptData:
    history_text = format_history(history)

    match tool_result.tool_name:
        case "observe_page" | "navigate" | "execute_steps" | "scroll" | "switch_tab" | "switch_frame":
            observation: Observation | None = tool_result.output
            return PromptData(task=task, history=history_text, observation=observation)
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
                if tool_result.history_record:
                    add_to_history(history, tool_result.history_record)
                prompt_data = create_prompt_data(tool_result, task, history)
                current_prompt = update_prompt(prompt_data, prompt_template)

                Log.write_separator()
                Log.write(current_prompt)
                Log.write_separator()
        print(f"Stopped after {MAX_STEPS} steps without a final answer")
        return None
    finally:
        pass
        # await browser_session.close()
        # await browser_manager.stop()


task = "Go to https://www.saucedemo.com/ and login, add to the Cart an item of $15.99 and go to Checkout, enter random test credentials and complete the purchase."
task = "Go to https://the-internet.herokuapp.com/ and open the 'WYSIWYG Editor' example, then tell me the text inside the editor."
# task = "Go to https://books.toscrape.com/, go to the next page of books, and tell me the title and price of the first book on page 2."
# task = "Go to https://www.saucedemo.com/ and login"
# task = (
#     "Go to https://the-internet.herokuapp.com/. "
#     "Find the 'Multiple Windows' example and open it. Click 'Click Here', switch to the new tab "
#     "and note its heading. Switch back to the first tab. "
#     "Then return to the home page, open 'Frames', then 'Nested Frames', "
#     "and tell me the text in the MIDDLE frame. "
#     "Finally, open the 'Large & Deep DOM' example and tell me the last row number of the table at the bottom of the page. "
#     "Reply with all three answers."
# )

if __name__ == "__main__":
    answer = asyncio.run(run(task))
    print("Answer:", answer)
