from dataclasses import asdict, fields
from datetime import datetime
from typing import Any

from app.runs.schemas import BrowserControlEvent
from navgent import (
    AgentEvent,
    ClickAction,
    KeyAction,
    MouseDownAction,
    MouseUpAction,
    ScrollAction,
    TextAction,
)


class RunEventUtils:
    @staticmethod
    def payload(event: AgentEvent) -> dict[str, Any]:
        payload = asdict(event)
        payload.pop("event_type")
        return RunEventUtils.json_safe(payload)

    @staticmethod
    def json_safe(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            result = {}
            for key, nested_value in value.items():
                result[str(key)] = RunEventUtils.json_safe(nested_value)
            return result
        if isinstance(value, (list, tuple)):
            result = []
            for nested_value in value:
                result.append(RunEventUtils.json_safe(nested_value))
            return result
        return str(value)

    @staticmethod
    def control_action(event: BrowserControlEvent):
        action_classes = {
            "click": ClickAction,
            "mouse_down": MouseDownAction,
            "mouse_up": MouseUpAction,
            "scroll": ScrollAction,
            "key": KeyAction,
            "text": TextAction,
        }
        action_class = action_classes[event.type]
        values = {}
        for action_field in fields(action_class):
            if action_field.init:
                values[action_field.name] = getattr(event, action_field.name)
        return action_class(**values)
