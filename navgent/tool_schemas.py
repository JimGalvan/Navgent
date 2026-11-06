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
            "name": "click",
            "description": "Click an element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_index": {"type": "integer", "description": "The [index] of an element from the last observation."},
                },
                "required": ["element_index"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "Replace the text in an input with a value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_index": {"type": "integer", "description": "The [index] of an element from the last observation."},
                    "value": {"type": "string"},
                },
                "required": ["element_index", "value"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select",
            "description": "Choose an option in a dropdown by typing its label.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_index": {"type": "integer", "description": "The [index] of an element from the last observation."},
                    "value": {"type": "string"},
                },
                "required": ["element_index", "value"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press",
            "description": "Press a key such as Enter or Ctrl+A on an element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_index": {"type": "integer", "description": "The [index] of an element from the last observation."},
                    "key": {"type": "string"},
                },
                "required": ["element_index", "key"],
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
