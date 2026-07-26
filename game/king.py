from .main import setData
from . import engine


GAME_TYPE = "国王游戏"


def start_king(data, groupid):
    game = engine.ensure_game(data, groupid, GAME_TYPE, phase="collect", turn=1)
    game["submissions"] = {}
    game["used_hosts"] = []
    setData("game.json", data)
    send_place = "个人群" if data[groupid]["playname"] else "我的小窗发送（如不回复请加好友）"
    return (
        "国王游戏已开启！\n"
        f"玩家入座后，请于{send_place}：国王游戏 题目内容"
    )


def handle_submission(plugin_event, data, uid, message):
    if not message.startswith(GAME_TYPE):
        return False
    play_group = engine.find_play_group(data, uid, GAME_TYPE)
    if not play_group:
        plugin_event.reply("您尚未参加任何游戏！")
        return True
    game = data[play_group].get("game", {})
    if game.get("type") != GAME_TYPE:
        return False
    content = message.replace(GAME_TYPE, "", 1).strip()
    if not content:
        plugin_event.reply("请填写题目内容：国王游戏 题目内容")
        return True
    engine.record_submission(data, play_group, uid, {"question": content})
    setData("game.json", data)
    plugin_event.reply("题目已记录。")
    plugin_event.send(
        "group",
        play_group,
        f"已提交题目（{engine.active_submitted_count(data, play_group)}/{len(engine.active_players(data, play_group))}）"
    )
    if data[play_group]["game"].get("phase") == "collect" and engine.all_active_submitted(data, play_group):
        data[play_group]["game"]["phase"] = "play"
        data[play_group]["game"]["used_hosts"] = []
        setData("game.json", data)
        start_round(plugin_event, data, play_group)
    return True


def handle(plugin_event, data, groupid, uid, message, masterlist=None):
    message = message.strip()
    game = engine.ensure_common_fields(data[groupid].get("game"))
    if message == "直接开始游戏":
        game["phase"] = "play"
        game["used_hosts"] = []
        setData("game.json", data)
        start_round(plugin_event, data, groupid)
        return True
    if message in ["下一轮", "跳过"]:
        start_round(plugin_event, data, groupid)
        return True
    if message == "查看顺序":
        order = game.get("round", {}).get("order", [])
        if not order:
            plugin_event.reply("本轮还没有生成顺序。")
            return True
        plugin_event.reply(engine.format_seat_order(data, groupid, order))
        return True
    return False


def start_round(plugin_event, data, groupid):
    game = engine.ensure_common_fields(data[groupid].get("game"))
    seats = engine.active_seats(data, groupid)
    if not seats:
        plugin_event.send("group", groupid, "没有非空玩家！游戏已结束。")
        engine.mark_game_ended(data, groupid)
        setData("game.json", data)
        return

    start = int(game.get("turn", 1)) - 1
    used_hosts = set(str(uid) for uid in game.get("used_hosts", []))
    for _ in seats:
        seat = engine.next_active_seat(data, groupid, start)
        player = engine.player_by_seat(data, groupid, seat)
        host_uid = str(player.get("uid", ""))
        submission = None if host_uid in used_hosts else engine.get_submission(data, groupid, host_uid)
        if submission:
            engine.set_turn(game, seat)
            order = engine.random_seat_order(data, groupid)
            game["phase"] = "play"
            game["round"] = {
                "king": host_uid,
                "seat": seat,
                "question": submission["question"],
                "order": order,
            }
            game.setdefault("used_hosts", []).append(host_uid)
            engine.mark_round_start(game)
            setData("game.json", data)
            plugin_event.send(
                "group",
                groupid,
                f"本轮国王：{engine.player_name(player)}\n"
                f"题目：{submission['question']}\n\n"
                + engine.format_seat_order(data, groupid, order)
            )
            engine.advance_turn(data, groupid)
            setData("game.json", data)
            return
        start = int(seat)

    if game.get("used_hosts"):
        plugin_event.send("group", groupid, "国王游戏本轮已结束！开启新游戏请使用指令：开启游戏 国王游戏 人数")
        engine.mark_game_ended(data, groupid)
    else:
        plugin_event.send("group", groupid, "没有可用题目！请玩家先私聊/个人群提交题目。")
    setData("game.json", data)


def check_timeout(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    if game.get("type") != GAME_TYPE or not engine.is_round_timeout(game):
        return False
    plugin_event.reply("本轮已超过三分钟，自动进入下一轮。")
    start_round(plugin_event, data, groupid)
    return True
