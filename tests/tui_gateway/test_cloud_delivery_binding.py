import threading
import types

from cron.cloud_delivery import origin
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from tui_gateway import methods_session


def test_binding_requires_a_hidden_shell_and_uses_its_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(methods_session, "_sessions_lock", threading.Lock(), raising=False)
    monkeypatch.setattr(methods_session, "_sessions", {
        "visible": {"session_key": "visible", "pending_hidden": False},
        "hidden": {"session_key": "hidden", "pending_hidden": True, "profile_home": str(tmp_path)},
    }, raising=False)
    monkeypatch.setattr(methods_session, "_ok", lambda rid, result: {"result": result}, raising=False)
    monkeypatch.setattr(methods_session, "_err", lambda rid, code, message: {"error": message}, raising=False)
    handler = dict(methods_session._registry._pending)["session.bind_cloud"]
    binding = {"accountUid": "alice", "conversationId": "botconv_" + "a" * 36,
               "instanceId": "botinst_" + "b" * 36}
    assert "error" in handler("1", {"session_id": "visible", "binding": binding})
    assert "error" in handler("1", {"session_id": "missing", "binding": binding})
    assert handler("1", {"session_id": "hidden", "binding": binding})["result"]["bound"]
    token = set_hermes_home_override(tmp_path)
    try:
        assert origin("hidden")["cloud"] == binding
    finally:
        reset_hermes_home_override(token)


def test_compression_keeps_cloud_origin_and_runtime_can_bind_again(tmp_path, monkeypatch):
    from tui_gateway import server
    session = {"session_key": "before", "pending_hidden": True,
               "profile_home": str(tmp_path), "agent": types.SimpleNamespace(session_id="after")}
    monkeypatch.setattr(methods_session, "_sessions_lock", threading.Lock(), raising=False)
    monkeypatch.setattr(methods_session, "_sessions", {"runtime": session}, raising=False)
    monkeypatch.setattr(methods_session, "_ok", lambda rid, result: {"result": result}, raising=False)
    monkeypatch.setattr(methods_session, "_err", lambda rid, code, message: {"error": message}, raising=False)
    monkeypatch.setattr(server, "_transfer_active_session_slot", lambda *a, **kw: True)
    handler = dict(methods_session._registry._pending)["session.bind_cloud"]
    binding = {"accountUid": "alice", "conversationId": "botconv_" + "a" * 36,
               "instanceId": "botinst_" + "b" * 36}
    params = {"session_id": "runtime", "binding": binding}
    assert handler("1", params)["result"]["bound"]
    server._sync_session_key_after_compress("runtime", session, restart_slash_worker=False)
    assert session["session_key"] == "after"
    assert handler("2", params)["result"]["bound"]
    token = set_hermes_home_override(tmp_path)
    try:
        assert origin("after") == origin("before")
        from tools.cronjob_tools import _origin_from_env
        from gateway import session_context
        monkeypatch.setattr(session_context, "get_session_env", lambda key: "after" if key == "HERMES_SESSION_KEY" else "")
        assert _origin_from_env()["cloud"] == binding
    finally:
        reset_hermes_home_override(token)
