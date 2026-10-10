"""Parse group-chat exports into a flat list of messages.

Supported: WhatsApp Android export, WhatsApp iOS export, Telegram Desktop JSON export.
Multi-line WhatsApp messages are joined onto the previous message.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

SYSTEM_HINTS = ("end-to-end encrypted", "created group", "added", "joined using this group", "left", "<Media omitted>")


@dataclass(frozen=True)
class Message:
    id: int
    ts: datetime | None
    sender: str
    text: str


_ANDROID = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?:\s?[APap][Mm])?) - (.*)$")
_IOS = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\] (.*)$")


def _ts(date: str, time: str) -> datetime | None:
    time = time.replace("\u202f", " ").upper().strip()
    for fmt in ("%d/%m/%y %I:%M:%S %p", "%d/%m/%y %I:%M %p", "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M",
                "%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p"):
        try:
            return datetime.strptime(f"{date} {time}", fmt)
        except ValueError:
            continue
    return None


def parse_whatsapp(text: str) -> list[Message]:
    out: list[dict] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.replace("\u200e", "")
        m = _IOS.match(line) or _ANDROID.match(line)
        if m:
            date, time, rest = m.groups()
            if ": " in rest:
                sender, body = rest.split(": ", 1)
                out.append({"ts": _ts(date, time), "sender": sender.strip(), "text": body})
            else:
                out.append({"ts": _ts(date, time), "sender": "", "text": rest, "system": True})
        elif out and line.strip():
            out[-1]["text"] += "\n" + line
    msgs, i = [], 0
    for d in out:
        if d.get("system") or any(h in d["text"] for h in SYSTEM_HINTS[:1]):
            continue
        i += 1
        msgs.append(Message(i, d["ts"], d["sender"], d["text"].strip()))
    return msgs


def _tg_text(t) -> str:
    if isinstance(t, str):
        return t
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in t)


def parse_telegram(data: str | dict) -> list[Message]:
    d = json.loads(data) if isinstance(data, str) else data
    msgs = []
    for m in d.get("messages", []):
        if m.get("type") != "message":
            continue
        text = _tg_text(m.get("text", "")).strip()
        if not text:
            continue
        ts = datetime.fromisoformat(m["date"]) if m.get("date") else None
        msgs.append(Message(int(m["id"]), ts, m.get("from") or "", text))
    return msgs


def parse_export(content: str) -> list[Message]:
    s = content.lstrip()
    if s.startswith("{"):
        return parse_telegram(s)
    return parse_whatsapp(content)
