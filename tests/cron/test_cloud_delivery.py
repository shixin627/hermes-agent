import pytest

from cron import cloud_delivery as delivery
from hermes_constants import set_hermes_home_override, reset_hermes_home_override


@pytest.fixture
def home(tmp_path):
    token = set_hermes_home_override(tmp_path)
    yield tmp_path
    reset_hermes_home_override(token)


def test_restart_retry_and_account_isolation(home):
    binding = {"accountUid": "alice", "conversationId": "botconv_" + "a" * 36,
               "instanceId": "botinst_" + "b" * 36}
    delivery.bind("shell", binding)
    delivery.bind("shell", binding)
    with pytest.raises(ValueError):
        delivery.bind("shell", {**binding, "accountUid": "bob"})
    job = {"id": "job", "name": "科技新聞", "execution_id": "execution-1",
           "origin": delivery.origin("shell")}
    delivery.enqueue(job, "今日新聞")
    delivery.enqueue(job, "今日新聞")
    assert delivery.pending("bob") == []
    delivery.acknowledge("bob", "execution-1")
    assert len(delivery.pending("alice")) == 1
    with pytest.raises(ValueError):
        delivery.enqueue(job, "different")
    # Every operation reopens SQLite, so this also exercises a restarted reader.
    assert delivery.pending("alice")[0]["conversationId"] == binding["conversationId"]
    delivery.acknowledge("alice", "execution-1")
    assert delivery.pending("alice") == []


def test_cloud_origin_is_captured_and_local_is_respected(home):
    from gateway.session_context import set_session_vars, clear_session_vars
    from tools.cronjob_tools import _origin_from_env, _local_delivery_notice
    from cron.scheduler import _deliver_result
    binding = {"accountUid": "alice", "conversationId": "botconv_" + "a" * 36,
               "instanceId": "botinst_" + "b" * 36}
    delivery.bind("shell", binding)
    tokens = set_session_vars(session_key="shell")
    try:
        job = {"id": "job", "execution_id": "execution-2", "origin": _origin_from_env(), "deliver": "origin"}
    finally:
        clear_session_vars(tokens)
    assert _local_delivery_notice(job, None) is None
    assert _deliver_result(job, "output") is None
    assert len(delivery.pending("alice")) == 1
    delivery.acknowledge("alice", "execution-2")
    assert _deliver_result({**job, "deliver": "local"}, "private") is None
    assert delivery.pending("alice") == []


def test_create_and_explicit_update_persist_the_host_origin(home, monkeypatch):
    import json
    from cron import jobs, scheduler
    from gateway.session_context import set_session_vars, clear_session_vars
    from tools.cronjob_tools import cronjob, _validate_bot_chat_deliver
    monkeypatch.setattr(scheduler, "create_job_with_scheduler_registration", jobs.create_job)
    monkeypatch.setattr(scheduler, "_notify_provider_jobs_changed", lambda: None)
    binding = {"accountUid": "alice", "conversationId": "botconv_" + "a" * 36,
               "instanceId": "botinst_" + "b" * 36}
    delivery.bind("shell", binding)
    old = jobs.create_job(prompt="news", schedule="0 9 * * *", deliver="local")
    tokens = set_session_vars(session_key="shell")
    try:
        created = json.loads(cronjob(action="create", prompt="news", schedule="0 9 * * *"))
        assert created["success"], created
        stored = jobs.get_job(created["job_id"])
        assert stored["deliver"] == "origin"
        assert stored["origin"]["cloud"] == binding
        assert _validate_bot_chat_deliver("bot-chat") is not None
        updated = json.loads(cronjob(action="update", job_id=old["id"], deliver="origin"))
        assert updated["success"], updated
        assert jobs.get_job(old["id"])["origin"]["cloud"] == binding
    finally:
        clear_session_vars(tokens)
