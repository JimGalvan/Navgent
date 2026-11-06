from dataclasses import dataclass

from navgent.browser.browser_session import BrowserSession


@dataclass(frozen=True)
class ToolContext:
    browser_session: BrowserSession
