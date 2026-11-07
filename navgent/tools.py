from dataclasses import dataclass

from navgent.browser.constants import PAGE_TEXT_CHARACTER_LIMIT
from navgent.browser.models import Observation
from navgent.context import ToolContext


@dataclass
class ToolResult[T]:
    tool_name: str
    succeeded: bool
    history_record: str
    output: T


async def navigate(context: ToolContext, url: str) -> ToolResult[Observation]:
    observation = await context.browser_session.attempt_navigate_and_observe(url)
    history_record = f'navigate {url} → "{observation.title}" {observation.url}'
    return ToolResult(tool_name="navigate", succeeded=True, history_record=history_record, output=observation)


async def observe_page(context: ToolContext) -> ToolResult[Observation]:
    observation = await context.browser_session.attempt_observe_page()
    history_record = f'observe_page → "{observation.title}" {observation.url}'
    return ToolResult(tool_name="observe_page", succeeded=True, history_record=history_record, output=observation)


async def read_page_text(context: ToolContext) -> ToolResult[str]:
    page_text = await context.browser_session.get_page_text()
    omitted = len(page_text) - PAGE_TEXT_CHARACTER_LIMIT
    if omitted > 0:
        page_text = f"{page_text[:PAGE_TEXT_CHARACTER_LIMIT]}…[{omitted} chars omitted]"
    history_record = f"read_page_text → {len(page_text)} chars"
    return ToolResult(tool_name="read_page_text", succeeded=True, history_record=history_record, output=page_text)


async def execute_steps(context: ToolContext, steps: list[dict]) -> ToolResult[list[str]]:
    session = context.browser_session
    for step in steps[:-1]:
        if step["action"] in ("click", "press"):
            message = f"{step['action']} must be the last step; observe the page before planning more."
            return ToolResult(tool_name="execute_steps", succeeded=False, history_record=message, output=[message])

    previous_url = session.page.url
    messages = []
    for step in steps:
        action = step["action"]
        index = step["element_index"]
        value = step["value"]

        match action:
            case "click":
                message = await session.click(index)
            case "fill":
                message = await session.fill(index, value)
            case "select":
                message = await session.select(index, value)
            case "press":
                message = await session.press(index, value)
            case _:
                messages.append(f"Unknown action {action}")
                return ToolResult(tool_name="execute_steps", succeeded=False, history_record="\n".join(messages), output=messages)
        messages.append(message)

    current_url = await session.wait_for_page_to_settle()
    if current_url != previous_url:
        messages.append(f"URL changed to {current_url}")
    else:
        messages.append(f"Still on {current_url}")
    return ToolResult(tool_name="execute_steps", succeeded=True, history_record="\n".join(messages), output=messages)


async def switch_tab(context: ToolContext, tab_id: str) -> ToolResult[str]:
    message = await context.browser_session.switch_tab(tab_id)
    return ToolResult(tool_name="switch_tab", succeeded=True, history_record=message, output=message)


async def switch_frame(context: ToolContext, frame_id: str) -> ToolResult[str]:
    message = await context.browser_session.switch_to_iframe(frame_id)
    return ToolResult(tool_name="switch_frame", succeeded=True, history_record=message, output=message)


TOOLS = {
    "navigate": navigate,
    "observe_page": observe_page,
    "read_page_text": read_page_text,
    "execute_steps": execute_steps,
    "switch_tab": switch_tab,
    "switch_frame": switch_frame,
}
