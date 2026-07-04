from __future__ import annotations

import os
import smtplib
import argparse
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable


DEFAULT_WECHAT_DRAFT_URL = "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_list&type=10&action=list&lang=zh_CN"


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    reason: str = ""


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    mail_to: tuple[str, ...] = ()
    use_tls: bool = True
    use_ssl: bool = False

    @classmethod
    def from_env(cls) -> "EmailConfig":
        raw_enabled = os.getenv("EMAIL_NOTIFY_ENABLED")
        smtp_username = _first_env("SMTP_USERNAME", "SMTP_USER", "EMAIL_SMTP_USERNAME")
        smtp_password = _first_env("SMTP_PASSWORD", "EMAIL_SMTP_PASSWORD")
        mail_from = _first_env("SMTP_FROM", "EMAIL_NOTIFY_FROM", "EMAIL_FROM", "SMTP_USERNAME", "SMTP_USER")
        recipient_value = _first_env("EMAIL_NOTIFY_TO", "SMTP_TO", "NOTIFY_EMAIL_TO")
        mail_to = _split_addresses(recipient_value)
        if not mail_to:
            mail_to = _split_addresses(mail_from or smtp_username)

        smtp_host = _first_env("SMTP_HOST", "EMAIL_SMTP_HOST")
        if not smtp_host:
            smtp_host = _infer_smtp_host(mail_from or smtp_username)

        use_ssl = _bool_env("SMTP_USE_SSL", False)
        use_tls = _bool_env("SMTP_USE_TLS", not use_ssl)
        smtp_port = _int_env("SMTP_PORT", 465 if use_ssl else 587)

        has_any_config = any(
            (
                smtp_host,
                smtp_username,
                smtp_password,
                mail_from,
                mail_to,
                recipient_value,
            )
        )
        enabled = _bool_text(raw_enabled) if raw_enabled is not None else has_any_config

        return cls(
            enabled=enabled,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            mail_from=mail_from,
            mail_to=tuple(mail_to),
            use_tls=use_tls,
            use_ssl=use_ssl,
        )

    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.smtp_host:
            missing.append("SMTP_HOST")
        if not self.mail_from:
            missing.append("SMTP_FROM")
        if not self.mail_to:
            missing.append("EMAIL_NOTIFY_TO")
        if self.smtp_username and not self.smtp_password:
            missing.append("SMTP_PASSWORD")
        if self.smtp_password and not self.smtp_username:
            missing.append("SMTP_USERNAME")
        return tuple(missing)


class EmailNotifier:
    def __init__(self, config: EmailConfig | None = None, timeout: int = 30) -> None:
        self.config = config or EmailConfig.from_env()
        self.timeout = timeout

    def send(self, subject: str, body: str) -> NotificationResult:
        if not self.config.enabled:
            return NotificationResult(False, "email notification disabled")

        missing = self.config.missing_fields()
        if missing:
            return NotificationResult(False, "missing email config: " + ", ".join(missing))

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.mail_from
        message["To"] = ", ".join(self.config.mail_to)
        message.set_content(body)

        try:
            if self.config.use_ssl:
                with smtplib.SMTP_SSL(
                    self.config.smtp_host,
                    self.config.smtp_port,
                    timeout=self.timeout,
                ) as smtp:
                    self._login_and_send(smtp, message)
            else:
                with smtplib.SMTP(
                    self.config.smtp_host,
                    self.config.smtp_port,
                    timeout=self.timeout,
                ) as smtp:
                    if self.config.use_tls:
                        smtp.starttls()
                    self._login_and_send(smtp, message)
        except (OSError, smtplib.SMTPException) as exc:
            return NotificationResult(False, f"email send failed: {exc}")

        return NotificationResult(True)

    def _login_and_send(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self.config.smtp_username:
            smtp.login(self.config.smtp_username, self.config.smtp_password)
        smtp.send_message(message)


def notify_draft_created(
    *,
    article_type: str,
    title: str,
    media_id: str,
    publish_mode: str,
    local_paths: Iterable[Path] = (),
    source_url: str | None = None,
    extra_lines: Iterable[str] = (),
) -> NotificationResult:
    if step_notifications_suppressed():
        return NotificationResult(False, "step email notification suppressed")

    output_dirs = tuple(dict.fromkeys(str(path.resolve().parent) for path in local_paths))
    lines = [
        "公众号草稿：已创建",
        "",
        "【关键信息】",
        f"- 类型：{article_type}",
        f"- 标题：{title}",
        f"- media_id：{media_id}",
        f"- 模式：{publish_mode}",
        f"- 草稿箱：{wechat_backend_url()}",
    ]
    if source_url:
        lines.append(f"- 来源：{source_url}")
    for output_dir in output_dirs:
        lines.append(f"- 本地输出：{output_dir}")
    lines.extend(extra_lines)
    lines.append("")
    lines.append("请到公众号后台草稿箱检查排版、封面和图片后再发布。")
    _append_quick_commands(lines)
    return EmailNotifier().send(f"公众号草稿已创建｜{title[:36]}", "\n".join(lines))


def notify_publish_issue(
    *,
    article_type: str,
    title: str,
    media_id: str,
    reason: str,
) -> NotificationResult:
    if step_notifications_suppressed():
        return NotificationResult(False, "step email notification suppressed")

    body = "\n".join(
        [
            "公众号正式发布没有成功，但草稿已经保留。",
            f"类型：{article_type}",
            f"标题：{title}",
            f"草稿 media_id：{media_id}",
            f"公众号后台草稿箱：{wechat_backend_url()}",
            f"失败原因：{reason}",
            "",
            "可以在公众号后台手动发布该草稿，或等账号开通发布接口权限后再使用 publish 模式。",
        ]
    )
    return EmailNotifier().send(f"公众号发布失败，草稿已保留｜{title[:32]}", body)


def notify_automation_summary(*, subject: str, lines: Iterable[str]) -> NotificationResult:
    body_lines = list(lines)
    _append_quick_commands(body_lines)
    return EmailNotifier().send(subject, "\n".join(body_lines))


def describe_notification_result(result: NotificationResult) -> str:
    if result.sent:
        return "Sent email notification."
    return f"Email notification skipped: {result.reason or 'unknown reason'}"


def wechat_backend_url() -> str:
    return _first_env("WECHAT_BACKEND_URL", "WECHAT_DRAFT_BACKEND_URL") or DEFAULT_WECHAT_DRAFT_URL


def step_notifications_suppressed() -> bool:
    return _bool_env("EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES", False)


def quick_command_templates() -> str:
    return "\n".join(
        [
            "【快捷指令】",
            "把下面任意一段作为新邮件正文发送给自己，主题包含“论文指令”即可触发。",
            "",
            "1. 只生成每日论文总结",
            "主题：论文指令：只生成总结",
            "关键词：GNSS spoofing detection, robust localization",
            "任务：总结",
            "模式：draft",
            "数量：5",
            "检索天数：180",
            "",
            "2. 生成总结 + 论文解读",
            "主题：论文指令：总结和解读",
            "关键词：3DGS SLAM, LiDAR inertial odometry, neural mapping",
            "任务：总结, 解读",
            "模式：draft",
            "数量：5",
            "解读数量：2",
            "检索天数：180",
            "",
            "3. 只生成一篇重点论文解读",
            "主题：论文指令：只解读论文",
            "关键词：GNSS timing spoofing protection level",
            "任务：解读",
            "模式：draft",
            "数量：3",
            "解读数量：1",
            "",
            "4. 生成周报",
            "主题：论文指令：周报",
            "关键词：robotics navigation localization SLAM manipulation",
            "任务：周报",
            "模式：none",
        ]
    )


def _append_quick_commands(lines: list[str]) -> None:
    if not _bool_env("EMAIL_NOTIFY_INCLUDE_QUICK_COMMANDS", True):
        return
    lines.extend(["", quick_command_templates()])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send an email notification through the configured SMTP account.")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args(argv)

    result = notify_automation_summary(
        subject=args.subject,
        lines=args.body_file.read_text(encoding="utf-8").splitlines(),
    )
    print(describe_notification_result(result))
    return 0 if result.sent else 1


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _split_addresses(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _infer_smtp_host(address: str) -> str:
    lowered = address.lower()
    if lowered.endswith("@qq.com"):
        return "smtp.qq.com"
    if lowered.endswith("@gmail.com"):
        return "smtp.gmail.com"
    if lowered.endswith("@163.com"):
        return "smtp.163.com"
    if lowered.endswith("@126.com"):
        return "smtp.126.com"
    if lowered.endswith("@outlook.com") or lowered.endswith("@hotmail.com"):
        return "smtp-mail.outlook.com"
    return ""


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return _bool_text(value)


def _bool_text(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


if __name__ == "__main__":
    raise SystemExit(main())
