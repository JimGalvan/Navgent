from dataclasses import dataclass
from enum import Enum

from openai import AsyncOpenAI
from pydantic import BaseModel

PLANNER_MODEL = "gpt-4.1-mini"

PLANNER_PROMPT = """
You are the planner for a browser agent. You only write the plan; a separate agent with a real browser will execute it.
Return 3 to 7 ordered steps. Each step is a page-level goal (e.g. "Log in"), not a single click or keystroke.
Do not invent credentials or values. If they are needed, add a step to find them on the page.
The last step should report what the task asks for.
"""


class StepStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


STATUS_MARKS = {StepStatus.PENDING: "[ ]", StepStatus.DONE: "[x]", StepStatus.FAILED: "[!]"}
CURRENT_STEP_MARK = "[>]"


@dataclass
class PlanStep:
    id: int
    description: str
    status: StepStatus = StepStatus.PENDING
    note: str = ""


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]

    def get_step(self, step_id: int) -> PlanStep | None:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def pending_steps(self) -> list[PlanStep]:
        pending = []
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                pending.append(step)
        return pending

    def current_step(self) -> PlanStep | None:
        next_index = 0
        for index, step in enumerate(self.steps):
            if step.status != StepStatus.PENDING:
                next_index = index + 1
        if next_index < len(self.steps):
            return self.steps[next_index]
        return None

    def __str__(self) -> str:
        current_step = self.current_step()
        lines = []
        for step in self.steps:
            if step is current_step:
                mark = CURRENT_STEP_MARK
            else:
                mark = STATUS_MARKS[step.status]
            line = f"{mark} {step.id}. {step.description}"
            if step.note:
                line += f" — {step.note}"
            lines.append(line)
        return "\n".join(lines)


class PlanSchema(BaseModel):
    steps: list[str]


async def create_plan(client: AsyncOpenAI, task: str) -> Plan:
    response = await client.beta.chat.completions.parse(
        model=PLANNER_MODEL,
        messages=[
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": task},
        ],
        response_format=PlanSchema,
    )
    parsed = response.choices[0].message.parsed
    steps = []
    for step_id, step_description in enumerate(parsed.steps, start=1):
        steps.append(PlanStep(id=step_id, description=step_description))
    return Plan(goal=task, steps=steps)
