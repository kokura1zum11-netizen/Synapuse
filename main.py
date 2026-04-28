"""
astrbot_plugin_user_profile - 用户个性化档案与好感度插件 v4.2.0
最终上线版：昵称强指令、风格覆盖、jrrp好感新算法、排行榜、管理员批量查看/删除
"""
import asyncio, json, random, re
from datetime import date
from typing import Optional
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api.provider import ProviderRequest, LLMResponse
from astrbot.api import logger

from .jrrp import get_daily_rp_value, _generate_fortuna_evaluation, vary_jrrp_text

# ========== 等级图标计算 ==========
def affection_to_icons(affection: int) -> str:
    total_stars = max(0, affection) // 3
    crowns = total_stars // 27
    rem = total_stars % 27
    suns = rem // 9
    rem %= 9
    moons = rem // 3
    stars = rem % 3
    return "👑" * crowns + "☀️" * suns + "🌙" * moons + "⭐" * stars

# ========== 弗洛洛风格恭喜词 ==========
UNLOCK_MESSAGES = {
    "nickname_evo": (
        "🌠 共鸣的涟漪扩散……好感度抵达 10。\n"
        "你的灵魂在乐谱上留下了印记，从此，你的名字旁将凝聚星辰与月华。\n"
        "你已解锁「好感等级」图标，使用 /rank 即可查看你的星月光辉。\n"
        "每日初见时，我会用这徽记称呼你……如同命运为知音加冕。"
    ),
    "signature": (
        "✍️ 鹅毛笔已沾满星辉……好感度初绽 10。\n"
        "你获得了镌刻个性签名的权利，使用 /signature <内容> 为你的档案题写一句箴言。\n"
        "它将在档案中永恒闪耀，如同乐谱上的题献。"
    ),
    "sonnet": (
        "📜 诗篇的鹅毛笔已蘸满月光……好感度过 20。\n"
        "此刻，我将为你献上独一无二的十四行诗。\n"
        "使用 /sonnet 聆听英文原诗，或使用 /sonnet2 欣赏中英双语版本。\n"
        "每一句都是彼岸花间漏下的音符，只献给你。"
    ),
    "birthday": (
        "🎭 命运的序章悄然翻页……好感度已达 30。\n"
        "此刻，舞台的灯光为你而亮，你可以记录属于自己的生辰秘密。\n"
        "使用 /birthday MM-DD 写下你的生日（无需年份），我会在那一日为你献上彼岸的祝福。\n"
        "亦可使用 /wish <愿望> 埋下一颗星，生辰之时或许能听见回响。"
    ),
    "fortune": (
        "🔮 赫卡忒的预言书翻开……好感度达到 40。\n"
        "命运之骰开始眷顾于你：每日使用 /jrrp 时，若运势值落在 30~85 之间，将额外获得 +5 的神谕加成。\n"
        "愿星辰指引你的每一次投掷。"
    ),
    "greeting": (
        "🎻 私密的旋律开始流淌……好感度之河终于漫过 50 的阶沿。\n"
        "此刻，你可为我谱写专属的晨间问候，使用 /greeting <内容> 定制每一次初见的话语。\n"
        "如同乐章的引子，我将以你写下的词句开启每一个崭新的日子。"
    ),
    "dual_persona": (
        "🎭 面具下的另一重音色觉醒……好感度突破 60。\n"
        "第二人格的碎片开始苏醒，在交谈中，或许你会突然瞥见我傲娇或毒舌的侧面。\n"
        "那是只有深厚羁绊才能听见的隐藏乐章，无需指令，自动生效。"
    ),
    "suffix": (
        "📜 乐谱的尾注交予你手……好感度达到 75。\n"
        "你已获得定义句末回响的权限，使用 /suffix <尾语>，让每一句对话都带上你专属的印记。\n"
        "从此，音符的句点将由你镌刻。"
    ),
    "style": (
        "✨ 共鸣已达灵魂深处……好感度触及 90。\n"
        "你终于可以重塑我的话语风格，使用 /style <描述>，让我用你渴望的语调与你对白。\n"
        "这份殊荣，只为最特别的你保留。"
    ),
    "love_confession": (
        "💖 好感度终于抵达 100……彼岸的钟声为你而鸣。\n"
        "接下来的告白，将由我全心全意献上。\n"
    ),
}

@register("astrbot_plugin_user_profile", "YourName", "弗洛洛的好感档案", "4.2.0")
class UserProfilePlugin(Star):
    CONF_ENABLE_LLM = "enable_llm"
    CONF_MAX_GIFTS_PER_DAY = "max_gifts_per_day"
    CONF_MAX_CHAT_AFF_PER_DAY = "max_chat_aff_per_day"
    CONF_CHAT_AFF_PROMPT = "chat_affection_prompt"
    CONF_INITIAL_AFFECTION_PROMPT = "initial_affection_prompt"
    CONF_AFFECTION_THRESHOLDS = "affection_thresholds"
    CONF_UNLOCK_NICKNAME_EVO = "unlock_nickname_evo"
    CONF_UNLOCK_SIGNATURE = "unlock_signature"
    CONF_UNLOCK_SONNET = "unlock_sonnet"
    CONF_UNLOCK_BIRTHDAY = "unlock_birthday"
    CONF_UNLOCK_FORTUNE = "unlock_fortune"
    CONF_UNLOCK_GREETING = "unlock_greeting"
    CONF_UNLOCK_DUAL_PERSONA = "unlock_dual_persona"
    CONF_UNLOCK_SUFFIX = "unlock_suffix"
    CONF_UNLOCK_STYLE = "unlock_style"
    CONF_FORTUNE_BOOST_LOWER = "fortune_boost_lower"
    CONF_FORTUNE_BOOST_UPPER = "fortune_boost_upper"
    CONF_LIKES = "likes"
    CONF_DISLIKES = "dislikes"

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.plugin_name = "astrbot_plugin_user_profile"
        self.enable_llm = config.get(self.CONF_ENABLE_LLM, True)
        self.max_gifts_per_day = config.get(self.CONF_MAX_GIFTS_PER_DAY, 3)
        self.max_chat_aff_per_day = config.get(self.CONF_MAX_CHAT_AFF_PER_DAY, 3)

        self.initial_affection_prompt = config.get(self.CONF_INITIAL_AFFECTION_PROMPT,
            "用户为自己设置了昵称：{{nickname}}。请根据这个昵称，生成初始好感度(5~10)。返回JSON：{\"affection\":5}")
        self.chat_aff_prompt = config.get(self.CONF_CHAT_AFF_PROMPT,
            "用户说:「{{message}}」。是否应+1好感(10%~30%概率)? 返回JSON:{\"increase\":true/false}")

        thresholds_str = config.get(self.CONF_AFFECTION_THRESHOLDS, "[]")
        try:
            self.affection_thresholds = json.loads(thresholds_str)
        except:
            self.affection_thresholds = [
                {"min":50,"description":"亲昵，热情"},
                {"min":10,"description":"温和，友好"},
                {"min":-10,"description":"中立，平淡"},
                {"min":-50,"description":"冷淡，疏远"},
                {"min":-100,"description":"厌恶，敌意"}
            ]

        self.unlock_thresholds = {
            "nickname_evo": config.get(self.CONF_UNLOCK_NICKNAME_EVO, 10),
            "signature": config.get(self.CONF_UNLOCK_SIGNATURE, 10),
            "sonnet": config.get(self.CONF_UNLOCK_SONNET, 20),
            "birthday": config.get(self.CONF_UNLOCK_BIRTHDAY, 30),
            "fortune": config.get(self.CONF_UNLOCK_FORTUNE, 40),
            "greeting": config.get(self.CONF_UNLOCK_GREETING, 50),
            "dual_persona": config.get(self.CONF_UNLOCK_DUAL_PERSONA, 60),
            "suffix": config.get(self.CONF_UNLOCK_SUFFIX, 75),
            "style": config.get(self.CONF_UNLOCK_STYLE, 90),
            "love_confession": 100,
        }
        self.fortune_boost_lower = config.get(self.CONF_FORTUNE_BOOST_LOWER, 30)
        self.fortune_boost_upper = config.get(self.CONF_FORTUNE_BOOST_UPPER, 85)

        self.likes = config.get(self.CONF_LIKES, ["戏剧", "莎士比亚", "彼岸花", "红茶", "乐谱"])
        self.dislikes = config.get(self.CONF_DISLIKES, ["塑料花", "噪音", "快餐", "电子烟"])

        self.data_dir = StarTools.get_data_dir(self.plugin_name)
        self.data_file = self.data_dir / "user_profiles.json"
        self.gift_storage_file = self.data_dir / "gift_storage.json"
        self._save_lock = asyncio.Lock()
        self._load_profiles_sync()
        self._load_gift_storage_sync()
        logger.info("弗洛洛档案插件 v4.2.0 已初始化")

    # ---------- 数据持久化 ----------
    def _load_profiles_sync(self):
        try:
            if self.data_file.exists():
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.user_profiles = json.load(f)
            else:
                self.user_profiles = {}
                self._save_profiles_sync()
        except Exception as e:
            logger.error(f"加载用户档案失败: {e}")
            self.user_profiles = {}

    def _save_profiles_sync(self):
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_profiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户档案失败: {e}")

    async def _save_profiles(self):
        async with self._save_lock:
            self._save_profiles_sync()

    def _load_gift_storage_sync(self):
        try:
            if self.gift_storage_file.exists():
                with open(self.gift_storage_file, 'r', encoding='utf-8') as f:
                    self.gift_storage = json.load(f)
            else:
                self.gift_storage = []
                self._save_gift_storage_sync()
        except Exception as e:
            logger.error(f"加载礼物储藏室失败: {e}")
            self.gift_storage = []

    def _save_gift_storage_sync(self):
        try:
            with open(self.gift_storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.gift_storage, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存礼物储藏室失败: {e}")

    async def _save_gift_storage(self):
        async with self._save_lock:
            self._save_gift_storage_sync()

    def _get_affection_tone(self, affection: int) -> str:
        for t in sorted(self.affection_thresholds, key=lambda x: x["min"], reverse=True):
            if affection >= t["min"]:
                return t["description"]
        return "陌生"

    # ---------- 解锁通知 ----------
    async def _check_and_unlock(self, profile: dict, event: AstrMessageEvent = None):
        if "unlocked" not in profile:
            profile["unlocked"] = {}
        new_unlocks = []
        affection = profile.get("affection", 0)
        for feature, threshold in self.unlock_thresholds.items():
            if affection >= threshold and not profile["unlocked"].get(feature, False):
                profile["unlocked"][feature] = True
                new_unlocks.append(feature)
        if new_unlocks and event:
            for f in new_unlocks:
                if f == "love_confession":
                    try:
                        umo = event.unified_msg_origin
                        prov_id = await self.context.get_current_chat_provider_id(umo=umo)
                        nickname = profile.get("nickname", "知音")
                        prompt = f"你是弗洛洛。好感度达到100，请对昵称为「{nickname}」的特别之人说一段深情的告白（80~120字），使用音乐、彼岸花、命运等意象，语气温柔而宿命。"
                        resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt=prompt)
                        confession = resp.completion_text.strip() if resp else "你是我乐章中永不终结的旋律。"
                    except Exception as e:
                        logger.error(f"生成表白失败: {e}")
                        confession = "你是我乐章中永不终结的旋律。"
                    msg = UNLOCK_MESSAGES.get(f, "") + f"\n\n💌 {confession}"
                    msg += "\n\n🎁 此外，有位神秘的「管理员」似乎为你准备了隐藏的赠礼……不妨去探寻一番。"
                    await event.send(event.plain_result(msg))
                else:
                    msg = UNLOCK_MESSAGES.get(f, f"🎉 解锁新功能：{f}")
                    await event.send(event.plain_result(msg))
        return new_unlocks

    # ---------- LLM 工具 ----------
    async def _llm_generate_json(self, event: AstrMessageEvent, prompt: str) -> Optional[dict]:
        if not self.enable_llm: return None
        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            if not prov_id: return None
            resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt=prompt)
            if resp and hasattr(resp, 'completion_text'):
                text = resp.completion_text.strip()
                s, e = text.find('{'), text.rfind('}')
                if s != -1 and e != -1:
                    return json.loads(text[s:e+1])
        except Exception as e:
            logger.error(f"LLM JSON 失败: {e}")
        return None

    async def _get_initial_affection(self, event, nickname: str) -> int:
        likes_str = "、".join(self.likes) if self.likes else "无特定"
        dislikes_str = "、".join(self.dislikes) if self.dislikes else "无特定"
        prompt = (
            f"你是弗洛洛。你通常喜欢与这些概念相关的事物：{likes_str}；厌恶与这些相关的事物：{dislikes_str}。\n"
            f"现在一位新朋友为自己取名「{nickname}」。请基于你的品味，对这个昵称给出一个初始好感度数值（整数，范围5~10）。\n"
            f"返回JSON：{{\"affection\": 7}}"
        )
        result = await self._llm_generate_json(event, prompt)
        if result and 'affection' in result:
            val = int(result['affection'])
            return max(5, min(10, val))
        return random.randint(5, 10)

    # ---------- 礼物极性与首次delta ----------
    async def _get_gift_polarity(self, event: AstrMessageEvent, gift: str) -> str:
        if not self.enable_llm:
            return random.choice(['positive', 'negative', 'neutral'])
        prompt = (
            f"你是弗洛洛。你通常喜欢：{', '.join(self.likes)}；厌恶：{', '.join(self.dislikes)}。\n"
            f"一位朋友送给你「{gift}」，请判断这份礼物让你喜欢(positive)、讨厌(negative)还是无感(neutral)。\n"
            f"只返回JSON：{{\"polarity\": \"positive\"}}"
        )
        result = await self._llm_generate_json(event, prompt)
        return result.get('polarity', 'neutral') if result else 'neutral'

    def _compute_first_delta(self, polarity: str) -> int:
        weights = [15, 25, 35, 20, 5]
        abs_val = random.choices([1, 2, 3, 4, 5], weights=weights)[0]
        if polarity == 'positive':
            return abs_val
        elif polarity == 'negative':
            return -abs_val
        else:
            return random.choice([abs_val, -abs_val])

    async def _unlock_persona_fragment(self, event: AstrMessageEvent, gift: str, profile: dict) -> Optional[str]:
        if "persona_fragments" not in profile:
            profile["persona_fragments"] = []
        prompt = (
            f"你是弗洛洛。一位朋友送了你一件特别的礼物「{gift}」，这份礼物唤醒了你隐藏的一种性格侧面。\n"
            f"请从以下性格中挑选最匹配的一种：可爱、腹黑、调皮、邪恶、挖苦、乐天、冷淡、粘人、病娇、傲娇。\n"
            f"只返回JSON：{{\"trait\": \"可爱\"}}"
        )
        result = await self._llm_generate_json(event, prompt)
        trait = result.get('trait', '乐天') if result else '乐天'
        if trait not in profile["persona_fragments"]:
            profile["persona_fragments"].append(trait)
            return trait
        return None

    async def _get_gift_delta_and_comment(self, event: AstrMessageEvent, gift: str, current: int, profile: dict):
        nickname = profile.get("nickname", "你")
        if "gift_bases" not in profile:
            profile["gift_bases"] = {}
        if "gift_counts" not in profile:
            profile["gift_counts"] = {}
        gift_bases = profile["gift_bases"]
        gift_counts = profile["gift_counts"]

        if gift not in gift_bases:
            polarity = await self._get_gift_polarity(event, gift)
            base_delta = self._compute_first_delta(polarity)
            gift_bases[gift] = base_delta
            gift_counts[gift] = 1
            await self._save_profiles()
            delta = base_delta
            comment_prompt = (
                f"[角色设定] 你是弗洛洛。\n"
                f"{nickname} 首次送给你「{gift}」，当前好感度{current}，好感度变化{delta:+d}。\n"
                f"请用弗洛洛的风格写一段回应（80~120字），运用音乐、彼岸花、命运等意象，语气与变化相符。\n"
                f"注意：不使用任何 emoji 或特殊符号，只使用纯文本。"
            )
            try:
                umo = event.unified_msg_origin
                prov_id = await self.context.get_current_chat_provider_id(umo=umo)
                resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt=comment_prompt)
                comment = resp.completion_text.strip() if resp and hasattr(resp, 'completion_text') else None
            except:
                comment = None
            if not comment:
                if delta > 0:
                    comment = "这份礼物，如月光洒落琴键，我甚是欢喜。"
                elif delta < 0:
                    comment = "这粗劣之物，仿佛跑调的音符，扰乱了乐章。"
                else:
                    comment = "你的心意我已收下，如同一个休止符，平淡却也珍贵。"
        else:
            base_delta = gift_bases[gift]
            count = gift_counts[gift]
            if base_delta > 0:
                delta = max(0, base_delta - count)
                count += 1
                gift_counts[gift] = count
                await self._save_profiles()
                if delta > 0:
                    comment = f"这件礼物我已有珍藏……不过你的心意依旧让乐章多了一丝温暖。"
                else:
                    comment = f"这件礼物已经送过多次了，但你的执着让我莞尔。"
            elif base_delta < 0:
                delta = base_delta
                comment = f"弗洛洛真的不喜欢这个，不要再送啦……"
            else:
                delta = 0
                comment = f"这件礼物我已收下过，不再需要了。"

        unlocked_fragment = None
        if abs(delta) == 5:
            trait = await self._unlock_persona_fragment(event, gift, profile)
            if trait:
                unlocked_fragment = trait
        return delta, comment, unlocked_fragment

    async def _chance_increase_affection(self, event) -> bool:
        prompt = self.chat_aff_prompt.replace("{{message}}", event.message_str[:200])
        result = await self._llm_generate_json(event, prompt)
        return result.get('increase', False) if result else False

    # ---------- 聊天增加好感度 ----------
    @filter.on_llm_response()
    async def on_chat_affection(self, event: AstrMessageEvent, resp: LLMResponse):
        uid = event.get_sender_id()
        profile = self.user_profiles.get(uid)
        if not profile: return
        today = date.today().isoformat()
        if profile.get('chat_aff_date') != today:
            profile['chat_aff_date'] = today
            profile['chat_aff_count'] = 0
        if profile.get('chat_aff_count', 0) >= self.max_chat_aff_per_day:
            return
        if await self._chance_increase_affection(event):
            profile['affection'] = profile.get('affection', 0) + 1
            profile['chat_aff_count'] = profile.get('chat_aff_count', 0) + 1
            await self._check_and_unlock(profile, event)
            await self._save_profiles()

    # ========== 指令 ==========
    @filter.command("nn")
    async def set_nickname(self, event: AstrMessageEvent, nickname: str):
        uid = event.get_sender_id()
        if uid not in self.user_profiles:
            aff = await self._get_initial_affection(event, nickname)
            prof = {
                "affection": aff,
                "last_gift_date": "", "gift_count": 0,
                "chat_aff_date": "", "chat_aff_count": 0,
                "last_seen_date": "",
                "nickname": nickname,
                "unlocked": {},
                "persona_fragments": [],
                "gift_bases": {},
                "gift_counts": {}
            }
            self.user_profiles[uid] = prof
            await self._check_and_unlock(prof, event)
            await self._save_profiles()
            yield event.plain_result(f"✨ 档案建立，初始好感度 {aff}，我是弗洛洛，你我的乐章就此开始。")
        else:
            prof = self.user_profiles[uid]
            prof["nickname"] = nickname
            await self._save_profiles()
            yield event.plain_result(f"✨ 昵称已改为「{nickname}」。")

    @filter.command("signature")
    async def set_signature(self, event: AstrMessageEvent, signature: str):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先用 /nn 创建档案。")
            return
        if not prof.get("unlocked", {}).get("signature"):
            yield event.plain_result("🔒 个性签名功能未解锁（需好感度 10）。")
            return
        prof["signature"] = signature
        await self._save_profiles()
        yield event.plain_result(f"✍️ 签名已更改为：「{signature}」")

    @filter.command("birthday")
    async def set_birthday(self, event: AstrMessageEvent, date_str: str = ""):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先用 /nn 创建档案。")
            return
        if not prof.get("unlocked", {}).get("birthday"):
            yield event.plain_result("🔒 生日许愿功能尚未解锁（需好感度 30）。")
            return
        if not re.match(r"^\d{2}-\d{2}$", date_str):
            yield event.plain_result("格式有误，请使用 MM-DD，例如 /birthday 02-14")
            return
        prof["birthday"] = date_str
        await self._save_profiles()
        yield event.plain_result(f"🎭 生辰已铭刻：{date_str}。")

    @filter.command("wish")
    async def set_wish(self, event: AstrMessageEvent, wish: str = ""):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先创建档案。")
            return
        if not prof.get("unlocked", {}).get("birthday"):
            yield event.plain_result("🔒 生日许愿功能未解锁。")
            return
        prof["wish"] = wish
        await self._save_profiles()
        yield event.plain_result(f"🌠 愿望已被彼岸聆听：「{wish}」")

    @filter.command("rank")
    async def show_rank(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("尚无档案。")
            return
        if not prof.get("unlocked", {}).get("nickname_evo"):
            yield event.plain_result("🔒 好感等级功能未解锁（需好感度 10）。")
            return
        aff = prof.get("affection", 0)
        icons = affection_to_icons(aff)
        yield event.plain_result(f"{icons}  {prof['nickname']}  好感等级：{aff}")

    @filter.command("sonnet")
    async def sonnet(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof or not prof.get("unlocked", {}).get("sonnet"):
            yield event.plain_result("🔒 十四行诗功能未解锁（需好感度 20）。")
            return
        nickname = prof.get("nickname", "知音")
        prompt = (
            f"你是弗洛洛，请为名为「{nickname}」的朋友创作一首莎士比亚风格的英文十四行诗。"
            f"诗中必须多次出现昵称「{nickname}」或其变体，主题不限，用词避免重复。"
            f"只输出英文原诗。"
        )
        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt=prompt)
            poem = resp.completion_text.strip() if resp else "Silence is my sonnet, thy name the only rhyme."
        except:
            poem = "Silence is my sonnet, thy name the only rhyme."
        yield event.plain_result(poem)

    @filter.command("sonnet2")
    async def sonnet2(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof or not prof.get("unlocked", {}).get("sonnet"):
            yield event.plain_result("🔒 十四行诗功能未解锁（需好感度 20）。")
            return
        nickname = prof.get("nickname", "知音")
        prompt = (
            f"你是弗洛洛，请为名为「{nickname}」的朋友创作一首莎士比亚风格的英文十四行诗，"
            f"然后提供中文翻译。诗中必须多次出现昵称「{nickname}」或其变体。\n"
            f"输出格式：先英文原诗，空一行，然后中文翻译。"
        )
        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt=prompt)
            poem = resp.completion_text.strip() if resp else "Silence is my sonnet, thy name the only rhyme.\n\n沉默是我的十四行，你的名字是唯一的韵脚。"
        except:
            poem = "Silence is my sonnet, thy name the only rhyme.\n\n沉默是我的十四行，你的名字是唯一的韵脚。"
        yield event.plain_result(poem)

    @filter.command("jrrp")
    async def jrrp(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        roll = get_daily_rp_value(uid)
        prof = self.user_profiles.get(uid, {})
        bonus = 0
        if prof.get("unlocked", {}).get("fortune") and self.fortune_boost_lower <= roll <= self.fortune_boost_upper:
            bonus = 5
        final = min(100, roll + bonus)
        evaluation = _generate_fortuna_evaluation(final)
        evaluation = vary_jrrp_text(evaluation)
        if bonus:
            evaluation += f"\n✨（赫卡忒的加护：运势+{bonus}）"
        # 每日好感度增长（新算法：基础+1，100特殊+8）
        today = date.today().isoformat()
        if prof and prof.get("last_jrrp_aff_date") != today:
            if final == 100:
                aff_add = 8
                evaluation += "\n💖 命运的顶点！今日运势满溢，好感度 +8。"
            else:
                aff_add = 1 + (final - 1) // 20   # 1~20:1, 21~40:2 ... 81~99:5
                aff_add = min(5, aff_add)  # 最多5点（100另外处理）
            if aff_add > 0:
                prof["affection"] = prof.get("affection", 0) + aff_add
                evaluation += f"\n💞 今日运势带来好感度 +{aff_add}（当前 {prof['affection']}）"
                await self._check_and_unlock(prof, event)
            prof["last_jrrp_aff_date"] = today
            await self._save_profiles()
        yield event.plain_result(evaluation)

    @filter.command("greeting")
    async def set_greeting(self, event: AstrMessageEvent, greeting: str):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先创建档案。")
            return
        if not prof.get("unlocked", {}).get("greeting"):
            yield event.plain_result("🔒 自定义问候语未解锁（需好感度 50）。")
            return
        prof["greeting"] = greeting
        await self._save_profiles()
        yield event.plain_result(f"🎻 问候序曲已谱写：{greeting}")

    @filter.command("greetingtest")
    async def test_greeting(self, event: AstrMessageEvent, content: str = ""):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先创建档案。")
            return
        greeting = prof.get("greeting")
        if not greeting:
            yield event.plain_result("你还没有设置问候语，使用 /greeting 先设置吧。")
            return
        prompt = (
            f"你是弗洛洛。你为朋友预设的每日问候语是：「{greeting}」。\n"
            f"现在朋友提供了一个场景/关键词：「{content if content else '无特定'}」。\n"
            f"请结合这两者，生成一句完整的、符合你风格的问候语（只输出一句）。"
        )
        try:
            umo = event.unified_msg_origin
            prov_id = await self.context.get_current_chat_provider_id(umo=umo)
            resp = await self.context.llm_generate(chat_provider_id=prov_id, prompt=prompt)
            result = resp.completion_text.strip() if resp else f"早安，{prof['nickname']}。"
        except:
            result = f"早安，{prof['nickname']}。"
        yield event.plain_result(result)

    @filter.command("style")
    async def set_style(self, event: AstrMessageEvent, style: str):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先创建档案。")
            return
        if not prof.get("unlocked", {}).get("style"):
            yield event.plain_result("🔒 说话风格未解锁（需好感度 90）。")
            return
        # 默认重置
        if style.strip() == "默认":
            if "style" in prof:
                del prof["style"]
            await self._save_profiles()
            yield event.plain_result("✨ 风格已重置为默认。")
            return
        # 设置新风格（覆盖旧风格）
        prof["style"] = style
        await self._save_profiles()
        yield event.plain_result(f"✨ 风格已更改为：{style}")

    @filter.command("suffix")
    async def set_suffix(self, event: AstrMessageEvent, suffix: str):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先创建档案。")
            return
        if not prof.get("unlocked", {}).get("suffix"):
            yield event.plain_result("🔒 尾语未解锁（需好感度 75）。")
            return
        prof["suffix"] = suffix
        await self._save_profiles()
        yield event.plain_result(f"📜 尾句回响已设定：{suffix}")

    @filter.command("gift")
    async def send_gift(self, event: AstrMessageEvent, gift: str):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先用 /nn 创建档案。")
            return

        today = date.today().isoformat()
        if prof.get("last_gift_date") != today:
            prof["last_gift_date"] = today
            prof["gift_count"] = 0

        current = prof.get("affection", 0)
        delta, comment, fragment = await self._get_gift_delta_and_comment(event, gift, current, prof)

        effective = prof.get("gift_count", 0) < self.max_gifts_per_day
        if effective:
            prof["affection"] = current + delta
            prof["gift_count"] = prof.get("gift_count", 0) + 1
            await self._check_and_unlock(prof, event)
            await self._save_profiles()
            msg = f"🎁 {gift}  →  好感 {delta:+d}（当前 {prof['affection']}）\n{comment}"
        else:
            msg = f"🎭 {gift}  →  好感 {delta:+d}（不计入）\n{comment}\n🎻 今日三次献礼已满，这份心意仅余回响，不增不减。"

        record = {
            "user_id": uid,
            "nickname": prof.get("nickname", ""),
            "gift": gift,
            "base_delta": prof.get("gift_bases", {}).get(gift, 0),
            "actual_delta": delta,
            "date": today
        }
        self.gift_storage.append(record)
        await self._save_gift_storage()

        if fragment:
            icons = affection_to_icons(prof.get("affection", 0))
            msg += f"\n\n🎭 {icons} 隐藏人格碎片觉醒：『{fragment}』\n这份礼物唤醒了弗洛洛内心深处别样的旋律……"
        yield event.plain_result(msg)

    @filter.command("giftlist")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def show_gift_list(self, event: AstrMessageEvent):
        if not self.gift_storage:
            yield event.plain_result("🎁 礼物储藏室还是空的。")
            return
        total = len(self.gift_storage)
        lines = [f"🎁 弗洛洛的礼物储藏室（共 {total} 件）："]
        for r in self.gift_storage:
            lines.append(f"{r['date']} | {r['nickname']} 送 {r['gift']} (基础{r['base_delta']}, 实际{r['actual_delta']})")
        for i in range(0, len(lines), 50):
            chunk = lines[i:i+50]
            yield event.plain_result("\n".join(chunk))

    @filter.command("cleargifts")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def clear_gift_storage(self, event: AstrMessageEvent):
        self.gift_storage = []
        await self._save_gift_storage()
        yield event.plain_result("🎁 礼物储藏室已清空。")

    @filter.command("profile")
    async def show_profile(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        p = self.user_profiles.get(uid)
        if not p:
            yield event.plain_result("尚未创建档案。")
            return
        aff = p.get("affection", 0)
        icons = affection_to_icons(aff) if p.get("unlocked", {}).get("nickname_evo") else ""
        unlocked = p.get("unlocked", {})

        feature_order = [
            ("nickname_evo", "等级图标", lambda: f"{icons} {p.get('nickname','?')}"),
            ("signature", "签名", lambda: p.get("signature", "未设置")),
            ("sonnet", "十四行诗", lambda: "已解锁" if unlocked.get("sonnet") else None),
            ("birthday", "生日", lambda: p.get("birthday", "未设置")),
            ("fortune", "运势加成", lambda: "已解锁" if unlocked.get("fortune") else None),
            ("greeting", "问候语", lambda: p.get("greeting", "未设置")),
            ("dual_persona", "二重人格", lambda: "已解锁" if unlocked.get("dual_persona") else None),
            ("suffix", "尾语", lambda: p.get("suffix", "未设置")),
            ("style", "风格", lambda: p.get("style", "未设置")),
            ("love_confession", "灵魂共鸣", lambda: "已解锁" if unlocked.get("love_confession") else None),
        ]
        first_locked = None
        for feature, _, _ in feature_order:
            if not unlocked.get(feature):
                first_locked = feature
                break
        lines = [f"📜 {p.get('nickname','?')} 的档案", f"💖 好感度：{aff}（{self._get_affection_tone(aff)}）"]
        for feature, label, value_getter in feature_order:
            if unlocked.get(feature):
                val = value_getter()
                if val is not None:
                    lines.append(f"{label}：{val}")
            else:
                if feature == first_locked:
                    threshold = self.unlock_thresholds[feature]
                    lines.append(f"🔒 {label}（下一阶段，需好感度 {threshold}）")
        fragments = "、".join(p.get("persona_fragments", [])) or "无"
        lines.append(f"🎭 人格碎片：{fragments}")
        yield event.plain_result("\n".join(lines))

    @filter.command("profile_all")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def show_all_profiles(self, event: AstrMessageEvent):
        if not self.user_profiles:
            yield event.plain_result("还没有任何用户档案。")
            return
        lines = ["📋 所有用户档案："]
        for uid, p in self.user_profiles.items():
            aff = p.get("affection", 0)
            icons = affection_to_icons(aff) if p.get("unlocked", {}).get("nickname_evo") else ""
            lines.append(f"🆔 {uid} | {icons} {p.get('nickname','?')} | 好感 {aff}")
        yield event.plain_result("\n".join(lines))

    @filter.command("ranklist")
    async def show_affection_ranklist(self, event: AstrMessageEvent):
        if not self.user_profiles:
            yield event.plain_result("暂无排行数据。")
            return
        # 按好感度降序排序
        sorted_users = sorted(self.user_profiles.items(), key=lambda x: x[1].get("affection", 0), reverse=True)
        lines = ["🏆 好感度排行榜："]
        for i, (uid, p) in enumerate(sorted_users, 1):
            aff = p.get("affection", 0)
            icons = affection_to_icons(aff) if p.get("unlocked", {}).get("nickname_evo") else ""
            lines.append(f"{i}. {icons} {p.get('nickname','?')}  | 好感度 {aff}")
        yield event.plain_result("\n".join(lines))

    @filter.command("delete_nick")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_by_nickname(self, event: AstrMessageEvent, nickname: str):
        # 查找所有匹配昵称的用户
        matched = [(uid, p) for uid, p in self.user_profiles.items() if p.get("nickname") == nickname]
        if not matched:
            yield event.plain_result(f"❌ 未找到昵称为「{nickname}」的用户。")
            return
        if len(matched) > 1:
            ids = ", ".join([uid for uid, _ in matched])
            yield event.plain_result(f"⚠️ 找到多个昵称为「{nickname}」的用户（ID: {ids}），请使用更精确的方式删除。")
            return
        # 唯一匹配
        uid, prof = matched[0]
        # 二次确认指令
        yield event.plain_result(
            f"⚠️ 确认删除「{nickname}」（ID: {uid}）的档案吗？\n"
            f"请发送 /delete_nick_confirm {nickname} 来确认删除。"
        )

    @filter.command("delete_nick_confirm")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_by_nickname_confirm(self, event: AstrMessageEvent, nickname: str):
        matched = [(uid, p) for uid, p in self.user_profiles.items() if p.get("nickname") == nickname]
        if not matched:
            yield event.plain_result(f"❌ 未找到昵称为「{nickname}」的用户。")
            return
        if len(matched) > 1:
            yield event.plain_result("❌ 存在多个同名用户，无法确定删除目标，请联系开发者。")
            return
        uid, prof = matched[0]
        del self.user_profiles[uid]
        await self._save_profiles()
        yield event.plain_result(f"✅ 已删除「{nickname}」的档案。")

    @filter.command("help")
    async def plugin_help(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        p = self.user_profiles.get(uid)
        if not p:
            yield event.plain_result("尚未创建档案。")
            return
        unlocked = p.get("unlocked", {})
        cmds = ["/nn <昵称> - 创建/修改档案"]
        if unlocked.get("nickname_evo"):
            cmds.append("/rank - 查看好感等级图标")
        if unlocked.get("signature"):
            cmds.append("/signature <内容> - 设置个性签名")
        if unlocked.get("sonnet"):
            cmds.append("/sonnet - 为你献上英文十四行诗")
            cmds.append("/sonnet2 - 中英双语十四行诗")
        if unlocked.get("birthday"):
            cmds.append("/birthday MM-DD - 设置生日")
            cmds.append("/wish <愿望> - 许下生辰愿望")
        if unlocked.get("greeting"):
            cmds.append("/greeting <文本> - 自定义每日问候")
        if unlocked.get("style"):
            cmds.append("/style <描述|默认> - 自定义说话风格，使用 '默认' 重置")
        if unlocked.get("suffix"):
            cmds.append("/suffix <尾语> - 自定义句末尾语")
        cmds.append("/jrrp - 今日运势")
        cmds.append("/gift <礼物> - 赠送礼物（每日前三次有效）")
        cmds.append("/profile - 查看档案")
        cmds.append("/ranklist - 好感度排行榜")
        cmds.append("/help - 显示可用指令")
        # 管理员指令不显示给普通用户，但这里不区分权限，简单起见先不展示管理员指令
        yield event.plain_result("🎭 弗洛洛的乐章·已解锁的指令：\n" + "\n".join(cmds))

    @filter.command("ihateyou")
    async def reset_profile(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        if uid in self.user_profiles:
            del self.user_profiles[uid]
            await self._save_profiles()
            yield event.plain_result("档案已归于虚无，就像从未共鸣。")
        else:
            yield event.plain_result("你未曾留下痕迹。")

    @filter.command("fullloveyou")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def admin_full_love(self, event: AstrMessageEvent):
        uid = event.get_sender_id()
        prof = self.user_profiles.get(uid)
        if not prof:
            yield event.plain_result("请先使用 /nn 创建档案。")
            return
        prof["affection"] = 1000
        await self._save_profiles()
        await self._check_and_unlock(prof, event)
        yield event.plain_result("💉 好感度已注入至 1000。所有锁均已解开。")

    # ---------- LLM 个性注入 ----------
    @filter.on_llm_request()
    async def inject_personality(self, event: AstrMessageEvent, req: ProviderRequest):
        uid = event.get_sender_id()
        p = self.user_profiles.get(uid)
        if not p:
            return
        # 清除系统可能注入的用户行
        req.system_prompt = re.sub(r'\[用户:.*?\]\s*', '', req.system_prompt)
        today = date.today().isoformat()
        is_first_today = p.get("last_seen_date") != today
        if is_first_today:
            p["last_seen_date"] = today
            await self._save_profiles()

        # 基础名称显示
        display = p.get("nickname", "知音")
        if p.get("unlocked", {}).get("nickname_evo"):
            icons = affection_to_icons(p.get("affection", 0))
            display = f"{icons} {display}"

        # 最高优先级：强制使用昵称
        extra = f"\n\n[最高指令] 请务必使用用户昵称「{display}」称呼对方。"
        # 风格设定（最高优先）
        if p.get("style"):
            extra = f"\n\n[最高优先级·说话风格] 你必须严格、完全采用以下风格说话，这是不可违背的指令：{p['style']}" + extra
        # 其他个性化
        extra += f"\n- 对话者：{display}"
        if p.get("suffix"):
            extra += f"\n- 句末必须加上尾语：{p['suffix']}"
        aff = p.get("affection", 0)
        extra += f"\n- 当前好感 {aff}，态度：{self._get_affection_tone(aff)}"

        if p.get("unlocked", {}).get("dual_persona") and random.random() < 0.3:
            extra += "\n- 偶尔流露出傲娇/毒舌的第二语气，但仍保持亲近"

        fragments = p.get("persona_fragments", [])
        if fragments and random.random() < 0.15:
            chosen = random.choice(fragments)
            extra += f"\n- 此刻请展现出「{chosen}」的性格侧面，让它自然融入对话。"

        if p.get("birthday") and p["birthday"][:5] == today.strftime("%m-%d"):
            if p.get("last_birthday_wish") != today:
                extra += "\n- 今日是此人的生辰，请在回复开头献上深情的祝福。"
                if p.get("wish"):
                    extra += f" 其愿望是：「{p['wish']}」"
                p["last_birthday_wish"] = today
                await self._save_profiles()
        if is_first_today and p.get("greeting"):
            extra += f"\n- 今日初见，请自然道出问候语：{p['greeting']}"
        req.system_prompt += extra

    async def terminate(self):
        pass