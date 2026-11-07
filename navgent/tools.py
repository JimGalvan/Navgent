from dataclasses import dataclass

from navgent.browser.constants import PAGE_TEXT_CHARACTER_LIMIT
from navgent.browser.models import Observation
from navgent.context import ToolContext

SCROLL_PAGES = 0.8


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
    return ToolResult(tool_name="observe_page", succeeded=True, history_record="", output=observation)


async def read_page_text(context: ToolContext) -> ToolResult[str]:
    page_text = await context.browser_session.get_page_text()
    omitted = len(page_text) - PAGE_TEXT_CHARACTER_LIMIT
    if omitted > 0:
        page_text = f"{page_text[:PAGE_TEXT_CHARACTER_LIMIT]}…[{omitted} chars omitted]"
    history_record = f"read_page_text → {len(page_text)} chars"
    return ToolResult(tool_name="read_page_text", succeeded=True, history_record=history_record, output=page_text)


async def execute_steps(context: ToolContext, steps: list[dict]) -> ToolResult[Observation]:
    session = context.browser_session
    for step in steps[:-1]:
        if step["action"] in ("click", "press"):
            planned_steps = []
            for planned in steps:
                planned_steps.append(f"{planned['action']} [{planned['element_index']}]")
            planned_text = ", ".join(planned_steps)
            message = f"Rejected plan ({planned_text}): {step['action']} must be the last step, nothing was run."
            observation = await session.attempt_observe_page()
            return ToolResult(tool_name="execute_steps", succeeded=False, history_record=message, output=observation)

    for step in steps:
        element_index = step["element_index"]
        if not session.has_element(element_index):
            message = ("Rejected: an element index was not in the latest observation, nothing was run. "
                       "Scroll to bring the element on screen, then use an index from the new observation.")
            observation = await session.attempt_observe_page()
            return ToolResult(tool_name="execute_steps", succeeded=False, history_record=message, output=observation)

    previous_url = session.page.url
    messages = []
    for step in steps:
        action = step["action"]
        index = step["element_index"]
        value = step["value"]

        message = None
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
                observation = await session.attempt_observe_page()
                return ToolResult(tool_name="execute_steps", succeeded=False, history_record="\n".join(messages),
                                  output=observation)
        if message:
            messages.append(message)

    current_url = await session.wait_for_page_to_settle()
    if current_url != previous_url:
        messages.append(f"URL changed to {current_url}")
    else:
        messages.append(f"Still on {current_url}")
    observation = await session.attempt_observe_page()
    return ToolResult(tool_name="execute_steps", succeeded=True, history_record="\n".join(messages), output=observation)


async def scroll(context: ToolContext, direction: str) -> ToolResult[Observation]:
    session = context.browser_session
    if direction == "down":
        pages = SCROLL_PAGES
    else:
        pages = -SCROLL_PAGES

    message = await session.scroll(pages)
    observation = await session.attempt_observe_page()
    history_record = f"scroll {direction} → {message}"
    return ToolResult(tool_name="scroll", succeeded=True, history_record=history_record, output=observation)


async def switch_tab(context: ToolContext, tab_id: str) -> ToolResult[Observation]:
    session = context.browser_session
    message = await session.switch_tab(tab_id)
    observation = await session.attempt_observe_page()
    return ToolResult(tool_name="switch_tab", succeeded=True, history_record=message, output=observation)


async def switch_frame(context: ToolContext, frame_id: str) -> ToolResult[Observation]:
    session = context.browser_session
    message = await session.switch_to_iframe(frame_id)
    observation = await session.attempt_observe_page()
    return ToolResult(tool_name="switch_frame", succeeded=True, history_record=message, output=observation)


TOOLS = {
    "navigate": navigate,
    "observe_page": observe_page,
    "read_page_text": read_page_text,
    "execute_steps": execute_steps,
    "scroll": scroll,
    "switch_tab": switch_tab,
    "switch_frame": switch_frame,
}
