"""Read-only discovery providers. The application never sees CLI envelopes."""

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    description: str
    url: str | None


@dataclass(frozen=True)
class Section:
    id: str
    name: str


class ProviderError(RuntimeError):
    pass


class CollectorProvider(Protocol):
    name: str

    def search_channels(self, query: str) -> list[Channel]: ...
    def list_sections(self, channel_id: str) -> list[Section]: ...


def redact(value: str) -> str:
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[已脱敏]", value)
    return re.sub(r"(?<!\d)\d{5,}(?!\d)", "[已脱敏]", value)


class MockProvider:
    name = "mock"

    def __init__(self):
        fixture = Path(__file__).with_name("mock_channels.json")
        self.rows = json.loads(fixture.read_text(encoding="utf-8"))

    def search_channels(self, query: str) -> list[Channel]:
        return [
            Channel(row["id"], row["name"], row["description"], row["url"])
            for row in self.rows
            if query in row["queries"]
        ]

    def list_sections(self, channel_id: str) -> list[Section]:
        for row in self.rows:
            if row["id"] == channel_id:
                return [Section(**section) for section in row["sections"]]
        raise ProviderError("模拟频道不存在")


class TencentSkillProvider:
    name = "tencent-skill"
    commands = {
        "search": ("manage", "search-guild-content"),
        "sections": ("manage", "get-guild-channel-list"),
        "latest": ("feed", "get-guild-feeds"),
        "timeline": ("feed", "get-channel-timeline-feeds"),
        "info": ("manage", "get-guild-info"),
        "detail": ("feed", "get-feed-detail"),
    }

    def __init__(self, executable: Path, *, page_size: int = 20):
        if not 1 <= page_size <= 100:
            raise ValueError("主页单页数量必须为 1 至 100")
        self.page_size = page_size
        self.executable = executable.resolve()
        if not self.executable.is_file() or self.executable.suffix.lower() in {".bat", ".cmd", ".ps1"}:
            raise ProviderError("请指定可信的官方 CLI 原生可执行文件")
        self.last_request = 0.0

    def _call(self, operation: str, params: dict) -> dict:
        for attempt in range(2):
            time.sleep(max(0, self.last_request + 2 - time.monotonic()))
            try:
                result = subprocess.run(
                    [str(self.executable), *self.commands[operation], "--json"],
                    input=json.dumps(params).encode(), capture_output=True,
                    timeout=30, shell=False,
                )
                envelope = json.loads(result.stdout)
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                raise ProviderError("官方 CLI 执行失败或未返回 JSON") from exc
            finally:
                self.last_request = time.monotonic()
            if not isinstance(envelope, dict):
                raise ProviderError("官方 CLI 响应格式未知")
            error = envelope.get("error")
            error_code = error.get("code", "") if isinstance(error, dict) else ""
            code = str(envelope.get("retCode", envelope.get("code", error_code)))
            if code == "153":
                if attempt == 0:
                    time.sleep(70)
                    continue
                raise ProviderError("官方 CLI 限流，请稍后运行")
            if result.returncode == 0 and envelope.get("success") is True:
                data = envelope.get("data")
                if isinstance(data, dict):
                    return data
            raise ProviderError("官方 CLI 查询失败，请检查授权、网络及响应兼容性")
        raise ProviderError("官方 CLI 查询失败")

    @staticmethod
    def _rows(data: dict, key: str) -> list[dict]:
        rows = data.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProviderError("官方 CLI 响应结构未验证，已停止导入")
        return rows

    def search_channels(self, query: str, *, max_pages: int = 3) -> list[Channel]:
        channels = {}
        params = {"keyword": query, "scope": "channel"}
        seen_tokens = set()
        for _ in range(max_pages):
            data = self._call("search", params)
            for row in self._rows(data, "channels"):
                channel_id = row.get("guild_id")
                name = row.get("name")
                if not isinstance(channel_id, str) or not re.fullmatch(r"[0-9]+", channel_id):
                    raise ProviderError("频道 ID 格式未知")
                if not isinstance(name, str) or not name.strip():
                    raise ProviderError("频道名称缺失")
                url = row.get("share_url")
                if not isinstance(url, str) or not re.fullmatch(r"https://pd\.qq\.com/s/[A-Za-z0-9_-]+", url):
                    url = None
                description = row.get("profile")
                channels[channel_id] = Channel(
                    channel_id, name, description if isinstance(description, str) else "", url
                )
            token = data.get("next_page_token")
            if data.get("has_more") is False:
                break
            if not token:
                break
            if not isinstance(token, str) or token in seen_tokens:
                raise ProviderError("官方 CLI 返回无效或重复的分页令牌")
            seen_tokens.add(token)
            params["next_page_token"] = token
        return list(channels.values())

    def list_sections(self, channel_id: str) -> list[Section]:
        if not re.fullmatch(r"[0-9]+", channel_id):
            raise ProviderError("频道 ID 格式无效")
        data = self._call("sections", {"guild_id": channel_id})
        sections = []
        for row in self._rows(data, "channels"):
            section_id, name = row.get("channel_id"), row.get("channel_name")
            if not isinstance(section_id, str) or not re.fullmatch(r"[0-9]+", section_id):
                raise ProviderError("版块 ID 格式未知")
            if not isinstance(name, str) or not name.strip():
                raise ProviderError("版块名称缺失")
            sections.append(Section(section_id, name))
        return sections

    def latest_page(self, guild_id: str, section_id: str, cursor: str | None):
        if not re.fullmatch(r"[0-9]+", guild_id) or (section_id and not re.fullmatch(r"[0-9]+", section_id)):
            raise ProviderError("频道或版块 ID 无效")
        params = {"guild_id": guild_id, "count": 20 if section_id else self.page_size}
        if not section_id:
            params["get_type"] = 2
        if section_id:
            params["channel_id"] = section_id
        if cursor:
            params["feed_attach_info"] = cursor
        data = self._call("timeline" if section_id else "latest", params)
        rows = self._rows(data, "feeds")
        posts = []
        for row in rows:
            fields = [row.get("feed_id"), row.get("create_time"), row.get("title", ""), row.get("content_snippet", "")]
            if any(not isinstance(value, str) for value in fields) or not re.fullmatch(r"[A-Za-z0-9_-]+", fields[0]):
                raise ProviderError("帖子响应格式未知")
            title = redact(fields[2])[:200]
            snippet = redact(fields[3])[:500]
            if row.get("images"):
                snippet += " [附图待审]"
            posts.append((fields[0], fields[1], title, snippet))
        if data.get("has_more") is False:
            return posts, None
        cursor = data.get("feed_attach_info")
        if data.get("has_more") is not True or not isinstance(cursor, str) or not cursor:
            raise ProviderError("Feed 分页状态未知")
        return posts, cursor

    def channel_info(self, guild_id: str) -> dict:
        if not re.fullmatch(r"[0-9]+", guild_id):
            raise ProviderError("频道 ID 无效")
        data = self._call("info", {"guild_id": guild_id})
        return {key: data.get(key) for key in ("name", "guild_type", "member_count", "share_url")}

    def post_url(self, guild_id: str, post_id: str) -> str | None:
        if not re.fullmatch(r"[0-9]+", guild_id) or not re.fullmatch(r"[A-Za-z0-9_-]+", post_id):
            raise ProviderError("频道或帖子 ID 无效")
        feed = self._call("detail", {"guild_id": guild_id, "feed_id": post_id}).get("feed")
        if not isinstance(feed, dict):
            raise ProviderError("帖子详情格式未知")
        url = feed.get("share_url")
        return url if isinstance(url, str) else None


class QQBotForumProvider:
    name = "qq-bot"

    def search_channels(self, query: str) -> list[Channel]:
        raise ProviderError("QQ 机器人全局频道搜索能力未验证")

    def list_sections(self, channel_id: str) -> list[Section]:
        raise ProviderError("QQ 机器人校园频道权限未验证")
