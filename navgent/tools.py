from navgent.browser.constants import PAGE_TEXT_CHARACTER_LIMIT
from navgent.context import AgentContext


async def navigate(context: AgentContext, url: str) -> str:
    observation = await context.browser_session.attempt_navigate_and_observe(url)
    return observation.page_state


async def observe_page(context: AgentContext) -> str:
    observation = await context.browser_session.attempt_observe_page()
    return observation.page_state


async def read_page_text(context: AgentContext) -> str:
    page_text = await context.browser_session.get_page_text()
    if len(page_text) <= PAGE_TEXT_CHARACTER_LIMIT:
        return page_text
    omitted = len(page_text) - PAGE_TEXT_CHARACTER_LIMIT
    return f"{page_text[:PAGE_TEXT_CHARACTER_LIMIT]}…[{omitted} chars omitted]"


async def click(context: AgentContext, element_index: int) -> str:
    return await context.browser_session.click(element_index)


async def fill(context: AgentContext, element_index: int, value: str) -> str:
    return await context.browser_session.fill(element_index, value)


async def select(context: AgentContext, element_index: int, value: str) -> str:
    return await context.browser_session.select(element_index, value)


async def press(context: AgentContext, element_index: int, key: str) -> str:
    return await context.browser_session.press(element_index, key)


async def switch_tab(context: AgentContext, tab_id: str) -> str:
    return await context.browser_session.switch_tab(tab_id)


async def switch_frame(context: AgentContext, frame_id: str) -> str:
    return await context.browser_session.switch_to_iframe(frame_id)


TOOLS = {
    "navigate": navigate,
    "observe_page": observe_page,
    "read_page_text": read_page_text,
    "click": click,
    "fill": fill,
    "select": select,
    "press": press,
    "switch_tab": switch_tab,
    "switch_frame": switch_frame,
}

