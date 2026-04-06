import html
import random
import re
import time
import traceback
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Tuple
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.core.message.components import Plain, Record
from astrbot.core import file_token_service, logger
from astrbot.core.star.register import register_on_decorating_result, register_on_llm_request
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

class TTSModifyPlugin(Star):
    TTS_TAG_START = "<tts>"
    TTS_TAG_END = "</tts>"
    CONFIG_KEY_TTS_SETTINGS = "provider_tts_settings"
    CONFIG_KEY_ENABLE = "enable"
    CONFIG_KEY_TTS_PROMPT = "tts_prompt"
    CONFIG_KEY_NOTIFY_FAILURE = "notify_on_failure"
    CONFIG_KEY_AUTO_JP_VOICE_ENABLED = "auto_japanese_voice_enabled"
    CONFIG_KEY_AUTO_JP_VOICE_PROBABILITY = "auto_japanese_voice_probability"
    CONFIG_KEY_AUTO_JP_VOICE_MAX_CHARS = "auto_japanese_voice_max_chars"
    CONFIG_KEY_AUTO_JP_VOICE_COOLDOWN_SECONDS = "auto_japanese_voice_cooldown_seconds"
    CONFIG_KEY_AUTO_JP_TRANSLATE_PROMPT = "auto_japanese_voice_translate_prompt"
    INTERNAL_AUTO_JP_TRANSLATE_MARKER = "[TTS_MODIFY_AUTO_JP_TRANSLATE]"
    DEFAULT_NOTIFY_ON_FAILURE = False
    DEFAULT_AUTO_JP_VOICE_ENABLED = False
    DEFAULT_AUTO_JP_VOICE_PROBABILITY = 20.0
    DEFAULT_AUTO_JP_VOICE_MAX_CHARS = 50
    DEFAULT_AUTO_JP_VOICE_COOLDOWN_SECONDS = 120
    DEFAULT_AUTO_JP_TRANSLATE_PROMPT = (
        "当你想要发送语音时，使用<tts></tts>标签包裹需要转语音的文本，语音可放在句中的任意位置。\n"
        "你必须严格按照以下TTS格式输出内容：\n\n"
        "1. 默认语音消息为日语，除非特别说明其他语言。未经允许不能发送中文语音消息。所有日语内容必须包裹在 <tts> 成对标签中，不嵌套、不遗漏闭合。\n"
        "2. 情感标签请使用日语自然表达，并用[]包裹，参考情感：[嬉しそうに]、[悲しそうに]、[怒ったように]、[落ち着いた調子で]、[緊張した様子で]、[自信ありげに]、[驚いたように]、[満足そうに]、[怯えたように]、[心配そうに]、[落ち込んだように]、[苛立ったように]、[憂鬱そうに]、[共感するように]、[恥ずかしそうに]、[嫌悪感を込めて]、[感動したように]、[誇らしげに]、[リラックスして]、[感謝を込めて]、[興味深そうに]、[皮肉っぽく]。请根据语境选择标签或使用自然语言描述，不要使用英文情感标签。可在[]中加入自然停顿、笑声和其他类人元素，使语音更具吸引力和真实感。\n"
        "3. 为了让消息更连贯，可以保留少量不重复的中文铺垫文本放在 <tts> 标签前，把更适合强调、收尾或情绪表达的后半句改成日语语音。\n"
        "4. 如果在 </tts> 后补充中文文本，只保留与语音内容对应、且不会和前文重复的那一小段，不要把整段原文完整重复一遍。\n"
        "5. 要避免标签前后的中文与语音表达语义重复，读起来要像一句自然接上的话，而不是同一句话先说中文再说日语。\n\n"
        "输出格式示例：\n"
        "1.今天只对你悄悄说一句：<tts>[優しく]おやすみ、いい夢を。</tts>\n"
        "2.先别着急，<tts>[落ち着いた調子で]ゆっくり話して。</tts>\n"
        "3.我知道你已经很努力了。<tts>[感謝を込めて]本当にありがとう。</tts>\n"
        "4.如果你还想继续，我就陪你到最后。<tts>[眠たそうに]もう......限界だけど、君が納得するまで付き合ってあげる。</tts>\n\n"
        "现在请把我提供的中文内容，改写成符合以上规范的输出。不要解释，不要添加格式说明。"
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

    def _get_plugin_config(self) -> dict:
        return self.config or {}

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
        tts_prompt = self._get_text_config(self.CONFIG_KEY_TTS_PROMPT, "").strip()
        if tts_prompt:
            # Append to system prompt with a newline for safety
            request.system_prompt += f"\n{tts_prompt}"

    @register_on_decorating_result(priority=10)
    async def on_decorate(self, event: AstrMessageEvent):
        result = event.get_result()
        if not result or not result.chain:
            return

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
        has_tts_tag = False
        for comp in result.chain:
            if isinstance(comp, Plain) and self.TTS_TAG_START in comp.text:
                has_tts_tag = True
                break

        # 3. 获取TTS服务提供商
        tts_provider = self.context.get_using_tts_provider(event.unified_msg_origin)
        if has_tts_tag and not tts_provider:
            logger.error(f"会话 {event.unified_msg_origin} 缺少 TTS 服务提供商，但检测到 <tts> 标签。将剥离标签并显示文本。")

        if not has_tts_tag:
            auto_chain = await self._maybe_convert_random_japanese_voice(
                event,
                result.chain,
                tts_provider,
                provider_tts_settings,
                config,
            )
            if auto_chain:
                result.chain = auto_chain
            return

        # 4. 处理标签
        new_chain = []
        modified = False
        
        for comp in result.chain:
            if isinstance(comp, Plain) and self.TTS_TAG_START in comp.text:
                components = await self._process_tts_tags(comp.text, tts_provider, provider_tts_settings, config)
                new_chain.extend(components)
                modified = True
            else:
                new_chain.append(comp)

        if modified:
            result.chain = new_chain

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

        max_chars = self._get_int_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_MAX_CHARS,
            self.DEFAULT_AUTO_JP_VOICE_MAX_CHARS,
        )
        if max_chars > 0 and len(original_text.strip()) > max_chars:
            return None

        cooldown_seconds = max(
            0,
            self._get_int_config(
                self.CONFIG_KEY_AUTO_JP_VOICE_COOLDOWN_SECONDS,
                self.DEFAULT_AUTO_JP_VOICE_COOLDOWN_SECONDS,
            ),
        )
        if cooldown_seconds > 0:
            now = time.monotonic()
            last_trigger_at = self._auto_jp_voice_last_trigger_at.get(event.unified_msg_origin)
            if last_trigger_at is not None and now - last_trigger_at < cooldown_seconds:
                return None

        probability = self._get_float_config(
            self.CONFIG_KEY_AUTO_JP_VOICE_PROBABILITY,
            self.DEFAULT_AUTO_JP_VOICE_PROBABILITY,
        )
        probability = max(0.0, min(100.0, probability))
        if probability <= 0 or random.random() * 100 >= probability:
            return None

        tts_formatted_message = await self._build_auto_japanese_tts_message(event, original_text)
        if not tts_formatted_message:
            logger.warning("自动日语语音模式翻译失败，保留原始文本发送。")
            return None

        logger.debug(
            f"自动日语语音命中: {original_text!r} -> {tts_formatted_message!r}"
        )

        if cooldown_seconds > 0:
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

        translated_text = self._extract_provider_text(response)
        translated_text = self._cleanup_translated_japanese_text(translated_text)
        translated_text = self._extract_tts_formatted_message(translated_text)
        translated_text = self._build_canonical_auto_tts_message(translated_text, text)
        return translated_text.strip()

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
                    parts.append(Plain(pre_text))
            
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
                parts.append(Plain(post_text))
        
        return parts

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
        display_fallback_text = fallback_text if fallback_text is not None else normalized_tts_content
        
        tts_enabled = provider_settings.get(self.CONFIG_KEY_ENABLE, False)
        
        if tts_enabled and tts_provider:
            try:
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
                logger.error(f"TTS 生成失败: {e}")
                logger.debug(traceback.format_exc())
            
            if audio_path:
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
                    res_components.append(Plain(success_text))
                elif dual_output:
                    res_components.append(Plain(normalized_tts_content))
            else:
                # 生成失败 或 路径不安全
                if provider_settings.get(self.CONFIG_KEY_NOTIFY_FAILURE, self.DEFAULT_NOTIFY_ON_FAILURE):
                    res_components.append(Plain(f"[TTS失败] {display_fallback_text}"))
                else:
                    res_components.append(Plain(display_fallback_text))
                    
        elif not tts_enabled:
            # TTS 未启用
            logger.warning(f"检测到 TTS 标签，但全局配置中 TTS 未启用。剥离标签并显示文本。")
            res_components.append(Plain(display_fallback_text))
        else:
            # 没 provider
            res_components.append(Plain(display_fallback_text))

        return res_components
