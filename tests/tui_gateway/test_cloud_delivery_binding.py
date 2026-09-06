import threading

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
    assert "error" in handler("1", {"session_key": "visible", "binding": binding})
    assert "error" in handler("1", {"session_key": "missing", "binding": binding})
    assert handler("1", {"session_key": "hidden", "binding": binding})["result"]["bound"]
    token = set_hermes_home_override(tmp_path)
    try:
        assert origin("hidden")["cloud"] == binding
    finally:
        reset_hermes_home_override(token)
