from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from daily_gnss_slam_digest.notify import (
    DEFAULT_WECHAT_DRAFT_URL,
    EmailConfig,
    NotificationResult,
    notify_automation_summary,
    notify_draft_created,
    quick_command_templates,
    wechat_backend_url,
)


class EmailConfigTest(unittest.TestCase):
    def test_disabled_when_no_email_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = EmailConfig.from_env()

        self.assertFalse(config.enabled)

    def test_accepts_smtp_username_alias_and_infers_qq_host(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMTP_USERNAME": "reader@qq.com",
                "SMTP_PASSWORD": "authorization-code",
                "SMTP_FROM": "reader@qq.com",
            },
            clear=True,
        ):
            config = EmailConfig.from_env()

        self.assertTrue(config.enabled)
        self.assertEqual(config.smtp_host, "smtp.qq.com")
        self.assertEqual(config.smtp_port, 587)
        self.assertEqual(config.smtp_username, "reader@qq.com")
        self.assertEqual(config.mail_from, "reader@qq.com")
        self.assertEqual(config.mail_to, ("reader@qq.com",))
        self.assertTrue(config.use_tls)
        self.assertFalse(config.use_ssl)
        self.assertEqual(config.missing_fields(), ())

    def test_explicit_recipients_are_split(self) -> None:
        with patch.dict(
            os.environ,
            {
                "EMAIL_NOTIFY_TO": "a@example.com,b@example.com; c@example.com",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_FROM": "sender@example.com",
            },
            clear=True,
        ):
            config = EmailConfig.from_env()

        self.assertEqual(config.mail_to, ("a@example.com", "b@example.com", "c@example.com"))

    def test_wechat_backend_url_can_be_overridden(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(wechat_backend_url(), DEFAULT_WECHAT_DRAFT_URL)

        with patch.dict(os.environ, {"WECHAT_BACKEND_URL": "https://example.com/drafts"}, clear=True):
            self.assertEqual(wechat_backend_url(), "https://example.com/drafts")

    def test_step_notification_suppression_skips_draft_email(self) -> None:
        with patch.dict(os.environ, {"EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES": "1"}, clear=True):
            result = notify_draft_created(
                article_type="单篇论文解读",
                title="Example",
                media_id="draft-media-id",
                publish_mode="draft",
            )

        self.assertFalse(result.sent)
        self.assertIn("suppressed", result.reason)

    def test_step_notification_suppression_keeps_automation_summary_enabled(self) -> None:
        with patch.dict(os.environ, {"EMAIL_NOTIFY_SUPPRESS_STEP_MESSAGES": "1"}, clear=True):
            with patch("daily_gnss_slam_digest.notify.EmailNotifier.send") as send:
                send.return_value = NotificationResult(True)

                result = notify_automation_summary(subject="Summary", lines=("done",))

        self.assertTrue(result.sent)
        send.assert_called_once()
        _subject, body = send.call_args.args
        self.assertIn("【快捷指令】", body)
        self.assertIn("主题：论文指令：只生成总结", body)

    def test_quick_commands_can_be_disabled_for_plain_summary(self) -> None:
        with patch.dict(os.environ, {"EMAIL_NOTIFY_INCLUDE_QUICK_COMMANDS": "0"}, clear=True):
            with patch("daily_gnss_slam_digest.notify.EmailNotifier.send") as send:
                send.return_value = NotificationResult(True)

                notify_automation_summary(subject="Summary", lines=("done",))

        _subject, body = send.call_args.args
        self.assertNotIn("【快捷指令】", body)

    def test_quick_command_templates_include_supported_modes(self) -> None:
        text = quick_command_templates()

        self.assertIn("任务：总结", text)
        self.assertIn("任务：总结, 解读", text)
        self.assertIn("任务：解读", text)
        self.assertIn("任务：周报", text)


if __name__ == "__main__":
    unittest.main()
