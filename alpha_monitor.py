#!/usr/bin/env python3
"""Lightweight Binance Alpha airdrop monitor for alphac.cc."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import smtplib
import socket
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_BASE_URL = "https://alphac.cc"
DEFAULT_TIMEOUT = 15
DEFAULT_SOON_MINUTES = 120
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; AlphaAirdropMonitor/1.0; +https://alphac.cc/)"
)
WATCH_FIELDS = (
    "category",
    "project",
    "points",
    "amount",
    "quantity",
    "date",
    "time",
    "status",
    "schedule_at",
)


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is missing."""


@dataclass
class MonitorConfig:
    base_url: str
    timeout: int
    soon_minutes: int
    state_file: Path
    user_agent: str
    monitor_tz_name: str
    monitor_tz: timezone | ZoneInfo
    notify_on_first_run: bool
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_sender: str | None
    smtp_recipient: str | None
    smtp_ssl: bool
    smtp_starttls: bool
    dry_run: bool


def load_config(args: argparse.Namespace) -> MonitorConfig:
    root = Path(__file__).resolve().parent
    state_file = Path(
        os.getenv("ALPHA_STATE_FILE", str(root / "alpha_monitor_state.json"))
    ).expanduser()
    smtp_sender = os.getenv("ALPHA_EMAIL_FROM") or os.getenv("ALPHA_SMTP_USER")
    smtp_recipient = os.getenv("ALPHA_EMAIL_TO") or smtp_sender
    smtp_ssl = os.getenv("ALPHA_SMTP_SSL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    smtp_starttls = os.getenv("ALPHA_SMTP_STARTTLS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    monitor_tz_name = os.getenv("ALPHA_TIMEZONE", "Asia/Shanghai")
    try:
        monitor_tz: timezone | ZoneInfo = ZoneInfo(monitor_tz_name)
    except ZoneInfoNotFoundError:
        logging.warning("无法识别时区 %s，已回退到 UTC", monitor_tz_name)
        monitor_tz_name = "UTC"
        monitor_tz = timezone.utc
    return MonitorConfig(
        base_url=os.getenv("ALPHA_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        timeout=int(os.getenv("ALPHA_REQUEST_TIMEOUT", str(DEFAULT_TIMEOUT))),
        soon_minutes=int(os.getenv("ALPHA_SOON_MINUTES", str(DEFAULT_SOON_MINUTES))),
        state_file=state_file,
        user_agent=os.getenv("ALPHA_USER_AGENT", DEFAULT_USER_AGENT),
        monitor_tz_name=monitor_tz_name,
        monitor_tz=monitor_tz,
        notify_on_first_run=os.getenv("ALPHA_NOTIFY_ON_FIRST_RUN", "0").strip().lower()
        in {"1", "true", "yes"},
        smtp_host=os.getenv("ALPHA_SMTP_HOST"),
        smtp_port=int(os.getenv("ALPHA_SMTP_PORT", "465")),
        smtp_user=os.getenv("ALPHA_SMTP_USER"),
        smtp_password=os.getenv("ALPHA_SMTP_PASSWORD"),
        smtp_sender=smtp_sender,
        smtp_recipient=smtp_recipient,
        smtp_ssl=smtp_ssl,
        smtp_starttls=smtp_starttls,
        dry_run=args.dry_run,
    )


def http_get_json(url: str, *, timeout: int, user_agent: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        payload = response.read().decode(charset, errors="replace")
    return json.loads(payload)


def fetch_feed(config: MonitorConfig, action: str) -> list[dict[str, Any]]:
    url = f"{config.base_url}/local_data_api.php?{urlencode({'action': action})}"
    payload = http_get_json(url, timeout=config.timeout, user_agent=config.user_agent)
    if not payload.get("success"):
        raise RuntimeError(f"{action} 接口返回失败: {payload}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError(f"{action} 接口数据格式异常: {payload}")
    return data


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.replace("\u00a0", " ").split())
    return str(value)


def parse_schedule(date_text: str, time_text: str, *, now: datetime) -> str:
    raw_values = []
    if date_text and time_text:
        raw_values.append(f"{date_text} {time_text}")
    if time_text:
        raw_values.append(time_text)
    if date_text:
        raw_values.append(date_text)

    for raw_value in raw_values:
        normalized = normalize_datetime_text(raw_value)
        if not normalized:
            continue

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%m-%d %H:%M:%S",
            "%m-%d %H:%M",
            "%m-%d",
            "%H:%M:%S",
            "%H:%M",
        ):
            try:
                parsed = datetime.strptime(normalized, fmt)
            except ValueError:
                continue

            if fmt.startswith("%H"):
                parsed = parsed.replace(
                    year=now.year, month=now.month, day=now.day, tzinfo=now.tzinfo
                )
                if parsed < now - timedelta(minutes=5):
                    parsed += timedelta(days=1)
            elif fmt.startswith("%m"):
                parsed = parsed.replace(year=now.year, tzinfo=now.tzinfo)
            else:
                parsed = parsed.replace(tzinfo=now.tzinfo)
            return parsed.isoformat()

    return ""


def normalize_datetime_text(value: str) -> str:
    normalized = (
        value.replace("年", "-")
        .replace("月", "-")
        .replace("日", " ")
        .replace("/", "-")
        .replace(".", "-")
        .replace("：", ":")
        .replace("T", " ")
    )
    normalized = " ".join(normalized.split())
    lowered = normalized.lower()
    if not normalized or any(word in lowered for word in ("待公布", "tba", "coming soon")):
        return ""
    return normalized.strip(" -")


def normalize_record(raw: dict[str, Any], category: str, *, now: datetime) -> dict[str, str]:
    project = clean_text(raw.get("project"))
    date_text = clean_text(raw.get("date"))
    time_text = clean_text(raw.get("time"))
    record = {
        "key": f"{category}:{project}",
        "category": category,
        "project": project,
        "points": clean_text(raw.get("points")),
        "amount": clean_text(raw.get("amount")),
        "quantity": clean_text(raw.get("quantity")),
        "date": date_text,
        "time": time_text,
        "status": clean_text(raw.get("status")),
        "schedule_at": parse_schedule(date_text, time_text, now=now),
    }
    return record


def snapshot_signature(records: dict[str, dict[str, str]]) -> str:
    payload = json.dumps(
        list(sorted(records.values(), key=lambda item: item["key"])),
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"records": {}, "soon_markers": {}, "signature": "", "initialized": False}
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        logging.warning("状态文件损坏，已忽略旧状态: %s", path)
        return {"records": {}, "soon_markers": {}, "signature": "", "initialized": False}
    return {
        "records": state.get("records", {}),
        "soon_markers": state.get("soon_markers", {}),
        "signature": state.get("signature", ""),
        "initialized": bool(state.get("initialized", False)),
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)


def diff_fields(old: dict[str, str], new: dict[str, str]) -> list[str]:
    changed_fields = []
    for field in WATCH_FIELDS:
        if clean_text(old.get(field)) != clean_text(new.get(field)):
            changed_fields.append(field)
    return changed_fields


def is_starting_soon(record: dict[str, str], *, now: datetime, soon_minutes: int) -> bool:
    if record.get("category") != "upcoming":
        return False
    if record.get("status") == "completed":
        return False
    schedule_at = record.get("schedule_at")
    if not schedule_at:
        return False
    try:
        start_at = datetime.fromisoformat(schedule_at)
    except ValueError:
        return False
    delta = start_at - now
    return timedelta(0) <= delta <= timedelta(minutes=soon_minutes)


def describe_record(record: dict[str, str]) -> str:
    pieces = [record["project"], f"分类: {record['category']}"]
    if record.get("status"):
        pieces.append(f"状态: {record['status']}")
    if record.get("points"):
        pieces.append(f"积分: {record['points']}")
    if record.get("amount"):
        pieces.append(f"数量: {record['amount']}")
    elif record.get("quantity"):
        pieces.append(f"数量: {record['quantity']}")
    if record.get("date"):
        pieces.append(f"日期: {record['date']}")
    if record.get("time"):
        pieces.append(f"时间: {record['time']}")
    return " | ".join(piece for piece in pieces if piece)


def collect_records(config: MonitorConfig, now: datetime) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for category in ("today", "upcoming"):
        items = fetch_feed(config, category)
        for item in items:
            record = normalize_record(item, category, now=now)
            records[record["key"]] = record
    return records


def build_events(
    previous_records: dict[str, dict[str, str]],
    current_records: dict[str, dict[str, str]],
    soon_markers: dict[str, str],
    *,
    now: datetime,
    soon_minutes: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    events: list[dict[str, Any]] = []
    updated_soon_markers = dict(soon_markers)

    for key, record in current_records.items():
        previous = previous_records.get(key)
        if previous is None:
            event_type = "preview" if record["category"] == "upcoming" else "started"
            events.append({"type": event_type, "record": record})
        else:
            changed_fields = diff_fields(previous, record)
            if changed_fields:
                events.append(
                    {
                        "type": "changed",
                        "record": record,
                        "before": previous,
                        "changed_fields": changed_fields,
                    }
                )

        if is_starting_soon(record, now=now, soon_minutes=soon_minutes):
            soon_marker = record.get("schedule_at") or f"{record.get('date')} {record.get('time')}"
            if updated_soon_markers.get(key) != soon_marker:
                events.append({"type": "starting_soon", "record": record})
                updated_soon_markers[key] = soon_marker

    for key, previous in previous_records.items():
        if key not in current_records:
            events.append({"type": "removed", "record": previous})
            updated_soon_markers.pop(key, None)

    active_keys = set(current_records)
    for key in list(updated_soon_markers):
        if key not in active_keys:
            updated_soon_markers.pop(key, None)

    return events, updated_soon_markers


def render_email(events: list[dict[str, Any]], now: datetime) -> tuple[str, str]:
    subject = f"[Alpha监控] 检测到 {len(events)} 条变化"
    lines = [f"检查时间({now.tzname() or 'LOCAL'}): {now.strftime('%Y-%m-%d %H:%M:%S')}", ""]

    for index, event in enumerate(events, start=1):
        record = event["record"]
        event_type = event["type"]
        if event_type == "preview":
            title = "发现新的空投预告"
        elif event_type == "started":
            title = "发现新的今日空投"
        elif event_type == "starting_soon":
            title = "空投即将开始"
        elif event_type == "changed":
            title = "空投状态发生变化"
        elif event_type == "removed":
            title = "空投从列表中消失"
        else:
            title = f"事件: {event_type}"

        lines.append(f"{index}. {title}")
        lines.append(f"   {describe_record(record)}")

        if event_type == "changed":
            before = event["before"]
            for field in event["changed_fields"]:
                lines.append(
                    "   变更 - "
                    f"{field}: {clean_text(before.get(field)) or '-'} -> "
                    f"{clean_text(record.get(field)) or '-'}"
                )
        lines.append("")

    return subject, "\n".join(lines).strip()


def ensure_mail_config(config: MonitorConfig) -> None:
    required = {
        "ALPHA_SMTP_HOST": config.smtp_host,
        "ALPHA_SMTP_USER": config.smtp_user,
        "ALPHA_SMTP_PASSWORD": config.smtp_password,
        "ALPHA_EMAIL_TO": config.smtp_recipient,
    }
    missing = [key for key, value in required.items() if not value]
    if not config.smtp_sender:
        missing.append("ALPHA_EMAIL_FROM or ALPHA_SMTP_USER")
    if missing:
        raise ConfigError("缺少邮件配置: " + ", ".join(missing))


def send_email(config: MonitorConfig, subject: str, body: str) -> None:
    if config.dry_run:
        logging.info("DRY RUN: 跳过发信\n%s\n\n%s", subject, body)
        return

    ensure_mail_config(config)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_sender
    message["To"] = config.smtp_recipient
    message.set_content(body)

    if config.smtp_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as server:
            server.login(config.smtp_user, config.smtp_password)
            server.send_message(message)
        return

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.timeout) as server:
        if config.smtp_starttls:
            server.starttls(context=ssl.create_default_context())
        server.login(config.smtp_user, config.smtp_password)
        server.send_message(message)


def run_check(config: MonitorConfig, *, test_email: bool = False) -> dict[str, Any]:
    now = datetime.now(config.monitor_tz)
    state = load_state(config.state_file)
    previous_records = state.get("records", {})
    current_records = collect_records(config, now)
    current_signature = snapshot_signature(current_records)

    if test_email:
        subject = "[Alpha监控] 测试邮件"
        body = (
            "这是一封测试邮件。\n\n"
            f"检查时间({now.tzname() or 'LOCAL'}): {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"当前 today 条目数: {sum(1 for item in current_records.values() if item['category'] == 'today')}\n"
            f"当前 upcoming 条目数: {sum(1 for item in current_records.values() if item['category'] == 'upcoming')}\n"
        )
        send_email(config, subject, body)
        return {"sent": True, "subject": subject, "events": []}

    if not state.get("initialized"):
        new_state = {
            "records": current_records,
            "soon_markers": {},
            "signature": current_signature,
            "initialized": True,
        }
        save_state(config.state_file, new_state)
        if config.notify_on_first_run and current_records:
            bootstrap_events = [
                {"type": "preview" if item["category"] == "upcoming" else "started", "record": item}
                for item in current_records.values()
            ]
            subject, body = render_email(bootstrap_events, now)
            send_email(config, subject, body)
            return {"sent": True, "subject": subject, "events": bootstrap_events}
        return {
            "sent": False,
            "reason": "bootstrap",
            "records": len(current_records),
        }

    events, soon_markers = build_events(
        previous_records,
        current_records,
        state.get("soon_markers", {}),
        now=now,
        soon_minutes=config.soon_minutes,
    )

    new_state = {
        "records": current_records,
        "soon_markers": soon_markers,
        "signature": current_signature,
        "initialized": True,
    }
    save_state(config.state_file, new_state)

    if not events:
        reason = "no_change" if current_signature == state.get("signature") else "no_event"
        return {"sent": False, "reason": reason, "records": len(current_records)}

    subject, body = render_email(events, now)
    send_email(config, subject, body)
    return {"sent": True, "subject": subject, "events": events}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Monitor alphac.cc Binance Alpha airdrop changes and send email alerts."
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="发送一封测试邮件，顺便验证接口是否可访问。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印结果，不真正发邮件。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出更详细的日志。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    config = load_config(args)

    try:
        result = run_check(config, test_email=args.test_email)
    except ConfigError as exc:
        logging.error("%s", exc)
        return 2
    except (HTTPError, URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as exc:
        logging.error("请求 alphac.cc 失败: %s", exc)
        return 3
    except smtplib.SMTPException as exc:
        logging.error("邮件发送失败: %s", exc)
        return 4
    except Exception as exc:  # pragma: no cover
        logging.exception("运行失败: %s", exc)
        return 1

    if result.get("sent"):
        logging.info("已发送邮件: %s", result.get("subject"))
    else:
        logging.info("本次未发邮件: %s", result.get("reason"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
