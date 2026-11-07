from dataclasses import dataclass

from navgent.browser.browser_session import BrowserSession
from navgent.planner import Plan


@dataclass(frozen=True)
class ToolContext:
    browser_session: BrowserSession
    plan: Plan | None = None
