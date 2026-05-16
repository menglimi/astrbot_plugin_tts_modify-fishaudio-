import base64
import builtins
import html
import os
import random
import re
import subprocess
import time
import traceback
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from inspect import isawaitable
from pathlib import Path
from typing import Optional, Set, Tuple
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.message.components import At, Plain, Record
from astrbot.core import file_token_service, logger
from astrbot.core.star.register import register_on_llm_request
from astrbot.core.provider.entities import ProviderRequest
from astrbot.api.provider import LLMResponse
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

class TTSModifyPlugin(Star):
    TTS_TAG_START = "<tts>"
    TTS_TAG_END = "</tts>"
    TTS_BLOCK_PLACEHOLDER_PREFIX = "[[TTSBLOCK:"
    TTS_BLOCK_PLACEHOLDER_SUFFIX = "]]"
    ADMIN_FORCE_VOICE_PROMPT = "本次回复需要包含语音消息"
    CONFIG_KEY_TTS_SETTINGS = "provider_tts_settings"
    CONFIG_KEY_ENABLE = "enable"
    CONFIG_KEY_TTS_PROMPT = "tts_prompt"
    CONFIG_KEY_NOTIFY_FAILURE = "notify_on_failure"
    CONFIG_KEY_AUTO_JP_VOICE_ENABLED = "auto_japanese_voice_enabled"
    CONFIG_KEY_AUTO_JP_VOICE_PROBABILITY = "auto_japanese_voice_probability"
    CONFIG_KEY_AUTO_JP_VOICE_ADMIN_USER_IDS = "auto_japanese_voice_admin_user_ids"
    CONFIG_KEY_AUTO_JP_VOICE_ADMIN_PROBABILITY = "auto_japanese_voice_admin_probability"
    CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_ENTRIES = "admin_mention_keyword_voice_entries"
    CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_KEYWORDS = "admin_mention_keyword_voice_keywords"
    CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_PROBABILITY = "admin_mention_keyword_voice_probability"
    CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_PROMPT = "admin_mention_keyword_voice_prompt"
    CONFIG_KEY_AUTO_JP_VOICE_MAX_CHARS = "auto_japanese_voice_max_chars"
    CONFIG_KEY_AUTO_JP_VOICE_COOLDOWN_SECONDS = "auto_japanese_voice_cooldown_seconds"
    CONFIG_KEY_AUTO_JP_TRANSLATE_PROMPT = "auto_japanese_voice_translate_prompt"
    CONFIG_KEY_AUTO_JP_FULL_CONVERSION_ENABLED = "auto_japanese_voice_full_conversion_enabled"
    CONFIG_KEY_LOCAL_AUDIO_PLAYBACK_ENABLED = "local_audio_playback_enabled"
    CONFIG_KEY_VTUBE_SUBTITLE_SYNC_ENABLED = "vtube_subtitle_sync_enabled"
    INTERNAL_AUTO_JP_TRANSLATE_MARKER = "[TTS_MODIFY_AUTO_JP_TRANSLATE]"
    DEFAULT_NOTIFY_ON_FAILURE = False
    DEFAULT_AUTO_JP_VOICE_ENABLED = False
    DEFAULT_AUTO_JP_VOICE_PROBABILITY = 20.0
    DEFAULT_AUTO_JP_VOICE_ADMIN_USER_IDS = ""
    DEFAULT_AUTO_JP_VOICE_ADMIN_PROBABILITY = -1.0
    DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_ENTRIES = ""
    DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_KEYWORDS = ""
    DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROBABILITY = 0.0
    DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROMPT = (
        "当群聊消息@到管理员且命中指定关键词时，本次回复需要包含语音消息。\n"
        "请根据当前对话自然回应，语气可以更温柔、亲近或安抚，但不要脱离上下文。"
    )
    DEFAULT_AUTO_JP_VOICE_MAX_CHARS = 50
    DEFAULT_AUTO_JP_VOICE_COOLDOWN_SECONDS = 120
    DEFAULT_AUTO_JP_FULL_CONVERSION_ENABLED = False
    DEFAULT_LOCAL_AUDIO_PLAYBACK_ENABLED = False
    DEFAULT_VTUBE_SUBTITLE_SYNC_ENABLED = False
    DEFAULT_AUTO_JP_TRANSLATE_PROMPT = (
        "当你想要发送语音时，使用<tts></tts>标签包裹需要转语音的文本，语音可放在句中的任意位置，注意内容的连续性而不是把一句话说两遍。\n"
        "你必须严格按照以下TTS格式输出内容：\n\n"
        "1. 默认语音消息为日语，除非特别说明其他语言。未经允许不能发送中文语音消息。所有日语内容必须包裹在 <tts> 成对标签中，不嵌套、不遗漏闭合。\n"
        "2. 情感标签请使用日语自然表达，并用[]包裹，参考情感：[嬉しそうに]、[悲しそうに]、[怒ったように]、[落ち着いた調子で]、[緊張した様子で]、[自信ありげに]、[驚いたように]、[満足そうに]、[怯えたように]、[心配そうに]、[落ち込んだように]、[苛立ったように]、[憂鬱そうに]、[共感するように]、[恥ずかしそうに]、[嫌悪感を込めて]、[感動したように]、[誇らしげに]、[リラックスして]、[感謝を込めて]、[興味深そうに]、[皮肉っぽく]。请根据语境选择标签或使用自然语言描述，不要使用英文情感标签。可在[]中加入自然停顿、笑声和其他类人元素，使语音更具吸引力和真实感。\n"
        "3. 输出的语音文本必须翻译成日语，发出语音后，必须在后面换行，附上原本对应的中文内容。\n\n"
        "输出格式示例：\n"
        "1.今天只对你悄悄说一句：<tts>[優しく]おやすみ、いい夢を。</tts>\n"
        "晚安，祝你好梦。\n"
        "2.<tts>[嬉しそうに]今日は本当に嬉しい！</tts>\n"
        "今天真的很开心！\n"
        "3.<tts>大丈夫だよ、[落ち着いた調子で]ゆっくり話して。</tts>\n"
        "没关系，慢慢说。\n"
        "4.<tts>[眠たそうに]もう......本当に[吸い込む]限界だよ。[小さく笑う]でも、君が納得するまで付き合ってあげる。</tts>\n"
        "我真的……已经快到极限了。不过，只要你还没满意，我还是会继续陪着你。"
    )
    EMOTION_TAG_NATURAL_LANGUAGE = {
        "sleepy": {
            "default": "[困倦地说]",
            "japanese": "[眠たそうに]",
        },
        "calm": {
            "default": "[平静地说]",
            "japanese": "[落ち着いた調子で]",
        },
        "shy": {
            "default": "[害羞地说]",
            "japanese": "[照れながら]",
        },
        "embarrassed": {
            "default": "[不好意思地说]",
            "japanese": "[恥ずかしそうに]",
        },
        "delighted": {
            "default": "[开心地说]",
            "japanese": "[嬉しそうに]",
        },
    }
    # 英文中括号标签在 FishAudio 中更容易出现乱码；如后续确认有稳定可用的英文动作标签，
    # 可以再把标准化后的标签名加入白名单。
    ENGLISH_ACTION_TAG_WHITELIST = set()

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)
        self.config = config
        self._auto_jp_voice_last_trigger_at = {}
        self._pending_forced_voice_events = set()
        self._pending_llm_response_events = set()
        self._admin_mention_keyword_voice_last_trigger_at = {}
        self._admin_mention_keyword_voice_last_trigger_date = {}
        self._admin_mention_keyword_voice_user_daily_trigger_date = {}

    def _get_plugin_config(self) -> dict:
        return self.config or {}

    def _refresh_runtime_config(self, event: Optional[AstrMessageEvent] = None) -> dict:
        base_config = self._get_plugin_config()

        try:
            if event is not None:
                runtime_config = self.context.get_config(event.unified_msg_origin)
            else:
                runtime_config = self.context.get_config()
        except KeyError:
            try:
                runtime_config = self.context.get_config()
            except Exception:
                return base_config
        except Exception:
            return base_config

        if not isinstance(runtime_config, dict):
            return base_config

        merged_config = dict(base_config)
        merged_config.update(runtime_config)
        self.config = merged_config
        return merged_config

    def _get_raw_config_value(self, key: str, default=None):
        return self._get_plugin_config().get(key, default)

    def _get_bool_config(self, key: str, default: bool = False) -> bool:
        value = self._get_plugin_config().get(key, default)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("1", "true", "yes", "on"):
                return True
            if normalized in ("0", "false", "no", "off", ""):
                return False
        return bool(value)

    def _get_int_config(self, key: str, default: int = 0) -> int:
        value = self._get_plugin_config().get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _get_float_config(self, key: str, default: float = 0.0) -> float:
        value = self._get_plugin_config().get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _get_text_config(self, key: str, default: str = "") -> str:
        value = self._get_plugin_config().get(key, default)
        if value is None:
            return default
        return str(value)

    @staticmethod
    def _split_id_config_text(text: str) -> Set[str]:
        if not text:
            return set()

        normalized_ids = set()
        for piece in re.split(r"[\s,，、;；|]+", text):
            normalized_piece = TTSModifyPlugin._normalize_qq_id(piece)
            if normalized_piece:
                normalized_ids.add(normalized_piece)
        return normalized_ids

    @staticmethod
    def _split_keyword_config_text(text: str) -> list[str]:
        if not text:
            return []

        keywords = []
        seen_keywords = set()
        for piece in re.split(r"[\r\n,，;；|]+", text):
            normalized_piece = piece.strip()
            if not normalized_piece or normalized_piece in seen_keywords:
                continue
            keywords.append(normalized_piece)
            seen_keywords.add(normalized_piece)
        return keywords

    @classmethod
    def _normalize_entry_keywords(cls, *raw_values) -> list[str]:
        keywords = []
        seen_keywords = set()
        for raw_value in raw_values:
            if raw_value is None:
                continue

            if isinstance(raw_value, (list, tuple, set)):
                split_keywords = []
                for item in raw_value:
                    split_keywords.extend(cls._split_keyword_config_text(str(item)))
            else:
                split_keywords = cls._split_keyword_config_text(str(raw_value))

            for keyword in split_keywords:
                normalized_keyword = keyword.strip()
                folded_keyword = normalized_keyword.casefold()
                if not normalized_keyword or folded_keyword in seen_keywords:
                    continue
                keywords.append(normalized_keyword)
                seen_keywords.add(folded_keyword)

        return keywords

    def _parse_admin_mention_keyword_voice_entries(self) -> list[dict]:
        raw_entries_value = self._get_raw_config_value(
            self.CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_ENTRIES,
            self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_ENTRIES,
        )
        parsed_entries = []

        if isinstance(raw_entries_value, list):
            for line_index, raw_entry in enumerate(raw_entries_value, start=1):
                if not isinstance(raw_entry, dict):
                    logger.warning(
                        f"@管理员关键词词条第 {line_index} 项不是对象，已跳过。"
                    )
                    continue

                if not bool(raw_entry.get("enabled", True)):
                    continue

                keywords = self._normalize_entry_keywords(
                    raw_entry.get("keywords", ""),
                    raw_entry.get("keyword", ""),
                )
                if not keywords:
                    logger.warning(
                        f"@管理员关键词词条第 {line_index} 项缺少关键词，已跳过。"
                    )
                    continue

                primary_keyword = keywords[0]
                entry_name = str(raw_entry.get("name", "")).strip() or primary_keyword

                try:
                    probability = float(raw_entry.get("probability", 100))
                except (TypeError, ValueError):
                    logger.warning(
                        f"@管理员关键词词条 {entry_name!r} 的概率无效，已跳过。"
                    )
                    continue

                try:
                    cooldown_seconds = int(raw_entry.get("cooldown_seconds", 0))
                except (TypeError, ValueError):
                    logger.warning(
                        f"@管理员关键词词条 {entry_name!r} 的冷却秒数无效，已跳过。"
                    )
                    continue

                prompt_text = (
                    str(raw_entry.get("prompt", "")).strip()
                    or self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROMPT
                )
                parsed_entries.append(
                    {
                        "entry_id": f"{line_index}:{entry_name}",
                        "line_index": line_index,
                        "name": entry_name,
                        "keyword": primary_keyword,
                        "keywords": keywords,
                        "probability": max(0.0, min(100.0, probability)),
                        "cooldown_seconds": max(0, cooldown_seconds),
                        "daily_once": bool(raw_entry.get("daily_once", False)),
                        "per_user_daily_once": bool(raw_entry.get("per_user_daily_once", False)),
                        "prompt": prompt_text,
                    }
                )
            return parsed_entries

        raw_entries_text = str(raw_entries_value or "").strip()
        if not raw_entries_text:
            return []

        for line_index, raw_line in enumerate(raw_entries_text.splitlines(), start=1):
            stripped_line = raw_line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                continue

            normalized_line = stripped_line.replace("｜", "|")
            parts = [part.strip() for part in normalized_line.split("|", 3)]
            if len(parts) < 4:
                logger.warning(
                    f"@管理员关键词词条第 {line_index} 行格式无效，"
                    "应为 关键词|概率|冷却秒数|提示词"
                )
                continue

            keyword_text, probability_text, cooldown_text, prompt_text = parts
            keywords = self._normalize_entry_keywords(keyword_text)
            if not keywords:
                logger.warning(f"@管理员关键词词条第 {line_index} 行缺少关键词，已跳过。")
                continue

            primary_keyword = keywords[0]

            try:
                probability = float(probability_text)
            except (TypeError, ValueError):
                logger.warning(
                    f"@管理员关键词词条第 {line_index} 行概率无效: {probability_text!r}，已跳过。"
                )
                continue

            try:
                cooldown_seconds = int(cooldown_text)
            except (TypeError, ValueError):
                logger.warning(
                    f"@管理员关键词词条第 {line_index} 行冷却秒数无效: {cooldown_text!r}，已跳过。"
                )
                continue

            prompt_text = prompt_text.strip() or self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROMPT
            parsed_entries.append(
                {
                    "entry_id": f"{line_index}:{primary_keyword}",
                    "line_index": line_index,
                    "name": primary_keyword,
                    "keyword": primary_keyword,
                    "keywords": keywords,
                    "probability": max(0.0, min(100.0, probability)),
                    "cooldown_seconds": max(0, cooldown_seconds),
                    "daily_once": False,
                    "per_user_daily_once": False,
                    "prompt": prompt_text,
                }
            )

        return parsed_entries

    def _has_admin_mention_keyword_voice_entries_configured(self) -> bool:
        raw_entries_value = self._get_raw_config_value(
            self.CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_ENTRIES,
            self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_ENTRIES,
        )
        if isinstance(raw_entries_value, list):
            return len(raw_entries_value) > 0
        return bool(str(raw_entries_value or "").strip())

    @staticmethod
    def _normalize_qq_id(value) -> str:
        raw_value = str(value).strip() if value is not None else ""
        if not raw_value:
            return ""

        if ":" in raw_value:
            raw_value = raw_value.split(":")[-1].strip()

        digit_only = "".join(builtins.filter(str.isdigit, raw_value))
        return digit_only or raw_value

    @staticmethod
    def _get_group_id_from_event(event: AstrMessageEvent) -> str:
        try:
            group_id = event.get_group_id()
            if group_id:
                return str(group_id).strip()
        except Exception:
            pass

        message_obj = getattr(event, "message_obj", None)
        if message_obj:
            for attr_name in ("group_id", "groupId"):
                value = getattr(message_obj, attr_name, None)
                if value:
                    return str(value).strip()

        return ""

    @staticmethod
    def _get_sender_id_from_event(event: AstrMessageEvent) -> str:
        try:
            sender_id = event.get_sender_id()
            if sender_id:
                return str(sender_id).strip()
        except Exception:
            pass

        message_obj = getattr(event, "message_obj", None)
        if message_obj:
            for attr_name in ("sender_id", "senderId", "user_id", "userId"):
                value = getattr(message_obj, attr_name, None)
                if value:
                    return str(value).strip()

            sender = getattr(message_obj, "sender", None)
            if isinstance(sender, dict):
                for key in ("user_id", "userId"):
                    value = sender.get(key)
                    if value:
                        return str(value).strip()

        return ""

    @classmethod
    def _is_group_message(cls, event: AstrMessageEvent) -> bool:
        if cls._get_group_id_from_event(event):
            return True
        unified_msg_origin = str(getattr(event, "unified_msg_origin", "") or "")
        return ":GroupMessage:" in unified_msg_origin

    def _is_group_admin_sender(self, event: AstrMessageEvent) -> bool:
        if not self._is_group_message(event):
            return False

        configured_admin_ids = self._get_configured_admin_qq_ids()
        if not configured_admin_ids:
            return False

        sender_qq = self._normalize_qq_id(self._get_sender_id_from_event(event))
        if not sender_qq:
            return False

        return sender_qq in configured_admin_ids

    def _get_configured_admin_qq_ids(self) -> Set[str]:
        return self._split_id_config_text(
            self._get_text_config(
                self.CONFIG_KEY_AUTO_JP_VOICE_ADMIN_USER_IDS,
                self.DEFAULT_AUTO_JP_VOICE_ADMIN_USER_IDS,
            )
        )

    @staticmethod
    def _get_event_message_components(event: AstrMessageEvent) -> list:
        try:
            messages = event.get_messages()
            if messages:
                return list(messages)
        except Exception:
            pass

        message_obj = getattr(event, "message_obj", None)
        if message_obj:
            raw_messages = getattr(message_obj, "message", None)
            if isinstance(raw_messages, (list, tuple)):
                return list(raw_messages)

        return []

    @classmethod
    def _extract_mentioned_qq_ids(cls, event: AstrMessageEvent) -> Set[str]:
        mentioned_ids = set()
        mention_patterns = (r"<@(\d+)>", r"\[CQ:at,qq=(\d+)[^\]]*\]", r"\[At:(\d+)\]")

        for comp in cls._get_event_message_components(event):
            qq_value = None

            if isinstance(comp, At):
                qq_value = getattr(comp, "qq", None)
            else:
                comp_type = getattr(comp, "type", None)
                if isinstance(comp_type, str) and comp_type.lower() == "at":
                    qq_value = getattr(comp, "qq", None) or getattr(comp, "target", None)
                    data = getattr(comp, "data", None)
                    if qq_value is None and isinstance(data, dict):
                        qq_value = data.get("qq") or data.get("target")

            normalized_qq = cls._normalize_qq_id(qq_value)
            if normalized_qq:
                mentioned_ids.add(normalized_qq)

            text_value = None
            if isinstance(comp, Plain):
                text_value = getattr(comp, "text", None)
            else:
                comp_type = getattr(comp, "type", None)
                if isinstance(comp_type, str) and comp_type.lower() in {"plain", "text"}:
                    text_value = getattr(comp, "text", None)
                    data = getattr(comp, "data", None)
                    if text_value is None and isinstance(data, dict):
                        text_value = data.get("text")

            if text_value:
                for pattern in mention_patterns:
                    for match in re.findall(pattern, str(text_value)):
                        normalized_match = cls._normalize_qq_id(match)
                        if normalized_match:
                            mentioned_ids.add(normalized_match)

        raw_text = str(
            getattr(getattr(event, "message_obj", None), "message_str", "")
            or getattr(event, "message_str", "")
            or ""
        )
        if raw_text:
            for pattern in mention_patterns:
                for match in re.findall(pattern, raw_text):
                    normalized_match = cls._normalize_qq_id(match)
                    if normalized_match:
                        mentioned_ids.add(normalized_match)

        return mentioned_ids

    def _is_message_mentioning_configured_admin(self, event: AstrMessageEvent) -> bool:
        if not self._is_group_message(event):
            return False

        configured_admin_ids = self._get_configured_admin_qq_ids()
        if not configured_admin_ids:
            return False

        return bool(self._extract_mentioned_qq_ids(event) & configured_admin_ids)

    @classmethod
    def _extract_event_text_for_keyword_match(cls, event: AstrMessageEvent) -> str:
        raw_text = str(
            getattr(getattr(event, "message_obj", None), "message_str", "")
            or getattr(event, "message_str", "")
            or ""
        ).strip()
        if raw_text:
            return raw_text

        parts = []
        for comp in cls._get_event_message_components(event):
            if isinstance(comp, At):
                qq_value = cls._normalize_qq_id(getattr(comp, "qq", None))
                if qq_value:
                    parts.append(f"[At:{qq_value}]")
                continue

            if isinstance(comp, Plain):
                text_value = getattr(comp, "text", None)
                if text_value:
                    parts.append(str(text_value))
                continue

            comp_type = getattr(comp, "type", None)
            if isinstance(comp_type, str) and comp_type.lower() in {"plain", "text"}:
                text_value = getattr(comp, "text", None)
                data = getattr(comp, "data", None)
                if text_value is None and isinstance(data, dict):
                    text_value = data.get("text")
                if text_value:
                    parts.append(str(text_value))

        return "".join(parts).strip()

    @staticmethod
    def _text_contains_any_keyword(text: str, keywords: list[str]) -> bool:
        if not text or not keywords:
            return False

        folded_text = text.casefold()
        return any(keyword.casefold() in folded_text for keyword in keywords if keyword)

    def _matches_admin_voice_target(self, event: AstrMessageEvent) -> bool:
        return self._is_group_admin_sender(event) or self._is_message_mentioning_configured_admin(event)

    def _resolve_admin_target_probability(self, event: AstrMessageEvent) -> Optional[float]:
        if not self._matches_admin_voice_target(event):
            return None

        admin_probability = self._get_float_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_ADMIN_PROBABILITY,
            self.DEFAULT_AUTO_JP_VOICE_ADMIN_PROBABILITY,
        )
        if admin_probability < 0:
            return self._resolve_auto_jp_voice_probability(event)

        return max(0.0, min(100.0, admin_probability))

    def _get_prioritized_admin_auto_jp_probability(self, event: AstrMessageEvent) -> Optional[float]:
        if not self._is_group_admin_sender(event):
            return None
        admin_probability = self._get_float_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_ADMIN_PROBABILITY,
            self.DEFAULT_AUTO_JP_VOICE_ADMIN_PROBABILITY,
        )
        if admin_probability < 0:
            return None

        return max(0.0, min(100.0, admin_probability))

    def _resolve_auto_jp_voice_probability(self, event: AstrMessageEvent) -> float:
        prioritized_admin_probability = self._get_prioritized_admin_auto_jp_probability(event)
        if prioritized_admin_probability is not None:
            return prioritized_admin_probability

        default_probability = self._get_float_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_PROBABILITY,
            self.DEFAULT_AUTO_JP_VOICE_PROBABILITY,
        )
        return max(0.0, min(100.0, default_probability))

    def _should_force_admin_voice_prompt(self, event: AstrMessageEvent) -> bool:
        if not self._get_bool_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_ENABLED,
            self.DEFAULT_AUTO_JP_VOICE_ENABLED,
        ):
            return False

        probability = self._resolve_admin_target_probability(event)
        if probability is None:
            return False

        return probability > 0 and random.random() * 100 < probability

    def _build_forced_voice_prompt_text(self, custom_prompt: str = "") -> str:
        normalized_prompt = (custom_prompt or "").strip()
        if not normalized_prompt:
            return self.ADMIN_FORCE_VOICE_PROMPT

        if self.ADMIN_FORCE_VOICE_PROMPT in normalized_prompt:
            return normalized_prompt

        return f"{self.ADMIN_FORCE_VOICE_PROMPT}\n{normalized_prompt}"

    def _select_admin_mention_keyword_voice_entry(self, event: AstrMessageEvent) -> Optional[dict]:
        entries = self._parse_admin_mention_keyword_voice_entries()
        if not entries:
            return None

        event_text = self._extract_event_text_for_keyword_match(event)
        if not event_text:
            return None

        folded_event_text = event_text.casefold()
        matching_entries = []
        for entry in entries:
            entry_keywords = entry.get("keywords") or self._normalize_entry_keywords(
                entry.get("keyword", "")
            )
            matched_keywords = [
                keyword
                for keyword in entry_keywords
                if keyword and keyword.casefold() in folded_event_text
            ]
            if not matched_keywords:
                continue

            best_matched_keyword = max(matched_keywords, key=len)
            matching_entries.append((entry, best_matched_keyword))

        if not matching_entries:
            return None

        matching_entries.sort(
            key=lambda item: (-len(str(item[1])), int(item[0]["line_index"]))
        )
        selected_entry, matched_keyword = matching_entries[0]
        resolved_entry = dict(selected_entry)
        resolved_entry["matched_keyword"] = matched_keyword
        return resolved_entry

    def _build_admin_mention_keyword_voice_cooldown_key(self, event: AstrMessageEvent, entry: dict) -> str:
        return f"{getattr(event, 'unified_msg_origin', '')}:{entry['entry_id']}"

    def _build_admin_mention_keyword_voice_user_daily_key(self, event: AstrMessageEvent, entry: dict) -> str:
        sender_qq = self._normalize_qq_id(self._get_sender_id_from_event(event))
        if sender_qq:
            return f"{entry['entry_id']}:{sender_qq}"
        return f"{entry['entry_id']}:{getattr(event, 'unified_msg_origin', '')}"

    @staticmethod
    def _get_local_business_date_text() -> str:
        return datetime.now().astimezone().date().isoformat()

    def _evaluate_admin_mention_keyword_voice_entry_trigger(
        self,
        event: AstrMessageEvent,
    ) -> Tuple[bool, Optional[str]]:
        if not self._is_group_message(event):
            return False, None

        if not self._is_message_mentioning_configured_admin(event):
            return False, None

        matched_entry = self._select_admin_mention_keyword_voice_entry(event)
        if not matched_entry:
            return False, None

        cooldown_key = self._build_admin_mention_keyword_voice_cooldown_key(event, matched_entry)
        needs_date_text = bool(matched_entry.get("daily_once", False)) or bool(
            matched_entry.get("per_user_daily_once", False)
        )
        if needs_date_text:
            current_date_text = self._get_local_business_date_text()
            if bool(matched_entry.get("daily_once", False)):
                last_trigger_date = self._admin_mention_keyword_voice_last_trigger_date.get(cooldown_key)
                if last_trigger_date == current_date_text:
                    return True, None
            if bool(matched_entry.get("per_user_daily_once", False)):
                user_daily_key = self._build_admin_mention_keyword_voice_user_daily_key(event, matched_entry)
                last_user_trigger_date = self._admin_mention_keyword_voice_user_daily_trigger_date.get(user_daily_key)
                if last_user_trigger_date == current_date_text:
                    return True, None
        else:
            current_date_text = None
            user_daily_key = None

        cooldown_seconds = int(matched_entry["cooldown_seconds"])
        if cooldown_seconds > 0:
            last_trigger_at = self._admin_mention_keyword_voice_last_trigger_at.get(cooldown_key)
            now = time.monotonic()
            if last_trigger_at is not None and now - last_trigger_at < cooldown_seconds:
                return True, None
        else:
            now = None

        probability = float(matched_entry["probability"])
        if probability <= 0 or random.random() * 100 >= probability:
            return True, None

        if cooldown_seconds > 0:
            self._admin_mention_keyword_voice_last_trigger_at[cooldown_key] = (
                now if now is not None else time.monotonic()
            )
        if current_date_text is not None:
            if bool(matched_entry.get("daily_once", False)):
                self._admin_mention_keyword_voice_last_trigger_date[cooldown_key] = current_date_text
            if bool(matched_entry.get("per_user_daily_once", False)) and user_daily_key is not None:
                self._admin_mention_keyword_voice_user_daily_trigger_date[user_daily_key] = current_date_text

        prompt_text = self._build_forced_voice_prompt_text(str(matched_entry["prompt"]))
        return True, prompt_text

    def _evaluate_legacy_admin_mention_keyword_voice_trigger(
        self,
        event: AstrMessageEvent,
    ) -> Tuple[bool, Optional[str]]:
        if not self._is_group_message(event):
            return False, None

        if not self._is_message_mentioning_configured_admin(event):
            return False, None

        keywords = self._split_keyword_config_text(
            self._get_text_config(
                self.CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_KEYWORDS,
                self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_KEYWORDS,
            )
        )
        if not keywords:
            return False, None

        event_text = self._extract_event_text_for_keyword_match(event)
        if not self._text_contains_any_keyword(event_text, keywords):
            return False, None

        probability = self._get_float_config(
            self.CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_PROBABILITY,
            self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROBABILITY,
        )
        probability = max(0.0, min(100.0, probability))
        if probability <= 0 or random.random() * 100 >= probability:
            return True, None

        custom_prompt = self._get_text_config(
            self.CONFIG_KEY_ADMIN_MENTION_KEYWORD_VOICE_PROMPT,
            self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROMPT,
        ).strip() or self.DEFAULT_ADMIN_MENTION_KEYWORD_VOICE_PROMPT
        return True, self._build_forced_voice_prompt_text(custom_prompt)

    def _evaluate_admin_mention_keyword_voice_trigger(
        self,
        event: AstrMessageEvent,
    ) -> Tuple[bool, Optional[str]]:
        if self._has_admin_mention_keyword_voice_entries_configured():
            return self._evaluate_admin_mention_keyword_voice_entry_trigger(event)

        return self._evaluate_legacy_admin_mention_keyword_voice_trigger(event)

    def _resolve_forced_voice_prompt_injection(self, event: AstrMessageEvent) -> Optional[str]:
        keyword_rule_matched, keyword_prompt = self._evaluate_admin_mention_keyword_voice_trigger(event)
        if keyword_rule_matched:
            return keyword_prompt

        if self._should_force_admin_voice_prompt(event):
            return self.ADMIN_FORCE_VOICE_PROMPT

        return None

    @classmethod
    def _get_event_tracking_key(cls, event: AstrMessageEvent) -> str:
        unified_msg_origin = str(getattr(event, "unified_msg_origin", "") or "")
        message_obj = getattr(event, "message_obj", None)
        message_id = getattr(message_obj, "message_id", None) if message_obj else None
        if message_id not in (None, ""):
            return f"{unified_msg_origin}:{message_id}"

        sender_id = cls._get_sender_id_from_event(event)
        if sender_id:
            return f"{unified_msg_origin}:{sender_id}"

        return f"{unified_msg_origin}:{id(event)}"

    def _mark_pending_forced_voice_event(self, event: AstrMessageEvent):
        self._pending_forced_voice_events.add(self._get_event_tracking_key(event))

    def _consume_pending_forced_voice_event(self, event: AstrMessageEvent) -> bool:
        event_key = self._get_event_tracking_key(event)
        if event_key in self._pending_forced_voice_events:
            self._pending_forced_voice_events.remove(event_key)
            return True
        return False

    def _mark_pending_llm_response_event(self, event: AstrMessageEvent):
        self._pending_llm_response_events.add(self._get_event_tracking_key(event))

    def _consume_pending_llm_response_event(self, event: AstrMessageEvent) -> bool:
        event_key = self._get_event_tracking_key(event)
        if event_key in self._pending_llm_response_events:
            self._pending_llm_response_events.remove(event_key)
            return True
        return False

    @staticmethod
    def _extract_provider_text(response) -> str:
        if not response:
            return ""

        for attr in ("completion_text", "content", "text", "message"):
            value = getattr(response, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    @staticmethod
    def _cleanup_translated_japanese_text(text: str) -> str:
        if not text:
            return ""

        cleaned = text.strip()
        cleaned = re.sub(r"^(?:日语|日文|日本語|翻译|翻譯)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)

        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()

        return cleaned.strip()

    @staticmethod
    def _chain_contains_audio(chain) -> bool:
        for comp in chain:
            if isinstance(comp, Record):
                return True
        return False

    @classmethod
    def _chain_contains_tts_marker(cls, chain) -> bool:
        for comp in chain:
            if isinstance(comp, Plain) and cls._contains_tts_marker(comp.text):
                return True
        return False

    def _extract_leading_record_segment(self, chain: list) -> tuple[Optional[list], list]:
        """提取“首个可见组件是语音且后续还有文本”的前置语音段，避免与正文混发。"""
        if not chain:
            return None, chain

        first_visible_index = None
        for index, comp in enumerate(chain):
            if isinstance(comp, At):
                continue
            if isinstance(comp, Plain) and not (comp.text or "").strip():
                continue
            first_visible_index = index
            break

        if first_visible_index is None:
            return None, chain

        first_visible_component = chain[first_visible_index]
        if not isinstance(first_visible_component, Record):
            return None, chain

        next_visible_plain_index = None
        for index in range(first_visible_index + 1, len(chain)):
            comp = chain[index]
            if isinstance(comp, Plain) and (comp.text or "").strip():
                next_visible_plain_index = index
                break

        if next_visible_plain_index is None:
            return None, chain

        leading_segment = [chain[first_visible_index]]
        remaining_chain = list(chain[:first_visible_index]) + list(chain[first_visible_index + 1:])
        return leading_segment, remaining_chain

    async def _send_leading_record_segment_if_needed(
        self,
        event: AstrMessageEvent,
        result,
        chain: list,
    ) -> list:
        if getattr(result, "__tts_modify_leading_record_sent", False):
            return chain

        leading_segment, remaining_chain = self._extract_leading_record_segment(chain)
        if not leading_segment:
            return chain

        try:
            message_chain = MessageChain()
            message_chain.chain = leading_segment
            await self.context.send_message(event.unified_msg_origin, message_chain)
            setattr(result, "__tts_modify_leading_record_sent", True)
            logger.debug("检测到回复首项为语音且后续存在文本，已先行单独发送首条语音。")
            return remaining_chain
        except Exception as e:
            logger.error(f"首条语音单独发送失败，保留原消息链继续发送: {e}")
            logger.debug(traceback.format_exc())
            return chain

    @staticmethod
    def _extract_tts_formatted_message(text: str) -> str:
        if not text:
            return ""

        cleaned = text.strip()
        match = re.search(
            r"(?s)(.*?<tts>.*?</tts>\s*(?:\r?\n.*)?)",
            cleaned,
        )
        if match:
            return match.group(1).strip()
        return cleaned

    @classmethod
    def _contains_tts_marker(cls, text: str) -> bool:
        if not text:
            return False
        return cls.TTS_TAG_START in text or cls.TTS_TAG_END in text

    @classmethod
    def _strip_tts_markers(cls, text: str) -> str:
        if not text:
            return ""
        return text.replace(cls.TTS_TAG_START, "").replace(cls.TTS_TAG_END, "")

    @staticmethod
    def _sanitize_plain_output_text(text: str) -> str:
        if not text:
            return ""
        sanitized = text.replace("\\n", " ")
        sanitized = sanitized.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        sanitized = re.sub(r"\s+", " ", sanitized)
        return sanitized.strip()

    @staticmethod
    def _contains_japanese_kana(text: str) -> bool:
        if not text:
            return False
        return bool(re.search(r"[\u3040-\u30FF\u31F0-\u31FF\uFF66-\uFF9F]", text))

    @classmethod
    def _build_tts_failure_plain_text(
        cls,
        fallback_text: str,
        notify_failure: bool,
    ) -> str:
        sanitized_fallback_text = cls._sanitize_plain_output_text(fallback_text)
        if cls._contains_japanese_kana(sanitized_fallback_text):
            return "[TTS失败]" if notify_failure else ""
        if notify_failure:
            return cls._sanitize_plain_output_text(f"[TTS失败] {sanitized_fallback_text}")
        return sanitized_fallback_text

    @staticmethod
    def _looks_like_non_japanese_tts_text(text: str) -> bool:
        if not text:
            return False

        # 去掉情绪/动作标签后，再判断正文语言，避免仅因日语标签存在就误判为日语正文。
        content = re.sub(r"\[[^\[\]]*\]", " ", text)
        content = re.sub(r"\s+", " ", content).strip()
        if not content:
            return False

        kana_count = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\uFF66-\uFF9F]", content))
        han_count = len(re.findall(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]", content))

        if han_count == 0:
            return False

        # 正文几乎没有假名、却有较明显的汉字量时，极大概率是中文，不交给日语 TTS 去念。
        return kana_count == 0 or han_count >= max(4, kana_count * 3)

    @classmethod
    def _encode_tts_blocks_for_splitter(cls, text: str) -> str:
        if not text or cls.TTS_TAG_START not in text or cls.TTS_TAG_END not in text:
            return text

        pattern = re.compile(
            rf"{re.escape(cls.TTS_TAG_START)}.*?{re.escape(cls.TTS_TAG_END)}",
            re.DOTALL,
        )

        def repl(match: re.Match) -> str:
            raw_block = match.group(0)
            encoded = base64.urlsafe_b64encode(raw_block.encode("utf-8")).decode("ascii")
            return f"{cls.TTS_BLOCK_PLACEHOLDER_PREFIX}{encoded}{cls.TTS_BLOCK_PLACEHOLDER_SUFFIX}"

        return pattern.sub(repl, text)

    @classmethod
    def _decode_tts_blocks_from_splitter(cls, text: str) -> str:
        if not text or cls.TTS_BLOCK_PLACEHOLDER_PREFIX not in text:
            return text

        pattern = re.compile(
            rf"{re.escape(cls.TTS_BLOCK_PLACEHOLDER_PREFIX)}([A-Za-z0-9_\-=]+){re.escape(cls.TTS_BLOCK_PLACEHOLDER_SUFFIX)}"
        )

        def repl(match: re.Match) -> str:
            encoded = match.group(1)
            try:
                return base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
            except Exception:
                logger.warning(f"TTS 占位块解码失败，保留原文: {encoded!r}")
                return match.group(0)

        return pattern.sub(repl, text)

    @classmethod
    def _wrap_plain_japanese_as_tts(cls, translated_text: str, original_text: str) -> str:
        cleaned_text = cls._cleanup_translated_japanese_text(translated_text)
        if not cleaned_text:
            return ""

        if cls.TTS_TAG_START in cleaned_text and cls.TTS_TAG_END in cleaned_text:
            return cleaned_text

        normalized_tts_text = cls._normalize_tts_text(cleaned_text)
        if not normalized_tts_text:
            return ""

        original_plain_text = (original_text or "").strip()
        if original_plain_text:
            return f"{cls.TTS_TAG_START}{normalized_tts_text}{cls.TTS_TAG_END}\n{original_plain_text}"
        return f"{cls.TTS_TAG_START}{normalized_tts_text}{cls.TTS_TAG_END}"

    @classmethod
    def _normalize_similarity_text(text: str) -> str:
        if not text:
            return ""

        normalized = html.unescape(text)
        normalized = normalized.lower()
        normalized = unicodedata.normalize("NFKC", normalized)
        normalized = re.sub(r"\s+", "", normalized)
        normalized = re.sub(r"[，。！？、,.!?:：;；“”\"'‘’（）()\[\]{}<>《》「」『』…~\-]+", "", normalized)
        return normalized

    @classmethod
    def _texts_are_similar(cls, left: str, right: str, threshold: float = 0.72) -> bool:
        normalized_left = cls._normalize_similarity_text(left)
        normalized_right = cls._normalize_similarity_text(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left in normalized_right or normalized_right in normalized_left:
            return True
        return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= threshold

    @staticmethod
    def _clean_auto_segment_text(text: str) -> str:
        if not text:
            return ""
        cleaned = text.strip()
        cleaned = re.sub(r"^\s*[\-\d\.\):：]+\s*", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def _extract_tail_after_prefix(cls, original_text: str, prefix_text: str) -> str:
        if not original_text or not prefix_text:
            return ""

        stripped_original = original_text.strip()
        stripped_prefix = prefix_text.strip()
        if stripped_original.startswith(stripped_prefix):
            return stripped_original[len(stripped_prefix):].lstrip("，。！？、,.!?:：;； \n")

        pieces = re.split(r"(?<=[。！？!?；;])", stripped_original)
        pieces = [piece.strip() for piece in pieces if piece.strip()]
        if len(pieces) >= 2:
            return pieces[-1]

        return ""

    @classmethod
    def _extract_prefix_before_tail(cls, original_text: str) -> str:
        if not original_text:
            return ""

        stripped_original = original_text.strip()
        pieces = re.split(r"(?<=[。！？!?；;])", stripped_original)
        pieces = [piece.strip() for piece in pieces if piece.strip()]

        if len(pieces) >= 2:
            return "".join(pieces[:-1]).strip()

        comma_pieces = re.split(r"(?<=[，、,:：])", stripped_original)
        comma_pieces = [piece.strip() for piece in comma_pieces if piece.strip()]
        if len(comma_pieces) >= 2:
            return "".join(comma_pieces[:-1]).strip()

        return ""

    @classmethod
    def _build_canonical_auto_tts_message(cls, generated_text: str, original_text: str) -> str:
        """自动模式下保留自然衔接的前后文本，但剔除与语音语义明显重复的部分。"""
        if not generated_text:
            return ""

        match = re.search(
            rf"{re.escape(cls.TTS_TAG_START)}(.*?){re.escape(cls.TTS_TAG_END)}",
            generated_text,
            re.DOTALL,
        )
        if not match:
            return ""

        tts_content = match.group(1).strip()
        if not tts_content:
            return ""

        prefix_text = cls._clean_auto_segment_text(generated_text[:match.start()])
        suffix_text = cls._clean_auto_segment_text(generated_text[match.end():])

        if prefix_text and cls._texts_are_similar(prefix_text, original_text):
            derived_prefix = cls._extract_prefix_before_tail(original_text)
            if derived_prefix and not cls._texts_are_similar(derived_prefix, original_text):
                prefix_text = cls._clean_auto_segment_text(derived_prefix)
                suffix_text = ""

        if suffix_text and cls._texts_are_similar(suffix_text, original_text):
            derived_tail = cls._extract_tail_after_prefix(original_text, prefix_text)
            suffix_text = cls._clean_auto_segment_text(derived_tail) if derived_tail else ""

        if suffix_text and cls._texts_are_similar(prefix_text, suffix_text):
            suffix_text = ""

        if suffix_text and prefix_text and cls._texts_are_similar(original_text, suffix_text):
            derived_tail = cls._extract_tail_after_prefix(original_text, prefix_text)
            if derived_tail and not cls._texts_are_similar(prefix_text, derived_tail):
                suffix_text = cls._clean_auto_segment_text(derived_tail)

        if not suffix_text and prefix_text:
            derived_tail = cls._extract_tail_after_prefix(original_text, prefix_text)
            if derived_tail and not cls._texts_are_similar(prefix_text, derived_tail):
                suffix_text = cls._clean_auto_segment_text(derived_tail)

        if suffix_text and cls._texts_are_similar(prefix_text, suffix_text):
            suffix_text = ""

        canonical_parts = []
        if prefix_text:
            canonical_parts.append(prefix_text)
        canonical_parts.append(f"{cls.TTS_TAG_START}{tts_content}{cls.TTS_TAG_END}")
        if suffix_text:
            canonical_parts.append(suffix_text)

        return "\n".join(canonical_parts)

    @classmethod
    def _build_full_auto_tts_message(cls, generated_text: str, original_text: str) -> str:
        """完全转换模式：整段原文只对应一个完整 TTS 片段，文本区保留原文。"""
        if not generated_text:
            return ""

        match = re.search(
            rf"{re.escape(cls.TTS_TAG_START)}(.*?){re.escape(cls.TTS_TAG_END)}",
            generated_text,
            re.DOTALL,
        )
        if not match:
            return cls._wrap_plain_japanese_as_tts(generated_text, original_text)

        tts_content = match.group(1).strip()
        if not tts_content:
            return ""

        parts = [f"{cls.TTS_TAG_START}{tts_content}{cls.TTS_TAG_END}"]
        original_plain_text = (original_text or "").strip()
        if original_plain_text:
            parts.append(original_plain_text)
        return "\n".join(parts)

    @staticmethod
    def _extract_plain_text_chain(chain) -> Tuple[bool, str]:
        texts = []

        for comp in chain:
            if not isinstance(comp, Plain):
                return False, ""
            texts.append(comp.text or "")

        return True, "".join(texts)

    @staticmethod
    def _normalize_tts_text(text: str) -> str:
        """在发送给 TTS 前统一清理文本格式。"""
        if not text:
            return ""

        text = html.unescape(text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\s*\n+\s*", " ", text)

        # 去除零宽字符、BOM 和大部分不可见控制字符，但保留换行以便后续统一处理。
        text = re.sub(r"[\u200B-\u200D\u2060\uFEFF]", "", text)
        text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

        punctuation_map = str.maketrans(
            {
                "。": ".",
                "，": ",",
                "、": ",",
                "；": ";",
                "：": ":",
                "！": "!",
                "？": "?",
                "（": "(",
                "）": ")",
                "【": "[",
                "】": "]",
                "｛": "{",
                "｝": "}",
                "《": "<",
                "》": ">",
                "〈": "<",
                "〉": ">",
                "「": "[",
                "」": "]",
                "『": "[",
                "』": "]",
                "“": "\"",
                "”": "\"",
                "‘": "'",
                "’": "'",
                "…": "...",
                "—": "-",
                "～": "~",
                "·": ".",
                "・": ".",
                "\u3000": " ",
            }
        )
        text = text.translate(punctuation_map)

        # 将全角字符统一为半角。
        text = unicodedata.normalize("NFKC", text)

        # 统一空白：换行折叠为空格，多余空格压缩为一个。
        text = re.sub(r"\s*\n+\s*", " ", text)
        text = re.sub(r"[ \t\f\v]+", " ", text)

        # 去掉中日韩文字之间、以及它们与英文标点之间的多余空格，保留英文单词正常空格。
        east_asian = (
            r"\u3040-\u309F"  # Hiragana
            r"\u30A0-\u30FF"  # Katakana
            r"\u31F0-\u31FF"  # Katakana Phonetic Extensions
            r"\u3400-\u4DBF"  # CJK Unified Ideographs Extension A
            r"\u4E00-\u9FFF"  # CJK Unified Ideographs
            r"\uF900-\uFAFF"  # CJK Compatibility Ideographs
            r"\uFF66-\uFF9F"  # Halfwidth Katakana
            r"\uAC00-\uD7AF"  # Hangul Syllables
        )
        ascii_punct = r"""[.,!?;:'"\[\]\(\)\{\}<>/\-]"""
        text = re.sub(rf"(?<=[{east_asian}])\s+(?=[{east_asian}])", "", text)
        text = re.sub(rf"(?<=[{east_asian}])\s+(?={ascii_punct})", "", text)
        text = re.sub(rf"(?<={ascii_punct})\s+(?=[{east_asian}])", "", text)

        # 统一情绪标签括号，并清理标签内部首尾空格。
        text = re.sub(r"\[\s*([^\[\]]+?)\s*\]", r"[\1]", text)

        contains_japanese = bool(re.search(r"[\u3040-\u30FF\u31F0-\u31FF]", text))

        def replace_emotion_tag(match: re.Match) -> str:
            tag_name = match.group(1).strip().lower()
            natural_language = TTSModifyPlugin.EMOTION_TAG_NATURAL_LANGUAGE.get(tag_name)
            if not natural_language:
                return match.group(0)
            return natural_language["japanese"] if contains_japanese else natural_language["default"]

        # 已知情绪标签统一改成自然语言提示；未知标签（如动作标签）保持原样。
        text = re.sub(r"\[([^\[\]]+)\]", replace_emotion_tag, text)

        def strip_unsafe_english_tag(match: re.Match) -> str:
            raw_tag = match.group(1).strip()
            normalized_tag = re.sub(r"\s+", " ", raw_tag).lower()
            if normalized_tag in TTSModifyPlugin.ENGLISH_ACTION_TAG_WHITELIST:
                return f"[{raw_tag}]"
            return ""

        # 已知情绪标签完成映射后，剩余的纯英文中括号标签默认剥离，避免触发 FishAudio 乱码。
        text = re.sub(
            r"\[([A-Za-z][A-Za-z0-9 _'\-]{0,63})\]",
            strip_unsafe_english_tag,
            text,
        )
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(rf"(?<=[{east_asian}])\s+(?=[{east_asian}])", "", text)
        text = re.sub(rf"(?<=[{east_asian}])\s+(?={ascii_punct})", "", text)
        text = re.sub(rf"(?<={ascii_punct})\s+(?=[{east_asian}])", "", text)

        # FishAudio 在句首未知标签 + 日语/中日韩正文时，可能会在语音开头读出异常字符。
        # 情绪标签已在上面转为自然语言，这里只兼容剩余的未知标签，不影响句中动作标签。
        leading_tag_match = re.match(r"^(\[[^\[\]]+\])(.*)$", text)
        if leading_tag_match:
            leading_tag = leading_tag_match.group(1)
            remaining_text = leading_tag_match.group(2).lstrip()
            protected_leading_tags = {
                value["default"]
                for value in TTSModifyPlugin.EMOTION_TAG_NATURAL_LANGUAGE.values()
            } | {
                value["japanese"]
                for value in TTSModifyPlugin.EMOTION_TAG_NATURAL_LANGUAGE.values()
            }
            if leading_tag in protected_leading_tags:
                return f"{leading_tag}{remaining_text}".strip()
            east_asian_start = (
                r"[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF"
                r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
                r"\uFF66-\uFF9F\uAC00-\uD7AF]"
            )
            if remaining_text and re.match(east_asian_start, remaining_text):
                split_match = re.match(r"^(.+?(?:\.{2,}|[.,!?;:~]+|$))(.*)$", remaining_text)
                if split_match:
                    leading_segment = split_match.group(1).strip()
                    trailing_segment = split_match.group(2).lstrip()
                    if trailing_segment:
                        text = f"{leading_segment}{leading_tag}{trailing_segment}"
                    else:
                        text = f"{leading_tag}{leading_segment}"

        return text.strip()

    @register_on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest):
        self._refresh_runtime_config(event)
        self._mark_pending_llm_response_event(event)

        if request.system_prompt and self.INTERNAL_AUTO_JP_TRANSLATE_MARKER in request.system_prompt:
            request.system_prompt = request.system_prompt.replace(
                self.INTERNAL_AUTO_JP_TRANSLATE_MARKER,
                "",
            ).strip()
            return

        # 1. 检查配置
        try:
            global_config = self.context.get_config(event.unified_msg_origin)
        except KeyError:
             # 如果没有特定会话配置，尝试获取全局配置
            global_config = self.context.get_config()
        except Exception as e:
            logger.error(f"TTS插件获取配置失败: {e}")
            logger.debug(traceback.format_exc())
            return

        provider_tts_settings = global_config.get(self.CONFIG_KEY_TTS_SETTINGS, {})
        if not provider_tts_settings.get(self.CONFIG_KEY_ENABLE, False):
            return

        # 2. 检查 TTS Provider 是否可用
        tts_provider = self.context.get_using_tts_provider(event.unified_msg_origin)
        if not tts_provider:
            return

        # 3. 注入 Prompt
        request.system_prompt = request.system_prompt or ""
        tts_prompt = self._get_text_config(self.CONFIG_KEY_TTS_PROMPT, "").strip()
        if tts_prompt:
            # Append to system prompt with a newline for safety
            request.system_prompt += f"\n{tts_prompt}"

        forced_voice_prompt = self._resolve_forced_voice_prompt_injection(event)
        if forced_voice_prompt:
            request.system_prompt += f"\n{forced_voice_prompt}"
            self._mark_pending_forced_voice_event(event)
            logger.debug(
                f"管理员语音提示注入已命中: {event.unified_msg_origin} -> {forced_voice_prompt}"
            )

    @filter.on_llm_response(priority=1000)
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        self._refresh_runtime_config(event)

        completion_text = getattr(resp, "completion_text", None)
        if isinstance(completion_text, str) and self.TTS_TAG_START in completion_text and self.TTS_TAG_END in completion_text:
            encoded_text = self._encode_tts_blocks_for_splitter(completion_text)
            if encoded_text != completion_text:
                logger.debug("已在 on_llm_response 阶段保护 TTS 片段，避免被 splitter 拆开。")
                resp.completion_text = encoded_text

    # 必须先于 splitter 处理 <tts> 标签。
    # 这里使用超高正优先级，兼容“数值越大越早执行”的调度顺序。
    @filter.on_decorating_result(priority=100000000000000001)
    async def on_decorate(self, event: AstrMessageEvent):
        self._refresh_runtime_config(event)
        result = event.get_result()
        if not result or not result.chain:
            return

        had_protected_tts_block = False
        for comp in result.chain:
            if isinstance(comp, Plain) and comp.text and self.TTS_BLOCK_PLACEHOLDER_PREFIX in comp.text:
                had_protected_tts_block = True
                decoded_text = self._decode_tts_blocks_from_splitter(comp.text)
                if decoded_text != comp.text:
                    logger.debug("已在结果阶段还原 TTS 占位块。")
                    comp.text = decoded_text

        had_pending_llm_response = self._consume_pending_llm_response_event(event)
        has_tts_tag = self._chain_contains_tts_marker(result.chain)

        if not had_protected_tts_block and not had_pending_llm_response and not has_tts_tag:
            return

        forced_voice_requested = self._consume_pending_forced_voice_event(event)

        # 1. 获取配置
        try:
            config = self.context.get_config(event.unified_msg_origin)
        except KeyError:
            config = self.context.get_config()
        except Exception as e:
            logger.error(f"TTS插件获取配置失败: {e}")
            return
            
        provider_tts_settings = config.get(self.CONFIG_KEY_TTS_SETTINGS, {})

        # 2. 检查消息中是否包含TTS标签
        # 3. 获取TTS服务提供商
        tts_provider = self.context.get_using_tts_provider(event.unified_msg_origin)
        if has_tts_tag and not tts_provider:
            logger.error(f"会话 {event.unified_msg_origin} 缺少 TTS 服务提供商，但检测到 <tts> 标签。将剥离标签并显示文本。")

        if not has_tts_tag:
            if forced_voice_requested:
                auto_chain = await self._force_convert_auto_japanese_voice(
                    event,
                    result.chain,
                    tts_provider,
                    provider_tts_settings,
                    config,
                )
            else:
                auto_chain = await self._maybe_convert_random_japanese_voice(
                    event,
                    result.chain,
                    tts_provider,
                    provider_tts_settings,
                    config,
                )
            if auto_chain:
                result.chain = await self._send_leading_record_segment_if_needed(
                    event,
                    result,
                    auto_chain,
                )
            return

        # 4. 处理标签。这里按整条 chain 串流解析，避免 <tts>...</tts> 被拆到多个 Plain 组件后漏处理。
        new_chain, modified = await self._process_tts_chain(
            result.chain,
            tts_provider,
            provider_tts_settings,
            config,
        )
        if modified:
            result.chain = await self._send_leading_record_segment_if_needed(
                event,
                result,
                new_chain,
            )

    async def _maybe_convert_random_japanese_voice(
        self,
        event: AstrMessageEvent,
        chain: list,
        tts_provider,
        provider_settings: dict,
        config: dict,
    ) -> Optional[list]:
        """按概率将纯文本回复改为“日语语音 + 中文文本”双输出。"""
        if not self._get_bool_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_ENABLED,
            self.DEFAULT_AUTO_JP_VOICE_ENABLED,
        ):
            return None

        if self._chain_contains_audio(chain):
            return None

        tts_enabled = provider_settings.get(self.CONFIG_KEY_ENABLE, False)
        if not tts_enabled or not tts_provider:
            return None

        is_plain_text_only, original_text = self._extract_plain_text_chain(chain)
        if not is_plain_text_only or not original_text.strip():
            return None

        is_admin_sender = self._is_group_admin_sender(event)
        prioritized_admin_probability = self._get_prioritized_admin_auto_jp_probability(event)

        max_chars = self._get_int_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_MAX_CHARS,
            self.DEFAULT_AUTO_JP_VOICE_MAX_CHARS,
        )
        if prioritized_admin_probability is None and max_chars > 0 and len(original_text.strip()) > max_chars:
            return None

        cooldown_seconds = max(
            0,
            self._get_int_config(
                self.CONFIG_KEY_AUTO_JP_VOICE_COOLDOWN_SECONDS,
                self.DEFAULT_AUTO_JP_VOICE_COOLDOWN_SECONDS,
            ),
        )
        if not is_admin_sender and cooldown_seconds > 0:
            now = time.monotonic()
            last_trigger_at = self._auto_jp_voice_last_trigger_at.get(event.unified_msg_origin)
            if last_trigger_at is not None and now - last_trigger_at < cooldown_seconds:
                return None

        probability = (
            prioritized_admin_probability
            if prioritized_admin_probability is not None
            else self._resolve_auto_jp_voice_probability(event)
        )
        if probability <= 0 or random.random() * 100 >= probability:
            return None

        tts_formatted_message = await self._build_auto_japanese_tts_message(event, original_text)
        if not tts_formatted_message:
            logger.warning("自动日语语音模式翻译失败，保留原始文本发送。")
            return None

        logger.debug(
            f"自动日语语音命中: {original_text!r} -> {tts_formatted_message!r}"
        )

        if not is_admin_sender and cooldown_seconds > 0:
            self._auto_jp_voice_last_trigger_at[event.unified_msg_origin] = time.monotonic()

        if self.TTS_TAG_START in tts_formatted_message and self.TTS_TAG_END in tts_formatted_message:
            return await self._process_tts_tags(
                tts_formatted_message,
                tts_provider,
                provider_settings,
                config,
            )

        logger.warning("自动日语语音模式未返回合法 <tts> 格式，保留原始文本发送。")
        return None

    async def _force_convert_auto_japanese_voice(
        self,
        event: AstrMessageEvent,
        chain: list,
        tts_provider,
        provider_settings: dict,
        config: dict,
    ) -> Optional[list]:
        if self._chain_contains_audio(chain):
            return None

        tts_enabled = provider_settings.get(self.CONFIG_KEY_ENABLE, False)
        if not tts_enabled or not tts_provider:
            return None

        is_plain_text_only, original_text = self._extract_plain_text_chain(chain)
        if not is_plain_text_only or not original_text.strip():
            return None

        tts_formatted_message = await self._build_auto_japanese_tts_message(event, original_text)
        if not tts_formatted_message:
            logger.warning("管理员语音提示已命中，但兜底转换失败，保留原始文本发送。")
            return None

        logger.debug(
            f"管理员语音提示已命中，结果阶段执行兜底转换: {original_text!r} -> {tts_formatted_message!r}"
        )

        if self.TTS_TAG_START in tts_formatted_message and self.TTS_TAG_END in tts_formatted_message:
            return await self._process_tts_tags(
                tts_formatted_message,
                tts_provider,
                provider_settings,
                config,
            )

        logger.warning("管理员语音提示已命中，但兜底转换未返回合法 <tts> 格式，保留原始文本发送。")
        return None

    async def _build_auto_japanese_tts_message(self, event: AstrMessageEvent, text: str) -> str:
        provider = self.context.get_using_provider(event.unified_msg_origin)
        if not provider:
            try:
                provider = self.context.get_using_provider()
            except Exception:
                provider = None

        if not provider:
            logger.warning("自动日语语音模式未找到可用的 LLM Provider。")
            return ""

        system_prompt = self._get_text_config(
            self.CONFIG_KEY_AUTO_JP_TRANSLATE_PROMPT,
            self.DEFAULT_AUTO_JP_TRANSLATE_PROMPT,
        ).strip() or self.DEFAULT_AUTO_JP_TRANSLATE_PROMPT
        full_conversion_enabled = self._should_use_full_auto_japanese_conversion()
        if full_conversion_enabled:
            system_prompt += (
                "\n\n完全转换模式要求：必须把输入的整段原文完整转换为一段适合朗读的日语，"
                "不要只转换其中一句、后半句或摘要。输出中 <tts> 前不要添加中文铺垫；"
                "格式必须为：<tts>完整日语朗读文本</tts>，随后换行附上原中文全文。"
            )

        try:
            response = await provider.text_chat(
                system_prompt=f"{self.INTERNAL_AUTO_JP_TRANSLATE_MARKER}\n{system_prompt}",
                prompt=text,
                session_id=f"{event.unified_msg_origin}:tts_modify_auto_jp",
                persist=False,
            )
        except Exception as e:
            logger.error(f"自动日语语音模式调用翻译失败: {e}")
            logger.debug(traceback.format_exc())
            return ""

        raw_translated_text = self._extract_provider_text(response)
        translated_text = self._cleanup_translated_japanese_text(raw_translated_text)
        translated_text = self._extract_tts_formatted_message(translated_text)
        if full_conversion_enabled:
            translated_text = self._build_full_auto_tts_message(translated_text, text)
        else:
            translated_text = self._build_canonical_auto_tts_message(translated_text, text)
        if not translated_text:
            translated_text = self._wrap_plain_japanese_as_tts(raw_translated_text, text)
            if translated_text:
                logger.debug("自动日语语音模式检测到纯日语输出，已自动补全为 <tts> 格式。")
        return translated_text.strip()

    def _should_use_full_auto_japanese_conversion(self) -> bool:
        if self._is_vtube_live_mode_active():
            return True

        if not self._get_bool_config(
            self.CONFIG_KEY_AUTO_JP_FULL_CONVERSION_ENABLED,
            self.DEFAULT_AUTO_JP_FULL_CONVERSION_ENABLED,
        ):
            return False

        return True

    def _play_audio_locally_once(self, audio_path: str):
        if not self._get_bool_config(
            self.CONFIG_KEY_LOCAL_AUDIO_PLAYBACK_ENABLED,
            self.DEFAULT_LOCAL_AUDIO_PLAYBACK_ENABLED,
        ):
            return

        if not audio_path:
            return

        try:
            audio_file = Path(audio_path).resolve()
            if not audio_file.is_file():
                logger.warning(f"TTS 自动播放失败，音频文件不存在: {audio_path}")
                return

            if os.name == "nt":
                command = self._build_windows_local_playback_command(audio_file)
                subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return

            opener = "open" if os.name == "posix" and os.uname().sysname == "Darwin" else "xdg-open"
            subprocess.Popen(
                [opener, str(audio_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.error(f"TTS 自动播放失败: {e}")
            logger.debug(traceback.format_exc())

    @staticmethod
    def _build_windows_local_playback_command(audio_file: Path) -> list[str]:
        audio_uri = audio_file.as_uri().replace("'", "''")
        script = (
            "Add-Type -AssemblyName PresentationCore;"
            "$player=New-Object System.Windows.Media.MediaPlayer;"
            f"$player.Open([Uri]'{audio_uri}');"
            "$player.Play();"
            "$deadline=(Get-Date).AddSeconds(120);"
            "Start-Sleep -Milliseconds 500;"
            "while((Get-Date) -lt $deadline){"
            "if($player.NaturalDuration.HasTimeSpan -and "
            "$player.Position -ge $player.NaturalDuration.TimeSpan){break};"
            "Start-Sleep -Milliseconds 200"
            "};"
            "$player.Close()"
        )
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-Command",
            script,
        ]

    def _find_vtube_studio_plugin(self):
        try:
            stars = self.context.get_all_stars()
        except Exception as e:
            logger.debug(f"获取插件列表失败，无法联动 VTube 字幕: {e}")
            return None

        for star in stars or []:
            plugin_name = str(getattr(star, "name", "") or "")
            module_path = str(getattr(star, "module_path", "") or "")
            if (
                plugin_name == "astrbot_plugin_vtube_studio"
                or module_path.endswith("astrbot_plugin_vtube_studio.main")
            ):
                return getattr(star, "star_cls", None)
        return None

    def _is_vtube_live_mode_active(self) -> bool:
        vtube_plugin = self._find_vtube_studio_plugin()
        if not vtube_plugin:
            return False

        is_running = getattr(vtube_plugin, "_is_bili_live_running", None)
        if callable(is_running):
            try:
                return bool(is_running())
            except Exception as e:
                logger.debug(f"读取 VTube 直播状态失败: {e}")

        live_task = getattr(vtube_plugin, "_bili_live_task", None)
        if live_task is not None:
            try:
                return not live_task.done()
            except Exception:
                return False

        return False

    async def _push_vtube_subtitle_for_tts(self, subtitle_text: str):
        if not self._get_bool_config(
            self.CONFIG_KEY_VTUBE_SUBTITLE_SYNC_ENABLED,
            self.DEFAULT_VTUBE_SUBTITLE_SYNC_ENABLED,
        ):
            return

        cleaned_text = self._sanitize_plain_output_text(subtitle_text)
        if not cleaned_text:
            return

        vtube_plugin = self._find_vtube_studio_plugin()
        push_subtitle = getattr(vtube_plugin, "_push_subtitle", None) if vtube_plugin else None
        if not callable(push_subtitle):
            logger.debug("未找到可用的 VTube Studio 字幕插件实例，已跳过 TTS 字幕联动。")
            return

        try:
            result = push_subtitle(cleaned_text)
            if isawaitable(result):
                await result
        except Exception as e:
            logger.error(f"TTS 联动 VTube 字幕失败: {e}")
            logger.debug(traceback.format_exc())

    async def _process_tts_tags(self, text: str, tts_provider, provider_settings: dict, config: dict) -> list:
        """处理文本中的 TTS 标签，返回组件列表"""
        parts = []
        # 使用非贪婪匹配
        pattern = re.compile(f"{self.TTS_TAG_START}(.*?){self.TTS_TAG_END}", re.DOTALL)
        last_idx = 0
        
        for match in pattern.finditer(text):
            # 添加标签前的文本
            if match.start() > last_idx:
                pre_text = text[last_idx:match.start()]
                if pre_text:
                    sanitized_pre_text = self._sanitize_plain_output_text(pre_text)
                    if sanitized_pre_text:
                        parts.append(Plain(sanitized_pre_text))
            
            # 处理 TTS 内容
            tts_content = match.group(1).strip()
            if tts_content:
                component = await self._create_tts_component(
                    tts_content, tts_provider, provider_settings, config
                )
                if component:
                    parts.extend(component)
            
            last_idx = match.end()
        
        # 添加标签后的文本
        if last_idx < len(text):
            post_text = text[last_idx:]
            if post_text:
                sanitized_post_text = self._sanitize_plain_output_text(post_text)
                if sanitized_post_text:
                    parts.append(Plain(sanitized_post_text))

        if not parts and self._contains_tts_marker(text):
            stripped_text = self._strip_tts_markers(text)
            if stripped_text:
                sanitized_stripped_text = self._sanitize_plain_output_text(stripped_text)
                if sanitized_stripped_text:
                    parts.append(Plain(sanitized_stripped_text))
            return parts

        sanitized_parts = []
        for part in parts:
            if isinstance(part, Plain) and self._contains_tts_marker(part.text):
                stripped_text = self._strip_tts_markers(part.text)
                if stripped_text:
                    sanitized_stripped_text = self._sanitize_plain_output_text(stripped_text)
                    if sanitized_stripped_text:
                        sanitized_parts.append(Plain(sanitized_stripped_text))
            else:
                sanitized_parts.append(part)

        return sanitized_parts

    async def _process_tts_chain(self, chain: list, tts_provider, provider_settings: dict, config: dict) -> tuple[list, bool]:
        """按组件流解析 TTS 标签，支持标签和正文跨多个 Plain 组件。"""
        if not chain:
            return chain, False

        new_chain = []
        plain_buffer = []
        tts_buffer = []
        inside_tts = False
        modified = False

        def flush_plain_buffer():
            if plain_buffer:
                merged_text = "".join(plain_buffer)
                plain_buffer.clear()
                sanitized_merged_text = self._sanitize_plain_output_text(merged_text)
                if sanitized_merged_text:
                    new_chain.append(Plain(sanitized_merged_text))

        for comp in chain:
            if not isinstance(comp, Plain):
                flush_plain_buffer()
                if inside_tts:
                    tts_buffer.append("")
                new_chain.append(comp)
                continue

            text = comp.text or ""
            cursor = 0

            while cursor < len(text):
                if inside_tts:
                    end_idx = text.find(self.TTS_TAG_END, cursor)
                    if end_idx == -1:
                        tts_buffer.append(text[cursor:])
                        cursor = len(text)
                        break

                    tts_buffer.append(text[cursor:end_idx])
                    tts_content = "".join(tts_buffer).strip()
                    tts_buffer.clear()
                    inside_tts = False
                    modified = True
                    if tts_content:
                        tts_components = await self._create_tts_component(
                            tts_content,
                            tts_provider,
                            provider_settings,
                            config,
                        )
                        if tts_components:
                            flush_plain_buffer()
                            new_chain.extend(tts_components)
                    cursor = end_idx + len(self.TTS_TAG_END)
                    continue

                start_idx = text.find(self.TTS_TAG_START, cursor)
                if start_idx == -1:
                    trailing_text = text[cursor:]
                    if self.TTS_TAG_END in trailing_text:
                        logger.debug(f"TTS 组件流解析：清理孤立结束标签 -> {trailing_text!r}")
                        trailing_text = self._strip_tts_markers(trailing_text)
                        modified = True
                    if trailing_text:
                        plain_buffer.append(trailing_text)
                    break

                prefix_text = text[cursor:start_idx]
                if self.TTS_TAG_END in prefix_text:
                    logger.debug(f"TTS 组件流解析：清理前缀中的孤立结束标签 -> {prefix_text!r}")
                    prefix_text = self._strip_tts_markers(prefix_text)
                    modified = True
                if prefix_text:
                    plain_buffer.append(prefix_text)

                inside_tts = True
                modified = True
                cursor = start_idx + len(self.TTS_TAG_START)

        if inside_tts:
            dangling_tts_text = "".join(tts_buffer)
            logger.debug(f"TTS 组件流解析：检测到未闭合开始标签，按普通文本回退 -> {dangling_tts_text!r}")
            if dangling_tts_text:
                plain_buffer.append(dangling_tts_text)
            modified = True

        flush_plain_buffer()
        return new_chain, modified

    async def _create_tts_component(
        self,
        tts_content: str,
        tts_provider,
        provider_settings: dict,
        config: dict,
        fallback_text: Optional[str] = None,
        success_text: Optional[str] = None,
    ) -> list:
        """生成 TTS 组件"""
        res_components = []
        audio_path = None
        normalized_tts_content = self._normalize_tts_text(tts_content)
        display_fallback_text = self._normalize_tts_text(
            fallback_text if fallback_text is not None else normalized_tts_content
        )
        
        tts_enabled = provider_settings.get(self.CONFIG_KEY_ENABLE, False)
        
        if tts_enabled and tts_provider:
            try:
                if self._looks_like_non_japanese_tts_text(normalized_tts_content):
                    logger.warning(f"TTS 文本疑似为非日语正文，已回退为普通文本: {normalized_tts_content!r}")
                    raise ValueError("non_japanese_tts_text")

                if normalized_tts_content != tts_content:
                    logger.debug(f"TTS 文本已清洗: {tts_content!r} -> {normalized_tts_content!r}")

                audio_path = await tts_provider.get_audio(normalized_tts_content)
                
                # 安全检查
                if audio_path:
                    audio_file = Path(audio_path).resolve()
                    expected_dir = Path(get_astrbot_data_path()).resolve()
                    # 允许在 data 目录下的文件
                    if not audio_file.is_relative_to(expected_dir):
                        logger.error(f"TTS 返回路径不安全: {audio_path}")
                        audio_path = None
                        
            except Exception as e:
                if str(e) == "non_japanese_tts_text":
                    audio_path = None
                else:
                    logger.error(f"TTS 生成失败: {e}")
                    logger.debug(traceback.format_exc())
            
            if audio_path:
                await self._push_vtube_subtitle_for_tts(normalized_tts_content)
                self._play_audio_locally_once(audio_path)

                # 成功：转换为 Record
                use_file_service = provider_settings.get("use_file_service", False)
                callback_api_base = config.get("callback_api_base", "")
                dual_output = provider_settings.get("dual_output", False)
                
                url = None
                if use_file_service and callback_api_base:
                    try:
                        token = await file_token_service.register_file(audio_path)
                        url = f"{callback_api_base}/api/file/{token}"
                    except Exception as e:
                        logger.error(f"文件注册失败: {e}")

                res_components.append(Record(file=url or audio_path, url=url or audio_path))

                if success_text is not None:
                    sanitized_success_text = self._sanitize_plain_output_text(success_text)
                    if sanitized_success_text:
                        res_components.append(Plain(sanitized_success_text))
                elif dual_output:
                    sanitized_dual_output_text = self._sanitize_plain_output_text(normalized_tts_content)
                    if sanitized_dual_output_text:
                        res_components.append(Plain(sanitized_dual_output_text))
            else:
                # 生成失败 或 路径不安全
                failure_plain_text = self._build_tts_failure_plain_text(
                    display_fallback_text,
                    provider_settings.get(
                        self.CONFIG_KEY_NOTIFY_FAILURE,
                        self.DEFAULT_NOTIFY_ON_FAILURE,
                    ),
                )
                if failure_plain_text:
                    res_components.append(Plain(failure_plain_text))
                    
        elif not tts_enabled:
            # TTS 未启用
            logger.warning(f"检测到 TTS 标签，但全局配置中 TTS 未启用。剥离标签并显示文本。")
            sanitized_fallback_text = self._sanitize_plain_output_text(display_fallback_text)
            if sanitized_fallback_text:
                res_components.append(Plain(sanitized_fallback_text))
        else:
            # 没 provider
            sanitized_fallback_text = self._sanitize_plain_output_text(display_fallback_text)
            if sanitized_fallback_text:
                res_components.append(Plain(sanitized_fallback_text))

        return res_components
