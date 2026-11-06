import json
import os
import random
import re
import time


def _monitor_core():
    # 延迟导入，避免 main 在加载 engagement 时产生循环导入。
    from AmourGame import main

    return main


def monitor_appointment_message(plugin_event, message, uid, groupid):
    core = _monitor_core()
    if not core._monitor_should_record(message, plugin_event.bot_info.id):
        return False
    appoint = core.getData("engagement", "appoint.json")
    target = next(
        (
            (str(code), info)
            for code, info in appoint.items()
            if str(info.get("group", "")) == str(groupid)
        ),
        None,
    )
    if not target:
        return False
    code, appointment = target
    participants = core._monitor_participants(appointment)
    if str(uid) not in participants:
        return False

    playname = appointment.get("playname", "")
    privategroup = core.getData("groupcollection", "privategroup.json")
    user_name = core._monitor_display_name(privategroup, playname, uid)
    text_length = core._monitor_text_length(message)
    now_time = int(time.time())
    namespace = core._monitor_record_namespace(playname)
    record_filename = core._monitor_record_filename(playname)
    arc_filename = core._monitor_arc_filename(playname)
    excluded_time, minimum_words = core._monitor_arc_settings(playname)

    with core.monitor_lock:
        states = core.getData("engagement", "msg_appoint.json")
        state = core._monitor_normalize_state(states.get(str(groupid)), code, appointment)
        record_data = core.getData(namespace, record_filename)
        appointments = record_data.setdefault("appointments", {})
        record_entry = appointments.setdefault(str(code), {})
        records = record_entry.setdefault("messages", [])
        if not isinstance(records, list):
            records = []
            record_entry["messages"] = records
        message_id = str(
            getattr(plugin_event.data, "message_id", "")
            or f"{now_time}-{uid}-{len(records) + 1}"
        )
        qualifies = text_length >= minimum_words
        previous_uid = str(state.get("last_round_id", ""))
        previous_time = int(state.get("last_round_time", 0) or 0)
        changed_round = qualifies and previous_uid != str(uid)
        arc_minutes = 0
        if qualifies:
            if changed_round:
                state["rounds"][str(uid)] = state["rounds"].get(str(uid), 0) + 1
                if previous_uid and previous_time:
                    arc_minutes = core._monitor_arc_minutes(
                        previous_time, now_time, excluded_time
                    )
            state["last_round_id"] = str(uid)
            state["last_round_time"] = now_time
        state["last_id"] = str(uid)
        state["last_time"] = now_time
        state["word_count"][str(uid)] = state["word_count"].get(str(uid), 0) + text_length
        state["par"] = dict(state["rounds"])
        records.append(
            {
                "message_id": message_id,
                "uid": str(uid),
                "name": user_name,
                "message": str(message),
                "time": now_time,
                "word_count": text_length,
                "round": bool(changed_round),
            }
        )

        stats = core.getData(namespace, arc_filename)
        if appointment.get("playtype") != "微信":
            user_stats = stats.setdefault(
                str(uid),
                {
                    "name": user_name,
                    "total_minutes": 0,
                    "response_count": 0,
                    "rounds": 0,
                    "word_count": 0,
                },
            )
            user_stats["name"] = user_name
            user_stats["word_count"] = (
                int(user_stats.get("word_count", 0)) + text_length
            )
            if changed_round:
                user_stats["rounds"] = int(user_stats.get("rounds", 0)) + 1
                if previous_uid and arc_minutes > 0:
                    user_stats["total_minutes"] = (
                        int(user_stats.get("total_minutes", 0)) + arc_minutes
                    )
                    user_stats["response_count"] = (
                        int(user_stats.get("response_count", 0)) + 1
                    )
            count = int(user_stats.get("response_count", 0))
            user_stats["average_minutes"] = (
                round(int(user_stats.get("total_minutes", 0)) / count, 2) if count else 0
            )

        states[str(groupid)] = state
        appointments[str(code)] = record_entry
        core.setData(namespace, record_filename, record_data)
        core.setData(namespace, arc_filename, stats)
        core.setData("engagement", "msg_appoint.json", states)
        core._monitor_ensure_record_index(code, appointment)
    return True


def handle_recalled_message(plugin_event):
    core = _monitor_core()
    group_id = str(plugin_event.data.group_id)
    message_id = str(plugin_event.data.message_id)
    appoint = core.getData("engagement", "appoint.json")
    target = next(
        (
            (str(code), info)
            for code, info in appoint.items()
            if str(info.get("group", "")) == group_id
        ),
        None,
    )
    if not target:
        return False
    code, appointment = target
    playname = appointment.get("playname", "")
    namespace = core._monitor_record_namespace(playname)
    record_filename = core._monitor_record_filename(playname)
    arc_filename = core._monitor_arc_filename(playname)
    excluded_time, minimum_words = core._monitor_arc_settings(playname)

    with core.monitor_lock:
        record_data = core.getData(namespace, record_filename)
        appointments = record_data.get("appointments", {})
        record_entry = appointments.get(code, {})
        records = record_entry.get("messages", [])
        if not isinstance(records, list) or not records:
            return False

        remove_index = next(
            (
                index
                for index in range(len(records) - 1, -1, -1)
                if str(records[index].get("message_id", "")) == message_id
            ),
            None,
        )
        if remove_index is None:
            try:
                recalled = plugin_event.get_msg(plugin_event.data.message_id)
                raw_message = recalled.get("data", {}).get("raw_message", "").strip()
            except Exception:
                raw_message = ""
            if raw_message:
                remove_index = next(
                    (
                        index
                        for index in range(len(records) - 1, -1, -1)
                        if str(records[index].get("message", "")).strip()
                        == raw_message
                    ),
                    None,
                )
        if remove_index is None:
            return False

        records.pop(remove_index)
        record_entry["messages"] = records
        appointments[code] = record_entry
        record_data["appointments"] = appointments

        privategroup = core.getData("groupcollection", "privategroup.json")
        stats = {}
        for entry in appointments.values():
            entry_messages = entry.get("messages", [])
            if not isinstance(entry_messages, list):
                continue
            if entry.get("playtype") == "微信":
                continue
            previous_uid = ""
            previous_time = 0
            for item in entry_messages:
                item_uid = str(item.get("uid", ""))
                if not item_uid:
                    continue
                word_count = int(
                    item.get("word_count", core._monitor_text_length(item.get("message", "")))
                    or 0
                )
                item["word_count"] = word_count
                user_stats = stats.setdefault(
                    item_uid,
                    {
                        "name": item.get("name")
                        or core._monitor_display_name(
                            privategroup, playname, item_uid
                        ),
                        "total_minutes": 0,
                        "response_count": 0,
                        "rounds": 0,
                        "word_count": 0,
                    },
                )
                user_stats["word_count"] += word_count
                qualifies = word_count >= minimum_words
                changed_round = qualifies and previous_uid != item_uid
                item["round"] = bool(changed_round)
                item_time = int(item.get("time", 0) or 0)
                if changed_round:
                    user_stats["rounds"] += 1
                    if previous_uid and previous_time and item_time:
                        arc_minutes = core._monitor_arc_minutes(
                            previous_time, item_time, excluded_time
                        )
                        if arc_minutes > 0:
                            user_stats["total_minutes"] += arc_minutes
                            user_stats["response_count"] += 1
                if qualifies:
                    previous_uid = item_uid
                    previous_time = item_time
        for user_stats in stats.values():
            response_count = int(user_stats.get("response_count", 0) or 0)
            user_stats["average_minutes"] = (
                round(
                    int(user_stats.get("total_minutes", 0))
                    / response_count,
                    2,
                )
                if response_count
                else 0
            )

        states = core.getData("engagement", "msg_appoint.json")
        old_state = states.get(group_id, {})
        state = core._monitor_normalize_state(old_state, code, appointment)
        participants = core._monitor_participants(appointment)
        state["rounds"] = {participant: 0 for participant in participants}
        state["par"] = dict(state["rounds"])
        state["word_count"] = {participant: 0 for participant in participants}
        state["last_id"] = ""
        state["last_time"] = 0
        state["last_round_id"] = ""
        state["last_round_time"] = 0
        for item in records:
            item_uid = str(item.get("uid", ""))
            if item_uid not in state["word_count"]:
                continue
            word_count = int(item.get("word_count", 0) or 0)
            item_time = int(item.get("time", 0) or 0)
            state["word_count"][item_uid] += word_count
            if word_count >= minimum_words:
                if state["last_round_id"] != item_uid:
                    state["rounds"][item_uid] += 1
                state["last_round_id"] = item_uid
                state["last_round_time"] = item_time
            state["last_id"] = item_uid
            state["last_time"] = item_time
        state["par"] = dict(state["rounds"])
        states[group_id] = state

        core.setData(namespace, record_filename, record_data)
        core.setData(namespace, arc_filename, stats)
        core.setData("engagement", "msg_appoint.json", states)
    return True


def _monitor_query_records(
    plugin_event, playname, day_text, uid, bot_port, bot_token
):
    core = _monitor_core()
    appoint, _ = core._monitor_sync_states(playname)
    namespace = core._monitor_record_namespace(playname)
    for code, appointment in appoint.items():
        if appointment.get("playname") == playname:
            core._monitor_ensure_record_index(code, appointment)
    record_data = core.getData(namespace, core._monitor_record_filename(playname))
    appointments = record_data.get("appointments", {})
    privategroup = core.getData("groupcollection", "privategroup.json")
    outer_nodes = []
    for code, info in appointments.items():
        playtime = str(info.get("playtime", ""))
        if not playtime or playtime.split()[0] != day_text:
            continue
        participants = info.get("participants") or core._monitor_participants(info)
        participants = [str(item) for item in participants]
        if str(uid) not in participants:
            continue
        records = info.get("messages", [])
        if not isinstance(records, list) or not records:
            continue
        names = " × ".join(
            core._monitor_display_name(privategroup, playname, item)
            for item in participants
        )
        inner_nodes = [
            {
                "bot_id": plugin_event.bot_info.id,
                "bot_nickname": f"{playname}戏录",
                "content_text": (
                    f"【{code}｜{info.get('playtype', '')}】\n时间：{playtime}\n"
                    f"地点：{info.get('playplace', '')}\n参与：{names}\n"
                    f"共{len(records)}条戏文"
                ),
            }
        ]
        for item in records:
            content = str(item.get("message", ""))
            item_uid = str(item.get("uid", ""))
            if content:
                inner_nodes.append(
                    {
                        "bot_id": item_uid if item_uid.isdigit() else plugin_event.bot_info.id,
                        "bot_nickname": item.get("name") or item_uid,
                        "content_text": content,
                    }
                )
        outer_nodes.append(
            {
                "bot_id": plugin_event.bot_info.id,
                "bot_nickname": f"{day_text}戏录",
                "content_list": inner_nodes,
            }
        )
    if not outer_nodes:
        plugin_event.reply(f"恋综「{playname}」没有找到你参与的{day_text}戏录。")
        return
    for start in range(0, len(outer_nodes), 40):
        result = core._send_forward_with_split(
            bot_port,
            bot_token,
            plugin_event.data.group_id,
            outer_nodes[start : start + 40],
        )
        if result.get("retcode") != 0:
            plugin_event.reply(f"发送戏录失败：{result.get('message', '未知错误')}")
            return


def _monitor_query_arc(plugin_event, playname, uid):
    core = _monitor_core()
    privategroup = core.getData("groupcollection", "privategroup.json")
    if playname not in privategroup or str(uid) not in privategroup[playname]:
        plugin_event.reply(f"你没有恋综「{playname}」的嘉宾或NPC资料。")
        return
    stats = core.getData(
        core._monitor_record_namespace(playname),
        core._monitor_arc_filename(playname),
    )
    user_stats = stats.get(str(uid), {})
    count = int(user_stats.get("response_count", 0) or 0)
    rounds = int(user_stats.get("rounds", 0) or 0)
    total_words = int(user_stats.get("word_count", 0) or 0)
    if not count and not rounds and not total_words:
        plugin_event.reply(f"恋综「{playname}」暂时没有你的有效弧长记录。")
        return
    average_hours = (
        round(int(user_stats.get("total_minutes", 0) or 0) / count / 60, 1)
        if count
        else 0
    )
    average_words = round(total_words / rounds) if rounds else 0
    plugin_event.reply(
        f"【{playname}】{core._monitor_display_name(privategroup, playname, uid)}\n"
        f"平均弧长：{average_hours}h/{average_words}字\n"
        f"记录回合：{rounds}"
    )


def _monitor_auto_replay(plugin_event, groupid, bot_port, bot_token):
    core = _monitor_core()
    appoint = core.getData("engagement", "appoint.json")
    target = next(
        (
            (str(code), info)
            for code, info in appoint.items()
            if str(info.get("group", "")) == str(groupid)
        ),
        None,
    )
    if not target:
        plugin_event.reply("当前群没有正在进行的小群预约，无法自动复盘。")
        return

    code, appointment = target
    playname = str(appointment.get("playname", "")).strip()
    core._monitor_ensure_record_index(code, appointment)
    namespace = core._monitor_record_namespace(playname)
    record_filename = core._monitor_record_filename(playname)
    record_data = core.getData(namespace, record_filename)
    record_entry = record_data.get("appointments", {}).get(code, {})
    messages = record_entry.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    messages = [item for item in messages if str(item.get("message", "")).strip()]
    if not messages:
        plugin_event.reply(
            "本群自动戏录为空！请确认参与者已发送戏文，或使用合并转发方式复盘。"
        )
        return

    privategroup = core.getData("groupcollection", "privategroup.json")
    playtype = str(appointment.get("playtype", ""))
    playtime = str(appointment.get("playtime", ""))
    playplace = str(appointment.get("playplace", ""))
    inviter = str(appointment.get("inviter", ""))
    invitees = [str(item) for item in appointment.get("invitee", [])]
    if inviter == "官方":
        inviter_name = "官方"
    elif inviter in privategroup.get(playname, {}):
        inviter_info = privategroup[playname][inviter]
        inviter_name = inviter_info.get(
            "嘉宾姓名", inviter_info.get("NPC姓名", inviter)
        )
    else:
        inviter_name = inviter
    invitee_names = []
    for invitee in invitees:
        if invitee in privategroup.get(playname, {}):
            invitee_info = privategroup[playname][invitee]
            invitee_names.append(
                invitee_info.get(
                    "嘉宾姓名", invitee_info.get("NPC姓名", invitee)
                )
            )
    header = (
        f"<{playname}·{playtype}>\n"
        f"邀请者：{inviter_name}\n"
        f"受邀者：{'，'.join(invitee_names)}\n"
        f"时间：{playtime}\n"
        f"地点：{playplace}"
    )
    context = "\n\n".join(str(item.get("message", "")) for item in messages)
    replay_text = f"{header}\n\n{context}"

    day_match = re.match(r"D\d+", playtime)
    if not day_match:
        plugin_event.reply("预约时间缺少D日程，无法生成复盘文件。")
        return
    base_path = f"./plugin/data/amourgame/恋综复盘/{playname}/"
    log_path = os.path.join(base_path, f"{day_match.group()}{playtype}")
    replay_name = f"{playname} {playtime} {playtype} {inviter_name}"
    for invitee_name in invitee_names:
        replay_name += f"x{invitee_name}"
    replay_name = re.sub(r'[<>:"/\\|?*]', "_", replay_name)
    replay_file = os.path.join(log_path, f"{replay_name}.txt")
    with core.amourlock:
        os.makedirs(log_path, exist_ok=True)
        tech_file = os.path.join(
            base_path, "「技术支持」探丸借客@临皋闲人.txt"
        )
        if not os.path.exists(tech_file):
            tech_content = (
                "_      /)---(\\ \n"
                "\\ \\   (/ . . \\)\n"
                " \\ \\__)-\\(*)/\n"
                "  \\_       (_\n"
                "  (___/-(____)\n"
                "\n"
                "「技术支持」探丸借客@临皋闲人\n"
                "\n"
                "OlivaDice By lunzhiPenxil"
            )
            with open(tech_file, "w", encoding="utf-8") as tech:
                tech.write(tech_content)
        with open(replay_file, "w", encoding="utf-8") as replay:
            replay.write(replay_text)

    record_entry["auto_replay_at"] = int(time.time())
    record_entry["auto_replay_file"] = replay_file
    record_data.setdefault("appointments", {})[code] = record_entry
    core.setData(namespace, record_filename, record_data)

    preview_header = {
        "bot_id": plugin_event.bot_info.id,
        "bot_nickname": f"{playname}自动复盘",
        "content_text": f"{header}\n共{len(messages)}条戏文",
    }
    message_nodes = [
        {
            "bot_id": (
                str(item.get("uid"))
                if str(item.get("uid", "")).isdigit()
                else plugin_event.bot_info.id
            ),
            "bot_nickname": item.get("name") or str(item.get("uid", "嘉宾")),
            "content_text": str(item.get("message", "")),
        }
        for item in messages
    ]
    for start in range(0, len(message_nodes), 99):
        result = core._send_forward_with_split(
            bot_port,
            bot_token,
            groupid,
            [preview_header] + message_nodes[start : start + 99],
        )
        if result.get("retcode") != 0:
            plugin_event.reply(
                f"戏录文件已生成，但预览发送失败："
                f"{result.get('message', '未知错误')}"
            )
            return

    plugin_event.set_group_name(groupid, "戏录已上传请退群")
    plugin_event.reply(
        "自动复盘完成，戏录文件已生成，预览如上。\n"
        "如有缺失，可继续使用合并转发方式覆盖此戏录。"
    )


NOTICE_PLAYTYPES = {"私约", "电话", "前置电话", "官约", "微信"}


def _notice_parse_time_range(value):
    match = re.fullmatch(
        r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})",
        str(value).strip(),
    )
    if not match:
        return None
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    if (
        not 0 <= start_hour <= 23
        or not 0 <= start_minute <= 59
        or not 0 <= end_hour <= 24
        or not 0 <= end_minute <= 59
        or (end_hour == 24 and end_minute != 0)
    ):
        return None
    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    return (start, end) if start < end else None


def _notice_setting_items(value):
    return [
        item
        for item in re.split(r"[\s,，、]+", str(value).strip())
        if item
    ]


NOTICE_PROBABILITY_TARGETS = {
    "戏群": "play_group",
    "嘉宾群": "random_guest_group",
    "个人群": "random_guest_group",
    "专属群": "exclusive_group",
}


def _notice_probability_text(config):
    rules = config.get("probability_rules") if isinstance(config, dict) else None
    target_names = {
        "play_group": "戏群",
        "random_guest_group": "嘉宾群",
        "personal_group": "嘉宾群",
        "exclusive_group": "专属群",
    }
    if isinstance(rules, list) and rules:
        return " ".join(
            f"{target_names.get(rule.get('target'), rule.get('target'))}{float(rule.get('probability', 0) or 0):g}"
            for rule in rules
        )
    probability = config.get("probability") if isinstance(config, dict) else None
    return f"{float(probability):g}" if probability is not None else "0-1"


def _notice_parse_probability_rules(value):
    value = str(value or "").strip()
    if re.fullmatch(r"[01](?:\.\d*)?|0?\.\d+", value):
        probability = float(value)
        if not 0 <= probability <= 1:
            return None, "通报概率必须填写0到1之间的数字。"
        return [{"target": "play_group", "probability": probability}], None
    rules = []
    seen_targets = set()
    total_probability = 0.0
    for match in re.finditer(
        r"(戏群|嘉宾群|个人群|专属群)\s*(?:概率)?\s*([01](?:\.\d*)?|0?\.\d+)",
        value,
    ):
        target_label = match.group(1)
        target = NOTICE_PROBABILITY_TARGETS[target_label]
        probability = float(match.group(2))
        if target in seen_targets:
            return None, f"{target_label}重复设置了，请合并成一项。"
        seen_targets.add(target)
        if probability > 0:
            rules.append({"target": target, "probability": probability})
            total_probability += probability
    if not rules:
        return None, "通报概率请填写数字，或按「戏群0.2 嘉宾群0.3 专属群0.1」填写。"
    if total_probability > 1:
        return None, "通报概率总和不能超过1。"
    return rules, None


def _notice_choose_rule(config):
    rules = config.get("probability_rules")
    if not isinstance(rules, list):
        try:
            probability = float(config.get("probability", 0) or 0)
        except (TypeError, ValueError):
            return None
        rules = [{"target": "play_group", "probability": probability}]
    roll = random.random()
    cumulative = 0.0
    for rule in rules:
        probability = float(rule.get("probability", 0) or 0)
        cumulative += probability
        if roll < cumulative:
            return rule
    return None


def _notice_pick_random_guest_group(playname, excluded_uids, privategroup):
    excluded_uids = {str(item) for item in excluded_uids if str(item) != "官方"}
    groups = []
    for guest_uid, info in privategroup.get(playname, {}).items():
        guest_uid = str(guest_uid)
        if not guest_uid.isdigit() or guest_uid in excluded_uids:
            continue
        if not isinstance(info, dict):
            continue
        group_id = info.get("个人群号") or info.get("NPC群号")
        if group_id:
            groups.append(str(group_id))
    return random.choice(groups) if groups else ""


def _notice_pick_exclusive_group(core, playname, participant_uids):
    limit_data = core.getData("sendmessage", "limit.json")
    candidates = []
    for participant_uid in participant_uids:
        group_id = core._drop_pick_exclusive_group(
            limit_data,
            playname,
            str(participant_uid),
        )
        if group_id:
            candidates.append(group_id)
    return random.choice(candidates) if candidates else ""


def _notice_send_by_rule(core, plugin_event, playname, rule, play_group, privategroup, participant_uids, message):
    target = rule.get("target")
    if target == "play_group":
        if not play_group:
            return False, "未设置戏群群号"
        plugin_event.send("group", play_group, message)
        return True, "戏群"
    if target in ("random_guest_group", "personal_group"):
        group_id = _notice_pick_random_guest_group(
            playname,
            participant_uids,
            privategroup,
        )
        if not group_id:
            return False, "未找到可用嘉宾群"
        plugin_event.send("group", group_id, message)
        return True, "嘉宾群"
    if target == "exclusive_group":
        group_id = _notice_pick_exclusive_group(core, playname, participant_uids)
        if not group_id:
            return False, "未找到可用专属群"
        plugin_event.send("group", group_id, message)
        return True, "专属群"
    return False, "未知通报目标"


def _notice_setting_text(playname, config=None):
    config = config if isinstance(config, dict) else {}
    playtypes = config.get("playtypes")
    time_ranges = config.get("time_ranges")
    target = config.get("target")
    return (
        f"通报设置 {playname}\n"
        f"通报类型：{' '.join(playtypes) if isinstance(playtypes, list) else '私约 电话'}\n"
        f"通报时间段：{' '.join(time_ranges) if isinstance(time_ranges, list) else '20:00-23:00'}\n"
        f"通报概率：{_notice_probability_text(config)}\n"
        f"通报对象：{int(target) if target is not None else 1}"
    )


def _handle_notice_setting(plugin_event, text, uid, groupid, masterlist):
    core = _monitor_core()
    first_line = str(text).strip().splitlines()[0].strip()
    match = re.fullmatch(r"通报设置\s+(.+)", first_line)
    if not match:
        return False
    playname = match.group(1).strip()
    if not core._monitor_manage_permission(
        plugin_event, playname, uid, groupid, masterlist
    ):
        return True

    settings = core.getData("engagement", "notice.json")
    lines = str(text).strip().splitlines()
    if len(lines) == 1:
        plugin_event.reply(_notice_setting_text(playname, settings.get(playname)))
        return True

    labels = ("通报类型", "通报时间段", "通报概率", "通报对象")
    values = {}
    for label in labels:
        field_match = re.search(
            rf"(?:^|\n){re.escape(label)}[：:]\s*(.*)",
            str(text),
        )
        if field_match:
            values[label] = field_match.group(1).strip()
    missing = [label for label in labels if not values.get(label)]
    if missing:
        plugin_event.reply(f"以下设置不能为空：{'、'.join(missing)}。")
        return True

    playtypes = _notice_setting_items(values["通报类型"])
    invalid_types = [item for item in playtypes if item not in NOTICE_PLAYTYPES]
    if invalid_types:
        plugin_event.reply(
            f"不支持的通报类型：{'、'.join(invalid_types)}。\n"
            f"可用类型：{'、'.join(sorted(NOTICE_PLAYTYPES))}"
        )
        return True
    time_ranges = _notice_setting_items(values["通报时间段"])
    invalid_ranges = [
        item for item in time_ranges if _notice_parse_time_range(item) is None
    ]
    if invalid_ranges:
        plugin_event.reply(
            f"通报时间段格式错误：{'、'.join(invalid_ranges)}。"
        )
        return True
    probability_rules, probability_error = _notice_parse_probability_rules(
        values["通报概率"]
    )
    if probability_error:
        plugin_event.reply(probability_error)
        return True
    if values["通报对象"] not in {"1", "2", "3", "4", "5"}:
        plugin_event.reply("通报对象只能填写1、2、3、4或5。")
        return True

    settings[playname] = {
        "playtypes": playtypes,
        "time_ranges": time_ranges,
        "probability_rules": probability_rules,
        "probability": probability_rules[0]["probability"]
        if len(probability_rules) == 1 and probability_rules[0]["target"] == "play_group"
        else 0,
        "target": int(values["通报对象"]),
    }
    core.setData("engagement", "notice.json", settings)
    plugin_event.reply(
        f"「{playname}」的通报设置已保存。"
    )
    return True


def _maybe_send_appointment_notice(
    plugin_event,
    playname,
    playtype,
    playtime,
    inviter,
    invitees,
    privategroup,
):
    core = _monitor_core()
    settings = core.getData("engagement", "notice.json")
    config = settings.get(playname)
    if not isinstance(config, dict):
        return
    configured_playtypes = config.get("playtypes", [])
    if not isinstance(configured_playtypes, (list, tuple, set)):
        configured_playtypes = _notice_setting_items(configured_playtypes)
    if playtype not in configured_playtypes:
        return
    playtime_parts = str(playtime).split()
    if len(playtime_parts) < 2:
        return
    appointment_range = _notice_parse_time_range(playtime_parts[1])
    if appointment_range is None:
        return
    configured_time_ranges = config.get("time_ranges", [])
    if not isinstance(configured_time_ranges, (list, tuple, set)):
        configured_time_ranges = _notice_setting_items(
            configured_time_ranges
        )
    configured_ranges = [
        parsed
        for parsed in (
            _notice_parse_time_range(item)
            for item in configured_time_ranges
        )
        if parsed is not None
    ]
    if not any(
        appointment_range[0] < end and appointment_range[1] > start
        for start, end in configured_ranges
    ):
        return
    has_probability = any(
        float(rule.get("probability", 0) or 0) > 0
        for rule in (
            config.get("probability_rules")
            if isinstance(config.get("probability_rules"), list)
            else [{"probability": config.get("probability", 0)}]
        )
    )
    if not has_probability:
        return

    def display_name(target_uid):
        if str(target_uid) == "官方":
            return "官方"
        return core._monitor_display_name(
            privategroup, playname, str(target_uid)
        )

    invitee_names = []
    for target_uid in invitees or []:
        name = display_name(target_uid)
        if name and name not in invitee_names:
            invitee_names.append(name)
    target = int(config.get("target", 1) or 1)
    if target == 1:
        subject = "有人"
    elif target == 2:
        subject = display_name(inviter)
    elif target == 3:
        subject = "、".join(invitee_names)
    elif target == 4:
        all_names = []
        if str(inviter) != "官方":
            all_names.append(display_name(inviter))
        for name in invitee_names:
            if name not in all_names:
                all_names.append(name)
        subject = "、".join(all_names)
    elif target == 5:
        participants_for_roll = []
        participant_uids = set()
        if str(inviter) != "官方":
            inviter_uid = str(inviter)
            participants_for_roll.append(
                (inviter_uid, display_name(inviter_uid), False)
            )
            participant_uids.add(inviter_uid)
        for invitee_uid in invitees or []:
            invitee_uid = str(invitee_uid)
            if invitee_uid in participant_uids:
                continue
            participants_for_roll.append(
                (invitee_uid, display_name(invitee_uid), True)
            )
            participant_uids.add(invitee_uid)
        if not participants_for_roll:
            return
        subject = ""
    else:
        return
    if target != 5 and not subject:
        return
    register = core.getData("groupcollection", "register.json")
    play_group = str(register.get(playname, {}).get("play_group", "")).strip()
    start_time = playtime_parts[1].split("-", 1)[0]
    all_participant_uids = []
    if str(inviter) != "官方":
        all_participant_uids.append(str(inviter))
    for invitee_uid in invitees or []:
        invitee_uid = str(invitee_uid)
        if invitee_uid not in all_participant_uids:
            all_participant_uids.append(invitee_uid)
    if target == 5:
        send_errors = []
        for participant_uid, participant_name, is_invitee in participants_for_roll:
            rule = _notice_choose_rule(config)
            if not rule:
                continue
            try:
                ok, target_label = _notice_send_by_rule(
                    core,
                    plugin_event,
                    playname,
                    rule,
                    play_group,
                    privategroup,
                    all_participant_uids,
                    f"{participant_name}于{start_time}出门啦~",
                )
                if not ok:
                    send_errors.append(f"{participant_name}：{target_label}")
                    continue
                result_text = (
                    f"判定失败，已于{target_label}通报！"
                )
                if is_invitee:
                    participant_info = privategroup.get(playname, {}).get(
                        participant_uid, {}
                    )
                    participant_group = participant_info.get(
                        "个人群号"
                    ) or participant_info.get("NPC群号")
                    if participant_group:
                        plugin_event.send(
                            "group", str(participant_group), result_text
                        )
                    else:
                        plugin_event.reply(
                            f"{participant_name} {result_text}"
                        )
                else:
                    plugin_event.reply(result_text)
            except Exception as error:
                send_errors.append(f"{participant_name}：{error}")
                continue
        if send_errors:
            plugin_event.reply(
                "部分出门通报发送失败：\n" + "\n".join(send_errors)
            )
        return

    rule = _notice_choose_rule(config)
    if not rule:
        return
    try:
        ok, target_label = _notice_send_by_rule(
            core,
            plugin_event,
            playname,
            rule,
            play_group,
            privategroup,
            all_participant_uids,
            f"{subject}于{start_time}出门啦~",
        )
        if not ok:
            plugin_event.reply(
                f"「{playname}」的通报条件已命中，但{target_label}，无法发送出门通报。"
            )
            return
        plugin_event.reply(f"判定失败，已于{target_label}通报！")
    except Exception as error:
        plugin_event.reply(
            f"出门通报发送失败：{error}"
        )
        return


def _monitor_remind(plugin_event, playname):
    core = _monitor_core()
    appoint, states = core._monitor_sync_states(playname)
    config = core.getData("engagement", "api_port.json")
    threshold = float(config.get("催戏", {}).get(playname, 5))
    privategroup = core.getData("groupcollection", "privategroup.json")
    now_time = int(time.time())
    targets = []
    for code, appointment in appoint.items():
        if appointment.get("playname") != playname:
            continue
        if appointment.get("playtype") == "微信":
            continue
        group_id = str(appointment.get("group", ""))
        if not group_id.isdigit():
            continue
        state = states.get(group_id, {})
        base_time = int(state.get("last_time", 0) or state.get("created_at", 0) or now_time)
        elapsed = now_time - base_time
        if elapsed < threshold * 3600:
            continue
        participants = core._monitor_participants(appointment)
        last_id = str(state.get("last_id", ""))
        waiting = [item for item in participants if not last_id or item != last_id]
        if waiting:
            targets.append(
                (code, appointment, group_id, waiting, elapsed, last_id)
            )
    if not targets:
        plugin_event.reply(f"恋综「{playname}」没有超过{threshold:g}小时的待催小群。")
        return
    group_success = group_failed = 0
    personal_targets = {}
    for index, (
        code,
        appointment,
        group_id,
        waiting,
        elapsed,
        last_id,
    ) in enumerate(targets):
        at_text = " ".join(f"[OP:at,id={item}]" for item in waiting)
        try:
            plugin_event.send("group", group_id, at_text)
            group_success += 1
        except Exception:
            group_failed += 1
        for waiting_uid in waiting:
            personal_targets.setdefault(str(waiting_uid), []).append(
                {
                    "playtime": appointment.get("playtime", ""),
                    "playtype": appointment.get("playtype", ""),
                    "elapsed": elapsed,
                    "action": "回戏" if last_id else "开戏",
                    "participants": [
                        participant
                        for participant in core._monitor_participants(
                            appointment
                        )
                        if str(participant) != str(waiting_uid)
                    ],
                }
            )
        if index < len(targets) - 1:
            time.sleep(1)

    personal_success = personal_failed = 0
    personal_items = list(personal_targets.items())
    for index, (waiting_uid, items) in enumerate(personal_items):
        guest_info = privategroup.get(playname, {}).get(waiting_uid, {})
        personal_group = guest_info.get("个人群号") or guest_info.get("NPC群号")
        if not personal_group:
            personal_failed += 1
            continue
        guest_name = core._monitor_display_name(
            privategroup, playname, waiting_uid
        )
        lines = [
            f"【{playname}催戏】",
            f"[OP:at,id={waiting_uid}] {guest_name}，你有{len(items)}个小群"
            f"超过{threshold:g}小时未处理："
        ]
        for item in sorted(items, key=lambda data: data["elapsed"], reverse=True):
            participant_names = [
                core._monitor_display_name(
                    privategroup, playname, participant
                )
                for participant in item.get("participants", [])
            ]
            participant_text = "、".join(participant_names) or ""
            lines.append(
                f"{item['playtime']} {item['playtype']}→{participant_text}\n"
                f"已{core._monitor_format_duration(item['elapsed'])}未{item['action']}"
            )
        try:
            plugin_event.send("group", str(personal_group), "\n\n".join(lines))
            personal_success += 1
        except Exception:
            personal_failed += 1
        if index < len(personal_items) - 1:
            time.sleep(1)

    plugin_event.reply(
        f"恋综「{playname}」一键催戏完成。\n超过{threshold:g}小时："
        f"{len(targets)}个小群\n"
        f"小群发送：成功{group_success}，失败{group_failed}\n"
        f"个人群汇总：成功{personal_success}，失败{personal_failed}"
    )


def handle_monitor_command(
    plugin_event, message, uid, groupid, masterlist, bot_port, bot_token
):
    core = _monitor_core()
    text = str(message).strip()
    if text.startswith("通报设置"):
        if _handle_notice_setting(
            plugin_event, text, uid, groupid, masterlist
        ):
            return True
    match = re.fullmatch(
        r"\[(?:OP:at,id|CQ:at,qq)=(\d+)\]\s*复盘",
        text,
    )
    if match:
        if match.group(1) != str(plugin_event.bot_info.id):
            return False
        _monitor_auto_replay(plugin_event, groupid, bot_port, bot_token)
        return True
    match = re.fullmatch(r"设置催戏\s+(.+?)\s+(\d+(?:\.\d+)?)", text)
    if match:
        playname, hours = match.group(1).strip(), float(match.group(2))
        if not core._monitor_manage_permission(plugin_event, playname, uid, groupid, masterlist):
            return True
        if hours <= 0:
            plugin_event.reply("催戏间隔必须大于0小时。")
            return True
        config = core.getData("engagement", "api_port.json")
        if not isinstance(config.get("催戏"), dict):
            config["催戏"] = {}
        config["催戏"][playname] = hours
        core.setData("engagement", "api_port.json", config)
        plugin_event.reply(f"恋综「{playname}」的催戏间隔已设置为{hours:g}小时。")
        return True
    match = re.fullmatch(r"一键催戏\s+(.+)", text)
    if match:
        playname = match.group(1).strip()
        if not core._monitor_manage_permission(plugin_event, playname, uid, groupid, masterlist):
            return True
        _monitor_remind(plugin_event, playname)
        return True
    match = re.fullmatch(r"(.+?)戏录\s+(D\d+)", text)
    if match:
        playname, day_text = match.group(1).strip(), match.group(2).strip()
        privategroup = core.getData("groupcollection", "privategroup.json")
        if playname not in privategroup:
            return False
        if str(uid) not in privategroup[playname]:
            plugin_event.reply(f"你没有恋综「{playname}」的嘉宾或NPC资料。")
            return True
        _monitor_query_records(
            plugin_event, playname, day_text, uid, bot_port, bot_token
        )
        return True
    match = re.fullmatch(r"(.+?)弧长", text)
    if match:
        playname = match.group(1).strip()
        if playname not in core.getData("groupcollection", "privategroup.json"):
            return False
        _monitor_query_arc(plugin_event, playname, uid)
        return True
    return False


def open_engagement(
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
    system_create=False,
):
    apply = re.match(
        r"<(.+)·\s*(私约|电话|前置电话|官约|微信)>\s+邀请者：(.+)\s+受邀者：(.+)\s+时间：(D\d+\s+\d{2}:\d{2}-\d{2}:\d{2})\s+地点：([\s\S]+)",
        message,
    )
    if not apply:
        apply = re.match(
            r"<(.+)·\s*(官约)>\s+邀请者：\s*受邀者：(.+)\s+时间：(D\d+\s+\d{2}:\d{2}-\d{2}:\d{2})\s+地点：([\s\S]+)",
            message,
        )
        if apply:
            playname = apply.group(1)
            playtype = apply.group(2)
            inviter = ""
            invitee = apply.group(3).strip()
            playtime = apply.group(4)
            playplace = apply.group(5)
        else:
            plugin_event.reply(
                "请复制下面的内容并填写后发送至当前窗口\n\n注意事项：\n① 私约、电话、前置电话、官约、微信五选一，微信不检测时间冲突，前置电话仅同类型不检测时间冲突；\n② 邀请者仅限一人（官约则为空），受邀者可多名，使用中文逗号隔开；\n③ 时间D大写，后附时间采用24小时8位数字制，使用英文冒号；\n④ 24:00写作23:59。\n\n「技术支持」探丸借客@临皋闲人"
            )
            time.sleep(1)
            plugin_event.reply(
                "<恋综名·私约/电话/前置电话/官约/微信>\n邀请者：嘉宾姓名\n受邀者：嘉宾姓名，嘉宾姓名\n时间：D0 07:00-23:59\n地点："
            )
            return
    else:
        playname = apply.group(1)
        playtype = apply.group(2)
        inviter = apply.group(3).strip()
        invitee = apply.group(4).strip()
        playtime = apply.group(5)
        playplace = apply.group(6)
    day_part = playtime.split()[0]
    if playtype not in {"官约", "前置电话"}:
        is_today, error_msg = check_virtual_date(playname, day_part)
        if not is_today:
            plugin_event.reply(error_msg)
            return
    privategroup = getData("groupcollection", "privategroup.json")
    usertime = getData("engagement", "usertime.json")
    if playname not in usertime:
        usertime[playname] = {}
    if playname not in privategroup:
        plugin_event.reply(
            f"恋综「{playname}」未注册或已注销，请检查恋综名或联系骰主噢！"
        )
        return
    try:
        switch_data = getData("engagement", "switch.json")
        notify_invitee = switch_data.get(playname, {}).get("通知受邀者", False)
    except:
        notify_invitee = False

    def get_playtime_tuple(target_playtime):
        return list(checkgrouptime(target_playtime, []))[0]

    def get_time_tuple(day_part, time_range):
        return get_playtime_tuple(f"{day_part} {time_range}")

    def normalize_times(times):
        return [(item[0], item[1]) for item in times if len(item) >= 2]

    def get_type_times(user_id, target_playtype):
        timeline = getData("engagement", "timeline.json")
        type_times = []
        if (
            playname not in timeline
            or user_id not in timeline[playname]
            or day_part not in timeline[playname][user_id]
        ):
            return type_times
        for time_key, slot_info in timeline[playname][user_id][day_part].items():
            if not isinstance(slot_info, dict):
                continue
            if slot_info.get("playtype") != target_playtype:
                continue
            time_range = time_key.split("#", 1)[0]
            type_times.append(get_time_tuple(day_part, time_range))
        return type_times

    def get_conflict_check_times(user_id):
        current_times = normalize_times(usertime[playname].get(user_id, []))
        if playtype != "前置电话":
            return current_times
        same_type_times = get_type_times(user_id, "前置电话")
        return [item for item in current_times if item not in same_type_times]

    def add_usertime(user_id, new_times):
        existing_times = normalize_times(usertime[playname].get(user_id, []))
        playtime_tuple = get_playtime_tuple(playtime)
        if playtime_tuple not in existing_times:
            existing_times.append(playtime_tuple)
        usertime[playname][user_id] = sorted(
            existing_times, key=lambda item: (item[0], item[1])
        )
    dlc1 = Proc.database.get_basic_config(
        "AmourGame", "dlc1", default_value="0", pkl=False
    )
    if invitee == "随机" and playtype == "电话":
        if dlc1 == "0":
            plugin_event.reply("随机通话未开启，请联系骰主开启噢！")
            return
        playername = []
        for uid_key in privategroup[playname]:
            if uid_key.isdigit():
                user_data = privategroup[playname][uid_key]
                if "嘉宾姓名" in user_data and uid_key != uid:
                    playername.append((user_data["嘉宾姓名"], uid_key))
        if len(playername) < 1:
            plugin_event.reply("该恋综人数不足，无法随机噢！")
            return
        timereq = "时间冲突啦！"
        while timereq == "时间冲突啦！":  # 循环条件是当冲突时才继续尝试
            if len(playername) < 1:
                plugin_event.reply("该恋综该时间段无空闲嘉宾，请选择其他时间段噢！")
                return
            invitee_info = random.sample(playername, 1)
            playername.remove(invitee_info[0])
            invitee_uid = invitee_info[0][1]
            if invitee_uid not in usertime[playname]:
                usertime[playname][invitee_uid] = []
            timereq = checkgrouptime(playtime, usertime[playname][invitee_uid])
        if isinstance(timereq, str) and timereq != "时间冲突啦！":
            plugin_event.reply(timereq)
            return
        invitee = invitee_info[0][0]
    official_system_precall = (
        system_create and playtype == "前置电话" and inviter == "官方"
    )
    if playtype != "官约" and not official_system_precall:
        inviter_uid = None
        originname = inviter
        for uid_key in privategroup[playname]:
            if uid_key.isdigit():
                user_data = privategroup[playname][uid_key]
                if (user_data.get("嘉宾姓名") == inviter) or (
                    user_data.get("NPC姓名") == inviter
                ):
                        inviter_uid = uid_key
                        break
        if not inviter_uid:
            plugin_event.reply(
                f"{sender}还未录入个人群，发送「个人群录入 {playname}」获取格式噢！"
            )
            return
        if not system_create:
            if uid != inviter_uid:
                plugin_event.reply(
                    f"「{inviter}」绑定的账号与{sender}的账号不匹配，请使用绑定的账号发送噢！"
                )
                return
            user_groupid = privategroup[playname][inviter_uid].get(
                "个人群号"
            ) or privategroup[playname][inviter_uid].get("NPC群号")
            if user_groupid and groupid != user_groupid:
                plugin_event.reply(f"{inviter}未在个人群创建申请，请前往个人群创建噢！")
                return
        inviter = inviter_uid
    else:
        inviter = "官方"
    skips_time_conflict = playtype == "微信"
    if inviter != "官方" and inviter.isdigit() and not skips_time_conflict:
        if inviter not in usertime[playname]:
            usertime[playname][inviter] = []
        timereq = checkgrouptime(playtime, get_conflict_check_times(inviter))
        if type(timereq) == str:
            if timereq == "时间冲突啦！":
                timereq = (f"{originname}的") + timereq
            plugin_event.reply(timereq)
            return
        add_usertime(inviter, timereq)

    if playtype != "官约":
        limit_data = getData("sendmessage", "limit.json")
        daily_limit = None
        if isinstance(limit_data, dict):
            play_limit = limit_data.get(playname, {})
            if isinstance(play_limit, dict):
                daily_limit = play_limit.get(playtype)
        if daily_limit is not None:
            timeline_data = getData("engagement", "timeline.json")
            appointment_count = 0
            inviter_uid = (
                inviter if inviter != "官方" and inviter.isdigit() else None
            )
            if (
                inviter_uid
                and isinstance(timeline_data, dict)
                and playname in timeline_data
                and inviter_uid in timeline_data[playname]
                and day_part in timeline_data[playname][inviter_uid]
            ):
                for time_slot, slot_data in timeline_data[playname][inviter_uid][
                    day_part
                ].items():
                    if (
                        isinstance(slot_data, dict)
                        and slot_data.get("playtype") == playtype
                    ):
                        appointment_count += 1
            if appointment_count >= daily_limit:
                plugin_event.reply(
                    f"{day_part}你已发起了{appointment_count}/{daily_limit}个{playtype}，无法再创建新的{playtype}啦！"
                )
                return

    invitee_list = invitee.split("，")
    invitee_uids = []
    conflict_invitees = []  # 记录冲突的受邀者
    non_conflict_invitees = []  # 记录不冲突的受邀者
    for i in invitee_list:
        i = i.strip()
        invitee_uid = None
        for uid_key in privategroup[playname]:
            if uid_key.isdigit():
                user_data = privategroup[playname][uid_key]
                if "嘉宾姓名" in user_data and user_data["嘉宾姓名"] == i:
                    invitee_uid = uid_key
                    break
                elif "NPC姓名" in user_data and user_data["NPC姓名"] == i:
                    invitee_uid = uid_key
                    break
        if not invitee_uid:
            plugin_event.reply(f"{i}还未录入个人群噢！")
            return
        if playtype == "微信":
            invitee_uids.append(invitee_uid)
            non_conflict_invitees.append((i, invitee_uid))
            continue
        if invitee_uid not in usertime[playname]:
            usertime[playname][invitee_uid] = []
        timereq = checkgrouptime(playtime, get_conflict_check_times(invitee_uid))
        if type(timereq) == str:
            if timereq == "时间冲突啦！":
                conflict_invitees.append((i, invitee_uid))
                if not notify_invitee:
                    timereq = f"{i}" + "的" + timereq
                    plugin_event.reply(timereq)
                    return
                continue
            else:
                plugin_event.reply(timereq)
                return
        add_usertime(invitee_uid, timereq)
        invitee_uids.append(invitee_uid)
        non_conflict_invitees.append((i, invitee_uid))
    if conflict_invitees and notify_invitee and playtype != "微信":
        inviter_name = (
            "官方"
            if inviter == "官方"
            else privategroup[playname]
            .get(inviter, {})
            .get(
                "嘉宾姓名",
                privategroup[playname].get(inviter, {}).get("NPC姓名", inviter),
            )
        )
        all_invitee_names = []
        for name, uid in non_conflict_invitees + conflict_invitees:
            all_invitee_names.append(name)
        playerstr = "，".join(all_invitee_names)
        for conflict_name, conflict_uid in conflict_invitees:
            conflict_groupid = None
            if conflict_uid in privategroup[playname]:
                user_data = privategroup[playname][conflict_uid]
                conflict_groupid = user_data.get("个人群号") or user_data.get(
                    "NPC群号"
                )
            if conflict_groupid:
                conflict_participants = []
                if conflict_uid in usertime[playname]:
                    timeline = getData("engagement", "timeline.json")
                    if (
                        playname in timeline
                        and conflict_uid in timeline[playname]
                        and day_part in timeline[playname][conflict_uid]
                    ):
                        for time_slot, slot_info in timeline[playname][conflict_uid][
                            day_part
                        ].items():
                            timeline_time_slot = time_slot.split("#", 1)[0]
                            time_start, time_end = timeline_time_slot.split("-")
                            playtime_start, playtime_end = playtime.split()[
                                1
                            ].split("-")
                            if (
                                playtime_start < time_end
                                and playtime_end > time_start
                            ):
                                for participant_uid in slot_info.get(
                                    "participants", []
                                ):
                                    if participant_uid != conflict_uid:
                                        if (
                                            participant_uid
                                            in privategroup[playname]
                                        ):
                                            part_data = privategroup[playname][
                                                participant_uid
                                            ]
                                            part_name = part_data.get(
                                                "嘉宾姓名",
                                                part_data.get(
                                                    "NPC姓名", participant_uid
                                                ),
                                            )
                                            conflict_participants.append(part_name)
                conflict_with = (
                    "、".join(set(conflict_participants))
                    if conflict_participants
                    else "其他安排"
                )
                plugin_event.send(
                    "group",
                    conflict_groupid,
                    f"{conflict_name}收到了{inviter_name}的邀请，但这个时间{conflict_name}和{conflict_with}在一起。\n\n"
                    f"<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{playerstr}\n时间：{playtime}\n地点：{playplace}",
                )
        if non_conflict_invitees:
            conflict_names = [name for name, _ in conflict_invitees]
            conflict_str = "、".join(conflict_names)
            for i, (non_conflict_name, non_conflict_uid) in enumerate(
                non_conflict_invitees
            ):
                non_conflict_groupid = None
                if non_conflict_uid in privategroup[playname]:
                    user_data = privategroup[playname][non_conflict_uid]
                    non_conflict_groupid = user_data.get(
                        "个人群号"
                    ) or user_data.get("NPC群号")
                if non_conflict_groupid:
                    if i > 0:
                        time.sleep(1)
                    plugin_event.send(
                        "group",
                        non_conflict_groupid,
                        f"{non_conflict_name}收到了{inviter_name}的邀请，但{conflict_str}的时间冲突了。\n\n"
                        f"<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{playerstr}\n时间：{playtime}\n地点：{playplace}",
                    )
        conflict_names = [name for name, _ in conflict_invitees]
        conflict_str = "、".join(conflict_names)
        plugin_event.reply(f"{conflict_str}的时间冲突啦！已通知所有的受邀者。")
        return
    if playtype == "微信":
        appoint = getData("engagement", "appoint.json")
        participants_set = set()
        if inviter != "官方":
            participants_set.add(inviter)
        else:
            participants_set.add("官方")
        for uid in invitee_uids:
            participants_set.add(uid)
        for appoint_id, appoint_info in appoint.items():
            if (
                appoint_info["playtype"] == "微信"
                and appoint_info["playname"] == playname
                and appoint_info["playtime"] == playtime
            ):
                existing_participants = set()
                if appoint_info["inviter"] != "官方":
                    existing_participants.add(appoint_info["inviter"])
                else:
                    existing_participants.add("官方")
                for uid in appoint_info["invitee"]:
                    existing_participants.add(uid)
                if participants_set == existing_participants:
                    plugin_event.reply(
                        "同一组人在相同时间已经开过微信了，不能重复创建噢！"
                    )
                    return
    register = getData("groupcollection", "register.json")
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
            group_dict = {}
            try:
                groups = plugin_event.get_group_list()
                for group_item in groups.get("data", []):
                    group_name = group_item.get("name") or group_item.get("group_name")
                    group_id = group_item.get("id") or group_item.get("group_id")
                    if group_name and group_id:
                        group_dict[str(group_name)] = str(group_id)
            except Exception:
                group_dict = {}
            matched_files = [
                item for item in files if os.path.splitext(item)[0] in group_dict
            ]
            random_file = random.choice(matched_files or files)
            original_name = os.path.splitext(random_file)[0]
            mapping_file = os.path.join(group_path, "二维码与群号对应组.json")
            group_id_from_mapping = None
            mapping_data = {}
            if os.path.exists(mapping_file):
                try:
                    with open(mapping_file, "r", encoding="utf-8") as f:
                        mapping_data = json.load(f)
                    if original_name in mapping_data:
                        group_id_from_mapping = str(mapping_data[original_name])
                except Exception as e:
                    mapping_data = {}
            if not group_id_from_mapping and original_name in group_dict:
                group_id_from_mapping = group_dict[original_name]
                mapping_data[original_name] = group_id_from_mapping
                try:
                    with open(mapping_file, "w", encoding="utf-8") as f:
                        json.dump(mapping_data, f, ensure_ascii=False, indent=2)
                except Exception:
                    group_id_from_mapping = None
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
    participants = []
    if inviter != "官方" and inviter.isdigit():
        participants.append(inviter)
    participants.extend(invitee_uids)
    appoint[replaynum] = {
        "playname": playname,
        "playtype": playtype,
        "group": group_info,
        "inviter": inviter,
        "invitee": invitee_uids,
        "playtime": playtime,
        "playplace": playplace,
    }
    setData("engagement", "appoint.json", appoint)
    now_time = int(time.time())
    msg_appoint = getData("engagement", "msg_appoint.json")
    msg_appoint[str(group_info)] = {
        "code": replaynum,
        "playname": playname,
        "playtype": playtype,
        "playtime": playtime,
        "participants": participants,
        "last_time": 0,
        "last_id": "",
        "last_round_time": 0,
        "last_round_id": "",
        "rounds": {participant: 0 for participant in participants},
        "word_count": {participant: 0 for participant in participants},
        "created_at": now_time,
    }
    setData("engagement", "msg_appoint.json", msg_appoint)
    safe_playname = re.sub(r'[<>:"/\\|?*]+', "_", str(playname)).strip(". ") or "未命名恋综"
    record_data = getData("record", f"{safe_playname}.json")
    record_appointments = record_data.setdefault("appointments", {})
    record_appointments[replaynum] = {
        "playname": playname,
        "playtype": playtype,
        "playtime": playtime,
        "playplace": playplace,
        "group": str(group_info),
        "inviter": inviter,
        "invitee": invitee_uids,
        "participants": participants,
        "created_at": now_time,
        "messages": [],
    }
    setData("record", f"{safe_playname}.json", record_data)
    if not skips_time_conflict:
        setData("engagement", "usertime.json", usertime)
    playtime_parts = playtime.split()
    date_part = playtime_parts[0]
    time_range = playtime_parts[1]
    timeline = getData("engagement", "timeline.json")
    if playname not in timeline:
        timeline[playname] = {}
    for participant in participants:
        if participant not in timeline[playname]:
            timeline[playname][participant] = {}
    for participant in participants:
        if date_part not in timeline[playname][participant]:
            timeline[playname][participant][date_part] = {}
        timeline_time_key = (
            f"{time_range}#{replaynum}" if playtype == "前置电话" else time_range
        )
        timeline[playname][participant][date_part][timeline_time_key] = {
            "playtype": playtype,
            "participants": participants,
        }
    if playtype != "微信":
        setData("engagement", "timeline.json", timeline)
    if not system_create:
        if play_method == "二维码":
            if group_id_from_mapping:
                plugin_event.reply(
                    f"预定成功！\n\n{playtype}复盘编号{replaynum}\n\n{group_display}"
                )
            else:
                plugin_event.reply(
                    f"预定成功！\n\n{playtype}复盘编号{replaynum}\n\n进群发送「更改群名{replaynum}」\n\n结戏引用合并转发消息并附文「@骰子 {playtype}{replaynum}」\n{group_display}"
                )
        else:  # 群号
            plugin_event.reply(
                f"预定成功！\n\n{playtype}复盘编号{replaynum}\n\n搜索{group_display}"
            )
    
    inviter_name = (
        "官方"
        if inviter == "官方"
        else privategroup[playname]
        .get(inviter, {})
        .get(
            "嘉宾姓名",
            privategroup[playname].get(inviter, {}).get("NPC姓名", inviter),
        )
    )
    player_names = []
    for uid in invitee_uids:
        if uid in privategroup[playname]:
            user_info = privategroup[playname][uid]
            name = user_info.get("嘉宾姓名", user_info.get("NPC姓名", uid))
            player_names.append(name)
    playerstr = "，".join(player_names)
    for invitee_uid in invitee_uids:
        if invitee_uid not in privategroup[playname]:
            continue
        user_data = privategroup[playname][invitee_uid]
        if "NPC姓名" in user_data:
            tname = user_data.get("NPC姓名", invitee_uid)
            tgroup = user_data.get("NPC群号")
        else:
            tname = user_data.get("嘉宾姓名", invitee_uid)
            tgroup = user_data.get("个人群号")
        if not tgroup:
            continue
        if play_method == "二维码":
            if group_id_from_mapping:
                plugin_event.send(
                    "group",
                    tgroup,
                    f"{tname}收到了一条邀请：\n\n<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{playerstr}\n时间：{playtime}\n地点：{playplace}\n\n拒绝请回复「拒绝{playtype}{replaynum}」\n\n{group_display}",
                )
            else:
                plugin_event.send(
                    "group",
                    tgroup,
                    f"{tname}收到了一条邀请：\n\n<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{playerstr}\n时间：{playtime}\n地点：{playplace}\n\n{playtype}复盘编号{replaynum}\n\n进群发送「更改群名{replaynum}」\n拒绝请回复「拒绝{playtype}{replaynum}」\n\n结戏引用合并转发消息并附文「@骰子 {playtype}{replaynum}」\n{group_display}",
                )
        else:
            plugin_event.send(
                "group",
                tgroup,
                f"{tname}收到了一条邀请：\n\n<{playname}·{playtype}>\n邀请者：{inviter_name}\n受邀者：{playerstr}\n时间：{playtime}\n地点：{playplace}\n\n拒绝请回复「拒绝{playtype}{replaynum}」\n\n搜索{group_display}",
            )
            
    _maybe_send_appointment_notice(
        plugin_event,
        playname,
        playtype,
        playtime,
        inviter,
        invitee_uids,
        privategroup,
    )

    if play_method == "群号":
        time.sleep(1)
        try:
            with amourlock:
                with open(group_file, "r", encoding="utf-8") as f:
                    group_data = json.load(f)
                if new_name in group_data:
                    group_info_dict = group_data[new_name]
                    if (
                        isinstance(group_info_dict, dict)
                        and group_info_dict.get("使用情况") != True
                    ):
                        group_data[new_name]["使用情况"] = True
                        with open(group_file, "w", encoding="utf-8") as f:
                            json.dump(group_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            manage_group = None
            if playname in register and "manage_group" in register[playname]:
                manage_group = register[playname]["manage_group"]
            if manage_group:
                notification = f"恋综「{playname}」的{playtype}小群{replaynum}状态异常，请至{group_file}路径内对应文件中检查小群使用状况，或删除该小群、并通知嘉宾重新开群，或联系临皋闲人报bug。"
                plugin_event.send("group", manage_group, notification)

def phone(
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
):
    privategroup = getData("groupcollection", "privategroup.json")
    register = getData("groupcollection", "register.json")

    def get_phone_data():
        return getData("engagement", "phone.json")

    def set_phone_data(data):
        setData("engagement", "phone.json", data)

    def get_playname(user_id, current_groupid):
        for pname, guests in privategroup.items():
            for guest_uid, guest_info in guests.items():
                if str(guest_uid) != str(user_id):
                    continue
                personal_group = guest_info.get("个人群号")
                npc_group = guest_info.get("NPC群号")
                if str(current_groupid) in (str(personal_group), str(npc_group)):
                    return pname
        return None

    def get_playname_by_groupid(current_groupid):
        for pname, data in register.items():
            if str(current_groupid) in (
                str(data.get("manage_group")),
                str(data.get("notice_group")),
                str(data.get("play_group")),
            ):
                return pname
        return None

    def call_a_phone(plugin_event, privategroup, playname, invitee, playtime, playmsg, playtype="前置电话"):
        names = [item.strip() for item in re.split(r"[\s,，、]+", invitee) if item.strip()]
        if len(names) < 2:
            return
        if playtype == "官约":
            message_text = (
                f"<{playname}·官约>\n"
                f"邀请者：\n"
                f"受邀者：{'，'.join(names)}\n"
                f"时间：{playtime}\n"
                f"地点：{playmsg}"
            )
        else:
            message_text = (
                f"<{playname}·{playtype}>\n"
                f"邀请者：官方\n"
                f"受邀者：{'，'.join(names)}\n"
                f"时间：{playtime}\n"
                f"地点：{playmsg}"
            )
        open_engagement(
            plugin_event,
            Proc,
            message_text,
            uid,
            groupid,
            sender,
            getData,
            setData,
            checkgrouptime,
            check_virtual_date,
            amourlock,
            system_create=True,
        )

    def get_playname_by_manage_group():
        register = getData("groupcollection", "register.json")
        matched = []
        for pname, info in register.items():
            if str(info.get("manage_group", "")) == str(groupid):
                matched.append(pname)
        if not matched:
            return None
        return matched[-1]

    def get_member_name(info):
        return (info.get("嘉宾姓名") or info.get("NPC姓名") or "").strip()

    def parse_gender_template(text):
        m = re.search(r"【嘉宾性别·(.+?)】", text)
        if not m:
            return None, {}
        playname = m.group(1).strip()
        genders = {}
        for line in text[m.end():].splitlines():
            line = line.strip()
            if not line:
                continue
            line_match = re.match(r"(.+?)[:：]\s*(.*)", line)
            if not line_match:
                continue
            name, gender = line_match.groups()
            name = name.strip()
            gender = gender.strip()
            if name and gender:
                genders[name] = gender
        return playname, genders

    if message.startswith("录入嘉宾性别"):
        args = message.split()
        playname = args[1] if len(args) >= 2 else get_playname_by_manage_group()
        if not playname:
            plugin_event.reply("指令格式：录入嘉宾性别 恋综名")
            return
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        register = getData("groupcollection", "register.json")
        manage_group = str(register.get(playname, {}).get("manage_group", ""))
        if uid not in masterlist and str(groupid) != manage_group:
            plugin_event.reply("请在恋综后台群录入嘉宾性别噢！")
            return

        lines = [f"【嘉宾性别·{playname}】"]
        for member_uid, info in privategroup[playname].items():
            if not str(member_uid).isdigit() or not isinstance(info, dict):
                continue
            name = get_member_name(info)
            if not name:
                continue
            current_gender = str(info.get("性别", "")).strip()
            lines.append(f"{name}：{current_gender}")
        plugin_event.reply("\n".join(lines))
        return

    if message.startswith("【嘉宾性别·"):
        playname, gender_map = parse_gender_template(message)
        if not playname:
            plugin_event.reply("格式错误！")
            return
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        register = getData("groupcollection", "register.json")
        manage_group = str(register.get(playname, {}).get("manage_group", ""))
        if uid not in masterlist and str(groupid) != manage_group:
            plugin_event.reply("请在恋综后台群录入嘉宾性别噢！")
            return
        if not gender_map:
            plugin_event.reply("未填写任何性别。")
            return

        name_to_uid = {}
        for member_uid, info in privategroup[playname].items():
            if not str(member_uid).isdigit() or not isinstance(info, dict):
                continue
            name = get_member_name(info)
            if name:
                name_to_uid[name] = member_uid

        updated = []
        not_found = []
        for name, gender in gender_map.items():
            member_uid = name_to_uid.get(name)
            if not member_uid:
                not_found.append(name)
                continue
            privategroup[playname][member_uid]["性别"] = gender
            updated.append(name)
        setData("groupcollection", "privategroup.json", privategroup)
        reply = f"嘉宾性别已保存：{len(updated)}人"
        if not_found:
            reply += "\n\n未找到：" + "、".join(not_found)
        plugin_event.reply(reply)
        return

    # 发起模板：列出成员，返回可复制填写的格式
    if (
        message.startswith("发起前置电话 ")
        or message.strip() == "发起前置电话"
    ):
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：发起前置电话 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return

        data = privategroup.get(playname, {})
        # 生成模板头部
        tpl_lines = []
        tpl_lines.append(f"【前置电话设置·{playname}】")
        tpl_lines.append("限额：")
        tpl_lines.append("时间：D0 10:00-12:00")
        tpl_lines.append("双选时间：D0 10:00-12:00")
        # 列出成员占位
        for qq, info in data.items():
            member_name = get_member_name(info)
            if member_name:
                tpl_lines.append(f"{member_name}：")

        tpl = "\n".join(tpl_lines)
        plugin_event.reply(tpl)
        return

    if message.startswith("【前置电话设置·"):
        m = re.search(r"【前置电话设置·(.+?)】", message)
        if not m:
            return
        playname = m.group(1).strip()
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return

        parsed = parse_precall_template(circled_num_to_int(message))
        if not parsed:
            plugin_event.reply("格式错误！")
            return

        phone_data = get_phone_data()
        phone_data[playname] = parsed
        set_phone_data(phone_data)
        plugin_event.reply("已保存设置。")
        return

    if message.startswith("【前置电话选择】") or message.strip() == "前置电话选择":
        m = re.search(r"【前置电话选择】(.*?)", message)
        if not m:
            plugin_event.reply(f"指令格式：（删除本行）\n【前置电话选择】序号\n\n一次选择所有序号，使用空格或其他标点分隔。多次选择会覆盖之前的内容。")
            return
        groupid = str(plugin_event.data.group_id)
        playname = get_playname(uid, groupid)
        phone_data = get_phone_data()
        limit = int(phone_data[playname]["limit"])
        members = phone_data[playname]["members"]
        valid_symbols = set(members.values())  # 所有人编号的集合，例如 {"④","⑤","⑥"}
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}

        sender = get_member_name(
            privategroup.get(playname, {}).get(uid, {})
        )
        sender_symbol = members.get(sender, "")

        if not sender_symbol:
            plugin_event.reply("未找到你的编号，无法选择前置电话。")
            return

        # ---- 1. 解析用户输入中的所有数字符号（支持空格/逗号/顿号/连续写） ----
        raw = message.replace("【前置电话选择】", "")
        parts = re.split(r"[,\s，、]+", circled_num_to_int(raw))
        parts = [p.strip() for p in parts if p.strip()]

        # ---- 2. 检查每个选择是否存在于 members ----
        chosen = []
        for p in parts:
            if p in valid_symbols:
                chosen.append(p)
                continue
            # 都不是 → 无效输入
            plugin_event.reply(f"无效选择内容：「{p}」，找不到对应成员。")
            return

        if len(chosen) > limit:
            plugin_event.reply(f"你选择了 {len(chosen)} 人，已超过限额 {limit} 人，请重新输入。")
            return

        choices[sender] = chosen
        set_phone_data(phone_data)
        if parts:
            plugin_event.reply("前置电话选择已记录。")
        else:
            plugin_event.reply("你的前置电话选择已清空。")
        return

    if (
        message.startswith("查看前置电话选择 ")
        or message.strip() == "查看前置电话选择"
    ):
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：查看前置电话选择 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return
        lines = []
        lines.append("【前置电话选择总览】")
        phone_data = get_phone_data()
        members = phone_data[playname]["members"]
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}
        call_map_single, call_map_double = build_call_maps(choices, members)

        def three_per_line(items, sep="    "):
            result = []
            for i in range(0, len(items), 3):
                result.append(sep.join(items[i:i + 3]))
            return result

        def align_id(x, width=2):
            s = str(x)
            # 计算显示宽度：中文=2，其他=1
            w = sum(2 if ord(c) > 127 else 1 for c in s)
            if w >= width:
                return s
            return s + " " * (width - w)

        # ---- 1. 显示每位成员的选择 ----
        for name, sym in members.items():
            ch = choices.get(name, [])
            if ch:
                choose_text = "、".join(ch)
                lines.append(f"{name}（{sym}） → {choose_text}")
            else:
                lines.append(f"{name}（{sym}） → 未选择")

        # ---------- 2. 单向选择 ----------
        lines.append(f"\n【单向选择】共 {len(call_map_single)} 条")
        if call_map_single:
            single_lines = []
            for a, b in call_map_single:
                left = align_id(a)
                right = align_id(b)
                single_lines.append(f"{left} → {right}")
            lines.extend(three_per_line(single_lines))
        else:
            lines.append("无")

        # ---------- 3. 双向选择 ----------
        lines.append(f"\n【双向选择】共 {len(call_map_double)} 对")
        if call_map_double:
            double_lines = []
            for a, b in call_map_double:
                left = align_id(a)
                right = align_id(b)
                double_lines.append(f"{left} ↔ {right}")
            lines.extend(three_per_line(double_lines))
        else:
            lines.append("无")

        plugin_event.reply("\n".join(lines))
        return


    if (
        message.startswith("拉取前置电话 ")
        or message.strip() == "拉取前置电话"
    ):
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：拉取前置电话 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return
        phone_data = get_phone_data()
        members = phone_data[playname]["members"]
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}
        call_map_single, call_map_double = build_call_maps(choices, members)
        time_val = phone_data[playname]["time"]
        dual_val = phone_data[playname]["dual_time"]

        symbol_to_name = {v: k for k, v in members.items()}

        # ---------- 双向选择 ----------
        for a, b in call_map_double:
            name_a = symbol_to_name.get(a)
            name_b = symbol_to_name.get(b)
            if not name_a or not name_b:
                continue
            invitee = f"{name_a} {name_b}"
            playtime = dual_val
            playmsg = f"{a} ↔ {b}"
            call_a_phone(plugin_event, privategroup, playname, invitee, playtime, playmsg)
            time.sleep(1)

        # ---------- 单向选择 ----------
        for a, b in call_map_single:
            name_a = symbol_to_name.get(a)
            name_b = symbol_to_name.get(b)
            if not name_a or not name_b:
                continue
            invitee = f"{name_a} {name_b}"
            playtime = time_val
            playmsg = f"{name_a} → {name_b}{b}"
            call_a_phone(plugin_event, privategroup, playname, invitee, playtime, playmsg)
            time.sleep(1)

        plugin_event.reply("已拉取完毕！")
        notification_group = register.get(playname, {}).get("notice_group") or register.get(playname, {}).get("manage_group")
        plugin_event.send("group", notification_group,
            f"前置电话已拉取完毕！\n共开群 {len(call_map_single) + len(call_map_double)} 个，其中双选 {len(call_map_double)} 个。")

    if message.startswith("发起官约 ") or message.strip() == "发起官约":
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：发起官约 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return

        data = privategroup.get(playname, {})
        # 生成模板头部
        tpl_lines = []
        tpl_lines.append(f"【官约设置·{playname}】")
        tpl_lines.append("限额：")
        tpl_lines.append("时间：D1 10:00-12:00")
        tpl_lines.append("双选时间：D1 10:00-12:00")
        # 列出成员占位
        for qq, info in data.items():
            member_name = get_member_name(info)
            if member_name:
                tpl_lines.append(f"{member_name}：")

        tpl = "\n".join(tpl_lines)
        plugin_event.reply(tpl)
        return

    if (
        message.startswith("发起双选官约 ")
        or message.strip() == "发起双选官约"
    ):
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：发起双选官约 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return

        data = privategroup.get(playname, {})
        # 生成模板头部
        tpl_lines = []
        tpl_lines.append(f"【官约设置·{playname}】")
        tpl_lines.append("限额：")
        tpl_lines.append("时间：D4 10:00-12:00")
        tpl_lines.append("双选时间：D4 10:00-12:00")
        # 列出成员占位
        for qq, info in data.items():
            member_name = get_member_name(info)
            if member_name:
                tpl_lines.append(f"{member_name}：{member_name}")

        tpl = "\n".join(tpl_lines)
        plugin_event.reply(tpl)
        return
    
    if message.startswith("【官约设置·"):
        m = re.search(r"【官约设置·(.+?)】", message)
        if not m:
            return
        playname = m.group(1).strip()
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return

        parsed = parse_precall_template(circled_num_to_int(message))
        if not parsed:
            plugin_event.reply("格式错误！")
            return

        phone_data = get_phone_data()
        phone_data[playname] = parsed
        set_phone_data(phone_data)
        plugin_event.reply("已保存设置。")
        return

    if message.startswith("【官约选择】") or message.strip() == "官约选择":
        m = re.search(r"【官约选择】(.*?)", message)
        if not m:
            plugin_event.reply(f"指令格式：（删除本行）\n【官约选择】序号")
            return
        groupid = str(plugin_event.data.group_id)
        playname = get_playname(uid, groupid)
        phone_data = get_phone_data()
        limit = int(phone_data[playname]["limit"])
        members = phone_data[playname]["members"]
        valid_symbols = set(members.values())  # 所有人编号的集合，例如 {"④","⑤","⑥"}
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}

        sender = get_member_name(
            privategroup.get(playname, {}).get(uid, {})
        )
        sender_symbol = members.get(sender, "")

        if not sender_symbol:
            plugin_event.reply("未找到你的编号，无法选择官约。")
            return

        # ---- 1. 解析用户输入中的所有数字符号（支持空格/逗号/顿号/连续写） ----
        raw = message.replace("【官约选择】", "")
        parts = re.split(r"[,\s，、]+", circled_num_to_int(raw))
        parts = [p.strip() for p in parts if p.strip()]

        # ---- 2. 检查每个选择是否存在于 members ----
        chosen = []
        for p in parts:
            if p in valid_symbols:
                chosen.append(p)
                continue
            # 都不是 → 无效输入
            plugin_event.reply(f"无效选择内容：「{p}」，找不到对应成员。")
            return

        if len(chosen) > limit:
            plugin_event.reply(f"你选择了 {len(chosen)} 人，已超过限额 {limit} 人，请重新输入。")
            return

        choices[sender] = chosen
        set_phone_data(phone_data)
        if parts:
            plugin_event.reply("官约选择已记录。")
        else:
            plugin_event.reply("你的官约选择已清空。")
        return

    if (
        message.startswith("查看官约选择 ")
        or message.strip() == "查看官约选择"
    ):
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：查看官约选择 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return
        lines = []
        lines.append("【官约选择总览】")
        phone_data = get_phone_data()
        members = phone_data[playname]["members"]
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}
        call_map_single, call_map_double = build_call_maps(choices, members)

        def three_per_line(items, sep="    "):
            result = []
            for i in range(0, len(items), 3):
                result.append(sep.join(items[i:i + 3]))
            return result

        def align_id(x, width=2):
            s = str(x)
            # 计算显示宽度：中文=2，其他=1
            w = sum(2 if ord(c) > 127 else 1 for c in s)
            if w >= width:
                return s
            return s + " " * (width - w)

        # ---- 1. 显示每位成员的选择 ----
        for name, sym in members.items():
            ch = choices.get(name, [])
            if ch:
                choose_text = "、".join(ch)
                lines.append(f"{name}（{sym}） → {choose_text}")
            else:
                lines.append(f"{name}（{sym}） → 未选择")

        # ---------- 2. 单向选择 ----------
        lines.append(f"\n【单向选择】共 {len(call_map_single)} 条")
        if call_map_single:
            single_lines = []
            for a, b in call_map_single:
                left = align_id(a)
                right = align_id(b)
                single_lines.append(f"{left} → {right}")
            lines.extend(three_per_line(single_lines))
        else:
            lines.append("无")

        # ---------- 3. 双向选择 ----------
        lines.append(f"\n【双向选择】共 {len(call_map_double)} 对")
        if call_map_double:
            double_lines = []
            for a, b in call_map_double:
                left = align_id(a)
                right = align_id(b)
                double_lines.append(f"{left} ↔ {right}")
            lines.extend(three_per_line(double_lines))
        else:
            lines.append("无")

        plugin_event.reply("\n".join(lines))
        return


    if message.startswith("拉取官约 ") or message.strip() == "拉取官约":
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：拉取官约 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return
        phone_data = get_phone_data()
        members = phone_data[playname]["members"]
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}
        call_map_single, call_map_double = build_call_maps(choices, members)
        time_val = phone_data[playname]["time"]
        dual_val = phone_data[playname]["dual_time"]

        symbol_to_name = {v: k for k, v in members.items()}

        # ---------- 双向选择 ----------
        for a, b in call_map_double:
            name_a = symbol_to_name.get(a)
            name_b = symbol_to_name.get(b)
            if not name_a or not name_b:
                continue
            invitee = f"{name_a} {name_b}"
            playtime = dual_val
            playmsg = f"{a} ↔ {b}"
            call_a_phone(plugin_event, privategroup, playname, invitee, playtime, playmsg, "官约")
            time.sleep(1)

        # ---------- 单向选择 ----------
        for a, b in call_map_single:
            name_a = symbol_to_name.get(a)
            name_b = symbol_to_name.get(b)
            if not name_a or not name_b:
                continue
            invitee = f"{name_a} {name_b}"
            playtime = time_val
            playmsg = f"{name_a} → {name_b}{b}"
            call_a_phone(plugin_event, privategroup, playname, invitee, playtime, playmsg, "官约")
            time.sleep(1)

        plugin_event.reply("已拉取完毕！")
        notification_group = register.get(playname, {}).get("notice_group") or register.get(playname, {}).get("manage_group")
        plugin_event.send("group", notification_group,
            f"官约已拉取完毕！\n共开群 {len(call_map_single) + len(call_map_double)} 个，其中双选 {len(call_map_double)} 个。")
        return

    if (
        message.startswith("拉取双选官约 ")
        or message.strip() == "拉取双选官约"
    ):
        args = message.split()
        if len(args) < 2:
            plugin_event.reply("指令格式：拉取双选官约 恋综名")
            return
        playname = args[1]
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return
        phone_data = get_phone_data()
        members = phone_data[playname]["members"]
        choices = phone_data[playname]["choices"]  # 记录每个人已经选过哪些，如 {"赵六": ["③","④"]}
        call_map_single, call_map_double = build_call_maps(choices, members)
        time_val = phone_data[playname]["time"]
        dual_val = phone_data[playname]["dual_time"]

        symbol_to_name = {v: k for k, v in members.items()}

        # ---------- 双向选择 ----------
        for a, b in call_map_double:
            name_a = symbol_to_name.get(a)
            name_b = symbol_to_name.get(b)
            if not name_a or not name_b:
                continue
            invitee = f"{name_a} {name_b}"
            playtime = dual_val
            playmsg = f"{a} ↔ {b}"
            call_a_phone(plugin_event, privategroup, playname, invitee, playtime, playmsg, "官约")
            time.sleep(1)

        plugin_event.reply("已拉取完毕！")
        notification_group = register.get(playname, {}).get("notice_group") or register.get(playname, {}).get("manage_group")
        plugin_event.send("group", notification_group,
            f"双选官约已拉取完毕！共 {len(call_map_double)} 个。")
        return

    if (
        message.startswith("拉取异性随机官约 ")
        or message.strip() == "拉取异性随机官约"
    ):
        args = message.split()
        if len(args) < 3:
            plugin_event.reply("指令格式：拉取异性随机官约 恋综名 D0 19:00-20:00")
            return
        playname = args[1]
        playtime = normalize_playtime(" ".join(args[2:]))
        if not playtime:
            plugin_event.reply("时间格式错误！示例：拉取异性随机官约 恋综名 D0 19:00-20:00")
            return
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return

        gender_groups = {}
        missing_gender = []
        for member_uid, info in privategroup[playname].items():
            if not str(member_uid).isdigit() or not isinstance(info, dict):
                continue
            if "NPC姓名" in info:
                continue
            name = info.get("嘉宾姓名", "").strip()
            if not name:
                continue
            gender = str(info.get("性别", "")).strip()
            if not gender:
                missing_gender.append(name)
                continue
            gender_groups.setdefault(gender, []).append(name)

        active_groups = [names for names in gender_groups.values() if names]
        if len(active_groups) < 2:
            plugin_event.reply("可参与异性随机官约的不同性别嘉宾不足2组。")
            return

        for names in active_groups:
            random.shuffle(names)

        opened = 0
        pairs = []
        while True:
            active_groups = [names for names in active_groups if names]
            if len(active_groups) < 2:
                break
            active_groups.sort(key=len, reverse=True)
            first_group = active_groups[0]
            second_group = random.choice(active_groups[1:])
            name_a = first_group.pop()
            name_b = second_group.pop()
            pairs.append((name_a, name_b))

        for name_a, name_b in pairs:
            invitee = f"{name_a} {name_b}"
            call_a_phone(
                plugin_event,
                privategroup,
                playname,
                invitee,
                playtime,
                "异性随机官约",
                "官约"
            )
            opened += 1
            time.sleep(1)

        msg = f"异性随机官约已拉取完毕！\n时间：{playtime}\n共开群 {opened} 个。"
        if missing_gender:
            msg += f"\n\n未录入性别，已跳过：{'、'.join(missing_gender)}"
        plugin_event.reply(msg)
        notification_group = register.get(playname, {}).get("notice_group") or register.get(playname, {}).get("manage_group")
        if notification_group:
            plugin_event.send("group", notification_group, msg)
        return

    if (
        message.startswith("拉取随机官约 ")
        or message.strip() == "拉取随机官约"
    ):
        args = message.split()
        if len(args) < 3:
            plugin_event.reply("指令格式：拉取随机官约 恋综名 D0 19:00-20:00")
            return

        platform = plugin_event.platform["platform"]
        tmp_botHash = plugin_event.bot_info.hash
        masterlist = getMaster(tmp_botHash, platform)
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return

        groupid = str(plugin_event.data.group_id)
        playname = get_playname(uid, groupid) or get_playname_by_groupid(groupid)
        time_text = " ".join(args[1:])
        if not normalize_playtime(time_text):
            playname = args[1]
            time_text = " ".join(args[2:])

        playtime = normalize_playtime(time_text)
        if not playtime:
            plugin_event.reply("时间格式错误！示例：发起随机官约 D0 19:00-20:00")
            return
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return

        players = [
            (player_uid, info.get("嘉宾姓名", "").strip())
            for player_uid, info in privategroup.get(playname, {}).items()
            if "is_NPC" not in info and info.get("嘉宾姓名", "").strip()
        ]
        if len(players) < 2:
            plugin_event.reply("可参与随机官约的非NPC嘉宾不足2人。")
            return

        random.shuffle(players)
        pairs = [(players[i], players[i + 1]) for i in range(0, len(players) - 1, 2)]
        leftover = players[-1][1] if len(players) % 2 else ""
        opened = 0
        for (uid_a, name_a), (uid_b, name_b) in pairs:
            call_a_phone(
                plugin_event,
                privategroup,
                playname,
                f"{name_a} {name_b}",
                playtime,
                f"随机官约",
                "官约"
            )
            opened += 1
            time.sleep(1)

        msg = f"随机官约已拉取完毕！\n时间：{playtime}\n共开群 {opened} 个。"
        if leftover:
            msg += f"\n轮空：{leftover}"
        plugin_event.reply(msg)

        notification_group = register.get(playname, {}).get("notice_group") or register.get(playname, {}).get("manage_group")
        if notification_group:
            plugin_event.send("group", notification_group, f"随机官约已拉取完毕！\n时间：{playtime}\n共开群 {opened} 个。")
        return


def build_call_maps(choices, members):
    """
    从 choices 推导：
    - call_map_single: [(a, b)]
    - call_map_double: [(a, b)]  # a < b（排序后）
    """

    name_by_symbol = {v: k for k, v in members.items()}

    call_map_single = set()
    call_map_double = set()
    visited_pairs = set()

    for name, selected_symbols in choices.items():
        src_symbol = members.get(name)
        if not src_symbol:
            continue

        for tgt_symbol in selected_symbols:
            if tgt_symbol not in name_by_symbol:
                continue

            tgt_name = name_by_symbol[tgt_symbol]

            # 用无序 key 去重
            pair_key = tuple(sorted([src_symbol, tgt_symbol]))

            # 已处理过
            if pair_key in visited_pairs:
                continue

            # 判断是否双选
            if src_symbol in choices.get(tgt_name, []):
                call_map_double.add(pair_key)
                visited_pairs.add(pair_key)
            else:
                call_map_single.add((src_symbol, tgt_symbol))

    # 清理：单选中剔除已成为双选的
    for a, b in call_map_double:
        call_map_single.discard((a, b))
        call_map_single.discard((b, a))

    return list(call_map_single), list(call_map_double)

def normalize_playtime(playtime):
    if not playtime:
        return ""
    m = re.match(
        r"([Dd]\d+)\s+(\d{1,2})[:：—.](\d{2})[-—~](\d{1,2})[:：—.](\d{2})",
        playtime.strip()
    )
    if not m:
        return None
    day, sh, sm, eh, em = m.groups()
    return f"{day.upper()} {sh.zfill(2)}:{sm}-{eh.zfill(2)}:{em}"

# 辅助解析函数
def parse_precall_template(text):
    # 匹配开头
    m = re.search(r"【(前置电话|官约)设置·(.+?)】", text)
    if not m:
        return None
    # 提取字段
    limit_match = re.search(r"限额：\s*(.*)", text)
    time_match = re.search(r"时间：\s*(.*)", text)
    dual_match = re.search(r"双选时间：\s*(.*)", text)

    limit_raw = limit_match.group(1).strip() if limit_match else ""
    time_raw = time_match.group(1).strip() if time_match else ""
    dual_raw = dual_match.group(1).strip() if dual_match else ""

    # ---- 时间格式正规化 ----
    def normalize_playtime(playtime):
        if not playtime:
            return ""
        m = re.match(
            r"([Dd]\d+)\s+(\d{1,2})[:：∶.](\d{2})[-—](\d{1,2})[:：∶.](\d{2})",
            playtime.strip()
        )
        if m:
            day, sh, sm, eh, em = m.groups()
            day = day.upper()
            return f"{day} {sh.zfill(2)}:{sm}-{eh.zfill(2)}:{em}"
        else:
            return None

    time_val = normalize_playtime(time_raw)
    if time_raw and time_val is None:
        return None

    dual_val = normalize_playtime(dual_raw)
    if dual_raw and dual_val is None:
        return None

    # ---- 成员 ----
    members = {}
    # 找到 “双选” 那行结束的位置
    dual_line = re.search(r"双选时间：.*", text)
    if not dual_line:
        return None
    start_index = dual_line.end()
    member_block = text[start_index:].strip()

    # 分行解析
    for line in member_block.splitlines():
        line = line.strip()
        if not line:
            continue

        m = re.match(r"(.+?)[:：]\s*(.*)", line)
        if not m:
            continue

        name, content = m.groups()
        name = name.strip()
        content = content.strip()
        members[name] = content

    if not members:
        return None

    return {
        "limit": limit_raw,
        "time": time_val,
        "dual_time": dual_val,
        "members": members,
        "choices": {}
    }

def circled_num_to_int(text: str) -> str:
    table = {
        "①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5",
        "⑥": "6", "⑦": "7", "⑧": "8", "⑨": "9", "⑩": "10",
        "⑪": "11", "⑫": "12", "⑬": "13", "⑭": "14", "⑮": "15",
        "⑯": "16", "⑰": "17", "⑱": "18", "⑲": "19", "⑳": "20",
        "⓪": "0"
    }
    for k, v in table.items():
        text = text.replace(k, v)
    return text


