import contextlib
import logging
import sys
import types

import pytest

from tui_gateway import anticipate
from tui_gateway import methods_session


class _FakeDb:
    def list_sessions_rich(self, **_kw):
        return [{"title": "整理報表", "preview": "幫我整理 Book1.xlsx"}]


@pytest.fixture
def methods(tmp_path, monkeypatch):
    monkeypatch.setattr(anticipate, "hermes_home", lambda: tmp_path)
    calls = {"oneshot": [], "memory": []}
    fenced = '```json\n{"suggestions":[{"label":"整理 Excel 報表","prompt":"整理 Book1.xlsx",' \
             '"files":["C:\\\\x\\\\Book1.xlsx"],"reason":"檔名相似"},' \
             '{"label":"寄週報","prompt":"寄週報給老闆","files":[],"reason":"週三"}]}\n```'
    monkeypatch.setitem(sys.modules, "agent.oneshot", types.SimpleNamespace(
        run_oneshot=lambda **kw: calls["oneshot"].append(kw) or fenced))
    monkeypatch.setitem(sys.modules, "tools.memory_tool", types.SimpleNamespace(
        load_on_disk_store=lambda: types.SimpleNamespace(
            add=lambda target, content: calls["memory"].append((target, content)))))

    @contextlib.contextmanager
    def _session_db(_session):
        yield _FakeDb()

    server = types.SimpleNamespace(
        _methods={}, _profile_scoped=lambda fn: fn, _sessions={}, logger=logging.getLogger("t"),
        _ok=lambda rid, result: {"id": rid, "result": result},
        _err=lambda rid, code, msg, data=None: {"id": rid, "error": {"code": code, "message": msg}},
        _session_db=_session_db, _main_runtime_from_agent=lambda a: None,
    )
    methods_session._registry.install(server)
    return server._methods, calls


def test_suggest_parses_fenced_json_and_filters_twice_dismissed(methods, tmp_path):
    m, calls = methods
    ctx = {"foreground": {"title": "Book1.xlsx - Excel", "process": "EXCEL"}}
    res = m["anticipate.suggest"](1, {"context": ctx, "limit": 3})["result"]
    labels = [s["label"] for s in res["suggestions"]]
    assert labels == ["整理 Excel 報表", "寄週報"]
    s = res["suggestions"][0]
    assert s["files"] == ["C:\\x\\Book1.xlsx"] and s["id"] == anticipate.suggestion_id(s["label"], s["prompt"])
    kw = calls["oneshot"][0]
    assert kw["task"] == "anticipation" and "整理報表" in kw["user_input"] and "Book1.xlsx" in kw["user_input"]

    for _ in range(2):
        assert m["anticipate.feedback"](2, {"id": s["id"], "label": "寄週報", "prompt": "x",
                                            "action": "dismissed"})["result"] == {"ok": True}
    assert calls["memory"] == [("memory", "使用者不想被主動建議：「寄週報」")]
    assert [s["label"] for s in m["anticipate.suggest"](3, {"context": ctx})["result"]["suggestions"]] == ["整理 Excel 報表"]


def test_turn_episode_strips_refs_and_caps(tmp_path):
    rec = anticipate.turn_episode('看一下 @file:"C:\\a b\\Book1.xlsx" 和 @image:C:/pic.png ' + "字" * 300, "s1")
    assert rec["files"] == ["Book1.xlsx", "pic.png"] and "@file" not in rec["text"] and len(rec["text"]) == 200
    for i in range(anticipate.EPISODES_MAX_LINES + 5):
        anticipate.append_episode(tmp_path, kind="turn", text=str(i))
    eps = anticipate.read_episodes(tmp_path)
    assert len(eps) == anticipate.EPISODES_MAX_LINES and eps[-1]["text"] == str(anticipate.EPISODES_MAX_LINES + 4)
    assert anticipate.parse_suggestions("not json", 3) == []
