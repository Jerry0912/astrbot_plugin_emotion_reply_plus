import asyncio
import random
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

# 随机表情池参考原插件的内置列表，保留为随机贴表情使用。
RANDOM_EMOJI_LIST = [
    4, 5, 8, 9, 10, 12, 14, 16, 21, 23, 24, 25, 26, 27, 28, 29, 30,
    32, 33, 34, 38, 39, 41, 42, 43, 49, 53, 60, 63, 66, 74, 75, 76,
    78, 79, 85, 89, 96, 97, 98, 99, 100, 101, 102, 103, 104, 106,
    109, 111, 116, 118, 120, 122, 123, 124, 125, 129, 144, 147, 171,
    173, 174, 175, 176, 179, 180, 181, 182, 183, 201, 203, 212, 214,
    219, 222, 227, 232, 240, 243, 246, 262, 264, 265, 266, 267, 268,
    269, 270, 271, 272, 273, 277, 278, 281, 282, 284, 285, 287, 289,
    290, 293, 294, 297, 298, 299, 305, 306, 307, 314, 315, 318, 319,
    320, 322, 324, 326,
    "9728", "9749", "9786", "10024", "10060", "10068", "127801",
    "127817", "127822", "127827", "127836", "127838", "127847",
    "127866", "127867", "127881", "128027", "128046", "128051",
    "128053", "128074", "128076", "128077", "128079", "128089",
    "128102", "128104", "128147", "128157", "128164", "128166",
    "128168", "128170", "128235", "128293", "128513", "128514",
    "128516", "128522", "128524", "128527", "128530", "128531",
    "128532", "128536", "128538", "128540", "128541", "128557",
    "128560", "128563",
]

DEFAULT_PIG_EMOJI_ID = 49


@register(
    "EmotionReplyPlus",
    "OpenAI",
    "引用消息后贴指定表情，或随机贴指定数量表情",
    "1.1.0",
    "https://github.com/QiChenSn/astrbot_qqemotionreply",
)
class EmotionReplyPlus(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config or {}
        self.default_random_num = self._read_int_config("default_random_num", 5)
        self.max_random_num = min(self._read_int_config("max_random_num", 20), 20)
        self.time_interval = self._read_float_config("time_interval", 0.3)
        self.fallback_pig_emoji_id = self._read_int_config(
            "fallback_pig_emoji_id", DEFAULT_PIG_EMOJI_ID
        )
        self.open_admin_mode = bool(self.config.get("open_admin_mode", False))
        admins = self.context.get_config().admins_id or []
        self.admin_list = {str(x) for x in admins}
        logger.info("EmotionReplyPlus 已初始化")

    def _read_int_config(self, key: str, default: int) -> int:
        value = self.config.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except Exception:
            return default

    def _read_float_config(self, key: str, default: float) -> float:
        value = self.config.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except Exception:
            return default

    async def get_reply_info(self, event: AstrMessageEvent) -> tuple[int | None, str | None]:
        reply_id = None
        receiver_id = None
        for message in event.message_obj.message:
            if message.type == "Reply":
                reply_id = message.id
                receiver_id = str(message.sender_id)
                break
        return reply_id, receiver_id

    def normalize_emoji_id(self, raw: str) -> int | str | None:
        raw = str(raw).strip()
        if not raw or not raw.isdigit():
            return None
        # 较长的 Unicode emoji id 用字符串，短的 QQ 系统表情 id 用整数
        if len(raw) >= 5:
            return raw
        return int(raw)

    def extract_emoji_id_from_component(self, comp: Any) -> int | str | None:
        comp_type = str(getattr(comp, "type", "")).lower()
        # 常见非文本表情组件类型优先直接识别
        candidate_attr_names = (
            "emoji_id", "id", "face_id", "faceId", "qqface_id", "marketface_id",
            "tab_id", "result_id", "summary", "text"
        )

        # 先从组件属性里直接找编号
        for attr in candidate_attr_names:
            if hasattr(comp, attr):
                value = getattr(comp, attr)
                if value is None:
                    continue
                value_str = str(value).strip()
                if value_str.isdigit() and comp_type not in {"plain", "text", "reply", "at"}:
                    return int(value_str) if len(value_str) < 5 else value_str

        # 某些适配器会把表情序列化成 [CQ:face,id=14] / [表情:344] / [表情：344]
        for attr in candidate_attr_names:
            if hasattr(comp, attr):
                value = getattr(comp, attr)
                if value is None:
                    continue
                value_str = str(value)
                import re
                patterns = [
                    r"(?:id|emoji_id|face_id)\s*=\s*(\d+)",
                    r"\[表情[:：]\s*(\d+)\]",
                ]
                for pat in patterns:
                    m = re.search(pat, value_str, re.IGNORECASE)
                    if m:
                        digits = m.group(1)
                        return int(digits) if len(digits) < 5 else digits

        return None

    def extract_emoji_id_from_plain_text(self, text: str) -> int | str | None:
        text = str(text).strip()
        if not text:
            return None
        import re
        patterns = [
            r"^\[表情[:：]\s*(\d+)\]$",
            r"^\[CQ:face,id=(\d+)\]$",
            r"^\[CQ:mface,id=(\d+)\]$",
            r"^\d+$",
        ]
        for pat in patterns:
            m = re.match(pat, text, re.IGNORECASE)
            if m:
                digits = m.group(1) if m.groups() else text
                return int(digits) if len(digits) < 5 else digits
        return None

    def query_emoji_id_from_message(self, event: AstrMessageEvent) -> int | str | None:
        # 优先从消息链里的非文本组件中提取，例如直接输入 QQ 表情
        message_chain = event.message_obj.message
        for comp in message_chain:
            comp_type = str(getattr(comp, "type", "")).lower()
            if comp_type in {"reply", "at", "plain", "text"}:
                continue
            found = self.extract_emoji_id_from_component(comp)
            if found is not None:
                return found

        # 如果表情被适配器序列化成纯文本，则再从文本中尝试提取
        plain_parts: list[str] = []
        for comp in message_chain:
            comp_type = str(getattr(comp, "type", "")).lower()
            if comp_type in {"plain", "text"} and hasattr(comp, "text"):
                text = str(getattr(comp, "text", "")).strip()
                if text:
                    plain_parts.append(text)
        for text in plain_parts:
            found = self.extract_emoji_id_from_plain_text(text)
            if found is not None:
                return found
        return None

    async def send_emoji(
        self, event: AstrMessageEvent, message_id: int, emoji_id: int | str
    ) -> bool:
        if event.get_platform_name() != "aiocqhttp":
            logger.error("EmotionReplyPlus 仅支持 aiocqhttp")
            return False

        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot
        payload: dict[str, Any] = {
            "message_id": message_id,
            "emoji_id": emoji_id,
            "set": True,
        }

        try:
            ret = await client.api.call_action("set_msg_emoji_like", **payload)
            logger.info(f"表情 ID: {emoji_id}, 返回结果: {ret}")
            post_result = ret.get("result")
            if post_result == 0:
                return True
            if post_result == 65002:
                logger.warning("已经回应过该表情")
                return False
            if post_result == 65001:
                logger.warning("表情已达上限，无法添加新的表情")
                return False
            logger.warning(f"未知返回结果: {post_result}")
            return False
        except Exception as exc:
            logger.exception(f"贴表情失败: {exc}")
            return False

    def is_admin_protected(self, receiver_id: str | None) -> bool:
        return self.open_admin_mode and receiver_id in self.admin_list

    @filter.command("贴表情")
    async def send_specific_emoji(self, event: AstrMessageEvent, emoji_id: str = ""):
        reply_id, receiver_id = await self.get_reply_info(event)
        if not reply_id:
            yield event.plain_result("请先引用一条消息再贴表情")
            return

        if self.is_admin_protected(receiver_id):
            yield event.plain_result("对管理员启用了保护，不能贴表情")
            return

        emoji_id = str(emoji_id).strip()
        if not emoji_id:
            yield event.plain_result(
                "不告诉我贴什么表情就让我贴，那我只能给你贴个小猪了"
            )
            await self.send_emoji(event, reply_id, self.fallback_pig_emoji_id)
            return

        real_emoji_id = self.normalize_emoji_id(emoji_id)
        if real_emoji_id is None:
            yield event.plain_result("表情编号必须是纯数字")
            return

        ok = await self.send_emoji(event, reply_id, real_emoji_id)
        if not ok:
            yield event.plain_result(f"贴表情失败，编号: {emoji_id}")

    @filter.command("随机贴表情")
    async def send_random_emojis(self, event: AstrMessageEvent, count: int = -1):
        reply_id, receiver_id = await self.get_reply_info(event)
        if not reply_id:
            yield event.plain_result("请先引用一条消息再贴表情")
            return

        if self.is_admin_protected(receiver_id):
            yield event.plain_result("对管理员启用了保护，不能贴表情")
            return

        if count == -1:
            count = self.default_random_num

        if count <= 0:
            yield event.plain_result("随机贴表情数量必须大于 0")
            return

        if count > self.max_random_num:
            count = self.max_random_num
            yield event.plain_result(
                f"贴表情数量超出上限，已自动改为 {self.max_random_num}"
            )

        selected = random.sample(RANDOM_EMOJI_LIST, min(count, len(RANDOM_EMOJI_LIST)))
        for emoji_id in selected:
            await self.send_emoji(event, reply_id, emoji_id)
            await asyncio.sleep(self.time_interval)

    @filter.command("查询表情")
    async def query_emoji(self, event: AstrMessageEvent, emoji_text: str = ""):
        emoji_text = str(emoji_text).strip()

        # 先尝试解析命令参数，例如 /查询表情 [表情：344] 或 /查询表情 344
        if emoji_text:
            found = self.extract_emoji_id_from_plain_text(emoji_text)
            if found is not None:
                yield event.plain_result(f"这个表情的编号是：{found}")
                return

        # 再从整个消息链里找真正的表情组件，例如 /查询表情 + 直接插入一个 QQ 表情
        found = self.query_emoji_id_from_message(event)
        if found is not None:
            yield event.plain_result(f"这个表情的编号是：{found}")
            return

        yield event.plain_result("没识别到表情。请发送 /查询表情 后面跟一个表情，或直接写成 [表情：344]")

    @filter.command("emotionreplyplus帮助", alias={"贴表情帮助plus", "erphelp"})
    async def show_help(self, event: AstrMessageEvent):
        help_text = (
            "EmotionReplyPlus 使用方法：\n\n"
            "1. 指定表情\n"
            "/贴表情 344\n\n"
            "2. 随机贴表情\n"
            "/随机贴表情 5\n\n"
            "3. 查询表情编号\n"
            "/查询表情 [表情：344]\n"
            "或 /查询表情 后面直接跟一个 QQ 表情\n\n"
            "4. 不写编号\n"
            "/贴表情\n"
            "会回复：不告诉我贴什么表情就让我贴，那我只能给你贴个小猪了\n\n"
            "注意：\n"
            "- 必须先引用一条消息\n"
            "- 仅支持 aiocqhttp\n"
            "- 随机贴表情单次上限默认 20"
        )
        yield event.plain_result(help_text)
