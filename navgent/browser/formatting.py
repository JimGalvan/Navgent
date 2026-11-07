import html
import re

from navgent.browser.models import Element, Observation




def normalize_page_text(text: str) -> str:
    normalized_lines = []

    for line in text.splitlines():
        collapsed = re.sub(r"\s+", " ", line).strip()

        if collapsed:
            normalized_lines.append(collapsed)

    return "\n".join(normalized_lines)





