import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

from proton_mail_mcp_policy import (  # noqa: E402
    FULL_ACTION_LIST,
    MUTATING_TOOL_ORDER,
    READ_TOOL_ORDER,
    apply_call_guards,
    full_function_env,
    is_hidden_tool,
    parse_comma_list,
    visible_tool_names,
)

ALL_32 = list(READ_TOOL_ORDER) + list(MUTATING_TOOL_ORDER)


def test_catalog_is_32_unique_names():
    assert len(ALL_32) == 32
    assert len(set(ALL_32)) == 32
    assert len(FULL_ACTION_LIST.split(",")) == 22


def test_all_token_is_unrestricted_for_actions_and_folders():
    assert parse_comma_list("ALL") is None
    assert parse_comma_list("all") is None
    assert parse_comma_list("*") is None
    assert parse_comma_list("send_email,ALL") is None
    assert parse_comma_list("send_email,save_draft") == ["send_email", "save_draft"]


def test_full_function_lists_every_tool_without_being_approval():
    assert visible_tool_names(full_function_env()) == ALL_32


def test_all_actions_still_need_send_and_empty_folder_flags():
    env = {
        "READONLY": "false",
        "PROTONMAIL_ALLOW_SEND": "false",
        "PROTONMAIL_ALLOWED_ACTIONS": "ALL",
        "ALLOW_EMPTY_FOLDER": "true",
    }
    visible = set(visible_tool_names(env))
    assert "save_draft" in visible
    assert "delete_message" in visible
    assert "empty_folder" in visible
    for name in ("send_email", "reply_email", "reply_all_email", "forward_email"):
        assert name not in visible


def test_readonly_hides_mutations_even_when_all_and_send_are_set():
    env = {
        "READONLY": "true",
        "PROTONMAIL_ALLOW_SEND": "true",
        "PROTONMAIL_ALLOWED_ACTIONS": "ALL",
        "ALLOW_EMPTY_FOLDER": "true",
    }
    assert visible_tool_names(env) == list(READ_TOOL_ORDER)


def test_narrow_default_is_not_the_full_set():
    env = {
        "READONLY": "false",
        "PROTONMAIL_ALLOW_SEND": "false",
        "PROTONMAIL_ALLOWED_ACTIONS": "save_draft,update_message_flags,mark_all_read,move_message,update_message_labels",
        "ALLOW_EMPTY_FOLDER": "false",
    }
    visible = visible_tool_names(env)
    assert visible == list(READ_TOOL_ORDER) + [
        "save_draft",
        "move_message",
        "update_message_flags",
        "mark_all_read",
        "update_message_labels",
    ]
    assert "send_email" not in visible
    assert "delete_message" not in visible


def test_folder_gate_blocks_calls_outside_the_list():
    env = {"PROTONMAIL_ALLOWED_FOLDERS": "INBOX", "PROTONMAIL_ALLOW_SEND": "true", "READONLY": "false"}
    assert apply_call_guards("move_message", {"folder": "INBOX", "destination": "Archive"}, env)
    assert apply_call_guards("move_message", {"folder": "INBOX", "destination": "INBOX"}, env) is None


def test_star_folder_gate_allows_every_folder():
    env = {"PROTONMAIL_ALLOWED_FOLDERS": "*", "READONLY": "false"}
    assert apply_call_guards("delete_message", {"folder": "Archive"}, env) is None
    env["PROTONMAIL_ALLOWED_FOLDERS"] = "ALL"
    assert apply_call_guards("delete_message", {"folder": "Folders/Work"}, env) is None


def test_hidden_tool_is_rejected_before_a_call():
    env = {"READONLY": "false", "PROTONMAIL_ALLOW_SEND": "false", "PROTONMAIL_ALLOWED_ACTIONS": "ALL"}
    assert is_hidden_tool("send_email", env)
    assert apply_call_guards("send_email", {"to": "a@example.invalid"}, env)
