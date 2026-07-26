import time

from .main import setData
from . import engine
GAME_TYPE = "偏执狂"

def start_paranoia(data, groupid):

    data[groupid]["game"] = {
        "type": "偏执狂",
        "turn": 2,
        "phase": "collect",
        "questions": {},
        "current_q": None,
        "current_target": None,
        "drinkers": {},
        "used_questioners": [],
        "last_answer_time": 0
    }

    setData("game.json", data)
    if data[groupid]["playname"]:
        return f"偏执狂游戏已开启！\n玩家入座后，请于个人群发送：偏执狂 问题内容"
    else:
        return f"偏执狂游戏已开启！\n玩家入座后，请在我的小窗发送（如不回复请加好友）：偏执狂 问题内容"

def handle_private(plugin_event, data, uid, message):
    if not message.startswith("偏执狂"):
        return False
    handle_paranoia(plugin_event, data, 0, uid, message)
    return True

def handle(plugin_event, data, groupid, uid, message, masterlist=None):
    message = message.strip()
    if message.startswith("偏执狂"):
        handle_paranoia(plugin_event, data, groupid, uid, message)
        return True
    if data[groupid].get("game", {}).get("type") != GAME_TYPE:
        return False
    return handle_paranoia_playgroup(
        plugin_event, data, groupid, uid, message
    )

def check_timeout(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    if game.get("type") != GAME_TYPE:
        return False
    if game.get("phase") == "drink" and time.time() - game.get("last_answer_time", 0) > 180:
        next_paranoia_round(plugin_event, data, groupid, groupid)
        return True
    return False


def handle_paranoia(plugin_event, data, groupid, uid, message):
    uid = str(uid)
    play_group = engine.find_play_group(data, uid, GAME_TYPE)
    if not play_group:
        if engine.find_play_group(data, uid):
            plugin_event.reply("您当前没有参加偏执狂游戏！")
        else:
            plugin_event.reply("您尚未参加任何游戏！")
        return
    set_paranoia_question(plugin_event, data, uid, play_group, message)
    return


def handle_paranoia_playgroup(plugin_event, data, groupid, uid, message):
    message = message.strip()
    game = data[groupid].get("game") or {}
    if message == "开启偏执狂":
        plugin_event.reply(start_paranoia(data, groupid))
        return True
    if handle_paranoia_answer(plugin_event, data, groupid, uid):
        return True
    if "phase" not in game:
        return False
    if game["phase"] == "drink" and time.time() - game["last_answer_time"] > 180:
        next_paranoia_round(plugin_event, data, groupid, groupid)
        return False
    elif message == "喝":
        handle_drink(plugin_event, data, groupid, uid)
        return True
    elif message.startswith("跳过"):
        next_paranoia_round(plugin_event, data, groupid, groupid)
        return True
    elif message == "直接开始游戏":
        game["phase"] = "ask"
        game["used_questioners"] = []
        setData("game.json", data)
        start_paranoia_round(plugin_event, data, groupid)
        return True
    return False


def set_paranoia_question(plugin_event, data, uid, play_group, message):
    game = data[play_group].get("game")
    content = message[3:].strip()
    if not content:
        plugin_event.reply("请输入问题内容！")
        return

    game["questions"][str(uid)] = content
    setData("game.json", data)

    plugin_event.reply("问题已记录。")
    active_players = engine.active_players(data, play_group)
    active_uids = [str(player.get("uid")) for player in active_players]
    submitted_count = len([
        uid for uid in active_uids
        if uid in game.get("questions", {})
    ])
    # 判断是否全部提交
    if active_uids and submitted_count >= len(active_uids) and game["phase"] == "collect":
        game["phase"] = "ask"
        setData("game.json", data)
        start_paranoia_round(plugin_event, data, play_group)
    else:
        plugin_event.send("group", play_group, f"已提交问题（{submitted_count}/{len(active_uids)}）")
    return

def search_valid(plugin_event, data, play_group, turn, require_question=False, exclude_used=False):
    personal = data[play_group]["个人"]
    game = data[play_group].get("game", {})
    used_questioners = set(str(uid) for uid in game.get("used_questioners", []))
    search_turn = turn
    for _ in range(len(personal)):
        if search_turn == len(personal) + 1:
            search_turn = 1
        p = personal[str(search_turn)]
        uid = str(p.get("uid", ""))
        if p.get("uid"):
            if require_question and uid not in game.get("questions", {}):
                search_turn += 1
                continue
            if exclude_used and uid in used_questioners:
                search_turn += 1
                continue
            target_item = p
            return target_item, str(search_turn)
        search_turn += 1
    else:
        plugin_event.reply("没有非空玩家！游戏已结束！开启新游戏请使用指令：开启偏执狂")
        engine.mark_game_ended(data, play_group)
        setData("game.json", data)
        return None, None


def start_paranoia_round(plugin_event, data, play_group):
    game = data[play_group]["game"]
    turn = game["turn"]

    q_item, game["current_q"] = search_valid(
        plugin_event, data, play_group, game["turn"] - 1, require_question=True, exclude_used=True
    )
    if not q_item:
        return
    if q_item:
        target_item, game["current_target"] = search_valid(
            plugin_event, data, play_group, int(game["current_q"]) + 1
        )
    if not target_item:
        return

    if game["current_target"] == game["current_q"]:
        plugin_event.reply("没有非空玩家！游戏已结束！开启新游戏请使用指令：开启偏执狂")
        engine.mark_game_ended(data, play_group)
        setData("game.json", data)
        return

    qname = q_item["name"]
    target_name = target_item["name"]
    game["phase"] = "answer"
    game.setdefault("used_questioners", []).append(str(q_item["uid"]))

    setData("game.json", data)

    question = game["questions"].get(q_item["uid"], "（无问题）")
    if data[play_group]["playname"]:
        plugin_event.send("group", target_item["groupid"], f"{qname}问你：\n{question}\n请公屏回答（默认你在群内发的第一条消息就是回答）。")
    else:
        plugin_event.send("private", target_item["uid"],
                          f"{qname}问你：\n{question}\n请公屏回答（默认你在群内发的第一条消息就是回答）。")
    plugin_event.send("group", play_group, f"第{turn-1}轮：{qname} 问 {target_name}，[OP:at,id={target_item['uid']}]请回答。")
    return

def handle_paranoia_answer(plugin_event, data, groupid, uid):
    game = data[groupid].get("game")
    if game.get("phase") != "answer":
        return 0
    personal = data[groupid]["个人"]
    if str(uid) != str(personal[game["current_target"]]["uid"]):
        return 0

    game["phase"] = "drink"
    game["last_answer_time"] = time.time()

    setData("game.json", data)
    name = data[groupid]["个人"][game["current_target"]]["name"]
    plugin_event.reply(f"{name} 已回答！想知道答案请在三分钟内发送：喝（不要加名字，只发一个字喝）")
    return 1

def handle_drink(plugin_event, data, groupid, uid):
    game = data[groupid].get("game")
    if game["phase"] != "drink":
        return
    if time.time() - game["last_answer_time"] > 180:
        return

    game["drinkers"][uid] = game["drinkers"].get(uid, 0) + 1
    setData("game.json", data)

    personal = data[groupid]["个人"]

    q_item = personal[game["current_q"]]
    target_item = personal[game["current_target"]]

    qname = q_item["name"]
    target_name = target_item["name"]
    question = game["questions"].get(q_item["uid"], "（未填写）")

    if data[groupid]["playname"]:
        for p, v in personal.items():
            if v.get("uid") == uid:
                plugin_event.send("group", v["groupid"],
                    f"{game['turn']-1}. {qname}问{target_name}：{question}"
                )
                break
    else:
        plugin_event.send("private", uid, f"{game['turn']-1}. {qname}问{target_name}：{question}")
    return


def next_paranoia_round(plugin_event, data, groupid, play_group):
    game = data[groupid].get("game")
    active_questioners = [
        str(player.get("uid"))
        for player in engine.active_players(data, play_group)
        if str(player.get("uid")) in game.get("questions", {})
    ]
    used_questioners = set(str(uid) for uid in game.get("used_questioners", []))
    if active_questioners and all(uid in used_questioners for uid in active_questioners):
        plugin_event.reply("游戏已结束！开启新游戏请使用指令：开启偏执狂")
        engine.mark_game_ended(data, groupid)
        setData("game.json", data)
        send_drink_stats(plugin_event, data, groupid)
    else:
        send_drink_stats(plugin_event, data, groupid)
        game["turn"] += 1
        game["phase"] = "ask"
        setData("game.json", data)
        start_paranoia_round(plugin_event, data, play_group)
    return


def send_drink_stats(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    stats = []
    for uid, cnt in game.get("drinkers", {}).items():
        for p, v in data[groupid]["个人"].items():
            if v.get("uid") == uid:
                name = v["name"]
                stats.append(f"{name}：{cnt}次")
                break
    if not stats:
        return
    text = "喝酒数量统计：\n" + "\n".join(stats)
    engine.send_forward_text(
        plugin_event,
        groupid,
        0,
        [engine.build_forward_node(" ", plugin_event.bot_info.id, text)]
    )

def build_forward_node(name, uin, t):
    return {
        "type": "node",
        "data": {
            "name": name,
            "uin": str(uin),
            "content": [
                {
                    "type": "text",
                    "data": {
                        "text": t
                    }
                }
            ]
        }
    }
