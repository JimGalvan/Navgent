from navgent.browser.constants import PAGE_TEXT_CHARACTER_LIMIT
from navgent.context import ToolContext


async def navigate(context: ToolContext, url: str) -> str:
    observation = await context.browser_session.attempt_navigate_and_observe(url)
    return observation.page_state


async def observe_page(context: ToolContext) -> str:
    observation = await context.browser_session.attempt_observe_page()
    return observation.page_state


async def read_page_text(context: ToolContext) -> str:
    page_text = await context.browser_session.get_page_text()
    if len(page_text) <= PAGE_TEXT_CHARACTER_LIMIT:
        return page_text
    omitted = len(page_text) - PAGE_TEXT_CHARACTER_LIMIT
    return f"{page_text[:PAGE_TEXT_CHARACTER_LIMIT]}…[{omitted} chars omitted]"


async def execute_steps(context: ToolContext, steps: list[dict]) -> str:
    session = context.browser_session
    for step in steps[:-1]:
        if step["action"] in ("click", "press"):
            return f"{step['action']} must be the last step; observe the page before planning more."

    results = []
    for step in steps:
        index, value = step["element_index"], step["value"]
        match step["action"]:
            case "click":
                result = await session.click(index)
            case "fill":
                result = await session.fill(index, value)
            case "select":
                result = await session.select(index, value)
            case "press":
                result = await session.press(index, value)
        results.append(result)
    return "\n".join(results)


async def switch_tab(context: ToolContext, tab_id: str) -> str:
    return await context.browser_session.switch_tab(tab_id)


async def switch_frame(context: ToolContext, frame_id: str) -> str:
    return await context.browser_session.switch_to_iframe(frame_id)


TOOLS = {
    "navigate": navigate,
    "observe_page": observe_page,
    "read_page_text": read_page_text,
    "execute_steps": execute_steps,
    "switch_tab": switch_tab,
    "switch_frame": switch_frame,
}

