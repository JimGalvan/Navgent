from navgent.browser.browser_session import BrowserSession


async def navigate(session: BrowserSession, url: str) -> str:
    observation = await session.attempt_navigate_and_observe(url)
    return observation.page_state


async def observe_page(session: BrowserSession) -> str:
    observation = await session.attempt_observe_page()
    return observation.page_state


TOOLS = {
    "navigate": navigate,
    "observe_page": observe_page,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Open a URL and return the page state.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "observe_page",
            "description": "Re-read the current page and return its state.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]
