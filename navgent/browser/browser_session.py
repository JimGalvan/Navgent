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
from navgent.browser.browser_utils import (
    evaluate_with_timeout,
    get_js_script,
    normalize_key,
)
from navgent.browser.constants import (
    FRAME_QUALITY,
    LOAD_TIMEOUT_MS,
    OBSERVE_ATTEMPTS,
    SCAN_BUDGET_SECONDS,
    TYPING_DELAY_MS,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)
from navgent.browser.element_factory import ElementFactory
from navgent.browser.models import Box, Element, Iframe, Observation, Tab, Viewport
from navgent.browser.page_content import PageContent
from navgent.browser.recording import (
    PageRecorder,
    PerformedClick,
    Recording,
    wall_time_ms,
)
from navgent.browser.target_registry import TargetRegistry

logger = logging.getLogger(__name__)


class BrowserSession:

    def __init__(
            self,
            browser_manager: BrowserManager,
            trace_path: Path | None = None,
            recording_dir: Path | None = None,
    ):
        self._browser_manager = browser_manager
        self._trace_path = trace_path
        self._recording_dir = recording_dir
        self._recorders: list[PageRecorder] = []
        self._recording_starts: list[asyncio.Task[None]] = []
        self._performed_clicks: list[PerformedClick] = []
        self.recording_paths: list[Path] = []
        self.recordings: list[Recording] = []
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
            viewport = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
            self._context = await browser.new_context(viewport=viewport)
            if self._recording_dir is not None:
                self._context.on("page", self._start_recording)
            if self._trace_path is not None:
                await self._context.tracing.start(screenshots=False, snapshots=True)
        return self._context

    def _start_recording(self, page: Page) -> None:
        recorder = PageRecorder(page, self._recording_dir, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
        self._recorders.append(recorder)
        self._recording_starts.append(asyncio.create_task(recorder.start()))

    async def _wait_for_recordings_to_start(self) -> None:
        starts = self._recording_starts
        self._recording_starts = []
        await asyncio.gather(*starts)

    async def _finish_recordings(self) -> None:
        await self._wait_for_recordings_to_start()
        stops = []
        for recorder in self._recorders:
            stops.append(recorder.stop())
        await asyncio.gather(*stops)
        for recorder in self._recorders:
            if recorder.path.exists() and recorder.path.stat().st_size > 0:
                self.recording_paths.append(recorder.path)
                self.recordings.append(recorder.describe())
        self._recorders = []

    def _recorder_for(self, page: Page) -> PageRecorder | None:
        for recorder in self._recorders:
            if recorder.page is page:
                return recorder
        return None

    def current_recording(self) -> PageRecorder | None:
        if not self.is_open:
            return None
        return self._recorder_for(self._page)

    def viewport_size(self) -> tuple[int, int]:
        size = self.page.viewport_size
        if size is None:
            return VIEWPORT_WIDTH, VIEWPORT_HEIGHT
        return size["width"], size["height"]

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
            await self._wait_for_recordings_to_start()

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
        pages = []
        for page in self._context.pages:
            if not page.is_closed():
                pages.append(page)
        return pages

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
        iframes = []
        for frame_id, frame in self._iframes.sync(list(self._page.frames)).items():
            iframes.append(
                Iframe(
                    id=frame_id,
                    selected=frame is active_frame,
                    main=frame is main_frame,
                    name=frame.name or "",
                    url=frame.url,
                )
            )
        return iframes

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

    def _remove_duplicate_links(self, raw_elements: list[dict]) -> list[dict]:
        """Keep the first link for each (text, href) pair and every non-link element."""

        def find_href(attrs: str) -> str:
            href = ""
            for attribute in attrs.split():
                if attribute.startswith("href="):
                    href = attribute
            return href

        unique_elements = []
        seen_links = set()
        for raw_element in raw_elements:
            href = find_href(raw_element["attrs"])
            is_link = raw_element["tag"] == "a" and href != ""
            if is_link:
                link_key = (raw_element["text"], href)
                if link_key in seen_links:
                    continue
                seen_links.add(link_key)
            unique_elements.append(raw_element)
        return unique_elements

    def _filter_outside_viewport(self, elements: list[Element], viewport: Viewport) -> list[Element]:
        updated_list = []
        for element in elements:
            is_on_screen = viewport.check_if_on_screen(element.element_bounds)
            if is_on_screen:
                updated_list.append(element)
        return updated_list

    async def _observe_current_page(self) -> Observation:
        scan_result = json.loads(await self._scan_page())
        unique_raw_elements = self._remove_duplicate_links(scan_result["elements"])

        elements = []
        for index, raw_element in enumerate(unique_raw_elements):
            elements.append(ElementFactory.create_element(index, raw_element))

        viewport = Viewport(**scan_result["viewport"])
        self._elements = self._filter_outside_viewport(elements, viewport)
        for index, element in enumerate(self._elements):
            element.index = index
        elements_outside_viewport_count = len(elements) - len(self._elements)

        self._reconcile_current_page()
        url = self.page.url
        title = await self.page.title()
        pages_below = float(scan_result.get("pagesBelow", 0))
        page_content = await PageContent.get_page_content(
            self._page, self._active_frame(), scan_result, char_budget=500
        )
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
            elements_outside_viewport_count=elements_outside_viewport_count,
        )

    def get_stored_element(self, element_index: int) -> Element | None:
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

    async def _read_form_fields(self) -> list[dict]:
        return await evaluate_with_timeout(
            self._active_frame(), self._get_script("get-form-values.js")
        )

    @staticmethod
    def _describe_form_field(field: dict) -> str:
        value = field["value"].strip()
        if not value:
            value = "(empty)"
        return f"{field['label']}: {value}"

    async def get_form_values(self) -> list[str]:
        lines = []
        for field in await self._read_form_fields():
            lines.append(self._describe_form_field(field))
        return lines

    async def locate_quote(self, quote: str) -> Box | None:
        """Return the on-screen box of a quote that appears exactly once, unhidden and uncovered."""
        found = await evaluate_with_timeout(
            self._active_frame(), self._get_script("locate-text.js"), quote
        )
        if not found:
            found = await self._locate_form_field(quote)
        if len(found) != 1 or not found[0]["unobscured"]:
            return None

        x, y = await self._page_coordinates(found[0]["x"], found[0]["y"])
        box = Box(round(x, 1), round(y, 1), round(found[0]["width"], 1), round(found[0]["height"], 1))
        if not box.fits_inside(*self.viewport_size()):
            return None
        return box

    async def _locate_form_field(self, quote: str) -> list[dict]:
        wanted = " ".join(quote.split())
        found = []
        for field in await self._read_form_fields():
            if " ".join(self._describe_form_field(field).split()) == wanted:
                found.append({**field["box"], "unobscured": True})
        return found

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
        element = self.get_stored_element(element_index)
        if element is None:
            return f"element [{element_index}]"
        opening_tag = f"{element.tag} {element.attrs}".strip()
        return f"<{opening_tag}> {element.text}".strip()

    async def _click_element(self, element_index: int) -> None:
        element = self.get_stored_element(element_index)
        if element is None:
            raise ValueError(f"Element [{element_index}] is not available")

        page = self.page
        horizontal, vertical = await self._page_coordinates(element.cx, element.cy)
        clicked_at = wall_time_ms()
        await page.mouse.click(horizontal, vertical)
        self._remember_click(page, horizontal, vertical, clicked_at)

    def _remember_click(self, page: Page, horizontal: float, vertical: float, clicked_at: float) -> None:
        size = page.viewport_size or {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
        recorder = self._recorder_for(page)
        recording_id = None
        recording_time = None
        if recorder is not None:
            recording_id = recorder.id
            recording_time = recorder.recording_time_ms(clicked_at)
        self._performed_clicks.append(
            PerformedClick(
                horizontal, vertical, size["width"], size["height"], clicked_at, recording_id, recording_time,
            )
        )

    def take_performed_clicks(self) -> list[PerformedClick]:
        """Return the clicks dispatched since the last call, oldest first."""
        clicks = self._performed_clicks
        self._performed_clicks = []
        return clicks

    async def click(self, element_index: int) -> str:
        await self._click_element(element_index)
        return f"Clicked {self._describe_element(element_index)}"

    async def fill(self, element_index: int, value: str) -> str:
        await self._click_element(element_index)
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.insert_text(value)
        return f"Filled {self._describe_element(element_index)}"

    async def type_text(self, element_index: int, value: str) -> str:
        await self._click_element(element_index)
        await self.page.keyboard.press("Control+A")
        await self.page.keyboard.type(value, delay=TYPING_DELAY_MS)
        return f"Typed into {self._describe_element(element_index)}"

    async def fill_sensitive(
            self, element_index: int, value: str, submit_element_index: int | None = None
    ) -> str:
        element = self.get_stored_element(element_index)
        if element is None:
            raise ValueError(f"Element [{element_index}] is not available")

        await evaluate_with_timeout(
            self._active_frame(),
            self._get_script("mask-sensitive-field.js"),
            {"x": element.cx, "y": element.cy},
        )
        await self.fill(element_index, value)
        return await self._submit_sensitive_field(element_index, submit_element_index)

    async def _submit_sensitive_field(self, element_index: int, submit_element_index: int | None) -> str:
        if submit_element_index is not None:
            await self._click_element(submit_element_index)
            return f"Filled element [{element_index}] and clicked element [{submit_element_index}] to submit it"

        await self.page.keyboard.press("Enter")
        return f"Filled element [{element_index}] and pressed Enter to submit it"

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

    async def user_click(self, horizontal: float, vertical: float) -> str:
        await self.page.mouse.click(horizontal, vertical)
        self._invalidate_elements()
        return f"Clicked at {horizontal:.0f}, {vertical:.0f}"

    async def user_scroll(self, horizontal: float, vertical: float, amount: float) -> str:
        await self.page.mouse.move(horizontal, vertical)
        await self.page.mouse.wheel(0, amount)
        self._invalidate_elements()
        return f"Scrolled by {amount:.0f} pixels"

    async def user_mouse_down(self, horizontal: float, vertical: float) -> str:
        await self.page.mouse.move(horizontal, vertical)
        await self.page.mouse.down()
        self._invalidate_elements()
        return "Mouse button held"

    async def user_mouse_up(self) -> str:
        await self.page.mouse.up()
        self._invalidate_elements()
        return "Mouse button released"

    async def user_key(self, key: str) -> str:
        await self.page.keyboard.press(key)
        self._invalidate_elements()
        return f"Pressed {key}"

    async def user_text(self, text: str) -> str:
        await self.page.keyboard.insert_text(text)
        self._invalidate_elements()
        return "Typed text"

    async def capture_screen_frame(self, quality: int = FRAME_QUALITY) -> bytes | None:
        if not self.is_open:
            return None
        return await self.page.screenshot(type="jpeg", quality=quality, scale="css")

    async def close(self) -> None:
        """Close this session's context. The browser belongs to BrowserManager."""
        if self._context is not None:
            await self._stop_trace()
            await self._finish_recordings()
            await self._context.close()
            self._context = None

        self._reset_page_state()
        self._tabs.reset()
