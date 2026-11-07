import asyncio
import json
import logging
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page
from playwright.async_api import Frame as PlaywrightFrame
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from navgent.browser.browser_manager import BrowserManager
from navgent.browser.browser_utils import evaluate_with_timeout, get_js_script, normalize_key
from navgent.browser.constants import (
    LOAD_TIMEOUT_MS,
    OBSERVE_ATTEMPTS,
    SCAN_BUDGET_SECONDS,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)
from navgent.browser.models import Element, Iframe, Observation, Tab
from navgent.browser.page_content import PageContent
from navgent.browser.target_registry import TargetRegistry

logger = logging.getLogger(__name__)


class BrowserSession:

    def __init__(self, browser_manager: BrowserManager, trace_path: Path | None = None):
        self._browser_manager = browser_manager
        self._trace_path = trace_path
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._iframe: PlaywrightFrame | None = None
        self._elements: list[Element] = []
        self._tabs: TargetRegistry[Page] = TargetRegistry("tab")
        self._iframes: TargetRegistry[PlaywrightFrame] = TargetRegistry("frame")

    @property
    def is_open(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    @property
    def page(self) -> Page:
        if not self.is_open:
            raise RuntimeError("No page is open")
        return self._page

    @property
    def current_hostname(self) -> str:
        hostname = urlsplit(self.page.url).hostname
        if not hostname:
            raise RuntimeError("The current page has no valid hostname")
        return hostname

    @staticmethod
    @cache
    def _get_script(name: str) -> str:
        return get_js_script(name)

    async def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            browser = await self._browser_manager.start()
            self._context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
            )
            if self._trace_path is not None:
                await self._context.tracing.start(screenshots=False, snapshots=True)
        return self._context

    async def _stop_trace(self) -> None:
        if self._trace_path is None or self._context is None:
            return

        try:
            self._trace_path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.tracing.stop(path=str(self._trace_path))
            logger.info("Wrote a browser trace to %s", self._trace_path)
        except Exception:
            logger.warning(
                "Could not write a browser trace to %s",
                self._trace_path,
                exc_info=True,
            )

    def _reset_page_state(self, page: Page | None = None) -> None:
        self._page = page
        self._iframe = page.main_frame if page else None
        self._iframes.reset()
        self._elements = []

    def _invalidate_elements(self) -> None:
        self._elements = []

    async def _wait_for_page_to_load(self, static_wait: float, dom_wait: float,
                                     network_wait: float) -> None:
        """static_wait is in seconds; dom_wait and network_wait are in milliseconds."""
        page = self.page
        await asyncio.sleep(static_wait)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=dom_wait)
        except PlaywrightTimeoutError:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=network_wait)
        except PlaywrightTimeoutError:
            pass

    async def attempt_navigate_and_observe(self, url: str) -> Observation:
        context = await self._ensure_context()

        if not self.is_open:
            self._reset_page_state(await context.new_page())

        await self._page.goto(url, timeout=LOAD_TIMEOUT_MS)
        self._reset_page_state(self._page)
        await self._wait_for_page_to_load(static_wait=0.50, dom_wait=2_500, network_wait=3_500)
        return await self._observe_current_page()

    async def attempt_observe_page(self) -> Observation:
        await self._wait_for_page_to_load(static_wait=0.25, dom_wait=500, network_wait=2_000)
        return await self._observe_current_page()

    async def wait_for_page_to_settle(self) -> str:
        await self._wait_for_page_to_load(static_wait=0.25, dom_wait=2_000, network_wait=3_000)
        return self.page.url

    def _live_pages(self) -> list[Page]:
        if self._context is None:
            return []
        return [page for page in self._context.pages if not page.is_closed()]

    def _reconcile_current_page(self) -> None:
        pages = self._live_pages()
        if self._page not in pages:
            self._reset_page_state(pages[-1] if pages else None)

    async def _collect_tabs(self) -> list[Tab]:
        tabs = []
        for tab_id, page in self._tabs.sync(self._live_pages()).items():
            try:
                title = await page.title()
            except Exception:
                title = ""
            tabs.append(Tab(id=tab_id, selected=page is self._page, title=title, url=page.url))
        return tabs

    def _collect_iframes(self) -> list[Iframe]:
        if self._page is None:
            self._iframes.reset()
            return []

        main_frame = self._page.main_frame
        active_frame = self._active_frame()
        return [
            Iframe(
                id=frame_id,
                selected=frame is active_frame,
                main=frame is main_frame,
                name=frame.name or "",
                url=frame.url,
            )
            for frame_id, frame in self._iframes.sync(list(self._page.frames)).items()
        ]

    def _active_frame(self) -> PlaywrightFrame:
        page = self.page
        if self._iframe not in page.frames:
            self._iframe = page.main_frame
        return self._iframe

    async def _scan_page(self) -> str:
        try:
            async with asyncio.timeout(SCAN_BUDGET_SECONDS):
                return await self._scan_until_the_page_settles()
        except TimeoutError:
            raise TimeoutError(
                f"The page could not be scanned within {SCAN_BUDGET_SECONDS} seconds"
            ) from None

    async def _scan_until_the_page_settles(self) -> str:
        """Scan the page, following it if it navigates mid-scan."""
        final_attempt = OBSERVE_ATTEMPTS - 1
        for attempt in range(OBSERVE_ATTEMPTS):
            try:
                active_iframe = self._active_frame()
                await active_iframe.wait_for_load_state(
                    "domcontentloaded", timeout=LOAD_TIMEOUT_MS
                )
                await active_iframe.wait_for_load_state("load", timeout=LOAD_TIMEOUT_MS)
                return await evaluate_with_timeout(
                    active_iframe, self._get_script("scan-page.js")
                )
            except Exception as exception:
                if attempt == final_attempt:
                    raise
                logger.info(
                    "Page navigated mid-scan, observing the new document: %s", exception
                )
                self._reset_page_state(self._page)
        raise RuntimeError("The page kept navigating and could not be observed")

    async def _observe_current_page(self) -> Observation:
        result = json.loads(await self._scan_page())
        elements = []
        seen_links = set()
        for raw_element in result["elements"]:
            href = ""
            for attribute in raw_element["attrs"].split():
                if attribute.startswith("href="):
                    href = attribute
            is_link = raw_element["tag"] == "a" and bool(href)
            link_key = (raw_element["text"], href)
            if is_link and link_key in seen_links:
                continue
            if is_link:
                seen_links.add(link_key)

            element = Element(index=len(elements), **raw_element)
            elements.append(element)
        self._elements = elements

        self._reconcile_current_page()

        url = self.page.url
        title = await self.page.title()
        pages_below = float(result.get("pagesBelow", 0))
        page_content = await PageContent.get_page_content(self._page, char_budget=2_000)
        tabs = await self._collect_tabs()
        iframes = self._collect_iframes()

        return Observation(
            url=url,
            title=title,
            pages_below=pages_below,
            elements=self._elements,
            page_content=page_content,
            tabs=tabs,
            iframes=iframes,
        )

    def _get_stored_element(self, element_index: int) -> Element | None:
        if 0 <= element_index < len(self._elements):
            return self._elements[element_index]
        return None

    async def get_text_in_viewport(self) -> str:
        return await evaluate_with_timeout(
            self._active_frame(), self._get_script("get-text-in-viewport.js")
        )

    async def get_page_text(self) -> str:
        return await evaluate_with_timeout(
            self._active_frame(), self._get_script("get-page-text.js")
        )

    async def scroll(self, pages: float) -> str:
        position = await evaluate_with_timeout(
            self._active_frame(),
            self._get_script("scroll-by-pages.js"),
            pages,
        )
        self._invalidate_elements()
        current_pixels = round(position["current"])
        maximum_pixels = round(position["maximum"])
        return f"Scrolled to {current_pixels} of {maximum_pixels} pixels"

    async def _page_coordinates(
            self, horizontal: float, vertical: float
    ) -> tuple[float, float]:
        frame = self._active_frame()
        if frame is self.page.main_frame:
            return horizontal, vertical

        frame_element = await frame.frame_element()
        bounding_box = await frame_element.bounding_box()
        if bounding_box is None:
            raise RuntimeError("The selected frame is not visible")

        border = await evaluate_with_timeout(
            frame_element,
            "element => ({horizontal: element.clientLeft, vertical: element.clientTop})",
        )
        return (
            bounding_box["x"] + border["horizontal"] + horizontal,
            bounding_box["y"] + border["vertical"] + vertical,
        )

    def _describe_element(self, element_index: int) -> str:
        element = self._get_stored_element(element_index)
        if element is None:
            return f"element [{element_index}]"
        opening_tag = f"{element.tag} {element.attrs}".strip()
        return f"[{element_index}] <{opening_tag}> {element.text}".strip()

    async def _click_element(self, element_index: int) -> None:
        element = self._get_stored_element(element_index)
        if element is None:
            raise ValueError(f"Element [{element_index}] is not available")

        horizontal, vertical = await self._page_coordinates(element.cx, element.cy)
        await self.page.mouse.click(horizontal, vertical)

    async def click(self, element_index: int) -> str:
        await self._click_element(element_index)
        return f"Clicked {self._describe_element(element_index)}"

    async def fill(self, element_index: int, value: str) -> str:
        await self._click_element(element_index)
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.insert_text(value)
        return f"Filled {self._describe_element(element_index)}"

    async def select(self, element_index: int, value: str) -> str:
        await self._click_element(element_index)
        await self.page.keyboard.type(value)
        await self.page.keyboard.press("Enter")
        return f"Selected {value!r} in {self._describe_element(element_index)}"

    async def press(self, element_index: int, value: str) -> str:
        key = normalize_key(value)
        await self._click_element(element_index)
        await self.page.keyboard.press(key)
        return f"Pressed {key} on {self._describe_element(element_index)}"

    async def switch_tab(self, tab_id: str) -> str:
        if self._context is None:
            raise RuntimeError("No browser is open")

        page = self._tabs.get(tab_id)
        if page is None or page.is_closed():
            return f"Tab with id {tab_id} not found"

        await page.bring_to_front()
        self._reset_page_state(page)
        return f"Switched to tab with title {await page.title()} and url {page.url}"

    async def switch_to_iframe(self, iframe_id: str) -> str:
        frame = self._iframes.get(iframe_id)
        if frame is None or frame.is_detached():
            return f"Frame with id {iframe_id} not found"

        self._iframe = frame
        if frame is not self.page.main_frame:
            await (await frame.frame_element()).scroll_into_view_if_needed()
        self._invalidate_elements()
        return f"Switched to frame {iframe_id} with url {frame.url}"

    async def close(self) -> None:
        """Close this session's context. The browser belongs to BrowserManager."""
        if self._context is not None:
            await self._stop_trace()
            await self._context.close()
            self._context = None

        self._reset_page_state()
        self._tabs.reset()
