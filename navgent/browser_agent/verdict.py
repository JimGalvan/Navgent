from pydantic import BaseModel, ConfigDict, Field

from navgent.models import Verdict


class VerdictReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    expected: str
    observed: str
    step_number: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=500)


def check_observed(observed: str, page_text: str) -> str | None:
    if not observed.strip():
        return "observed is empty. Quote the value from the page, or report inconclusive."
    if normalize(observed) not in normalize(page_text):
        return (
            f"'{observed}' is not on the current page. Quote it word for word from the page, "
            "switch to the tab or frame that shows it, or report inconclusive."
        )
    return None


def normalize(text: str) -> str:
    return " ".join(text.split())
