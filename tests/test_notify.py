from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from daily_gnss_slam_digest.notify import DEFAULT_WECHAT_DRAFT_URL, EmailConfig, wechat_backend_url


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


if __name__ == "__main__":
    unittest.main()
