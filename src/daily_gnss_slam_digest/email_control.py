from __future__ import annotations

import argparse
import email
import hashlib
import html
import imaplib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterable

from .notify import describe_notification_result, notify_automation_summary


VALID_TASKS = ("digest", "deepdive", "weekly")
TASK_ALIASES = {
    "digest": "digest",
    "daily": "digest",
    "recommend": "digest",
    "summary": "digest",
    "summarize": "digest",
    "日报": "digest",
    "推荐": "digest",
    "总结": "digest",
    "论文总结": "digest",
    "只总结": "digest",
    "仅总结": "digest",
    "只生成总结": "digest",
    "只生成日报": "digest",
    "只要总结": "digest",
    "只要日报": "digest",
    "不解读": "digest",
    "不要解读": "digest",
    "不生成解读": "digest",
    "不生成论文解读": "digest",
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
    recent_days: int
    state_path: Path
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
            max_messages=_int_env("EMAIL_COMMAND_MAX_MESSAGES", 100),
            recent_days=_int_env("EMAIL_COMMAND_RECENT_DAYS", 7),
            state_path=Path(
                _first_env("EMAIL_COMMAND_STATE_PATH") or "outputs/email_commands/processed_commands.json"
            ),
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
    parser.add_argument(
        "--force-recent",
        action="store_true",
        help="Allow recent read command emails even if they are older than the latest output run.",
    )
    args = parser.parse_args(argv)

    if not _bool_env("EMAIL_COMMAND_ENABLED", False):
        print("Email command processing disabled. Set EMAIL_COMMAND_ENABLED=1 to enable.")
        return 0

    config = EmailCommandConfig.from_env()
    missing = config.missing_fields()
    if missing:
        print("Email command setup failed: missing " + ", ".join(missing), file=sys.stderr)
        return 2

    processed = process_unread_commands(config, dry_run=args.dry_run, force_recent=args.force_recent)
    print(f"Processed email commands: {processed}")
    return 0


def process_unread_commands(
    config: EmailCommandConfig,
    *,
    dry_run: bool = False,
    force_recent: bool = False,
) -> int:
    processed = 0
    matched = 0
    skipped_processed = 0
    skipped_legacy_read = 0
    processed_fingerprints = _load_processed_fingerprints(config.state_path)
    latest_run_at = _latest_command_run_at()
    with imaplib.IMAP4_SSL(config.imap_host, config.imap_port) as imap:
        imap.login(config.username, config.password)
        status, _ = imap.select(config.folder)
        if status != "OK":
            raise RuntimeError(f"Could not select IMAP folder: {config.folder}")
        unread_ids = _search_message_ids(imap, "UNSEEN")
        recent_ids = _search_message_ids(imap, "SINCE", _imap_since_date(config.recent_days))
        unread_id_set = set(unread_ids)
        message_ids = _newest_message_ids(_merge_message_ids(unread_ids, recent_ids), config.max_messages)
        if dry_run:
            print(
                f"Scanned candidate messages: {len(message_ids)} "
                f"(unread: {len(unread_ids)}, recent: {len(recent_ids)})"
            )
        for message_id in message_ids:
            status, payload = imap.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(payload[0][1])
            command = command_from_message(message, config)
            if command is None:
                continue
            matched += 1
            fingerprint = _message_fingerprint(message)
            if fingerprint in processed_fingerprints:
                skipped_processed += 1
                continue
            if not force_recent and message_id not in unread_id_set and _is_legacy_read_command(message, latest_run_at):
                skipped_legacy_read += 1
                continue
            processed += 1
            if dry_run:
                print(f"Dry run command: {command}")
                continue
            result = execute_command(command)
            print(describe_notification_result(_send_command_summary(command, result)))
            processed_fingerprints.add(fingerprint)
            _save_processed_fingerprints(config.state_path, processed_fingerprints)
            if config.mark_seen:
                imap.store(message_id, "+FLAGS", "\\Seen")
    if dry_run:
        print(
            "Matched command emails: "
            f"{matched}; skipped already processed: {skipped_processed}; "
            f"skipped old read: {skipped_legacy_read}"
        )
    return processed


def command_from_message(message: Message, config: EmailCommandConfig) -> PaperCommand | None:
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    subject = _normalize_command_text(_decode_header(str(message.get("Subject", ""))))
    if sender not in config.allowed_senders:
        return None
    if config.subject_keyword and config.subject_keyword.lower() not in subject.lower():
        return None

    text = _normalize_command_text(subject + "\n" + _message_text(message))
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
    deepdive_limit = _optional_int(fields.get("deepdive_limit") or fields.get("解读数量"))
    if deepdive_limit == 0 or _wants_no_deepdive(fields, text):
        tasks = _without_task(tasks, "deepdive") or ("digest",)
    if "deepdive" in tasks and "digest" not in tasks:
        tasks = ("digest", *tasks)

    return PaperCommand(
        keywords=keywords,
        tasks=tasks,
        mode=mode,
        digest_limit=_optional_int(fields.get("limit") or fields.get("数量")),
        deepdive_limit=deepdive_limit,
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
    env["PYTHONPATH"] = (
        f"{Path.cwd() / 'src'}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(Path.cwd() / "src")
    )

    steps: list[dict[str, object]] = []
    python = _python_executable(env)
    if "digest" in command.tasks:
        digest_step = _run_step("Generate keyword digest", _digest_command(command, run_dir, today, python, env), env)
        if _is_wechat_ip_blocked_step(digest_step) and digest_json.exists():
            digest_step = {
                **digest_step,
                "returncode": 0,
                "note": "WeChat IP whitelist blocked draft creation; local digest files were generated.",
            }
        steps.append(digest_step)
    if "deepdive" in command.tasks and digest_json.exists():
        deepdive_step = _run_step(
            "Generate keyword deep dives",
            _deepdive_command(command, digest_json, run_dir, python, env),
            env,
        )
        if command.mode != "none" and _is_wechat_ip_blocked_step(deepdive_step):
            fallback_step = _run_step(
                "Generate keyword deep dives locally",
                _with_publish_mode(_deepdive_command(command, digest_json, run_dir, python, env), "none"),
                env,
            )
            if int(fallback_step.get("returncode", 1)) == 0:
                deepdive_step = {
                    **deepdive_step,
                    "returncode": 0,
                    "note": "WeChat IP whitelist blocked draft creation; local deep-dive files were generated.",
                }
            else:
                steps.append(deepdive_step)
                deepdive_step = fallback_step
        steps.append(deepdive_step)
    elif "deepdive" in command.tasks:
        steps.append({"label": "Generate keyword deep dives", "returncode": 2, "note": f"missing {digest_json}"})
    if "weekly" in command.tasks:
        steps.append(_run_step("Generate weekly summary", _weekly_command(today, python, env), env))

    if _bool_env("EMAIL_COMMAND_GIT_PUSH", True):
        steps.append(_git_commit_and_push(run_id, run_dir))

    status = 0 if all(int(step.get("returncode", 0)) == 0 for step in steps) else 1
    return {"status": status, "run_id": run_id, "run_dir": str(run_dir), "digest_json": str(digest_json), "steps": steps}


def _run_step(label: str, command: list[str], env: dict[str, str]) -> dict[str, object]:
    print(f"==> {label}: {' '.join(command)}")
    result = subprocess.run(command, env=env, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    output = (result.stdout or "") + (result.stderr or "")
    step: dict[str, object] = {"label": label, "returncode": result.returncode}
    note = _step_note(output)
    if note:
        step["note"] = note
    return step


def _python_executable(env: dict[str, str]) -> str:
    if env.get("AUTOMATION_PYTHON"):
        return env["AUTOMATION_PYTHON"]
    if env.get("PYTHON_BIN"):
        return env["PYTHON_BIN"]
    if Path(".venv/bin/python").exists():
        return ".venv/bin/python"
    return sys.executable


def _digest_command(
    command: PaperCommand,
    run_dir: Path,
    issue_date: str,
    python: str,
    env: dict[str, str],
) -> list[str]:
    return [
        python,
        "-m",
        "daily_gnss_slam_digest",
        "--output-dir",
        str(run_dir),
        "--limit",
        str(_command_int(command.digest_limit, env.get("DIGEST_LIMIT"), 5)),
        "--days-back",
        str(_command_int(command.days_back, env.get("DIGEST_DAYS_BACK"), 180)),
        "--publish-mode",
        command.mode,
        "--issue-date",
        issue_date,
        "--keywords",
        command.keywords,
    ]


def _deepdive_command(
    command: PaperCommand,
    digest_json: Path,
    run_dir: Path,
    python: str,
    env: dict[str, str],
) -> list[str]:
    return [
        python,
        "-m",
        "daily_gnss_slam_digest.deepdive",
        "--input-json",
        str(digest_json),
        "--output-dir",
        str(run_dir / "deepdives"),
        "--limit",
        str(_command_int(command.deepdive_limit, env.get("DEEPDIVE_LIMIT"), 3)),
        "--figures",
        str(_command_int(None, env.get("DEEPDIVE_FIGURES"), 2)),
        "--publish-mode",
        command.mode,
    ]


def _with_publish_mode(command: list[str], mode: str) -> list[str]:
    updated = list(command)
    try:
        mode_index = updated.index("--publish-mode") + 1
    except ValueError:
        return [*updated, "--publish-mode", mode]
    if mode_index < len(updated):
        updated[mode_index] = mode
    return updated


def _weekly_command(issue_date: str, python: str, env: dict[str, str]) -> list[str]:
    return [
        python,
        "-m",
        "daily_gnss_slam_digest.weekly",
        "--input-dir",
        env.get("DIGEST_OUTPUT_DIR", "outputs"),
        "--output-dir",
        env.get("WEEKLY_OUTPUT_DIR", "outputs/weekly"),
        "--end-date",
        issue_date,
        "--days",
        env.get("WEEKLY_SUMMARY_DAYS", "7"),
    ]


def _newest_message_ids(message_ids: list[bytes], max_messages: int) -> list[bytes]:
    if max_messages <= 0:
        return list(reversed(message_ids))
    return list(reversed(message_ids[-max_messages:]))


def _search_message_ids(imap: imaplib.IMAP4_SSL, *criteria: str) -> list[bytes]:
    status, data = imap.search(None, *criteria)
    if status != "OK":
        raise RuntimeError(f"Could not search email commands: {' '.join(criteria)}")
    return data[0].split() if data and data[0] else []


def _merge_message_ids(*groups: Iterable[bytes]) -> list[bytes]:
    unique: dict[bytes, None] = {}
    for group in groups:
        for message_id in group:
            unique[message_id] = None
    return sorted(unique, key=_message_id_number)


def _message_id_number(message_id: bytes) -> int:
    try:
        return int(message_id)
    except ValueError:
        return 0


def _imap_since_date(days: int) -> str:
    since = date.today() - timedelta(days=max(days, 0))
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{since.day:02d}-{months[since.month - 1]}-{since.year}"


def _load_processed_fingerprints(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = data.get("processed", []) if isinstance(data, dict) else []
    return {str(value) for value in values}


def _save_processed_fingerprints(path: Path, fingerprints: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    recent = sorted(fingerprints)[-500:]
    path.write_text(json.dumps({"processed": recent}, ensure_ascii=False, indent=2), encoding="utf-8")


def _message_fingerprint(message: Message) -> str:
    message_id = str(message.get("Message-ID", "")).strip()
    if message_id:
        return f"message-id:{message_id}"
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    subject = _decode_header(str(message.get("Subject", "")))
    date_header = str(message.get("Date", ""))
    text = _message_text(message)
    digest = hashlib.sha256(f"{sender}\n{subject}\n{date_header}\n{text}".encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _latest_command_run_at() -> datetime | None:
    root = Path("outputs/email_commands")
    if not root.exists():
        return None
    latest: datetime | None = None
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            value = datetime.strptime(path.name, "%Y%m%d-%H%M%S").astimezone()
        except ValueError:
            continue
        if latest is None or value > latest:
            latest = value
    return latest


def _is_legacy_read_command(message: Message, latest_run_at: datetime | None) -> bool:
    if latest_run_at is None:
        return False
    message_at = _message_datetime(message)
    if message_at is None:
        return False
    return message_at <= latest_run_at


def _message_datetime(message: Message) -> datetime | None:
    value = str(message.get("Date", "")).strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed.astimezone()


def _git_commit_and_push(run_id: str, run_dir: Path) -> dict[str, object]:
    print("==> Commit and push email command outputs")
    add_paths = [str(run_dir)]
    weekly_dir = Path("outputs/weekly")
    if weekly_dir.exists():
        add_paths.append(str(weekly_dir))
    add = subprocess.run(["git", "add", *add_paths])
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
        key = _normalize_command_text(key).strip().lower().replace(" ", "_").replace("-", "_")
        value = _normalize_command_text(value).strip()
        if key and value:
            fields[key] = value
    return fields


def _wants_no_deepdive(fields: dict[str, str], text: str) -> bool:
    for key in ("deepdive", "deep_dive", "论文解读", "生成解读", "解读"):
        if _is_false_value(fields.get(key)):
            return True
    compact = re.sub(r"\s+", "", text.lower())
    phrases = (
        "不生成论文解读",
        "不要论文解读",
        "不做论文解读",
        "不生成解读",
        "不要解读",
        "不解读",
        "只生成总结",
        "仅生成总结",
        "只要总结",
        "只生成日报",
        "只要日报",
    )
    return any(phrase in compact for phrase in phrases)


def _is_false_value(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"0", "false", "no", "off", "否", "不", "不要", "不生成", "不需要"}


def _without_task(tasks: tuple[str, ...], task: str) -> tuple[str, ...]:
    return tuple(item for item in tasks if item != task)


def _normalize_tasks(value: str) -> tuple[str, ...]:
    tasks: list[str] = []
    for part in re.split(r"[,;，；、\s]+", value.lower()):
        if not part:
            continue
        task = TASK_ALIASES.get(part, part)
        if task in VALID_TASKS and task not in tasks:
            tasks.append(task)
    return tuple(tasks or ("digest", "deepdive"))


def _command_int(command_value: int | None, env_value: str | None, default: int) -> int:
    if command_value is not None:
        return command_value
    parsed = _optional_int(env_value)
    return parsed if parsed is not None else default


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
    value = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    value = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", value)
    return _normalize_command_text(re.sub(r"<[^>]+>", " ", value))


def _normalize_command_text(value: str) -> str:
    value = html.unescape(value)
    return value.replace("\xa0", " ").replace("\u200b", "").replace("\ufeff", "")


def _step_note(output: str) -> str:
    if _is_wechat_ip_blocked_text(output):
        match = re.search(r"invalid ip\s+([0-9.]+)", output)
        ip_hint = f" ({match.group(1)})" if match else ""
        return f"WeChat IP whitelist blocked{ip_hint}."
    if "HTTP 429" in output or "rate limited" in output.lower():
        return "External source rate limited; fallback/cache may have been used."
    return ""


def _is_wechat_ip_blocked_step(step: dict[str, object]) -> bool:
    note = str(step.get("note") or "")
    return "WeChat IP whitelist blocked" in note


def _is_wechat_ip_blocked_text(output: str) -> bool:
    lowered = output.lower()
    return "40164" in lowered and "invalid ip" in lowered and "whitelist" in lowered


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
