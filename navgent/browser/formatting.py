import html
import re

from navgent.browser.models import Element, Observation

MAX_ELEMENTS = 100


def normalize_page_text(text: str) -> str:
    normalized_lines = []

    for line in text.splitlines():
        collapsed = re.sub(r"\s+", " ", line).strip()

        if collapsed:
            normalized_lines.append(collapsed)

    return "\n".join(normalized_lines)


def hide_query_string(url: str) -> str:
    if "?" not in url:
        return url

    path = url.split("?", 1)[0]
    return f"{path}?..."


def format_element(element: Element) -> str:
    tag = element.tag.strip()
    attrs = html.escape(element.attrs.strip(), quote=False)
    text = html.escape(normalize_page_text(element.text), quote=False)

    opening_tag = f"{tag} {attrs}".strip()

    if text:
        return f"[{element.index}] <{opening_tag}> {text}"

    return f"[{element.index}] <{opening_tag}>"


def format_elements(elements: list[Element]) -> str:
    shown_elements = elements[:MAX_ELEMENTS]
    omitted_count = len(elements) - len(shown_elements)

    if not shown_elements:
        return "(none)"

    lines = [format_element(element) for element in shown_elements]
    if omitted_count:
        lines.append(f"... {omitted_count} additional elements omitted")
    return "\n".join(lines)


def format_observation(observation: Observation) -> str:
    url = html.escape(hide_query_string(observation.url), quote=True)
    title = html.escape(observation.title, quote=True)
    pages_below = f"{observation.pages_below:.1f}"
    elements = format_elements(observation.elements)
    iframes = "\n".join(str(iframe) for iframe in observation.iframes)

    return (
        f'<page url="{url}" title="{title}" pages_below="{pages_below}">\n\n'
        f"Interactive elements:\n{elements}\n\n</page>\n"
        f"<page-content>{observation.page_content}</page-content>\n"
        f"<available-tabs>{observation.tabs}</available-tabs>\n"
        f"<available-iframes>\n{iframes}\n</available-iframes>"
    )
