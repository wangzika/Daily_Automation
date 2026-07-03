from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "https://api.weixin.qq.com/cgi-bin"


class WeChatPublisherError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeChatConfig:
    app_id: str
    app_secret: str
    thumb_media_id: str
    base_url: str = DEFAULT_BASE_URL
    author: str = "GNSS Paper Bot"
    need_open_comment: int = 0
    only_fans_can_comment: int = 0

    @classmethod
    def from_env(cls, require_thumb_media_id: bool = True) -> "WeChatConfig":
        app_id = os.getenv("WECHAT_APP_ID") or os.getenv("APP_ID")
        app_secret = os.getenv("WECHAT_APP_SECRET") or os.getenv("APP_SECRET")
        thumb_media_id = os.getenv("WECHAT_THUMB_MEDIA_ID")

        missing = []
        if not app_id:
            missing.append("WECHAT_APP_ID or APP_ID")
        if not app_secret:
            missing.append("WECHAT_APP_SECRET or APP_SECRET")
        if require_thumb_media_id and not thumb_media_id:
            missing.append("WECHAT_THUMB_MEDIA_ID")
        if missing:
            raise WeChatPublisherError(
                "Missing WeChat credentials: " + ", ".join(missing)
            )
        return cls(
            app_id=app_id,
            app_secret=app_secret,
            thumb_media_id=thumb_media_id or "",
            base_url=os.getenv("WECHAT_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            author=os.getenv("WECHAT_AUTHOR", "GNSS Paper Bot"),
            need_open_comment=int(os.getenv("WECHAT_COMMENT_OPEN", "0")),
            only_fans_can_comment=int(os.getenv("WECHAT_COMMENT_FANS_ONLY", "0")),
        )


class WeChatPublisher:
    def __init__(self, config: WeChatConfig, timeout: int = 30) -> None:
        self.config = config
        self.timeout = timeout

    def get_access_token(self) -> str:
        params = {
            "grant_type": "client_credential",
            "appid": self.config.app_id,
            "secret": self.config.app_secret,
        }
        data = self._get_json(f"{self.config.base_url}/token?{urllib.parse.urlencode(params)}")
        errcode = data.get("errcode", 0)
        if errcode not in (0, "0"):
            raise WeChatPublisherError(f"WeChat token API returned error: {data}")
        token = data.get("access_token")
        if not token:
            raise WeChatPublisherError(f"WeChat token response missing access_token: {data}")
        return str(token)

    def add_draft(
        self,
        access_token: str,
        title: str,
        content_html: str,
        digest: str,
        content_source_url: str | None = None,
    ) -> str:
        article: dict[str, Any] = {
            "title": title[:64],
            "author": self.config.author,
            "digest": digest[:120],
            "content": content_html,
            "thumb_media_id": self.config.thumb_media_id,
            "need_open_comment": self.config.need_open_comment,
            "only_fans_can_comment": self.config.only_fans_can_comment,
        }
        if content_source_url:
            article["content_source_url"] = content_source_url

        data = self._post_json(
            f"{self.config.base_url}/draft/add?access_token={urllib.parse.quote(access_token)}",
            {"articles": [article]},
        )
        media_id = data.get("media_id")
        if not media_id:
            raise WeChatPublisherError(f"WeChat draft response missing media_id: {data}")
        return str(media_id)

    def submit_publish(self, access_token: str, media_id: str) -> dict[str, Any]:
        return self._post_json(
            f"{self.config.base_url}/freepublish/submit?access_token={urllib.parse.quote(access_token)}",
            {"media_id": media_id},
        )

    def upload_permanent_image(self, access_token: str, image_path: Path) -> dict[str, Any]:
        return self._post_multipart(
            f"{self.config.base_url}/material/add_material?"
            f"access_token={urllib.parse.quote(access_token)}&type=image",
            field_name="media",
            file_path=image_path,
        )

    def upload_article_image(self, access_token: str, image_path: Path) -> str:
        data = self._post_multipart(
            f"{self.config.base_url}/media/uploadimg?"
            f"access_token={urllib.parse.quote(access_token)}",
            field_name="media",
            file_path=image_path,
        )
        url = data.get("url")
        if not url:
            raise WeChatPublisherError(f"WeChat article image response missing url: {data}")
        return str(url)

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"User-Agent": "daily-gnss-slam-digest/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _decode_response(response.read())
        except OSError as exc:
            raise WeChatPublisherError(f"WeChat GET failed: {exc}") from exc

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "daily-gnss-slam-digest/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = _decode_response(response.read())
        except OSError as exc:
            raise WeChatPublisherError(f"WeChat POST failed: {exc}") from exc

        errcode = data.get("errcode", 0)
        if errcode not in (0, "0"):
            raise WeChatPublisherError(f"WeChat API returned error: {data}")
        return data

    def _post_multipart(self, url: str, field_name: str, file_path: Path) -> dict[str, Any]:
        file_path = file_path.expanduser().resolve()
        if not file_path.exists():
            raise WeChatPublisherError(f"File does not exist: {file_path}")

        boundary = "----codex-wechat-boundary-7MA4YWxkTrZu0gW"
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        file_bytes = file_path.read_bytes()
        body = b"".join(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{file_path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                file_bytes,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "daily-gnss-slam-digest/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = _decode_response(response.read())
        except OSError as exc:
            raise WeChatPublisherError(f"WeChat multipart POST failed: {exc}") from exc

        errcode = data.get("errcode", 0)
        if errcode not in (0, "0"):
            raise WeChatPublisherError(f"WeChat API returned error: {data}")
        return data


def _decode_response(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise WeChatPublisherError(f"WeChat response is not JSON: {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise WeChatPublisherError(f"WeChat response is not an object: {data!r}")
    return data
