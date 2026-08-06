from .main import setData
from . import engine


GAME_TYPE = "你有我没有"


def start_never_have_i(data, groupid):
    game = engine.ensure_game(data, groupid, GAME_TYPE, phase="ask", turn=1)
    game["reverse_fold"] = True
    game["used_hosts"] = []
    engine.mark_round_start(game)
    seated = engine.active_players(data, groupid)
    next_seat = engine.next_active_seat(data, groupid, 0)
    if not next_seat:
        setData("game.json", data)
        return "还没有玩家入座，不能开始游戏。"
    initial_score = len(seated)
    for player in seated:
        engine.set_score(data, groupid, player.get("uid"), initial_score)
    engine.set_turn(game, next_seat)
    setData("game.json", data)
    player = engine.current_player(data, groupid)
    return (
        "你有我没有游戏已开启！\n"
        f"{engine.at(player.get('uid'))}请直接发送你的题目\n"
        "其他玩家根据情况发送：折 / 不折\n"
        "如需要补折历史回合，请发送：补折 轮数 折/不折"
    )


def handle(plugin_event, data, groupid, uid, message, masterlist=None):
    message = message.strip()
    game = engine.ensure_common_fields(data[groupid].get("game"))

    if message in ["计分", "计分榜"]:
        send_score_with_history(plugin_event, data, groupid)
        return True

    if message.startswith("补折 "):
        handle_makeup_choice(plugin_event, data, groupid, uid, message)
        return True

    if message in ["开启反折", "关闭反折"]:
        if masterlist is not None and uid not in masterlist:
            plugin_event.reply("权限不足！")
            return True
        game["reverse_fold"] = message == "开启反折"
        setData("game.json", data)
        plugin_event.reply("反折已开启。" if game["reverse_fold"] else "反折已关闭。")
        return True

    if message in ["跳过", "下一轮"]:
        finish_round(plugin_event, data, groupid, force=True)
        return True

    if game.get("phase") == "ask":
        if not engine.is_current_player(data, groupid, uid):
            return False
        statement = message.strip()
        if not statement:
            plugin_event.reply("请直接发送你的题目内容。")
            return True
        game["phase"] = "choose"
        game["round"] = {
            "host": str(uid),
            "statement": statement,
            "choices": {}
        }
        game.setdefault("used_hosts", []).append(str(uid))
        setData("game.json", data)
        plugin_event.reply(
            f"{engine.uid_name(data, groupid, uid)} 已出题：{statement}\n"
            "其他玩家请发送：折 / 不折"
        )
        return True

    if game.get("phase") == "choose" and message in ["折", "不折"]:
        round_data = game.get("round", {})
        if str(uid) == str(round_data.get("host")):
            plugin_event.reply("出题人不用选择。")
            return True
        if not engine.player_by_uid(data, groupid, uid):
            return False
        choices = round_data.setdefault("choices", {})
        old_choice = choices.get(str(uid))
        if old_choice == message:
            score = engine.get_score(data, groupid, uid)
        elif old_choice == "折" and message == "不折":
            score = engine.add_score(data, groupid, uid, 1)
        elif old_choice != "折" and message == "折":
            score = engine.add_score(data, groupid, uid, -1)
        else:
            score = engine.get_score(data, groupid, uid)
        choices[str(uid)] = message
        setData("game.json", data)
        plugin_event.reply(f"{engine.uid_name(data, groupid, uid)}{message}，余{score}")
        if is_round_complete(data, groupid):
            finish_round(plugin_event, data, groupid)
        return True
    return False


def is_round_complete(data, groupid):
    game = data[groupid]["game"]
    host = str(game.get("round", {}).get("host", ""))
    choices = game.get("round", {}).get("choices", {})
    need = [
        p.get("uid")
        for p in engine.active_players(data, groupid)
        if str(p.get("uid")) != host
    ]
    return bool(need) and all(str(uid) in choices for uid in need)


def finish_round(plugin_event, data, groupid, force=False):
    game = engine.ensure_common_fields(data[groupid].get("game"))
    if game.get("phase") == "choose":
        choices = game.get("round", {}).get("choices", {})
        host = game.get("round", {}).get("host")
        choice_values = list(choices.values())
        reverse_hit = (
            game.get("reverse_fold")
            and choice_values
            and len(set(choice_values)) == 1
            and is_round_complete(data, groupid)
        )
        if reverse_hit:
            if choice_values[0] == "折":
                for voter_uid in choices:
                    engine.add_score(data, groupid, voter_uid, 1)
            score = engine.add_score(data, groupid, host, -1)
            plugin_event.reply(f"触发反折！{engine.uid_name(data, groupid, host)} -1分，当前{score}分")
        if choices or force:
            plugin_event.reply("本轮结算完毕。")
        record_round_history(data, groupid)
        send_history_forward(plugin_event, data, groupid)

    next_seat = next_unused_host_seat(data, groupid)
    if not next_seat:
        plugin_event.reply("你有我没有本轮已结束！开启新游戏请使用指令：开启游戏 你有我没有 人数")
        engine.mark_game_ended(data, groupid)
        setData("game.json", data)
        send_score_with_history(plugin_event, data, groupid)
        return
    engine.set_turn(game, next_seat)
    game["phase"] = "ask"
    game["round"] = {}
    engine.mark_round_start(game)
    setData("game.json", data)
    player = engine.player_by_seat(data, groupid, next_seat)
    if player:
        plugin_event.reply(f"{engine.at(player.get('uid'))}请直接发送你的题目")


def next_unused_host_seat(data, groupid):
    game = engine.ensure_common_fields(data[groupid].get("game"))
    seats = engine.active_seats(data, groupid)
    used_hosts = set(str(uid) for uid in game.get("used_hosts", []))
    if not seats:
        return None
    start = int(game.get("turn", 1))
    for _ in seats:
        seat = engine.next_active_seat(data, groupid, start)
        player = engine.player_by_seat(data, groupid, seat)
        if str(player.get("uid", "")) not in used_hosts:
            return seat
        start = int(seat)
    return None


def check_timeout(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    if game.get("type") != GAME_TYPE or not engine.is_round_timeout(game):
        return False
    plugin_event.reply(f"本轮已超过{engine.round_timeout_minutes_text(game)}，自动跳过。")
    finish_round(plugin_event, data, groupid, force=True)
    return True


def record_round_history(data, groupid):
    game = engine.ensure_common_fields(data[groupid].get("game"))
    round_data = game.get("round", {})
    if not round_data:
        return
    personal = data[groupid].get("个人", {})
    host = str(round_data.get("host", ""))
    choices = round_data.get("choices", {})
    result = []
    for seat, player in sorted(personal.items(), key=lambda x: int(x[0])):
        uid = str(player.get("uid", ""))
        if not uid:
            continue
        if uid == host:
            choice = "出题"
        else:
            choice = choices.get(uid, "未选择")
        result.append({
            "seat": seat,
            "uid": uid,
            "name": player.get("name", f"{seat}号"),
            "choice": choice,
            "score": engine.get_score(data, groupid, uid)
        })
    game.setdefault("history", []).append({
        "host": host,
        "host_name": engine.uid_name(data, groupid, host),
        "statement": round_data.get("statement", ""),
        "choices": result,
        "reverse_fold": game.get("reverse_fold"),
        "reverse_applied": (
            game.get("reverse_fold")
            and choices
            and len(set(choices.values())) == 1
            and is_round_complete(data, groupid)
        )
    })


def send_history_forward(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    history = game.get("history", [])
    if not history:
        return
    sections = build_history_nodes(plugin_event, history)
    engine.send_forward_text(plugin_event, groupid, 0, sections)


def send_score_with_history(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    sections = [
        engine.build_forward_node(
            " ",
            plugin_event.bot_info.id,
            engine.score_lines(data, groupid, "你有我没有计分：")
        )
    ]
    sections.extend(build_history_nodes(plugin_event, game.get("history", [])))
    engine.send_forward_text(plugin_event, groupid, 0, sections)


def build_history_nodes(plugin_event, history):
    sections = []
    for idx, item in reversed(list(enumerate(history, start=1))):
        lines = [
            f"【第{idx}轮】{item.get('host_name', '')}",
            f" ：{item.get('statement', '')}"
        ]
        for choice in item.get("choices", []):
            score_text = f"，余{choice['score']}" if "score" in choice else ""
            lines.append(f"[{choice['name']}]{choice['choice']}{score_text}")
        sections.append(
            engine.build_forward_node(" ", plugin_event.bot_info.id, "\n".join(lines))
        )
    return sections


def handle_makeup_choice(plugin_event, data, groupid, uid, message):
    parts = message.split()
    if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ["折", "不折"]:
        plugin_event.reply("指令格式：补折 轮数 折/不折")
        return
    round_no = int(parts[1])
    new_choice = parts[2]
    game = engine.ensure_common_fields(data[groupid].get("game"))
    current_round = len(game.get("history", [])) + 1
    if round_no >= current_round:
        plugin_event.reply("补折只能补之前的轮次，当前轮请直接发送：折 / 不折。")
        return
    history = game.get("history", [])
    if round_no < 1 or round_no > len(history):
        plugin_event.reply("没有找到这一轮记录。")
        return
    if not engine.player_by_uid(data, groupid, uid):
        return
    item = history[round_no - 1]
    if str(item.get("host")) == str(uid):
        plugin_event.reply("出题人不能补折本轮。")
        return

    for choice in item.get("choices", []):
        if str(choice.get("uid")) != str(uid):
            continue
        old_choice = choice.get("choice")
        if old_choice != "未选择":
            plugin_event.reply("这一轮你已经操作过，不能事后修改。")
            return
        if new_choice == "折":
            score = engine.add_score(data, groupid, uid, -1)
        else:
            score = engine.get_score(data, groupid, uid)
        choice["choice"] = new_choice
        choice["score"] = score
        reverse_hit = apply_history_reverse_if_needed(data, groupid, item)
        if reverse_hit:
            score = engine.get_score(data, groupid, uid)
        setData("game.json", data)
        plugin_event.reply(f"{engine.uid_name(data, groupid, uid)}补{new_choice}第{round_no}轮，当前{score}分")
        if reverse_hit:
            plugin_event.reply(f"第{round_no}轮触发反折！{item.get('host_name')} -1分")
        send_history_forward(plugin_event, data, groupid)
        return
    plugin_event.reply("这一轮没有你的记录。")


def apply_history_reverse_if_needed(data, groupid, item):
    if item.get("reverse_applied") or not item.get("reverse_fold", True):
        return False
    choices = item.get("choices", [])
    voter_choices = [
        choice
        for choice in choices
        if str(choice.get("uid", "")) != str(item.get("host", ""))
    ]
    values = [choice.get("choice") for choice in voter_choices]
    if not values or "未选择" in values or len(set(values)) != 1:
        return False

    if values[0] == "折":
        for choice in voter_choices:
            score = engine.add_score(data, groupid, choice.get("uid"), 1)
            choice["score"] = score

    host_score = engine.add_score(data, groupid, item.get("host"), -1)
    for choice in choices:
        if str(choice.get("uid", "")) == str(item.get("host", "")):
            choice["score"] = host_score
            break
    item["reverse_applied"] = True
    return True
