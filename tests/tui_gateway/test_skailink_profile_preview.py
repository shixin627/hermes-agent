from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from tui_gateway import methods_profiles


def test_profile_preview_ignores_timeline_markers(tmp_path):
    from hermes_cli import profiles
    from hermes_state import SessionDB

    profile_dir = tmp_path / "reviewer"
    profile_dir.mkdir()
    db = SessionDB(db_path=profile_dir / "state.db")
    db.create_session("bot-chat", "skailink")
    db.set_session_title("bot-chat", "Bot Chat")
    db.append_message("bot-chat", "assistant", "real latest reply")
    db.append_message(
        "bot-chat",
        "user",
        "[System: The active model for this chat has changed...]",
        display_kind="model_switch",
    )
    db.close()

    profile = SimpleNamespace(
        name="reviewer",
        path=profile_dir,
        is_default=False,
        model="deepseek-v4-flash",
        provider="deepseek",
        description="",
        display_name="Reviewer",
        skill_count=0,
    )
    patches = (
        mock.patch.object(methods_profiles, "_ok", lambda rid, result: {"result": result}, create=True),
        mock.patch.object(methods_profiles, "_err", lambda rid, code, message: {"error": message}, create=True),
        mock.patch.object(methods_profiles, "is_truthy_value", bool, create=True),
        mock.patch.object(profiles, "list_profiles", lambda: [profile]),
    )
    with ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        handler = dict(methods_profiles._registry._pending)["profiles.list"]
        response = handler("request-1", {"include_sessions": True})

    row = response["result"]["profiles"][0]
    assert row["last_session"]["preview"] == "real latest reply"
    assert row["canonical_session"]["preview"] == "real latest reply"
