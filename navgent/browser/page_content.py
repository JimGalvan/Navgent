import json
import re

from playwright.async_api import Page

from navgent.browser.browser_utils import evaluate_with_timeout, get_js_script

WHITESPACE = re.compile(r"\s+")
NGRAM_SIZE = 5
HEAD_SHARE = 0.45
MIN_SHORTENED_LENGTH = 40
SCROLL_HINT_MIN_PAGES = 0.05
TIMED_OUT_FRAME_TEXT = "[Frame unavailable: script evaluation timed out]"


def normalize(text: str) -> str:
    return WHITESPACE.sub(" ", text or "").strip()


def join_indexes(indexes: list[int]) -> str:
    index_strings = []
    for index in indexes:
        index_strings.append(str(index))
    return ",".join(index_strings)


def group_identical_frames(frame_texts: dict[int, str]) -> list[tuple[list[int], str]]:
    """Collapse frames sharing identical text, ordered by first frame index."""
    indexes_by_text: dict[str, list[int]] = {}
    for index in sorted(frame_texts):
        text = normalize(frame_texts[index])
        if text not in indexes_by_text:
            indexes_by_text[text] = []
        indexes_by_text[text].append(index)

    groups = []
    for text, indexes in indexes_by_text.items():
        groups.append((indexes, text))
    return groups


def fair_share(sizes: list[int], budget: int) -> list[int]:
    """Max-min fair allocation.

    Repeatedly hand out an equal share; any frame smaller than its share is
    settled at its true size and its leftover is redistributed to the frames
    still over-share. Means one 2000-char frame can't starve a 20-char one.
    """
    allocations = [0] * len(sizes)
    remaining = budget
    unsettled = set(range(len(sizes)))

    while unsettled and remaining > 0:
        share = remaining // len(unsettled)
        if share == 0:
            break

        fits_in_share = set()
        for index in unsettled:
            if sizes[index] <= share:
                fits_in_share.add(index)

        if not fits_in_share:
            for index in unsettled:
                allocations[index] = share
            break

        for index in fits_in_share:
            allocations[index] = sizes[index]
            remaining -= sizes[index]
        unsettled -= fits_in_share

    return allocations


def drop_repeated_ngrams(text: str, n: int = NGRAM_SIZE) -> str:
    """Remove any word n-gram already seen earlier in this frame.

    All n words of a repeat are marked, so trailing fragments of a duplicated
    phrase disappear too instead of leaving debris behind.
    """
    words = text.split()
    if len(words) <= n:
        return text

    lowered_words = []
    for word in words:
        lowered_words.append(word.lower())

    seen_ngrams = set()
    is_repeat = [False] * len(words)
    for start in range(len(words) - n + 1):
        ngram = tuple(lowered_words[start:start + n])
        if ngram in seen_ngrams:
            for position in range(start, start + n):
                is_repeat[position] = True
        else:
            seen_ngrams.add(ngram)

    kept_words = []
    for word, repeated in zip(words, is_repeat):
        if not repeated:
            kept_words.append(word)
    return " ".join(kept_words)


def keep_head_and_tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    head_length = int(limit * HEAD_SHARE)
    tail_length = limit - head_length
    head = text[:head_length].rstrip()
    tail = text[-tail_length:].lstrip()
    omitted_count = len(text) - limit
    return f"{head} …[{omitted_count} chars omitted]… {tail}"


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    deduplicated = drop_repeated_ngrams(text)
    return keep_head_and_tail(deduplicated, max(limit, MIN_SHORTENED_LENGTH))


def describe_scroll(pages_below: float) -> str:
    if pages_below <= SCROLL_HINT_MIN_PAGES:
        return ""
    return (
        f"[{pages_below:.1f} pages below the screen. This text covers the whole page, "
        "but only on-screen elements are listed; scroll down to reach the rest.]\n"
    )


def frame_label(indexes: list[int]) -> str:
    label = f"iframe[{join_indexes(indexes)}]"
    if len(indexes) > 1:
        label += f" (×{len(indexes)} identical)"
    return label


async def scan_frames(page: Page) -> tuple[dict[int, str], dict[int, float]]:
    """Return each frame's text and how many screens of it are below the fold."""
    frame_texts: dict[int, str] = {}
    pages_below_by_frame: dict[int, float] = {}
    scan_script = get_js_script("scan-page.js")

    for index, frame in enumerate(page.frames):
        if frame.is_detached():
            continue
        try:
            scan_json = await evaluate_with_timeout(frame, scan_script)
        except TimeoutError:
            frame_texts[index] = TIMED_OUT_FRAME_TEXT
            continue

        scan_result = json.loads(scan_json)
        frame_texts[index] = scan_result["pageText"]
        pages_below_by_frame[index] = float(scan_result.get("pagesBelow", 0))

    return frame_texts, pages_below_by_frame


class PageContent:
    @staticmethod
    async def get_page_content(page: Page, char_budget: int = 500) -> str:
        frame_texts, pages_below_by_frame = await scan_frames(page)

        filled_groups = []
        empty_indexes = []
        for indexes, text in group_identical_frames(frame_texts):
            if text:
                filled_groups.append((indexes, text))
            else:
                empty_indexes.extend(indexes)

        text_lengths = []
        for _, text in filled_groups:
            text_lengths.append(len(text))
        limits = fair_share(text_lengths, char_budget)

        has_only_main_frame = len(frame_texts) == 1
        lines = []
        for (indexes, text), limit in zip(filled_groups, limits):
            shortened_text = shorten(text, limit)
            first_frame_index = indexes[0]
            scroll_hint = describe_scroll(pages_below_by_frame.get(first_frame_index, 0.0))
            if has_only_main_frame:
                lines.append(f"{scroll_hint}{shortened_text}")
            else:
                lines.append(f"{frame_label(indexes)} {scroll_hint}{shortened_text}")

        if empty_indexes:
            lines.append(f"iframe[{join_indexes(empty_indexes)}] (empty)")

        return "\n".join(lines)
