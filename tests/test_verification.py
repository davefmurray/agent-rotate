import runpy
from pathlib import Path

import pytest

has_tool_result = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "verify_live.py")
)["has_tool_result"]


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": [{"content": [{"type": "tool_result", "content": "ROTATE_TOOL_OK"}]}]},
        {"input": [{"type": "function_call_output", "output": "ROTATE_TOOL_OK"}]},
        {
            "input": [
                {
                    "type": "custom_tool_call_output",
                    "output": [{"type": "input_text", "text": "ROTATE_TOOL_OK"}],
                }
            ]
        },
    ],
)
def test_live_verification_recognizes_provider_tool_results(payload):
    assert has_tool_result(payload)


def test_live_verification_does_not_mistake_requested_command_for_result():
    assert not has_tool_result(
        {
            "input": [
                {"type": "message", "content": "Run printf ROTATE_TOOL_OK"},
                {"type": "custom_tool_call", "input": "printf ROTATE_TOOL_OK"},
                {"type": "custom_tool_call_output", "output": "permission denied"},
            ]
        }
    )
