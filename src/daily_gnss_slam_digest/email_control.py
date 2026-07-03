from __future__ import annotations

import argparse
import email
import html
import imaplib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable

from .notify import describe_notification_result, notify_automation_summary


VALID_TASKS = ("digest", "deepdive", "weekly")
TASK_ALIASES = {
    "digest": "digest",
    "daily": "digest",
    "recommend": "digest",
    "日报": "digest",
    "推荐": "digest",
    "deepdive": "deepdive",
    "deep-dive": "deepdive",
    "paper": "deepdive",
    "解读": "deepdive",
    "论文解读": "deepdive",
    "weekly": "weekly",
    "week": "weekly",
    "周报": "weekly",
}


@dataclass(frozen=True)
class EmailCommandConfig:
    imap_host: str
    imap_port: int
    username: str
    password: str
    folder: str
    allowed_senders: tuple[str, ...]
    subject_keyword: str
    max_messages: int
    mark_seen: bool
    default_mode: str
    default_tasks: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "EmailCommandConfig":
        username = _first_env("EMAIL_COMMAND_USERNAME", "IMAP_USERNAME", "SMTP_USERNAME")
        password = _first_env("EMAIL_COMMAND_PASSWORD", "IMAP_PASSWORD", "SMTP_PASSWORD")
        host = _first_env("EMAIL_COMMAND_IMAP_HOST", "IMAP_HOST") or _infer_imap_host(username)
        allowed = _split_csv(
            _first_env("EMAIL_COMMAND_ALLOWED_SENDERS", "EMAIL_NOTIFY_TO", "SMTP_USERNAME")
        )
        return cls(
            imap_host=host,
            imap_port=_int_env("EMAIL_COMMAND_IMAP_PORT", 993),
            username=username,
            password=password,
            folder=_first_env("EMAIL_COMMAND_FOLDER", "IMAP_FOLDER") or "INBOX",
            allowed_senders=tuple(address.lower() for address in allowed),
            subject_keyword=_first_env("EMAIL_COMMAND_SUBJECT_KEYWORD") or "论文指令",
            max_messages=_int_env("EMAIL_COMMAND_MAX_MESSAGES", 5),
            mark_seen=_bool_env("EMAIL_COMMAND_MARK_SEEN", True),
            default_mode=_first_env("EMAIL_COMMAND_DEFAULT_MODE") or "draft",
            default_tasks=_normalize_tasks(_first_env("EMAIL_COMMAND_DEFAULT_TASKS") or "digest,deepdive"),
        )

    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.imap_host:
            missing.append("EMAIL_COMMAND_IMAP_HOST")
        if not self.username:
            missing.append("EMAIL_COMMAND_USERNAME")
        if not self.password:
            missing.append("EMAIL_COMMAND_PASSWORD")
        if not self.allowed_senders:
            missing.append("EMAIL_COMMAND_ALLOWED_SENDERS")
        return tuple(missing)


@dataclass(frozen=True)
class PaperCommand:
    keywords: str
    tasks: tuple[str, ...]
    mode: str
    digest_limit: int | None
    deepdive_limit: int | None
    days_back: int | None
    source_subject: str
    source_sender: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process unread email commands for paper generation.")
    parser.add_argument("--dry-run", action="store_true", help="Parse commands without running generation scripts.")
    args = parser.parse_args(argv)

    if not _bool_env("EMAIL_COMMAND_ENABLED", False):
        print("Email command processing disabled. Set EMAIL_COMMAND_ENABLED=1 to enable.")
        return 0

    config = EmailCommandConfig.from_env()
    missing = config.missing_fields()
    if missing:
        print("Email command setup failed: missing " + ", ".join(missing), file=sys.stderr)
        return 2

    processed = process_unread_commands(config, dry_run=args.dry_run)
    print(f"Processed email commands: {processed}")
    return 0


def process_unread_commands(config: EmailCommandConfig, *, dry_run: bool = False) -> int:
    processed = 0
    with imaplib.IMAP4_SSL(config.imap_host, config.imap_port) as imap:
        imap.login(config.username, config.password)
        status, _ = imap.select(config.folder)
        if status != "OK":
            raise RuntimeError(f"Could not select IMAP folder: {config.folder}")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Could not search unread email commands")
        message_ids = _newest_message_ids(data[0].split(), config.max_messages)
        for message_id in message_ids:
            status, payload = imap.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(payload[0][1])
            command = command_from_message(message, config)
            if command is None:
                continue
            processed += 1
            if dry_run:
                print(f"Dry run command: {command}")
                continue
            result = execute_command(command)
            print(describe_notification_result(_send_command_summary(command, result)))
            if config.mark_seen:
                imap.store(message_id, "+FLAGS", "\\Seen")
    return processed


def command_from_message(message: Message, config: EmailCommandConfig) -> PaperCommand | None:
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    subject = _decode_header(str(message.get("Subject", "")))
    if sender not in config.allowed_senders:
        return None
    if config.subject_keyword and config.subject_keyword.lower() not in subject.lower():
        return None

    text = subject + "\n" + _message_text(message)
    fields = _parse_fields(text)
    keywords = fields.get("keywords") or fields.get("keyword") or fields.get("关键词") or fields.get("关键字") or ""
    keywords = keywords.strip()
    if not keywords:
        return None

    mode = (fields.get("mode") or fields.get("模式") or config.default_mode).strip().lower()
    if mode not in {"none", "draft", "publish"}:
        mode = config.default_mode

    tasks_value = fields.get("tasks") or fields.get("task") or fields.get("任务") or fields.get("内容") or ""
    tasks = _normalize_tasks(tasks_value) if tasks_value else config.default_tasks
    if "deepdive" in tasks and "digest" not in tasks:
        tasks = ("digest", *tasks)

    return PaperCommand(
        keywords=keywords,
        tasks=tasks,
        mode=mode,
        digest_limit=_optional_int(fields.get("limit") or fields.get("数量")),
        deepdive_limit=_optional_int(fields.get("deepdive_limit") or fields.get("解读数量")),
        days_back=_optional_int(fields.get("days_back") or fields.get("检索天数")),
        source_subject=subject,
        source_sender=sender,
    )


def execute_command(command: PaperCommand) -> dict[str, object]:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path("outputs/email_commands") / run_id
    today = date.today().isoformat()
    digest_json = run_dir / f"{today}-gnss-slam-digest.json"
    env = os.environ.copy()
    env.update(
        {
            "DIGEST_KEYWORDS": command.keywords,
            "DIGEST_OUTPUT_DIR": str(run_dir),
            "DIGEST_JSON": str(digest_json),
            "DEEPDIVE_OUTPUT_DIR": str(run_dir / "deepdives"),
            "EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES": "1",
        }
    )
    if command.digest_limit is not None:
        env["DIGEST_LIMIT"] = str(command.digest_limit)
    if command.deepdive_limit is not None:
        env["DEEPDIVE_LIMIT"] = str(command.deepdive_limit)
    if command.days_back is not None:
        env["DIGEST_DAYS_BACK"] = str(command.days_back)

    steps: list[dict[str, object]] = []
    if "digest" in command.tasks:
        steps.append(_run_step("Generate keyword digest", ["./scripts/publish_now.sh", command.mode], env))
    if "deepdive" in command.tasks and digest_json.exists():
        steps.append(_run_step("Generate keyword deep dives", ["./scripts/generate_deepdives.sh", command.mode], env))
    elif "deepdive" in command.tasks:
        steps.append({"label": "Generate keyword deep dives", "returncode": 2, "note": f"missing {digest_json}"})
    if "weekly" in command.tasks:
        steps.append(_run_step("Generate weekly summary", ["./scripts/generate_weekly_summary.sh"], env))

    if _bool_env("EMAIL_COMMAND_GIT_PUSH", True):
        steps.append(_git_commit_and_push(run_id))

    status = 0 if all(int(step.get("returncode", 0)) == 0 for step in steps) else 1
    return {"status": status, "run_id": run_id, "run_dir": str(run_dir), "digest_json": str(digest_json), "steps": steps}


def _run_step(label: str, command: list[str], env: dict[str, str]) -> dict[str, object]:
    print(f"==> {label}: {' '.join(command)}")
    result = subprocess.run(command, env=env)
    return {"label": label, "returncode": result.returncode}


def _newest_message_ids(message_ids: list[bytes], max_messages: int) -> list[bytes]:
    if max_messages <= 0:
        return list(reversed(message_ids))
    return list(reversed(message_ids[-max_messages:]))


def _git_commit_and_push(run_id: str) -> dict[str, object]:
    print("==> Commit and push email command outputs")
    add = subprocess.run(["git", "add", "outputs", "README.md", ".env.example", "docs", "scripts", "src", "tests"])
    if add.returncode != 0:
        return {"label": "Commit and push email command outputs", "returncode": add.returncode}
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return {"label": "Commit and push email command outputs", "returncode": 0, "note": "no changes"}
    commit = subprocess.run(["git", "commit", "-m", f"email command {run_id}"])
    if commit.returncode != 0:
        return {"label": "Commit and push email command outputs", "returncode": commit.returncode}
    push = subprocess.run(["git", "push"])
    return {"label": "Commit and push email command outputs", "returncode": push.returncode}


def _send_command_summary(command: PaperCommand, result: dict[str, object]):
    success = int(result["status"]) == 0
    lines = [
        f"邮件论文指令：{'完成' if success else '失败'}",
        "",
        "【关键信息】",
        f"- 关键词：{command.keywords}",
        f"- 任务：{', '.join(command.tasks)}",
        f"- 模式：{command.mode}",
        f"- 输出目录：{Path(str(result['run_dir'])).resolve()}",
        f"- Digest JSON：{Path(str(result['digest_json'])).resolve()}",
        "",
        "【步骤】",
    ]
    for step in result["steps"]:  # type: ignore[index]
        note = f"；{step['note']}" if step.get("note") else ""
        lines.append(f"- {step['label']}：exit {step['returncode']}{note}")
    return notify_automation_summary(
        subject=f"邮件论文指令{'完成' if success else '失败'}｜{command.keywords[:30]}",
        lines=lines,
    )


def _parse_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
        elif "：" in line:
            key, value = line.split("：", 1)
        else:
            continue
        key = key.strip().lower().replace(" ", "_").replace("-", "_")
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _normalize_tasks(value: str) -> tuple[str, ...]:
    tasks: list[str] = []
    for part in re.split(r"[,;，；、\s]+", value.lower()):
        if not part:
            continue
        task = TASK_ALIASES.get(part, part)
        if task in VALID_TASKS and task not in tasks:
            tasks.append(task)
    return tuple(tasks or ("digest", "deepdive"))


def _message_text(message: Message) -> str:
    body = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
            if content_type == "text/html":
                body = _strip_html(body)
            if body.strip():
                return body
    else:
        payload = message.get_payload(decode=True)
        if payload is not None:
            charset = message.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
            if message.get_content_type() == "text/html":
                body = _strip_html(body)
    return body


def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value))


def _decode_header(value: str) -> str:
    decoded = decode_header(value)
    parts: list[str] = []
    for payload, charset in decoded:
        if isinstance(payload, bytes):
            parts.append(payload.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(payload)
    return "".join(parts)


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;，；]+", value) if part.strip()]


def _infer_imap_host(address: str) -> str:
    lowered = address.lower()
    if lowered.endswith("@qq.com"):
        return "imap.qq.com"
    if lowered.endswith("@163.com"):
        return "imap.163.com"
    if lowered.endswith("@126.com"):
        return "imap.126.com"
    if lowered.endswith("@gmail.com"):
        return "imap.gmail.com"
    if lowered.endswith("@outlook.com") or lowered.endswith("@hotmail.com"):
        return "outlook.office365.com"
    return ""


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


if __name__ == "__main__":
    raise SystemExit(main())
