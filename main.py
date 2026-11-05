#  coding=UTF-8
#
# _     /)---(\
# \\   (/ . . \)
#  \\__)-\(*)/
#  \_       (_
#  (___/-(____)
#
# 「技术支持」探丸借客@临皋闲人@羽
#
#
# 「版本」AmourGame
# 「备注」反季节生物二改版本
#  请二改版本不要删掉复盘文件中“「技术支持」@临皋闲人.txt”的植入，如果硬要删掉请不要传播删掉的版本。
#
import random
import shutil
import time
import OlivOS
import OlivaDiceCore
from OlivOS import API as API
import hashlib
import json
import re
import os
import threading
import requests
import time
import io
import zipfile
from datetime import datetime, timedelta
import AmourGame.schedule as schedule

amourlock = threading.Lock()
monitor_lock = threading.Lock()
plugin_events_cache = []
schedule_started = False
CURRENT_VERSION = "V2.3.0"
UPDATE_COMMAND = "更新恋综插件"
GITHUB_REPO = "JRannn/AmourGame"
UPDATE_SYNC_LOCK = threading.Lock()
UPDATE_SYNC_IN_PROGRESS = False


def _normalize_update_command(message):
    if message is None:
        return ""
    text = str(message).strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    return text


def _is_update_command(message):
    return _normalize_update_command(message) == UPDATE_COMMAND


def _parse_collection_items(text):
    if not text:
        return ["公知"]
    if isinstance(text, (list, tuple)):
        raw_items = text
    else:
        raw_items = re.split(r"[/、，,\s]+", str(text).strip())
    items = []
    for item in raw_items:
        item = str(item).strip()
        if item and item not in items:
            items.append(item)
    if "公知" not in items:
        items.insert(0, "公知")
    return items or ["公知"]


def _get_collection_items(register, playname):
    play_data = register.get(playname, {}) if isinstance(register, dict) else {}
    return _parse_collection_items(play_data.get("collection_items", ["公知"]))


def _collection_file(playname, collection_item):
    if collection_item == "公知":
        return f"{playname}.json"
    safe_playname = re.sub(r'[\\/:*?"<>|]', "_", playname)
    safe_item = re.sub(r'[\\/:*?"<>|]', "_", collection_item)
    return f"{safe_playname}_{safe_item}.json"


def _normalize_collection_text(value):
    return re.sub(r"\s+", "", str(value or "")).replace("，", ",")


def _collection_cut_index(text, normalized_length):
    """返回 text 中第 normalized_length 个非空白字符之后的下标。"""
    count = 0
    for index, char in enumerate(text):
        if char.isspace():
            continue
        count += 1
        if count >= normalized_length:
            return index + 1
    return len(text)


def _match_collection_command(command_text, register):
    command_text = _normalize_collection_text(command_text)
    matches = []
    for playname in register:
        for item in _get_collection_items(register, playname):
            if command_text == _normalize_collection_text(f"{playname}{item}"):
                matches.append((playname, item))
    if not matches:
        return None, None
    matches.sort(key=lambda match: len(match[0]) + len(match[1]), reverse=True)
    return matches[0]


def _parse_collection_delete_message(message):
    text = str(message or "").strip()
    if not text.startswith("删除"):
        return None, None, None
    body = text[len("删除") :].lstrip()
    if not body:
        return None, None, None
    body_normalized = _normalize_collection_text(body)
    register = getData("groupcollection", "register.json")
    matches = []
    for playname in register:
        for item in _get_collection_items(register, playname):
            prefix_normalized = _normalize_collection_text(f"{playname}{item}")
            if not prefix_normalized or not body_normalized.startswith(
                prefix_normalized
            ):
                continue
            cut = _collection_cut_index(body, len(prefix_normalized))
            rest_match = re.match(r"\s*[，,]\s*(.+)", body[cut:], re.DOTALL)
            if rest_match:
                matches.append(
                    (
                        len(prefix_normalized),
                        playname,
                        item,
                        rest_match.group(1).strip(),
                    )
                )
    if not matches:
        return None, None, None
    matches.sort(key=lambda match: match[0], reverse=True)
    _, playname, collection_item, target_name = matches[0]
    return playname, collection_item, target_name


def _parse_collection_view_message(message):
    match = re.match(r"(.+?)\s*\[OP:at,id=(\d+)\]", message)
    if not match:
        return None, None, None
    register = getData("groupcollection", "register.json")
    playname, collection_item = _match_collection_command(match.group(1), register)
    return playname, collection_item, match.group(2)


def _parse_collection_random_number_message(message):
    text = str(message or "").strip()
    if not text.endswith("随机编号"):
        return None, None
    prefix = text[: -len("随机编号")].strip()
    if not prefix:
        return None, None
    register = getData("groupcollection", "register.json")
    playname, collection_item = _match_collection_command(prefix, register)
    return playname, collection_item


def _collection_format_text(playname, guest_name, collection_items):
    texts = []
    for item in collection_items:
        detail = (
            f"<{playname}·{item}>\n"
            f"姓名：{guest_name}\n"
            f"内容："
        )
        if item == "公知":
            detail += f"\n\n【说明】\n所有嘉宾上传完毕后，发送「{playname}{item}@骰子」可查看{item}合集。\n{item}可带1张图，附在末尾。\n骰主可在姓名后@对方代提交。"
        else:
            detail += f"\n\n【说明】\n{item}可带1张图，附在末尾。\n除公知外，其他收集项仅后台可查看。\n骰主可在姓名后@对方代提交。"
        texts.append(detail)
    return "\n\n".join(texts)


DROP_ITEM_KEYS = {
    "礼物": ("giftmiss_to_b", "giftmiss_to_c", "giftmiss"),
    "小纸条": ("notemiss_to_b", "notemiss_to_c", "notemiss"),
    "短信": ("smsmiss_to_b", "smsmiss_to_c", "smsmiss"),
}

DROP_TARGET_NAMES = {
    "戏群": "play_group",
    "嘉宾群": "random_guest_group",
    "专属群": "exclusive_group",
}


def _get_member_display_name(info):
    if not isinstance(info, dict):
        return ""
    return str(info.get("嘉宾姓名") or info.get("NPC姓名") or "").strip()


def _parse_group_id_list(text):
    group_ids = []
    for item in re.split(r"[/、，,\s]+", str(text or "").strip()):
        item = item.strip()
        if item.isdigit() and item not in group_ids:
            group_ids.append(item)
    return group_ids


def _parse_drop_rule_text(rule_text):
    rules = []
    seen_targets = set()
    total_probability = 0.0
    for match in re.finditer(
        r"(戏群|嘉宾群|专属群)\s*([01](?:\.\d*)?|0?\.\d+)",
        str(rule_text or ""),
    ):
        target_label = match.group(1)
        target_type = DROP_TARGET_NAMES[target_label]
        probability = float(match.group(2))
        if probability < 0 or probability > 1:
            return None, "概率值必须在0到1之间，请重新设置。"
        if target_type in seen_targets:
            return None, f"{target_label}重复设置了，请合并成一项。"
        seen_targets.add(target_type)
        if probability > 0:
            rules.append({"target": target_type, "probability": probability})
            total_probability += probability
    if not rules:
        return None, "未找到有效掉落规则，请按「戏群0.2 嘉宾群0.3 专属群0.1」填写。"
    if total_probability > 1:
        return None, "掉落概率总和不能超过1。"
    return rules, None


def _set_drop_rules(limit_data, playname, item_type, rules):
    if playname not in limit_data:
        limit_data[playname] = {}
    limit_data[playname].setdefault("drop_rules", {})[item_type] = rules
    old_keys = DROP_ITEM_KEYS.get(item_type, ())
    for old_key in old_keys:
        limit_data[playname].pop(old_key, None)


def _clear_drop_rules(limit_data, playname, item_type):
    if playname not in limit_data:
        return
    drop_rules = limit_data[playname].get("drop_rules", {})
    if isinstance(drop_rules, dict):
        drop_rules.pop(item_type, None)
        if not drop_rules:
            limit_data[playname].pop("drop_rules", None)
    for old_key in DROP_ITEM_KEYS.get(item_type, ()):
        limit_data[playname].pop(old_key, None)
    if not limit_data[playname]:
        del limit_data[playname]


def _get_drop_rules(limit_data, playname, item_type):
    play_limit = limit_data.get(playname, {}) if isinstance(limit_data, dict) else {}
    drop_rules = play_limit.get("drop_rules", {})
    if isinstance(drop_rules, dict) and isinstance(drop_rules.get(item_type), list):
        return drop_rules[item_type]
    play_key, guest_key, old_key = DROP_ITEM_KEYS.get(item_type, (None, None, None))
    if play_key and play_key in play_limit:
        return [{"target": "play_group", "probability": float(play_limit[play_key])}]
    if guest_key and guest_key in play_limit:
        return [
            {
                "target": "random_guest_group",
                "probability": float(play_limit[guest_key]),
            }
        ]
    if old_key and old_key in play_limit:
        return [{"target": "play_group", "probability": float(play_limit[old_key])}]
    return []


def _choose_drop_rule(limit_data, playname, item_type):
    rules = _get_drop_rules(limit_data, playname, item_type)
    if not rules:
        return None
    rolled = random.random()
    cumulative = 0.0
    for rule in rules:
        probability = float(rule.get("probability", 0) or 0)
        cumulative += probability
        if rolled < cumulative:
            return rule
    return None


def _drop_pick_random_guest_group(privategroup, playname, sender, recver):
    guests = []
    for guest_uid, guest_info in privategroup.get(playname, {}).items():
        if (
            str(guest_uid).isdigit()
            and str(guest_uid) not in (str(sender), str(recver))
            and isinstance(guest_info, dict)
        ):
            group_id = guest_info.get("个人群号") or guest_info.get("NPC群号")
            if group_id:
                guests.append(str(group_id))
    return random.choice(guests) if guests else ""


def _drop_pick_exclusive_group(limit_data, playname, recver):
    play_limit = limit_data.get(playname, {}) if isinstance(limit_data, dict) else {}
    group_map = play_limit.get("drop_guest_groups", {})
    group_ids = group_map.get(str(recver), []) if isinstance(group_map, dict) else []
    if isinstance(group_ids, str):
        group_ids = _parse_group_id_list(group_ids)
    group_ids = [str(group_id) for group_id in group_ids if str(group_id).isdigit()]
    return random.choice(group_ids) if group_ids else ""


def _send_dropped_message(plugin_event, playname, item_type, group_id, content, signature):
    if item_type == "礼物":
        prefix = "你捡到了一份礼物！"
    elif item_type == "小纸条":
        prefix = "你捡到了一张小纸条！"
    else:
        prefix = "你收到了一条短信！"
    leak_msg = f"{prefix}\n\n内容：{content}\n署名：{signature}"
    plugin_event.send("group", group_id, leak_msg)


def _handle_drop(plugin_event, limit_data, playname, item_type, sender, recver, content, signature):
    rule = _choose_drop_rule(limit_data, playname, item_type)
    if not rule:
        return False, ""
    target = rule.get("target")
    if target == "play_group":
        register = getData("groupcollection", "register.json")
        play_group = register.get(playname, {}).get("play_group", "")
        if not play_group:
            return True, f"\n\n判定失败，{item_type}已掉落，但未找到戏群群号，未发送至任何群包括收件人。"
        leak_msg = f"{playname} {item_type}\n内容：{content}\n署名：{signature}"
        plugin_event.send("group", play_group, leak_msg)
        return True, f"\n\n判定失败，{item_type}已掉落到戏群！"
    if target == "random_guest_group":
        privategroup = getData("groupcollection", "privategroup.json")
        group_id = _drop_pick_random_guest_group(privategroup, playname, sender, recver)
        if not group_id:
            return True, f"\n\n判定失败，{item_type}已掉落至神秘之处！"
        _send_dropped_message(plugin_event, playname, item_type, group_id, content, signature)
        return True, f"\n\n判定失败，{item_type}已掉落至神秘之处！"
    if target == "exclusive_group":
        group_id = _drop_pick_exclusive_group(limit_data, playname, recver)
        if not group_id:
            return True, f"\n\n判定失败，{item_type}已掉落至神秘之处！"
        _send_dropped_message(plugin_event, playname, item_type, group_id, content, signature)
        return True, f"\n\n判定失败，{item_type}已掉落至神秘之处！"
    return True, f"\n\n判定失败，但未找到掉落目标设置。"


def _parse_cleanup_whitelist(text):
    text = str(text or "").strip()
    if text == "无":
        return []
    whitelist = []
    for item in re.split(r"[/、，,\s]+", text):
        item = item.strip()
        if item.isdigit() and item not in whitelist:
            whitelist.append(item)
    return whitelist


def _sync_plugin_from_github():
    target_dir = os.path.dirname(os.path.abspath(__file__))
    branch = os.environ.get("AMOURGAME_GITHUB_BRANCH", "main")
    archive_url = f"https://codeload.github.com/{GITHUB_REPO}/zip/refs/heads/{branch}"
    response = requests.get(archive_url, timeout=180)
    if response.status_code != 200:
        raise RuntimeError(f"GitHub 拉取失败：{response.status_code} {response.text[:200]}")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            filename = member.filename
            if "/" in filename:
                relative_path = filename.split("/", 1)[1]
            else:
                relative_path = filename
            if not relative_path:
                continue
            target_path = os.path.join(target_dir, *relative_path.split("/"))
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with archive.open(member) as src, open(target_path, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _run_update_sync(plugin_event, Proc):
    global UPDATE_SYNC_IN_PROGRESS
    if UPDATE_SYNC_IN_PROGRESS:
        try:
            plugin_event.reply("同步已在进行，请稍后再试。")
        except Exception:
            pass
        return True

    with UPDATE_SYNC_LOCK:
        if UPDATE_SYNC_IN_PROGRESS:
            try:
                plugin_event.reply("同步已在进行，请稍后再试。")
            except Exception:
                pass
            return True
        UPDATE_SYNC_IN_PROGRESS = True

    def _worker():
        global UPDATE_SYNC_IN_PROGRESS
        try:
            _sync_plugin_from_github()            
            try:
                plugin_event.reply("同步完成，已更新到本地当前插件目录，正在重载插件。")
                Proc.set_restart()
            except Exception:
                pass
        except Exception as exc:
            try:
                plugin_event.reply(f"同步失败：{exc}")
            except Exception:
                pass
        finally:
            UPDATE_SYNC_IN_PROGRESS = False

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    try:
        plugin_event.reply("正在同步最新版本，请稍候...")
    except Exception:
        pass
    return True


def start_checktime_thread():
    thread = threading.Thread(target=checktime, daemon=True)
    thread.start()


class Event(object):
    def init_after(plugin_event, Proc):
        with amourlock:
            qrcode_default_path = "./data/images/恋综备用群/二维码/默认池"
            if not os.path.exists(qrcode_default_path):
                os.makedirs(qrcode_default_path, exist_ok=True)
            groupnum_path = "./data/images/恋综备用群/群号"
            if not os.path.exists(groupnum_path):
                os.makedirs(groupnum_path, exist_ok=True)
        dispatch_embedded_module_event("init_after", plugin_event, Proc)

    def group_message(plugin_event, Proc):
        global plugin_events_cache, schedule_started
        plugin_events_cache.append(plugin_event)
        if len(plugin_events_cache) > 5:
            plugin_events_cache.pop(0)
        if not schedule_started:
            start_checktime_thread()
            schedule_started = True
        if dispatch_game_event(plugin_event, Proc, is_group=True):
            return
        dispatch_embedded_module_event("group_message", plugin_event, Proc)
        reply(plugin_event, Proc, is_group=True)

    def group_message_recall(plugin_event, Proc):
        from AmourGame import engagement as engagement_module

        engagement_module.handle_recalled_message(plugin_event)

    def private_message(plugin_event, Proc):
        dispatch_game_event(plugin_event, Proc, is_group=False)
        dispatch_embedded_module_event("private_message", plugin_event, Proc)

    def poke(plugin_event, Proc):
        dispatch_embedded_module_event("poke", plugin_event, Proc)

    def save(plugin_event, Proc):
        dispatch_embedded_module_event("save", plugin_event, Proc)

    def group_member_increase(plugin_event, Proc):
        auto_rename_group(plugin_event, Proc)

    def group_member_decrease(plugin_event, Proc):
        auto_release_group(plugin_event, Proc)

    def group_add_request(plugin_event, Proc):
        # 本部分代码为邀请码机制，即嘉宾申请入群必须在申请消息中填入“复盘编号”
        # 如需启用本功能，请在相关的消息文本中增加说明
        # 并调整本段代码的缩进
        #   uid=str(plugin_event.data.user_id)
        #   code=re.search(r"\d{8}",plugin_event.data.comment)
        #   if code:
        #       appoint =  getData("appoint.json")
        #       if code not in appoint:
        #          return
        #       if uid != appoint[code].get("inviter") and uid not in appoint[code].get("invitee"):
        #          return
        #       plugin_event.set_group_add_request(plugin_event.data.flag, "add", True, "")
        plugin_event.set_group_add_request(plugin_event.data.flag, "add", True, "")


EMBEDDED_MODULE_HANDLERS = (
    ("ArchiveV2_1_0", {"group_message": "reply", "private_message": "reply"}),
    (
        "reconnoiter",
        {
            "init_after": "init_after",
            "group_message": "reply",
            "private_message": "reply",
        },
    ),
    ("searchpack", {"group_message": "reply", "private_message": "reply"}),
)


def dispatch_embedded_module_event(event_name, plugin_event, Proc):
    for module_name, handlers in EMBEDDED_MODULE_HANDLERS:
        handler_name = handlers.get(event_name)
        if not handler_name:
            continue
        try:
            module = __import__(f"AmourGame.{module_name}", fromlist=[handler_name])
        except ModuleNotFoundError as e:
            if e.name == f"AmourGame.{module_name}":
                continue
            raise
        try:
            event_handler = getattr(module, handler_name, None)
            if event_handler:
                event_handler(plugin_event, Proc)
        except Exception as e:
            try:
                plugin_event.reply(f"{module_name}功能错误：{e}")
            except Exception:
                pass


GAME_COMMAND_PREFIXES = (
    "游戏插件手册",
    "出场顺序 ",
    "开始出场 ",
    "结束出场",
    "晚间游戏 ",
    "开启游戏",
    "结束游戏",
    "设置自动跳过",
    "自动跳过",
    "关闭自动跳过",
    "查看座位",
    "坐",
    "不坐",
    "计分",
    "计分榜",
    "计分项",
    "清空计分",
    "添加计分项 ",
    "删除计分项 ",
    "直接开始游戏",
    "开始数字炸弹",
    "开始女巫毒药",
    "放毒",
    "偏执狂",
    "你有我没有",
    "两真一假",
    "两假一真",
    "国王游戏",
    "你画我猜",
    "查看顺序",
    "跳过",
    "下一轮",
    "开启反折",
    "关闭反折",
    "开启出题人加分",
    "关闭出题人加分",
)


def should_dispatch_game(plugin_event, is_group):
    message = str(getattr(plugin_event.data, "message", "")).strip()
    if not message:
        return False
    try:
        from AmourGame.game import main as game_main
        data = game_main.get_daily_game_data()
    except Exception:
        data = {}
    if not is_group:
        return bool(data)
    groupid = str(plugin_event.data.group_id)
    uid = str(plugin_event.data.user_id)
    if groupid in data:
        return True
    try:
        from AmourGame.game import main as game_main
        if game_main.is_appearance_group(data, groupid):
            return True
        if game_main.is_player_submit_group(data, groupid, uid):
            return True
    except Exception:
        pass
    return message.startswith(GAME_COMMAND_PREFIXES)


def dispatch_game_event(plugin_event, Proc, is_group):
    message = str(getattr(plugin_event.data, "message", "")).strip()
    if _is_update_command(message):
        return _run_update_sync(plugin_event, Proc)
    if not should_dispatch_game(plugin_event, is_group):
        return False
    try:
        from AmourGame.game import main as game_main
        if is_group:
            handled = game_main.reply(plugin_event, Proc)
            if handled is not True:
                return False
        else:
            game_main.pri_reply(plugin_event, Proc)
        return True
    except Exception as e:
        try:
            import traceback
            plugin_event.reply(f"游戏功能错误：{e}\n{traceback.format_exc()}")
        except Exception:
            pass
        return True
    
def auto_rename_group(plugin_event, Proc):
    group_id = str(plugin_event.data.group_id)
    new_member_id = str(plugin_event.data.user_id)
    if new_member_id == str(plugin_event.bot_info.id):
        return
    appoint = getData("engagement", "appoint.json")
    target_code = None
    for code, info in appoint.items():
        if "group" in info and str(info["group"]) == group_id:
            target_code = code
            break
    if not target_code:
        return
    appointment = appoint[target_code]
    inviter = appointment.get("inviter")
    invitee = appointment.get("invitee", [])
    if isinstance(inviter, list):
        is_inviter = new_member_id in inviter
    else:
        is_inviter = str(inviter) == new_member_id
    is_invitee = new_member_id in [str(i) for i in invitee]
    if not (is_inviter or is_invitee):
        return
    appoint = getData("engagement", "appoint.json")
    if target_code not in appoint:
        return
    appointment = appoint[target_code]
    group_id = str(plugin_event.data.group_id)
    if "group" not in appointment or str(appointment["group"]) != group_id:
        return
    inviter = appointment.get("inviter")
    invitee = appointment.get("invitee", [])
    playname = appointment.get("playname")
    playtype = appointment.get("playtype")
    playtime = appointment.get("playtime")
    playplace = appointment.get("playplace")
    privategroup = getData("groupcollection", "privategroup.json")
    if playtype == "官约":
        groupname = f"{playname} {playtype} {playtime.split(' ')[0]}"
        if invitee:
            first_invitee = True
            for i in invitee:
                user_info = privategroup.get(playname, {}).get(i, {})
                display_name = (
                    user_info.get("嘉宾姓名") or user_info.get("NPC姓名") or f"用户{i}"
                )
                if first_invitee:
                    groupname += f" {display_name}"
                    first_invitee = False
                else:
                    groupname += f"x{display_name}"
    elif inviter == "官方":
        groupname = (
            f"{playname} {playtype} {playtime.split(' ')[0]} 官方"
        )
        if invitee:
            for i in invitee:
                user_info = privategroup.get(playname, {}).get(i, {})
                display_name = (
                    user_info.get("嘉宾姓名")
                    or user_info.get("NPC姓名")
                    or f"用户{i}"
                )
                groupname += f"x{display_name}"
    else:
        inviter_info = privategroup.get(playname, {}).get(inviter, {})
        inviter_display_name = (
            inviter_info.get("嘉宾姓名")
            or inviter_info.get("NPC姓名")
            or f"用户{inviter}"
        )
        groupname = (
            f"{playname} {playtype} {playtime.split(' ')[0]} {inviter_display_name}"
        )
        if invitee:
            for i in invitee:
                user_info = privategroup.get(playname, {}).get(i, {})
                display_name = (
                    user_info.get("嘉宾姓名") or user_info.get("NPC姓名") or f"用户{i}"
                )
                groupname += f"x{display_name}"
    groupname += " " + playtime.split(" ")[1]
    plugin_event.set_group_name(group_id, groupname)
    invitee_names = []
    for i in invitee:
        user_info = privategroup.get(playname, {}).get(i, {})
        display_name = (
            user_info.get("嘉宾姓名") or user_info.get("NPC姓名") or f"用户{i}"
        )
        invitee_names.append(display_name)
    invitee_str = "，".join(invitee_names)
    if playtype == "官约" or inviter == "官方":
        inviter_display = "官方"
    else:
        inviter_info = privategroup.get(playname, {}).get(inviter, {})
        inviter_display = (
            inviter_info.get("嘉宾姓名")
            or inviter_info.get("NPC姓名")
            or f"用户{inviter}"
        )
    plugin_event.reply(
        f"检测到参与者，群名已更新！\n\n<{playname}·{playtype}>\n"
        f"邀请者：{inviter_display}\n"
        f"受邀者：{invitee_str}\n"
        f"时间：{playtime}\n"
        f"地点：{playplace}\n"
        f"编号：{target_code}\n\n"
        f"①如为开错的小群，请不要直接退群，联系管理在后台删除时间线，再退。\n\n"
        f"②结戏可发送「@骰子 复盘」，也可合并转发戏录至本群，引用该消息并附文「@骰子 复盘」\n\n"
        f"③自助撤戏指令：引用戏文并附文「@骰子 撤戏」\n\n"
        f"④复盘不合并本条。\n\n⑤骰子自动监控所有内容收入戏录，下皮沟通请带（）❗️"
    )


def get_group_member_list(plugin_event, group_id):
    try:
        bot_port = plugin_event.bot_info.post_info.port
        bot_token = plugin_event.bot_info.post_info.access_token
        url = f"http://127.0.0.1:{bot_port}/get_group_member_list"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bot_token}",
        }
        payload = json.dumps({"group_id": int(group_id)})
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        result = response.json()
        if result.get("retcode") == 0 and "data" in result:
            member_ids = [str(member["user_id"]) for member in result["data"]]
            return member_ids
        else:
            return None
    except Exception as e:
        pass


def get_group_member_detail_list(plugin_event, group_id):
    try:
        bot_port = plugin_event.bot_info.post_info.port
        bot_token = plugin_event.bot_info.post_info.access_token
        url = f"http://127.0.0.1:{bot_port}/get_group_member_list"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bot_token}",
        }
        payload = json.dumps({"group_id": int(group_id)})
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        result = response.json()
        if result.get("retcode") == 0 and "data" in result:
            return result["data"]
        return None
    except Exception:
        return None


def kick_group_member(plugin_event, group_id, user_id):
    try:
        bot_port = plugin_event.bot_info.post_info.port
        bot_token = plugin_event.bot_info.post_info.access_token
        url = f"http://127.0.0.1:{bot_port}/set_group_kick"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bot_token}",
        }
        payload = json.dumps(
            {
                "group_id": int(group_id),
                "user_id": int(user_id),
                "reject_add_request": False,
            }
        )
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        result = response.json()
        return result.get("retcode") == 0, result.get("message") or result.get("msg", "")
    except Exception as e:
        return False, str(e)


def _get_pool_group_file(playname, use_default=False):
    groupnum_base_path = "./data/images/恋综备用群/群号"
    playname_file = os.path.join(groupnum_base_path, f"{playname}.json")
    default_file = os.path.join(groupnum_base_path, "默认池.json")
    if not use_default and os.path.exists(playname_file):
        return playname_file
    if os.path.exists(default_file):
        return default_file
    return None


def _get_pool_qrcode_path(playname, use_default=False):
    qrcode_base_path = "./data/images/恋综备用群/二维码"
    playname_path = os.path.join(qrcode_base_path, playname)
    default_path = os.path.join(qrcode_base_path, "默认池")
    if not use_default and os.path.exists(playname_path) and os.path.isdir(playname_path):
        return playname_path
    if os.path.exists(default_path) and os.path.isdir(default_path):
        return default_path
    return None


def _unused_pool_groups(playname, play_method):
    groups = []
    if play_method == "二维码":
        group_path = _get_pool_qrcode_path(playname)
        if not group_path:
            return groups
        mapping_file = os.path.join(group_path, "二维码与群号对应组.json")
        if not os.path.exists(mapping_file):
            return groups
        try:
            with open(mapping_file, "r", encoding="utf-8") as f:
                mapping_data = json.load(f)
        except Exception:
            return groups
        for filename in os.listdir(group_path):
            file_path = os.path.join(group_path, filename)
            if not os.path.isfile(file_path):
                continue
            if filename.lower().endswith(".json") or filename.startswith("已占用_"):
                continue
            group_id = mapping_data.get(filename)
            if not group_id:
                name_without_ext = os.path.splitext(filename)[0]
                group_id = mapping_data.get(name_without_ext)
            if group_id:
                groups.append({"group_id": str(group_id), "source": filename})
    elif play_method == "群号":
        group_file = _get_pool_group_file(playname)
        if not group_file:
            return groups
        try:
            with open(group_file, "r", encoding="utf-8") as f:
                group_data = json.load(f)
        except Exception:
            return groups
        for group_id, group_info in group_data.items():
            if isinstance(group_info, dict) and group_info.get("使用情况") is False:
                groups.append({"group_id": str(group_id), "source": os.path.basename(group_file)})
    return groups


def auto_release_group(plugin_event, Proc):
    group_id = str(plugin_event.data.group_id)
    left_member_id = str(plugin_event.data.user_id)
    if left_member_id == str(plugin_event.bot_info.id):
        return
    appoint = getData("engagement", "appoint.json")
    target_code = None
    target_appointment = None
    for code, info in appoint.items():
        group_value = str(info.get("group", ""))
        if group_value.isdigit() and group_value == group_id:
            target_code = code
            target_appointment = info
            break
    if not target_code or not target_appointment:
        return
    inviter = target_appointment.get("inviter")
    invitee = target_appointment.get("invitee", [])
    is_participant = False
    if isinstance(inviter, list):
        if left_member_id in inviter:
            is_participant = True
    elif str(inviter) == left_member_id:
        is_participant = True
    if not is_participant and left_member_id in [str(i) for i in invitee]:
        is_participant = True
    if not is_participant:
        return
    current_members = get_group_member_list(plugin_event, group_id)
    if current_members is None:
        return
    if left_member_id in current_members:
        current_members.remove(left_member_id)
    remaining_participants = []
    if isinstance(inviter, list):
        for inv in inviter:
            if str(inv) in current_members:
                remaining_participants.append(str(inv))
    elif inviter != "官方" and str(inviter) in current_members:
        remaining_participants.append(str(inviter))
    for invitee_id in invitee:
        if str(invitee_id) in current_members:
            remaining_participants.append(str(invitee_id))
    if remaining_participants:
        return
    release_group_with_code(plugin_event, target_code, target_appointment)


def cleanup_monitor_session(group_id, code=None):
    """释放小群时清理实时监听状态，保留历史戏录和弧长。"""
    states = getData("engagement", "msg_appoint.json")
    changed = states.pop(str(group_id), None) is not None
    if code is not None:
        for state_group, state in list(states.items()):
            if isinstance(state, dict) and str(state.get("code", "")) == str(code):
                del states[state_group]
                changed = True
    if changed:
        setData("engagement", "msg_appoint.json", states)


def _appointment_participant_ids(appointment):
    participant_ids = []
    inviter = appointment.get("inviter")
    invitee = appointment.get("invitee", [])
    if isinstance(inviter, list):
        for item in inviter:
            item = str(item)
            if item.isdigit() and item not in participant_ids:
                participant_ids.append(item)
    elif inviter != "官方":
        inviter = str(inviter)
        if inviter.isdigit() and inviter not in participant_ids:
            participant_ids.append(inviter)
    for item in invitee:
        item = str(item)
        if item.isdigit() and item not in participant_ids:
            participant_ids.append(item)
    return participant_ids


def release_group_with_code(plugin_event, code, appointment, group_id=None, reply=True):
    group_id = str(group_id or plugin_event.data.group_id)
    if str(appointment.get("group", "")) != group_id:
        return False
    playname = appointment.get("playname")
    playtype = appointment.get("playtype")
    playtime = appointment.get("playtime")
    playplace = appointment.get("playplace")
    inviter = appointment.get("inviter")
    invitee = appointment.get("invitee", [])
    register = getData("groupcollection", "register.json")
    play_method = register.get(playname, {}).get("play_method", "二维码")
    new_group_name = None
    if play_method == "二维码":
        playname_path = f"./data/images/恋综备用群/二维码/{playname}"
        default_path = "./data/images/恋综备用群/二维码/默认池"
        if os.path.exists(playname_path) and os.path.isdir(playname_path):
            group_path = playname_path
        else:
            group_path = default_path
        mapping_file = os.path.join(group_path, "二维码与群号对应组.json")
        if not os.path.exists(mapping_file):
            return False
        try:
            with open(mapping_file, "r", encoding="utf-8") as f:
                mapping_data = json.load(f)
            qr_filename = None
            for qr_name, qr_group_id in mapping_data.items():
                if str(qr_group_id) == group_id:
                    qr_filename = qr_name
                    break
            if not qr_filename:
                if reply:
                    plugin_event.reply(f"未找到群号{group_id}对应的二维码文件")
                return False
            occupied_files = []
            for filename in os.listdir(group_path):
                if filename.startswith("已占用_") and qr_filename in filename:
                    occupied_files.append(filename)
            if not occupied_files:
                if reply:
                    plugin_event.reply(f"未找到已占用的二维码文件: {qr_filename}")
                return False
            occupied_file = occupied_files[0]
            original_filename = occupied_file.replace("已占用_", "", 1)
            old_file_path = os.path.join(group_path, occupied_file)
            new_file_path = os.path.join(group_path, original_filename)
            try:
                if os.path.exists(old_file_path):
                    os.rename(old_file_path, new_file_path)
            except OSError as e:
                if reply:
                    plugin_event.reply(f"群二维码释放失败: {e}")
            match = re.match(r"(.+)\.\w+$", original_filename)
            if match:
                new_group_name = match.group(1)
            else:
                new_group_name = original_filename
        except Exception as e:
            if reply:
                plugin_event.reply(f"释放二维码文件时出错，请联系管理。")
            return False
    elif play_method == "群号":
        with amourlock:
            playname_file = f"./data/images/恋综备用群/群号/{playname}.json"
            default_file = "./data/images/恋综备用群/群号/默认池.json"
            group_file = None
            if os.path.exists(playname_file):
                group_file = playname_file
            elif os.path.exists(default_file):
                group_file = default_file
            if not group_file:
                if reply:
                    plugin_event.reply(f"群号配置文件不存在: {playname}")
                return False
            try:
                with open(group_file, "r", encoding="utf-8") as f:
                    group_data = json.load(f)
                if group_id in group_data:
                    group_data[group_id]["使用情况"] = False
                    with open(group_file, "w", encoding="utf-8") as f:
                        json.dump(group_data, f, ensure_ascii=False, indent=2)
                else:
                    if reply:
                        plugin_event.reply(f"群号{group_id}不在配置文件中！")
            except Exception as e:
                if reply:
                    plugin_event.reply(f"处理群号文件时出错: {e}")
                return False
        new_group_name = f"{playname}备用"
    if new_group_name:
        plugin_event.set_group_name(group_id, new_group_name)
    privategroup = getData("groupcollection", "privategroup.json")
    base_path = f"./plugin/data/amourgame/恋综复盘/{playname}/"
    with amourlock:
        if not os.path.exists(base_path):
            os.makedirs(base_path)
        tech_file = os.path.join(base_path, "「技术支持」探丸借客@临皋闲人.txt")
        if not os.path.exists(tech_file):
            tech_content = (
                "_      /)---(\ \n"
                "\ \   (/ . . \)\n"
                " \ \__)-\(*)/\n"
                "  \_       (_\n"
                "  (___/-(____)\n"
                "\n"
                "「技术支持」探丸借客@临皋闲人\n"
                "\n"
                "OlivaDice By lunzhiPenxil"
            )
            with open(tech_file, "w", encoding="utf-8") as f:
                f.write(tech_content)
    inviter_name = ""
    if inviter == "官方":
        inviter_name = "官方"
    elif inviter in privategroup.get(playname, {}):
        user_data = privategroup[playname][inviter]
        inviter_name = user_data.get("嘉宾姓名", user_data.get("NPC姓名", inviter))
    else:
        inviter_name = str(inviter)
    invitee_names = []
    for i in invitee:
        if i in privategroup.get(playname, {}):
            user_data = privategroup[playname][i]
            name = user_data.get("嘉宾姓名", user_data.get("NPC姓名", i))
            invitee_names.append(name)
    resee_name = f"{playname} {playtime} {playtype} {inviter_name}"
    for name in invitee_names:
        resee_name += f"x{name}"
    resee_name = re.sub(r'[<>:"/\\|?*]', "_", resee_name)
    invitee_text = "，".join(invitee_names)
    resee_text = f"<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{invitee_text}\n时间：{playtime}\n地点：{playplace}"
    playlog = getData("engagement", f"{code}.json")
    if playlog:
        for i in playlog:
            resee_text += f"\n\n{i}"
        with amourlock:
            Dnum = re.match(r"D\d+", playtime).group()
            log_path = f"./plugin/data/amourgame/恋综复盘/{playname}/{Dnum}{playtype}"
            if not os.path.exists(log_path):
                os.makedirs(log_path)
            with open(f"{log_path}/{resee_name}.txt", "w", encoding="utf-8") as f:
                f.write(resee_text)
    try:
        os.remove(f"./plugin/data/amourgame/engagement/{code}.json")
        os.remove(f"./plugin/data/amourgame/engagement/{code}.json.bak")
    except:
        pass
    appoint = getData("engagement", "appoint.json")
    if code in appoint:
        del appoint[code]
        setData("engagement", "appoint.json", appoint)
    cleanup_monitor_session(group_id, code)
    if reply:
        plugin_event.reply(f"如有复盘，文件已生成在后台。\n小群{code}已释放！")
    return True


def vtor(playname):
    try:
        register = getData("groupcollection", "register.json")
        if playname not in register:
            return None
        reg_data = register[playname]
        start_date_str = reg_data["start_date"]
        end_date_str = reg_data.get("end_date", "")
        start_date = datetime.strptime(start_date_str, "%Y%m%d")
        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%Y%m%d")
            original_total_days = (end_date - start_date).days + 1
        else:
            original_total_days = 1
        supplements = reg_data.get("supplements", {})
        real_to_virtual = {}
        current_date = start_date
        for virtual_day in range(original_total_days):
            supplement_count = supplements.get(str(virtual_day), 0)
            days_for_virtual = supplement_count + 1
            for i in range(days_for_virtual):
                date_6 = current_date.strftime("%y%m%d")
                real_to_virtual[date_6] = virtual_day
                current_date += timedelta(days=1)
        return real_to_virtual
    except Exception as e:
        return None


def reply(plugin_event, Proc, is_group):
    message = plugin_event.data.message
    groupid = str(plugin_event.data.group_id)
    uid = str(plugin_event.data.user_id)
    platform = plugin_event.platform["platform"]
    tmp_botHash = plugin_event.bot_info.hash
    masterlist = getMaster(tmp_botHash, platform)
    bot_id = str(plugin_event.bot_info.id)
    sender = plugin_event.data.sender["name"]
    bot_port = plugin_event.bot_info.post_info.port
    bot_token = plugin_event.bot_info.post_info.access_token
    from AmourGame import engagement as engagement_module

    if engagement_module.handle_monitor_command(
        plugin_event,
        message,
        uid,
        groupid,
        masterlist,
        bot_port,
        bot_token,
    ):
        return
    engagement_module.monitor_appointment_message(
        plugin_event, message, uid, groupid
    )
    collection_format_match = re.fullmatch(
        r"(.+?)(?:\s*\[OP:at,id=(\d+)\])\s*",
        str(message).strip(),
    )
    if collection_format_match:
        requested_collection_item = collection_format_match.group(1).strip()
        at_id = collection_format_match.group(2)
        privategroup = getData("groupcollection", "privategroup.json")
        register = getData("groupcollection", "register.json")
        matched_playnames = []
        matched_guest_names = []
        if privategroup:
            for playname, guests in privategroup.items():
                for uid_str, guest_info in guests.items():
                    if str(uid) != uid_str:
                        continue
                    personal_group = guest_info.get("个人群号")
                    npc_group = guest_info.get("NPC群号")
                    if str(groupid) in (str(personal_group), str(npc_group)):
                        guest_name = (
                            guest_info.get("嘉宾姓名")
                            or guest_info.get("NPC姓名")
                            or "嘉宾姓名"
                        )
                        matched_playnames.append(playname)
                        matched_guest_names.append(guest_name)
        if not matched_playnames:
            for playname, reg_data in register.items():
                if str(reg_data.get("manage_group")) == str(groupid):
                    matched_playnames.append(playname)
                    matched_guest_names.append("嘉宾姓名")
        if (not at_id or at_id == str(plugin_event.bot_info.id)) and (
            at_id or matched_playnames
        ):
            replace_playname = matched_playnames[-1] if matched_playnames else "恋综名"
            replace_guest_name = (
                matched_guest_names[-1] if matched_guest_names else "嘉宾姓名"
            )
            collection_items = _get_collection_items(register, replace_playname)
            if requested_collection_item in collection_items:
                plugin_event.reply(
                    _collection_format_text(
                        replace_playname,
                        replace_guest_name,
                        [requested_collection_item],
                    )
                )
                return
    format_match = re.fullmatch(
        r"(心动信|小纸条|礼物|短信|送图|心愿|点歌|关系线|留言板|公知|私约|电话|前置电话|微信|官约)"
        r"(?:\s*\[OP:at,id=(\d+)\])?\s*",
        str(message).strip(),
    )
    if format_match:
        match = format_match
        if match:
            format_type = match.group(1)
            at_id = match.group(2)
            from datetime import datetime

            today_date = datetime.now().strftime("%y%m%d")
            privategroup = getData("groupcollection", "privategroup.json")
            matched_playnames = []
            matched_guest_names = []
            if privategroup:
                for playname, guests in privategroup.items():
                    for uid_str, guest_info in guests.items():
                        if str(uid) != uid_str:
                            continue
                        personal_group = guest_info.get("个人群号")
                        npc_group = guest_info.get("NPC群号")
                        if str(groupid) in (str(personal_group), str(npc_group)):
                            guest_name = (
                                guest_info.get("嘉宾姓名")
                                or guest_info.get("NPC姓名")
                                or "嘉宾姓名"
                            )
                            matched_playnames.append(playname)
                            matched_guest_names.append(guest_name)
            if at_id:
                if at_id != str(plugin_event.bot_info.id):
                    return
            elif not matched_playnames:
                return
            if matched_playnames:
                replace_playname = matched_playnames[-1]
                replace_guest_name = matched_guest_names[-1]
                replace_date = today_date
                replace_sender = replace_guest_name
                replace_receiver = ""
            else:
                replace_playname = "恋综名"
                replace_date = "日期"
                replace_sender = "张三"
                replace_receiver = "李四"
                replace_guest_name = "嘉宾姓名"
            if format_type == "心动信":
                msg = (
                    f"{replace_playname} 心动信\n"
                    f"{replace_sender} 致 {replace_receiver}\n"
                    f"内容：\n署名："
                )
            elif format_type == "礼物":
                msg = (
                    f"{replace_playname} 礼物\n"
                    f"{replace_sender} 致 {replace_receiver}\n"
                    f"内容：\n署名："
                )
            elif format_type == "小纸条":
                msg = (
                    f"{replace_playname} 小纸条\n"
                    f"{replace_sender} 致 {replace_receiver}\n"
                    f"内容：\n署名："
                )
            elif format_type == "短信":
                msg = (
                    f"{replace_playname} 短信\n"
                    f"{replace_sender} 致 {replace_receiver}\n"
                    f"内容：\n署名："
                )
            elif format_type == "送图":
                msg = (
                    f"{replace_playname} 送图\n"
                    f"{replace_sender} 致 {replace_receiver}\n"
                    f"内容：\n署名："
                )
            elif format_type == "心愿":
                msg = (
                    f"<{replace_playname}·心愿>\n"
                    f"内容：\n署名：（可为空）\n"
                    f"时间：D0 07:00-08:00\n"
                    f"地点："
                )
            elif format_type == "点歌":
                msg = (
                    f"<{replace_playname}·点歌>\n"
                    f"歌曲：\n留言：（可为空）\n署名：（可为空）\n\n【说明】\n点歌方式1：\n自动搜索，默认发送结果列表的第一首歌。\n“歌曲：”栏可通过“歌名 歌手”的格式控制结果，用空格隔开，如果点歌失败，把歌手删了只写歌名。\n\n点歌方式2：\n引用音乐卡片消息，附文表格。\n\n点歌只发表格，把后面这些删了。"
                )
            elif format_type == "关系线":
                msg = (
                    f"<{replace_playname}·关系线>\n"
                    f"发送者：{replace_guest_name}\n"
                    f"接收者：{replace_guest_name}\n"
                    f"内容："
                )
            elif format_type == "留言板":
                msg = (
                    f"<{replace_playname}·留言板bot>\n"
                    f"留言人：（可为空）\n"
                    f"接收人：（可为空）\n"
                    f"内容："
                )
            elif format_type == "公知":
                msg = (
                    f"<{replace_playname}·公知>\n"
                    f"姓名：{replace_guest_name}\n"
                    f"内容：\n\n【说明】\n所有嘉宾上传完毕后，发送「{replace_playname}公知@骰子」可查看公知合集。\n公知可带1张图，附在末尾。"
                )
            elif format_type == "私约":
                msg = (
                    f"<{replace_playname}·私约>\n"
                    f"邀请者：{replace_guest_name}\n"
                    f"受邀者：\n"
                    f"时间：D0 07:00-23:59\n"
                    f"地点："
                )
            elif format_type == "电话":
                msg = (
                    f"<{replace_playname}·电话>\n"
                    f"邀请者：{replace_guest_name}\n"
                    f"受邀者：\n"
                    f"时间：D0 07:00-23:59\n"
                    f"地点："
                )
            elif format_type == "前置电话":
                msg = (
                    f"<{replace_playname}·前置电话>\n"
                    f"邀请者：官方\n"
                    f"受邀者：{replace_guest_name}，{replace_guest_name}\n"
                    f"时间：D0 07:00-23:59\n"
                    f"地点："
                )
            elif format_type == "微信":
                msg = (
                    f"<{replace_playname}·微信>\n"
                    f"邀请者：{replace_guest_name}\n"
                    f"受邀者：\n"
                    f"时间：D0 07:00-23:59\n"
                    f"地点：\n\n微信不检测时间冲突。"
                )
            elif format_type == "官约":
                msg = (
                    f"<{replace_playname}·官约>\n"
                    f"邀请者：官方\n"
                    f"受邀者：{replace_guest_name}，{replace_guest_name}\n"
                    f"时间：D0 07:00-23:59\n"
                    f"地点："
                )
            is_letter_query = (
                format_type == "心动信"
                and at_id is not None
                and bool(matched_playnames)
            )
            if not is_letter_query:
                plugin_event.reply(msg)
            if format_type == "心动信":
                if not is_letter_query:
                    return
                letters = getData("sendmessage", "letters.json")
                today = datetime.now().strftime("%y%m%d")
                current_guest_name = None
                if matched_playnames:
                    for playname, guests in privategroup.items():
                        for uid_str, guest_info in guests.items():
                            if str(uid) != uid_str:
                                continue
                            personal_group = guest_info.get("个人群号")
                            npc_group = guest_info.get("NPC群号")
                            if str(groupid) in (str(personal_group), str(npc_group)):
                                if playname == replace_playname:
                                    current_guest_name = guest_info.get(
                                        "嘉宾姓名"
                                    ) or guest_info.get("NPC姓名")
                                    break
                        if current_guest_name:
                            break
                player_letters = []
                for key, content in letters.items():
                    datalist = key.split("/////")
                    if len(datalist) < 5:
                        continue
                    key_playname = datalist[0]
                    key_date = datalist[1]
                    sender = datalist[2]
                    recver = datalist[3]
                    signature = datalist[4]
                    if (
                        key_playname == replace_playname
                        and key_date == today
                        and str(sender) == str(uid)
                    ):
                        recver_info = {}
                        recver_name = recver
                        if (
                            replace_playname in privategroup
                            and recver in privategroup[replace_playname]
                        ):
                            recver_info = privategroup[replace_playname][recver]
                            recver_name = (
                                recver_info.get("嘉宾姓名")
                                or recver_info.get("NPC姓名")
                                or recver
                            )
                        segments = []
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"{replace_playname} 心动信\n"},
                            }
                        )
                        segments.append(
                            {
                                "type": "text",
                                "data": {"text": f"致 {recver_name}\n"},
                            }
                        )
                        segments.append(
                            {"type": "text", "data": {"text": f"内容：{content}\n"}}
                        )
                        if "[CQ:image" in signature or "[OP:image" in signature:
                            segments.append(
                                {"type": "text", "data": {"text": "署名："}}
                            )
                            text_parts = re.split(
                                r"(\[(?:CQ|OP):image[^\]]+\])", signature
                            )
                            for part in text_parts:
                                if part.startswith("[CQ:image") or part.startswith(
                                    "[OP:image"
                                ):
                                    image_segment = _image_segment_from_text(part)
                                    if image_segment:
                                        segments.append(image_segment)
                                elif part:
                                    segments.append(
                                        {"type": "text", "data": {"text": part}}
                                    )
                        else:
                            segments.append(
                                {"type": "text", "data": {"text": f"署名：{signature}"}}
                            )
                        player_letters.append(
                            {
                                "recver": recver,
                                "recver_name": recver_name,
                                "segments": segments,
                                "content": content,
                                "signature": signature,
                            }
                        )
                if player_letters:
                    nodes_data = []
                    title_text = f"{current_guest_name or replace_sender}今日已发送{len(player_letters)}封信件"
                    nodes_data.append({"bot_id": bot_id, "content_text": title_text})
                    for letter in player_letters:
                        nodes_data.append(
                            {"bot_id": bot_id, "content_list": letter["segments"]}
                        )
                    result = send_forward_message(
                        bot_port, bot_token, groupid, nodes_data
                    )
                    if result.get("retcode") != 0:
                        for letter in player_letters:
                            message_text = (
                                f"{replace_playname} 心动信\n"
                                f"致 {letter['recver_name']}\n"
                                f"内容：{letter['content']}\n"
                                f"署名：{letter['signature']}"
                            )
                            plugin_event.reply(message_text)
                            time.sleep(0.5)
                else:
                    plugin_event.reply("你今天还没有发送心动信。")
                return

            if format_type == "关系线":
                relation_file = f"{replace_playname}.json"
                try:
                    relation_data = getData("relation", relation_file)
                except:
                    return
                current_guest_name = None
                if matched_playnames:
                    for playname, guests in privategroup.items():
                        for uid_str, guest_info in guests.items():
                            if str(uid) != uid_str:
                                continue
                            personal_group = guest_info.get("个人群号")
                            npc_group = guest_info.get("NPC群号")
                            if str(groupid) in (str(personal_group), str(npc_group)):
                                if playname == replace_playname:
                                    current_guest_name = guest_info.get(
                                        "嘉宾姓名"
                                    ) or guest_info.get("NPC姓名")
                                    break
                        if current_guest_name:
                            break
                else:
                    return
                if not current_guest_name:
                    return
                user_relations = {}
                for relation_key, relation_contents in relation_data.items():
                    if "→" in relation_key:
                        sender, receiver = relation_key.split("→")
                        sender = sender.strip()
                        receiver = receiver.strip()
                        if current_guest_name in [sender, receiver]:
                            other_party = (
                                receiver if current_guest_name == sender else sender
                            )
                            relation_details = []
                            content_keys = [
                                k for k in relation_contents.keys() if k.isdigit()
                            ]
                            content_keys.sort(key=int)
                            for key in content_keys:
                                relation_details.append(relation_contents[key])
                            user_relations[relation_key] = {
                                "other_party": other_party,
                                "details": relation_details,
                                "direction": f"{sender}→{receiver}",
                            }
                if not user_relations:
                    return
                for relation_key, info in user_relations.items():
                    other_party = info["other_party"]
                    relation_details = info["details"]
                    direction = info["direction"]
                    nodes_data = []
                    if relation_details:
                        first_content = f"{direction}\n\n{relation_details[0]}"
                        nodes_data.append(
                            {"bot_id": bot_id, "content_text": first_content}
                        )
                        for i in range(1, len(relation_details)):
                            detail = relation_details[i]
                            nodes_data.append(
                                {"bot_id": bot_id, "content_text": f"{detail}\n"}
                            )
                    if not nodes_data:
                        continue
                    result = send_forward_message(
                        bot_port, bot_token, groupid, nodes_data
                    )
                    if result.get("retcode") != 0:
                        plugin_event.reply(f"发送关系线消息失败，请联系骰主。")
                        continue
                    time.sleep(0.5)
                return
    elif re.match(
        r"恋综\s*\[OP:at,id=(\d+)\]",
        message,
    ):
        match = re.match(r"恋综\s*\[OP:at,id=(\d+)\]", message)
        if match:
            at_id = match.group(1)
            if at_id != str(plugin_event.bot_info.id):
                return
            if uid not in masterlist:
                plugin_event.reply("如需注册恋综请联系骰主开放权限。")
                return
            try:
                register = getData("groupcollection", "register.json")
                matching = None
                for playname, data in register.items():
                    if data.get("manage_group") == groupid:
                        matching = (playname, data)
                if matching:
                    playname, data = matching
                    start_date_str = data["start_date"]
                    original_end_date_str = data["end_date"]
                    from datetime import datetime, timedelta

                    start_date = datetime.strptime(start_date_str, "%Y%m%d")
                    original_end_date = datetime.strptime(
                        original_end_date_str, "%Y%m%d"
                    )
                    original_days = (original_end_date - start_date).days + 1
                    supplement_days = 0
                    if "supplements" in data:
                        for supplement_count in data["supplements"].values():
                            supplement_days += supplement_count
                    if supplement_days > 0:
                        expected_end_date = original_end_date + timedelta(
                            days=supplement_days
                        )
                        end_date_str = expected_end_date.strftime("%Y%m%d")
                        if data.get("current_end_date") != end_date_str:
                            data["current_end_date"] = end_date_str
                            setData("groupcollection", "register.json", register)
                    else:
                        end_date_str = original_end_date_str
                        if "current_end_date" in data:
                            del data["current_end_date"]
                            setData("groupcollection", "register.json", register)
                    end_date = datetime.strptime(end_date_str, "%Y%m%d")
                    today = datetime.now()
                    total_days = original_days + supplement_days
                    today_display = ""
                    if today < start_date:
                        today_display = "未开始"
                    elif today > end_date:
                        today_display = "已结束"
                    else:
                        days_since_start = (today - start_date).days
                        if "supplements" in data and data["supplements"]:
                            current_day = 0
                            virtual_day = 0
                            is_supplement = False
                            while current_day <= days_since_start:
                                supplement_count = data["supplements"].get(
                                    str(virtual_day), 0
                                )
                                days_for_this_virtual = supplement_count + 1
                                if (
                                    current_day
                                    <= days_since_start
                                    < current_day + days_for_this_virtual
                                ):
                                    offset = days_since_start - current_day
                                    if offset == 0:
                                        today_display = f"D{virtual_day}"
                                    else:
                                        today_display = f"D{virtual_day}（补戏日）"
                                    break
                                current_day += days_for_this_virtual
                                virtual_day += 1
                        else:
                            day_number = (today - start_date).days
                            today_display = f"D{day_number}"
                    lettertime = getData("groupcollection", "lettertime.json")
                    send_time = lettertime.get(playname, {}).get("time", "未设置")
                    arc_time, arc_words = _monitor_arc_settings(playname)
                    reply_msg = f"恋综名称：{playname}\n"
                    reply_msg += f"日程时间：{start_date_str}-{end_date_str}\n"
                    reply_msg += f"今日状态：{today_display}\n"
                    reply_msg += f"后台群号：{data['manage_group']}（本群）\n"
                    reply_msg += f"公告群号：{data.get('notice_group', '未设置')}\n"
                    reply_msg += f"戏群群号：{data.get('play_group', '未设置')}\n"
                    reply_msg += f"发信时间：{send_time}\n"
                    reply_msg += f"记录弧长：{arc_time} {arc_words}\n"
                    reply_msg += f"备用调用：{data.get('play_method', '未设置')}\n\n"
                    if "supplements" in data and data["supplements"]:
                        reply_msg += "补戏信息：\n"
                        for virtual_day, supplement_count in data[
                            "supplements"
                        ].items():
                            reply_msg += f"D{virtual_day}：{supplement_count}天补戏\n"
                        reply_msg += "\n"
                    reply_msg += f"所有玩法默认开启，按需关闭。\n格式指令：「格式@骰子」\n后台指令：「后台@骰子」"
                    plugin_event.reply(reply_msg)
                    return
            except:
                pass
            plugin_event.reply(
                "仅骰主权限可注册恋综，复制并按说明填写以下格式发送至当前窗口，当前群注册为后台群。\n拉关系线不在时间范围内。\n\n当前群被绑定注册后，发送“恋综@骰子”可显示恋综详情。\n\n2:00-10:00为本恋综不计入弧长的休息时间，50为单回合计入弧长的最少字数。\n\n备用群调用方式一旦确定，不可更改，除非注销恋综（即删除所有数据）。在不确定的时候可以先填写「不使用」，后期再确定具体调用方式。\n\n"
                "恋综名称：\n"
                "开始时间：20260101\n"
                "结束时间：20260110\n"
                "公告群号：\n"
                "戏群群号：\n"
                "发信时间：hh:mm\n"
                "记录弧长：2:00-10:00 50\n"
                "备用调用：群号/二维码/不使用"
            )
    elif (
        "恋综名称：" in message
        and "开始时间：" in message
        and "结束时间：" in message
        and "发信时间：" in message
        and "备用调用：" in message
    ):
        playname_match = re.search(
            r"恋综名称：(.+?)(?=\n开始时间：|\n结束时间：|\n公告群号：|\n戏群群号：|\n发信时间：|\n备用调用：|$)",
            message,
            re.DOTALL,
        )
        if uid not in masterlist:
            plugin_event.reply("如需注册恋综请联系骰主开放权限。")
            return
        start_match = re.search(r"开始时间：(\d{8})", message)
        end_match = re.search(r"结束时间：(\d{8})", message)
        notice_match = re.search(r"公告群号：(\d*)", message)
        play_match = re.search(r"戏群群号：(\d*)", message)
        time_match = re.search(r"发信时间：(\d{2}:\d{2})", message)
        arc_match = re.search(r"记录弧长：([^\r\n]+)", message)
        backup_match = re.search(r"备用调用：(.+)", message)
        error_messages = []
        if not playname_match:
            error_messages.append("恋综名称未找到")
        if not start_match:
            error_messages.append("开始时间未找到")
        elif len(start_match.group(1)) != 8:
            error_messages.append("开始时间格式应为8位数字(如：20260101)")
        if not end_match:
            error_messages.append("结束时间未找到")
        elif len(end_match.group(1)) != 8:
            error_messages.append("结束时间格式应为8位数字(如：20260110)")
        if not time_match:
            error_messages.append("发信时间未找到，不可设置24:00或00:00")
        else:
            try:
                time_str = time_match.group(1)
                from datetime import datetime

                time_obj = datetime.strptime(time_str, "%H:%M")
                hour, minute = map(int, time_str.split(":"))
                if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                    error_messages.append(
                        "发信时间格式应为hh:mm（24小时制，不可设置24:00或00:00）"
                    )
            except ValueError:
                error_messages.append(
                    "发信时间格式应为hh:mm（24小时制，不可设置24:00或00:00）"
                )
        arc_setting = (
            _monitor_parse_arc_setting(arc_match.group(1)) if arc_match else None
        )
        if not arc_match:
            error_messages.append("记录弧长设置未找到")
        elif not arc_setting:
            error_messages.append(
                "记录弧长格式应为：2:00-10:00 50（时段在前，最低字数在后）"
            )
        if not backup_match:
            error_messages.append("备用群调用方式未找到")
        else:
            play_content = backup_match.group(1).strip()
            if play_content not in ["群号", "二维码", "不使用"]:
                error_messages.append("备用群调用方式为群号/二维码/不使用，三选一")
        if (
            notice_match
            and notice_match.group(1)
            and not re.match(r"^\d+$", notice_match.group(1))
        ):
            error_messages.append("公告群号必须为纯数字")
        if (
            play_match
            and play_match.group(1)
            and not re.match(r"^\d+$", play_match.group(1))
        ):
            error_messages.append("戏群群号必须为纯数字")
        if start_match and end_match:
            try:
                start_date = datetime.strptime(start_match.group(1), "%Y%m%d")
                end_date = datetime.strptime(end_match.group(1), "%Y%m%d")
                if start_date > end_date:
                    error_messages.append("开始时间不能晚于结束时间")
                if start_date == end_date:
                    error_messages.append("开始时间和结束时间不能为同一天")
                total_days = (end_date - start_date).days + 1
            except ValueError:
                error_messages.append("日期格式不正确")
        if error_messages:
            error_msg = "输入格式有误，请检查以下问题：\n"
            for msg in error_messages:
                error_msg += f"{msg}\n"
            error_msg += "\n请重新发送正确格式："
            plugin_event.reply(
                error_msg
                + "\n\n恋综名称：\n开始时间：20260101\n结束时间：20260110\n公告群号：\n戏群群号：\n发信时间：hh:mm\n记录弧长：2:00-10:00 50\n备用调用：群号/二维码/不使用"
            )
            return
        playname = playname_match.group(1).strip()
        start_date_str = start_match.group(1)
        end_date_str = end_match.group(1)
        notice_group = (
            notice_match.group(1) if notice_match and notice_match.group(1) else ""
        )
        play_group = play_match.group(1) if play_match and play_match.group(1) else ""
        send_time = time_match.group(1)
        arc_time, arc_words = arc_setting
        play_method = backup_match.group(1).strip()
        manage_group = str(plugin_event.data.group_id)
        time_changed = False
        old_send_time = None
        lettertime = getData("groupcollection", "lettertime.json")
        if playname in lettertime:
            old_send_time = lettertime[playname].get("time")
            if old_send_time != send_time:
                time_changed = True
        else:
            time_changed = True
        lettertime[playname] = {
            "time": send_time,
            "arc_time": arc_time,
            "arc_words": arc_words,
        }
        setData("groupcollection", "lettertime.json", lettertime)
        start_date = datetime.strptime(start_date_str, "%Y%m%d")
        end_date = datetime.strptime(end_date_str, "%Y%m%d")
        total_days = (end_date - start_date).days + 1
        register = getData("groupcollection", "register.json")
        is_update = playname in register
        if playname not in register:
            register[playname] = {}
        old_start_date = register[playname].get("start_date")
        old_end_date = register[playname].get("end_date")
        date_changed = (
            is_update
            and (old_start_date != start_date_str or old_end_date != end_date_str)
        )
        register[playname]["start_date"] = start_date_str
        register[playname]["end_date"] = end_date_str
        if date_changed:
            register[playname].pop("supplements", None)
            register[playname].pop("current_end_date", None)
        if notice_group:
            register[playname]["notice_group"] = notice_group
        elif "notice_group" not in register[playname]:
            register[playname]["notice_group"] = ""
        if play_group:
            register[playname]["play_group"] = play_group
        elif "play_group" not in register[playname]:
            register[playname]["play_group"] = ""
        register[playname]["play_method"] = play_method
        register[playname]["manage_group"] = manage_group
        setData("groupcollection", "register.json", register)
        effective_notice_group = register[playname].get("notice_group", "")
        effective_play_group = register[playname].get("play_group", "")
        reply_msg = f"已{'修改' if is_update else '开启'}恋综：{playname}\n"
        start_date_obj = datetime.strptime(start_date_str, "%Y%m%d")
        end_date_obj = datetime.strptime(end_date_str, "%Y%m%d")
        today = datetime.now()
        total_days = (end_date_obj - start_date_obj).days + 1
        if today < start_date_obj:
            today_display = "未开始"
        elif today > end_date_obj:
            today_display = "已结束"
        else:
            day_number = (today - start_date_obj).days
            today_display = f"D{day_number}"
        reply_msg += f"日程时间：{start_date_str}-{end_date_str}\n"
        reply_msg += f"今日状态：{today_display}，日程共{total_days}日\n"
        reply_msg += f"后台群号：{manage_group}（本群）\n"
        reply_msg += f"公告群号：{effective_notice_group if effective_notice_group else '未设置'}\n"
        reply_msg += f"戏群群号：{effective_play_group if effective_play_group else '未设置'}\n"
        reply_msg += f"发信时间：{send_time}\n"
        reply_msg += f"记录弧长：{arc_time} {arc_words}\n"
        reply_msg += f"备用调用：{play_method}\n\n"
        if date_changed:
            reply_msg += "检测到日程起止日期已修改，已清空原补戏记录。\n\n"
        reply_msg += f"所有玩法默认开启，按需关闭。\n格式指令：「格式@骰子」\n后台指令：「后台@骰子」"
        if time_changed:
            if old_send_time:
                change_type = "已修改"
            else:
                change_type = "已增加"
            reply_msg += f"\n\n【【【【【❗️注意❗️】】】】】\n检测到发信时间{change_type}，请骰主权限发送[.system restart]以刷新定时器，重载后请发送[.r]以激活定时器，【否则无法定时发送信件】。\n发送时删除[]，获得回复视为成功。"
        plugin_event.reply(reply_msg)
        if effective_notice_group:
            time.sleep(1)
            plugin_event.send(
                "group",
                effective_notice_group,
                f"本群已注册为恋综「{playname}」的公告群。",
            )
        if effective_play_group:
            time.sleep(1)
            plugin_event.send(
                "group",
                effective_play_group,
                f"本群已注册为恋综「{playname}」的戏群。",
            )

    elif message.startswith("个人群录入") or message.startswith("NPC录入"):
        if message.startswith("个人群录入"):
            register_type = "嘉宾"
            simple_pattern = r"个人群录入\s*(.+)"
            full_pattern = r"个人群录入\s*恋综名称：(.+?)\s*嘉宾姓名：([^\n]+?)(?:\s*嘉宾皮相：([^\n]*))?$"
            number_key = "嘉宾编号"
            name_key = "嘉宾姓名"
            avatar_key = "嘉宾皮相"
            group_key = "个人群号"
            allow_share = False  # 嘉宾不允许共享个人群
        else:  # NPC录入
            register_type = "NPC"
            simple_pattern = r"NPC录入\s*(.+)"
            full_pattern = r"NPC录入\s*恋综名称：(.+?)\s*NPC姓名：([^\n]+?)(?:\s*NPC皮相：([^\n]*))?$"
            number_key = "NPC编号"
            name_key = "NPC姓名"
            avatar_key = "NPC皮相"
            group_key = "NPC群号"
            allow_share = True  # NPC允许共享个人群
        match_full = re.match(full_pattern, message, re.DOTALL)
        if match_full:
            playname = match_full.group(1).strip()
            player = match_full.group(2).strip()
            avatar = match_full.group(3) if match_full.group(3) is not None else ""
            avatar = avatar.strip()
            if avatar and len(avatar) > 6:
                plugin_event.reply(
                    f"戏群头衔不允许皮相超过6个字，当前为{len(avatar)}个字，请重新输入噢！"
                )
                return
            is_admin_input = False
            target_uid = uid
            if uid in masterlist and re.search(r"\[OP:at,id=(\d+)\]", player):
                at_match = re.search(r"\[OP:at,id=(\d+)\]", player)
                if at_match:
                    target_uid = at_match.group(1)
                    player = re.sub(r"\[OP:at,id=\d+\]\s*", "", player).strip()
                    is_admin_input = True
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称或联系管理噢！"
                )
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname in privategroup and target_uid in privategroup[playname]:
                existing_user_data = privategroup[playname][target_uid]
                if (
                    group_key in existing_user_data
                    and existing_user_data[group_key] == groupid
                ):
                    if (
                        name_key in existing_user_data
                        and existing_user_data[name_key] != player
                    ):
                        plugin_event.reply(
                            f"{existing_user_data[name_key]}（{target_uid}）已在恋综「{playname}」中注册过{register_type}。如需补录皮相，请保持姓名一致。"
                        )
                        return
                    if avatar:
                        existing_user_data[avatar_key] = avatar
                    else:
                        if avatar_key not in existing_user_data:
                            existing_user_data[avatar_key] = ""
                    setData("groupcollection", "privategroup.json", privategroup)
                    reply_msg = (
                        f"皮相补录成功！\n\n"
                        f"恋综名称：{playname}\n"
                        f"{register_type}姓名：{existing_user_data[name_key]}\n"
                    )
                    if avatar:
                        reply_msg += f"{register_type}皮相：{avatar}\n"
                    else:
                        reply_msg += f"{register_type}皮相：未设置\n"
                    reply_msg += f"注册主体：{target_uid}\n"
                    reply_msg += f"{register_type}群号：{groupid}\n\n"
                    reply_msg += (
                        f"格式指令：「格式@骰子」\n如信息有误，请联系管理删除。"
                    )
                    plugin_event.reply(reply_msg)
                    return
                else:
                    if name_key in existing_user_data:
                        existing_name = existing_user_data[name_key]
                        plugin_event.reply(
                            f"{existing_name}（{target_uid}）已在恋综「{playname}」中注册过{register_type}，如需删除请联系管理。"
                        )
                        return
            if not allow_share and playname in privategroup:
                for existing_uid, user_data in privategroup[playname].items():
                    if (
                        user_data.get(group_key) == groupid
                        and existing_uid != target_uid
                    ):
                        plugin_event.reply(
                            f"本群（{groupid}）已在恋综「{playname}」中注册为其他{register_type}的个人群，如需删除请联系管理。"
                        )
                        return
            if playname not in privategroup:
                privategroup[playname] = {}
            type_count = 0
            for existing_uid, user_data in privategroup[playname].items():
                if number_key in user_data:
                    type_count += 1
            type_number = type_count + 1
            if target_uid not in privategroup[playname]:
                user_data = {
                    number_key: type_number,
                    name_key: player,
                    group_key: groupid,
                }
                if avatar:
                    user_data[avatar_key] = avatar
                privategroup[playname][target_uid] = user_data
            else:
                if register_type == "嘉宾":
                    for key in ["NPC编号", "NPC姓名", "NPC皮相", "NPC群号"]:
                        privategroup[playname][target_uid].pop(key, None)
                else:  # NPC
                    for key in ["嘉宾编号", "嘉宾姓名", "嘉宾皮相", "个人群号"]:
                        privategroup[playname][target_uid].pop(key, None)
                privategroup[playname][target_uid][number_key] = type_number
                privategroup[playname][target_uid][name_key] = player
                privategroup[playname][target_uid][group_key] = groupid
                if avatar:
                    privategroup[playname][target_uid][avatar_key] = avatar
                elif avatar_key in privategroup[playname][target_uid]:
                    del privategroup[playname][target_uid][avatar_key]
            setData("groupcollection", "privategroup.json", privategroup)
            if is_admin_input:
                reply_msg = (
                    f"管理{sender}代注册成功！\n\n"
                    f"恋综名称：{playname}\n"
                    f"{register_type}姓名：{player}\n"
                )
                if avatar:
                    reply_msg += f"{register_type}皮相：{avatar}\n"
                reply_msg += (
                    f"{register_type}账号：{target_uid}\n"
                    f"{register_type}群号：{groupid}\n\n"
                    f"格式指令：「格式@骰子」\n如信息有误，请联系管理删除。"
                )
            else:
                reply_msg = (
                    f"注册成功！\n\n"
                    f"恋综名称：{playname}\n"
                    f"{register_type}姓名：{player}\n"
                )
                if avatar:
                    reply_msg += f"{register_type}皮相：{avatar}\n"
                reply_msg += (
                    f"注册主体：{sender}\n"
                    f"{register_type}群号：{groupid}\n\n"
                    f"格式指令：「格式@骰子」\n如信息有误，请联系管理删除。"
                )
            plugin_event.reply(reply_msg)
            return
        match_simple = re.match(simple_pattern, message)
        if match_simple:
            playname = match_simple.group(1).strip()
            register = getData("groupcollection", "register.json")
            if playname not in register:
                return
            if register_type == "嘉宾":
                plugin_event.reply(
                    "① 请复制以下内容，填写后发送至当前窗口，若没有回执则填写错误。\n\n② 皮相为戏群头衔服务，可为空，按需补录（重发格式）。\n\n③ 支持管理代录入。"
                )
                time.sleep(1)
                plugin_event.reply(
                    f"个人群录入\n恋综名称：{playname}\n嘉宾姓名：\n嘉宾皮相："
                )
            else:  # NPC
                plugin_event.reply(
                    "① 请复制以下内容，填写后发送至当前窗口，若没有回奏则填写错误。\n\n② 皮相为戏群头衔服务，可为空，按需补录（重发格式）。\n\n③ NPC允许共享个人群。\n\n④ 支持管理代录入。"
                )
                time.sleep(1)
                plugin_event.reply(
                    f"NPC录入\n恋综名称：{playname}\nNPC姓名：\nNPC皮相："
                )
            return
        return

    elif re.match(
        r"<(.+?)·关系线>\s*发送者：(.+?)\s*接收者：(.+?)\s*内容：([\s\S]*)", message
    ):
        match = re.match(
            r"<(.+?)·关系线>\s*发送者：(.+?)\s*接收者：(.+?)\s*内容：([\s\S]*)", message
        )
        if match:
            playname = match.group(1).strip()
            sender_name = match.group(2).strip()
            receiver_name = match.group(3).strip()
            content = match.group(4).strip()
            try:
                limit_data = getData("sendmessage", "limit.json")
                if playname in limit_data and "relation" in limit_data[playname]:
                    limit_date_str = limit_data[playname]["relation"]

                    if limit_date_str and len(limit_date_str) == 8:
                        from datetime import datetime

                        current_date = datetime.now()
                        current_date_str = current_date.strftime("%Y%m%d")
                        current_date_int = int(current_date_str)
                        limit_date_int = int(limit_date_str)
                        if current_date_int > limit_date_int:
                            plugin_event.reply(
                                f"关系线发送失败！\n\n恋综「{playname}」的关系线已于{limit_date_str[:4]}年{limit_date_str[4:6]}月{limit_date_str[6:8]}日24:00截止！"
                            )
                            return
            except Exception as e:
                pass
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            user_found = False
            user_info = None
            for uid_in_file, info in privategroup[playname].items():
                if uid_in_file == uid:
                    user_found = True
                    user_info = info
                    break
            if not user_found:
                plugin_event.reply(f"{sender}不是该恋综的嘉宾或NPC，无法发送关系线噢！")
                return
            if playname in privategroup and uid in privategroup[playname]:
                user_groupid = privategroup[playname][uid].get(
                    "个人群号"
                ) or privategroup[playname][uid].get("NPC群号")
            if user_groupid != groupid:
                plugin_event.reply(f"请前往个人群中发送关系线噢！")
                return
            sender_registered_name = None
            if "嘉宾姓名" in user_info:
                sender_registered_name = user_info["嘉宾姓名"]
            elif "NPC姓名" in user_info:
                sender_registered_name = user_info["NPC姓名"]
            if sender_registered_name != sender_name:
                plugin_event.reply(
                    f"发送者姓名与登记的姓名「{sender_registered_name}」不匹配，无法发送关系线噢！"
                )
                return
            receiver_found = False
            receiver_uid = None
            receiver_info = None
            for uid_in_file, info in privategroup[playname].items():
                if info.get("嘉宾姓名") == receiver_name:
                    receiver_found = True
                    receiver_uid = uid_in_file
                    receiver_info = info
                    break
                elif info.get("NPC姓名") == receiver_name:
                    receiver_found = True
                    receiver_uid = uid_in_file
                    receiver_info = info
                    break
            if not receiver_found:
                plugin_event.reply(
                    f"接收者「{receiver_name}」不是恋综「{playname}」的嘉宾或NPC，无法发送关系线噢！"
                )
                return
            receiver_group_id = receiver_info.get("个人群号") or receiver_info.get(
                "NPC群号"
            )
            if not receiver_group_id:
                plugin_event.reply(
                    f"接收者「{receiver_name}」的个人群号/NPC群号未设置，无法发送关系线噢！"
                )
                return
            key1 = f"{sender_name}→{receiver_name}"
            key2 = f"{receiver_name}→{sender_name}"
            relation_data = {}
            relation_file = f"{playname}.json"
            try:
                relation_data = getData("relation", relation_file)
            except:
                relation_data = {}
            existing_key = None
            if key1 in relation_data:
                existing_key = key1
            elif key2 in relation_data:
                existing_key = key2
            content_to_save = content
            if existing_key:
                content_to_save = f"{sender_name}→{receiver_name}\n\n{content}"
            if existing_key:
                max_num = 0
                for k in relation_data[existing_key].keys():
                    if k.isdigit():
                        max_num = max(max_num, int(k))
                new_key = str(max_num + 1)
                relation_data[existing_key][new_key] = content_to_save
                display_sender, display_receiver = existing_key.split("→")
            else:
                relation_data[key1] = {"1": content_to_save}
                existing_key = key1
                display_sender, display_receiver = sender_name, receiver_name
            setData("relation", relation_file, relation_data)
            plugin_event.reply("关系线发送成功！")
            time.sleep(1)
            plugin_event.send(
                "group",
                receiver_group_id,
                f"{receiver_name}收到了新的关系线！\n\n如需拒绝，请引用合并转发消息并附文「@骰子 {playname}拒绝关系线」即可删除最新一条内容。\n\n指令「关系线@骰子」可查看所有关系线。",
            )
            relation_contents = relation_data[existing_key]
            content_keys = [k for k in relation_contents.keys() if k.isdigit()]
            content_keys.sort(key=int)
            nodes_data = []
            for i, key in enumerate(content_keys):
                if i == 0:
                    first_content = relation_contents[key]
                    if "→" in first_content and "\n\n" in first_content:
                        header_text = first_content
                    else:
                        header_text = (
                            f"{display_sender}→{display_receiver}\n\n{first_content}"
                        )
                else:
                    header_text = relation_contents[key]
                nodes_data.append({"bot_id": bot_id, "content_text": header_text})
            result = send_forward_message(
                bot_port, bot_token, receiver_group_id, nodes_data
            )
            if result.get("retcode") != 0:
                register = getData("groupcollection", "register.json")
                manage_group = None
                if playname in register and "manage_group" in register[playname]:
                    manage_group = register[playname]["manage_group"]
                if manage_group:
                    notification = (
                        f"恋综「{playname}」的{sender_name}发送给{receiver_name}的合并转发消息构造失败，"
                        f"错误信息：{result.get('message', '未知错误')}"
                    )
                    plugin_event.send("group", manage_group, notification)

    elif re.match(r"\[OP:reply,id=([-]?\d+)\]<(.+)·点歌>", message) or re.match(
        r"<(.+)·点歌>", message
    ):
        reply_match = re.match(r"\[OP:reply,id=([-]?\d+)\]", message)
        song_match = None
        if reply_match:
            reply_id = reply_match.group(1)
            replied_msg = plugin_event.get_msg(reply_id)["data"]
            raw_message = replied_msg.get("raw_message", "")
            song_part = message[reply_match.end() :].strip()
            song_match = re.match(
                r"<(.+)·点歌>\s*歌曲：\s*(.+?)\s*留言：\s*(.*?)\s*署名：\s*(.*)",
                song_part,
                re.DOTALL,
            )
        else:
            song_match = re.match(
                r"<(.+)·点歌>\s*歌曲：\s*(.+?)\s*留言：\s*(.*?)\s*署名：\s*(.*)",
                message,
                re.DOTALL,
            )
        if song_match:
            playname = song_match.group(1).strip()
            song_name = song_match.group(2).strip()
            message_text = song_match.group(3).strip()
            signature = song_match.group(4).strip()
            if not song_name:
                plugin_event.reply("歌曲名不能为空噢！")
                return
            try:
                limit_data = getData("sendmessage", "limit.json")
                limit_key = "点歌"
                if playname in limit_data and limit_key in limit_data[playname]:
                    limit_num = limit_data[playname][limit_key]
                    if limit_num != -1:
                        try:
                            summary_data = getData("engagement", "summary.json")
                        except:
                            summary_data = {}
                        current_count = 0
                        if (
                            playname in summary_data
                            and limit_key in summary_data[playname]
                        ):
                            current_count = summary_data[playname][limit_key]
                        if limit_num == 0:
                            plugin_event.reply(f"恋综「{playname}」的点歌功能未开启！")
                            return
                        elif current_count >= limit_num:
                            plugin_event.reply(
                                f"恋综「{playname}」的点歌数量已达上限！\n已点{current_count}首，限制{limit_num}首。"
                            )
                            return
            except Exception as e:
                pass
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名噢！"
                )
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup or uid not in privategroup[playname]:
                plugin_event.reply(
                    f"{sender}不是恋综「{playname}」的嘉宾/NPC，无法点歌噢！"
                )
                return
            play_group = register[playname].get("play_group", "")
            if not play_group:
                plugin_event.reply(f"恋综「{playname}」未设置戏群，无法点歌噢！")
                return
            if not message_text:
                message_text = "-"
            if not signature:
                signature = "-"
            send_msg = f"<{playname}·点歌>\n歌曲：{song_name}\n留言：{message_text}\n署名：{signature}"
            send_success = False
            if reply_match:
                try:
                    plugin_event.send("group", play_group, raw_message)
                    plugin_event.send("group", play_group, send_msg)
                    send_success = True
                    plugin_event.reply(f"点歌成功，《{song_name}》已发送到戏群啦！")
                except Exception as e:
                    plugin_event.reply(f"发送失败：{str(e)}")
                    return
            else:
                song_id = search_netease_music(song_name)
                if song_id:
                    api_url = f"http://127.0.0.1:{bot_port}/send_group_msg"
                    music_payload = {
                        "group_id": int(play_group),
                        "message": [
                            {"type": "music", "data": {"type": "163", "id": song_id}}
                        ],
                    }
                    headers = {
                        "Authorization": f"Bearer {bot_token}",
                        "Content-Type": "application/json",
                    }
                    try:
                        response = requests.post(
                            api_url,
                            headers=headers,
                            data=json.dumps(music_payload),
                            timeout=10,
                        )
                        if response.status_code == 200:
                            result = response.json()
                            if result.get("status") == "ok":
                                plugin_event.send("group", play_group, send_msg)
                                send_success = True
                                time.sleep(1)
                                plugin_event.reply(
                                    f"点歌成功，歌曲《{song_name}》已发送到戏群啦！"
                                )
                            else:
                                plugin_event.reply(
                                    f"点歌失败！请联系骰主检查或使用点歌方式2。"
                                )
                    except requests.exceptions.RequestException as e:
                        plugin_event.reply(f"点歌失败！请联系骰主检查或使用点歌方式2。")
                else:
                    plugin_event.reply(f"点歌失败！请联系骰主检查或使用点歌方式2")
            if send_success:
                summary_data = getData("engagement", "summary.json")
                if playname not in summary_data:
                    summary_data[playname] = {}
                if "点歌" not in summary_data[playname]:
                    summary_data[playname]["点歌"] = 1
                else:
                    summary_data[playname]["点歌"] += 1
                setData("engagement", "summary.json", summary_data)

    elif message.startswith("<") and "·留言板bot>" in message:
        match_prefix = re.match(r"<(.+?)·留言板bot>", message)
        if match_prefix:
            playname = match_prefix.group(1).strip()
            content = message[match_prefix.end() :].strip()
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                return
            user_found = False
            user_groupid = None
            user_name = ""
            for uid_key in privategroup[playname]:
                if uid_key.isdigit() and uid_key == uid:
                    user_data = privategroup[playname][uid_key]
                    if "NPC姓名" in user_data:
                        user_name = user_data.get("NPC姓名", uid)
                        user_groupid = user_data.get("NPC群号")
                    else:
                        user_name = user_data.get("嘉宾姓名", uid)
                        user_groupid = user_data.get("个人群号")
                    user_found = True
                    break
            if not user_found:
                plugin_event.reply(
                    f"{sender}不是恋综「{playname}」的嘉宾/NPC，无法发送留言板噢！"
                )
                return
            if str(groupid) != str(user_groupid):
                plugin_event.reply(f"请前往绑定的个人群发送留言噢！")
                return

            match = re.match(
                r"留言人：\s*(.*?)\s*接收人：\s*(.*?)\s*内容：\s*(.*)",
                content,
                re.DOTALL,
            )
            if not match:
                error_template = (
                    "请按照以下格式上传噢！\n\n"
                    f"<{playname}·留言板bot>\n"
                    "留言人：（可为空）\n"
                    "接收人：（可为空）\n"
                    "内容：（不可为空）"
                )
                plugin_event.reply(error_template)
                return
            author_part = match.group(1).strip() or "-"
            receiver_part = match.group(2).strip() or "-"
            content_part = match.group(3).strip()
            if not content_part:
                plugin_event.reply("内容不能为空，请检查格式后重新输入噢！")
                return

            register = getData("groupcollection", "register.json")
            if playname not in register:
                return
            play_group = register[playname].get("play_group", "")
            if not play_group:
                plugin_event.reply(
                    f"恋综「{playname}」的戏群未设置，请联系管理设置噢！"
                )
                return

            try:
                limit_data = getData("sendmessage", "limit.json")
                limit_key = "留言板"

                if playname in limit_data and limit_key in limit_data[playname]:
                    limit_num = limit_data[playname][limit_key]

                    if limit_num != -1:
                        try:
                            summary_data = getData("engagement", "summary.json")
                        except:
                            summary_data = {}

                        current_count = 0
                        if (
                            playname in summary_data
                            and limit_key in summary_data[playname]
                        ):
                            current_count = summary_data[playname][limit_key]

                        if limit_num == 0:
                            plugin_event.reply(
                                f"恋综「{playname}」的留言板功能未开启！"
                            )
                            return
                        elif current_count >= limit_num:
                            plugin_event.reply(
                                f"恋综「{playname}」的留言板数量已达上限！\n已发送{current_count}条，限制{limit_num}条。"
                            )
                            return
            except Exception as e:
                pass
            plugin_event.reply(f"留言成功啦！")
            time.sleep(1)
            notification_msg = (
                f"<{playname}·留言板bot>\n"
                f"留言人：{author_part}\n"
                f"接收人：{receiver_part}\n"
                f"内容：{content_part}"
            )
            plugin_event.send("group", play_group, notification_msg)
            summary_data = getData("engagement", "summary.json")
            if playname not in summary_data:
                summary_data[playname] = {}
            if "留言板" not in summary_data[playname]:
                summary_data[playname]["留言板"] = 1
            else:
                summary_data[playname]["留言板"] += 1
            setData("engagement", "summary.json", summary_data)

    elif (
        message.strip().startswith("删除心动信")
        or re.match(r"^(.+?)\s*限制心动信", message)
        or re.search(r"致\s*.+?\s*心动信", message)
        or re.search(r"心动信\s+.+?\s*致", message)
    ):
        if message.strip().startswith("删除心动信"):
            delete_pattern = r"删除心动信\s*(.+?)\s+心动信\s+(.+?)\s+致\s+(.+?)\s*内容：\s*(.+?)\s*\n署名：\s*(.+)"
            delete_match = re.match(delete_pattern, message, re.DOTALL)
            if delete_match:
                from datetime import datetime

                playname = delete_match.group(1).strip()
                date = datetime.now().strftime("%y%m%d")
                sender_name = delete_match.group(2).strip()
                receiver_name = delete_match.group(3).strip()
                content_to_match = delete_match.group(4).strip()
                signature_to_match = delete_match.group(5).strip()
                if not content_to_match or not signature_to_match:
                    plugin_event.reply(
                        "删除指令中的内容或署名不可为空，请提供具体的内容和署名以便匹配信件！"
                    )
                    return
                privategroup = getData("groupcollection", "privategroup.json")
                if playname not in privategroup:
                    plugin_event.reply(
                        f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                    )
                    return
                sender_uid = None
                for guest_uid, guest_info in privategroup[playname].items():
                    guest_name = guest_info.get("嘉宾姓名") or guest_info.get("NPC姓名")
                    if guest_name == sender_name:
                        sender_uid = guest_uid
                        break
                if not sender_uid:
                    sender_display = plugin_event.data.sender["name"]
                    plugin_event.reply(
                        f"{sender_display}不是恋综「{playname}」的嘉宾或NPC，无法删除心动信噢！"
                    )
                    return
                is_master = uid in masterlist
                if not is_master:
                    if str(uid) != str(sender_uid):
                        sender_display = plugin_event.data.sender["name"]
                        plugin_event.reply(
                            f"{sender_display}只能删除自己发送的心动信噢！"
                        )
                        return
                receiver_uid = None
                for guest_uid, guest_info in privategroup[playname].items():
                    guest_name = guest_info.get("嘉宾姓名") or guest_info.get("NPC姓名")
                    if guest_name == receiver_name:
                        receiver_uid = guest_uid
                        break
                if not receiver_uid:
                    plugin_event.reply(
                        f"收信者「{receiver_name}」不是恋综「{playname}」的嘉宾或NPC，没有查找到匹配的信件噢！"
                    )
                    return
                letters = getData("sendmessage", "letters.json")
                found_keys = []
                for key in letters.keys():
                    # 使用正则表达式匹配键结构，考虑签名为空的情况
                    # 这个正则表达式会匹配所有部分，即使签名为空
                    pattern = r"([^/]+)/////(\d{6})/////([^/]+)/////([^/]+)/////(.*?)(?://///(\d{2}:\d{2}:\d{2}))?$"
                    match = re.match(pattern, key)

                    if match:
                        key_playname = match.group(1)
                        key_date = match.group(2)
                        key_sender = match.group(3)
                        key_recver = match.group(4)
                        # 签名为group(5)，可能是空字符串
                        key_signature = match.group(5)
                        # 如果签名为空字符串，说明原始署名为"/"
                        if key_signature == "":
                            key_signature = "/"
                        key_time = match.group(6) if match.group(6) else "00:00:00"
                    else:
                        # 如果正则不匹配，尝试更简单的split方法
                        parts = key.split("/////", 5)  # 最多分割5次，得到6个部分
                        if len(parts) >= 6:
                            # 正常有签名的情况
                            key_playname = parts[0]
                            key_date = parts[1]
                            key_sender = parts[2]
                            key_recver = parts[3]
                            key_signature = parts[4]
                            key_time = parts[5]
                        elif len(parts) == 5:
                            # 签名为空的情况
                            key_playname = parts[0]
                            key_date = parts[1]
                            key_sender = parts[2]
                            key_recver = parts[3]
                            key_signature = "/"
                            key_time = parts[4] if len(parts) > 4 else "00:00:00"
                        else:
                            continue

                    # 特殊情况处理：如果签名是空字符串，可能是/
                    if key_signature == "":
                        key_signature = "/"

                    key_content = letters[key]

                    if (
                        key_playname == playname
                        and key_date == date
                        and key_sender == str(sender_uid)
                        and key_recver == str(receiver_uid)
                    ):
                        clean_signature = key_signature
                        image_pattern = r"\[(?:CQ|OP):image[^\]]*\]"
                        clean_signature = re.sub(
                            image_pattern, "", clean_signature
                        ).strip()
                        clean_content = key_content
                        clean_content = re.sub(image_pattern, "", clean_content).strip()
                        if (
                            clean_content == content_to_match
                            and clean_signature == signature_to_match
                        ):
                            found_keys.append((key, key_time))
                if not found_keys:
                    plugin_event.reply(
                        f"未找到完全匹配的心动信，若原始信件中含有图片，请在删除指令中去掉图片后重新发送噢！"
                    )
                    return
                found_keys.sort(key=lambda x: x[1], reverse=True)
                key_to_delete = found_keys[0][0]
                del letters[key_to_delete]
                setData("sendmessage", "letters.json", letters)
                if len(found_keys) > 1:
                    plugin_event.reply(
                        f"成功删除{sender_name}写给{receiver_name}的心动信！\n\n"
                        f"【注意】\n找到{len(found_keys)}条完全匹配的信件，已删除时间最晚的一封（{found_keys[0][1]}）。\n如需继续删除，请再次发送。"
                    )
                else:
                    plugin_event.reply(
                        f"成功删除{sender_name}写给{receiver_name}的心动信！"
                    )
                return
        limit_match = re.match(r"^(.+?)\s*限制心动信", message)
        if limit_match:
            playname = limit_match.group(1).strip()
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可设置心动信限额。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置限额。")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            personal_match = re.match(
                r"^(.+?)\s*限制心动信\s+([Dd]\d+)\s+(.+?)\s+(-?\d+)$", message.strip()
            )
            if personal_match:
                if personal_match.group(1).strip() != playname:
                    return
                day_key = personal_match.group(2).upper()
                person_name = personal_match.group(3).strip()
                limit_num = int(personal_match.group(4))
                if limit_num < -1:
                    plugin_event.reply(
                        "限制数量不能为其他负数，0表示不能发信，-1表示移除限制。"
                    )
                    return
                person_exists = False
                if playname in privategroup:
                    for guest_uid, guest_info in privategroup[playname].items():
                        guest_name = guest_info.get("嘉宾姓名") or guest_info.get(
                            "NPC姓名"
                        )
                        if guest_name == person_name:
                            person_exists = True
                            break
                if not person_exists:
                    plugin_event.reply(
                        f"在恋综「{playname}」中未找到嘉宾或NPC「{person_name}」，请检查噢！"
                    )
                    return
                limit_data = getData("sendmessage", "limit.json")
                if playname not in limit_data:
                    limit_data[playname] = {}
                if "letter" not in limit_data[playname]:
                    limit_data[playname]["letter"] = {}
                personal_key = f"{day_key}_{person_name}"
                if limit_num == -1:
                    if personal_key in limit_data[playname]["letter"]:
                        del limit_data[playname]["letter"][personal_key]
                        plugin_event.reply(
                            f"已移除恋综「{playname}」{day_key}「{person_name}」的心动信限制。"
                        )
                    else:
                        plugin_event.reply(
                            f"恋综「{playname}」{day_key}「{person_name}」没有心动信限制，无需移除。"
                        )
                else:
                    limit_data[playname]["letter"][personal_key] = limit_num
                    plugin_event.reply(
                        f"已设置恋综「{playname}」{day_key}「{person_name}」的心动信限额为{limit_num}封。"
                    )
                setData("sendmessage", "limit.json", limit_data)
                return
            lines = message.strip().splitlines()
            first_line = lines[0]
            from datetime import datetime

            if len(lines) == 1:
                start_date_str = data["start_date"]
                end_date_str = data.get("end_date", "")
                start_date = datetime.strptime(start_date_str, "%Y%m%d")
                if end_date_str:
                    end_date = datetime.strptime(end_date_str, "%Y%m%d")
                    original_total_days = (end_date - start_date).days + 1
                else:
                    original_total_days = 1
                limit_data = getData("sendmessage", "limit.json")
                playname_limits = limit_data.get(playname, {}).get("letter", {})
                template = f"{playname} 限制心动信\n"
                for day in range(original_total_days):
                    day_key = f"D{day}"
                    default_limit = playname_limits.get(day_key, "")
                    template += f"{day_key}：{default_limit}\n"
                plugin_event.reply(template)
                return
            elif len(lines) > 1:
                limit_data = getData("sendmessage", "limit.json")
                if playname not in limit_data:
                    limit_data[playname] = {}
                if "letter" not in limit_data[playname]:
                    limit_data[playname]["letter"] = {}
                updated_days = []
                for line in lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    day_match = re.match(r"([Dd]\d+)\s*[:：]\s*(-?\d+|)", line)
                    if day_match:
                        day_key = day_match.group(1).upper()
                        limit_str = day_match.group(2)
                        if limit_str == "":
                            if day_key in limit_data[playname]["letter"]:
                                del limit_data[playname]["letter"][day_key]
                                updated_days.append(f"{day_key}：删除限额")
                            else:
                                pass
                        elif limit_str == "-1":
                            if day_key in limit_data[playname]["letter"]:
                                del limit_data[playname]["letter"][day_key]
                            updated_days.append(f"{day_key}：不限制")
                        else:
                            try:
                                limit_num = int(limit_str)
                                if limit_num < 0:
                                    plugin_event.reply(
                                        f"{day_key}的限制数量不能为其他负数，0表示不能发信，-1表示不限制。"
                                    )
                                    return
                                limit_data[playname]["letter"][day_key] = limit_num
                                updated_days.append(f"{day_key}：{limit_num}")
                            except ValueError:
                                continue
                setData("sendmessage", "limit.json", limit_data)
                if updated_days:
                    result_msg = f"恋综「{playname}」心动信限额设置成功！\n\n"
                    result_msg += "\n".join(updated_days)
                    plugin_event.reply(result_msg)
                else:
                    plugin_event.reply("未找到有效的限额设置信息，请检查格式！")
                return
        if not (
            re.search(r"致\s*.+?\s*心动信", message)
            or re.search(r"心动信\s+.+?\s*致", message)
        ):
            return
        letters = getData("sendmessage", "letters.json")
        if re.search(r"\[(OP|CQ):image,.+\]", message):
            image = re.search(r"\[(OP|CQ):image,.+\]", message).group(0)
            message = message.replace(image, "")
        else:
            image = ""
        from datetime import datetime

        match1 = re.match(
            r"(.+?)\s+心动信\s+(.+?)\s*致\s*(.+?)\s*内容：\s*([\s\S]+?)\s*署名：\s*([\s\S]+)",
            message,
        )
        if match1:
            playname = match1.group(1).strip()
            now = datetime.now()
            date = now.strftime("%y%m%d")
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            if date in real_to_virtual:
                virtual_day = real_to_virtual[date]
                day_display = f"D{virtual_day}"
                day_key = f"D{virtual_day}"
            else:
                virtual_day = None
                day_display = "今日"
                day_key = None
            sender = str(uid)
            recver = match1.group(3).strip()
            content = match1.group(4).strip()
            url_pattern = re.compile(r"https?://\S+")
            if url_pattern.search(content):
                plugin_event.reply(
                    "为避免风险检测，内容中不建议包含网页链接，请重新输入噢！\n如为图片，请插在消息末尾"
                )
                return
            signature = match1.group(5).strip() + image
            if not content or not signature:
                plugin_event.reply("内容或署名不可为空噢！可为符号或假名。")
                return
            url_pattern = re.compile(r"https?://\S+")
            if url_pattern.search(content):
                plugin_event.reply(
                    "为避免风险检测，内容中不建议包含网页链接，请重新输入噢！\n如为图片，请插在消息末尾。"
                )
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if not re.match(r"^\d+$", recver):
                if playname in privategroup:
                    found = False
                    for guest_uid, guest_info in privategroup[playname].items():
                        if guest_info.get("嘉宾姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                        if guest_info.get("NPC姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                    if not found:
                        plugin_event.reply(
                            "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                        )
                        return
            if not re.match(r"^\d+$", recver):
                plugin_event.reply(
                    "本场恋综已录入信息中未找到该嘉宾姓名，请检查填写信息或改为填写收件人qq噢！"
                )
                return
            lettertime = getData("groupcollection", "lettertime.json")
            send_time_str = lettertime.get(playname, {}).get("time", "22:30")
            send_hour, send_minute = map(int, send_time_str.split(":"))
            if now.hour > send_hour or (
                now.hour == send_hour and now.minute >= send_minute
            ):
                plugin_event.reply(
                    f"信件超时，发信时间{send_time_str}已过，找不到信鸽啦！"
                )
                return
            else:
                if playname not in privategroup or uid not in privategroup[playname]:
                    sender = plugin_event.data.sender["name"]
                    plugin_event.reply(
                        f"{sender}不是恋综「{playname}」的嘉宾或NPC，无法发送信件噢！"
                    )
                    return
                sender_name = None
                if playname in privategroup and uid in privategroup[playname]:
                    user_info = privategroup[playname][uid]
                    sender_name = user_info.get("嘉宾姓名") or user_info.get("NPC姓名")
                limit_data = getData("sendmessage", "limit.json")
                daily_limit = None
                if playname in limit_data and "letter" in limit_data[playname]:
                    playname_limits = limit_data[playname]["letter"]
                    if sender_name and day_key:
                        personal_key = f"{day_key}_{sender_name}"
                        if personal_key in playname_limits:
                            daily_limit = playname_limits[personal_key]
                    if daily_limit is None and day_key and day_key in playname_limits:
                        daily_limit = playname_limits[day_key]
                current_count = 0
                for key in letters.keys():
                    parts = key.split("/////")
                    if len(parts) >= 5:
                        key_playname = parts[0]
                        key_date = parts[1]
                        key_sender = parts[2]
                        if (
                            key_playname == playname
                            and key_date == date
                            and key_sender == uid
                        ):
                            current_count += 1
                if daily_limit is not None:
                    if current_count >= daily_limit:
                        if sender_name and f"{day_key}_{sender_name}" in limit_data.get(
                            playname, {}
                        ).get("letter", {}):
                            limit_type = f"{day_key}个人限额"
                        else:
                            limit_type = f"{day_key}限额"
                        plugin_event.reply(
                            f"{day_display}已发送{current_count}封信啦！达到{limit_type}{daily_limit}封，无法继续发送。"
                        )
                        return
                reply_message = f"信件将在{send_time_str}护送！\n\n"
                if daily_limit is not None:
                    if sender_name and f"{day_key}_{sender_name}" in limit_data.get(
                        playname, {}
                    ).get("letter", {}):
                        reply_message += f"{day_display}已发送{current_count + 1}/{daily_limit}（个人限额）封，"
                    else:
                        reply_message += (
                            f"{day_display}已发送{current_count + 1}/{daily_limit}封，"
                        )
                else:
                    reply_message += f"{day_display}已发送{current_count + 1}封，"
                reply_message += "为避免冲突，请在10秒后发送下一封信噢！"
                plugin_event.reply(reply_message)
            key = (
                playname
                + "/////"
                + date
                + "/////"
                + sender
                + "/////"
                + recver
                + "/////"
                + signature
                + "/////"
                + now.strftime("%H:%M:%S")
            )
            letters[key] = content
            setData("sendmessage", "letters.json", letters)
            time.sleep(2)
            letters = getData("sendmessage", "letters.json")
            while key not in letters:
                letters[key] = content
                setData("sendmessage", "letters.json", letters)
                time.sleep(2)
                letters = getData("sendmessage", "letters.json")
            return
        elif (
            not "礼物" in message and not "小纸条" in message and not "短信" in message
        ):
            return

    elif re.match(r"^掉落群设置\s+(.+)$", message):
        match = re.match(r"^掉落群设置\s+(.+)$", message)
        playname = match.group(1).strip()
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可设置专属掉落群。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        if groupid != str(register[playname].get("manage_group", "")):
            plugin_event.reply(f"请在恋综「{playname}」的后台群中设置专属掉落群。")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            plugin_event.reply(f"恋综「{playname}」暂无嘉宾数据。")
            return
        limit_data = getData("sendmessage", "limit.json")
        group_map = limit_data.get(playname, {}).get("drop_guest_groups", {})
        lines = [f"【掉落群设置·{playname}】"]
        for member_uid, info in privategroup[playname].items():
            if not str(member_uid).isdigit() or not isinstance(info, dict):
                continue
            member_name = _get_member_display_name(info)
            if not member_name:
                continue
            group_ids = group_map.get(str(member_uid), []) if isinstance(group_map, dict) else []
            if isinstance(group_ids, str):
                group_ids = _parse_group_id_list(group_ids)
            lines.append(f"{member_name}：{' '.join(group_ids)}")
        plugin_event.reply("\n".join(lines))
        return

    elif message.startswith("【掉落群设置·"):
        match = re.search(r"【掉落群设置·(.+?)】", message)
        if not match:
            plugin_event.reply("格式错误！")
            return
        playname = match.group(1).strip()
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可设置专属掉落群。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        if groupid != str(register[playname].get("manage_group", "")):
            plugin_event.reply(f"请在恋综「{playname}」的后台群中设置专属掉落群。")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            plugin_event.reply(f"恋综「{playname}」暂无嘉宾数据。")
            return
        name_to_uid = {}
        for member_uid, info in privategroup[playname].items():
            member_name = _get_member_display_name(info)
            if str(member_uid).isdigit() and member_name:
                name_to_uid[member_name] = str(member_uid)
        limit_data = getData("sendmessage", "limit.json")
        if playname not in limit_data:
            limit_data[playname] = {}
        group_map = limit_data[playname].setdefault("drop_guest_groups", {})
        updated = []
        cleared = []
        not_found = []
        for line in message[match.end():].splitlines():
            line = line.strip()
            if not line:
                continue
            line_match = re.match(r"(.+?)[:：]\s*(.*)", line)
            if not line_match:
                continue
            member_name, group_text = line_match.groups()
            member_name = member_name.strip()
            group_text = group_text.strip()
            member_uid = name_to_uid.get(member_name)
            if not member_uid:
                not_found.append(member_name)
                continue
            if not group_text:
                continue
            if group_text == "无":
                if member_uid in group_map:
                    del group_map[member_uid]
                cleared.append(member_name)
                continue
            group_ids = _parse_group_id_list(group_text)
            if group_ids:
                group_map[member_uid] = group_ids
                updated.append(member_name)
        if not group_map:
            limit_data[playname].pop("drop_guest_groups", None)
        if not limit_data[playname]:
            del limit_data[playname]
        setData("sendmessage", "limit.json", limit_data)
        reply_msg = f"专属掉落群已保存：{len(updated)}人"
        if cleared:
            reply_msg += f"\n已清空：{'、'.join(cleared)}"
        if not_found:
            reply_msg += f"\n未找到：{'、'.join(not_found)}"
        plugin_event.reply(reply_msg)
        return

    elif re.match(r"^(.+?)\s*(礼物|小纸条|短信)掉落\s+(.+)$", message):
        match = re.match(r"^(.+?)\s*(礼物|小纸条|短信)掉落\s+(.+)$", message)
        playname = match.group(1).strip()
        item_type = match.group(2)
        rule_text = match.group(3).strip()
        if uid not in masterlist:
            plugin_event.reply(f"权限不足，仅骰主可设置{item_type}掉落概率。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        if groupid != str(register[playname].get("manage_group", "")):
            plugin_event.reply(f"请在恋综「{playname}」的后台群中设置{item_type}掉落。")
            return
        limit_data = getData("sendmessage", "limit.json")
        if rule_text in ("关闭", "0", "无"):
            _clear_drop_rules(limit_data, playname, item_type)
            setData("sendmessage", "limit.json", limit_data)
            plugin_event.reply(f"已关闭恋综「{playname}」的{item_type}掉落功能。")
            return
        rules, error_msg = _parse_drop_rule_text(rule_text)
        if error_msg:
            plugin_event.reply(error_msg)
            return
        _set_drop_rules(limit_data, playname, item_type, rules)
        setData("sendmessage", "limit.json", limit_data)
        target_names = {"play_group": "戏群", "random_guest_group": "嘉宾群", "exclusive_group": "专属群"}
        rule_display = " ".join(
            f"{target_names.get(rule['target'], rule['target'])}{float(rule['probability']):g}"
            for rule in rules
        )
        plugin_event.reply(f"已设置恋综「{playname}」的{item_type}掉落规则：{rule_display}")
        return

    elif (
        re.search(r"致\s*.+?\s*礼物", message)
        or re.search(r"礼物\s+.+?\s*致", message)
        or re.match(r"^(.+?)\s*限制礼物\s*(-?\d+)$", message)
        or re.match(
            r"^(.+?)\s*礼物\s*掉落至(戏群|嘉宾群)，概率\s*([01]\.?\d*|0?\.\d+)$",
            message,
        )
    ):
        match0 = re.match(r"^(.+?)\s*限制礼物\s*(-?\d+)$", message)
        if match0:
            playname = match0.group(1).strip()
            limit_num_str = match0.group(2)
            limit_num = int(limit_num_str)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可设置礼物限额。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            current_group = str(plugin_event.data.group_id)
            if current_group != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置限额。")
                return
            limit_data = getData("sendmessage", "limit.json")
            if limit_num == -1:
                if playname in limit_data and "gift" in limit_data[playname]:
                    del limit_data[playname]["gift"]
                    if not limit_data[playname]:
                        del limit_data[playname]
                    setData("sendmessage", "limit.json", limit_data)
                    plugin_event.reply(
                        f"已移除恋综「{playname}」的礼物限制，即不限制数量。"
                    )
                else:
                    plugin_event.reply(f"恋综「{playname}」没有礼物限制，无需移除。")
                return
            if limit_num < 0:
                plugin_event.reply("限制数量仅可为正数或0，或使用-1表示不限制数量。")
                return
            if playname not in limit_data:
                limit_data[playname] = {}
            limit_data[playname]["gift"] = limit_num
            setData("sendmessage", "limit.json", limit_data)
            plugin_event.reply(
                f"已设置恋综「{playname}」的礼物限额为每天{limit_num}份。"
            )
            return
        match2 = re.match(
            r"^(.+?)\s*礼物\s*掉落至(戏群|嘉宾群)，概率\s*([01]\.?\d*|0?\.\d+)$",
            message,
        )
        if match2:
            playname = match2.group(1).strip()
            drop_to = match2.group(2).strip()
            probability_str = match2.group(3)
            probability = float(probability_str)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可设置礼物掉落概率。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置礼物掉落。")
                return
            if probability < 0 or probability > 1:
                plugin_event.reply(
                    "概率值必须在0到1之间，请重新设置。\n\n概率为0时不掉落礼物，概率为1时所有礼物都将掉落。"
                )
                return
            limit_data = getData("sendmessage", "limit.json")
            if probability == 0:
                _clear_drop_rules(limit_data, playname, "礼物")
                setData("sendmessage", "limit.json", limit_data)
                plugin_event.reply(f"已关闭恋综「{playname}」的礼物掉落功能。")
                return
            target_type = "play_group" if drop_to == "戏群" else "random_guest_group"
            _set_drop_rules(
                limit_data,
                playname,
                "礼物",
                [{"target": target_type, "probability": probability}],
            )
            setData("sendmessage", "limit.json", limit_data)
            if probability == 1:
                probability_display = "100%"
            else:
                probability_display = f"{probability*100}%"
            drop_target = "戏群" if drop_to == "戏群" else "随机嘉宾的个人群"
            plugin_event.reply(
                f"已开启恋综「{playname}」的礼物掉落功能，概率为{probability_display}，掉落到{drop_target}。"
            )
            return
        if not (
            re.search(r"致\s*.+?\s*礼物", message)
            or re.search(r"礼物\s+.+?\s*致", message)
        ):
            return
        gifts = getData("sendmessage", "gifts.json")
        if re.search(r"\[(OP|CQ):image,.+\]", message):
            image = re.search(r"\[(OP|CQ):image,.+\]", message).group(0)
            message = message.replace(image, "")
        else:
            image = ""
        from datetime import datetime

        match1 = re.match(
            r"(.+?)\s+礼物\s+(.+?)\s*致\s*(.+?)\s*内容：\s*([\s\S]+?)\s*署名：\s*([\s\S]+)",
            message,
        )
        if match1:
            playname = match1.group(1).strip()
            now = datetime.now()
            date = now.strftime("%y%m%d")
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            if date in real_to_virtual:
                virtual_day = real_to_virtual[date]
                day_display = f"D{virtual_day}"
            else:
                virtual_day = None
                day_display = "今日"
            content = match1.group(4).strip()
            signature = match1.group(5).strip() + image
            if not content or not signature:
                plugin_event.reply("内容或署名不可为空噢！可为符号或假名。")
                return
            url_pattern = re.compile(r"https?://\S+")
            if url_pattern.search(content):
                plugin_event.reply(
                    "为避免风险检测，内容中不建议包含网页链接，请重新输入噢！\n如为图片，请插在消息末尾"
                )
                return
            sender = str(uid)
            recver = match1.group(3).strip()
            privategroup = getData("groupcollection", "privategroup.json")
            if not re.match(r"^\d+$", recver):
                if playname in privategroup:
                    found = False
                    for guest_uid, guest_info in privategroup[playname].items():
                        if guest_info.get("嘉宾姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                        if guest_info.get("NPC姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                    if not found:
                        plugin_event.reply(
                            "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                        )
                        return
            if not re.match(r"^\d+$", recver):
                plugin_event.reply(
                    "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                )
                return
            if playname not in privategroup or uid not in privategroup[playname]:
                sender = plugin_event.data.sender["name"]
                plugin_event.reply(f"{sender}不是该恋综的嘉宾或NPC，无法赠送礼物噢！")
                return
            limit_data = getData("sendmessage", "limit.json")
            current_count = 0
            for key in gifts.keys():
                parts = key.split("/////")
                if len(parts) >= 5:
                    key_playname = parts[0]
                    key_date = parts[1]
                    key_sender = parts[2]
                    if key_playname == playname and key_sender == uid:
                        if virtual_day is not None:
                            if (
                                key_date in real_to_virtual
                                and real_to_virtual[key_date] == virtual_day
                            ):
                                current_count += 1
                        else:
                            if key_date == date:
                                current_count += 1
            daily_limit = None
            if playname in limit_data and "gift" in limit_data[playname]:
                daily_limit = limit_data[playname]["gift"]
            if daily_limit is not None:
                if current_count >= daily_limit:
                    plugin_event.reply(
                        f"{day_display}已赠送{current_count}份礼物啦！已达到每日限额{daily_limit}份，无法继续赠送。"
                    )
                    return
            leaked = False
            key = (
                playname
                + "/////"
                + date
                + "/////"
                + sender
                + "/////"
                + recver
                + "/////"
                + signature
                + "/////"
                + now.strftime("%H:%M:%S")
            )
            gifts[key] = content
            setData("sendmessage", "gifts.json", gifts)
            reply_message = "礼物送好啦！"
            if daily_limit is not None:
                reply_message += (
                    f"{day_display}已赠送{current_count + 1}/{daily_limit}份。"
                )
            else:
                reply_message += f"{day_display}已赠送{current_count + 1}份。"
            leaked, drop_message = _handle_drop(
                plugin_event,
                limit_data,
                playname,
                "礼物",
                sender,
                recver,
                content,
                signature,
            )
            reply_message += drop_message
            plugin_event.reply(reply_message)
            if not leaked:
                if playname in privategroup and recver in privategroup[playname]:
                    guest_info = privategroup[playname][recver]
                    guest_name = ""
                    group_id = ""
                    if "嘉宾姓名" in guest_info:
                        guest_name = guest_info["嘉宾姓名"]
                        group_id = guest_info.get("个人群号", "")
                    elif "NPC姓名" in guest_info:
                        guest_name = guest_info["NPC姓名"]
                        group_id = guest_info.get(
                            "NPC群号", guest_info.get("个人群号", "")
                        )
                    if not guest_name:
                        guest_name = recver
                    if group_id:
                        plugin_event.send(
                            "group",
                            group_id,
                            playname
                            + " 礼物\n致 "
                            + guest_name
                            + "\n内容："
                            + content
                            + "\n署名："
                            + signature,
                        )
                    else:
                        plugin_event.send(
                            "private",
                            recver,
                            playname
                            + " 礼物\n致 "
                            + guest_name
                            + "\n内容："
                            + content
                            + "\n署名："
                            + signature,
                        )
                else:
                    plugin_event.send(
                        "private",
                        recver,
                        playname
                        + " 礼物\n致 "
                        + recver
                        + "\n内容："
                        + content
                        + "\n署名："
                        + signature,
                    )
            return
        elif not "小纸条" in message and not "短信" in message:
            return
    elif (
        re.search(r"致\s*.+?\s*小纸条", message)
        or re.search(r"小纸条\s+.+?\s*致", message)
        or re.match(r"^(.+?)\s*限制小纸条\s*(-?\d+)$", message)
        or re.match(
            r"^(.+?)\s*小纸条\s*掉落至(戏群|嘉宾群)，概率\s*([01]\.?\d*|0?\.\d+)$",
            message,
        )
    ):
        match0 = re.match(r"^(.+?)\s*限制小纸条\s*(-?\d+)$", message)
        if match0:
            playname = match0.group(1).strip()
            limit_num_str = match0.group(2)
            limit_num = int(limit_num_str)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可设置小纸条限额。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            current_group = str(plugin_event.data.group_id)
            if current_group != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置限额。")
                return
            limit_data = getData("sendmessage", "limit.json")
            if limit_num == -1:
                if playname in limit_data and "note" in limit_data[playname]:
                    del limit_data[playname]["note"]
                    if not limit_data[playname]:
                        del limit_data[playname]
                    setData("sendmessage", "limit.json", limit_data)
                    plugin_event.reply(
                        f"已移除恋综「{playname}」的小纸条限制，即不限制数量。"
                    )
                else:
                    plugin_event.reply(f"恋综「{playname}」没有小纸条限制，无需移除。")
                return
            if limit_num < 0:
                plugin_event.reply("限制数量仅可为正数或0，或使用-1表示不限制数量。")
                return
            if playname not in limit_data:
                limit_data[playname] = {}
            limit_data[playname]["note"] = limit_num
            setData("sendmessage", "limit.json", limit_data)
            plugin_event.reply(
                f"已设置恋综「{playname}」的小纸条限额为每天{limit_num}份。"
            )
            return
        match2 = re.match(
            r"^(.+?)\s*小纸条\s*掉落至(戏群|嘉宾群)，概率\s*([01]\.?\d*|0?\.\d+)$",
            message,
        )
        if match2:
            playname = match2.group(1).strip()
            drop_to = match2.group(2).strip()
            probability_str = match2.group(3)
            probability = float(probability_str)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可设置小纸条掉落概率。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置小纸条掉落。")
                return
            if probability < 0 or probability > 1:
                plugin_event.reply(
                    "概率值必须在0到1之间，请重新设置。\n\n概率为0时不掉落小纸条，概率为1时所有小纸条都将掉落。"
                )
                return
            limit_data = getData("sendmessage", "limit.json")
            if probability == 0:
                _clear_drop_rules(limit_data, playname, "小纸条")
                setData("sendmessage", "limit.json", limit_data)
                plugin_event.reply(f"已关闭恋综「{playname}」的小纸条掉落功能。")
                return
            target_type = "play_group" if drop_to == "戏群" else "random_guest_group"
            _set_drop_rules(
                limit_data,
                playname,
                "小纸条",
                [{"target": target_type, "probability": probability}],
            )
            setData("sendmessage", "limit.json", limit_data)
            if probability == 1:
                probability_display = "100%"
            else:
                probability_display = f"{probability*100}%"
            drop_target = "戏群" if drop_to == "戏群" else "随机嘉宾的个人群"
            plugin_event.reply(
                f"已开启恋综「{playname}」的小纸条掉落功能，概率为{probability_display}，掉落到{drop_target}。"
            )
            return
        if not (
            re.search(r"致\s*.+?\s*小纸条", message)
            or re.search(r"小纸条\s+.+?\s*致", message)
        ):
            return
        notes = getData("sendmessage", "notes.json")
        if re.search(r"\[(OP|CQ):image,.+\]", message):
            image = re.search(r"\[(OP|CQ):image,.+\]", message).group(0)
            message = message.replace(image, "")
        else:
            image = ""
        from datetime import datetime

        match1 = re.match(
            r"(.+?)\s+小纸条\s+(.+?)\s*致\s*(.+?)\s*内容：\s*([\s\S]+?)\s*署名：\s*([\s\S]+)",
            message,
        )
        if match1:
            playname = match1.group(1).strip()
            now = datetime.now()
            date = now.strftime("%y%m%d")
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            if date in real_to_virtual:
                virtual_day = real_to_virtual[date]
                day_display = f"D{virtual_day}"
            else:
                virtual_day = None
                day_display = "今日"
            content = match1.group(4).strip()
            signature = match1.group(5).strip() + image
            if not content or not signature:
                plugin_event.reply("内容或署名不可为空噢！可为符号或假名。")
                return
            url_pattern = re.compile(r"https?://\S+")
            if url_pattern.search(content):
                plugin_event.reply(
                    "为避免风险检测，内容中不建议包含网页链接，请重新输入噢！\n如为图片，请插在消息末尾"
                )
                return
            sender = str(uid)
            recver = match1.group(3).strip()
            privategroup = getData("groupcollection", "privategroup.json")
            if not re.match(r"^\d+$", recver):
                if playname in privategroup:
                    found = False
                    for guest_uid, guest_info in privategroup[playname].items():
                        if guest_info.get("嘉宾姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                        if guest_info.get("NPC姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                    if not found:
                        plugin_event.reply(
                            "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                        )
                        return
            if not re.match(r"^\d+$", recver):
                plugin_event.reply(
                    "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                )
                return
            if playname not in privategroup or uid not in privategroup[playname]:
                sender = plugin_event.data.sender["name"]
                plugin_event.reply(f"{sender}不是该恋综的嘉宾或NPC，无法发送小纸条噢！")
                return
            limit_data = getData("sendmessage", "limit.json")
            current_count = 0
            for key in notes.keys():
                parts = key.split("/////")
                if len(parts) >= 5:
                    key_playname = parts[0]
                    key_date = parts[1]
                    key_sender = parts[2]
                    if key_playname == playname and key_sender == uid:
                        if virtual_day is not None:
                            if (
                                key_date in real_to_virtual
                                and real_to_virtual[key_date] == virtual_day
                            ):
                                current_count += 1
                        else:
                            if key_date == date:
                                current_count += 1
            daily_limit = None
            if playname in limit_data and "note" in limit_data[playname]:
                daily_limit = limit_data[playname]["note"]
            if daily_limit is not None:
                if current_count >= daily_limit:
                    plugin_event.reply(
                        f"{day_display}已发送{current_count}份小纸条啦！已达到每日限额{daily_limit}份，无法继续发送。"
                    )
                    return
            leaked = False
            key = (
                playname
                + "/////"
                + date
                + "/////"
                + sender
                + "/////"
                + recver
                + "/////"
                + signature
                + "/////"
                + now.strftime("%H:%M:%S")
            )
            notes[key] = content
            setData("sendmessage", "notes.json", notes)
            reply_message = "小纸条送好啦！"
            if daily_limit is not None:
                if virtual_day is not None:
                    reply_message += (
                        f"{day_display}已发送{current_count + 1}/{daily_limit}份。"
                    )
                else:
                    reply_message += f"今日已发送{current_count + 1}/{daily_limit}份。"
            else:
                if virtual_day is not None:
                    reply_message += f"{day_display}已发送{current_count + 1}份。"
                else:
                    reply_message += f"今日已发送{current_count + 1}份。"
            leaked, drop_message = _handle_drop(
                plugin_event,
                limit_data,
                playname,
                "小纸条",
                sender,
                recver,
                content,
                signature,
            )
            reply_message += drop_message
            plugin_event.reply(reply_message)
            if not leaked:
                if playname in privategroup and recver in privategroup[playname]:
                    guest_info = privategroup[playname][recver]
                    guest_name = ""
                    group_id = ""
                    if "嘉宾姓名" in guest_info:
                        guest_name = guest_info["嘉宾姓名"]
                        group_id = guest_info.get("个人群号", "")
                    elif "NPC姓名" in guest_info:
                        guest_name = guest_info["NPC姓名"]
                        group_id = guest_info.get(
                            "NPC群号", guest_info.get("个人群号", "")
                        )
                    if not guest_name:
                        guest_name = recver
                    if group_id:
                        plugin_event.send(
                            "group",
                            group_id,
                            playname
                            + " 小纸条\n致 "
                            + guest_name
                            + "\n内容："
                            + content
                            + "\n署名："
                            + signature,
                        )
                    else:
                        plugin_event.send(
                            "private",
                            recver,
                            playname
                            + " 小纸条\n致 "
                            + guest_name
                            + "\n内容："
                            + content
                            + "\n署名："
                            + signature,
                        )
                else:
                    plugin_event.send(
                        "private",
                        recver,
                        playname
                        + " 小纸条\n致 "
                        + recver
                        + "\n内容："
                        + content
                        + "\n署名："
                        + signature,
                    )
            return
        elif not "短信" in message:
            return
    elif (
        re.search(r"致\s*.+?\s*短信", message)
        or re.search(r"短信\s+.+?\s*致", message)
        or re.match(r"^(.+?)\s*限制短信\s*(-?\d+)$", message)
        or re.match(
            r"^(.+?)\s*短信\s*掉落至(戏群|嘉宾群)，概率\s*([01]\.?\d*|0?\.\d+)$",
            message,
        )
    ):
        match0 = re.match(r"^(.+?)\s*限制短信\s*(-?\d+)$", message)
        if match0:
            playname = match0.group(1).strip()
            limit_num_str = match0.group(2)
            limit_num = int(limit_num_str)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可设置短信限额。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            current_group = str(plugin_event.data.group_id)
            if current_group != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置限额。")
                return
            limit_data = getData("sendmessage", "limit.json")
            if limit_num == -1:
                if playname in limit_data and "sms" in limit_data[playname]:
                    del limit_data[playname]["sms"]
                    if not limit_data[playname]:
                        del limit_data[playname]
                    setData("sendmessage", "limit.json", limit_data)
                    plugin_event.reply(
                        f"已移除恋综「{playname}」的短信限制，即不限制数量。"
                    )
                else:
                    plugin_event.reply(f"恋综「{playname}」没有短信限制，无需移除。")
                return
            if limit_num < 0:
                plugin_event.reply("限制数量仅可为正数或0，或使用-1表示不限制数量。")
                return
            if playname not in limit_data:
                limit_data[playname] = {}
            limit_data[playname]["sms"] = limit_num
            setData("sendmessage", "limit.json", limit_data)
            plugin_event.reply(
                f"已设置恋综「{playname}」的短信限额为每天{limit_num}份。"
            )
            return
        match2 = re.match(
            r"^(.+?)\s*短信\s*掉落至(戏群|嘉宾群)，概率\s*([01]\.?\d*|0?\.\d+)$",
            message,
        )
        if match2:
            playname = match2.group(1).strip()
            drop_to = match2.group(2).strip()
            probability_str = match2.group(3)
            probability = float(probability_str)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可设置短信掉落概率。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置短信掉落。")
                return
            if probability < 0 or probability > 1:
                plugin_event.reply(
                    "概率值必须在0到1之间，请重新设置。\n\n概率为0时不掉落短信，概率为1时所有短信都将掉落。"
                )
                return
            limit_data = getData("sendmessage", "limit.json")
            if probability == 0:
                _clear_drop_rules(limit_data, playname, "短信")
                setData("sendmessage", "limit.json", limit_data)
                plugin_event.reply(f"已关闭恋综「{playname}」的短信掉落功能。")
                return
            target_type = "play_group" if drop_to == "戏群" else "random_guest_group"
            _set_drop_rules(
                limit_data,
                playname,
                "短信",
                [{"target": target_type, "probability": probability}],
            )
            setData("sendmessage", "limit.json", limit_data)
            if probability == 1:
                probability_display = "100%"
            else:
                probability_display = f"{probability*100}%"
            drop_target = "戏群" if drop_to == "戏群" else "随机嘉宾的个人群"
            plugin_event.reply(
                f"已开启恋综「{playname}」的短信掉落功能，概率为{probability_display}，掉落到{drop_target}。"
            )
            return
        if not (
            re.search(r"致\s*.+?\s*短信", message)
            or re.search(r"短信\s+.+?\s*致", message)
        ):
            return
        sms = getData("sendmessage", "sms.json")
        if re.search(r"\[(OP|CQ):image,.+\]", message):
            image = re.search(r"\[(OP|CQ):image,.+\]", message).group(0)
            message = message.replace(image, "")
        else:
            image = ""
        from datetime import datetime

        match1 = re.match(
            r"(.+?)\s+短信\s+(.+?)\s*致\s*(.+?)\s*内容：\s*([\s\S]+?)\s*署名：\s*([\s\S]+)",
            message,
        )
        if match1:
            playname = match1.group(1).strip()
            now = datetime.now()
            date = now.strftime("%y%m%d")
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            if date in real_to_virtual:
                virtual_day = real_to_virtual[date]
                day_display = f"D{virtual_day}"
            else:
                virtual_day = None
                day_display = "今日"
            content = match1.group(4).strip()
            signature = match1.group(5).strip() + image
            if not content or not signature:
                plugin_event.reply("内容或署名不可为空噢！可为符号或假名。")
                return
            url_pattern = re.compile(r"https?://\S+")
            if url_pattern.search(content):
                plugin_event.reply(
                    "为避免风险检测，内容中不建议包含网页链接，请重新输入噢！\n如为图片，请插在消息末尾"
                )
                return
            sender = str(uid)
            recver = match1.group(3).strip()
            privategroup = getData("groupcollection", "privategroup.json")
            if not re.match(r"^\d+$", recver):
                if playname in privategroup:
                    found = False
                    for guest_uid, guest_info in privategroup[playname].items():
                        if guest_info.get("嘉宾姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                        if guest_info.get("NPC姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                    if not found:
                        plugin_event.reply(
                            "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                        )
                        return
            if not re.match(r"^\d+$", recver):
                plugin_event.reply(
                    "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                )
                return
            if playname not in privategroup or uid not in privategroup[playname]:
                sender = plugin_event.data.sender["name"]
                plugin_event.reply(f"{sender}不是该恋综的嘉宾或NPC，无法发送短信噢！")
                return
            limit_data = getData("sendmessage", "limit.json")
            current_count = 0
            for key in sms.keys():
                parts = key.split("/////")
                if len(parts) >= 5:
                    key_playname = parts[0]
                    key_date = parts[1]
                    key_sender = parts[2]
                    if key_playname == playname and key_sender == uid:
                        if virtual_day is not None:
                            if (
                                key_date in real_to_virtual
                                and real_to_virtual[key_date] == virtual_day
                            ):
                                current_count += 1
                        else:
                            if key_date == date:
                                current_count += 1
            daily_limit = None
            if playname in limit_data and "sms" in limit_data[playname]:
                daily_limit = limit_data[playname]["sms"]
            if daily_limit is not None:
                if current_count >= daily_limit:
                    plugin_event.reply(
                        f"{day_display}已发送{current_count}份短信啦！已达到每日限额{daily_limit}份，无法继续发送。"
                    )
                    return
            leaked = False
            key = (
                playname
                + "/////"
                + date
                + "/////"
                + sender
                + "/////"
                + recver
                + "/////"
                + signature
                + "/////"
                + now.strftime("%H:%M:%S")
            )
            sms[key] = content
            setData("sendmessage", "sms.json", sms)
            reply_message = "短信送好啦！"
            if daily_limit is not None:
                reply_message += (
                    f"{day_display}已发送{current_count + 1}/{daily_limit}份。"
                )
            else:
                reply_message += f"{day_display}已发送{current_count + 1}份。"
            leaked, drop_message = _handle_drop(
                plugin_event,
                limit_data,
                playname,
                "短信",
                sender,
                recver,
                content,
                signature,
            )
            reply_message += drop_message
            plugin_event.reply(reply_message)
            if not leaked:
                if playname in privategroup and recver in privategroup[playname]:
                    guest_info = privategroup[playname][recver]
                    guest_name = ""
                    group_id = ""
                    if "嘉宾姓名" in guest_info:
                        guest_name = guest_info["嘉宾姓名"]
                        group_id = guest_info.get("个人群号", "")
                    elif "NPC姓名" in guest_info:
                        guest_name = guest_info["NPC姓名"]
                        group_id = guest_info.get(
                            "NPC群号", guest_info.get("个人群号", "")
                        )
                    if not guest_name:
                        guest_name = recver
                    if group_id:
                        plugin_event.send(
                            "group",
                            group_id,
                            playname
                            + " 短信\n致 "
                            + guest_name
                            + "\n内容："
                            + content
                            + "\n署名："
                            + signature,
                        )
                    else:
                        plugin_event.send(
                            "private",
                            recver,
                            playname
                            + " 短信\n致 "
                            + guest_name
                            + "\n内容："
                            + content
                            + "\n署名："
                            + signature,
                        )
                else:
                    plugin_event.send(
                        "private",
                        recver,
                        playname
                        + " 短信\n致 "
                        + recver
                        + "\n内容："
                        + content
                        + "\n署名："
                        + signature,
                    )
            return
        else:
            return
    elif (
        message.startswith("发起前置电话 ")
        or message.strip() == "发起前置电话"
        or message.startswith("【前置电话设置·")
        or message.startswith("【前置电话选择】")
        or message.strip() == "前置电话选择"
        or message.startswith("查看前置电话选择 ")
        or message.strip() == "查看前置电话选择"
        or message.startswith("拉取前置电话 ")
        or message.strip() == "拉取前置电话"
        or message.startswith("发起官约 ")
        or message.strip() == "发起官约"
        or message.startswith("发起双选官约 ")
        or message.strip() == "发起双选官约"
        or message.startswith("【官约设置·")
        or message.startswith("【官约选择】")
        or message.strip() == "官约选择"
        or message.startswith("查看官约选择 ")
        or message.strip() == "查看官约选择"
        or message.startswith("拉取官约 ")
        or message.strip() == "拉取官约"
        or message.startswith("拉取双选官约 ")
        or message.strip() == "拉取双选官约"
        or message.startswith("拉取异性随机官约 ")
        or message.strip() == "拉取异性随机官约"
        or message.startswith("拉取随机官约 ")
        or message.strip() == "拉取随机官约"
        or message.startswith("录入嘉宾性别")
        or message.startswith("【嘉宾性别·")
    ):
        from AmourGame.engagement import phone

        phone(
            plugin_event,
            Proc,
            message,
            uid,
            groupid,
            sender,
            getData,
            setData,
            getMaster,
            checkgrouptime,
            check_virtual_date,
            amourlock,
        )
        return
    elif re.match(r"<.+·\s*(私约|电话|前置电话|官约|微信)>", message) or message == "创建预约":
        from AmourGame.engagement import open_engagement
        open_engagement(
            plugin_event,
            Proc,
            message,
            uid,
            groupid,
            sender,
            getData,
            setData,
            checkgrouptime,
            check_virtual_date,
            amourlock,
        )
        return

    elif re.match(r"拒绝(私约|电话|前置电话|官约|微信)\s*\d{8}", message):
        playtype = re.match(r"拒绝(私约|电话|前置电话|官约|微信)\s*(\d{8})", message).group(1)
        code = re.match(r"拒绝(私约|电话|前置电话|官约|微信)\s*(\d{8})", message).group(2)
        appoint = getData("engagement", "appoint.json")
        if code not in appoint:
            plugin_event.reply(f"该{playtype}编号不存在，请检查是否输入正确噢！")
            return
        if playtype != appoint[code].get("playtype"):
            plugin_event.reply(
                f"该{playtype}编号类型不是{playtype}，请检查是否输入正确噢！"
            )
            return
        playname = appoint[code].get("playname")
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            plugin_event.reply(f"该{playtype}编号对应的恋综未注册或已注销，请检查噢！")
            return
        inviter = appoint[code].get("inviter")
        invitee = appoint[code].get("invitee")
        playplace = appoint[code].get("playplace")
        if uid == inviter:
            plugin_event.reply(
                f"你是该{playtype}编号{code}的发起者，无法拒绝，请检查是否输入正确噢！"
            )
            return
        if uid not in invitee:
            plugin_event.reply(
                f"该{playtype}编号{code}中没有你的信息，请检查是否输入正确噢！"
            )
            return
        group = appoint[code].get("group")
        playtime = appoint[code].get("playtime")
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查噢！")
            return
        play_method = register[playname].get("play_method", "二维码")
        usertime = getData("engagement", "usertime.json")
        if playname not in usertime:
            usertime[playname] = {}
        invitee.remove(uid)
        rejecter_data = privategroup[playname][uid]
        if "NPC姓名" in rejecter_data:
            rejecter_name = rejecter_data.get("NPC姓名", uid)
        else:
            rejecter_name = rejecter_data.get("嘉宾姓名", uid)
        if invitee:  # 如果还有受邀者
            send_count = 0
            for invitee_uid in invitee:
                if invitee_uid not in privategroup[playname]:
                    continue
                user_data = privategroup[playname][invitee_uid]
                if "NPC姓名" in user_data:
                    invitee_name = user_data.get("NPC姓名", invitee_uid)
                    invitee_groupid = user_data.get("NPC群号")
                else:
                    invitee_name = user_data.get("嘉宾姓名", invitee_uid)
                    invitee_groupid = user_data.get("个人群号")
                if invitee_groupid:
                    if send_count >= 2:
                        time.sleep(1)
                    plugin_event.send(
                        "group",
                        invitee_groupid,
                        f"【通知】\n"
                        f"{rejecter_name}拒绝了{playtype}编号{code}。\n"
                        f"目前还有{len(invitee)}位受邀者。",
                    )
                    send_count += 1
        date_part = None
        time_range = None
        if playtype != "微信":
            timeline = getData("engagement", "timeline.json")
            playtime_parts = playtime.split()
            date_part = playtime_parts[0]
            time_range = playtime_parts[1]

            def get_timeline_key(day_data):
                replay_key = f"{time_range}#{code}"
                if replay_key in day_data:
                    return replay_key
                if time_range in day_data:
                    return time_range
                return None

            def has_time_occupation(user_id):
                if playname not in timeline or user_id not in timeline[playname]:
                    return False
                if date_part not in timeline[playname][user_id]:
                    return False
                return any(
                    time_key.split("#", 1)[0] == time_range
                    for time_key in timeline[playname][user_id][date_part]
                )

            def remove_usertime_if_free(user_id):
                if has_time_occupation(user_id):
                    return
                remove_usertime_interval(usertime, playname, user_id, playtime)

            if playname in timeline and uid in timeline[playname]:
                if date_part in timeline[playname][uid]:
                    timeline_key = get_timeline_key(timeline[playname][uid][date_part])
                    if timeline_key:
                        del timeline[playname][uid][date_part][timeline_key]
                        if not timeline[playname][uid][date_part]:
                            del timeline[playname][uid][date_part]
                        if not timeline[playname][uid]:
                            del timeline[playname][uid]
            remove_usertime_if_free(uid)
            if playname in timeline:
                participants = []
                if inviter != "官方" and inviter.isdigit():
                    participants.append(inviter)
                participants.extend(invitee)
                for participant in participants:
                    if participant in timeline[playname]:
                        if date_part in timeline[playname][participant]:
                            timeline_key = get_timeline_key(
                                timeline[playname][participant][date_part]
                            )
                            if timeline_key:
                                if (
                                    uid
                                    in timeline[playname][participant][date_part][
                                        timeline_key
                                    ]["participants"]
                                ):
                                    timeline[playname][participant][date_part][
                                        timeline_key
                                    ]["participants"].remove(uid)
            setData("engagement", "timeline.json", timeline)
        if len(invitee) == 0:
            if playtype != "微信" and inviter != "官方" and inviter.isdigit():
                if date_part and time_range:
                    timeline = getData("engagement", "timeline.json")
                    if playname in timeline and inviter in timeline[playname]:
                        if date_part in timeline[playname][inviter]:
                            timeline_key = get_timeline_key(
                                timeline[playname][inviter][date_part]
                            )
                            if timeline_key:
                                del timeline[playname][inviter][date_part][timeline_key]
                                if not timeline[playname][inviter][date_part]:
                                    del timeline[playname][inviter][date_part]
                                if not timeline[playname][inviter]:
                                    del timeline[playname][inviter]
                    remove_usertime_if_free(inviter)
                    setData("engagement", "timeline.json", timeline)
            del appoint[code]
            setData("engagement", "appoint.json", appoint)
            cleanup_monitor_session(group, code)
            if playtype != "微信":
                setData("engagement", "usertime.json", usertime)
            else:
                pass
            if play_method == "二维码":
                with amourlock:
                    playname_path = f"./data/images/恋综备用群/二维码/{playname}"
                    default_path = "./data/images/恋综备用群/二维码/默认池"
                    if os.path.exists(playname_path) and os.path.isdir(playname_path):
                        group_path = playname_path
                    else:
                        group_path = default_path
                    if group.isdigit():
                        mapping_file = os.path.join(
                            group_path, "二维码与群号对应组.json"
                        )
                        original_name = None
                        if os.path.exists(mapping_file):
                            try:
                                with open(mapping_file, "r", encoding="utf-8") as f:
                                    mapping_data = json.load(f)
                                for key, value in mapping_data.items():
                                    if str(value) == group:
                                        original_name = key
                                        break
                            except Exception as e:
                                plugin_event.reply(f"二维码释放失败：{str(e)}")
                        if original_name:
                            old_file_name = f"已占用_{original_name}"
                            old_file_path = os.path.join(group_path, old_file_name)
                            if not os.path.exists(old_file_path):
                                possible_extensions = [
                                    ".jpg",
                                    ".jpeg",
                                    ".png",
                                    ".gif",
                                    ".bmp",
                                ]
                                for ext in possible_extensions:
                                    old_file_path_with_ext = os.path.join(
                                        group_path, f"{old_file_name}{ext}"
                                    )
                                    if os.path.exists(old_file_path_with_ext):
                                        old_file_path = old_file_path_with_ext
                                        new_file_path = os.path.join(
                                            group_path, f"{original_name}{ext}"
                                        )
                                        break
                            else:
                                new_file_path = os.path.join(group_path, original_name)
                            try:
                                if os.path.exists(old_file_path):
                                    os.rename(old_file_path, new_file_path)
                            except OSError as e:
                                plugin_event.reply(f"二维码释放失败：{str(e)}")
                    else:
                        if group.startswith("已占用_"):
                            original_name = group.replace("已占用_", "")
                            old_file_path = os.path.join(group_path, group)
                            new_file_path = os.path.join(group_path, original_name)
                            try:
                                if os.path.exists(old_file_path):
                                    os.rename(old_file_path, new_file_path)
                            except OSError as e:
                                plugin_event.reply(f"二维码释放失败：{str(e)}")
            elif play_method == "群号":
                with amourlock:
                    playname_file = f"./data/images/恋综备用群/群号/{playname}.json"
                    default_file = "./data/images/恋综备用群/群号/默认池.json"
                    if os.path.exists(playname_file):
                        group_file = playname_file
                    elif os.path.exists(default_file):
                        group_file = default_file
                    else:
                        pass
                    try:
                        with open(group_file, "r", encoding="utf-8") as f:
                            group_data = json.load(f)
                    except Exception as e:
                        pass
                    if group in group_data:
                        group_data[group]["使用情况"] = False
                        try:
                            with open(group_file, "w", encoding="utf-8") as f:
                                json.dump(group_data, f, ensure_ascii=False, indent=2)
                        except Exception as e:
                            pass
            plugin_event.reply(
                f"已经拒绝{playtype}编号{code}啦！由于没有其他受邀者，该预约已取消，时段已释放。"
            )
            if (
                inviter != "官方"
                and inviter.isdigit()
                and inviter in privategroup[playname]
            ):
                user_data = privategroup[playname][inviter]
                if "NPC姓名" in user_data:
                    inviter_name = user_data.get("NPC姓名", inviter)
                    inviter_group = user_data.get("NPC群号")
                else:
                    inviter_name = user_data.get("嘉宾姓名", inviter)
                    inviter_group = user_data.get("个人群号")
                rejecter_data = privategroup[playname][uid]
                if "NPC姓名" in rejecter_data:
                    rejecter_name = rejecter_data.get("NPC姓名", uid)
                else:
                    rejecter_name = rejecter_data.get("嘉宾姓名", uid)
                if inviter_group:
                    plugin_event.send(
                        "group",
                        inviter_group,
                        f"{rejecter_name}拒绝了{playtype}编号{code}，由于没有邀请其他嘉宾，该预约已作废，该时段已释放，QAQ",
                    )
            return
        appoint[code]["invitee"] = invitee
        setData("engagement", "appoint.json", appoint)
        if playtype != "微信":
            setData("engagement", "usertime.json", usertime)
        with amourlock:
            playlog = []
            playlog_path = f"./data/amourgame/engagement/{code}.json"
            if os.path.exists(playlog_path):
                try:
                    with open(playlog_path, "r", encoding="utf-8") as f:
                        playlog = json.load(f)
                except:
                    playlog = []
        rejecter_data = privategroup[playname][uid]
        if "NPC姓名" in rejecter_data:
            rejecter_name = rejecter_data.get("NPC姓名", uid)
        else:
            rejecter_name = rejecter_data.get("嘉宾姓名", uid)
        playlog.append(f"{rejecter_name}已拒绝")
        try:
            with open(playlog_path, "w", encoding="utf-8") as f:
                json.dump(playlog, f, ensure_ascii=False, indent=2)
        except Exception as e:
            pass
        plugin_event.reply(f"已经拒绝{playtype}编号{code}啦！")
        if (
            inviter != "官方"
            and inviter.isdigit()
            and inviter in privategroup[playname]
        ):
            user_data = privategroup[playname][inviter]
            if "NPC姓名" in user_data:
                inviter_name = user_data.get("NPC姓名", inviter)
                inviter_group = user_data.get("NPC群号")
            else:
                inviter_name = user_data.get("嘉宾姓名", inviter)
                inviter_group = user_data.get("个人群号")
            if inviter_group:
                plugin_event.send(
                    "group",
                    inviter_group,
                    f"{rejecter_name}拒绝了{playtype}编号{code}，QAQ\n正在通知剩余的受邀者。",
                )

    elif re.match(r"更改群名\s*\d{8}", message):
        code = re.match(r"更改群名\s*(\d{8})", message).group(1)
        appoint = getData("engagement", "appoint.json")
        if code not in appoint:
            plugin_event.reply(f"该编号不存在，请检查是否输入正确噢！")
            return
        inviter = appoint[code].get("inviter")
        invitee = appoint[code].get("invitee", [])
        if uid != inviter and uid not in invitee:
            plugin_event.reply(f"该编号{code}中没有你的信息，请检查是否输入正确噢！")
            return
        old_group = str(appoint[code].get("group", ""))
        if old_group != groupid:
            appoint[code]["group"] = groupid
            setData("engagement", "appoint.json", appoint)
            msg_appoint = getData("engagement", "msg_appoint.json")
            old_state = msg_appoint.pop(old_group, {})
            old_state["code"] = code
            old_state["group"] = groupid
            msg_appoint[groupid] = old_state
            setData("engagement", "msg_appoint.json", msg_appoint)
        privategroup = getData("groupcollection", "privategroup.json")
        playname = appoint[code].get("playname")
        playtype = appoint[code].get("playtype")
        inviter = appoint[code].get("inviter")
        invitee = appoint[code].get("invitee")
        playtime = appoint[code].get("playtime")
        playplace = appoint[code].get("playplace")
        if playtype == "官约":
            groupname = f"{playname} {playtype} {playtime.split(' ')[0]}"
            if invitee:
                first_invitee = True
                for i in invitee:
                    user_info = privategroup.get(playname, {}).get(i, {})
                    display_name = (
                        user_info.get("嘉宾姓名")
                        or user_info.get("NPC姓名")
                        or f"用户{i}"
                    )
                    if first_invitee:
                        groupname += f" {display_name}"
                        first_invitee = False
                    else:
                        groupname += f"x{display_name}"
        else:
            inviter_info = privategroup.get(playname, {}).get(inviter, {})
            inviter_display_name = (
                inviter_info.get("嘉宾姓名")
                or inviter_info.get("NPC姓名")
                or f"用户{inviter}"
            )
            groupname = (
                f"{playname} {playtype} {playtime.split(' ')[0]} {inviter_display_name}"
            )
            if invitee:
                for i in invitee:
                    user_info = privategroup.get(playname, {}).get(i, {})
                    display_name = (
                        user_info.get("嘉宾姓名")
                        or user_info.get("NPC姓名")
                        or f"用户{i}"
                    )
                    groupname += f"x{display_name}"
        groupname += " " + playtime.split(" ")[1]
        plugin_event.set_group_name(groupid, groupname)
        invitee_names = []
        for i in invitee:
            user_info = privategroup.get(playname, {}).get(i, {})
            display_name = (
                user_info.get("嘉宾姓名") or user_info.get("NPC姓名") or f"用户{i}"
            )
            invitee_names.append(display_name)
        invitee_str = "，".join(invitee_names)
        if playtype == "官约":
            inviter_display = "官方"
        else:
            inviter_info = privategroup.get(playname, {}).get(inviter, {})
            inviter_display = (
                inviter_info.get("嘉宾姓名")
                or inviter_info.get("NPC姓名")
                or f"用户{inviter}"
            )
        plugin_event.reply(
            f"群名更改成功！\n\n<{playname}·{playtype}>\n"
            f"邀请者：{inviter_display}\n"
            f"受邀者：{invitee_str}\n"
            f"时间：{playtime}\n"
            f"地点：{playplace}\n\n"
            f"①如为开错的小群，请不要直接释放，联系管理在后台删除时间线。\n\n"
            f"②结戏可发送「@骰子 复盘」，也可合并转发戏录至本群，引用该消息并附文「@骰子 {playtype}{code}」\n\n"
            f"③自助撤戏指令：引用戏文并附文「@骰子 撤戏」\n\n"
            f"④复盘不合并本条。"
        )

    elif re.match(r"删除(私约|电话|前置电话|心愿|官约|微信)\s*\d{8}", message):
        playtype = re.match(r"删除(私约|电话|前置电话|心愿|官约|微信)\s*(\d{8})", message).group(
            1
        )
        code = re.match(r"删除(私约|电话|前置电话|心愿|官约|微信)\s*(\d{8})", message).group(2)
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主权限可删除。")
            return
        appoint = getData("engagement", "appoint.json")
        if code not in appoint:
            plugin_event.reply(f"该{playtype}编号不存在，请检查是否输入正确噢！")
            return
        real_playtype = appoint[code].get("playtype")
        if playtype != real_playtype:
            plugin_event.reply(f"该预约编号类型不是{playtype}，请检查是否输入正确噢！")
            return
        playname = appoint[code].get("playname")
        inviter = appoint[code].get("inviter")
        invitee = appoint[code].get("invitee", [])
        group = appoint[code].get("group")
        playtime = appoint[code].get("playtime")
        playplace = appoint[code].get("playplace")
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            plugin_event.reply(f"该{playtype}编号对应的恋综未注册或已注销，请检查噢！")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查噢！")
            return
        manage_group = register[playname].get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中删除小群时间线噢！")
            return
        play_method = register[playname].get("play_method", "二维码")
        usertime = getData("engagement", "usertime.json")
        if playtype != "微信":
            timeline = getData("engagement", "timeline.json")
            playtime_parts = playtime.split()
            date_part = playtime_parts[0]
            time_range = playtime_parts[1]

            def has_time_occupation(user_id):
                if playname not in timeline or user_id not in timeline[playname]:
                    return False
                if date_part not in timeline[playname][user_id]:
                    return False
                return any(
                    time_key.split("#", 1)[0] == time_range
                    for time_key in timeline[playname][user_id][date_part]
                )

            def remove_usertime_if_free(user_id):
                if playname not in usertime or user_id not in usertime[playname]:
                    return
                if has_time_occupation(user_id):
                    return
                remove_usertime_interval(usertime, playname, user_id, playtime)

            def delete_timeline_for(user_id):
                if playname not in timeline or user_id not in timeline[playname]:
                    return
                if date_part not in timeline[playname][user_id]:
                    return
                day_data = timeline[playname][user_id][date_part]
                replay_key = f"{time_range}#{code}"
                timeline_key = replay_key if replay_key in day_data else time_range
                if timeline_key not in day_data:
                    return
                del day_data[timeline_key]
                if not day_data:
                    del timeline[playname][user_id][date_part]
                if not timeline[playname][user_id]:
                    del timeline[playname][user_id]

            for uid in invitee:
                delete_timeline_for(uid)
                remove_usertime_if_free(uid)
            if inviter != "官方" and inviter.isdigit():
                delete_timeline_for(inviter)
                remove_usertime_if_free(inviter)
            setData("engagement", "timeline.json", timeline)
        if playtype != "微信":
            setData("engagement", "usertime.json", usertime)
        if play_method == "二维码":
            with amourlock:
                playname_path = f"./data/images/恋综备用群/二维码/{playname}"
                default_path = "./data/images/恋综备用群/二维码/默认池"
                if os.path.exists(playname_path) and os.path.isdir(playname_path):
                    group_path = playname_path
                else:
                    group_path = default_path
                if group.isdigit():
                    mapping_file = os.path.join(group_path, "二维码与群号对应组.json")
                    original_name = None
                    if os.path.exists(mapping_file):
                        try:
                            with open(mapping_file, "r", encoding="utf-8") as f:
                                mapping_data = json.load(f)
                            for key, value in mapping_data.items():
                                if str(value) == group:
                                    original_name = key
                                    break
                        except Exception as e:
                            pass
                    if original_name:
                        old_file_name = f"已占用_{original_name}"
                        old_file_path = os.path.join(group_path, old_file_name)
                        if not os.path.exists(old_file_path):
                            possible_extensions = [
                                ".jpg",
                                ".jpeg",
                                ".png",
                                ".gif",
                                ".bmp",
                            ]
                            for ext in possible_extensions:
                                old_file_path_with_ext = os.path.join(
                                    group_path, f"{old_file_name}{ext}"
                                )
                                if os.path.exists(old_file_path_with_ext):
                                    old_file_path = old_file_path_with_ext
                                    new_file_path = os.path.join(
                                        group_path, f"{original_name}{ext}"
                                    )
                                    break
                        else:
                            new_file_path = os.path.join(group_path, original_name)
                        try:
                            if os.path.exists(old_file_path):
                                os.rename(old_file_path, new_file_path)
                        except OSError as e:
                            plugin_event.reply(f"二维码释放失败：{str(e)}")
                else:
                    if group.startswith("已占用_"):
                        original_name = group.replace("已占用_", "")
                        old_file_path = os.path.join(group_path, group)
                        new_file_path = os.path.join(group_path, original_name)
                        try:
                            if os.path.exists(old_file_path):
                                os.rename(old_file_path, new_file_path)
                        except OSError as e:
                            plugin_event.reply(f"二维码释放失败：{str(e)}")
        elif play_method == "群号":
            with amourlock:
                playname_file = f"./data/images/恋综备用群/群号/{playname}.json"
                default_file = "./data/images/恋综备用群/群号/默认池.json"
                if os.path.exists(playname_file):
                    group_file = playname_file
                elif os.path.exists(default_file):
                    group_file = default_file
                else:
                    plugin_event.reply("群号配置文件不存在，请联系骰主处理。")
                    return
                try:
                    with open(group_file, "r", encoding="utf-8") as f:
                        group_data = json.load(f)
                except Exception as e:
                    plugin_event.reply(f"读取群号配置文件失败：{str(e)}")
                    return
                if group in group_data:
                    group_data[group]["使用情况"] = False
                    try:
                        with open(group_file, "w", encoding="utf-8") as f:
                            json.dump(group_data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        plugin_event.reply(f"保存群号配置文件失败：{str(e)}")
                        return
        del appoint[code]
        setData("engagement", "appoint.json", appoint)
        cleanup_monitor_session(group, code)
        with amourlock:
            playlog_path = f"./data/amourgame/engagement/{code}.json"
            if os.path.exists(playlog_path):
                try:
                    os.remove(playlog_path)
                except Exception as e:
                    pass
        all_notify_users = []
        all_notify_users.extend(invitee)
        if inviter != "官方" and inviter.isdigit():
            all_notify_users.append(inviter)
        participants_info = []
        for uid in all_notify_users:
            if uid in privategroup[playname]:
                user_data = privategroup[playname][uid]
                if "NPC姓名" in user_data:
                    name = user_data.get("NPC姓名", uid)
                    group_id = user_data.get("NPC群号")
                else:
                    name = user_data.get("嘉宾姓名", uid)
                    group_id = user_data.get("个人群号")
                if group_id:
                    participants_info.append(
                        {"uid": uid, "name": name, "group_id": group_id}
                    )
        inviter_names = []
        invitee_names = []
        if (
            inviter != "官方"
            and inviter.isdigit()
            and inviter in privategroup[playname]
        ):
            inviter_data = privategroup[playname][inviter]
            if "NPC姓名" in inviter_data:
                inviter_name = inviter_data.get("NPC姓名", inviter)
            else:
                inviter_name = inviter_data.get("嘉宾姓名", inviter)
            inviter_names.append(inviter_name)
        for uid in invitee:
            if uid in privategroup[playname]:
                invitee_data = privategroup[playname][uid]
                if "NPC姓名" in invitee_data:
                    invitee_name = invitee_data.get("NPC姓名", uid)
                else:
                    invitee_name = invitee_data.get("嘉宾姓名", uid)
                invitee_names.append(invitee_name)
        notification_msg = f"【通知】\n管理已删除{playtype}编号{code}\n\n"
        notification_msg += f"<{playname}·{playtype}>\n"
        notification_msg += (
            f"邀请者：{'，'.join(inviter_names) if inviter_names else '官方'}\n"
        )
        notification_msg += (
            f"受邀者：{'，'.join(invitee_names) if invitee_names else '无'}\n"
        )
        notification_msg += f"时间：{playtime}\n"
        notification_msg += f"地点：{playplace}\n\n"
        notification_msg += "该预约已作废，时段已释放。"
        plugin_event.reply(f"{notification_msg}\n\n现在开始每隔一秒通知所有相关人员。")
        if participants_info:
            if len(participants_info) > 3:
                for i, participant in enumerate(participants_info):
                    plugin_event.send(
                        "group", participant["group_id"], notification_msg
                    )
                    if i < len(participants_info) - 1:  # 不是最后一条消息
                        time.sleep(1)  # 等待1秒
            else:
                for participant in participants_info:
                    plugin_event.send(
                        "group", participant["group_id"], notification_msg
                    )

    # 复盘方式0：通过群号自动匹配code
    elif re.match(
        r"\[OP:reply,id=([-]?\d+)\]\[OP:at,id=(\d+)\]\s*复盘$",
        message,
    ):
        match = re.match(
            r"\[OP:reply,id=([-]?\d+)\]\[OP:at,id=(\d+)\]\s*复盘$",
            message,
        )
        if match:
            reply_id = match.group(1)
            at_id = match.group(2)
            if at_id != str(plugin_event.bot_info.id):
                plugin_event.reply("@错啦！请@骰子噢！")
                return
            current_group_id = str(plugin_event.data.group_id)
            appoint = getData("engagement", "appoint.json")
            target_code = None
            target_appointment = None
            for code, info in appoint.items():
                group_value = str(info.get("group", ""))
                if group_value == current_group_id:
                    target_code = code
                    target_appointment = info
                    break
            if not target_code:
                plugin_event.reply(
                    "当前群未找到对应的小群记录，请使用「@骰子+类型+编号」的方式复盘噢！"
                )
                return
            try:
                replied_msg = plugin_event.get_msg(reply_id)["data"]
                raw_message = replied_msg.get("raw_message", "")
                if not raw_message:
                    plugin_event.reply("引用的消息转译失败！")
                    return
                forward_match = re.search(
                    r"\[(?:OP|CQ):forward,id=([^,\]]+)\]", raw_message
                )
                if forward_match:
                    message_id = forward_match.group(1)
                    msglist, error_msg = get_forward_messages(
                        plugin_event, message_id, bot_port, bot_token
                    )
                    if error_msg:
                        plugin_event.reply(error_msg)
                        return
                    if not msglist:
                        plugin_event.reply("转发消息内容为空！")
                        return
                    all_texts = []
                    for msg in msglist:
                        message_text = ""
                        content_list = msg.get("content", [])
                        for content_item in content_list:
                            if content_item.get("type") == "text":
                                message_text += content_item.get("data", {}).get(
                                    "text", ""
                                )
                        if message_text:
                            all_texts.append(message_text)
                    context = "\n\n".join(all_texts)
                    playlog = getData("engagement", f"{target_code}.json")
                    if not playlog:
                        playlog = []
                    playlog.append(context)
                    setData("engagement", f"{target_code}.json", playlog)
                    plugin_event.reply(
                        f"本组戏录已复盘！\n\n如需继续复盘，请引用新的消息组，并等待成功回执。\n\n如无更多记录，可以【直接退群】，所有参与小群的嘉宾/NPC退群后，骰子将自动释放小群！"
                    )
                else:
                    plugin_event.reply("引用的消息不是合并转发消息，无法复盘噢！")
                    return
            except Exception as e:
                plugin_event.reply(f"获取消息失败：{str(e)}")

    # 复盘方式1：嘉宾正常出戏，结戏时将所有戏录合并转发至小群，随后引用该消息，@骰子 私约88920055

    elif re.match(
        r"\[OP:reply,id=([-]?\d+)\]\[OP:at,id=(\d+)\]\s*(私约|电话|前置电话|心愿|官约|微信)\s*(\d{8})\b",
        message,
    ):
        match = re.match(
            r"\[OP:reply,id=([-]?\d+)\]\[OP:at,id=(\d+)\]\s*(私约|电话|前置电话|心愿|官约|微信)\s*(\d{8})\b",
            message,
        )
        if match:
            reply_id = match.group(1)
            at_id = match.group(2)
            playtype = match.group(3)
            code = match.group(4)
            if at_id != str(plugin_event.bot_info.id):
                plugin_event.reply("@错啦！请@骰子噢！")
                return
            if playtype not in ["私约", "电话", "前置电话", "心愿", "官约", "微信"]:
                plugin_event.reply("仅支持私约/电话/前置电话/心愿/官约/微信的复盘噢！")
                return
            if len(code) != 8:
                plugin_event.reply("复盘编号位数有误噢！")
                return
            appoint = getData("engagement", "appoint.json")
            if code not in appoint:
                plugin_event.reply("该编号不存在，请检查是否输入正确噢！")
                return
            realplaytype = appoint[code].get("playtype")
            if playtype != realplaytype:
                plugin_event.reply(f"编号类型错误，该编号对应的是{realplaytype}噢！")
                return
            try:
                replied_msg = plugin_event.get_msg(reply_id)["data"]
                raw_message = replied_msg.get("raw_message", "")
                if not raw_message:
                    plugin_event.reply("引用的消息转译失败！")
                    return
                forward_match = re.search(
                    r"\[(?:OP|CQ):forward,id=([^,\]]+)\]", raw_message
                )
                if forward_match:
                    message_id = forward_match.group(1)
                    msglist, error_msg = get_forward_messages(
                        plugin_event, message_id, bot_port, bot_token
                    )
                    if error_msg:
                        plugin_event.reply(error_msg)
                        return
                    if not msglist:
                        plugin_event.reply("转发消息内容为空！")
                        return
                    all_texts = []
                    for msg in msglist:
                        message_text = ""
                        content_list = msg.get("content", [])
                        for content_item in content_list:
                            if content_item.get("type") == "text":
                                message_text += content_item.get("data", {}).get(
                                    "text", ""
                                )
                        if message_text:
                            all_texts.append(message_text)
                    context = "\n\n".join(all_texts)
                    playlog = getData("engagement", f"{code}.json")
                    if not playlog:
                        playlog = []
                    playlog.append(context)
                    setData("engagement", f"{code}.json", playlog)
                    plugin_event.reply(
                        f"本组戏录已复盘！\n\n如需继续复盘，请引用新的消息组，并等待成功回执。\n\n如无更多记录，发送「释放本群{code}」。"
                    )
                else:
                    plugin_event.reply("引用的消息不是合并转发消息，无法复盘噢！！")
                    return
            except Exception as e:
                plugin_event.reply(f"获取消息失败：{str(e)}")

    # 复盘方式2：嘉宾正常出戏，结戏时将所有戏录放到一个气泡，消息第一行为：私约88920055
    # 复盘方式3：嘉宾出戏时，每一段戏第一行为：私约88920055
    #          例如：私约88920055
    #               张三
    #               一段戏文。

    elif re.match(r"(私约|电话|前置电话|心愿|官约|微信)\s*\d{8}\s*([\s\S]+)", message):
        code = re.match(
            r"(私约|电话|前置电话|心愿|官约|微信)\s*(\d{8})\s*([\s\S]+)", message
        ).group(2)
        context = re.match(
            r"(私约|电话|前置电话|心愿|官约|微信)\s*(\d{8})\s*([\s\S]+)", message
        ).group(3)
        context = re.sub(r"(私约|电话|前置电话|心愿|官约|微信)\s*\d{8}\s*", "", context)
        appoint = getData("engagement", "appoint.json")
        if code not in appoint:
            plugin_event.reply(f"该编号不存在，请检查是否输入正确")
            return
        # 该部分代码，限制了私约、电话、心愿的编号发送者，必须为该编号的参与者
        # 注释后，任何人都可以发送携带编号的信息，并纳入复盘
        # if uid != appoint[code].get("inviter") and uid not in appoint[code].get("invitee"):
        #    plugin_event.reply(f"该编号{code}中没有你的信息，请检查是否输入正确")
        #    return
        playname = appoint[code].get("playname")
        playtype = appoint[code].get("playtype")
        privategroup = getData("groupcollection", "privategroup.json")
        dlc2 = Proc.database.get_basic_config(
            "AmourGame", "dlc2", default_value="0", pkl=False
        )
        if playtype == "电话" and dlc2 == "1":
            if random.random() <= 0.2:
                if len(context) >= 30:
                    start = random.randint(0, len(context) - 30)
                    lostcontext = context[start : start + 30]
                else:
                    lostcontext = context
                participants = []
                inviter = appoint[code].get("inviter")
                invitee = appoint[code].get("invitee", [])
                if inviter != "官方" and inviter.isdigit():
                    participants.append(inviter)
                participants.extend(invitee)
                playerlist = []
                for uid_key in privategroup[playname]:
                    if uid_key.isdigit():
                        user_data = privategroup[playname][uid_key]
                        if "嘉宾姓名" not in user_data:
                            continue
                        if uid_key in participants:
                            continue
                        group_id = user_data.get("个人群号")
                        if group_id:
                            playerlist.append((uid_key, group_id))
                if len(playerlist) >= 1:
                    lost_to = random.sample(playerlist, 1)
                    lost_uid, lost_group = lost_to[0]
                    lost_user_data = privategroup[playname][lost_uid]
                    lost_name = lost_user_data.get("嘉宾姓名", lost_uid)
                    plugin_event.send(
                        "group",
                        lost_group,
                        f"你的通讯设备传出一阵滋啦声，凑近细听：\n\n{lostcontext}",
                    )
        if uid in privategroup.get(playname, {}):
            user_data = privategroup[playname][uid]
            if "NPC姓名" in user_data:
                uname = user_data.get("NPC姓名", uid)
            else:
                uname = user_data.get("嘉宾姓名", uid)
        else:
            uname = uid
        playlog = getData("engagement", f"{code}.json")
        if len(playlog) == 0:
            playlog = []
        playlog.append(f"{uname}：\n{context}")
        setData("engagement", f"{code}.json", playlog)
        plugin_event.reply("记录成功！")

    elif re.match(r"释放本群\s*\d{8}", message):
        code = re.match(r"释放本群\s*(\d{8})", message).group(1)
        appoint = getData("engagement", "appoint.json")
        if code not in appoint:
            plugin_event.reply(f"该编号不存在,请检查是否输入正确")
            return
        inviter = appoint[code].get("inviter")
        invitee = appoint[code].get("invitee", [])
        if uid != inviter and uid not in invitee and uid not in masterlist:
            plugin_event.reply(f"该编号{code}中没有你的信息,请检查是否输入正确")
            return
        playname = appoint[code].get("playname")
        playtype = appoint[code].get("playtype")
        group = appoint[code].get("group")
        playtime = appoint[code].get("playtime")
        playplace = appoint[code].get("playplace")
        register = getData("groupcollection", "register.json")
        play_method = register[playname].get("play_method", "二维码")
        privategroup = getData("groupcollection", "privategroup.json")
        new_group_name = None
        if play_method == "二维码":
            with amourlock:
                playname_path = f"./data/images/恋综备用群/二维码/{playname}"
                default_path = "./data/images/恋综备用群/二维码/默认池"
                if os.path.exists(playname_path) and os.path.isdir(playname_path):
                    group_path = playname_path
                else:
                    group_path = default_path
                if group.isdigit():
                    mapping_file = os.path.join(group_path, "二维码与群号对应组.json")
                    original_name = None
                    if os.path.exists(mapping_file):
                        try:
                            with open(mapping_file, "r", encoding="utf-8") as f:
                                mapping_data = json.load(f)
                            for key, value in mapping_data.items():
                                if str(value) == group:
                                    original_name = key
                                    break
                        except Exception as e:
                            pass
                    if original_name:
                        old_file_name = f"已占用_{original_name}"
                        old_file_path = os.path.join(group_path, old_file_name)
                        if not os.path.exists(old_file_path):
                            possible_extensions = [
                                ".jpg",
                                ".jpeg",
                                ".png",
                                ".gif",
                                ".bmp",
                            ]
                            for ext in possible_extensions:
                                old_file_path_with_ext = os.path.join(
                                    group_path, f"{old_file_name}{ext}"
                                )
                                if os.path.exists(old_file_path_with_ext):
                                    old_file_path = old_file_path_with_ext
                                    new_file_path = os.path.join(
                                        group_path, f"{original_name}{ext}"
                                    )
                                    break
                        else:
                            new_file_path = os.path.join(group_path, original_name)
                        try:
                            if os.path.exists(old_file_path):
                                os.rename(old_file_path, new_file_path)
                        except OSError as e:
                            plugin_event.reply(f"二维码释放失败：{str(e)}")
                        match = re.match(r"(.+)\.\w+$", original_name)
                        if match:
                            new_group_name = match.group(1)
                        else:
                            new_group_name = original_name
                else:
                    if group.startswith("已占用_"):
                        original_name = group.replace("已占用_", "")
                        old_file_path = os.path.join(group_path, group)
                        new_file_path = os.path.join(group_path, original_name)
                        try:
                            if os.path.exists(old_file_path):
                                os.rename(old_file_path, new_file_path)
                        except OSError as e:
                            plugin_event.reply(f"二维码释放失败：{str(e)}")
                        match = re.match(r"(.+)\.\w+$", original_name)
                        if match:
                            new_group_name = match.group(1)
                        else:
                            new_group_name = original_name
        elif play_method == "群号":
            new_group_name = f"{playname}备用"
            with amourlock:
                playname_file = f"./data/images/恋综备用群/群号/{playname}.json"
                default_file = "./data/images/恋综备用群/群号/默认池.json"
                group_file = None
                if os.path.exists(playname_file):
                    group_file = playname_file
                elif os.path.exists(default_file):
                    group_file = default_file
                try:
                    with open(group_file, "r", encoding="utf-8") as f:
                        group_data = json.load(f)
                    group_str = str(group)
                    if group_str in group_data:
                        group_data[group_str]["使用情况"] = False
                        with open(group_file, "w", encoding="utf-8") as f:
                            json.dump(group_data, f, ensure_ascii=False, indent=2)
                    else:
                        plugin_event.reply(
                            f"群号{group_str}不在配置文件中，请联系骰主。"
                        )
                        return
                except Exception as e:
                    plugin_event.reply(f"处理群号文件时出错：{e}，请联系骰主处理。")
                    return
        if new_group_name:
            plugin_event.set_group_name(groupid, new_group_name)
        base_path = f"./plugin/data/amourgame/恋综复盘/{playname}/"
        with amourlock:
            if not os.path.exists(base_path):
                os.makedirs(base_path)
            tech_file = os.path.join(base_path, "「技术支持」探丸借客@临皋闲人.txt")
            if not os.path.exists(tech_file):
                tech_content = (
                    "_      /)---(\ \n"
                    "\ \   (/ . . \)\n"
                    " \ \__)-\(*)/\n"
                    "  \_       (_\n"
                    "  (___/-(____)\n"
                    "\n"
                    "「技术支持」探丸借客@临皋闲人\n"
                    "\n"
                    "OlivaDice By lunzhiPenxil"
                )
                with open(tech_file, "w", encoding="utf-8") as f:
                    f.write(tech_content)
        inviter_name = ""
        if inviter == "官方":
            inviter_name = "官方"
        elif inviter in privategroup[playname]:
            user_data = privategroup[playname][inviter]
            inviter_name = user_data.get("嘉宾姓名", user_data.get("NPC姓名", inviter))
        else:
            inviter_name = inviter
        invitee_names = []
        for i in invitee:
            if i in privategroup[playname]:
                user_data = privategroup[playname][i]
                name = user_data.get("嘉宾姓名", user_data.get("NPC姓名", i))
                invitee_names.append(name)
        resee_name = f"{playname} {playtime} {playtype} {inviter_name}"
        for name in invitee_names:
            resee_name += f"x{name}"
        resee_name = re.sub(r'[<>:"/\\|?*]', "_", resee_name)
        invitee_text = "，".join(invitee_names)
        resee_text = f"<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{invitee_text}\n时间：{playtime}\n地点：{playplace}"
        playlog = getData("engagement", f"{code}.json")
        if playlog:
            for i in playlog:
                resee_text += f"\n\n{i}"
            with amourlock:
                Dnum = re.match(r"D\d+", playtime).group()
                log_path = f"./plugin/data/amourgame/恋综复盘/{playname}/{Dnum}{playtype}"
                if not os.path.exists(log_path):
                    os.makedirs(log_path)
                with open(f"{log_path}/{resee_name}.txt", "w", encoding="utf-8") as f:
                    f.write(resee_text)
        try:
            os.remove(f"./plugin/data/amourgame/engagement/{code}.json")
            os.remove(f"./plugin/data/amourgame/engagement/{code}.json.bak")
        except:
            pass
        del appoint[code]
        setData("engagement", "appoint.json", appoint)
        cleanup_monitor_session(group, code)
        plugin_event.reply(f"如有复盘，文件已生成。\n小群{code}已释放，可以退群啦！")

    elif re.match(
        r"\[OP:reply,id=([-]?\d+)\]\[OP:at,id=(\d+)\]\s*撤戏$",
        message,
    ):
        match = re.match(
            r"\[OP:reply,id=([-]?\d+)\]\[OP:at,id=(\d+)\]\s*撤戏$",
            message,
        )
        if match:
            reply_id = match.group(1)
            at_id = match.group(2)
            if at_id != str(plugin_event.bot_info.id):
                plugin_event.reply("@错啦！请@骰子噢！")
                return
            url = f"http://127.0.0.1:{bot_port}/delete_msg"
            payload = json.dumps({"message_id": int(reply_id)})
            headers = {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json",
            }
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("retcode") == 0:
                plugin_event.reply("戏录撤回成功！")
            else:
                error_msg = result.get("message", "未知错误")
                error_wording = result.get("wording", "")
                plugin_event.reply(
                    f"撤回失败：{error_msg} {error_wording}，请联系骰主！\n\n【注意】\n管理员无法撤回群主/其他管理员的消息。"
                )

    elif re.match(r"<(.+)·心愿>", message):
        wish_match = re.match(
            r"<(.+)·心愿>\s*内容：(.+?)\s*署名：(.*?)\s*时间：(.+?)\s*地点：(.+)",
            message,
            re.DOTALL,
        )
        if wish_match:
            playname = wish_match.group(1).strip()
            content = wish_match.group(2).strip()
            author = wish_match.group(3).strip()
            if not author:
                author = "-"
            playtime = wish_match.group(4).strip()
            playplace = wish_match.group(5).strip()
            time_range = playtime.split()[1]
            if not re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", time_range):
                plugin_event.reply("请使用8位时间编码格式，如：07:00-23:59")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup or uid not in privategroup[playname]:
                plugin_event.reply(
                    f"{sender}未参与恋综「{playname}」，无法上传心愿噢！"
                )
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名或联系骰主噢！"
                )
                return
            if playname in privategroup and uid in privategroup[playname]:
                user_groupid = privategroup[playname][uid].get(
                    "个人群号"
                ) or privategroup[playname][uid].get("NPC群号")
            if user_groupid != groupid:
                plugin_event.reply(f"请前往个人群中挂心愿噢！")
                return
            play_group = register[playname].get("play_group", "")
            if not play_group:
                plugin_event.reply("该恋综未设置戏群，请联系骰主。")
                return
            day_part = playtime.split()[0]
            is_today, error_msg = check_virtual_date(playname, day_part)
            if not is_today:
                plugin_event.reply(error_msg)
                return
            limit_data = getData("sendmessage", "limit.json")
            daily_limit = None
            if isinstance(limit_data, dict):
                play_limit = limit_data.get(playname, {})
                if isinstance(play_limit, dict):
                    daily_limit = play_limit.get("心愿")
            if daily_limit is not None:
                timeline_data = getData("engagement", "timeline.json")
                wish_count = 0
                if (
                    isinstance(timeline_data, dict)
                    and playname in timeline_data
                    and uid in timeline_data[playname]
                    and day_part in timeline_data[playname][uid]
                ):
                    for time_slot, slot_data in timeline_data[playname][uid][
                        day_part
                    ].items():
                        if (
                            isinstance(slot_data, dict)
                            and slot_data.get("playtype") == "心愿"
                        ):
                            wish_count += 1
                if wish_count >= daily_limit:
                    plugin_event.reply(
                        f"{day_part}已挂{wish_count}/{daily_limit}个心愿，无法再挂新的心愿啦！"
                    )
                    return
            usertime = getData("engagement", "usertime.json")
            if playname not in usertime:
                usertime[playname] = {}
            if uid not in usertime[playname]:
                usertime[playname][uid] = []
            timereq = checkgrouptime(playtime, usertime[playname][uid])
            if isinstance(timereq, str):
                plugin_event.reply(timereq)
                return
            usertime[playname][uid] = timereq
            setData("engagement", "usertime.json", usertime)
            wish_data = getData("wishwall", "wish_data.json")
            if not isinstance(wish_data, dict):
                wish_data = {}
            if "total_count" not in wish_data:
                wish_data["total_count"] = 0
            if "wishes" not in wish_data:
                wish_data["wishes"] = []
            new_id = wish_data["total_count"] + 1
            user_data = privategroup[playname][uid]
            user_name = user_data.get("嘉宾姓名", user_data.get("NPC姓名", ""))
            new_wish = {
                "id": new_id,
                "playname": playname,
                "content": content,
                "author": author,
                "time": playtime,
                "location": playplace,
                "wisher_uid": uid,
                "wisher_real_name": user_name,
            }
            wish_data["wishes"].append(new_wish)
            wish_data["total_count"] = new_id
            setData("wishwall", "wish_data.json", wish_data)
            wish_msg = (
                f"心愿墙上新啦！\n\n"
                f"编号：{new_id}\n"
                f"内容：{content}\n"
                f"署名：{author}\n"
                f"时间：{playtime}\n"
                f"地点：{playplace}\n\n"
                f"发送「摘取心愿 {new_id}」即可摘下！\n\n发送「查看{playname}心愿墙」以获取所有未摘心愿。"
            )
            plugin_event.send("group", play_group, wish_msg)
            plugin_event.reply(
                f"心愿上传成功！编号：{new_id}\n\n该时段已被占用，自己摘下即可释放时间。"
            )

    elif message.startswith("摘取心愿"):
        wish_id_str = message.replace("摘取心愿", "").strip()
        if not wish_id_str:
            plugin_event.reply("请提供心愿编号，例如：摘取心愿 1")
            return
        wish_data = getData("wishwall", "wish_data.json")
        try:
            wish_id = int(wish_id_str)
        except ValueError:
            plugin_event.reply("心愿的编号必须是纯数字噢！")
            return
        if not isinstance(wish_data, dict) or "wishes" not in wish_data:
            plugin_event.reply("心愿墙数据为空，无法摘取噢！")
            return
        target_wish = None
        target_index = -1
        for i, wish in enumerate(wish_data["wishes"]):
            if wish["id"] == wish_id:
                target_wish = wish
                target_index = i
                break
        if not target_wish:
            plugin_event.reply(f"{wish_id}号心愿不存在或已被摘取噢！")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        wish_playname = target_wish.get("playname", "")
        if wish_playname not in privategroup:
            plugin_event.reply(f"恋综「{wish_playname}」未注册或已注销，无法摘取心愿！")
            return
        if uid not in privategroup[wish_playname]:
            plugin_event.reply(
                f"{sender}不是恋综「{wish_playname}」的嘉宾，无法摘取心愿噢！"
            )
            return
        user_groupid = privategroup[wish_playname][uid].get("个人群号") or privategroup[
            wish_playname
        ][uid].get("NPC群号")
        if user_groupid != groupid:
            plugin_event.reply(f"请前往个人群中摘取心愿噢！")
            return
        if uid == target_wish["wisher_uid"]:
            usertime = getData("engagement", "usertime.json")
            playtime = target_wish["time"]
            playname = target_wish["playname"]
            wisher_uid = target_wish["wisher_uid"]
            if remove_usertime_interval(
                usertime, playname, wisher_uid, playtime
            ):
                setData("engagement", "usertime.json", usertime)
            wish_data["wishes"].pop(target_index)
            setData("wishwall", "wish_data.json", wish_data)
            plugin_event.reply(
                f"摘取了自己的心愿，编号{wish_id}，心愿已取消，时间段已恢复空闲！"
            )
            return
        usertime = getData("engagement", "usertime.json")
        user_playname = wish_playname
        if user_playname not in usertime:
            usertime[user_playname] = {}
        if uid not in usertime[user_playname]:
            usertime[user_playname][uid] = []
        timereq = checkgrouptime(target_wish["time"], usertime[user_playname][uid])
        if isinstance(timereq, str):
            plugin_event.reply(timereq)
            return
        usertime[user_playname][uid] = timereq
        register = getData("groupcollection", "register.json")
        playname = target_wish["playname"]
        if playname not in register:
            plugin_event.reply(f"该心愿对应的恋综「{playname}」已注销，无法摘取噢！")
            return
        play_method = register[playname].get("play_method", "不使用")
        if play_method == "不使用":
            plugin_event.reply("后台尚未设置小群调用方式，请联系管理噢！")
            return
        elif play_method == "二维码":
            with amourlock:
                playname_path = f"./data/images/恋综备用群/二维码/{playname}"
                default_path = "./data/images/恋综备用群/二维码/默认池"
                if os.path.exists(playname_path) and os.path.isdir(playname_path):
                    group_path = playname_path
                else:
                    group_path = default_path
                if not os.path.exists(group_path):
                    plugin_event.reply(
                        f"二维码文件夹不存在：{group_path}，请联系骰主噢！"
                    )
                    return
                files = [
                    f
                    for f in os.listdir(group_path)
                    if os.path.isfile(os.path.join(group_path, f))
                ]
                files = [
                    item
                    for item in files
                    if not item.startswith("已占用")
                    and item != "二维码与群号对应组.json"
                ]
                if not files:
                    plugin_event.reply("群二维码文件夹为空，请联系骰主噢！")
                    return
                random_file = random.choice(files)
                original_name = os.path.splitext(random_file)[0]
                mapping_file = os.path.join(group_path, "二维码与群号对应组.json")
                group_id_from_mapping = None
                if os.path.exists(mapping_file):
                    try:
                        with open(mapping_file, "r", encoding="utf-8") as f:
                            mapping_data = json.load(f)
                        if original_name in mapping_data:
                            group_id_from_mapping = str(mapping_data[original_name])
                    except Exception as e:
                        pass
                new_name = f"已占用_{random_file}"
                number = 1
                while os.path.exists(os.path.join(group_path, new_name)):
                    new_name = f"{number}{os.path.splitext(random_file)[1]}({number})"
                    number += 1
                old_file_path = os.path.join(group_path, random_file)
                new_file_path = os.path.join(group_path, new_name)
                try:
                    os.rename(old_file_path, new_file_path)
                except OSError as e:
                    plugin_event.reply("群二维码锁定分配失败，请联系骰主噢！")
                    return
                if group_id_from_mapping:
                    group_info = group_id_from_mapping
                else:
                    group_info = new_name
                group_display = f"[CQ:image,file=恋综备用群/二维码/{playname if os.path.exists(playname_path) else '默认池'}/{new_name}]"
        elif play_method == "群号":
            with amourlock:
                playname_file = f"./data/images/恋综备用群/群号/{playname}.json"
                default_file = "./data/images/恋综备用群/群号/默认池.json"
                if os.path.exists(playname_file):
                    group_file = playname_file
                elif os.path.exists(default_file):
                    group_file = default_file
                else:
                    plugin_event.reply("群号文件不存在，请联系骰主噢！")
                    return
                try:
                    with open(group_file, "r", encoding="utf-8") as f:
                        group_data = json.load(f)
                except Exception as e:
                    plugin_event.reply("读取群号文件失败，请联系骰主噢！")
                    return
                available_groups = []
                for group_id, group_info in group_data.items():
                    if (
                        isinstance(group_info, dict)
                        and group_info.get("使用情况") == False
                    ):
                        available_groups.append(group_id)
                if not available_groups:
                    plugin_event.reply("没有可用的群号了，请联系骰主噢！")
                    return
                new_name = random.choice(available_groups)
                group_data[new_name]["使用情况"] = True
                try:
                    with open(group_file, "w", encoding="utf-8") as f:
                        json.dump(group_data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    plugin_event.reply("保存群号状态失败，请联系骰主噢！")
                    return
            group_info = new_name
            group_display = f"群号：{new_name}"
        else:
            plugin_event.reply(f"后台尚未设置小群调用方式，请联系管理噢！")
            return
        appoint = getData("engagement", "appoint.json")
        numlist = "0123456789"
        replaynum = "".join(random.choice(numlist) for _ in range(8))
        while replaynum in appoint:
            replaynum = "".join(random.choice(numlist) for _ in range(8))
        picker_name = privategroup[user_playname][uid].get(
            "嘉宾姓名", privategroup[user_playname][uid].get("NPC姓名", "")
        )
        appoint[replaynum] = {
            "playname": target_wish["playname"],
            "playtype": "心愿",
            "group": group_info,
            "inviter": target_wish["wisher_uid"],
            "invitee": [uid],
            "playtime": target_wish["time"],
            "playplace": target_wish["location"],
            "wish_id": wish_id,
        }
        setData("engagement", "appoint.json", appoint)
        setData("engagement", "usertime.json", usertime)
        timeline = getData("engagement", "timeline.json")
        playname = target_wish["playname"]
        playtime_parts = target_wish["time"].split()
        date_part = playtime_parts[0]
        time_range = playtime_parts[1]
        if playname not in timeline:
            timeline[playname] = {}
        if uid not in timeline[playname]:
            timeline[playname][uid] = {}
        if date_part not in timeline[playname][uid]:
            timeline[playname][uid][date_part] = {}
        participants = [uid, target_wish["wisher_uid"]]
        timeline[playname][uid][date_part][time_range] = {
            "playtype": "心愿",
            "participants": participants,
        }
        wisher_uid = target_wish["wisher_uid"]
        if wisher_uid not in timeline[playname]:
            timeline[playname][wisher_uid] = {}
        if date_part not in timeline[playname][wisher_uid]:
            timeline[playname][wisher_uid][date_part] = {}
        timeline[playname][wisher_uid][date_part][time_range] = {
            "playtype": "心愿",
            "participants": participants,
        }
        setData("engagement", "timeline.json", timeline)
        wish_data["wishes"].pop(target_index)
        setData("wishwall", "wish_data.json", wish_data)
        if play_method == "二维码":
            plugin_event.reply(
                f"摘取成功！\n\n"
                f"许愿方：{target_wish['wisher_real_name']}\n"
                f"内容：{target_wish['content']}\n"
                f"署名：{target_wish['author']}\n"
                f"时间：{target_wish['time']}\n"
                f"地点：{target_wish['location']}\n\n"
                f"心愿复盘编号{replaynum}\n\n"
                f"{group_display}"
            )
        else:
            plugin_event.reply(
                f"摘取成功！\n\n"
                f"许愿方：{target_wish['wisher_real_name']}\n"
                f"内容：{target_wish['content']}\n"
                f"署名：{target_wish['author']}\n"
                f"时间：{target_wish['time']}\n"
                f"地点：{target_wish['location']}\n\n"
                f"心愿复盘编号{replaynum}\n\n"
                f"搜索{group_display}"
            )
        wisher_group = privategroup[target_wish["playname"]][wisher_uid].get(
            "个人群号",
            privategroup[target_wish["playname"]][wisher_uid].get("NPC群号", ""),
        )
        if wisher_group:
            if play_method == "二维码":
                notification_msg = (
                    f"{wish_id}号心愿已被{picker_name}摘取！\n\n"
                    f"内容：{target_wish['content']}\n"
                    f"署名：{target_wish['author']}\n"
                    f"时间：{target_wish['time']}\n"
                    f"地点：{target_wish['location']}\n\n"
                    f"心愿复盘编号{replaynum}\n\n"
                    f"{group_display}"
                )
            else:
                notification_msg = (
                    f"{wish_id}号心愿已被{picker_name}摘取！\n\n"
                    f"内容：{target_wish['content']}\n"
                    f"署名：{target_wish['author']}\n"
                    f"时间：{target_wish['time']}\n"
                    f"地点：{target_wish['location']}\n\n"
                    f"心愿复盘编号{replaynum}\n\n"
                    f"搜索{group_display}"
                )
            plugin_event.send("group", wisher_group, notification_msg)

    elif message.startswith("查看") and message.endswith("心愿墙"):
        playname = message[2:-3].strip()
        if not playname:
            plugin_event.reply("请指定恋综名，格式：查看xx心愿墙")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup or uid not in privategroup[playname]:
            plugin_event.reply(
                f"{sender}不是恋综「{playname}」的嘉宾，无法查看心愿墙噢！"
            )
            return
        wish_data = getData("wishwall", "wish_data.json")
        if not isinstance(wish_data, dict) or "wishes" not in wish_data:
            plugin_event.reply("心愿墙目前是空的！")
            return
        playname_wishes = []
        for wish in wish_data["wishes"]:
            if wish["playname"] == playname:
                playname_wishes.append(wish)
        if not playname_wishes:
            plugin_event.reply(f"心愿墙目前是空的！")
            return
        if len(playname_wishes) == 1:
            wish = playname_wishes[0]
            wish_msg = (
                f"{playname} 心愿墙\n\n"
                f"编号：{wish['id']}\n"
                f"内容：{wish['content']}\n"
                f"署名：{wish['author']}\n"
                f"时间：{wish['time']}\n"
                f"地点：{wish['location']}\n\n"
                f"摘取指令：摘取心愿 {wish['id']}"
            )
            plugin_event.reply(wish_msg)
            return
        nodes_data = []
        nodes_data.append(
            {
                "bot_id": bot_id,
                "content_text": f"{playname} 心愿墙\n\n发送「摘取心愿 编号」即可摘取对应心愿",
            }
        )
        for wish in playname_wishes:
            wish_content = (
                f"编号：{wish['id']}\n"
                f"内容：{wish['content']}\n"
                f"署名：{wish['author']}\n"
                f"时间：{wish['time']}\n"
                f"地点：{wish['location']}"
            )
            nodes_data.append({"bot_id": bot_id, "content_text": wish_content})
        result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            plugin_event.reply("合并转发失败，请联系骰主处理。")
            for wish in playname_wishes:
                wish_msg = (
                    f"编号：{wish['id']}\n"
                    f"内容：{wish['content']}\n"
                    f"署名：{wish['author']}\n"
                    f"时间：{wish['time']}\n"
                    f"地点：{wish['location']}\n"
                )
                plugin_event.reply(wish_msg)
                time.sleep(0.5)

    elif re.match(
        r"^(.+?)\s*个人群列表$",
        message,
    ):
        match = re.match(r"^(.+?)\s*个人群列表$", message)
        if match:
            playname = match.group(1).strip()
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可查看。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            manage_group = register[playname].get("manage_group")
            current_group = groupid
            if current_group != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中查看个人群列表。")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup or not privategroup[playname]:
                plugin_event.reply(f"恋综「{playname}」暂无个人群数据。")
                return
            nodes_data = []
            guests = []
            npcs = []
            for guest_uid, guest_info in privategroup[playname].items():
                if "嘉宾编号" in guest_info:
                    guests.append(
                        {
                            "uid": guest_uid,
                            "编号": guest_info.get("嘉宾编号", 0),
                            "姓名": guest_info.get("嘉宾姓名", "未知"),
                            "群号": guest_info.get("个人群号", "未知"),
                            "类型": "嘉宾",
                        }
                    )
                if "NPC编号" in guest_info:
                    npcs.append(
                        {
                            "uid": guest_uid,
                            "编号": guest_info.get("NPC编号", 0),
                            "姓名": guest_info.get("NPC姓名", "未知"),
                            "群号": guest_info.get("NPC群号", "未知"),
                            "类型": "NPC",
                        }
                    )
            guests.sort(key=lambda x: x["编号"])
            npcs.sort(key=lambda x: x["编号"])
            for guest in guests:
                content_text = (
                    f"{guest['编号']}号嘉宾：{guest['姓名']}\n个人群号：{guest['群号']}"
                )
                nodes_data.append({"bot_id": bot_id, "content_text": content_text})
            for npc in npcs:
                content_text = (
                    f"{npc['编号']}号NPC：{npc['姓名']}\nNPC群号：{npc['群号']}"
                )
                nodes_data.append({"bot_id": bot_id, "content_text": content_text})
            total_guests = len(guests)
            total_npcs = len(npcs)
            total_all = total_guests + total_npcs
            if total_all == 0:
                plugin_event.reply(f"恋综「{playname}」暂无个人群数据。")
                return
            result = send_forward_message(
                bot_port, bot_token, current_group, nodes_data
            )
            if result.get("retcode") != 0:
                plugin_event.reply(
                    f"合并转发消息构造失败，{result.get('message', '未知错误')}"
                )
                return

    elif message.startswith("删除时间线："):
        content = message[6:].strip()
        match = re.match(
            r"(.+)\s+(.+)\s+(私约|电话|前置电话|官约|微信|心愿)\s+(D\d+\s+\d{2}:\d{2}-\d{2}:\d{2})",
            content,
        )
        if not match:
            return
        if uid not in masterlist:
            plugin_event.reply("如需删除时间线，请联系骰主开放权限。")
            return
        playname = match.group(1).strip()
        player_name = match.group(2).strip()
        playtype = match.group(3).strip()
        playtime = match.group(4).strip()
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中删除时间线！")
            return
        valid_playtypes = ["私约", "电话", "前置电话", "官约", "微信", "心愿"]
        if playtype not in valid_playtypes:
            plugin_event.reply(f"小群类型错误！仅可为：{'、'.join(valid_playtypes)}")
            return
        if not re.match(r"^D\d+\s+\d{2}:\d{2}-\d{2}:\d{2}$", playtime):
            plugin_event.reply("时间格式错误！请使用：Dx 07:00-23:59")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        player_uid = None
        player_groupid = None
        for uid_key, user_data in privategroup[playname].items():
            if user_data.get("嘉宾姓名") == player_name:
                player_uid = uid_key
                player_groupid = user_data.get("个人群号")
                break
            elif user_data.get("NPC姓名") == player_name:
                player_uid = uid_key
                player_groupid = user_data.get("NPC群号")
                break
        if not player_uid:
            plugin_event.reply(
                f"在恋综「{playname}」中未找到「{player_name}」，无法删除时间线噢！"
            )
            return
        timeline = getData("engagement", "timeline.json")
        if playname not in timeline:
            plugin_event.reply(f"恋综「{playname}」中没有任何时间线记录！")
            return
        if player_uid not in timeline[playname]:
            plugin_event.reply(
                f"恋综「{playname}」中「{player_name}」没有任何时间线记录！"
            )
            return
        date_part = playtime.split()[0]
        time_range = playtime.split()[1]
        timeline_key = None
        if date_part in timeline[playname][player_uid]:
            day_data = timeline[playname][player_uid][date_part]
            matching_keys = [
                key
                for key, slot_info in day_data.items()
                if key.split("#", 1)[0] == time_range
                and isinstance(slot_info, dict)
                and slot_info.get("playtype") == playtype
            ]
            if len(matching_keys) == 1:
                timeline_key = matching_keys[0]
            elif len(matching_keys) > 1:
                plugin_event.reply(
                    f"检测到「{player_name}」在{playtime}存在多个{playtype}时间线，"
                    f"无法确定要删除哪一个。请使用“删除{playtype}+编号”删除对应小群。"
                )
                return
            elif time_range in day_data:
                actual_type = day_data[time_range].get("playtype", "未知")
                plugin_event.reply(
                    f"时间线类型不匹配！该时段类型为：{actual_type}"
                )
                return
        if timeline_key is None:
            plugin_event.reply(
                f"未找到恋综「{playname}」中「{player_name}」在{playtime}的{playtype}时间线！"
            )
            return
        del timeline[playname][player_uid][date_part][timeline_key]
        has_same_time_occupation = any(
            key.split("#", 1)[0] == time_range
            for key in timeline[playname][player_uid][date_part]
        )
        usertime = getData("engagement", "usertime.json")
        if not has_same_time_occupation:
            remove_usertime_interval(usertime, playname, player_uid, playtime)
        if not timeline[playname][player_uid][date_part]:
            del timeline[playname][player_uid][date_part]
        if not timeline[playname][player_uid]:
            del timeline[playname][player_uid]
        if not timeline[playname]:
            del timeline[playname]
        setData("engagement", "timeline.json", timeline)
        setData("engagement", "usertime.json", usertime)
        if player_groupid:
            try:
                plugin_event.send(
                    "group",
                    player_groupid,
                    f"【通知】\n\n管理删除了「{player_name}」的时间线：\n\n"
                    f"恋综：{playname}\n"
                    f"类型：{playtype}\n"
                    f"时间：{playtime}\n\n"
                    f"该时段已释放，可以开启新的小群。",
                )
            except Exception as e:
                plugin_event.reply(f"时间线删除成功，但向玩家发送通知失败：{str(e)}")
                return
        plugin_event.reply(
            f"成功删除「{player_name}」的时间线！\n\n"
            f"恋综：{playname}\n"
            f"类型：{playtype}\n"
            f"时间：{playtime}\n"
            f"\n已通知至个人群。\n\n【注意】\n该指令仅删除了时间线，并未删除小群。\n若需删除小群+时间线，请使用删除小群的指令。\n\n若此时你已经在未释放的情况下删除了时间线，你可以：\n①使用添加时间线指令加回来再删。\n②直接去把小群释放了。"
        )

    elif message.startswith("添加时间线："):
        content = message[6:].strip()
        match = re.match(
            r"(.+)\s+(.+)\s+(私约|电话|前置电话|官约|微信|心愿)\s+(D\d+\s+\d{2}:\d{2}-\d{2}:\d{2})",
            content,
        )
        if not match:
            return
        if uid not in masterlist:
            plugin_event.reply("如需添加时间线，请联系骰主开放权限。")
            return
        playname = match.group(1).strip()
        player_name = match.group(2).strip()
        playtype = match.group(3).strip()
        playtime = match.group(4).strip()
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中添加时间线！")
            return
        valid_playtypes = ["私约", "电话", "前置电话", "官约", "微信", "心愿"]
        if playtype not in valid_playtypes:
            plugin_event.reply(f"小群类型错误！仅可为：{'、'.join(valid_playtypes)}")
            return
        if not re.match(r"^D\d+\s+\d{2}:\d{2}-\d{2}:\d{2}$", playtime):
            plugin_event.reply("时间格式错误！请使用：Dx 07:00-23:59")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        player_uid = None
        player_groupid = None
        for uid_key, user_data in privategroup[playname].items():
            if user_data.get("嘉宾姓名") == player_name:
                player_uid = uid_key
                player_groupid = user_data.get("个人群号")
                break
            elif user_data.get("NPC姓名") == player_name:
                player_uid = uid_key
                player_groupid = user_data.get("NPC群号")
                break
        if not player_uid:
            plugin_event.reply(
                f"在恋综「{playname}」中未找到「{player_name}」，无法添加时间线噢！"
            )
            return
        usertime = getData("engagement", "usertime.json")
        if playname not in usertime:
            usertime[playname] = {}
        if player_uid not in usertime[playname]:
            usertime[playname][player_uid] = []
        timereq = checkgrouptime(playtime, usertime[playname][player_uid])
        if isinstance(timereq, str):
            plugin_event.reply(f"添加时间线失败：{timereq}")
            return
        usertime[playname][player_uid] = timereq
        setData("engagement", "usertime.json", usertime)
        timeline = getData("engagement", "timeline.json")
        if playname not in timeline:
            timeline[playname] = {}
        if player_uid not in timeline[playname]:
            timeline[playname][player_uid] = {}
        date_part = playtime.split()[0]
        time_range = playtime.split()[1]
        if date_part not in timeline[playname][player_uid]:
            timeline[playname][player_uid][date_part] = {}
        timeline[playname][player_uid][date_part][time_range] = {
            "playtype": playtype,
            "participants": [player_uid],
        }
        setData("engagement", "timeline.json", timeline)
        if player_groupid:
            try:
                plugin_event.send(
                    "group",
                    player_groupid,
                    f"【通知】\n管理为「{player_name}」添加了时间线：\n\n"
                    f"恋综：{playname}\n"
                    f"类型：{playtype}\n"
                    f"时间：{playtime}\n\n"
                    f"该时段已被占用，无法开启小群。\n添加的时间线不会计入公告的小群数量。",
                )
            except Exception as e:
                plugin_event.reply(f"时间线添加成功，但向玩家发送通知失败：{str(e)}")
                return
        plugin_event.reply(
            f"成功为「{player_name}」添加时间线！\n\n"
            f"恋综：{playname}\n"
            f"类型：{playtype}\n"
            f"时间：{playtime}\n"
            f"\n已通知至个人群。\n添加的时间线不会计入公告的小群数量。"
        )

    elif re.match(r"^([\w\W]+?)\s+([\w\W]+?)\s*时间线$", message):
        apply_info = re.match(r"^([\w\W]+?)\s+([\w\W]+?)\s*时间线$", message)
        playname = apply_info.group(1).strip()
        guest_name = apply_info.group(2).strip()
        if uid not in masterlist:
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            return
        manage_group = register[playname].get("manage_group")
        if str(groupid) != str(manage_group):
            plugin_event.reply(f"请前往恋综「{playname}」的后台群查询嘉宾时间线噢！")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            return
        target_uid = None
        for uid_in_data, guest_data in privategroup[playname].items():
            if guest_data.get("嘉宾姓名") == guest_name:
                target_uid = uid_in_data
                break
            elif guest_data.get("NPC姓名") == guest_name:
                target_uid = uid_in_data
                break
        if not target_uid:
            plugin_event.reply(f"在恋综「{playname}」中未找到「{guest_name}」！")
            return
        timeline = getData("engagement", "timeline.json")
        appoint = getData("engagement", "appoint.json")
        msg_appoint = getData("engagement", "msg_appoint.json")
        if playname not in timeline or target_uid not in timeline[playname]:
            plugin_event.reply(
                f"没有找到{guest_name}在恋综「{playname}」中的时间线数据！"
            )
            return
        user_all_timeline = timeline[playname][target_uid]
        host_name = guest_name
        nodes_data = []
        sorted_dates = sorted(user_all_timeline.keys())
        for date_key in sorted_dates:
            user_timeline = user_all_timeline[date_key]
            if not user_timeline:
                continue
            meeting_strs = [f"{playname} {host_name} {date_key} 时间线", ""]
            for time_range, details in sorted(
                user_timeline.items(), key=lambda x: x[0]
            ):
                participant_uid_list = [str(item) for item in details["participants"]]
                participant_uids = set(participant_uid_list)
                participant_names = []
                for p_uid in participant_uid_list:
                    if (
                        playname in privategroup
                        and p_uid in privategroup[playname]
                        and "嘉宾姓名" in privategroup[playname][p_uid]
                    ):
                        participant_names.append(
                            privategroup[playname][p_uid]["嘉宾姓名"]
                        )
                    elif (
                        playname in privategroup
                        and p_uid in privategroup[playname]
                        and "NPC姓名" in privategroup[playname][p_uid]
                    ):
                        participant_names.append(
                            privategroup[playname][p_uid]["NPC姓名"]
                        )
                    else:
                        participant_names.append(str(p_uid))
                if participant_names:
                    time_parts = time_range.split("#", 1)
                    display_time_range = time_parts[0]
                    timeline_code = time_parts[1] if len(time_parts) > 1 else None
                    combined_playtime = f"{date_key} {display_time_range}"
                    groupcodes_found = []
                    for groupcode, appoint_info in appoint.items():
                        if appoint_info.get("playname") != playname:
                            continue
                        if timeline_code and str(groupcode) != timeline_code:
                            continue
                        if appoint_info.get("playtime") != combined_playtime:
                            continue
                        if appoint_info.get("playtype") != details["playtype"]:
                            continue
                        appoint_inviter = appoint_info.get("inviter")
                        appoint_invitee = set(appoint_info.get("invitee", []))
                        appoint_participants_uids = {appoint_inviter} | appoint_invitee
                        if appoint_inviter == "官方":
                            appoint_participants_uids.discard("官方")
                        if appoint_participants_uids == participant_uids:
                            groupcodes_found.append(groupcode)
                    if groupcodes_found:
                        type_line = (
                            f"【{details['playtype']}{'/'.join(groupcodes_found)}】"
                        )
                    else:
                        type_line = f"【{details['playtype']}，已结】"
                    if details["playtype"] == "官约":
                        non_official_names = (
                            participant_names  # 因为官方不在participant_uids中
                        )
                    else:
                        non_official_names = participant_names
                    round_text, status_lines = _monitor_timeline_status(
                        playname,
                        groupcodes_found,
                        appoint,
                        msg_appoint,
                        privategroup,
                        target_uid,
                    )
                    meeting_strs.append(type_line)
                    meeting_strs.append(
                        f"{display_time_range}，{'x'.join(non_official_names)}"
                        f"{f' {round_text}' if round_text else ''}"
                    )
                    meeting_strs.extend(status_lines)
                    meeting_strs.append("")
            if len(meeting_strs) > 2:
                node_content = "\n".join(meeting_strs).strip()
                nodes_data.append({"bot_id": bot_id, "content_text": node_content})
        if not nodes_data:
            target_name = guest_name
            plugin_event.reply(f"没有找到{target_name}在{playname}的时间线数据噢！")
            return
        result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            plugin_event.reply(
                f"发送合并转发消息失败，错误信息：{result.get('message', '未知错误')}。请联系骰主。"
            )

    elif re.match(r"^([\w\W]+?)\s*时间线$", message):
        apply_info = re.match(r"^([\w\W]+?)\s*时间线$", message)
        playname = apply_info.group(1).strip()
        privategroup = getData("groupcollection", "privategroup.json")
        timeline = getData("engagement", "timeline.json")
        appoint = getData("engagement", "appoint.json")
        msg_appoint = getData("engagement", "msg_appoint.json")
        if playname not in privategroup:
            return
        if playname not in timeline or uid not in timeline[playname]:
            plugin_event.reply(
                f"没有找到{sender}在恋综「{playname}」中的时间线数据噢！"
            )
            return
        user_groupid = None
        if playname in privategroup and uid in privategroup[playname]:
            user_groupid = privategroup[playname][uid].get("个人群号") or privategroup[
                playname
            ][uid].get("NPC群号")
        if user_groupid != groupid:
            plugin_event.reply(f"请前往个人群中查询时间线数据噢！")
            return
        user_all_timeline = timeline[playname][uid]
        host_name = uid
        if playname in privategroup and uid in privategroup[playname]:
            host_data = privategroup[playname][uid]
            host_name = host_data.get("嘉宾姓名") or host_data.get("NPC姓名")
        if not user_all_timeline:
            target_name = host_name if host_name != uid else sender
            plugin_event.reply(f"没有找到{target_name}在{playname}的时间线数据噢！")
            return
        nodes_data = []
        sorted_dates = sorted(user_all_timeline.keys())
        for date_key in sorted_dates:
            user_timeline = user_all_timeline[date_key]
            if not user_timeline:
                continue
            meeting_strs = [f"{playname} {host_name} {date_key} 时间线", ""]
            for time_range, details in sorted(
                user_timeline.items(), key=lambda x: x[0]
            ):
                participant_uid_list = [str(item) for item in details["participants"]]
                participant_uids = set(participant_uid_list)
                participant_names = []
                for p_uid in participant_uid_list:
                    if (
                        playname in privategroup
                        and p_uid in privategroup[playname]
                        and "嘉宾姓名" in privategroup[playname][p_uid]
                    ):
                        participant_names.append(
                            privategroup[playname][p_uid]["嘉宾姓名"]
                        )
                    elif (
                        playname in privategroup
                        and p_uid in privategroup[playname]
                        and "NPC姓名" in privategroup[playname][p_uid]
                    ):
                        participant_names.append(
                            privategroup[playname][p_uid]["NPC姓名"]
                        )
                    else:
                        participant_names.append(str(p_uid))
                if participant_names:
                    time_parts = time_range.split("#", 1)
                    display_time_range = time_parts[0]
                    timeline_code = time_parts[1] if len(time_parts) > 1 else None
                    combined_playtime = f"{date_key} {display_time_range}"
                    groupcodes_found = []
                    for groupcode, appoint_info in appoint.items():
                        if appoint_info.get("playname") != playname:
                            continue
                        if timeline_code and str(groupcode) != timeline_code:
                            continue
                        if appoint_info.get("playtime") != combined_playtime:
                            continue
                        if appoint_info.get("playtype") != details["playtype"]:
                            continue
                        appoint_inviter = appoint_info.get("inviter")
                        appoint_invitee = set(appoint_info.get("invitee", []))
                        appoint_participants_uids = {appoint_inviter} | appoint_invitee
                        if appoint_inviter == "官方":
                            appoint_participants_uids.discard("官方")
                        if appoint_participants_uids == participant_uids:
                            groupcodes_found.append(groupcode)
                    if groupcodes_found:
                        type_line = (
                            f"【{details['playtype']}{'/'.join(groupcodes_found)}】"
                        )
                    else:
                        type_line = f"【{details['playtype']}，已结】"
                    if details["playtype"] == "官约":
                        non_official_names = (
                            participant_names  # 因为官方不在participant_uids中
                        )
                    else:
                        non_official_names = participant_names
                    round_text, status_lines = _monitor_timeline_status(
                        playname,
                        groupcodes_found,
                        appoint,
                        msg_appoint,
                        privategroup,
                        uid,
                    )
                    meeting_strs.append(type_line)
                    meeting_strs.append(
                        f"{display_time_range}，{'x'.join(non_official_names)}"
                        f"{f' {round_text}' if round_text else ''}"
                    )
                    meeting_strs.extend(status_lines)
                    meeting_strs.append("")
            if len(meeting_strs) > 2:
                node_content = "\n".join(meeting_strs).strip()
                nodes_data.append({"bot_id": bot_id, "content_text": node_content})
        if not nodes_data:
            target_name = host_name if host_name != uid else sender
            plugin_event.reply(f"没有找到{target_name}在{playname}的时间线数据噢！")
            return
        result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            plugin_event.reply(
                f"发送合并转发消息失败，错误信息：{result.get('message', '未知错误')}。请联系骰主。"
            )

    elif re.match(r"^(.+?)\s*删除(\d+)号(嘉宾|NPC)个人群$", message):
        match = re.match(r"^(.+?)\s*删除(\d+)号(嘉宾|NPC)个人群$", message)
        if match:
            playname = match.group(1).strip()
            guest_number = int(match.group(2))
            guest_type = match.group(3)
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可删除个人群。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            manage_group = register[playname].get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中删除个人群。")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup or not privategroup[playname]:
                plugin_event.reply(f"恋综「{playname}」暂无个人群数据。")
                return
            guest_to_delete = None
            guest_uid_to_delete = None
            for guest_uid, guest_info in privategroup[playname].items():
                if guest_type == "嘉宾":
                    if guest_info.get("嘉宾编号") == guest_number:
                        guest_to_delete = guest_info
                        guest_uid_to_delete = guest_uid
                        break
                else:
                    if guest_info.get("NPC编号") == guest_number:
                        guest_to_delete = guest_info
                        guest_uid_to_delete = guest_uid
                        break
            if not guest_to_delete:
                plugin_event.reply(
                    f"恋综「{playname}」中未找到{guest_number}号{guest_type}。"
                )
                return
            if guest_type == "嘉宾":
                deleted_guest_name = guest_to_delete.get("嘉宾姓名", "未知")
                deleted_guest_groupid = guest_to_delete.get("个人群号", "未知")
                del privategroup[playname][guest_uid_to_delete]
            else:
                deleted_guest_name = guest_to_delete.get("NPC姓名", "未知")
                deleted_guest_groupid = guest_to_delete.get("NPC群号", "未知")
                del privategroup[playname][guest_uid_to_delete]
            remaining_guests = []
            for guest_uid, guest_info in privategroup[playname].items():
                if guest_type == "嘉宾" and "嘉宾编号" in guest_info:
                    remaining_guests.append((guest_uid, guest_info))
                elif guest_type == "NPC" and "NPC编号" in guest_info:
                    remaining_guests.append((guest_uid, guest_info))
            remaining_guests.sort(
                key=lambda x: x[1].get(
                    "嘉宾编号" if guest_type == "嘉宾" else "NPC编号", 0
                )
            )
            for i, (guest_uid, guest_info) in enumerate(remaining_guests, 1):
                if guest_type == "嘉宾":
                    guest_info["嘉宾编号"] = i
                else:
                    guest_info["NPC编号"] = i
            if not privategroup[playname]:
                del privategroup[playname]
            setData("groupcollection", "privategroup.json", privategroup)
            remaining_count = len(remaining_guests)
            reply_msg = f"已删除恋综「{playname}」的{guest_number}号{guest_type}{deleted_guest_name}（个人群号：{deleted_guest_groupid}）\n\n"
            reply_msg += f"已将剩余{remaining_count}位{guest_type}重新编号。\n\n"
            reply_msg += "如需继续删除，请重新查看列表以获取最新编号。"
            plugin_event.reply(reply_msg)
            return

    elif re.match(r"^(.+?)\s*D(\d+)\s*补戏$", message):
        match = re.match(r"^(.+?)\s*D(\d+)\s*补戏$", message)
        if match:
            import datetime

            playname = match.group(1).strip()
            virtual_day = int(match.group(2))
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可操作补戏指令。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            current_group = str(plugin_event.data.group_id)
            if current_group != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中操作补戏。")
                return
            start_date_str = data["start_date"]
            end_date_str = data.get("end_date", "")
            from datetime import datetime

            start_date = datetime.strptime(start_date_str, "%Y%m%d")
            end_date = (
                datetime.strptime(end_date_str, "%Y%m%d")
                if end_date_str
                else start_date
            )
            original_total_days = (end_date - start_date).days + 1
            if virtual_day < 0 or virtual_day >= original_total_days:
                plugin_event.reply(
                    f"日期D{virtual_day}无效。恋综「{playname}」的日程范围为D0到D{original_total_days-1}。"
                )
                return
            supplements = data.get("supplements", {})
            virtual_day_str = str(virtual_day)
            current_supplement = supplements.get(virtual_day_str, 0)
            supplements[virtual_day_str] = current_supplement + 1
            data["supplements"] = supplements
            from datetime import timedelta

            total_supplement_days = sum(supplements.values())
            new_end_date = end_date + timedelta(days=total_supplement_days)
            data["current_end_date"] = new_end_date.strftime("%Y%m%d")
            setData("groupcollection", "register.json", register)
            new_total_days = original_total_days + total_supplement_days
            reply_msg = f"恋综「{playname}」的D{virtual_day}已增加1天补戏。\n\n"
            reply_msg += f"原始日程：{start_date_str}-{end_date_str}，共{original_total_days}日\n"
            reply_msg += f"当前日程：{start_date_str}-{new_end_date.strftime('%Y%m%d')}，共{new_total_days}日\n"
            reply_msg += f"补戏信息：\n"
            if supplements:
                for v_day, count in sorted(
                    supplements.items(), key=lambda x: int(x[0])
                ):
                    reply_msg += f"D{v_day}：{count}天补戏\n"
            else:
                reply_msg += "暂无补戏\n"
            reply_msg += f"\n如需继续补戏，请再次发送补戏指令。"
            plugin_event.reply(reply_msg)
            return

    elif re.match(r"^(.+?)\s*D(\d+)\s*取消补戏$", message):
        match = re.match(r"^(.+?)\s*D(\d+)\s*取消补戏$", message)
        if match:
            playname = match.group(1).strip()
            virtual_day = int(match.group(2))
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主可操作取消补戏指令。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            current_group = str(plugin_event.data.group_id)
            if current_group != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中取消补戏。")
                return
            start_date_str = data["start_date"]
            end_date_str = data.get("end_date", "")
            from datetime import datetime, timedelta

            start_date = datetime.strptime(start_date_str, "%Y%m%d")
            end_date = (
                datetime.strptime(end_date_str, "%Y%m%d")
                if end_date_str
                else start_date
            )
            if "supplements" not in data or not data["supplements"]:
                plugin_event.reply(f"恋综「{playname}」目前没有任何补戏记录。")
                return
            supplements = data["supplements"]
            virtual_day_str = str(virtual_day)
            if virtual_day_str not in supplements or supplements[virtual_day_str] <= 0:
                plugin_event.reply(
                    f"恋综「{playname}」的D{virtual_day}没有补戏记录，无法取消。"
                )
                return
            current_supplement = supplements[virtual_day_str]
            new_supplement = current_supplement - 1
            supplements_deleted = False
            if new_supplement <= 0:
                del supplements[virtual_day_str]
                if not supplements:
                    del data["supplements"]
                    supplements_deleted = True
                    if "current_end_date" in data:
                        del data["current_end_date"]
            else:
                supplements[virtual_day_str] = new_supplement
            if not supplements_deleted:
                total_supplement_days = sum(supplements.values())
                if total_supplement_days > 0:
                    new_end_date = end_date + timedelta(days=total_supplement_days)
                    data["current_end_date"] = new_end_date.strftime("%Y%m%d")
                else:
                    del data["current_end_date"]
            setData("groupcollection", "register.json", register)
            original_total_days = (end_date - start_date).days + 1
            total_supplement_days = sum(supplements.values()) if supplements else 0
            new_total_days = original_total_days + total_supplement_days
            if supplements_deleted:
                display_end_date = end_date_str
            else:
                display_end_date = data.get("current_end_date", end_date_str)
            reply_msg = f"恋综「{playname}」的D{virtual_day}已取消1天补戏。\n\n"
            reply_msg += f"原始日程：{start_date_str}-{end_date_str}，共{original_total_days}日\n"
            if supplements:
                reply_msg += f"当前日程：{start_date_str}-{display_end_date}，共{new_total_days}日\n"
                reply_msg += f"剩余补戏信息：\n"
                for v_day, count in sorted(
                    supplements.items(), key=lambda x: int(x[0])
                ):
                    reply_msg += f"D{v_day}：{count}天补戏\n"
            else:
                reply_msg += f"所有补戏已取消，回归原始日程。\n"
            plugin_event.reply(reply_msg)
            return

    elif re.match(r"^(.+?)\s*统计$", message):
        match = re.match(r"^(.+?)\s*统计$", message)
        if match:
            playname = match.group(1).strip()
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                return
            if uid not in privategroup[playname]:
                plugin_event.reply(
                    f"{sender}不是恋综「{playname}」的嘉宾，无法查看互动。"
                )
                return
            user_info = privategroup[playname][uid]
            user_name = (
                user_info.get("嘉宾姓名")
                if "嘉宾姓名" in user_info
                else user_info.get("NPC姓名", "未知")
            )
            from datetime import datetime

            current_time = datetime.now()
            try:
                lettertime_data = getData("groupcollection", "lettertime.json")
                letter_time_str = lettertime_data.get(playname, {}).get("time", "22:30")
                letter_time = datetime.strptime(letter_time_str, "%H:%M").time()
            except Exception as e:
                letter_time = datetime.strptime("22:30", "%H:%M").time()
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            virtual_to_real = {}
            for real_date, virtual_day in real_to_virtual.items():
                virtual_day_str = str(virtual_day)
                if virtual_day_str not in virtual_to_real:
                    virtual_to_real[virtual_day_str] = []
                virtual_to_real[virtual_day_str].append(real_date)
            register = getData("groupcollection", "register.json")
            reg_data = register[playname]
            start_date_str = reg_data["start_date"]
            end_date_str = reg_data.get("end_date", "")
            start_date = datetime.strptime(start_date_str, "%Y%m%d")
            if end_date_str:
                end_date = datetime.strptime(end_date_str, "%Y%m%d")
                original_total_days = (end_date - start_date).days + 1
            else:
                original_total_days = 1
            current_date_str = current_time.strftime("%y%m%d")
            current_virtual_day = (
                str(real_to_virtual.get(current_date_str))
                if current_date_str in real_to_virtual
                else None
            )
            stats = {}
            total_counts = {
                "私约": 0,
                "电话": 0,
                "前置电话": 0,
                "心愿": 0,
                "微信": 0,
                "官约": 0,
            }
            for virtual_day in range(original_total_days):
                stats[str(virtual_day)] = {
                    "playtype_counts": {
                        "私约": 0,
                        "电话": 0,
                        "前置电话": 0,
                        "心愿": 0,
                        "微信": 0,
                        "官约": 0,
                    },
                    "send": {"礼物": 0, "短信": 0, "小纸条": 0, "心动信": 0},
                    "receive": {"礼物": 0, "短信": 0, "小纸条": 0, "心动信": 0},
                }
            timeline = getData("engagement", "timeline.json")
            if playname in timeline and uid in timeline[playname]:
                user_timeline = timeline[playname][uid]
                for virtual_day_str, day_data in user_timeline.items():
                    if virtual_day_str.startswith("D"):
                        virtual_day = virtual_day_str[1:]
                        if virtual_day in stats:
                            for time_range, details in day_data.items():
                                playtype = details.get("playtype", "")
                                if playtype in stats[virtual_day]["playtype_counts"]:
                                    stats[virtual_day]["playtype_counts"][playtype] += 1
                                    # 累加到合计统计
                                    if playtype in total_counts:
                                        total_counts[playtype] += 1

            def count_interaction(data_dict, interaction_type):
                for key, _ in data_dict.items():
                    parts = key.split("/////")
                    if len(parts) >= 5 and parts[0] == playname:
                        data_date = parts[1]
                        sender_uid = parts[2]
                        receiver_uid = parts[3]
                        if data_date in real_to_virtual:
                            virtual_day = str(real_to_virtual[data_date])
                            if sender_uid == uid:
                                stats[virtual_day]["send"][interaction_type] += 1
                            if receiver_uid == uid:
                                stats[virtual_day]["receive"][interaction_type] += 1

            letters = getData("sendmessage", "letters.json")
            gifts = getData("sendmessage", "gifts.json")
            notes = getData("sendmessage", "notes.json")
            count_interaction(letters, "心动信")
            count_interaction(gifts, "礼物")
            count_interaction(notes, "小纸条")
            title_content = f"{playname} {user_name}\n\n"
            total_lines = []
            for playtype in ["私约", "电话", "心愿", "微信", "官约"]:
                if total_counts[playtype] > 0:
                    total_lines.append(f"{playtype}合计：{total_counts[playtype]}")
            if total_lines:
                title_content += "\n".join(total_lines) + "\n"
            else:
                title_content += "暂无记录\n"
            nodes_data = [{"bot_id": bot_id, "content_text": title_content.strip()}]
            sorted_days = sorted(stats.keys(), key=lambda x: int(x))
            for virtual_day in sorted_days:
                day_stats = stats[virtual_day]
                has_data = False
                for count in day_stats["playtype_counts"].values():
                    if count > 0:
                        has_data = True
                        break
                for count in day_stats["send"].values():
                    if count > 0:
                        has_data = True
                        break
                for count in day_stats["receive"].values():
                    if count > 0:
                        has_data = True
                        break
                if not has_data:
                    continue
                real_dates = virtual_to_real.get(virtual_day, [])
                if not real_dates:
                    continue
                real_dates.sort()
                can_show_heart_letter = False
                if virtual_day == current_virtual_day:
                    if current_time.time() >= letter_time:
                        can_show_heart_letter = True
                else:
                    last_real_date = real_dates[-1]
                    try:
                        last_date = datetime.strptime(last_real_date, "%y%m%d")
                        last_day_letter_time = datetime.combine(last_date, letter_time)
                        if current_time >= last_day_letter_time:
                            can_show_heart_letter = True
                    except:
                        can_show_heart_letter = True
                content_text = f"D{virtual_day}\n\n"
                playtype_lines = []
                for playtype, count in day_stats["playtype_counts"].items():
                    if count > 0:
                        playtype_lines.append(f"{playtype}：{count}")
                if playtype_lines:
                    content_text += "\n".join(playtype_lines) + "\n"
                send_lines = []
                for item_type, count in day_stats["send"].items():
                    if count > 0:
                        send_lines.append(f"{item_type}：{count}")
                if send_lines:
                    content_text += "\n【发】\n" + "\n".join(send_lines) + "\n"
                receive_lines = []
                for item_type, count in day_stats["receive"].items():
                    if item_type == "心动信":
                        if can_show_heart_letter:
                            if count > 0:
                                receive_lines.append(f"{item_type}：{count}")
                        else:
                            receive_lines.append(f"{item_type}：发信后显示")
                    else:
                        if count > 0:
                            receive_lines.append(f"{item_type}：{count}")
                if receive_lines:
                    content_text += "\n【收】\n" + "\n".join(receive_lines) + "\n"
                nodes_data.append(
                    {"bot_id": bot_id, "content_text": content_text.strip()}
                )
            if len(nodes_data) <= 1:
                plugin_event.reply(
                    f"{user_name}在恋综「{playname}」中暂无任何互动记录。"
                )
                return
            result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
            if result.get("retcode") != 0:
                plugin_event.reply(
                    f"合并转发消息构造失败，{result.get('message', '未知错误')}"
                )
                return

    elif re.match(r"^(.+?)\s*数量$", message):
        match = re.match(r"^(.+?)\s*数量$", message)
        if match:
            playname = match.group(1).strip()
            register = getData("groupcollection", "register.json")
            if playname not in register:
                return
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            from datetime import datetime

            today = datetime.now()
            today_date = today.date()
            today_6 = today.strftime("%y%m%d")
            if today_6 not in real_to_virtual:
                plugin_event.reply(f"今天不在{playname}的恋综日程内，无法查询噢！")
                return
            virtual_day = real_to_virtual[today_6]
            dates_to_count = []
            for date_str, v_day in real_to_virtual.items():
                if v_day == virtual_day:
                    dates_to_count.append(date_str)
            data_sources = [
                ("心动信", "letters.json"),
                ("小纸条", "notes.json"),
                ("礼物", "gifts.json"),
                ("短信", "sms.json"),
            ]
            counts = {}
            total_count = 0
            for data_type, filename in data_sources:
                try:
                    data_list = getData("sendmessage", filename)
                    count = 0
                    for data in data_list:
                        datalist = data.split("/////")
                        if len(datalist) >= 2:
                            data_playname = datalist[0].strip()
                            data_date = datalist[1].strip()
                            if (
                                data_playname == playname
                                and data_date in dates_to_count
                            ):
                                count += 1
                    counts[data_type] = count
                    total_count += count
                except Exception as e:
                    counts[data_type] = 0
            timeline = getData("engagement", "timeline.json")
            timeline_counts = {
                "私约": 0,
                "电话": 0,
                "前置电话": 0,
                "心愿": 0,
                "微信": 0,
            }
            if playname in timeline:
                virtual_day_str = f"D{virtual_day}"
                counted_interactions = set()
                for guest_uid, guest_timeline in timeline[playname].items():
                    if virtual_day_str in guest_timeline:
                        day_data = guest_timeline[virtual_day_str]
                        for time_range, details in day_data.items():
                            playtype = details.get("playtype", "")
                            if playtype not in timeline_counts:
                                continue
                            participants = details.get("participants", [])
                            if len(participants) < 2:
                                continue
                            if not participants:
                                continue
                            sorted_participants = sorted([str(p) for p in participants])
                            interaction_key = f"{','.join(sorted_participants)}|{time_range}|{playtype}"
                            if interaction_key not in counted_interactions:
                                counted_interactions.add(interaction_key)
                                timeline_counts[playtype] += 1
            timeline_total = sum(timeline_counts.values())
            virtual_day_display = f"D{virtual_day}"
            date_info = ""
            if len(dates_to_count) > 1:
                dates_to_count.sort()
                date_info = f"\n（补戏日：{dates_to_count[0]}-{dates_to_count[-1]}）"
            has_data = timeline_total > 0 or total_count > 0
            if not has_data:
                plugin_event.reply(
                    f"{playname} {virtual_day_display}{date_info}\n\n今日暂无互动数据"
                )
                return
            msg = f"{playname} {virtual_day_display}{date_info}\n\n"
            for playtype, count in timeline_counts.items():
                if count > 0:
                    msg += f"{playtype}：{count}\n"
            for data_type, count in counts.items():
                if count > 0:
                    msg += f"{data_type}：{count}\n"
            plugin_event.reply(msg)

    elif re.match(r"^(.+?)\s*统计所有嘉宾$", message):
        match = re.match(r"^(.+?)\s*统计所有嘉宾$", message)
        if match:
            playname = match.group(1).strip()
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可查看所有嘉宾互动。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            reg_data = register[playname]
            manage_group = reg_data.get("manage_group")
            current_group = str(plugin_event.data.group_id)
            if current_group != manage_group:
                plugin_event.reply(
                    f"请在恋综「{playname}」的后台群中查看所有嘉宾统计。"
                )
                return
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(f"无法获取恋综「{playname}」的日期映射信息。")
                return
            start_date_str = reg_data["start_date"]
            end_date_str = reg_data.get("end_date", "")
            from datetime import datetime

            start_date = datetime.strptime(start_date_str, "%Y%m%d")
            if end_date_str:
                end_date = datetime.strptime(end_date_str, "%Y%m%d")
                original_total_days = (end_date - start_date).days + 1
            else:
                original_total_days = 1
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup or not privategroup[playname]:
                plugin_event.reply(f"恋综「{playname}」暂无嘉宾数据。")
                return
            timeline = getData("engagement", "timeline.json")
            letters = getData("sendmessage", "letters.json")
            gifts = getData("sendmessage", "gifts.json")
            notes = getData("sendmessage", "notes.json")
            arc_records = getData(
                _monitor_record_namespace(playname),
                _monitor_arc_filename(playname),
            )

            def init_guest_stats():
                return {
                    "playtype_counts": {
                        "私约": 0,
                        "电话": 0,
                        "前置电话": 0,
                        "心愿": 0,
                        "微信": 0,
                        "官约": 0,
                    },
                    "send": {"礼物": 0, "短信": 0, "小纸条": 0, "心动信": 0},
                    "receive": {"礼物": 0, "短信": 0, "小纸条": 0, "心动信": 0},
                }

            def format_guest_arc(uid):
                user_stats = arc_records.get(str(uid), {})
                count = int(user_stats.get("response_count", 0) or 0)
                rounds = int(user_stats.get("rounds", 0) or 0)
                total_words = int(user_stats.get("word_count", 0) or 0)
                if not count and not rounds and not total_words:
                    return "平均弧长：暂无有效记录\n记录回合：0", False
                average_hours = (
                    round(int(user_stats.get("total_minutes", 0) or 0) / count / 60, 1)
                    if count
                    else 0
                )
                average_words = round(total_words / rounds) if rounds else 0
                return f"平均弧长：{average_hours}h/{average_words}字\n记录回合：{rounds}", True

            all_guests_stats = {}
            for guest_uid in privategroup[playname].keys():
                all_guests_stats[guest_uid] = {}
                for virtual_day in range(original_total_days):
                    all_guests_stats[guest_uid][str(virtual_day)] = init_guest_stats()
            if playname in timeline:
                for guest_uid, guest_timeline in timeline[playname].items():
                    if guest_uid not in all_guests_stats:
                        all_guests_stats[guest_uid] = {}
                        for virtual_day in range(original_total_days):
                            all_guests_stats[guest_uid][
                                str(virtual_day)
                            ] = init_guest_stats()
                    for virtual_day_str, day_data in guest_timeline.items():
                        if virtual_day_str.startswith("D"):
                            virtual_day = virtual_day_str[1:]
                            if virtual_day in all_guests_stats[guest_uid]:
                                for time_range, details in day_data.items():
                                    playtype = details.get("playtype", "")
                                    if (
                                        playtype
                                        in all_guests_stats[guest_uid][virtual_day][
                                            "playtype_counts"
                                        ]
                                    ):
                                        all_guests_stats[guest_uid][virtual_day][
                                            "playtype_counts"
                                        ][playtype] += 1

            def count_interaction(data_dict, interaction_type):
                for key, _ in data_dict.items():
                    parts = key.split("/////")
                    if len(parts) >= 5 and parts[0] == playname:
                        data_date = parts[1]
                        sender = parts[2]
                        receiver = parts[3]
                        if data_date in real_to_virtual:
                            virtual_day = str(real_to_virtual[data_date])
                            if sender not in all_guests_stats:
                                all_guests_stats[sender] = {}
                                for vday in range(original_total_days):
                                    all_guests_stats[sender][
                                        str(vday)
                                    ] = init_guest_stats()
                            if receiver not in all_guests_stats:
                                all_guests_stats[receiver] = {}
                                for vday in range(original_total_days):
                                    all_guests_stats[receiver][
                                        str(vday)
                                    ] = init_guest_stats()
                            if virtual_day in all_guests_stats[sender]:
                                all_guests_stats[sender][virtual_day]["send"][
                                    interaction_type
                                ] += 1
                            if virtual_day in all_guests_stats[receiver]:
                                all_guests_stats[receiver][virtual_day]["receive"][
                                    interaction_type
                                ] += 1

            count_interaction(letters, "心动信")
            count_interaction(gifts, "礼物")
            count_interaction(notes, "小纸条")
            nodes_data = []
            guests_list = []
            for guest_uid in all_guests_stats:
                guest_info = privategroup[playname].get(guest_uid, {})
                guest_number = 0
                guest_name = f"用户{guest_uid}"
                is_npc = False
                if "嘉宾姓名" in guest_info:
                    guest_number = guest_info.get("嘉宾编号", 0)
                    guest_name = guest_info.get("嘉宾姓名", guest_name)
                elif "NPC姓名" in guest_info:
                    guest_number = guest_info.get("NPC编号", 0)
                    guest_name = guest_info.get("NPC姓名", guest_name)
                    is_npc = True
                arc_text, has_arc_data = format_guest_arc(guest_uid)
                guests_list.append(
                    {
                        "uid": guest_uid,
                        "number": guest_number,
                        "name": guest_name,
                        "is_npc": is_npc,
                        "stats": all_guests_stats[guest_uid],
                        "arc_text": arc_text,
                        "has_arc_data": has_arc_data,
                    }
                )
            guests_list.sort(
                key=lambda x: (x["number"], 1 if x["is_npc"] else 0, x["uid"])
            )
            for guest in guests_list:
                guest_name = guest["name"]
                guest_stats = guest["stats"]
                is_npc = guest["is_npc"]
                has_any_data = guest["has_arc_data"]
                for day_stats in guest_stats.values():
                    for count in day_stats["playtype_counts"].values():
                        if count > 0:
                            has_any_data = True
                            break
                    for count in day_stats["send"].values():
                        if count > 0:
                            has_any_data = True
                            break
                    for count in day_stats["receive"].values():
                        if count > 0:
                            has_any_data = True
                            break
                    if has_any_data:
                        break
                if not has_any_data:
                    continue
                display_name = f"{guest_name}（NPC）" if is_npc else guest_name
                content_text = f"【{display_name}】\n{guest['arc_text']}\n-\n"
                sorted_days = sorted(guest_stats.keys(), key=lambda x: int(x))
                for virtual_day in sorted_days:
                    day_stats = guest_stats[virtual_day]
                    has_day_data = False
                    for count in day_stats["playtype_counts"].values():
                        if count > 0:
                            has_day_data = True
                            break
                    for count in day_stats["send"].values():
                        if count > 0:
                            has_day_data = True
                            break
                    for count in day_stats["receive"].values():
                        if count > 0:
                            has_day_data = True
                            break
                    if not has_day_data:
                        continue
                    content_text += f"D{virtual_day}："
                    day_parts = []
                    for playtype, count in day_stats["playtype_counts"].items():
                        if count > 0:
                            day_parts.append(f"{playtype}{count}")
                    send_parts = []
                    for item_type, count in day_stats["send"].items():
                        if count > 0:
                            send_parts.append(f"{item_type}{count}")
                    if send_parts:
                        day_parts.append(f"[发]{''.join(send_parts)}")
                    receive_parts = []
                    for item_type, count in day_stats["receive"].items():
                        if count > 0:
                            receive_parts.append(f"{item_type}{count}")
                    if receive_parts:
                        day_parts.append(f"[收]{''.join(receive_parts)}")
                    if day_parts:
                        content_text += "，".join(day_parts) + "\n-\n"
                if content_text.strip() == f"【{display_name}】":
                    continue
                nodes_data.append(
                    {"bot_id": bot_id, "content_text": content_text.strip()}
                )
            if not nodes_data:
                plugin_event.reply(f"恋综「{playname}」的所有嘉宾均无互动记录。")
                return
            result = send_forward_message(
                bot_port, bot_token, current_group, nodes_data
            )
            if result.get("retcode") != 0:
                plugin_event.reply(
                    f"合并转发消息构造失败，{result.get('message', '未知错误')}"
                )
                return

    elif re.match(
        r"\[OP:reply,id=(-?\d+)\]\[OP:at,id=(\d+)\]\s*(.+?)\s*拒绝关系线$",
        message,
    ):
        match = re.match(
            r"\[OP:reply,id=(-?\d+)\]\[OP:at,id=(\d+)\]\s*(.+?)\s*拒绝关系线$",
            message,
        )
        if match:
            reply_id = match.group(1)
            at_id = match.group(2)
            playname = match.group(3).strip()
            if at_id != str(plugin_event.bot_info.id):
                plugin_event.reply("@错啦！请@骰子噢！")
                return
            replied_msg = plugin_event.get_msg(reply_id)["data"]
            raw_message = replied_msg.get("raw_message", "")
            if not raw_message:
                plugin_event.reply("引用的消息转译失败！")
                return
            forward_match = re.search(r"\[(?:OP|CQ):forward,id=([^,\]]+)\]", raw_message)
            if not forward_match:
                plugin_event.reply(
                    "未找到合并转发消息，请确保引用了关系线合并转发消息！"
                )
                return
            message_id = forward_match.group(1)
            forward_messages, error_msg = get_forward_messages(
                plugin_event, message_id, bot_port, bot_token
            )
            if error_msg:
                plugin_event.reply(error_msg)
                return
            if not forward_messages:
                plugin_event.reply("合并转发消息内容为空！")
                return
            first_message_content = forward_messages[0].get("content", [])
            if not first_message_content:
                plugin_event.reply("第一条消息内容为空！")
                return
            first_text_content = ""
            for content_item in first_message_content:
                if content_item.get("type") == "text":
                    first_text_content += content_item.get("data", {}).get("text", "")
            if "\n" in first_text_content:
                first_line = first_text_content.split("\n")[0].strip()
            else:
                first_line = first_text_content.strip()
            if "→" in first_line:
                direction_parts = first_line.split("→")
                if len(direction_parts) != 2:
                    plugin_event.reply("后台关系线数据错误，请联系骰主检查！")
                    return
                sender_name = direction_parts[0].strip()
                receiver_name = direction_parts[1].strip()
                try:
                    relation_data = getData("relation", f"{playname}.json")
                except:
                    plugin_event.reply(f"未找到用户在恋综「{playname}」的关系线数据！")
                    return
                relation_key = None
                if first_line in relation_data:
                    relation_key = first_line
                else:
                    names_sorted = sorted([sender_name, receiver_name])
                    standardized_key = f"{names_sorted[0]}→{names_sorted[1]}"
                    if standardized_key in relation_data:
                        relation_key = standardized_key
                if not relation_key:
                    plugin_event.reply(
                        f"未找到关系线「{first_line}」的数据，请联系骰主检查！！"
                    )
                    return
                privategroup = getData("groupcollection", "privategroup.json")
                if playname not in privategroup:
                    plugin_event.reply(
                        f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                    )
                    return
                current_user_name = None
                current_user_uid = uid
                for guest_uid, guest_info in privategroup[playname].items():
                    if guest_uid == current_user_uid:
                        if guest_info.get("嘉宾姓名"):
                            current_user_name = guest_info.get("嘉宾姓名")
                            break
                        elif guest_info.get("NPC姓名"):
                            current_user_name = guest_info.get("NPC姓名")
                            break
                if not current_user_name:
                    plugin_event.reply(
                        f"{sender}不是恋综「{playname}」的嘉宾或NPC，无法拒绝关系线噢！"
                    )
                    return
                if playname in privategroup and uid in privategroup[playname]:
                    user_groupid = privategroup[playname][uid].get(
                        "个人群号"
                    ) or privategroup[playname][uid].get("NPC群号")
                if user_groupid != groupid:
                    plugin_event.reply(f"请前往个人群中拒绝关系线噢！")
                    return
                other_party_name = None
                if current_user_name == sender_name:
                    other_party_name = receiver_name
                elif current_user_name == receiver_name:
                    other_party_name = sender_name
                else:
                    plugin_event.reply(
                        f"{sender}不是这条关系线的发送者或接收者，无法拒绝关系线噢！"
                    )
                    return
                other_party_uid = None
                other_party_group_id = None
                for guest_uid, guest_info in privategroup[playname].items():
                    name_match = False
                    if guest_info.get("嘉宾姓名") == other_party_name:
                        name_match = True
                    elif guest_info.get("NPC姓名") == other_party_name:
                        name_match = True
                    if name_match:
                        other_party_uid = guest_uid
                        other_party_group_id = guest_info.get(
                            "个人群号"
                        ) or guest_info.get("NPC群号")
                        break
                relation_contents = relation_data[relation_key]
                if isinstance(relation_contents, dict):
                    numeric_keys = [k for k in relation_contents.keys() if k.isdigit()]
                    if numeric_keys:
                        numeric_keys.sort(key=int)
                        latest_key = numeric_keys[-1]
                        deleted_content = relation_contents[latest_key]
                        del relation_contents[latest_key]
                        if not relation_contents:
                            del relation_data[relation_key]
                            action_desc = "内容已全部清空！"
                        else:
                            action_desc = f"最新的一条内容已删除，如需继续删除，请继续引用并拒绝。"
                        setData("relation", f"{playname}.json", relation_data)
                        plugin_event.reply(f"关系线「{first_line}」的{action_desc}")
                        time.sleep(1)
                        if other_party_group_id:
                            plugin_event.send(
                                "group",
                                other_party_group_id,
                                f"{current_user_name}拒绝了和{other_party_name}的关系线！\n\n{action_desc}",
                            )
                        else:
                            plugin_event.reply(
                                f"无法找到{other_party_name}的个人群号/NPC群号，无法发送通知，请联系骰主检查！"
                            )
                    else:
                        plugin_event.reply(
                            "关系线数据格式错误，没有找到有效的关系线内容！"
                        )
                else:
                    plugin_event.reply("关系线数据格式错误，请联系骰主检查！")
            else:
                plugin_event.reply(
                    "合并转发消息第一行没有找到关系线方向标识（→），请联系骰主检查！"
                )
                return

    elif re.match(r"(.+) 删除关系线 (.+) (.+)", message):
        match = re.match(r"(.+) 删除关系线 (.+) (.+)", message)
        if not match:
            return
        if uid not in masterlist:
            plugin_event.reply("如需删除关系线，请联系骰主开放权限。")
            return
        playname = match.group(1).strip()
        player1_name = match.group(2).strip()
        player2_name = match.group(3).strip()
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中删除关系线！")
            return
        try:
            relation_data = getData("relation", f"{playname}.json")
        except:
            plugin_event.reply(f"未找到恋综「{playname}」的关系线数据！")
            return
        key1 = f"{player1_name}→{player2_name}"
        key2 = f"{player2_name}→{player1_name}"
        relation_key = None
        if key1 in relation_data:
            relation_key = key1
        elif key2 in relation_data:
            relation_key = key2
        if not relation_key:
            plugin_event.reply(
                f"未找到恋综「{playname}」中「{player1_name}」和「{player2_name}」之间的关系线！"
            )
            return
        privategroup = getData("groupcollection", "privategroup.json")
        player1_uid = None
        player1_groupid = None
        player2_uid = None
        player2_groupid = None
        for uid_key, user_data in privategroup[playname].items():
            if (
                user_data.get("嘉宾姓名") == player1_name
                or user_data.get("NPC姓名") == player1_name
            ):
                player1_uid = uid_key
                player1_groupid = user_data.get("个人群号") or user_data.get("NPC群号")
            if (
                user_data.get("嘉宾姓名") == player2_name
                or user_data.get("NPC姓名") == player2_name
            ):
                player2_uid = uid_key
                player2_groupid = user_data.get("个人群号") or user_data.get("NPC群号")
        del relation_data[relation_key]
        setData("relation", f"{playname}.json", relation_data)
        notification_sent = False
        if player1_groupid:
            try:
                plugin_event.send(
                    "group",
                    player1_groupid,
                    f"【通知】\n管理删除了恋综「{playname}」中「{player1_name}」和「{player2_name}」的全部关系线！",
                )
                notification_sent = True
            except Exception as e:
                plugin_event.reply(
                    f"关系线删除成功，但向「{player1_name}」发送通知失败：{str(e)}"
                )
        if player2_groupid:
            try:
                plugin_event.send(
                    "group",
                    player2_groupid,
                    f"【通知】\n管理删除了恋综「{playname}」中「{player2_name}」和「{player1_name}」的全部关系线！",
                )
                notification_sent = True
            except Exception as e:
                plugin_event.reply(
                    f"关系线删除成功，但向「{player2_name}」发送通知失败：{str(e)}"
                )
        reply_msg = f"成功删除「{player1_name}」和「{player2_name}」之间的关系线！"
        if notification_sent:
            reply_msg += "已通知至个人群。"
        else:
            reply_msg += "未找到个人群，无法发送通知。"
        plugin_event.reply(reply_msg)

    elif re.match(r"格式\s*\[OP:at,id=(\d+)\]", message):
        match = re.match(r"格式\s*\[OP:at,id=(\d+)\]", message)
        if match:
            at_id = match.group(1)
            if at_id != str(plugin_event.bot_info.id):
                return
            from datetime import datetime

            today_date = datetime.now().strftime("%y%m%d")
            privategroup = getData("groupcollection", "privategroup.json")
            matched_playnames = []
            matched_guest_names = []
            if privategroup:
                for playname, guests in privategroup.items():
                    for uid_str, guest_info in guests.items():
                        if str(uid) != uid_str:
                            continue
                        personal_group = guest_info.get("个人群号")
                        npc_group = guest_info.get("NPC群号")
                        if str(groupid) in (str(personal_group), str(npc_group)):
                            guest_name = (
                                guest_info.get("嘉宾姓名")
                                or guest_info.get("NPC姓名")
                                or "嘉宾姓名"
                            )
                            matched_playnames.append(playname)
                            matched_guest_names.append(guest_name)
            register = getData("groupcollection", "register.json")
            if not matched_playnames:
                for playname, reg_data in register.items():
                    if str(reg_data.get("manage_group")) == str(groupid):
                        matched_playnames.append(playname)
                        matched_guest_names.append("嘉宾姓名")
            if matched_playnames:
                replace_playname = matched_playnames[-1]
                replace_guest_name = matched_guest_names[-1]
                replace_date = today_date
                replace_sender = replace_guest_name
                replace_receiver = ""
            else:
                replace_playname = "恋综名"
                replace_date = "日期"
                replace_sender = "张三"
                replace_receiver = "李四"
                replace_guest_name = "嘉宾姓名"
            arc_time, arc_words = _monitor_arc_settings(replace_playname)
            collection_items = _get_collection_items(register, replace_playname)
            collection_command_text = "/".join(
                f"{item}@骰子" for item in collection_items
            )
            collection_formats = _collection_format_text(
                replace_playname, replace_guest_name, collection_items
            )
            nodes_data = []
            format_texts = [
                f"发送「心动信/小纸条/礼物/短信/送图/心愿/点歌/关系线/留言板/私约/电话/官约/微信@骰子」可快速获得单独的格式。\n收集项格式：{collection_command_text}\n\n录入个人群后则不需要@骰子；格式自动填充恋综名、嘉宾姓名。\n本场收集项格式见下方。",
                f"没写「可为空」的地方不可留白，可以打个符号。\n\n署名不要求写真名。\n\n心动信/小纸条/礼物/短信/留言板均可带图。",
                f"发送「创建预约」可快速获得开群格式（未填充版）。",
                f"{replace_playname} 心动信\n{replace_sender} 致 {replace_receiver}\n内容：\n署名：",
                f"{replace_playname} 礼物\n{replace_sender} 致 {replace_receiver}\n内容：\n署名：",
                f"{replace_playname} 小纸条\n{replace_sender} 致 {replace_receiver}\n内容：\n署名：",
                f"{replace_playname} 短信\n{replace_sender} 致 {replace_receiver}\n内容：\n署名：",
                f"删除心动信\n{replace_playname} 心动信\n{replace_sender} 致 {replace_receiver}\n内容：\n署名：",
                f"心动信@骰子\n\n【说明】\n查询今日已发心动信合集。",
                f"<{replace_playname}·私约/电话/官约/微信>\n邀请者：{replace_guest_name}\n受邀者：{replace_guest_name}，{replace_guest_name}\n时间：D0 07:00-08:30\n地点：\n\n微信不检测时间冲突。",
                f"引用戏文并附文「@骰子 撤戏」\n\n【说明】\n该指令可自助撤回戏录。",
                f"{replace_playname} 弧长\n\n【说明】\n查看当前账号在恋综「{replace_playname}」中的平均弧长、平均字数和记录回合数。\n{arc_time}、字数小于{arc_words}字不计入弧长。",
                f"{replace_playname} 戏录 Dx\n\n【说明】\nDx替换为要查询的日程，例如D0、D1或D2。\n小群自动监听参与者消息并记录弧长，不希望收入戏录的非对戏消息请带（）。",
                f"{replace_playname} 统计\n\n【说明】\n查看日程内自己的所有互动数据",
                f"{replace_playname} 数量\n\n【说明】\n查看今日全体互动数据。\n每天10点、15点、20点、23点59分，自动在公告群播报。",
                f"{replace_playname} 时间线\n\n【说明】\n查看日程内所有时间线。",
                f"{replace_playname} 地点",
                f"{replace_playname} 日程",
                f"<{replace_playname}·心愿>\n内容：\n署名：（可为空）\n时间：D0 07:00-08:00\n地点：",
                f"<{replace_playname}·点歌>\n歌曲：\n留言：（可为空）\n署名：（可为空）\n\n【说明】\n点歌方式1：\n自动搜索，默认发送结果列表的第一首歌。\n「歌曲：」栏可通过「歌名 歌手」的格式控制结果，用空格隔开，如果点歌失败，把歌手删了只写歌名。\n\n点歌方式2：\n引用音乐卡片消息，附文表格。\n\n点歌只发表格，把后面这些删了。",
                collection_formats,
                f"<{replace_playname}·关系线>\n发送者：{replace_guest_name}\n接收者：\n内容：\n\n【说明】\n发送「关系线@骰子」可查看关系线合集。",
                f"<{replace_playname}·留言板bot>\n留言人：（可为空）\n接收人：（可为空）\n内容：",
                f"{replace_playname} 送图\n{replace_sender} 致 {replace_receiver}\n内容：\n署名：\n\n【注意】\n必须附带图片，支持发送原图；恋综日程期间不可送图。\n若对方已将骰子退群，则无法收到图片噢！\n如果没有回执，把图片放在「署名：」栏文本之后。",
                f"删除时间线\n\n发送「拒绝+类型+编号」即可释放双方时间线。\n多人群如需一键删除，请联系管理在后台使用专属指令删除。",
                f"添加/删除额外的时间线\n\n请联系管理在后台使用指令添加。添加后不会创建小群、并默认已结。",
                f"恋综插件当前版本：{CURRENT_VERSION}\n\n「技术支持」探丸借客@临皋闲人（反季节生物改编版）",
            ]
            for text in format_texts:
                nodes_data.append({"bot_id": bot_id, "content_text": text})
            result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
            if result.get("retcode") != 0:
                plugin_event.reply(
                    f"合并转发消息请求失败，请联系骰主：{result.get('message', '未知错误')}"
                )
            return

    elif re.match(r"(.+?)设置收集项\s+(.+)", message):
        match = re.match(r"(.+?)设置收集项\s+(.+)", message)
        if match:
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可设置收集项。")
                return
            playname = match.group(1).strip()
            collection_items = _parse_collection_items(match.group(2))
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
                return
            manage_group = register[playname].get("manage_group")
            if str(groupid) != str(manage_group):
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置收集项。")
                return
            register[playname]["collection_items"] = collection_items
            setData("groupcollection", "register.json", register)
            plugin_event.reply(
                f"恋综「{playname}」收集项已设置为：{'/'.join(collection_items)}"
            )
            return

    elif re.match(r"后台\s*\[OP:at,id=(\d+)\]", message):
        match = re.match(r"后台\s*\[OP:at,id=(\d+)\]", message)
        if not match:
            return
        if match.group(1) != str(plugin_event.bot_info.id):
            return
        register = getData("groupcollection", "register.json")
        matched_playnames = [
            playname
            for playname, reg_data in register.items()
            if str(reg_data.get("manage_group", "")) == str(groupid)
        ]
        if not matched_playnames:
            plugin_event.reply("请在恋综的后台群中查看噢！")
            return
        if len(matched_playnames) > 1:
            plugin_event.reply(
                f"检测到多个恋综使用本群作为后台群，将使用最后一个注册的恋综：{matched_playnames[-1]}\n\n请及时注销恋综，避免数据积压。"
            )
        replace_playname = matched_playnames[-1]
        collection_items = _get_collection_items(register, replace_playname)
        collection_view_text = "\n".join(
            f"{replace_playname}{item}@骰子" for item in collection_items
        )
        collection_random_text = "\n".join(
            f"{replace_playname}{item} 随机编号" for item in collection_items
        )
        collection_delete_text = "\n".join(
            f"删除{replace_playname}{item}，xxx" for item in collection_items
        )
        nodes_data = []
        texts = [
            f"恋综插件当前版本：{CURRENT_VERSION}\n更新恋综插件：发送该指令更新插件。\n\n以下每条消息的第一行文本为指令，其中「默认/恋综名」格式的内容，意味着二选一，如「登记默认群号」或「登记恋综名群号」。\n\n默认池，意味着没有设置专属池的恋综均会调用该池中的小群。专属池的小群用完后，并不会自动跳转默认池，请注意补充小群。\n\n如需设置二维码，请将二维码图片按手册中的要求整理好，放在「data/images/恋综备用群/二维码/默认池」文件夹中，如需设置专属二维码池，请在默认池文件夹旁新建文件夹，命名为「恋综名」。\n\n如需设置群号，请保证所有小群均已打开「通过群号搜索」。",
            f"发送「创建预约」可快速获得开群格式（未填充版）。\n\n支持私约/电话/前置电话/官约/微信。\n官约的邀请者请为空，即便填写了也不占用时间线。\n微信不检测时间冲突，前置电话仅同类型不检测时间冲突。",
            f"{replace_playname} 限制心动信\n\n【说明】\n发送后获得每日限额表格，按需填写。\n冒号后填写数量。\n数量为0，即关闭玩法。\n数量为-1，即移除限制。",
            f"{replace_playname} 限制心动信 Dx 嘉宾/NPC姓名 数量\n\n【说明】\n数量二字改为数字。\n数量为0，即关闭玩法。\n数量为-1，即移除限制。",
            f"{replace_playname} 限制私约/电话/心愿/微信/礼物/小纸条/短信/留言板/点歌 数量\n\n【说明】\n数量二字改为数字。\n数量为0，即关闭玩法。\n数量为-1，即移除限制。\n\n私约/电话/心愿/礼物/小纸条/短信，为每人每日限制。\n留言板/点歌为日程总限制。\n微信仅可限制0或-1。\n\n默认限制全日程，可每天更改。",
            f"{replace_playname} 礼物掉落 戏群0.2 嘉宾群0.3 专属群0.1\n{replace_playname} 小纸条掉落 戏群0.2 嘉宾群0.3 专属群0.1\n{replace_playname} 短信掉落 戏群0.2 嘉宾群0.3 专属群0.1\n掉落群设置 {replace_playname}\n\n【说明】\n每个地点可设置不同概率，概率总和不可超过1；每次判定最多只掉落到一个地点。\n发送「{replace_playname} 礼物/小纸条/短信掉落 关闭」可关闭对应掉落。\n「嘉宾群」会随机掉落到同综其他嘉宾/NPC个人群，排除发件人与收件人。\n「专属群」按收件人查询专属掉落群；发送「掉落群设置 恋综名」获取表格，按“姓名：群号 群号2”填写，多个群会随机选择一个，填写“无”可清空。",
            f"删除心动信的指令在嘉宾的格式中，骰主权限可删除任意心动信。",
            f"通报设置 {replace_playname}\n\n【说明】\n查看当前恋综的出门通报设置；修改骰子返回的表格后整表发送，可覆盖保存。\n通报概率只填数字时默认掉落至戏群；也可填写「戏群0.2 嘉宾群0.3 专属群0.1」，概率总和不可超过1，每次最多只通报到一个地点。\n专属群复用「掉落群设置 恋综名」中的专属掉落群。\n通报对象1匿名、2邀请者、3受邀者、4所有参与者、5参与者分别判定。",
            f"个人群录入 {replace_playname}\n\n【说明】\n代录入格式「嘉宾姓名：张三@对方」",
            f"NPC录入 {replace_playname}\n\n【说明】\n同一恋综的NPC可重复使用同一个个人群。",
            f"{replace_playname} 个人群列表",
            f"{replace_playname} 删除x号嘉宾/NPC个人群",
            f"{replace_playname} 设置戏群名片/头衔\n\n【说明】\n录入皮相后才可以设置头衔，设置头衔需群主权限。",
            f"{replace_playname} 小群催戏\n\n【注意】\n每隔2秒逐个向未结小群催戏，若未结群数量巨大，请谨慎使用以防风险检测。",
            f"{replace_playname} 个人群催戏\n\n【注意】\n每隔2秒逐个向嘉宾个人群催戏。",
            f"一键催戏 {replace_playname}\n\n【说明】\n只提醒超过设置时长的小群，不催微信。尚未开戏时提醒全部参与者；已经开戏时提醒当前待回戏者，并按人向个人群发送一条待处理小群汇总。\n默认催5h以上未回的小群，可使用「设置催戏 {replace_playname} 时长」指令修改，时长为小时数，支持小数。",
            f"{replace_playname} 数量\n\n【说明】\n查看今日全体互动数据。\n每天10点、15点、20点、23点59分，自动在公告群播报。",
            f"删除私约/电话/前置电话/官约/微信+编号\n\n【说明】\n指令中无需+号。\n删除并释放小群+删除时间线。\n删除后会通知至个人群。",
            f"添加时间线：{replace_playname} 嘉宾/NPC姓名 私约/电话/前置电话/官约/微信/心愿 Dx 07:00-23:59\n\n【说明】\n添加后不会创建小群、并默认已结。\n添加的时间线不会计入公告的小群数量。\n添加后会通知至个人群。",
            f"删除时间线：{replace_playname} 嘉宾/NPC姓名 私约/电话/前置电话/官约/微信/心愿 Dx 07:00-23:59\n\n【说明】\n该指令仅删除了时间线，并未释放/删除小群。\n若需删除小群+时间线，请使用删除小群的指令。\n删除后会通知至个人群。",
            f"引用戏文并附文「@骰子 撤戏」\n\n【说明】\n该指令可自助撤回戏录。",
            f"发起前置电话 {replace_playname}\n\n【说明】\n获取前置电话设置表，填写限额、（戏内占用的）时间（单双选可设置在不同时间）和每位嘉宾/NPC编号后，将整张表发送回后台群保存。\n\n嘉宾/NPC发送「前置电话选择」可查看/填写选择，后台发送「查看前置电话选择 {replace_playname}」可查看汇总。",
            f"拉取前置电话 {replace_playname}\n\n【说明】\n根据前置电话选择结果批量创建前置电话小群。\n前置电话会占用时间线，其他玩法同时间会冲突；多个前置电话同时间不互相冲突。",
            f"发起官约/双选官约 {replace_playname}\n\n【说明】\n与前置电话格式和用法一致，支持嘉宾和NPC；不支持双选多人顺位。发起双选官约返回的格式会自动填充成员姓名，拉取双选官约仅拉取选择结果中的双向选择。\n嘉宾/NPC发送「官约选择」可查看/填写选择，后台发送「查看官约选择 {replace_playname}」可查看汇总。",
            f"录入嘉宾性别 {replace_playname}\n\n【说明】\n获取嘉宾列表，填写后整张表发送回后台群保存。\n。性别可填写任意内容（包括不同身份），“拉取异性随机官约”会按照不同内容进行分组。",
            f"拉取随机官约/拉取异性随机官约 {replace_playname} D0 19:00-20:00\n\n【说明】\n将非NPC嘉宾随机两两配对并创建官约小群。\n“拉取异性随机官约”会根据已录入的嘉宾性别随机配对，未录入性别的嘉宾会被跳过。",
            f"{replace_playname}设置收集项 公知 收集内容2 收集内容3\n\n【说明】\n设置本场恋综可上传的收集项，即使不填写公知也会自动开启公知收集。\n本指令会覆盖当前收集项；想保留的项目每次都要写上，未写的项目会被关闭。\n关闭不会删除已上传内容，但关闭期间无法通过查看指令查看或上传；重新开启后可继续查看原内容。",
            f"{collection_view_text}\n{collection_random_text}\n\n【说明】\n在后台群发送查看指令，可查看对应收集项合集与收集进度。\n在后台群发送随机编号指令，可匿名随机编号并显示姓名对应关系；如已录入性别则自动按性别分组。\n除公知外，其他收集项仅后台可查看。",
            f"{collection_delete_text}\n\n【说明】\nxxx为嘉宾/NPC姓名。",
            f"{replace_playname} 删除关系线 张三 李四\n\n【说明】\n空格隔开。",
            f"{replace_playname} 关系线截止日期 20260101",
            f"{replace_playname} 通知受邀者 开启/关闭\n\n【注意】\n本功能默认关闭，需要手动开启。",
            f"{replace_playname} Dx补戏（x为数字）",
            f"{replace_playname} Dx取消补戏（x为数字）",
            f"{replace_playname} 统计所有嘉宾\n\n【说明】\n该指令可查看日程内所有嘉宾的所有数据",
            f"{replace_playname} 嘉宾姓名 时间线",
            f"<{replace_playname}·日程>\n时间：D0\n文本：（可为空）\n图片：（可为空）\n\n【说明】\n添加成功后，日程会发送到公告群，请按需添加。\n嘉宾可使用指令「{replace_playname} 日程」查看日程合集。",
            f"{replace_playname} 添加地点\n【地点名1】地点描述\n【地点名2】地点描述\n【地点名3】地点描述\n",
            f"{replace_playname} 删除地点\n地点名1\n地点名2\n地点名3\n",
            f"查询小群数量@骰子\n\n【说明】\n该指令可查询池内小群使用情况",
            f"登记默认/{replace_playname}群号\n群号1\n群号2",
            f"删除默认/{replace_playname}群号\n群号1\n群号2",
            f"清空默认/{replace_playname}群号",
            f"{replace_playname} 一键收群\n{replace_playname} 检测小群\n{replace_playname} 提醒退群\n{replace_playname} 踢出小群\n{replace_playname} 设置小群白名单 QQ1 QQ2\n{replace_playname} 设置小群白名单 无\n\n【说明】\n一键收群：释放本恋综所有未释放小群，并在释放后艾特该小群所有嘉宾/NPC。\n检测小群：检测该恋综备用池中所有空闲小群，列出仍留在群内的非白名单成员。\n提醒退群：向这些非白名单成员发送退群提醒。\n踢出小群：将这些非白名单成员移出小群；不会踢机器人或白名单成员。\n设置小群白名单：重复发送会覆盖；填写“无”会清空白名单。",
            f"导出{replace_playname}复盘\n\n【说明】\n复盘压缩包将会上传至后台群，不复盘关系线。",
            f"注销恋综@骰子\n\n【注意】\n避免数据积压，结束后及时注销。\n当一个群为多个恋综的后台群时，自动注销最后一个注册的恋综。",
            f"修正所有恋综数据\n\n【注意】\n在没有进行任何恋综时使用，清理所有坏数据。",
            f"开启/关闭电话dlc1/2\n\n【说明】\n全局设置。\ndlc1：随机电话，在受邀者一栏填写随机，NPC不会接到随机电话。\ndlc2：电话随机泄漏，需服从手册中复盘方式3。",
            f"游戏插件手册\n\n【说明】\n查看游戏插件的完整玩法和指令手册。",
            f"出场顺序 {replace_playname}\n\n【说明】\n随机生成恋综内全部非NPC嘉宾的出场顺序。每发送一次该指令就会重新生成随机顺序并覆盖，请勿重复查看。",
            f"开始出场 {replace_playname}\n\n【说明】\n在当前群按已保存的顺序依次艾特嘉宾；当前嘉宾发言后自动进入下一位。可使用“跳过”指令跳过当前嘉宾。",
            f"结束出场\n\n【说明】\n如在后台等其他群开启出场测试，可能造成消息回复延迟，请手动结束。",
            f"「技术支持」探丸借客@临皋闲人（反季节生物改编版）",
        ]
        section_specs = [
            ("使用说明", list(range(0, 2))),
            ("互动限制与掉落", list(range(2, 8))),
            ("嘉宾与个人群", list(range(8, 13))),
            ("催戏与数据查询", list(range(13, 17)) + [34, 35]),
            ("删除预约、时间线", list(range(17, 21)) + [31]),
            ("前置电话与官约", list(range(21, 26))),
            ("公知、收集项与关系线", list(range(26, 31))),
            ("补戏、日程与地点", [32, 33] + list(range(36, 39))),
            ("备用小群池", list(range(39, 44))),
            ("导出与数据维护", list(range(44, 48))),
            ("自动出场及游戏", list(range(48, 52))),
            ("技术支持", [53]),
        ]
        section_specs[-1] = (
            section_specs[-1][0],
            [len(texts) - 1],
        )
        for section_name, text_indexes in section_specs:
            if section_name in {"使用说明", "技术支持"}:
                nodes_data.extend(
                    {
                        "bot_id": bot_id,
                        "bot_nickname": section_name,
                        "content_text": texts[index],
                    }
                    for index in text_indexes
                    if index < len(texts)
                )
                continue
            section_nodes = [
                {
                    "bot_id": bot_id,
                    "bot_nickname": section_name,
                    "content_text": f"【{section_name}】",
                }
            ]
            section_nodes.extend(
                {
                    "bot_id": bot_id,
                    "bot_nickname": section_name,
                    "content_text": texts[index],
                }
                for index in text_indexes
                if index < len(texts)
            )
            nodes_data.append(
                {
                    "bot_id": bot_id,
                    "bot_nickname": f"后台手册·{section_name}",
                    "content_list": section_nodes,
                }
            )
        result = _send_forward_with_split(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            plugin_event.reply(
                f"合并转发消息请求失败，请联系骰主：{result.get('message', '未知错误')}"
            )
        return

    elif re.match(r"<(.+?)·(.+?)>", message) and "姓名：" in message and "内容：" in message:
        image = ""
        if re.search(r"\[(OP|CQ):image,.+\]", message):
            image_match = re.search(r"\[(OP|CQ):image,.+\]", message)
            image = image_match.group(0)
            message = message.replace(image, "")
        match = re.match(r"<(.+?)·(.+?)>\s*姓名：(.+?)\s*内容：([\s\S]*)", message)
        if match:
            playname = match.group(1).strip()
            collection_item = match.group(2).strip()
            name_field = match.group(3).strip()
            content = match.group(4).strip()
            target_uid = uid
            is_admin_input = False
            at_match = re.search(r"\[OP:at,id=(\d+)\]", name_field)
            if at_match:
                if uid not in masterlist:
                    plugin_event.reply("仅骰主权限可代提交收集项。")
                    return
                target_uid = at_match.group(1)
                sender_name = re.sub(
                    r"\[OP:at,id=\d+\]\s*", "", name_field
                ).strip()
                is_admin_input = True
            else:
                sender_name = name_field
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            register = getData("groupcollection", "register.json")
            if collection_item not in _get_collection_items(register, playname):
                plugin_event.reply(
                    f"恋综「{playname}」未开启「{collection_item}」收集项，请检查格式噢！"
                )
                return
            user_found = False
            registered_name = ""
            user_info = None
            for uid_in_file, info in privategroup[playname].items():
                if uid_in_file == target_uid:
                    user_found = True
                    user_info = info
                    if "嘉宾姓名" in info:
                        registered_name = info.get("嘉宾姓名", "")
                    elif "NPC姓名" in info:
                        registered_name = info.get("NPC姓名", "")
                    break
            if not user_found:
                if is_admin_input:
                    plugin_event.reply(
                        f"未找到被@的账号（{target_uid}）在恋综「{playname}」中的嘉宾/NPC登记信息，无法代提交。"
                    )
                else:
                    plugin_event.reply(
                        f"{sender}不是恋综「{playname}」的嘉宾或NPC，无法上传{collection_item}噢！"
                    )
                return
            if is_admin_input and not sender_name:
                sender_name = registered_name
            if sender_name != registered_name:
                plugin_event.reply(
                    f"填写的姓名「{sender_name}」与注册的姓名「{registered_name}」不一致！\n请填写正确的姓名重新上传。\n\n<{playname}·{collection_item}>\n姓名：{registered_name}\n内容："
                )
                return
            if not is_admin_input:
                if playname in privategroup and uid in privategroup[playname]:
                    user_groupid = privategroup[playname][uid].get(
                        "个人群号"
                    ) or privategroup[playname][uid].get("NPC群号")
                if user_groupid != groupid:
                    plugin_event.reply(f"请前往个人群中上传{collection_item}噢！")
                    return
            public_file = _collection_file(playname, collection_item)
            public_data = getData("public", public_file)
            if target_uid in public_data:
                plugin_event.reply(
                    f"{registered_name}已经上传过{collection_item}了！\n\n如需修改，请联系管理删除后重新上传。"
                )
                return
            stored_image = image
            if image:
                cached_image = _resolve_image_file(image)
                if cached_image:
                    stored_image = f"[OP:image,file={cached_image}]"
            public_data[target_uid] = {
                "姓名": sender_name,
                "内容": content,
                "图片": stored_image,
            }
            setData("public", public_file, public_data)
            if is_admin_input:
                plugin_event.reply(
                    f"已代「{registered_name}」提交{collection_item}！\n\n如需修改，请联系管理删除后重新提交。"
                )
            else:
                plugin_event.reply(f"{collection_item}上传成功！")
            return

    elif _parse_collection_delete_message(message)[0]:
        playname, collection_item, target_name = _parse_collection_delete_message(message)
        if playname:
            register = getData("groupcollection", "register.json")
            if uid not in masterlist:
                plugin_event.reply(f"仅骰主权限可删除{collection_item}。")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            if playname not in register:
                plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查噢！")
                return
            manage_group = register[playname].get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中删除{collection_item}噢！")
                return
            target_uid = None
            found_info = None
            for uid_in_file, info in privategroup[playname].items():
                if (
                    info.get("嘉宾姓名") == target_name
                    or info.get("NPC姓名") == target_name
                ):
                    target_uid = uid_in_file
                    found_info = info
                    break
            if not target_uid:
                plugin_event.reply(
                    f"在恋综「{playname}」中未找到姓名为「{target_name}」的嘉宾或NPC，无法删除！"
                )
                return
            public_file = _collection_file(playname, collection_item)
            try:
                public_data = getData("public", public_file)
            except:
                plugin_event.reply(f"恋综「{playname}」的{collection_item}文件不存在或为空！")
                return
            if target_uid not in public_data:
                plugin_event.reply(
                    f"「{target_name}」未在恋综「{playname}」中上传{collection_item}！"
                )
                return
            deleted_content = public_data[target_uid]
            del public_data[target_uid]
            setData("public", public_file, public_data)
            upload_name = deleted_content.get("姓名", "未知")
            registered_name = deleted_content.get("登记姓名", "未知")
            content_preview = deleted_content.get("内容", "")
            reply_msg = f"已删除恋综「{playname}」中「{target_name}」的{collection_item}！\n\n"
            reply_msg += f"内容：\n{content_preview}"
            plugin_event.reply(reply_msg)
            if found_info:
                notify_group_id = found_info.get("个人群号") or found_info.get(
                    "NPC群号"
                )
                if notify_group_id:
                    notification = (
                        f"【通知】\n{target_name}的{collection_item}已被管理删除。\n\n"
                        f"如需重新上传，请填写以下格式：\n"
                        f"<{playname}·{collection_item}>\n"
                        f"姓名：{target_name}\n"
                        f"内容："
                    )
                    plugin_event.send("group", notify_group_id, notification)
                else:
                    pass
            return

    elif _parse_collection_random_number_message(message)[0]:
        playname, collection_item = _parse_collection_random_number_message(message)
        if playname:
            register = getData("groupcollection", "register.json")
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            manage_group = register.get(playname, {}).get("manage_group")
            if manage_group is None or str(groupid) != str(manage_group):
                plugin_event.reply(
                    f"请在恋综「{playname}」的后台群中使用随机编号。"
                )
                return
            public_file = _collection_file(playname, collection_item)
            public_data = getData("public", public_file)
            entries = []
            for uid_in_file, info in privategroup[playname].items():
                if uid_in_file in public_data:
                    entry_name = info.get("嘉宾姓名") or info.get("NPC姓名", "未知")
                    entry_gender = str(info.get("性别", "")).strip()
                    entry_content = public_data[uid_in_file].get("内容", "")
                    entry_image = public_data[uid_in_file].get("图片", "")
                    entries.append(
                        {
                            "uid": uid_in_file,
                            "name": entry_name,
                            "gender": entry_gender,
                            "content": entry_content,
                            "image": entry_image,
                        }
                    )
            if not entries:
                plugin_event.reply(
                    f"恋综「{playname}」暂无任何{collection_item}内容！"
                )
                return
            all_have_gender = all(e["gender"] for e in entries)
            pid_to_number = {}
            nodes_data = []

            def _build_numbered_node(bot_id_val, number_val, content_val, image_val):
                image_segment = _image_segment_from_text(image_val)
                if image_segment:
                    segs = [
                        {
                            "type": "text",
                            "data": {"text": f"{number_val}：\n{content_val}"},
                        },
                        image_segment,
                    ]
                    return {"bot_id": bot_id_val, "content_list": segs}
                return {
                    "bot_id": bot_id_val,
                    "content_text": f"{number_val}：\n{content_val}",
                }

            if all_have_gender:
                gender_groups = {}
                for e in entries:
                    gender_groups.setdefault(e["gender"], []).append(e)
                sorted_genders = sorted(gender_groups.keys())
                counter = 1
                for gender in sorted_genders:
                    group_entries = gender_groups[gender]
                    random.shuffle(group_entries)
                    nodes_data.append(
                        {
                            "bot_id": bot_id,
                            "content_text": f"{playname} {collection_item} {gender}：",
                        }
                    )
                    for e in group_entries:
                        pid_to_number[e["uid"]] = counter
                        nodes_data.append(
                            _build_numbered_node(
                                bot_id, counter, e["content"], e["image"]
                            )
                        )
                        counter += 1
            else:
                random.shuffle(entries)
                nodes_data.append(
                    {
                        "bot_id": bot_id,
                        "content_text": f"{playname} {collection_item}",
                    }
                )
                for idx, e in enumerate(entries, start=1):
                    pid_to_number[e["uid"]] = idx
                    nodes_data.append(
                        _build_numbered_node(bot_id, idx, e["content"], e["image"])
                    )
            result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
            if result.get("retcode") != 0:
                plugin_event.reply(
                    f"合并转发消息发送失败，请联系骰主：{result.get('message', '未知错误')}"
                )
                return
            mapping_lines = []
            for e in entries:
                number = pid_to_number.get(e["uid"])
                mapping_lines.append(f"{e['name']}：{number}")
            time.sleep(1)
            plugin_event.reply("\n".join(mapping_lines))
            return

    elif _parse_collection_view_message(message)[0]:
        playname, collection_item, at_id = _parse_collection_view_message(message)
        if playname:
            if at_id != str(plugin_event.bot_info.id):
                return
            register = getData("groupcollection", "register.json")
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            manage_group = None
            if playname in register and "manage_group" in register[playname]:
                manage_group = register[playname]["manage_group"]
            is_manage_group = manage_group is not None and str(groupid) == str(
                manage_group
            )
            if collection_item != "公知" and not is_manage_group and uid not in masterlist:
                plugin_event.reply(f"恋综「{playname}」的{collection_item}仅后台可查看。")
                return
            public_file = _collection_file(playname, collection_item)
            public_data = getData("public", public_file)
            guest_uids = []
            npc_uids = []
            for uid_in_file, info in privategroup[playname].items():
                if "嘉宾姓名" in info:
                    guest_uids.append(uid_in_file)
                elif "NPC姓名" in info:
                    npc_uids.append(uid_in_file)
            missing_guests = []
            for guest_uid in guest_uids:
                if guest_uid not in public_data:
                    missing_guests.append(guest_uid)
            if collection_item == "公知" and not is_manage_group and missing_guests:
                missing_names = []
                for guest_uid in missing_guests:
                    if guest_uid in privategroup[playname]:
                        guest_info = privategroup[playname][guest_uid]
                        if "嘉宾姓名" in guest_info:
                            missing_names.append(guest_info["嘉宾姓名"])
                plugin_event.reply(
                    f"{collection_item}尚未收齐。\n\n所有嘉宾上传完毕后才可以查看噢！"
                )
                return
            nodes_data = []
            npc_public_count = 0
            for npc_uid in npc_uids:
                if npc_uid in public_data:
                    npc_public_count += 1
                    if npc_public_count == 1:
                        nodes_data.append({"bot_id": bot_id, "content_text": f"NPC{collection_item}"})
                    npc_info = privategroup[playname][npc_uid]
                    npc_name = npc_info.get("NPC姓名", "未知NPC")
                    public_info = public_data[npc_uid]
                    upload_name = public_info.get("姓名", npc_name)
                    content = public_info.get("内容", "")
                    image = public_info.get("图片", "")
                    image_segment = _image_segment_from_text(image)
                    if image_segment:
                        nodes_data.append(
                            {
                                "bot_id": bot_id,
                                "content_list": [
                                    {
                                        "type": "text",
                                        "data": {
                                            "text": f"{npc_name}\n\n{content}"
                                        },
                                    },
                                    image_segment,
                                ],
                            }
                        )
                    else:
                        nodes_data.append(
                            {
                                "bot_id": bot_id,
                                "content_text": f"{npc_name}\n\n{content}",
                            }
                        )
            guest_public_count = 0
            for guest_uid in guest_uids:
                if guest_uid in public_data:
                    guest_public_count += 1
                    if guest_public_count == 1 and npc_public_count > 0:
                        nodes_data.append(
                            {"bot_id": bot_id, "content_text": f"嘉宾{collection_item}"}
                        )
                    guest_info = privategroup[playname][guest_uid]
                    guest_name = guest_info.get("嘉宾姓名", "未知嘉宾")
                    public_info = public_data[guest_uid]
                    upload_name = public_info.get("姓名", guest_name)
                    content = public_info.get("内容", "")
                    image = public_info.get("图片", "")
                    image_segment = _image_segment_from_text(image)
                    if image_segment:
                        nodes_data.append(
                            {
                                "bot_id": bot_id,
                                "content_list": [
                                    {
                                        "type": "text",
                                        "data": {
                                            "text": f"{guest_name}\n\n{content}"
                                        },
                                    },
                                    image_segment,
                                ],
                            }
                        )
                    else:
                        nodes_data.append(
                            {
                                "bot_id": bot_id,
                                "content_text": f"{guest_name}\n\n{content}",
                            }
                        )
            if not nodes_data:
                plugin_event.reply(f"恋综「{playname}」暂无任何{collection_item}内容！")
                return
            result = _send_forward_with_split(
                bot_port, bot_token, groupid, nodes_data
            )
            if result.get("retcode") != 0:
                plugin_event.reply(
                    f"合并转发消息发送失败，请联系骰主：{result.get('message', '未知错误')}"
                )
                return
            if is_manage_group:
                total_guests = len(guest_uids)
                uploaded_guests = total_guests - len(missing_guests)
                total_npcs = len(npc_uids)
                uploaded_npcs = 0
                for npc_uid in npc_uids:
                    if npc_uid in public_data:
                        uploaded_npcs += 1
                progress_msg = f"恋综「{playname}」{collection_item}收集进度：\n"
                progress_msg += f"嘉宾：{uploaded_guests}/{total_guests}\n"
                progress_msg += f"NPC：{uploaded_npcs}/{total_npcs}"
                if missing_guests:
                    missing_names = []
                    for guest_uid in missing_guests:
                        if guest_uid in privategroup[playname]:
                            guest_info = privategroup[playname][guest_uid]
                            if "嘉宾姓名" in guest_info:
                                missing_names.append(guest_info["嘉宾姓名"])
                    progress_msg += f"\n\n未上传嘉宾：{'，'.join(missing_names)}"
                time.sleep(1)
                plugin_event.reply(progress_msg)
            return

    elif "送图" in message:
        if not re.search(r"送图\s+.+?\s*致", message):
            return
        from datetime import datetime

        if re.search("\[(OP|CQ):image,.+\]", message):
            image = re.search("\[(OP|CQ):image,.+\]", message).group(0)
            message = message.replace(image, "")
        else:
            plugin_event.reply("消息中没有检测到图片噢！")
            return
        match1 = re.match(
            r"(.+?)\s+送图\s+(.+?)\s*致\s*(.+?)\s*内容：\s*([\s\S]+?)\s*署名：\s*([\s\S]+)",
            message,
        )
        if match1:
            playname = match1.group(1).strip()
            now = datetime.now()
            date = now.strftime("%y%m%d")
            real_to_virtual = vtor(playname)
            if real_to_virtual is None:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            if date in real_to_virtual:
                plugin_event.reply(
                    f"当前日期在恋综「{playname}」日程范围内，日程内送图是坏文明！"
                )
                return
            else:
                pass
            sender = str(uid)
            recver = match1.group(3).strip()
            privategroup = getData("groupcollection", "privategroup.json")
            if not re.match(r"^\d+$", recver):
                if playname in privategroup:
                    found = False
                    for guest_uid, guest_info in privategroup[playname].items():
                        if guest_info.get("嘉宾姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                        if guest_info.get("NPC姓名") == recver:
                            recver = guest_uid
                            found = True
                            break
                    if not found:
                        plugin_event.reply(
                            "本场恋综已录入信息中未找到该嘉宾/NPC姓名，请检查填写信息或改为填写收件人qq噢！"
                        )
                        return
            if not re.match(r"^\d+$", recver):
                plugin_event.reply(
                    "本场恋综已录入信息中未找到该嘉宾姓名，请检查填写信息或改为填写收件人qq噢！"
                )
                return
            content = match1.group(4).strip()
            signature = match1.group(5).strip() + image
            if not content or not signature:
                plugin_event.reply("内容或署名不可为空噢！可为符号或假名。")
                return
            if playname not in privategroup or uid not in privategroup[playname]:
                sender_name = plugin_event.data.sender["name"]
                plugin_event.reply(f"{sender_name}不是该恋综的嘉宾或NPC，无法送图噢！")
                return
            plugin_event.reply("图送好啦！")
            if playname in privategroup and recver in privategroup[playname]:
                guest_info = privategroup[playname][recver]
                guest_name = ""
                group_id = ""
                if "嘉宾姓名" in guest_info:
                    guest_name = guest_info["嘉宾姓名"]
                    group_id = guest_info.get("个人群号", "")
                elif "NPC姓名" in guest_info:
                    guest_name = guest_info["NPC姓名"]
                    group_id = guest_info.get("NPC群号", guest_info.get("个人群号", ""))
                if not guest_name:
                    guest_name = recver
                if group_id:
                    plugin_event.send(
                        "group",
                        group_id,
                        playname
                        + " 送图\n致 "
                        + guest_name
                        + "\n内容："
                        + content
                        + "\n署名："
                        + signature,
                    )
                else:
                    plugin_event.send(
                        "private",
                        recver,
                        playname
                        + " 送图\n致 "
                        + guest_name
                        + "\n内容："
                        + content
                        + "\n署名："
                        + signature,
                    )
            else:
                plugin_event.send(
                    "private",
                    recver,
                    playname
                    + " 送图\n致 "
                    + recver
                    + "\n内容："
                    + content
                    + "\n署名："
                    + signature,
                )
            return
        else:
            return

    elif re.match(r"(.+)\s*添加地点", message):
        match = re.match(r"(.+)\s*添加地点", message)
        if not match:
            return
        playname = match.group(1).strip()
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主权限可设置。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中添加地点！")
            return
        lines = message.strip().splitlines()[1:]
        place_dict = {}
        place_pattern = re.compile(r"【(.+?)】(.+)")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            match_place = place_pattern.match(line)
            if match_place:
                place_name = match_place.group(1).strip()
                place_desc = match_place.group(2).strip()
                if place_name in place_dict:
                    plugin_event.reply(f"地点「{place_name}」已重复，请检查！")
                    return
                place_dict[place_name] = place_desc
            else:
                plugin_event.reply(
                    f"格式错误：{line}\n请使用「【地点名】描述」的格式！"
                )
                return
        if not place_dict:
            plugin_event.reply("未找到有效的地点信息，请按照格式输入！")
            return
        try:
            existing_places = getData("place", f"{playname}.json")
            if not isinstance(existing_places, dict):
                existing_places = {}
        except:
            existing_places = {}
        current_count = len(existing_places)
        new_count = len(place_dict)
        if current_count + new_count > 100:
            plugin_event.reply(
                f"地点数量超过限制！当前已有{current_count}个地点，本次添加{new_count}个，总计将超过100个。"
            )
            return
        existing_places.update(place_dict)
        setData("place", f"{playname}.json", existing_places)
        reply_msg = f"恋综「{playname}」已添加{new_count}个地点，目前共有{len(existing_places)}个。"
        plugin_event.reply(reply_msg)

    elif re.match(r"(.+)\s*删除地点", message):
        match = re.match(r"(.+)\s*删除地点", message)
        if not match:
            return
        playname = match.group(1).strip()
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主权限可删除。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中删除地点！")
            return
        lines = message.strip().splitlines()[1:]
        places_to_delete = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            places_to_delete.append(line)
        if not places_to_delete:
            plugin_event.reply("未指定要删除的地点名称，请按照格式输入！")
            return
        try:
            existing_places = getData("place", f"{playname}.json")
            if not isinstance(existing_places, dict):
                existing_places = {}
        except:
            existing_places = {}
        not_found_places = []
        found_places = []
        for place_name in places_to_delete:
            if place_name in existing_places:
                found_places.append(place_name)
            else:
                not_found_places.append(place_name)
        if not_found_places:
            not_found_str = "、".join(not_found_places)
            plugin_event.reply(f"以下地点不存在，无法删除：{not_found_str}")
            return
        for place_name in found_places:
            del existing_places[place_name]
        setData("place", f"{playname}.json", existing_places)
        reply_msg = f"恋综「{playname}」已删除{len(found_places)}个地点，剩下{len(existing_places)}个。"
        plugin_event.reply(reply_msg)

    elif re.match(r"(.+)\s*地点$", message):
        match = re.match(r"(.+)\s*地点$", message)
        if not match:
            return
        playname = match.group(1).strip()
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            return
        if uid not in privategroup[playname]:
            plugin_event.reply(f"{sender}未参与恋综「{playname}」，无法查看地点噢！")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名噢！")
            return
        if playname in privategroup and uid in privategroup[playname]:
            user_groupid = privategroup[playname][uid].get("个人群号") or privategroup[
                playname
            ][uid].get("NPC群号")
        if user_groupid != groupid:
            plugin_event.reply(f"请前往个人群中查看地点噢！")
            return
        try:
            place_data = getData("place", f"{playname}.json")
            if not isinstance(place_data, dict) or not place_data:
                plugin_event.reply(f"恋综「{playname}」暂无地点信息，请联系管理添加。")
                return
        except:
            plugin_event.reply(f"恋综「{playname}」暂无地点信息，请联系管理添加。")
            return
        sorted_places = sorted(place_data.items())
        nodes_data = []
        title_text = f"恋综「{playname}」地点列表\n共{len(place_data)}个\n开戏地点无需严格匹配以下文本。"
        nodes_data.append({"bot_id": bot_id, "content_text": title_text})
        for place_name, place_desc in sorted_places:
            place_node_text = f"{place_name}\n\n{place_desc}"
            nodes_data.append({"bot_id": bot_id, "content_text": place_node_text})
        result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            if len(sorted_places) <= 5:
                place_list_text = "\n".join(
                    [f"【{name}】{desc}" for name, desc in sorted_places]
                )
                reply_msg = f"恋综「{playname}」地点列表（共{len(place_data)}个）：\n\n{place_list_text}"
                plugin_event.reply(reply_msg)
            else:
                place_list_text = "\n".join(
                    [f"【{name}】{desc}" for name, desc in sorted_places[:5]]
                )
                reply_msg = f"合并转发失败，显示前5个地点：\n\n{place_list_text}\n\n……还有{len(place_data)-5}个地点，请稍后再试一次。"
                plugin_event.reply(reply_msg)

    elif re.search(r"<(.+?)·日程>", message):
        match = re.search(r"<(.+?)·日程>", message)
        if match:
            playname = match.group(1).strip()
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可设置。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中添加日程！")
                return
            time_pattern = re.compile(r"时间\s*[:：]\s*([Dd]\d+)")
            time_match = time_pattern.search(message)
            if not time_match:
                plugin_event.reply(
                    "未找到时间信息，请按照格式输入！\n\n<恋综名·日程>\n时间：D0/1/2/3/4/5\n文本：（可为空）\n图片：（可为空）"
                )
                return
            day_key = time_match.group(1).upper()
            text_pattern = re.compile(
                r"文本\s*[:：]\s*(.*?)(?=图片\s*[:：]|\n图片\s*[:：]|$)", re.DOTALL
            )
            text_match = text_pattern.search(message)
            text_content = text_match.group(1).strip() if text_match else ""
            image_pattern = re.compile(
                r"图片\s*[:：]\s*(\[CQ:image[^\]]+\]|\[OP:image[^\]]+\]|.*?)($|\n)",
                re.DOTALL,
            )
            image_match = image_pattern.search(message)
            image_content = image_match.group(1).strip() if image_match else ""
            if not text_content and not image_content:
                plugin_event.reply("文本和图片不能都为空，请至少填写一项！")
                return
            try:
                existing_schedules = getData("routine", f"{playname}.json")
                if not isinstance(existing_schedules, dict):
                    existing_schedules = {}
            except:
                existing_schedules = {}
            if len(existing_schedules) >= 100:
                plugin_event.reply("日程数量超过限制！最多只能添加100个日程。")
                return
            if day_key in existing_schedules:
                plugin_event.reply(
                    f"恋综「{playname}」{day_key}的日程已存在，如需修改请先删除原日程！"
                )
                return
            stored_image = image_content
            if image_content:
                cached_image = _resolve_image_file(image_content)
                if cached_image:
                    stored_image = f"[OP:image,file={cached_image}]"
            existing_schedules[day_key] = {
                "文本": text_content,
                "图片": stored_image,
            }
            setData("routine", f"{playname}.json", existing_schedules)
            reply_msg = (
                f"添加成功，正在发送至公告群！\n\n"
                f"删除指令：「{playname} 删除{day_key}日程」\n\n查看指令：「{playname} 日程」\n（嘉宾使用该指令可查看所有已添加日程，请按需添加）\n\n目前共有{len(existing_schedules)}个日程。"
            )
            plugin_event.reply(reply_msg)
            notice_group = data.get("notice_group")
            time.sleep(1)
            if notice_group:
                notice_message = f"{day_key}日程\n\n"
                if text_content:
                    notice_message += f"{text_content}\n\n"
                if stored_image:
                    notice_message += f"{stored_image}\n\n"
                notice_message += f"指令「{playname} 日程」查看日程合集"
                plugin_event.send("group", notice_group, notice_message)
            else:
                plugin_event.reply("未找到公告群配置，发送日程失败。")

    elif re.match(r"(.+)\s*删除\s*([Dd]\d+)\s*日程", message):
        match = re.match(r"(.+)\s*删除\s*([Dd]\d+)\s*日程", message)
        if not match:
            return
        playname = match.group(1).strip()
        day_to_delete = match.group(2).upper()

        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主权限可删除。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中删除日程！")
            return
        try:
            existing_schedules = getData("routine", f"{playname}.json")
            if not isinstance(existing_schedules, dict):
                existing_schedules = {}
        except:
            existing_schedules = {}
        if day_to_delete not in existing_schedules:
            plugin_event.reply(
                f"恋综「{playname}」{day_to_delete}的日程不存在，无法删除！"
            )
            return
        del existing_schedules[day_to_delete]
        setData("routine", f"{playname}.json", existing_schedules)
        reply_msg = (
            f"恋综「{playname}」{day_to_delete}日程删除成功！\n\n"
            f"剩余{len(existing_schedules)}个日程。"
        )
        plugin_event.reply(reply_msg)

    elif re.match(r"(.+)\s*日程$", message):
        match = re.match(r"(.+)\s*日程$", message)
        if not match:
            return
        playname = match.group(1).strip()
        register = getData("groupcollection", "register.json")
        if playname not in register:
            return
        data = register[playname]
        manage_group = str(data.get("manage_group"))
        is_manage_group = str(groupid) == manage_group
        if not is_manage_group:
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                return
            user_found = False
            if uid in privategroup[playname]:
                user_info = privategroup[playname][uid]
                user_groupid = user_info.get("个人群号") or user_info.get("NPC群号")
                if str(groupid) == str(user_groupid):
                    user_found = True
            if not user_found:
                plugin_event.reply(
                    f"请前往恋综「{playname}」的个人群或后台群查看日程！"
                )
                return
        try:
            schedule_data = getData("routine", f"{playname}.json")
            if not isinstance(schedule_data, dict) or not schedule_data:
                plugin_event.reply(f"恋综「{playname}」暂无日程信息，请联系管理添加。")
                return
        except:
            plugin_event.reply(f"恋综「{playname}」暂无日程信息，请联系管理添加。")
            return
        nodes_data = []

        def day_sort_key(day_str):
            try:
                return int(day_str[1:])
            except:
                return float("inf")

        sorted_days = sorted(schedule_data.keys(), key=day_sort_key)
        title_text = f"恋综「{playname}」日程"
        nodes_data.append({"bot_id": bot_id, "content_text": title_text})
        for day_key in sorted_days:
            day_info = schedule_data[day_key]
            text_content = day_info.get("文本", "")
            image_content = day_info.get("图片", "")
            image_segment = _image_segment_from_text(image_content)
            if image_segment:
                segments = [
                    {"type": "text", "data": {"text": f"{day_key} 日程\n\n"}}
                ]
                if text_content:
                    segments.append(
                        {"type": "text", "data": {"text": f"{text_content}\n"}}
                    )
                segments.append(image_segment)
                nodes_data.append({"bot_id": bot_id, "content_list": segments})
            else:
                content_text = f"{day_key} 日程\n\n"
                if text_content:
                    content_text += f"{text_content}\n"
                if image_content and not re.search(
                    r"\[(?:OP|CQ):image", image_content
                ):
                    content_text += f"\n{image_content}"
                nodes_data.append(
                    {"bot_id": bot_id, "content_text": content_text.strip()}
                )
        result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            summary = f"恋综「{playname}」日程\n\n"
            for day_key in sorted_days[:5]:  # 只显示前5个
                day_info = schedule_data[day_key]
                text_content = day_info.get("文本", "")[:50]
                has_image = bool(day_info.get("图片", ""))
                summary += f"{day_key}: {text_content}{'...' if len(text_content) > 50 else ''} {'[图片]' if has_image else ''}\n"
            if len(schedule_data) > 5:
                summary += f"\n……还有{len(schedule_data)-5}个日程，请稍后再试一次。"
            plugin_event.reply(summary)

    elif re.match(r"(.+)\s*设置戏群名片", message):
        match = re.match(r"(.+)\s*设置戏群名片", message)
        if match:
            playname = match.group(1).strip()
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可设置戏群名片。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                return
            reg_data = register[playname]
            manage_group = reg_data.get("manage_group")
            if str(groupid) != str(manage_group):
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置戏群名片！")
                return
            play_group = reg_data.get("play_group")
            if not play_group:
                plugin_event.reply(f"恋综「{playname}」未设置戏群群号，无法设置名片！")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(f"恋综「{playname}」暂无嘉宾数据，无法更改名片。")
                return
            group_member_ids = get_group_member_list(plugin_event, play_group)
            if not group_member_ids:
                plugin_event.reply("无法获取戏群成员列表，请检查机器人权限。")
                return
            group_member_ids = set(group_member_ids)
            plugin_event.reply(
                "现在开始依次设置戏群名片，根据成员人数，成功回执将会在约10-30秒后发送。"
            )
            url = f"http://127.0.0.1:{bot_port}/set_group_card"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bot_token}",
            }
            success_count = 0
            skip_count = 0
            fail_count = 0
            members_not_in_group = []
            for guest_uid, guest_info in privategroup[playname].items():
                guest_name = None
                if "嘉宾姓名" in guest_info:
                    guest_name = guest_info["嘉宾姓名"]
                    guest_type = "嘉宾"
                elif "NPC姓名" in guest_info:
                    guest_name = guest_info["NPC姓名"]
                    guest_type = "NPC"
                else:
                    continue
                if str(guest_uid) not in group_member_ids:
                    members_not_in_group.append(f"{guest_name}（{guest_type}）")
                    skip_count += 1
                    continue
                payload = json.dumps(
                    {
                        "group_id": int(play_group),
                        "user_id": int(guest_uid),
                        "card": guest_name,
                    }
                )
                try:
                    response = requests.post(
                        url, headers=headers, data=payload, timeout=10
                    )
                    result = response.json()
                    if result.get("retcode") == 0:
                        success_count += 1
                    else:
                        fail_count += 1
                    time.sleep(1)
                except Exception as e:
                    fail_count += 1
            reply_msg = f"恋综「{playname}」戏群名片设置完成！\n\n"
            reply_msg += f"成功：{success_count}人\n"
            reply_msg += f"跳过（不在群内）：{skip_count}人\n"
            reply_msg += f"失败：{fail_count}人\n"
            if members_not_in_group:
                reply_msg += f"\n以下成员不在戏群中，无法更改名片：\n"
                max_display = 5
                if len(members_not_in_group) > max_display:
                    reply_msg += "、".join(members_not_in_group[:max_display])
                    reply_msg += f"等{len(members_not_in_group)}人"
                else:
                    reply_msg += "、".join(members_not_in_group)
            plugin_event.reply(reply_msg)
            return

    elif re.match(r"(.+)\s*设置戏群头衔", message):
        match = re.match(r"(.+)\s*设置戏群头衔", message)
        if match:
            playname = match.group(1).strip()
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可设置戏群头衔。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                return
            reg_data = register[playname]
            manage_group = reg_data.get("manage_group")
            if str(groupid) != str(manage_group):
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置戏群头衔！")
                return
            play_group = reg_data.get("play_group")
            if not play_group:
                plugin_event.reply(f"恋综「{playname}」未设置戏群群号，无法设置头衔！")
                return
            privategroup = getData("groupcollection", "privategroup.json")
            if playname not in privategroup:
                plugin_event.reply(f"恋综「{playname}」暂无嘉宾数据，无法更改头衔。")
                return
            group_member_ids = get_group_member_list(plugin_event, play_group)
            if not group_member_ids:
                plugin_event.reply("无法获取戏群成员列表，请检查机器人权限。")
                return
            group_member_ids = set(group_member_ids)
            plugin_event.reply(
                "现在开始依次设置戏群名片，根据成员人数，成功回执将会在约10-30秒后发送。"
            )
            url = f"http://127.0.0.1:{bot_port}/set_group_special_title"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bot_token}",
            }
            success_count = 0
            skip_not_in_group = 0
            skip_no_avatar = 0
            fail_count = 0
            members_not_in_group = []
            members_no_avatar = []
            for guest_uid, guest_info in privategroup[playname].items():
                guest_name = None
                avatar = None
                if "嘉宾姓名" in guest_info:
                    guest_name = guest_info["嘉宾姓名"]
                    guest_type = "嘉宾"
                    avatar = guest_info.get("嘉宾皮相", "")
                elif "NPC姓名" in guest_info:
                    guest_name = guest_info["NPC姓名"]
                    guest_type = "NPC"
                    avatar = guest_info.get("NPC皮相", "")
                else:
                    continue
                if str(guest_uid) not in group_member_ids:
                    members_not_in_group.append(f"{guest_name}（{guest_type}）")
                    skip_not_in_group += 1
                    continue
                if not avatar:
                    members_no_avatar.append(f"{guest_name}（{guest_type}）")
                    skip_no_avatar += 1
                    continue
                payload = json.dumps(
                    {
                        "group_id": int(play_group),
                        "user_id": int(guest_uid),
                        "special_title": avatar,
                    }
                )
                try:
                    response = requests.post(
                        url, headers=headers, data=payload, timeout=10
                    )
                    result = response.json()
                    if result.get("retcode") == 0:
                        success_count += 1
                    else:
                        fail_count += 1
                    time.sleep(1)
                except Exception as e:
                    fail_count += 1
            reply_msg = f"恋综「{playname}」戏群头衔设置完成！\n\n"
            reply_msg += f"成功：{success_count}人\n"
            reply_msg += f"跳过（不在戏群内）：{skip_not_in_group}人\n"
            reply_msg += f"跳过（无皮相）：{skip_no_avatar}人\n"
            reply_msg += f"失败：{fail_count}人\n"
            if members_not_in_group:
                reply_msg += f"\n以下成员不在戏群中，无法更改头衔：\n"
                max_display = 5
                if len(members_not_in_group) > max_display:
                    reply_msg += "、".join(members_not_in_group[:max_display])
                    reply_msg += f"等{len(members_not_in_group)}人"
                else:
                    reply_msg += "、".join(members_not_in_group)
            if members_no_avatar:
                reply_msg += f"\n\n以下成员没有设置皮相，无法更改头衔：\n"
                max_display = 5
                if len(members_no_avatar) > max_display:
                    reply_msg += "、".join(members_no_avatar[:max_display])
                    reply_msg += f"等{len(members_no_avatar)}人"
                else:
                    reply_msg += "、".join(members_no_avatar)
            plugin_event.reply(reply_msg)
            return

    elif re.match(
        r"查询小群数量\s*\[OP:at,id=(\d+)\]",
        message,
    ):
        match = re.match(r"查询小群数量\s*\[OP:at,id=(\d+)\]", message)
        if match:
            at_id = match.group(1)
            if at_id != str(plugin_event.bot_info.id):
                return
            if uid not in masterlist:
                plugin_event.reply("如需查询小群数量请联系骰主。")
                return
            qrcode_base_path = "./data/images/恋综备用群/二维码"
            default_qrcode_path = os.path.join(qrcode_base_path, "默认池")
            playname_qrcode_stats = {}
            default_qrcode_total = 0
            default_qrcode_used = 0
            # 获取二维码文件夹的数量（排除json文件）
            if os.path.exists(default_qrcode_path) and os.path.isdir(
                default_qrcode_path
            ):
                for filename in os.listdir(default_qrcode_path):
                    file_path = os.path.join(default_qrcode_path, filename)
                    # 排除目录，只统计文件，并且排除json文件
                    if os.path.isfile(file_path) and not filename.lower().endswith(
                        ".json"
                    ):
                        default_qrcode_total += 1
                        if filename.startswith("已占用_"):
                            default_qrcode_used += 1
            if os.path.exists(qrcode_base_path) and os.path.isdir(qrcode_base_path):
                for item in os.listdir(qrcode_base_path):
                    item_path = os.path.join(qrcode_base_path, item)
                    if os.path.isdir(item_path) and item != "默认池":
                        playname = item
                        total = 0
                        used = 0
                        for filename in os.listdir(item_path):
                            file_path = os.path.join(item_path, filename)
                            # 排除目录，只统计文件，并且排除json文件
                            if os.path.isfile(
                                file_path
                            ) and not filename.lower().endswith(".json"):
                                total += 1
                                if filename.startswith("已占用_"):
                                    used += 1
                        playname_qrcode_stats[playname] = {
                            "total": total,
                            "used": used,
                            "free": total - used,
                        }
            groupnum_base_path = "./data/images/恋综备用群/群号"
            default_groupnum_file = os.path.join(groupnum_base_path, "默认池.json")
            playname_groupnum_stats = {}
            default_groupnum_total = 0
            default_groupnum_true = 0
            if os.path.exists(default_groupnum_file):
                try:
                    with open(default_groupnum_file, "r", encoding="utf-8") as f:
                        group_data = json.load(f)
                    default_groupnum_total = len(group_data)
                    for group_info in group_data.values():
                        if group_info.get("使用情况") == True:
                            default_groupnum_true += 1
                except Exception as e:
                    plugin_event.reply(f"读取默认池群号文件时出错：{e}")
                    return
            if os.path.exists(groupnum_base_path) and os.path.isdir(groupnum_base_path):
                for item in os.listdir(groupnum_base_path):
                    if item.endswith(".json") and item != "默认池.json":
                        playname = item.replace(".json", "")
                        file_path = os.path.join(groupnum_base_path, item)
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                group_data = json.load(f)
                            total = len(group_data)
                            true_count = 0
                            for group_info in group_data.values():
                                if group_info.get("使用情况") == True:
                                    true_count += 1
                            playname_groupnum_stats[playname] = {
                                "total": total,
                                "true": true_count,
                                "false": total - true_count,
                            }
                        except Exception as e:
                            playname_groupnum_stats[playname] = {
                                "total": 0,
                                "true": 0,
                                "false": 0,
                                "error": True,
                            }
            reply_msg = "【二维码】\n"
            if default_qrcode_total > 0:
                reply_msg += f"默认\n总量：{default_qrcode_total}\n已用：{default_qrcode_used}\n空闲：{default_qrcode_total - default_qrcode_used}\n"
            else:
                reply_msg += "默认\n空\n"
            if playname_qrcode_stats:
                sorted_playnames = sorted(playname_qrcode_stats.keys())
                for playname in sorted_playnames:
                    reply_msg += "-\n"
                    stats = playname_qrcode_stats[playname]
                    if stats["total"] > 0:
                        reply_msg += f"{playname}\n总量：{stats['total']}\n已用：{stats['used']}\n空闲：{stats['free']}\n"
                    else:
                        reply_msg += f"{playname}\n空\n"
            else:
                reply_msg += "\n"
            reply_msg += "\n【群号】\n"
            if default_groupnum_total > 0:
                reply_msg += f"默认池\n总量：{default_groupnum_total}\n已用：{default_groupnum_true}\n空闲：{default_groupnum_total - default_groupnum_true}\n"
            else:
                reply_msg += "默认池\n空\n"
            if playname_groupnum_stats:
                sorted_playnames = sorted(playname_groupnum_stats.keys())
                for playname in sorted_playnames:
                    reply_msg += "-\n"
                    stats = playname_groupnum_stats[playname]
                    if "error" in stats:
                        reply_msg += f"{playname}\n文件读取错误\n"
                    elif stats["total"] > 0:
                        reply_msg += f"{playname}\n总量：{stats['total']}\n已用：{stats['true']}\n空闲：{stats['false']}\n"
                    else:
                        reply_msg += f"{playname}\n空\n"
            else:
                reply_msg += ""
            plugin_event.reply(reply_msg)
            return

    elif "群号" in message:
        lines = message.splitlines()
        if len(lines) == 0:
            return
        command_line = lines[0]
        command_line = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", command_line)
        command_line = command_line.strip()
        if uid not in masterlist:
            return
        groupnum_base_path = "./data/images/恋综备用群/群号"
        if not os.path.exists(groupnum_base_path):
            os.makedirs(groupnum_base_path, exist_ok=True)
        if command_line.startswith("登记"):
            match = re.match(r"登记(默认|.+?)群号", command_line)
            if match:
                target = match.group(1)
                if target == "默认":
                    json_file = os.path.join(groupnum_base_path, "默认池.json")
                else:
                    playname = target
                    register = getData("groupcollection", "register.json")
                    if playname not in register:
                        return
                    json_file = os.path.join(groupnum_base_path, f"{playname}.json")
                existing_data = {}
                with amourlock:
                    if os.path.exists(json_file):
                        try:
                            with open(json_file, "r", encoding="utf-8") as f:
                                existing_data = json.load(f)
                        except Exception as e:
                            Proc.log(5, f"读取群号文件失败：{e}")
                            existing_data = {}
                group_numbers = []
                for line in lines[1:]:
                    line = line.strip()
                    if line and line.isdigit():
                        group_numbers.append(line)
                if not group_numbers:
                    plugin_event.reply("未提供有效的群号，请每行输入一个纯数字群号。")
                    return
                duplicates = []
                new_groups = []
                for group_num in group_numbers:
                    if group_num in existing_data:
                        duplicates.append(group_num)
                    else:
                        new_groups.append(group_num)
                success_count = 0
                for group_num in new_groups:
                    existing_data[group_num] = {"使用情况": False}
                    success_count += 1
                with amourlock:
                    try:
                        with open(json_file, "w", encoding="utf-8") as f:
                            json.dump(existing_data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        plugin_event.reply("保存群号文件失败，请联系骰主检查。")
                        return
                reply_msg = f"群号登记完成！\n成功保存：{success_count}个群号。"
                if duplicates:
                    reply_msg += f"\n\n重复群号（保存失败）：{len(duplicates)}个"
                    reply_msg += f"\n重复群号列表：\n" + "\n".join(duplicates)
                reply_msg += f"\n\n保存到：{json_file}"
                plugin_event.reply(reply_msg)
                return
        elif command_line.startswith("清空"):
            match = re.match(r"清空(默认|.+?)群号", command_line)
            if match:
                target = match.group(1)
                if target == "默认":
                    json_file = os.path.join(groupnum_base_path, "默认池.json")
                    if not os.path.exists(json_file):
                        plugin_event.reply(f"群号文件不存在，无法清空：{json_file}")
                        return
                    empty_data = {}
                    with amourlock:
                        try:
                            with open(json_file, "w", encoding="utf-8") as f:
                                json.dump(empty_data, f, ensure_ascii=False, indent=2)
                        except Exception as e:
                            plugin_event.reply("清空群号文件失败，请联系骰主检查。")
                            return
                    plugin_event.reply(f"默认群号池已清空！")
                    return
                else:
                    playname = target
                    register = getData("groupcollection", "register.json")
                    if playname not in register:
                        return
                    json_file = os.path.join(groupnum_base_path, f"{playname}.json")
                    bak_file = os.path.join(groupnum_base_path, f"{playname}.json.bak")
                    with amourlock:
                        success = True
                        if os.path.exists(json_file):
                            try:
                                os.remove(json_file)
                            except Exception as e:
                                success = False
                        if os.path.exists(bak_file):
                            try:
                                os.remove(bak_file)
                            except Exception as e:
                                pass
                    if success:
                        plugin_event.reply(f"恋综「{playname}」群号池已移除！")
                    else:
                        plugin_event.reply("清空群号文件失败，请联系骰主检查。")
                    return
        elif command_line.startswith("删除"):
            match = re.match(r"删除(默认|.+?)群号", command_line)
            if match:
                target = match.group(1)
                if target == "默认":
                    json_file = os.path.join(groupnum_base_path, "默认池.json")
                else:
                    playname = target
                    register = getData("groupcollection", "register.json")
                    if playname not in register:
                        return
                    json_file = os.path.join(groupnum_base_path, f"{playname}.json")
                if not os.path.exists(json_file):
                    plugin_event.reply(f"群号文件不存在：{json_file}")
                    return
                with amourlock:
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            existing_data = json.load(f)
                    except Exception as e:
                        plugin_event.reply("读取群号文件失败，请联系骰主检查。")
                        return
                groups_to_delete = []
                for line in lines[1:]:
                    line = line.strip()
                    if line and line.isdigit():
                        groups_to_delete.append(line)
                if not groups_to_delete:
                    plugin_event.reply("未提供要删除的群号，请每行输入一个纯数字群号。")
                    return
                deleted_count = 0
                not_found_count = 0
                not_found_groups = []
                for group_num in groups_to_delete:
                    if group_num in existing_data:
                        del existing_data[group_num]
                        deleted_count += 1
                    else:
                        not_found_count += 1
                        not_found_groups.append(group_num)
                with amourlock:
                    try:
                        with open(json_file, "w", encoding="utf-8") as f:
                            json.dump(existing_data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        plugin_event.reply("保存群号文件失败，请联系骰主检查。")
                        return
                reply_msg = f"群号删除完成！\n成功删除：{deleted_count}个群号。"
                if not_found_count > 0:
                    reply_msg += f"\n\n未找到的群号：{not_found_count}个"
                    reply_msg += f"\n未找到的群号列表：{', '.join(not_found_groups)}"
                reply_msg += f"\n\n文件：{json_file}"
                plugin_event.reply(reply_msg)
                return

    elif re.match(r"导出(.+?)复盘", message):
        import zipfile
        from datetime import datetime

        export_match = re.match(r"导出(.+?)复盘", message)
        if export_match:
            game_name = export_match.group(1).strip()
            if not game_name:
                return
            if uid not in masterlist:
                plugin_event.reply("该指令仅骰主权限可使用。")
                return
            register = getData("groupcollection", "register.json")
            if game_name not in register:
                plugin_event.reply(f"恋综「{game_name}」未注册或已注销，无法导出噢！")
                return
            with amourlock:
                base_path = f"./plugin/data/amourgame/恋综复盘/{game_name}"
                message_path = os.path.join(base_path, "message")
                if not os.path.exists(message_path):
                    os.makedirs(message_path)
                tech_file = os.path.join(base_path, "「技术支持」探丸借客@临皋闲人.txt")
                if not os.path.exists(tech_file):
                    tech_content = (
                        "_      /)---(\ \n"
                        "\ \   (/ . . \)\n"
                        " \ \__)-\(*)/\n"
                        "  \_       (_\n"
                        "  (___/-(____)\n"
                        "\n"
                        "「技术支持」探丸借客@临皋闲人\n"
                        "\n"
                        "OlivaDice By lunzhiPenxil"
                    )
                    with open(tech_file, "w", encoding="utf-8") as f:
                        f.write(tech_content)
            privategroup = getData("groupcollection", "privategroup.json")
            letters = getData("sendmessage", "letters.json")
            gifts = getData("sendmessage", "gifts.json")
            notes = getData("sendmessage", "notes.json")
            sms = getData("sendmessage", "sms.json")

            def export_data(data_dict, data_type, playname):
                all_dates = set()
                for key in data_dict.keys():
                    datalist = key.split("/////")
                    if len(datalist) >= 2 and datalist[0].strip() == playname:
                        all_dates.add(datalist[1].strip())
                for date in sorted(all_dates):
                    rep = ""
                    for key, content in data_dict.items():
                        datalist = key.split("/////")
                        if len(datalist) >= 6:
                            data_playname = datalist[0].strip()
                            data_date = datalist[1].strip()
                            if data_playname == playname and data_date == date:
                                sender = datalist[2].strip()
                                recver = datalist[3].strip()
                                signature = datalist[4].strip()
                                timestamp = datalist[5].strip()
                                sender_name = sender
                                recver_name = recver
                                if playname in privategroup:
                                    if sender in privategroup[playname]:
                                        sender_data = privategroup[playname][sender]
                                        sender_name = (
                                            sender_data.get("嘉宾姓名")
                                            or sender_data.get("NPC姓名")
                                            or sender
                                        )
                                    if recver in privategroup[playname]:
                                        recver_data = privategroup[playname][recver]
                                        recver_name = (
                                            recver_data.get("嘉宾姓名")
                                            or recver_data.get("NPC姓名")
                                            or recver
                                        )
                                rep += (
                                    f"{playname} {date} {timestamp}\n"
                                    f"{sender_name} 致 {recver_name}\n"
                                    f"{data_type}\n"
                                    f"内容：{content.strip()}\n"
                                    f"署名：{signature}\n\n"
                                )
                    with amourlock:
                        if rep:
                            filename = f"{date}{playname}{data_type}.txt"
                            filepath = os.path.join(message_path, filename)
                            with open(filepath, "w", encoding="utf-8") as w:
                                w.write(rep.strip())

            export_data(letters, "心动信", game_name)
            export_data(gifts, "礼物", game_name)
            export_data(notes, "小纸条", game_name)
            export_data(sms, "短信", game_name)
            game_folder = base_path
            if not os.path.exists(game_folder):
                plugin_event.reply(f"恋综「{game_name}」的复盘文件夹不存在，无法导出！")
                return
            if not os.listdir(game_folder):
                plugin_event.reply(f"恋综「{game_name}」的复盘文件夹为空，无需打包！")
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"{game_name}：复盘_{timestamp}.zip"
            zip_path = os.path.join(os.path.dirname(game_folder), zip_filename)
            with amourlock:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(game_folder):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, game_folder)
                            zipf.write(file_path, arcname)
            file_count = len(zipf.namelist())
            zip_size = os.path.getsize(zip_path) / (1024 * 1024)
            reply_msg = f"恋综「{game_name}」复盘文件夹打包完成，正在上传中……\n"
            url = f"http://127.0.0.1:{bot_port}/upload_group_file"
            payload = json.dumps(
                {
                    "group_id": int(groupid),
                    "file": os.path.abspath(zip_path).replace("\\", "/"),
                    "name": f"{zip_filename}",
                }
            )
            headers = {
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json",
            }
            response = requests.request("POST", url, headers=headers, data=payload)
            if response.status_code == 200:
                result = response.json()
                if result.get("retcode") == 0:
                    reply_msg += "\n上传成功！"
                else:
                    reply_msg += f"\n上传失败: {result.get('msg', '未知错误')}"
            else:
                reply_msg += f"\n请求失败，状态码: {response.status_code}"
            plugin_event.reply(reply_msg)
            return

    if re.match(
        r"注销恋综\s*\[OP:at,id=(\d+)\]",
        message,
    ):
        match = re.match(r"注销恋综\s*\[OP:at,id=(\d+)\]", message)
        if match:
            at_id = match.group(1)
            if at_id != str(plugin_event.bot_info.id):
                return
            if uid not in masterlist:
                plugin_event.reply("只有骰主权限才能使用该命令。")
                return
            register = getData("groupcollection", "register.json")
            if not register:
                plugin_event.reply("未找到符合条件的恋综数据。")
                return
            matched_playnames = []
            for playname, reg_data in register.items():
                manage_group = str(reg_data.get("manage_group", ""))
                if manage_group == groupid:
                    matched_playnames.append(playname)
            if not matched_playnames:
                plugin_event.reply("请在恋综的后台群注销噢！")
                return
            if len(matched_playnames) > 1:
                plugin_event.reply(
                    f"检测到多个恋综使用本群作为后台群，将注销最后一个注册的恋综：{matched_playnames[-1]}"
                )
            playname = matched_playnames[-1]
            success_count = 0
            error_count = 0
            extra_msg = ""
            play_method = register[playname].get("play_method", "不使用")
            with amourlock:
                qrcode_playname_path = f"./data/images/恋综备用群/二维码/{playname}"
                if os.path.exists(qrcode_playname_path) and os.path.isdir(
                    qrcode_playname_path
                ):
                    try:
                        files = [
                            f
                            for f in os.listdir(qrcode_playname_path)
                            if os.path.isfile(os.path.join(qrcode_playname_path, f))
                        ]
                        files = [item for item in files if item.startswith("已占用")]
                        if files:
                            for file in files:
                                try:
                                    new_name = file.replace("已占用_", "")
                                    number = 1
                                    base_name, extension = os.path.splitext(new_name)
                                    while os.path.exists(
                                        os.path.join(qrcode_playname_path, new_name)
                                    ):
                                        new_name = f"{base_name}({number}){extension}"
                                        number += 1
                                    old_file_path = os.path.join(
                                        qrcode_playname_path, file
                                    )
                                    new_file_path = os.path.join(
                                        qrcode_playname_path, new_name
                                    )
                                    os.rename(old_file_path, new_file_path)
                                    success_count += 1
                                except OSError as e:
                                    error_count += 1
                                    continue
                    except Exception as e:
                        error_count += 1
                else:
                    if play_method == "二维码":
                        default_qrcode_path = "./data/images/恋综备用群/二维码/默认池"
                        if os.path.exists(default_qrcode_path) and os.path.isdir(
                            default_qrcode_path
                        ):
                            try:
                                files = [
                                    f
                                    for f in os.listdir(default_qrcode_path)
                                    if os.path.isfile(
                                        os.path.join(default_qrcode_path, f)
                                    )
                                ]
                                files = [
                                    item for item in files if item.startswith("已占用")
                                ]
                                if files:
                                    for file in files:
                                        try:
                                            new_name = file.replace("已占用_", "")
                                            number = 1
                                            base_name, extension = os.path.splitext(
                                                new_name
                                            )
                                            while os.path.exists(
                                                os.path.join(
                                                    default_qrcode_path, new_name
                                                )
                                            ):
                                                new_name = (
                                                    f"{base_name}({number}){extension}"
                                                )
                                                number += 1
                                            old_file_path = os.path.join(
                                                default_qrcode_path, file
                                            )
                                            new_file_path = os.path.join(
                                                default_qrcode_path, new_name
                                            )
                                            os.rename(old_file_path, new_file_path)
                                            success_count += 1
                                        except OSError as e:
                                            error_count += 1
                                            continue
                                    extra_msg += "由于没有对应的二维码池，已将默认二维码池全部恢复空闲。\n"
                            except Exception as e:
                                error_count += 1
            with amourlock:
                groupnum_playname_file = (
                    f"./data/images/恋综备用群/群号/{playname}.json"
                )
                if os.path.exists(groupnum_playname_file):
                    try:
                        with open(groupnum_playname_file, "r", encoding="utf-8") as f:
                            group_data = json.load(f)
                        changed = False
                        for group_id, group_info in group_data.items():
                            if (
                                isinstance(group_info, dict)
                                and group_info.get("使用情况") == True
                            ):
                                group_info["使用情况"] = False
                                changed = True
                                success_count += 1
                        if changed:
                            with open(
                                groupnum_playname_file, "w", encoding="utf-8"
                            ) as f:
                                json.dump(group_data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        error_count += 1
                else:
                    if play_method == "群号":
                        default_groupnum_file = (
                            "./data/images/恋综备用群/群号/默认池.json"
                        )
                        if os.path.exists(default_groupnum_file):
                            try:
                                with open(
                                    default_groupnum_file, "r", encoding="utf-8"
                                ) as f:
                                    group_data = json.load(f)
                                changed = False
                                for group_id, group_info in group_data.items():
                                    if (
                                        isinstance(group_info, dict)
                                        and group_info.get("使用情况") == True
                                    ):
                                        group_info["使用情况"] = False
                                        changed = True
                                        success_count += 1
                                if changed:
                                    with open(
                                        default_groupnum_file, "w", encoding="utf-8"
                                    ) as f:
                                        json.dump(
                                            group_data, f, ensure_ascii=False, indent=2
                                        )
                                    extra_msg += "由于没有对应的群号池，已将默认群号池全部恢复空闲。\n"
                            except Exception as e:
                                error_count += 1
            try:
                letters = getData("sendmessage", "letters.json")
                keys_to_delete = []
                for key in letters.keys():
                    datalist = key.split("/////")
                    if len(datalist) >= 2 and datalist[0].strip() == playname:
                        keys_to_delete.append(key)
                for key in keys_to_delete:
                    del letters[key]
                if keys_to_delete:
                    setData("sendmessage", "letters.json", letters)
                    success_count += 1
            except:
                error_count += 1
            try:
                gifts = getData("sendmessage", "gifts.json")
                keys_to_delete = []
                for key in gifts.keys():
                    datalist = key.split("/////")
                    if len(datalist) >= 2 and datalist[0].strip() == playname:
                        keys_to_delete.append(key)
                for key in keys_to_delete:
                    del gifts[key]
                if keys_to_delete:
                    setData("sendmessage", "gifts.json", gifts)
                    success_count += 1
            except:
                error_count += 1
            try:
                notes = getData("sendmessage", "notes.json")
                keys_to_delete = []
                for key in notes.keys():
                    datalist = key.split("/////")
                    if len(datalist) >= 2 and datalist[0].strip() == playname:
                        keys_to_delete.append(key)
                for key in keys_to_delete:
                    del notes[key]
                if keys_to_delete:
                    setData("sendmessage", "notes.json", notes)
                    success_count += 1
            except:
                error_count += 1
            try:
                sms = getData("sendmessage", "sms.json")
                keys_to_delete = []
                for key in sms.keys():
                    datalist = key.split("/////")
                    if len(datalist) >= 2 and datalist[0].strip() == playname:
                        keys_to_delete.append(key)
                for key in keys_to_delete:
                    del sms[key]
                if keys_to_delete:
                    setData("sendmessage", "sms.json", sms)
                    success_count += 1
            except:
                error_count += 1
            try:
                limit = getData("sendmessage", "limit.json")
                if playname in limit:
                    del limit[playname]
                    setData("sendmessage", "limit.json", limit)
                    success_count += 1
            except:
                error_count += 1
            try:
                summary = getData("engagement", "summary.json")
                if playname in summary:
                    del summary[playname]
                    setData("engagement", "summary.json", summary)
                    success_count += 1
            except:
                error_count += 1
            try:
                usertime = getData("engagement", "usertime.json")
                if playname in usertime:
                    del usertime[playname]
                    setData("engagement", "usertime.json", usertime)
                    success_count += 1
            except:
                error_count += 1
            try:
                timeline = getData("engagement", "timeline.json")
                if playname in timeline:
                    del timeline[playname]
                    setData("engagement", "timeline.json", timeline)
                    success_count += 1
            except:
                error_count += 1
            codes_to_delete = []
            try:
                appoint = getData("engagement", "appoint.json")
                for code, appointment in appoint.items():
                    if appointment.get("playname") == playname:
                        codes_to_delete.append(code)
                for code in codes_to_delete:
                    del appoint[code]
                if codes_to_delete:
                    setData("engagement", "appoint.json", appoint)
                    success_count += 1
            except:
                error_count += 1
            try:
                msg_appoint = getData("engagement", "msg_appoint.json")
                removed_state = False
                for state_group, state in list(msg_appoint.items()):
                    if not isinstance(state, dict):
                        continue
                    if (
                        state.get("playname") == playname
                        or str(state.get("code", "")) in codes_to_delete
                    ):
                        del msg_appoint[state_group]
                        removed_state = True
                if removed_state:
                    setData("engagement", "msg_appoint.json", msg_appoint)
                    success_count += 1
            except:
                error_count += 1
            try:
                phone_data = getData("engagement", "phone.json")
                if playname in phone_data:
                    del phone_data[playname]
                    setData("engagement", "phone.json", phone_data)
                    success_count += 1
            except:
                error_count += 1
            try:
                notice_data = getData("engagement", "notice.json")
                if playname in notice_data:
                    del notice_data[playname]
                    setData("engagement", "notice.json", notice_data)
                    success_count += 1
            except:
                error_count += 1
            try:
                monitor_config = getData("engagement", "api_port.json")
                reminder_config = monitor_config.get("催戏", {})
                if isinstance(reminder_config, dict) and playname in reminder_config:
                    del reminder_config[playname]
                    monitor_config["催戏"] = reminder_config
                    setData("engagement", "api_port.json", monitor_config)
                    success_count += 1
            except:
                error_count += 1
            try:
                record_path = "./plugin/data/amourgame/record"
                record_files = [
                    _monitor_record_filename(playname),
                    _monitor_arc_filename(playname),
                ]
                removed_record = False
                for record_filename in record_files:
                    for suffix in ("", ".bak"):
                        target_path = os.path.join(
                            record_path, record_filename + suffix
                        )
                        if os.path.exists(target_path):
                            os.remove(target_path)
                            removed_record = True
                if removed_record:
                    success_count += 1
            except:
                error_count += 1
            try:
                lettertime = getData("groupcollection", "lettertime.json")
                if playname in lettertime:
                    del lettertime[playname]
                    setData("groupcollection", "lettertime.json", lettertime)
                    success_count += 1
            except:
                pass
            try:
                privategroup = getData("groupcollection", "privategroup.json")
                if playname in privategroup:
                    del privategroup[playname]
                    setData("groupcollection", "privategroup.json", privategroup)
                    success_count += 1
            except:
                error_count += 1
                pass
            try:
                os.remove(f"./plugin/data/amourgame/relation/{playname}.json")
                os.remove(f"./plugin/data/amourgame/relation/{playname}.json.bak")
                success_count += 1
            except:
                error_count += 1
            try:
                os.remove(f"./plugin/data/amourgame/public/{playname}.json")
                os.remove(f"./plugin/data/amourgame/public/{playname}.json.bak")
                success_count += 1
            except:
                error_count += 1
            try:
                os.remove(f"./plugin/data/amourgame/routine/{playname}.json")
                os.remove(f"./plugin/data/amourgame/routine/{playname}.json.bak")
                success_count += 1
            except:
                error_count += 1
            try:
                if playname in register:
                    playname_display = playname
                    del register[playname]
                    setData("groupcollection", "register.json", register)
                    success_count += 1
                else:
                    plugin_event.reply(
                        f"在plugin/data/amourgame/groupcollection/register.json中移除{playname}数据失败，请根据路径手动移除，以免造成bug。"
                    )
                    return
            except:
                error_count += 1
            msg = f"恋综「{playname_display}」注销完成！\n\n"
            msg += f"成功：{success_count}项\n"
            if error_count > 0:
                msg += f"失败：{error_count}项\n"
            msg += f"\n所有数据已全部移除！\n\n"
            msg += f"所有相关池内的小群已恢复空闲！\n\n"
            if extra_msg:
                msg += extra_msg + "\n"
            msg += f"如有坏数据，在没有进行任何恋综的情况下，可发送「修正所有恋综数据」以移除所有后台数据，并释放所有小群。"
            plugin_event.reply(msg)

    elif message == "修正所有恋综数据":
        if uid not in masterlist:
            plugin_event.reply("只有骰主权限才能使用该命令。")
            return
        success_count = 0
        error_count = 0
        with amourlock:
            qrcode_base_path = "./data/images/恋综备用群/二维码/"
            if os.path.exists(qrcode_base_path):
                all_dirs = []
                if os.path.exists(os.path.join(qrcode_base_path, "默认池")):
                    all_dirs.append(os.path.join(qrcode_base_path, "默认池"))
                for item in os.listdir(qrcode_base_path):
                    item_path = os.path.join(qrcode_base_path, item)
                    if os.path.isdir(item_path) and item != "默认池":
                        all_dirs.append(item_path)
                for dir_path in all_dirs:
                    try:
                        files = [
                            f
                            for f in os.listdir(dir_path)
                            if os.path.isfile(os.path.join(dir_path, f))
                        ]
                        files = [item for item in files if item.startswith("已占用")]
                        if not files:
                            continue
                        for file in files:
                            try:
                                new_name = file.replace("已占用_", "")
                                number = 1
                                base_name, extension = os.path.splitext(new_name)
                                while os.path.exists(os.path.join(dir_path, new_name)):
                                    new_name = f"{base_name}({number}){extension}"
                                    number += 1
                                old_file_path = os.path.join(dir_path, file)
                                new_file_path = os.path.join(dir_path, new_name)
                                os.rename(old_file_path, new_file_path)
                                success_count += 1
                            except OSError as e:
                                error_count += 1
                                continue
                    except Exception as e:
                        error_count += 1
        with amourlock:
            groupnum_base_path = "./data/images/恋综备用群/群号/"
            if os.path.exists(groupnum_base_path):
                json_files = []
                default_file = os.path.join(groupnum_base_path, "默认池.json")
                if os.path.exists(default_file):
                    json_files.append(default_file)
                for item in os.listdir(groupnum_base_path):
                    if item.endswith(".json") and item != "默认池.json":
                        json_files.append(os.path.join(groupnum_base_path, item))
                for json_file in json_files:
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            group_data = json.load(f)
                        changed = False
                        for group_id, group_info in group_data.items():
                            if (
                                isinstance(group_info, dict)
                                and group_info.get("使用情况") == True
                            ):
                                group_info["使用情况"] = False
                                changed = True
                                success_count += 1
                        if changed:
                            with open(json_file, "w", encoding="utf-8") as f:
                                json.dump(group_data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        error_count += 1
        usertime = {}
        timeline = {}
        appoint = {}
        switch = {}
        letters = {}
        notes = {}
        gifts = {}
        limit = {}
        sms = {}
        lettertime = {}
        privategroup = {}
        register = {}
        summary = {}
        setData("engagement", "summary.json", summary)
        setData("engagement", "usertime.json", usertime)
        setData("engagement", "timeline.json", timeline)
        setData("engagement", "appoint.json", appoint)
        setData("engagement", "switch.json", switch)
        setData("sendmessage", "letters.json", letters)
        setData("sendmessage", "notes.json", notes)
        setData("sendmessage", "gifts.json", gifts)
        setData("sendmessage", "sms.json", sms)
        setData("sendmessage", "limit.json", limit)
        setData("groupcollection", "lettertime.json", lettertime)
        setData("groupcollection", "privategroup.json", privategroup)
        setData("groupcollection", "register.json", register)
        with amourlock:
            engagement_path = "./plugin/data/amourgame/engagement/"
            if os.path.exists(engagement_path):
                keep_files = {
                    "appoint.json",
                    "appoint.json.bak",
                    "timeline.json",
                    "timeline.json.bak",
                    "usertime.json",
                    "usertime.json.bak",
                }
                try:
                    for filename in os.listdir(engagement_path):
                        file_path = os.path.join(engagement_path, filename)
                        if os.path.isfile(file_path):
                            if filename not in keep_files:
                                try:
                                    os.remove(file_path)
                                    success_count += 1
                                except:
                                    error_count += 1
                except:
                    pass
        plugin_event.reply(
            f"所有恋综的所有数据均修正完成！\n\n成功：{success_count}项\n失败：{error_count}项"
        )

    elif re.match(r"(.+?)\s*关系线截止日期\s*(\d{8})", message):
        match = re.match(r"(.+?)\s*关系线截止日期\s*(\d{8})", message)
        if not match:
            return
        playname = match.group(1).strip()
        date_str = match.group(2).strip()
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主权限可设置关系线截止日期。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中设置关系线截止日期。")
            return
        if not re.match(r"^\d{8}$", date_str):
            plugin_event.reply("日期格式错误！请使用8位数字格式，例如：20260130")
            return
        try:
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
            if month < 1 or month > 12:
                plugin_event.reply("月份必须在01-12范围内！")
                return
            if day < 1 or day > 31:
                plugin_event.reply("日期必须在01-31范围内！")
                return
            from datetime import datetime

            try:
                datetime(year, month, day)
            except ValueError:
                plugin_event.reply("日期不合法！请检查月份和日期的组合。")
                return
        except ValueError:
            plugin_event.reply("日期格式错误！请使用正确的8位数字格式，如20260130")
            return
        try:
            limit_data = getData("sendmessage", "limit.json")
        except:
            limit_data = {}
        if playname not in limit_data:
            limit_data[playname] = {}
        limit_data[playname]["relation"] = date_str
        setData("sendmessage", "limit.json", limit_data)
        reply_msg = (
            f"恋综「{playname}」已设置关系线截止日期！\n"
            f"{year}年{month:02d}月{day:02d}日24:00前可以发送关系线。"
        )
        plugin_event.reply(reply_msg)

    elif re.match(
        r"^(.+?)\s*限制(微信|私约|电话|心愿|留言板|点歌)\s*(-?\d+)$", message
    ):
        match = re.match(
            r"^(.+?)\s*限制(微信|私约|电话|心愿|留言板|点歌)\s*(-?\d+)$", message
        )
        if match:
            playname = match.group(1).strip()
            limit_type = match.group(2).strip()
            limit_num = int(match.group(3).strip())
            if uid not in masterlist:
                plugin_event.reply("权限不足，仅骰主权限可设置限制数量。")
                return
            register = getData("groupcollection", "register.json")
            if playname not in register:
                plugin_event.reply(
                    f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！"
                )
                return
            data = register[playname]
            manage_group = data.get("manage_group")
            if groupid != manage_group:
                plugin_event.reply(f"请在恋综「{playname}」的后台群中设置限制数量。")
                return
            if limit_num < -1:
                plugin_event.reply(
                    "限制数量不能为其他负数，0表示不能使用，-1表示移除限制。"
                )
                return
            limit_data = getData("sendmessage", "limit.json")
            if playname not in limit_data:
                limit_data[playname] = {}
            limit_type_key = limit_type
            if limit_num == -1:
                # 移除限制
                if limit_type_key in limit_data[playname]:
                    del limit_data[playname][limit_type_key]
                    if not limit_data[playname]:
                        del limit_data[playname]
                    if limit_type in ["微信", "私约", "电话", "心愿"]:
                        reply_msg = f"已移除恋综「{playname}」的{limit_type}每日限制。"
                    else:  # 留言板、点歌
                        reply_msg = (
                            f"已移除恋综「{playname}」的{limit_type}日程总数量限制。"
                        )
                else:
                    reply_msg = (
                        f"恋综「{playname}」没有设置{limit_type}数量限制，无需移除。"
                    )
            else:
                limit_data[playname][limit_type_key] = limit_num
                if limit_num == 0:
                    # 限制为0的情况
                    if limit_type in ["微信", "私约", "电话", "心愿"]:
                        reply_msg = f"已禁止恋综「{playname}」的{limit_type}功能。"
                    else:  # 留言板、点歌
                        reply_msg = f"已禁止恋综「{playname}」的{limit_type}功能。"
                else:
                    # 正常限制数量
                    if limit_type in ["微信", "私约", "电话", "心愿"]:
                        reply_msg = f"已将恋综「{playname}」的{limit_type}限制为每日每人{limit_num}。"
                    else:  # 留言板、点歌
                        reply_msg = f"已将恋综「{playname}」的{limit_type}限制为日程总计数量{limit_num}，可按需修改。"
            setData("sendmessage", "limit.json", limit_data)
            plugin_event.reply(reply_msg)

    elif re.match(r"(\S+)\s*一键收群$", message):
        match = re.match(r"(\S+)\s*一键收群$", message)
        if not match:
            return
        playname = match.group(1)
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可执行此操作")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中一键收群！")
            return
        appoint = getData("engagement", "appoint.json")
        target_appoints = {}
        for code, data in appoint.items():
            group_value = str(data.get("group", ""))
            if data.get("playname") == playname and group_value.isdigit():
                target_appoints[code] = data
        if not target_appoints:
            plugin_event.reply(f"恋综「{playname}」当前没有任何未释放小群！")
            return
        total_groups = len(target_appoints)
        success_count = 0
        failed_groups = []
        plugin_event.reply(
            f"恋综「{playname}」共有{total_groups}个未释放小群，现在开始一键收群……\n\n请等待成功回执。"
        )
        for i, (code, appointment) in enumerate(list(target_appoints.items())):
            target_group_id = str(appointment.get("group", ""))
            participant_ids = _appointment_participant_ids(appointment)
            released = release_group_with_code(
                plugin_event, code, appointment, group_id=target_group_id, reply=False
            )
            if not released:
                failed_groups.append(f"{code}（{target_group_id}）")
                continue
            success_count += 1
            at_text = " ".join(f"[OP:at,id={qq}]" for qq in participant_ids)
            notify_text = f"本小群已由后台一键收群释放。"
            if at_text:
                notify_text += f"\n\n{at_text}"
            try:
                plugin_event.send("group", target_group_id, notify_text)
            except Exception as e:
                failed_groups.append(f"{code}（通知失败：{e}）")
            if i < total_groups - 1:
                time.sleep(1)
        reply_msg = f"恋综「{playname}」一键收群完成！\n成功释放：{success_count}/{total_groups}"
        if failed_groups:
            reply_msg += f"\n失败/异常：{len(failed_groups)}个\n" + "\n".join(failed_groups[:10])
            if len(failed_groups) > 10:
                reply_msg += f"\n等{len(failed_groups)}个"
        plugin_event.reply(reply_msg)

    elif re.match(r"(\S+)\s*设置小群白名单\s+(.+)", message):
        match = re.match(r"(\S+)\s*设置小群白名单\s+(.+)", message)
        if not match:
            return
        playname = match.group(1)
        whitelist = _parse_cleanup_whitelist(match.group(2))
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可执行此操作")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中设置小群白名单！")
            return
        register[playname]["cleanup_whitelist"] = whitelist
        setData("groupcollection", "register.json", register)
        if whitelist:
            plugin_event.reply(
                f"恋综「{playname}」小群白名单已设置为：{'、'.join(whitelist)}"
            )
        else:
            plugin_event.reply(f"恋综「{playname}」小群白名单已清空。")

    elif re.match(r"(\S+)\s*(检测小群|清理小群|提醒退群|踢出小群)$", message):
        match = re.match(r"(\S+)\s*(检测小群|清理小群|提醒退群|踢出小群)$", message)
        if not match:
            return
        playname = match.group(1)
        action = match.group(2)
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可执行此操作")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中{action}！")
            return
        play_method = data.get("play_method", "不使用")
        if play_method not in ["二维码", "群号"]:
            plugin_event.reply(f"恋综「{playname}」未启用备用群池。")
            return
        pool_groups = _unused_pool_groups(playname, play_method)
        if not pool_groups:
            plugin_event.reply(f"恋综「{playname}」当前没有可检测的空闲小群。")
            return
        plugin_event.reply(
            f"恋综「{playname}」共有{len(pool_groups)}个空闲小群，现在开始{action}……"
        )
        dirty_groups = []
        failed_groups = []
        whitelist = set(str(item) for item in data.get("cleanup_whitelist", []))
        ignored_whitelist_count = 0
        bot_id = str(plugin_event.bot_info.id)
        for group_info in pool_groups:
            target_group_id = group_info["group_id"]
            members = get_group_member_detail_list(plugin_event, target_group_id)
            if members is None:
                failed_groups.append(target_group_id)
                continue
            normal_members = []
            for member in members:
                member_id = str(member.get("user_id", ""))
                if member_id == bot_id:
                    continue
                if member_id in whitelist:
                    ignored_whitelist_count += 1
                    continue
                display_name = (
                    member.get("card")
                    or member.get("nickname")
                    or member.get("name")
                    or member_id
                )
                normal_members.append(
                    {"id": member_id, "display": f"{display_name}（{member_id}）"}
                )
            if normal_members:
                dirty_groups.append(
                    {
                        "group_id": target_group_id,
                        "source": group_info.get("source", ""),
                        "members": normal_members,
                    }
                )
            time.sleep(0.3)
        if not dirty_groups and not failed_groups:
            plugin_event.reply(
                f"恋综「{playname}」空闲小群检测完成，未发现普通成员滞留。"
            )
            return
        remind_failed = []
        kick_success = 0
        kick_failed = []
        if action == "提醒退群":
            for item in dirty_groups:
                at_text = " ".join(
                    f"[OP:at,id={member['id']}]" for member in item["members"]
                )
                remind_text = (
                    f"{at_text} 请非管理成员及时退群！"
                )
                try:
                    plugin_event.send("group", item["group_id"], remind_text)
                except Exception as e:
                    remind_failed.append(f"{item['group_id']}（{e}）")
                time.sleep(0.5)
        elif action == "踢出小群":
            for item in dirty_groups:
                for member in item["members"]:
                    ok, err = kick_group_member(plugin_event, item["group_id"], member["id"])
                    if ok:
                        kick_success += 1
                    else:
                        kick_failed.append(
                            f"{item['group_id']} {member['display']}（{err or '未知错误'}）"
                        )
                    time.sleep(0.3)
        nodes_data = [
            {
                "bot_id": bot_id,
                "content_text": (
                    f"恋综「{playname}」空闲小群{action}结果\n"
                    f"检测小群：{len(pool_groups)}个\n"
                    f"存在非白名单成员：{len(dirty_groups)}个\n"
                    f"忽略白名单成员：{ignored_whitelist_count}人\n"
                    f"检测失败：{len(failed_groups)}个"
                ),
            }
        ]
        for item in dirty_groups:
            nodes_data.append(
                {
                    "bot_id": bot_id,
                    "content_text": (
                        f"群号：{item['group_id']}\n"
                        f"来源：{item['source'] or '未知'}\n"
                        f"非白名单成员：\n" + "\n".join(member["display"] for member in item["members"])
                    ),
                }
            )
        if failed_groups:
            nodes_data.append(
                {
                    "bot_id": bot_id,
                    "content_text": "以下小群检测失败：\n" + "\n".join(failed_groups),
                }
            )
        if remind_failed:
            nodes_data.append(
                {
                    "bot_id": bot_id,
                    "content_text": "以下小群提醒发送失败：\n" + "\n".join(remind_failed),
                }
            )
        if action == "踢出小群":
            kick_summary = f"踢出成功：{kick_success}人"
            if kick_failed:
                kick_summary += f"\n踢出失败：{len(kick_failed)}人\n" + "\n".join(kick_failed[:20])
                if len(kick_failed) > 20:
                    kick_summary += f"\n等{len(kick_failed)}人"
            nodes_data.append({"bot_id": bot_id, "content_text": kick_summary})
        result = send_forward_message(bot_port, bot_token, groupid, nodes_data)
        if result.get("retcode") != 0:
            reply_msg = (
                f"恋综「{playname}」空闲小群{action}完成。\n"
                f"存在非白名单成员：{len(dirty_groups)}个\n"
                f"忽略白名单成员：{ignored_whitelist_count}人\n"
                f"检测失败：{len(failed_groups)}个"
            )
            if action == "提醒退群":
                reply_msg += f"\n提醒失败：{len(remind_failed)}个"
            elif action == "踢出小群":
                reply_msg += f"\n踢出成功：{kick_success}人\n踢出失败：{len(kick_failed)}人"
            plugin_event.reply(reply_msg)

    elif re.match(r"(\S+)\s*小群催戏$", message):
        match = re.match(r"(\S+)\s*小群催戏$", message)
        if not match:
            return
        playname = match.group(1)
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可执行此操作")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中催戏！")
            return
        appoint = getData("engagement", "appoint.json")
        target_appoints = {}
        for code, data in appoint.items():
            if data.get("playname") == playname:
                target_appoints[code] = data
        if not target_appoints:
            plugin_event.reply(f"恋综「{playname}」当前没有任何小群记录！")
            return
        total_groups = len(target_appoints)
        plugin_event.reply(
            f"恋综「{playname}」共有{total_groups}个未释放小群，现在开始每隔2秒发送一次催戏……\n\n请等待成功回执。"
        )
        for i, (code, data) in enumerate(target_appoints.items()):
            group_id = data.get("group")
            inviter = data.get("inviter")
            invitee = data.get("invitee", [])
            at_qq_list = []
            if inviter != "官方" and inviter and inviter.isdigit():
                at_qq_list.append(inviter)
            for qq in invitee:
                if qq and isinstance(qq, str) and qq.isdigit():
                    at_qq_list.append(qq)
            if not at_qq_list:
                message_content = f"后台无差别一键催戏！"
            else:
                at_messages = []
                for qq in at_qq_list:
                    at_messages.append(f"[OP:at,id={qq}] ")
                at_string = " ".join(at_messages)
                message_content = f"后台无差别一键催戏\n\n{at_string}"
            try:
                group_id_str = str(group_id)
                if group_id_str.isdigit() and len(group_id_str) >= 5:
                    plugin_event.send("group", group_id_str, message_content)
                    if i < total_groups - 1:
                        time.sleep(2)
                else:
                    plugin_event.reply(f"跳过无效群号: {group_id_str}")
            except Exception as e:
                plugin_event.reply(
                    f"向群 {group_id} 发送催戏消息失败: {e}\n\n失败原因可能是未成功映射二维码至群号。\n请在恋综结束后，使用插件QRcodeCollection完成收集。"
                )
        plugin_event.reply(
            f"恋综「{playname}」催戏完成！已向{total_groups}个群发送催戏消息。"
        )

    elif re.match(r"(\S+)\s*个人群催戏$", message):
        match = re.match(r"(\S+)\s*个人群催戏$", message)
        if not match:
            return
        playname = match.group(1)
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可执行此操作")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中执行个人群催戏！")
            return
        appoint = getData("engagement", "appoint.json")
        target_appoints = {}
        for code, data in appoint.items():
            if data.get("playname") == playname:
                target_appoints[code] = data
        if not target_appoints:
            plugin_event.reply(f"恋综「{playname}」当前没有小群记录！")
            return
        privategroup = getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            return
        guest_stats = {}
        participant_uids = set()
        for code, data in target_appoints.items():
            inviter = data.get("inviter")
            invitee_list = data.get("invitee", [])
            playtime = data.get("playtime", "")
            day_part = playtime.split()[0] if playtime and " " in playtime else "未知"
            if inviter and inviter != "官方" and inviter.isdigit():
                participant_uids.add(inviter)
                if inviter not in guest_stats:
                    guest_stats[inviter] = {"total": 0, "days": {}}
                guest_stats[inviter]["total"] += 1
                if day_part in guest_stats[inviter]["days"]:
                    guest_stats[inviter]["days"][day_part] += 1
                else:
                    guest_stats[inviter]["days"][day_part] = 1
            for invitee_uid in invitee_list:
                if (
                    invitee_uid
                    and isinstance(invitee_uid, str)
                    and invitee_uid.isdigit()
                ):
                    participant_uids.add(invitee_uid)
                    if invitee_uid not in guest_stats:
                        guest_stats[invitee_uid] = {"total": 0, "days": {}}
                    guest_stats[invitee_uid]["total"] += 1
                    if day_part in guest_stats[invitee_uid]["days"]:
                        guest_stats[invitee_uid]["days"][day_part] += 1
                    else:
                        guest_stats[invitee_uid]["days"][day_part] = 1
        valid_guests = {}
        for uid_str in participant_uids:
            if uid_str in privategroup[playname]:
                guest_data = privategroup[playname][uid_str]
                if "NPC姓名" in guest_data:
                    continue
                guest_name = guest_data.get("嘉宾姓名", uid_str)
                personal_group = guest_data.get("个人群号")
                if personal_group:
                    valid_guests[uid_str] = {
                        "name": guest_name,
                        "group": personal_group,
                        "stats": guest_stats.get(uid_str, {"total": 0, "days": {}}),
                    }
        if not valid_guests:
            plugin_event.reply(f"恋综「{playname}」没有找到嘉宾个人群数据！")
            return
        plugin_event.reply(
            f"恋综「{playname}」共有{len(valid_guests)}位嘉宾，现在开始每隔2秒发送个人群催戏通知……\n\n请等待成功回执。"
        )
        success_count = 0
        fail_count = 0
        fail_details = []
        for i, (guest_uid, guest_info) in enumerate(valid_guests.items()):
            guest_name = guest_info["name"]
            group_id = guest_info["group"]
            stats = guest_info["stats"]
            message_content = "【后台无差别催戏】\n\n"
            message_content += f"{guest_name}未结小群\n\n"
            if stats["total"] > 0:
                sorted_days = sorted(stats["days"].items(), key=lambda x: x[0])
                for day, count in sorted_days:
                    message_content += f"{day}：{count}\n"
            else:
                message_content += "无\n"
            try:
                group_id_str = str(group_id)
                if group_id_str.isdigit() and len(group_id_str) >= 5:
                    plugin_event.send("group", group_id_str, message_content)
                    success_count += 1
                else:
                    fail_count += 1
                    fail_details.append(
                        f"嘉宾「{guest_name}」的群号无效：{group_id_str}"
                    )
            except Exception as e:
                fail_count += 1
                fail_details.append(
                    f"向嘉宾「{guest_name}」的个人群发送催戏消息失败：{e}"
                )
            if i < len(valid_guests) - 1:
                time.sleep(2)
        result_message = f"恋综「{playname}」个人群催戏完成！\n"
        result_message += f"成功：{success_count}\n"
        result_message += f"失败：{fail_count}\n"
        if fail_details:
            result_message += "\n\n失败详情：\n"
            for detail in fail_details:
                result_message += f"{detail}\n"
        plugin_event.reply(result_message)

    elif re.match(r"(.+)\s*通知受邀者\s*(开启|关闭)$", message):
        match = re.match(r"(.+)\s*通知受邀者\s*(开启|关闭)$", message)
        if not match:
            return
        playname = match.group(1).strip()
        operation = match.group(2).strip()
        if operation not in ["开启", "关闭"]:
            return
        playname = match.group(1).strip()
        operation = match.group(2).strip()
        if uid not in masterlist:
            plugin_event.reply("如需修改通知设置，请联系骰主开放权限。")
            return
        register = getData("groupcollection", "register.json")
        if playname not in register:
            plugin_event.reply(f"恋综「{playname}」未注册或已注销，请检查恋综名称噢！")
            return
        data = register[playname]
        manage_group = data.get("manage_group")
        if groupid != manage_group:
            plugin_event.reply(f"请在恋综「{playname}」的后台群中修改通知设置！")
            return
        switch_value = True if operation == "开启" else False
        switch_data = getData("engagement", "switch.json")
        if playname not in switch_data:
            switch_data[playname] = {}
        switch_data[playname]["通知受邀者"] = switch_value
        setData("engagement", "switch.json", switch_data)
        status_text = "已开启" if switch_value else "已关闭"
        plugin_event.reply(
            f"恋综「{playname}」{status_text}该功能。\n"
            f"当受邀者时间冲突时，{'会' if switch_value else '不会'}通知相关受邀者。\n\n【注意】\n‼️‼️本功能默认关闭，需要手动开启。开启时，多人小群（包括官约）将查找所有时间线被占用的受邀嘉宾，出于信息对等考虑，开群失败通知将会发送给全部受邀方，邀约方回执内不会详细说明，开启本功能时请管理务必主动告知恋综嘉宾这一点。\n若多个受邀者同时时间冲突，则只有完全空闲的受邀者（逻辑为赴约后看到谁没来）收到的通知可查看所有的冲突受邀者名单。"
        )

    elif re.match(r"(开启|关闭)电话dlc(1|2)", message.lower()):
        option = re.match(r"(开启|关闭)电话dlc(1|2)", message.lower()).group(1)
        dlc = re.match(r"(开启|关闭)电话dlc(1|2)", message.lower()).group(2)
        ###
        ###
        ###
        ###电话dlc1：随机电话功能，只需在“受邀者”栏填写“随机”
        ###电话dlc2：电话随机泄漏功能，开启后，任何一段电话戏，均有20%的概率泄露随机20字至随机一名同综嘉宾的个人群内
        ###
        ###
        ###
        if uid not in masterlist:
            plugin_event.reply("只有骰主权限才能使用该命令。")
            return
        dlc1 = Proc.database.get_basic_config(
            "AmourGame", "dlc1", default_value="0", pkl=False
        )
        dlc2 = Proc.database.get_basic_config(
            "AmourGame", "dlc2", default_value="0", pkl=False
        )
        if option == "开启":
            if dlc == "1":
                Proc.database.set_basic_config(
                    "AmourGame", "dlc1", "1", pkl=False
                )
                plugin_event.reply("全局的电话dlc1已开启，效果：随机电话。")
            if dlc == "2":
                Proc.database.set_basic_config(
                    "AmourGame", "dlc2", "1", pkl=False
                )
                plugin_event.reply("全局的电话dlc2已开启，效果：随机电话泄漏。")
        if option == "关闭":
            if dlc == "1":
                Proc.database.set_basic_config(
                    "AmourGame", "dlc1", "0", pkl=False
                )
                plugin_event.reply("全局的电话dlc1已关闭。")
            if dlc == "2":
                Proc.database.set_basic_config(
                    "AmourGame", "dlc2", "0", pkl=False
                )
                plugin_event.reply("全局的电话dlc2已关闭。")


MONITOR_OPENING_BRACKETS = (
    "(",
    "（",
    "[",
    "［",
    "【",
    "{",
    "｛",
    "<",
    "＜",
    "〈",
    "《",
    "「",
    "『",
    "〔",
    "〖",
    "〘",
    "〚",
)

MONITOR_COMMAND_PREFIXES = (
    ".",
    "。",
    "/",
    "#",
    "更改群名",
    "释放本群",
    "删除",
    "拒绝",
    "查询",
    "查看",
    "设置",
    "一键催戏",
    "创建预约",
    "发起",
    "拉取",
    "录入",
    "复盘",
    "撤戏",
    "开启",
    "关闭",
)


def _monitor_record_namespace(playname):
    return "record"


def _monitor_record_filename(playname):
    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", str(playname)).strip(". ")
    return f"{safe_name or '未命名恋综'}.json"


def _monitor_arc_filename(playname):
    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", str(playname)).strip(". ")
    return f"{safe_name or '未命名恋综'}_弧长.json"


def _monitor_parse_arc_setting(value):
    match = re.fullmatch(
        r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\s+(\d+)",
        str(value).strip(),
    )
    if not match:
        return None
    start_hour, start_minute, end_hour, end_minute, minimum_words = map(
        int, match.groups()
    )
    if (
        not 0 <= start_hour <= 23
        or not 0 <= start_minute <= 59
        or not 0 <= end_hour <= 23
        or not 0 <= end_minute <= 59
        or start_hour * 60 + start_minute >= end_hour * 60 + end_minute
        or minimum_words <= 0
    ):
        return None
    time_range = (
        f"{start_hour}:{start_minute:02d}-{end_hour}:{end_minute:02d}"
    )
    return time_range, minimum_words


def _monitor_arc_settings(playname):
    lettertime = getData("groupcollection", "lettertime.json")
    setting = lettertime.get(str(playname), {})
    if not isinstance(setting, dict):
        return "2:00-10:00", 50
    parsed = _monitor_parse_arc_setting(
        f"{setting.get('arc_time', '2:00-10:00')} "
        f"{setting.get('arc_words', 50)}"
    )
    return parsed or ("2:00-10:00", 50)


def _monitor_participants(appointment):
    participants = []
    inviter = appointment.get("inviter")
    if isinstance(inviter, list):
        participants.extend(str(item) for item in inviter if str(item).isdigit())
    elif inviter != "官方" and str(inviter).isdigit():
        participants.append(str(inviter))
    for item in appointment.get("invitee", []):
        item = str(item)
        if item.isdigit() and item not in participants:
            participants.append(item)
    return participants


def _monitor_display_name(privategroup, playname, uid):
    info = privategroup.get(playname, {}).get(str(uid), {})
    return info.get("嘉宾姓名") or info.get("NPC姓名") or str(uid)


def _monitor_visible_text(message):
    return re.sub(r"\[(?:OP|CQ):[^\]]+\]", "", str(message)).strip()


def _monitor_text_length(message):
    visible_text = _monitor_visible_text(message)
    return len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", visible_text))


def _monitor_is_command(message, bot_id):
    text = str(message).strip()
    if not text:
        return True
    if text.startswith(MONITOR_COMMAND_PREFIXES):
        return True
    if re.search(rf"\[(?:OP:at,id|CQ:at,qq)={re.escape(str(bot_id))}\]", text):
        return True
    if re.match(r"^.+?(?:戏录\s+D\d+|弧长)$", text):
        return True
    return False


def _monitor_should_record(message, bot_id):
    text = str(message).strip()
    if not text or text.startswith(MONITOR_OPENING_BRACKETS):
        return False
    if _monitor_is_command(text, bot_id):
        return False
    visible_text = _monitor_visible_text(text)
    if not visible_text:
        return False
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", visible_text):
        return False
    return True


def _monitor_arc_minutes(start_time, end_time, excluded_time="2:00-10:00"):
    """计算弧长，并扣除恋综配置的休息时段。"""
    start_time = int(start_time or 0)
    end_time = int(end_time or 0)
    if not start_time or end_time <= start_time:
        return 0
    parsed = _monitor_parse_arc_setting(f"{excluded_time} 1")
    if not parsed:
        excluded_time = "2:00-10:00"
    start_text, end_text = excluded_time.split("-", 1)
    start_hour, start_minute = map(int, start_text.split(":"))
    end_hour, end_minute = map(int, end_text.split(":"))
    sleeping_seconds = 0
    cursor = start_time
    while cursor < end_time:
        current = time.localtime(cursor)
        sleep_start = int(
            time.mktime(
                (
                    current.tm_year,
                    current.tm_mon,
                    current.tm_mday,
                    start_hour,
                    start_minute,
                    0,
                    0,
                    0,
                    -1,
                )
            )
        )
        sleep_end = int(
            time.mktime(
                (
                    current.tm_year,
                    current.tm_mon,
                    current.tm_mday,
                    end_hour,
                    end_minute,
                    0,
                    0,
                    0,
                    -1,
                )
            )
        )
        if cursor < sleep_start:
            cursor = min(sleep_start, end_time)
        elif cursor < sleep_end:
            segment_end = min(sleep_end, end_time)
            sleeping_seconds += segment_end - cursor
            cursor = segment_end
        else:
            cursor = sleep_start + 24 * 3600
    active_seconds = max(0, end_time - start_time - sleeping_seconds)
    return int(active_seconds / 60)


def _monitor_new_state(code, appointment, now_time=None):
    now_time = int(now_time or time.time())
    participants = _monitor_participants(appointment)
    return {
        "code": str(code),
        "playname": appointment.get("playname", ""),
        "playtype": appointment.get("playtype", ""),
        "playtime": appointment.get("playtime", ""),
        "participants": participants,
        "last_time": 0,
        "last_id": "",
        "last_round_time": 0,
        "last_round_id": "",
        "rounds": {participant: 0 for participant in participants},
        "word_count": {participant: 0 for participant in participants},
        "created_at": now_time,
    }


def _monitor_normalize_state(state, code, appointment):
    if not isinstance(state, dict) or (
        state.get("code") and str(state.get("code")) != str(code)
    ):
        state = _monitor_new_state(code, appointment)
    participants = _monitor_participants(appointment)
    state["code"] = str(code)
    state["playname"] = appointment.get("playname", "")
    state["playtype"] = appointment.get("playtype", "")
    state["playtime"] = appointment.get("playtime", "")
    state["participants"] = participants
    old_rounds = state.get("rounds")
    if not isinstance(old_rounds, dict):
        old_rounds = state.get("par", {})
    state["rounds"] = {
        participant: int(old_rounds.get(participant, 0) or 0)
        for participant in participants
    }
    old_words = state.get("word_count", {})
    if not isinstance(old_words, dict):
        old_words = {}
    state["word_count"] = {
        participant: int(old_words.get(participant, 0) or 0)
        for participant in participants
    }
    state["par"] = dict(state["rounds"])
    state.setdefault("last_time", 0)
    state.setdefault("last_id", "")
    state.setdefault("last_round_time", state.get("last_time", 0))
    state.setdefault("last_round_id", state.get("last_id", ""))
    state.setdefault("created_at", int(time.time()))
    return state


def _monitor_ensure_record_index(code, appointment):
    playname = appointment.get("playname", "")
    namespace = _monitor_record_namespace(playname)
    filename = _monitor_record_filename(playname)
    record_data = getData(namespace, filename)
    appointments = record_data.setdefault("appointments", {})
    current = appointments.get(str(code), {})
    messages = current.get("messages", [])
    current.update(
        {
            "playname": playname,
            "playtype": appointment.get("playtype", ""),
            "playtime": appointment.get("playtime", ""),
            "playplace": appointment.get("playplace", ""),
            "group": str(appointment.get("group", "")),
            "inviter": appointment.get("inviter", ""),
            "invitee": appointment.get("invitee", []),
            "participants": _monitor_participants(appointment),
        }
    )
    current["messages"] = messages if isinstance(messages, list) else []
    current.setdefault("created_at", int(time.time()))
    appointments[str(code)] = current
    setData(namespace, filename, record_data)


def _monitor_manage_permission(plugin_event, playname, uid, groupid, masterlist):
    if str(uid) not in [str(item) for item in masterlist]:
        plugin_event.reply("权限不足，仅骰主可执行该操作。")
        return False
    register = getData("groupcollection", "register.json")
    if playname not in register:
        plugin_event.reply(f"恋综「{playname}」未注册或已注销。")
        return False
    manage_group = str(register[playname].get("manage_group", ""))
    if manage_group and str(groupid) != manage_group:
        plugin_event.reply(f"请在恋综「{playname}」的后台群中执行该操作。")
        return False
    return True


def _monitor_sync_states(playname=None):
    appoint = getData("engagement", "appoint.json")
    msg_appoint = getData("engagement", "msg_appoint.json")
    changed = False
    for code, appointment in appoint.items():
        if playname and appointment.get("playname") != playname:
            continue
        group_id = str(appointment.get("group", ""))
        if not group_id:
            continue
        normalized = _monitor_normalize_state(
            msg_appoint.get(group_id), code, appointment
        )
        if msg_appoint.get(group_id) != normalized:
            msg_appoint[group_id] = normalized
            changed = True
        _monitor_ensure_record_index(code, appointment)
    if changed:
        setData("engagement", "msg_appoint.json", msg_appoint)
    return appoint, msg_appoint


def _monitor_format_duration(seconds):
    seconds = max(0, int(seconds))
    hours, remain = divmod(seconds, 3600)
    minutes = remain // 60
    return f"{hours}小时{minutes}分"


def _monitor_timeline_status(
    playname, groupcodes, appoint, msg_appoint, privategroup, owner_uid
):
    if not groupcodes:
        return "", []
    for code in groupcodes:
        appointment = appoint.get(str(code), appoint.get(code, {}))
        group_id = str(appointment.get("group", ""))
        state = msg_appoint.get(group_id)
        if not isinstance(state, dict):
            continue
        participants = state.get("participants") or _monitor_participants(appointment)
        participants = [str(item) for item in participants]
        rounds = state.get("rounds", state.get("par", {}))
        round_text = "v".join(
            str(int(rounds.get(participant, 0) or 0))
            for participant in participants
        )
        lines = []
        last_id = str(state.get("last_id", ""))
        if last_id:
            waiting_ids = [
                participant
                for participant in participants
                if participant != last_id
            ]
            last_time = int(state.get("last_time", 0) or 0)
            elapsed_seconds = max(0, int(time.time()) - last_time) if last_time else 0
            elapsed = _monitor_format_duration(elapsed_seconds) if last_time else "未知"
            if elapsed_seconds >= 24 * 3600:
                circle = "🔴"
            elif elapsed_seconds >= 12 * 3600:
                circle = "🟠"
            elif elapsed_seconds >= 5 * 3600:
                circle = "🟡"
            else:
                circle = "🟢"
            other_waiting = [
                _monitor_display_name(privategroup, playname, participant)
                for participant in waiting_ids
                if participant != str(owner_uid)
            ]
            if other_waiting:
                lines.append(
                    f"{circle}{'、'.join(other_waiting)} 已 {elapsed} 未回复。"
                )
            if str(owner_uid) in waiting_ids:
                lines.append(f"{circle}💡你已 {elapsed} 未回复。")
        else:
            created_at = int(state.get("created_at", 0) or 0)
            elapsed_seconds = (
                max(0, int(time.time()) - created_at) if created_at else 0
            )
            elapsed = _monitor_format_duration(elapsed_seconds) if created_at else "未知"
            if elapsed_seconds >= 24 * 3600:
                circle = "🔴"
            elif elapsed_seconds >= 12 * 3600:
                circle = "🟠"
            elif elapsed_seconds >= 5 * 3600:
                circle = "🟡"
            else:
                circle = "🟢"
            names = [
                _monitor_display_name(privategroup, playname, participant)
                for participant in participants
            ]
            lines.append(f"{circle}{'、'.join(names)} 已 {elapsed} 未开戏。")
            if str(owner_uid) in participants:
                lines.append(f"💡你已 {elapsed} 未开戏。")
        return round_text, lines
    return "", []


def getMaster(tmp_botHash, platform):
    dictConsoleSwitch = OlivaDiceCore.console.dictConsoleSwitch
    masterlist = []
    if tmp_botHash in dictConsoleSwitch:
        if "masterList" in dictConsoleSwitch[tmp_botHash]:
            for master_this in OlivaDiceCore.console.dictConsoleSwitch[tmp_botHash][
                "masterList"
            ]:
                if master_this[1] == platform:
                    masterlist.append(master_this[0])
    return masterlist


def getData(plugin_name, filename):
    with amourlock:
        path = f"./plugin/data/amourgame/{plugin_name}/"
        if not os.path.exists(path):
            os.makedirs(path)
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            try:
                with open(path + filename + ".bak", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    shutil.copy(path + filename + ".bak", path + filename)
            except:
                with open(path + filename, "w", encoding="utf-8") as f:
                    pass
        with open(path + filename, "r", encoding="utf-8") as f:
            file = str(f.read())
            if len(file) == 0:
                data = {}
            else:
                data = json.loads(file)
            return data


def setData(plugin_name, filename, data):
    with amourlock:
        path = f"./plugin/data/amourgame/{plugin_name}/"
        if not os.path.exists(path):
            os.makedirs(path)
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                check = json.load(f)
                shutil.copy(path + filename, path + filename + ".bak")
        except:
            pass
        with open(path + filename, "w", encoding="utf-8") as w:
            json.dump(data, w, indent=4, ensure_ascii=False)


_IMAGE_CACHE_DIR = "./plugin/data/amourgame/images"
_IMAGE_DOWNLOAD_FAILED = set()


def _strip_file_scheme(value):
    path = value[len("file://") :]
    if re.match(r"^/[A-Za-z]:[\\/]", path):
        path = path[1:]
    return path


def _find_local_image(value):
    """按 OlivOS 工作目录和常见缓存目录补全相对路径；找不到返回 None。"""
    if not value:
        return None
    path = value
    if path.lower().startswith("file://"):
        path = _strip_file_scheme(path)
    if os.path.isabs(path):
        return path if os.path.isfile(path) else None
    bases = (
        os.getcwd(),
        "./data/images",
        "./plugin/tmp",
        "./plugin/data/images",
    )
    for base in bases:
        candidate = os.path.abspath(os.path.join(base, path))
        if os.path.isfile(candidate):
            return candidate
    return None


def _guess_image_ext(blob, content_type):
    content_type = (content_type or "").lower()
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if blob[:3] == b"GIF":
        return ".gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def _download_image_to_cache(url):
    """由插件自己下载远程图片并缓存到本地，返回绝对路径；失败返回 None。

    不把 http(s) 地址直接交给 SnowLuma：它的 HTTP 下载失败（如 400）会让
    整条合并转发报错，而本地缓存文件它可以直接 stat。
    """
    if not url:
        return None
    url = str(url).strip().replace("&amp;", "&")
    if not url.lower().startswith(("http://", "https://")):
        return None
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()
    os.makedirs(_IMAGE_CACHE_DIR, exist_ok=True)
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        cached = os.path.abspath(os.path.join(_IMAGE_CACHE_DIR, digest + ext))
        if os.path.isfile(cached) and os.path.getsize(cached) > 0:
            return cached
    if url in _IMAGE_DOWNLOAD_FAILED:
        return None
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "image/*,*/*;q=0.8",
            },
            timeout=10,
        )
        response.raise_for_status()
        blob = response.content
    except Exception:
        _IMAGE_DOWNLOAD_FAILED.add(url)
        return None
    if not blob:
        _IMAGE_DOWNLOAD_FAILED.add(url)
        return None
    ext = _guess_image_ext(blob, response.headers.get("Content-Type", ""))
    path = os.path.abspath(os.path.join(_IMAGE_CACHE_DIR, digest + ext))
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(blob)
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return path


def _resolve_image_file(value):
    """把 [OP:image,...] / [CQ:image,...] 或裸 file 值归一化成可发送的字符串。

    优先级：base64 → 本机存在的路径（补全为绝对路径）→ 插件下载远程图到本地缓存。
    返回 None 表示这张图无法发送，调用方应跳过，避免整条合并转发失败。
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    if text.startswith("base64://"):
        return text
    if text.startswith(("http://", "https://")):
        return _download_image_to_cache(text)

    file_match = re.search(r"(?:^|,)\s*file=([^,\]]+)", text)
    if file_match:
        file_value = file_match.group(1).strip()
    elif "file=" not in text and not text.startswith("["):
        file_value = text
    else:
        file_value = ""

    url_match = re.search(r"(?:^|,)\s*url=([^,\]]+)", text)
    url_value = url_match.group(1).strip() if url_match else ""

    if file_value.startswith("base64://"):
        return file_value
    if file_value.startswith(("http://", "https://")):
        return _download_image_to_cache(file_value)
    if file_value.lower().startswith("file://"):
        file_value = _strip_file_scheme(file_value)

    local_path = _find_local_image(file_value)
    if local_path:
        return local_path

    if url_value.startswith(("http://", "https://")):
        return _download_image_to_cache(url_value)
    return None


def _image_segment_from_text(segment_text):
    """从图片段文本构造 OneBot image 段；无法解析时返回 None。"""
    file_value = _resolve_image_file(segment_text)
    if not file_value:
        return None
    return {"type": "image", "data": {"file": file_value}}


FORWARD_SPLIT_MAX_SUCCESS = 5


def _send_forward_with_split(bot_port, bot_token, group_id, nodes, state=None):
    """先整条发送；失败就对半拆开重发；最多成功发出 FORWARD_SPLIT_MAX_SUCCESS 条。"""
    if state is None:
        state = {"sent": 0}
    if not nodes:
        return {"retcode": 0}
    if state["sent"] >= FORWARD_SPLIT_MAX_SUCCESS:
        return {
            "retcode": -1,
            "message": (
                f"已成功发送{FORWARD_SPLIT_MAX_SUCCESS}条合并转发，"
                "剩余内容未发送"
            ),
        }
    result = send_forward_message(bot_port, bot_token, group_id, nodes)
    if result.get("retcode") == 0:
        state["sent"] += 1
        return result
    if len(nodes) <= 1:
        return result
    mid = len(nodes) // 2
    first_error = None
    for half in (nodes[:mid], nodes[mid:]):
        if not half:
            continue
        if state["sent"] >= FORWARD_SPLIT_MAX_SUCCESS:
            return {
                "retcode": -1,
                "message": (
                    f"已成功发送{FORWARD_SPLIT_MAX_SUCCESS}条合并转发，"
                    "剩余内容未发送"
                ),
            }
        time.sleep(1)
        half_result = _send_forward_with_split(
            bot_port, bot_token, group_id, half, state
        )
        if half_result.get("retcode") != 0 and first_error is None:
            first_error = half_result
    return first_error or {"retcode": 0}


def send_forward_message(bot_port, bot_token, group_id, nodes_data):
    url = f"http://127.0.0.1:{bot_port}/get_login_info"
    headers = {"Authorization": f"Bearer {bot_token}"}
    try:
        response = requests.request("GET", url, headers=headers, data={}, timeout=5)
        result = response.json()
        if result.get("retcode") == 0 and "data" in result:
            bot_nickname = result["data"].get("nickname", "QQ用户")
        else:
            bot_nickname = "QQ用户"
    except Exception as e:
        bot_nickname = "QQ用户"
    def build_node(node):
        bot_id = node.get("bot_id")
        if not bot_id:
            return None
        nickname = node.get("bot_nickname") or bot_nickname
        content = node.get("content_list")
        if content is None:
            content_text = node.get("content_text")
            content = (
                [{"type": "text", "data": {"text": content_text}}]
                if content_text is not None
                else []
            )
        processed_content = []
        for item in content:
            if isinstance(item, dict) and "bot_id" in item:
                child_node = build_node(item)
                if child_node:
                    processed_content.append(child_node)
            elif isinstance(item, dict) and item.get("type") == "image":
                resolved = _resolve_image_file(
                    (item.get("data") or {}).get("file", "")
                )
                if resolved:
                    processed_content.append(
                        {"type": "image", "data": {"file": resolved}}
                    )
            else:
                processed_content.append(item)
        return {
            "type": "node",
            "data": {
                "uin": int(bot_id),
                "name": nickname,
                "content": processed_content,
            },
        }

    messages = []
    for node in nodes_data:
        built_node = build_node(node)
        if built_node:
            messages.append(built_node)
    payload = {"group_id": int(group_id), "messages": messages}
    url = f"http://127.0.0.1:{bot_port}/send_group_forward_msg"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.request(
            "POST", url, headers=headers, data=json.dumps(payload), timeout=10
        )
        return response.json()
    except Exception as e:
        return {"retcode": -1, "message": f"请求失败: {str(e)}"}


def get_forward_messages(plugin_event, message_id, bot_port, bot_token):
    try:
        get_forward_msg = getattr(plugin_event, "get_forward_msg", None)
        if callable(get_forward_msg):
            forward_data = get_forward_msg(message_id)
            if isinstance(forward_data, dict):
                messages = forward_data.get("messages")
                if messages is None:
                    messages = forward_data.get("data", {}).get("messages")
                if isinstance(messages, list):
                    return messages, None
    except Exception:
        pass

    url = f"http://127.0.0.1:{bot_port}/get_forward_msg"
    payload = json.dumps({"message_id": message_id})
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=10)
        response.raise_for_status()
        response_data = response.json()
    except Exception as e:
        return [], f"获取合并转发消息失败：{str(e)}"
    if response_data.get("retcode") != 0:
        return [], f"获取合并转发消息失败：{response_data.get('message', '未知错误')}"
    messages = response_data.get("data", {}).get("messages", [])
    if not isinstance(messages, list):
        return [], "获取合并转发消息失败！"
    return messages, None


def sendletters(playname):
    global plugin_events_cache
    plugin_event = plugin_events_cache[-1]
    bot_port = plugin_event.bot_info.post_info.port
    bot_token = plugin_event.bot_info.post_info.access_token
    bot_id = str(plugin_event.bot_info.id)
    letters = getData("sendmessage", "letters.json")
    privategroup = getData("groupcollection", "privategroup.json")
    register = getData("groupcollection", "register.json")
    today = datetime.now().strftime("%y%m%d")
    letters_by_receiver = {}
    for key, content in letters.items():
        datalist = key.split("/////")
        if len(datalist) < 5:
            continue
        key_playname = datalist[0]
        key_date = datalist[1]
        sender = datalist[2]
        recver = datalist[3]
        signature = datalist[4]
        if key_playname == playname and key_date == today:
            sender_info = {}
            if playname in privategroup and sender in privategroup[playname]:
                sender_info = privategroup[playname][sender]
            sender_name = (
                sender_info.get("嘉宾姓名") or sender_info.get("NPC姓名") or sender
            )
            if recver not in letters_by_receiver:
                recver_info = {}
                if playname in privategroup and recver in privategroup[playname]:
                    recver_info = privategroup[playname][recver]
                recver_name = (
                    recver_info.get("嘉宾姓名") or recver_info.get("NPC姓名") or recver
                )
                letters_by_receiver[recver] = {
                    "recver_info": recver_info,
                    "recver_name": recver_name,
                    "letters": [],
                }
            segments = []
            segments.append(
                {"type": "text", "data": {"text": f"{playname} 心动信\n"}}
            )
            segments.append(
                {
                    "type": "text",
                    "data": {
                        "text": f"致 {letters_by_receiver[recver]['recver_name']}\n"
                    },
                }
            )
            segments.append({"type": "text", "data": {"text": f"内容：{content}\n"}})
            if "[CQ:image" in signature or "[OP:image" in signature:
                segments.append({"type": "text", "data": {"text": "署名："}})
                text_parts = re.split(r"(\[(?:CQ|OP):image[^\]]+\])", signature)
                for part in text_parts:
                    if part.startswith("[CQ:image") or part.startswith("[OP:image"):
                        image_segment = _image_segment_from_text(part)
                        if image_segment:
                            segments.append(image_segment)
                    elif part:
                        segments.append({"type": "text", "data": {"text": part}})
            else:
                segments.append(
                    {"type": "text", "data": {"text": f"署名：{signature}"}}
                )
            letters_by_receiver[recver]["letters"].append(
                {
                    "sender": sender,
                    "sender_name": sender_name,
                    "segments": segments,
                    "content": content,
                    "signature": signature,
                }
            )
    for recver, data in letters_by_receiver.items():
        recver_info = data["recver_info"]
        recver_name = data["recver_name"]
        letters_list = data["letters"]
        if not letters_list:
            continue
        group_id = recver_info.get("个人群号") or recver_info.get("NPC群号")
        if group_id and len(letters_list) > 1:
            nodes_data = []
            for letter in letters_list:
                nodes_data.append(
                    {
                        "bot_id": bot_id,
                        "content_list": letter["segments"],
                    }
                )
            result = send_forward_message(bot_port, bot_token, group_id, nodes_data)
            if result.get("retcode") == 0:
                pass
            else:
                manage_group = None
                if playname in register and "manage_group" in register[playname]:
                    manage_group = register[playname]["manage_group"]
                for letter in letters_list:
                    message = (
                        f"{playname} 心动信\n"
                        f"致 {recver_name}\n"
                        f"内容：{letter['content']}\n"
                        f"署名：{letter['signature']}"
                    )
                    plugin_event.send("group", group_id, message)
                if manage_group:
                    notification = (
                        f"恋综「{playname}」的嘉宾{recver_name}信件合并转发消息构造失败，"
                        f"已转为普通发送，请检查收信情况与代码异常。"
                    )
                    plugin_event.send("group", manage_group, notification)
        else:
            for letter in letters_list:
                message = (
                    f"{playname} 心动信\n"
                    f"致 {recver_name}\n"
                    f"内容：{letter['content']}\n"
                    f"署名：{letter['signature']}"
                )
                if group_id:
                    plugin_event.send("group", group_id, message)
                else:
                    plugin_event.send("private", recver, message)


def todaycounts():
    global plugin_events_cache
    plugin_event = plugin_events_cache[-1]
    from datetime import datetime, timedelta

    today = datetime.now()
    today_date = today.date()
    today_6 = today.strftime("%y%m%d")
    register = getData("groupcollection", "register.json")
    if not register:
        return
    timeline = getData("engagement", "timeline.json")
    for playname, reg_data in register.items():
        notice_group = reg_data.get("notice_group", "")
        if not notice_group:
            continue
        start_date_str = reg_data.get("start_date", "")
        if not start_date_str:
            continue
        start_date = datetime.strptime(start_date_str, "%Y%m%d").date()
        today_in_schedule = False
        virtual_day = None
        dates_to_count = []
        supplements = reg_data.get("supplements", {})
        end_date_str = reg_data.get("end_date", start_date_str)
        end_date = datetime.strptime(end_date_str, "%Y%m%d").date()
        original_total_days = (end_date - start_date).days + 1
        for v_day in range(original_total_days):
            offset = 0
            for supplement_day_str, supplement_days in supplements.items():
                supplement_day = int(supplement_day_str)
                if supplement_day < v_day:
                    offset += supplement_days
            base_date = start_date + timedelta(days=v_day + offset)
            if str(v_day) in supplements:
                supplement_days = supplements[str(v_day)]
                valid_dates = []
                for i in range(supplement_days + 1):
                    valid_date = base_date + timedelta(days=i)
                    valid_dates.append(valid_date)
                if today_date in valid_dates:
                    today_in_schedule = True
                    virtual_day = v_day
                    dates_to_count = [d.strftime("%y%m%d") for d in valid_dates]
                    break
            else:
                if today_date == base_date:
                    today_in_schedule = True
                    virtual_day = v_day
                    dates_to_count = [today_6]
                    break
        if not today_in_schedule:
            continue
        data_sources = [
            ("心动信", "letters.json"),
            ("小纸条", "notes.json"),
            ("礼物", "gifts.json"),
            ("短信", "sms.json"),
        ]
        counts = {}
        total_count = 0
        for data_type, filename in data_sources:
            try:
                data_list = getData("sendmessage", filename)
                count = 0
                for data in data_list:
                    datalist = data.split("/////")
                    if len(datalist) >= 2:
                        data_playname = datalist[0].strip()
                        data_date = datalist[1].strip()
                        if data_playname == playname and data_date in dates_to_count:
                            count += 1
                counts[data_type] = count
                total_count += count
            except Exception as e:
                counts[data_type] = 0
        timeline_counts = {
            "私约": 0,
            "电话": 0,
            "前置电话": 0,
            "心愿": 0,
            "微信": 0,
        }
        if playname in timeline:
            virtual_day_str = f"D{virtual_day}"
            counted_interactions = set()
            for guest_uid, guest_timeline in timeline[playname].items():
                if virtual_day_str in guest_timeline:
                    day_data = guest_timeline[virtual_day_str]
                    for time_range, details in day_data.items():
                        playtype = details.get("playtype", "")
                        if playtype not in timeline_counts:
                            continue
                        participants = details.get("participants", [])
                        if not participants:
                            continue
                        sorted_participants = sorted([str(p) for p in participants])
                        interaction_key = (
                            f"{','.join(sorted_participants)}|{time_range}|{playtype}"
                        )
                        if interaction_key not in counted_interactions:
                            counted_interactions.add(interaction_key)
                            timeline_counts[playtype] += 1
        timeline_total = sum(timeline_counts.values())
        if total_count == 0 and timeline_total == 0:
            continue
        virtual_day_display = f"D{virtual_day}"
        msg = f"{playname} {virtual_day_display}\n\n"
        for playtype, count in timeline_counts.items():
            if count > 0:
                msg += f"{playtype}：{count}\n"
        for data_type, count in counts.items():
            if count > 0:
                msg += f"{data_type}：{count}\n"
        try:
            plugin_event.send("group", notice_group, msg)
        except Exception as e:
            pass


def clearwish():
    with amourlock:
        path = "./plugin/data/amourgame/wishwall/wish_data.json"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        except:
            pass


def checktime():
    schedule.clear()
    schedule.every().day.at("00:00").do(clearwish)
    schedule.every().day.at("10:00").do(todaycounts)
    schedule.every().day.at("15:00").do(todaycounts)
    schedule.every().day.at("20:00").do(todaycounts)
    schedule.every().day.at("23:59").do(todaycounts)
    lettertime = getData("groupcollection", "lettertime.json")
    for playname, time_data in lettertime.items():
        send_time = time_data.get("time", "22:30")
        schedule.every().day.at(send_time).do(lambda pname=playname: sendletters(pname))
    while True:
        schedule.run_pending()
        time.sleep(1)


def checkgrouptime(time_str, usertime):
    import datetime

    try:
        usertime = [
            (
                datetime.datetime.strptime(i, "%Y-%m-%d %H:%M"),
                datetime.datetime.strptime(x, "%Y-%m-%d %H:%M"),
            )
            for i, x in usertime
        ]
        day, time_range = time_str.split()
        day_num = int(day.replace("D", ""))
        start_time_str, end_time_str = time_range.split("-")
        start_hour, start_minute = map(int, start_time_str.split(":"))
        end_hour, end_minute = map(int, end_time_str.split(":"))
        start_time = datetime.datetime(2025, 1, 1 + day_num, start_hour, start_minute)
        end_time = datetime.datetime(2025, 1, 1 + day_num, end_hour, end_minute)
        if start_time >= end_time:
            return "开始时间不能晚于结束时间噢！"
        for existing_start, existing_end in usertime:
            if start_time.date() == existing_start.date():
                if start_time < existing_end and end_time > existing_start:
                    return "时间冲突啦！"
        usertime.append((start_time, end_time))
        usertime = [
            (i.strftime("%Y-%m-%d %H:%M"), x.strftime("%Y-%m-%d %H:%M"))
            for i, x in usertime
        ]
        return usertime
    except ValueError:
        return "时间错误，请按照如D0 07:30-23:59的格式输入噢！"


def remove_usertime_interval(usertime, playname, user_id, playtime):
    """删除一个标准化占用时段，同时兼容 JSON 读取出的 list 和内存 tuple。"""
    if playname not in usertime or user_id not in usertime[playname]:
        return False
    parsed_time = checkgrouptime(playtime, [])
    if isinstance(parsed_time, str) or not parsed_time:
        return False
    target_interval = tuple(parsed_time[0][:2])
    current_times = usertime[playname].get(user_id, [])
    updated_times = []
    removed = False
    for item in current_times:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            interval = (item[0], item[1])
            if interval == target_interval:
                removed = True
                continue
        updated_times.append(item)
    if not removed:
        return False
    if updated_times:
        usertime[playname][user_id] = updated_times
    else:
        del usertime[playname][user_id]
        if not usertime[playname]:
            del usertime[playname]
    return True


def check_virtual_date(playname, virtual_day_str):
    import datetime

    try:
        register = getData("groupcollection", "register.json")
        if playname not in register:
            return False, "该恋综未注册或已注销，请联系管理噢！"
        reg_info = register[playname]
        start_date_str = reg_info.get("start_date", "20250101")
        start_date = datetime.datetime.strptime(start_date_str, "%Y%m%d").date()
        supplements = reg_info.get("supplements", {})
        if not virtual_day_str.startswith("D"):
            return False, "日期格式错误，请使用D0 07:00-08:30格式。"
        try:
            virtual_day_num = int(virtual_day_str[1:])
        except ValueError:
            return False, "日期格式错误，请使用D0 07:00-08:30的格式。"
        end_date_str = reg_info.get("end_date", "20250101")
        end_date = datetime.datetime.strptime(end_date_str, "%Y%m%d").date()
        total_days = (end_date - start_date).days
        if virtual_day_num > total_days:
            return False, f"日期超出恋综总天数，请使用D0 07:00-08:30的格式。"
        offset = 0
        for supplement_day_str, supplement_days in supplements.items():
            supplement_day = int(supplement_day_str)
            if supplement_day < virtual_day_num:
                offset += supplement_days
        base_date = start_date + datetime.timedelta(days=virtual_day_num + offset)
        today = datetime.date.today()
        if str(virtual_day_num) in supplements:
            supplement_days = supplements[str(virtual_day_num)]
            valid_dates = []
            for i in range(supplement_days + 1):
                valid_date = base_date + datetime.timedelta(days=i)
                valid_dates.append(valid_date)
            if today in valid_dates:
                return True, None
            else:
                if len(valid_dates) == 1:
                    date_str = valid_dates[0].strftime("%Y年%m月%d日")
                    return (
                        False,
                        f"今天不是{virtual_day_str}对应的现实日期{date_str}，无法创建预约。",
                    )
                else:
                    start_str = valid_dates[0].strftime("%Y年%m月%d日")
                    end_str = valid_dates[-1].strftime("%Y年%m月%d日")
                    return (
                        False,
                        f"今天不在{virtual_day_str}对应的现实日期范围{start_str}至{end_str}，无法创建预约。",
                    )
        else:
            if today == base_date:
                return True, None
            else:
                date_str = base_date.strftime("%Y年%m月%d日")
                return (
                    False,
                    f"今天不是{virtual_day_str}对应的现实日期{date_str}，无法创建预约。",
                )
    except Exception as e:
        return False, "获取日程信息时发生错误，请联系管理员。"


def search_netease_music(keywords):
    from urllib.parse import quote

    try:
        encoded_keywords = quote(keywords)
        url = (
            f"https://apis.netstart.cn/music/search?keywords={encoded_keywords}&limit=1"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        if (
            not result
            or "result" not in result
            or "songs" not in result["result"]
            or not result["result"]["songs"]
        ):
            return None
        song_id = result["result"]["songs"][0]["id"]
        return song_id
    except:
        return None
