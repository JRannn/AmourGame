import random

from .main import getData, setData
from . import engine

GAME_TYPES = ["数字炸弹", "女巫毒药"]

def is_active_player(player):
    return bool(player.get("uid") and player.get("name"))

def keep_auto_skip_config(new_game, old_game):
    if "auto_skip_seconds" in old_game:
        new_game["auto_skip_seconds"] = old_game["auto_skip_seconds"]
    return new_game

def get_next_active_turn(personal, turn):
    max_turn = len(personal)
    if max_turn <= 0:
        return 1
    next_turn = turn
    for _ in range(max_turn):
        next_turn = next_turn + 1 if next_turn < max_turn else 1
        if is_active_player(personal.get(str(next_turn), {})):
            return next_turn
    return next_turn

def get_next_alive_turn(personal, turn, dead):
    max_turn = len(personal)
    dead = set(str(uid) for uid in dead)
    if max_turn <= 0:
        return 1
    next_turn = turn
    for _ in range(max_turn):
        next_turn = next_turn + 1 if next_turn < max_turn else 1
        player = personal.get(str(next_turn), {})
        uid = player.get("uid")
        if is_active_player(player) and str(uid) not in dead:
            return next_turn
    return None

def has_active_player(personal):
    return any(is_active_player(player) for player in personal.values())

def get_number_bomb_start_turn(data, groupid, personal, old_game):
    if "number_bomb_next_turn" in data[groupid]:
        start_turn = data[groupid].pop("number_bomb_next_turn")
    elif old_game.get("type") == "数字炸弹":
        start_turn = old_game.get("turn", 1)
    else:
        start_turn = 1

    try:
        start_turn = int(start_turn)
    except (TypeError, ValueError):
        start_turn = 1

    if not personal.get(str(start_turn), {}).get("uid"):
        start_turn = get_next_active_turn(personal, start_turn - 1)
    return start_turn

def start_number_bomb(data, groupid, low, high):
    # 读取入座顺序
    personal = data[groupid]["个人"]
    if not has_active_player(personal):
        return "还没有玩家入座，不能开始游戏。"

    old_game = data[groupid].get("game", {})
    hit_history = old_game.get("hit_history", []) if old_game.get("type") == "数字炸弹" else []
    start_turn = get_number_bomb_start_turn(data, groupid, personal, old_game)
    first_player = personal.get(str(start_turn), {}).get("uid")

    bomb = random.randint(low + 1, high - 1)

    data[groupid]["game"] = keep_auto_skip_config({
        "type": "数字炸弹",
        "bomb": bomb,
        "low": low,
        "high": high,
        "origin_low": low,
        "origin_high": high,
        "hit_history": hit_history,
        "turn": start_turn
    }, old_game)
    engine.mark_round_start(data[groupid]["game"])

    setData("game.json", data)

    return f"数字炸弹开始！\n[OP:at,id={first_player}]请在{low}~{high}中选择，直接发送你选择的数字即可。"

def handle_private(plugin_event, data, uid, message):
    if not message.startswith("放毒"):
        return False
    play_group = find_play_group(data, uid, "女巫毒药")
    if not play_group:
        if find_play_group(data, uid):
            plugin_event.reply("您当前没有参加女巫毒药游戏！")
        else:
            plugin_event.reply("您尚未参加任何游戏！")
        return True
    game = data[play_group].get("game", {})
    if game.get("type") != "女巫毒药":
        return False
    if set_poison(plugin_event, data, play_group, uid, message):
        data = getData("game.json")
        rep = check_position(data, play_group)
        plugin_event.send("group", play_group, rep)
    return True

def handle(plugin_event, data, groupid, uid, message, masterlist=None):
    message = message.strip()
    gamename = data[groupid].get("gamename")
    game = data[groupid].get("game", {})
    game_type = game.get("type") or gamename

    if message.startswith("开始数字炸弹") or message.startswith("开始女巫毒药"):
        return handle_start_range(plugin_event, data, groupid, message)

    if message == "直接开始游戏":
        if game.get("type") == "女巫毒药":
            plugin_event.reply(start_position(data, groupid))
        elif gamename == "数字炸弹" or game.get("type") == "数字炸弹":
            low = game.get("origin_low", 1) if game.get("type") == "数字炸弹" else 1
            high = game.get("origin_high", 100) if game.get("type") == "数字炸弹" else 100
            plugin_event.reply(start_number_bomb(data, groupid, low, high))
        else:
            plugin_event.reply("当前游戏不能直接开始，请检查游戏状态。")
        return True

    if message == "跳过":
        if game.get("type") == "数字炸弹":
            skip_number_bomb(plugin_event, data, groupid)
            return True
        if game.get("type") == "女巫毒药":
            skip_witch(plugin_event, data, groupid)
            return True
        return False

    if message.isdigit():
        if game.get("type") == "数字炸弹":
            handle_number_bomb(plugin_event, data, groupid, uid, message)
            return True
        if game.get("type") == "女巫毒药":
            handle_witch_poison(plugin_event, data, groupid, uid, message)
            return True
        return False

    if message.startswith("放毒"):
        return handle_group_poison(plugin_event, data, groupid, uid, message)

    return game_type in GAME_TYPES and False

def handle_start_range(plugin_event, data, groupid, message):
    args = message.split()
    cmd = args[0]
    if len(args) != 3:
        plugin_event.reply(f"指令格式：{cmd} 下限 上限")
        return True

    if not (args[1].lstrip('-').isdigit() and args[2].lstrip('-').isdigit()):
        plugin_event.reply("上下限必须是数字！")
        return True

    low = int(args[1])
    high = int(args[2])

    if low >= high:
        plugin_event.reply("下限必须小于上限！")
        return True

    if cmd == "开始数字炸弹":
        if high - low <= 1:
            plugin_event.reply("数字炸弹上下限之间必须至少有一个数字！")
            return True
        plugin_event.reply(start_number_bomb(data, groupid, low, high))
    elif cmd == "开始女巫毒药":
        plugin_event.reply(start_witch_poison(data, groupid, low, high))
    return True

def handle_group_poison(plugin_event, data, groupid, uid, message):
    play_group = find_play_group(data, uid, "女巫毒药")
    if not play_group:
        return False
    game = data[play_group].get("game", {})
    if game.get("type") != "女巫毒药":
        return False
    if set_poison(plugin_event, data, play_group, uid, message):
        data = getData("game.json")
        rep = check_position(data, play_group)
        plugin_event.send("group", play_group, rep)
    return True

def find_play_group(data, uid, game_type=None):
    uid = str(uid)
    for group in data:
        if game_type and data[group].get("game", {}).get("type") != game_type:
            continue
        personal = data[group].get("个人", {})
        for player in personal.values():
            if str(player.get("uid", "")) == uid:
                return group
    return ""

def skip_number_bomb(plugin_event, data, groupid):
    game = data[groupid].get("game")
    turn = game["turn"]
    personal = data[groupid]["个人"]
    current_player = personal[str(turn)]

    game["turn"] = get_next_active_turn(personal, turn)
    engine.mark_round_start(game)

    next_turn = game["turn"]
    next_player = personal.get(str(next_turn), {}).get("uid", "")

    setData("game.json", data)
    name = current_player.get('name', f'{turn}号')
    plugin_event.reply(
        f"{name} 已被跳过！\n"
        f"[OP:at,id={next_player}] 请在{game['low']}~{game['high']}中选择，直接发送你选择的数字即可。"
    )
    return

def handle_number_bomb(plugin_event, data, groupid, uid, message):
    num = int(message)
    game = data[groupid].get("game")
    turn = game["turn"]
    current_player = data[groupid]["个人"][str(turn)]

    # ❗ 检查是不是该玩家
    if str(current_player.get("uid")) != str(uid):
        plugin_event.reply(f"不是你的轮次，请[OP:at,id={current_player.get('uid')}]进行选择！")
        return

    low = game["low"]
    high = game["high"]
    bomb = game["bomb"]

    if not (low < num < high):
        plugin_event.reply(f"请输入 {low}~{high} 之间的数字！")
        return

    # 💥 踩雷
    if num == bomb:
        personal = data[groupid]["个人"]
        next_turn = get_next_active_turn(personal, turn)
        origin_low = game.get("origin_low", low)
        origin_high = game.get("origin_high", high)
        history = game.setdefault("hit_history", [])
        history.append({
            "round": len(history) + 1,
            "uid": str(uid),
            "name": current_player.get("name", f"{turn}号"),
            "seat": turn,
            "bomb": bomb,
            "range": f"{origin_low}~{origin_high}",
        })
        game["low"] = origin_low
        game["high"] = origin_high
        game["bomb"] = random.randint(origin_low + 1, origin_high - 1)
        game["turn"] = next_turn
        engine.mark_round_start(game)
        next_player = personal.get(str(next_turn), {}).get("uid", "")
        setData("game.json", data)
        plugin_event.reply(
            f"{current_player['name']} 踩到了炸弹！\n"
            f"新一轮开始！[OP:at,id={next_player}]请在{origin_low}~{origin_high}中选择，直接发送你选择的数字即可。"
        )
        send_number_bomb_history(plugin_event, game, groupid)
        return

    # 更新范围
    if num < bomb:
        game["low"] = num
    else:
        game["high"] = num

    personal = data[groupid]["个人"]
    game["turn"] = get_next_active_turn(personal, turn)
    engine.mark_round_start(game)
    setData("game.json", data)
    next_player = personal.get(str(game["turn"]), {}).get("uid", "")
    if not next_player:
        skip_number_bomb(plugin_event, data, groupid)
    else:
        plugin_event.reply(f"[OP:at,id={next_player}]请在{game['low']}~{game['high']}中选择，直接发送你选择的数字即可。")
    return


def send_number_bomb_history(plugin_event, game, groupid):
    history = game.get("hit_history", [])
    if not history:
        return
    lines = ["数字炸弹踩中记录"]
    for item in history:
        lines.append(
            f"第{item.get('round')}轮：{item.get('name')}"
            f"（{item.get('seat')}号）踩中 {item.get('bomb')}"
            f"\n范围：{item.get('range')}"
        )
    engine.send_forward_text(
        plugin_event,
        groupid,
        0,
        [engine.build_forward_node(" ", plugin_event.bot_info.id, "\n".join(lines))]
    )


def start_witch_poison(data, groupid, low, high):
    old_game = data[groupid].get("game", {})
    hit_history = old_game.get("hit_history", []) if old_game.get("type") == "女巫毒药" else []
    data[groupid]["game"] = keep_auto_skip_config({
        "type": "女巫毒药",
        "low": low,
        "high": high,
        "turn": 0,
        "poisons": {},   # {数字: 描述}
        "poison_owner": {},
        "dead": [],       # 已出局 uid
        "chosen": [],
        "hit_history": hit_history,
    }, old_game)

    setData("game.json", data)
    if data[groupid]["playname"]:
        return (f"女巫毒药游戏已开启！\n玩家入座后，可以在 {low}~{high} 中放置毒药。\n"
                f"请于个人群发送：放毒 数字 毒药描述或惩罚（描述可不填）")
    else:
        return (f"女巫毒药游戏已开启！\n玩家入座后，可以在 {low}~{high} 中放置毒药。\n"
                f"请在我的小窗发送（如不回复请加好友）：放毒 数字 毒药描述或惩罚（描述可不填）")


# 🧪 放毒
def set_poison(plugin_event, data, groupid, uid, message):
    uid = str(uid)
    game = data[groupid].get("game")
    if not game or game["type"] != "女巫毒药":
        return 0

    content = message.replace("放毒", "", 1).strip()
    parts = content.split()
    if not parts:
        plugin_event.reply("格式：放毒 数字 可选描述")
        return 0
    if game["turn"] != 0:
        plugin_event.reply("游戏已开始，不能放毒！")
        return 0

    if not parts[0].lstrip("-").isdigit():
        plugin_event.reply("毒药数字必须是数字！")
        return 0
    num = int(parts[0])
    desc = " ".join(parts[1:]) if len(parts) > 1 else ""

    low = game["low"]
    high = game["high"]
    poisons = game["poisons"]

    if not low <= num <= high:
        plugin_event.reply(f"毒药数字必须在 {game['low']}~{game['high']} 之间！")
        return 0

    if uid in game.get("poison_owner", {}):
        plugin_event.reply("你已经放过毒了！")
        return 0

    uid = str(uid)

    if uid in game.get("poison_owner", {}):
        plugin_event.reply("你已经放过毒了！")
        return 0

    if str(num) in poisons: # 🔁 顺延找位置
        found = False
        cur = num

        for _ in range(high - low + 1):
            cur += 1
            if cur > high:
                cur = low
            if str(cur) not in poisons:
                num = cur
                found = True
                break

        if not found:
            plugin_event.reply("所有位置都已经被放置毒药了！")
            return 0

    game["poison_owner"][uid] = num
    game["poisons"][str(num)] = desc
    setData("game.json", data)

    plugin_event.reply(f"已成功放置毒药！（如该位置已有毒药会自动顺延）")
    return 1

def check_position(data, groupid):
    game = data[groupid].get("game")
    personal = data[groupid]["个人"]
    poisoned_users = game.get("poison_owner", {})
    seated = [p for p in personal.values() if is_active_player(p)]
    if seated and len(poisoned_users) >= len(seated) and all(str(p.get("uid")) in poisoned_users for p in seated):
        game["turn"] = get_next_alive_turn(personal, 0, game.get("dead", []))
        engine.mark_round_start(game)
        setData("game.json", data)
        first_player = personal[str(game["turn"])]["uid"]
        return f"所有人已放毒完毕！[OP:at,id={first_player}]请在{game['low']}~{game['high']}中选择，直接发送你选择的数字即可。"
    return f"已放毒（{len(poisoned_users)}/{len(seated)}）"

def start_position(data, groupid):
    game = data[groupid].get("game")
    personal = data[groupid]["个人"]
    game["turn"] = get_next_alive_turn(personal, 0, game.get("dead", []))
    engine.mark_round_start(game)
    setData("game.json", data)
    if not game["turn"]:
        return "没有可进行游戏的玩家。"
    first_player = personal[str(game["turn"])]["uid"]
    return f"游戏开始！[OP:at,id={first_player}]请在{game['low']}~{game['high']}中选择，直接发送你选择的数字即可。"

# ⏭️ 跳过（复用逻辑）
def skip_witch(plugin_event, data, groupid, con = 0):
    game = data[groupid].get("game")
    turn = game["turn"]
    personal = data[groupid]["个人"]
    current_player = personal[str(turn)]

    if not con:
        game["turn"] = get_next_alive_turn(personal, turn, game.get("dead", []))
        engine.mark_round_start(game)
        name = current_player.get('name', f'{turn}号')
        plugin_event.reply(f"{name} 已被跳过！")

    next_turn = game["turn"]
    if not next_turn:
        plugin_event.reply("没有可继续游戏的玩家。")
        del data[groupid]["game"]
        setData("game.json", data)
        return
    next_player = personal[str(next_turn)].get("uid", "")
    setData("game.json", data)

    if not next_player or str(next_player) in set(str(uid) for uid in game.get("dead", [])):
        skip_witch(plugin_event, data, groupid)
    else:
        low = game["low"]
        high = game["high"]
        chosen = set(game.get("chosen", []))
        available = [i for i in range(low, high + 1) if i not in chosen]

        # 转字符串
        chosen_str = "、".join(map(str, sorted(chosen)))
        available_str = "、".join(map(str, available))

        # 谁更少显示谁
        if len(chosen) <= len(available):
            show_text = f"已选：{chosen_str}" if chosen else ""
        else:
            show_text = f"剩余：{available_str}"

        plugin_event.reply(
            f"[OP:at,id={next_player}]请选择一个数字（{low}~{high}）\n{show_text}".strip()
        )
    return


# 🎯 选择数字
def handle_witch_poison(plugin_event, data, groupid, uid, message):
    game = data[groupid].get("game")
    if not game or game["type"] != "女巫毒药":
        return

    personal = data[groupid]["个人"]
    turn = game["turn"]
    current = personal[str(turn)]
    dead = set(str(uid) for uid in game.get("dead", []))

    if str(uid) in dead:
        plugin_event.reply("你已出局，不能再选择。")
        return

    if not current.get("uid") or str(current.get("uid")) in dead:
        next_turn = get_next_alive_turn(personal, turn, dead)
        if not next_turn:
            plugin_event.reply("没有可继续游戏的玩家。")
            del data[groupid]["game"]
            setData("game.json", data)
            return
        game["turn"] = next_turn
        setData("game.json", data)
        turn = next_turn
        current = personal[str(turn)]

    # ❗ 检查轮次
    if str(current.get("uid")) != str(uid):
        plugin_event.reply(f"不是你的回合！请等待 [OP:at,id={current.get('uid')}]")
        return

    num = int(message)

    if not (game["low"] <= num <= game["high"]):
        plugin_event.reply(f"请输入 {game['low']}~{game['high']} 之间的数字！")
        return
    if num in game.get("chosen", []):
        plugin_event.reply(f"该序号已选过，不可选择！")
        return
    name = current.get("name", f"{turn}号")

    # 💀 踩毒
    if str(num) in game["poisons"]:
        desc = game["poisons"].pop(str(num))
        game["dead"].append(uid)
        history = game.setdefault("hit_history", [])
        history.append({
            "round": len(history) + 1,
            "uid": str(uid),
            "name": name,
            "seat": turn,
            "poison": num,
            "range": f"{game['low']}~{game['high']}",
            "desc": desc,
        })

        msg = f"{name} 选到了毒药！已出局！"
        if desc:
            msg += f"\n毒药：{desc}"

        plugin_event.reply(msg)
        send_witch_poison_history(plugin_event, game, groupid)

        # 🏁 结束判断
        alive = [
            p for p in personal.values()
            if p.get("uid") and p.get("uid") not in game["dead"]
        ]

        if len(alive) <= 1 or len(game["poisons"]) == 0:
            winner = alive[0]["name"] if alive else "无人"
            plugin_event.reply(f"游戏结束！幸存者：{winner}")
            del data[groupid]["game"]
            setData("game.json", data)
            return

    game.setdefault("chosen", []).append(num)
    game["turn"] = get_next_alive_turn(personal, turn, game.get("dead", []))
    engine.mark_round_start(game)
    setData("game.json", data)
    if not game["turn"]:
        plugin_event.reply("没有可继续游戏的玩家。")
        del data[groupid]["game"]
        setData("game.json", data)
        return
    next_player = data[groupid]["个人"][str(game["turn"])].get("uid", "")
    if not next_player:
        skip_witch(plugin_event, data, groupid)
    else:
        skip_witch(plugin_event, data, groupid, con = 1)
    return


def check_timeout(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    if game.get("type") not in GAME_TYPES or not engine.is_round_timeout(game):
        return False
    plugin_event.reply(f"本轮已超过{engine.round_timeout_minutes_text(game)}，自动跳过。")
    if game.get("type") == "数字炸弹":
        skip_number_bomb(plugin_event, data, groupid)
        return True
    if game.get("type") == "女巫毒药" and game.get("turn"):
        skip_witch(plugin_event, data, groupid)
        return True
    return False


def send_witch_poison_history(plugin_event, game, groupid):
    history = game.get("hit_history", [])
    if not history:
        return
    lines = ["女巫毒药踩中记录"]
    for item in history:
        text = (
            f"第{item.get('round')}轮：{item.get('name')}"
            f"（{item.get('seat')}号）选中 {item.get('poison')}"
        )
        if item.get("desc"):
            text += f"\n毒药：{item.get('desc')}"
        lines.append(text)
    engine.send_forward_text(
        plugin_event,
        groupid,
        0,
        [engine.build_forward_node(" ", plugin_event.bot_info.id, "\n\n".join(lines))]
    )
