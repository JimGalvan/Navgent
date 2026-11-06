TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Open a URL and return the page state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "observe_page",
            "description": "Re-read the current page and return its state.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_page_text",
            "description": "Return the full text of the current page or selected frame, for values an observation shortened.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_steps",
            "description": "Run element actions in order, such as filling a form and submitting it. click and press can only be the last step, because they may change the page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "action": {"type": "string", "enum": ["click", "fill", "select", "press"]},
                                "element_index": {"type": "integer", "description": "The [index] of an element from the last observation."},
                                "value": {"type": ["string", "null"], "description": "Text for fill, option label for select, key for press, null for click."},
                            },
                            "required": ["action", "element_index", "value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["steps"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_tab",
            "description": "Switch to a tab by an id such as `tab:1` from <available-tabs>.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tab_id": {"type": "string"},
                },
                "required": ["tab_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "switch_frame",
            "description": "Switch to a frame by an id such as `frame:1` from <available-iframes>; `frame:0` is the main page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "frame_id": {"type": "string"},
                },
                "required": ["frame_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]
