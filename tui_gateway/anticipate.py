"""Anticipation: episode log + prompt/parse helpers for ``anticipate.*`` gateway methods.

Plain functions so the plugin hook, the gateway handlers and tests share one
implementation. Everything here is best-effort and never raises on I/O.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

EPISODES_MAX_LINES = 1000
_REF_RE = re.compile(r'@(?:file|image):(?:"([^"]+)"|(\S+))')


def hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home()


def episodes_path(home: Path) -> Path:
    return Path(home) / "memories" / "EPISODES.jsonl"


def read_episodes(home: Path, last_n: int | None = None) -> list[dict]:
    try:
        lines = episodes_path(home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if last_n:
        lines = lines[-last_n:]
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
            if isinstance(rec, dict):
                out.append(rec)
        except ValueError:
            continue
    return out


def append_episode(home: Path, **fields) -> None:
    """Append one JSON line; cap at EPISODES_MAX_LINES (drop oldest). Never raises."""
    try:
        path = episodes_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **fields}
        line = json.dumps(rec, ensure_ascii=False)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        lines.append(line)
        # ponytail: rewrite whole file on every turn; fine for 1000 short lines
        path.write_text("\n".join(lines[-EPISODES_MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        logger.debug("append_episode failed", exc_info=True)


def turn_episode(user_message: str, session_id: str = "") -> dict:
    """Build the ``kind=turn`` record from a raw user message (refs stripped)."""
    text = str(user_message or "")
    files = [os.path.basename(a or b) for a, b in _REF_RE.findall(text)]
    stripped = " ".join(_REF_RE.sub("", text).split())[:200]
    return {"kind": "turn", "text": stripped, "files": files, "session_id": str(session_id or "")}


def dismissed_labels(episodes: list[dict], min_count: int = 2) -> set[str]:
    counts: dict[str, int] = {}
    for rec in episodes:
        if rec.get("kind") == "dismissed" and rec.get("label"):
            counts[rec["label"]] = counts.get(rec["label"], 0) + 1
    return {label for label, n in counts.items() if n >= min_count}


def _read_capped(path: Path, cap: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:cap]
    except OSError:
        return ""


def build_prompt(home: Path, context: dict, sessions: list[dict], limit: int) -> tuple[str, str]:
    """Return (instructions, user_input) for run_oneshot."""
    mem_dir = Path(home) / "memories"
    episodes = read_episodes(home, last_n=60)
    parts = [
        "## MEMORY.md\n" + (_read_capped(mem_dir / "MEMORY.md") or "(無)"),
        "## USER.md\n" + (_read_capped(mem_dir / "USER.md") or "(無)"),
        "## 最近任務片段 (EPISODES.jsonl, 舊→新)\n"
        + ("\n".join(json.dumps(e, ensure_ascii=False) for e in episodes) or "(無)"),
        "## 最近對話 session\n"
        + ("\n".join(
            f"- {s.get('title') or '(無標題)'} — {s.get('preview') or ''}" for s in sessions
        ) or "(無)"),
        "## 目前情境\n" + json.dumps(context, ensure_ascii=False, indent=1),
    ]
    instructions = (
        "你是使用者的個人助理。根據使用者的習慣、過去交給你的任務、以及目前情境，"
        "推測他現在可能想要你做什麼。\n"
        f"最多提出 {limit} 個建議。只有在有具體訊號時才提出（例如：目前開著的檔案"
        "和以前交給你的檔案很像、這個時段常做的固定任務、剪貼簿內容明顯對應某個常見任務）；"
        "沒有具體訊號就回傳空清單。不要編造檔案路徑，files 只能填 recent_files 或 foreground 裡出現的絕對路徑。\n"
        "只輸出嚴格 JSON，不要加任何說明或 code fence：\n"
        '{"suggestions":[{"label":"≤14 中文字","prompt":"送給 AI 的完整指令",'
        '"files":["絕對路徑"],"reason":"一句話"}]}'
    )
    return instructions, "\n\n".join(parts)


def suggestion_id(label: str, prompt: str) -> str:
    return hashlib.sha1(f"{label}\n{prompt}".encode("utf-8")).hexdigest()[:10]


def parse_suggestions(text: str, limit: int, blocked: set[str] = frozenset()) -> list[dict]:
    """Parse model output into suggestion dicts; empty list on any failure."""
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
    if not raw.startswith("{"):
        start, end = raw.find("{"), raw.rfind("}")
        raw = raw[start : end + 1] if 0 <= start < end else ""
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    items = data.get("suggestions") if isinstance(data, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:14]
        prompt = str(item.get("prompt") or "").strip()
        if not label or not prompt or label in blocked:
            continue
        files = [str(f) for f in item.get("files") or [] if isinstance(f, str) and f]
        out.append({
            "id": suggestion_id(label, prompt),
            "label": label,
            "prompt": prompt,
            "files": files,
            "reason": str(item.get("reason") or "").strip(),
        })
        if len(out) >= limit:
            break
    return out
