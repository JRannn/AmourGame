from .main import setData
from . import engine


GAME_TYPE = "你画我猜"


def start_draw_guess(data, groupid):
    game = engine.ensure_game(data, groupid, GAME_TYPE, phase="collect", turn=1)
    game["submissions"] = {}
    game["used_hosts"] = []
    setData("game.json", data)
    send_place = "个人群" if data[groupid]["playname"] else "我的小窗发送（如不回复请加好友）"
    return (
        "你画我猜游戏已开启！\n"
        f"玩家入座后，请于{send_place}：你画我猜 答案\n"
        "抢答时第一个答对的人 +1 分。"
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
        plugin_event.reply("请填写答案：你画我猜 答案")
        return True
    answer, hint = content, ""
    if not answer:
        plugin_event.reply("请填写答案：你画我猜 答案")
        return True
    engine.record_submission(data, play_group, uid, {"answer": answer, "hint": hint})
    setData("game.json", data)
    plugin_event.reply("题目已记录。")
    plugin_event.send(
        "group",
        play_group,
        f"已提交题目（{engine.active_submitted_count(data, play_group)}/{len(engine.active_players(data, play_group))}）"
    )
    if data[play_group]["game"].get("phase") == "collect" and engine.all_active_submitted(data, play_group):
        data[play_group]["game"]["phase"] = "guess"
        data[play_group]["game"]["used_hosts"] = []
        setData("game.json", data)
        start_round(plugin_event, data, play_group)
    return True


def handle(plugin_event, data, groupid, uid, message, masterlist=None):
    message = message.strip()
    game = engine.ensure_common_fields(data[groupid].get("game"))

    if message in ["计分", "计分榜"]:
        engine.send_score_forward(plugin_event, data, groupid, "你画我猜计分：")
        return True

    if message == "直接开始游戏":
        game["phase"] = "guess"
        game["used_hosts"] = []
        setData("game.json", data)
        start_round(plugin_event, data, groupid)
        return True

    if message in ["跳过", "下一轮"]:
        start_round(plugin_event, data, groupid)
        return True

    if game.get("phase") != "guess":
        return False
    round_data = game.get("round", {})
    answer = str(round_data.get("answer", "")).strip()
    host = str(round_data.get("host", ""))
    if not answer or str(uid) == host:
        return False
    if message.lower() != answer.lower():
        return False
    if engine.first_answer(round_data, uid):
        engine.add_score(data, groupid, uid, 1)
        setData("game.json", data)
        plugin_event.reply(f"{engine.uid_name(data, groupid, uid)} 抢答成功！答案：{answer}，+1分")
        start_round(plugin_event, data, groupid)
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
            game["phase"] = "guess"
            game["round"] = {
                "host": host_uid,
                "seat": seat,
                "answer": submission["answer"],
                "hint": submission.get("hint", ""),
            }
            game.setdefault("used_hosts", []).append(host_uid)
            engine.mark_round_start(game)
            setData("game.json", data)
            msg = f"本轮画手：{engine.player_name(player)}\n请开始作画，其他玩家直接发送答案抢答。"
            if submission.get("hint"):
                msg += f"\n提示：{submission['hint']}"
            plugin_event.send("group", groupid, msg)
            engine.advance_turn(data, groupid)
            setData("game.json", data)
            return
        start = int(seat)

    if game.get("used_hosts"):
        plugin_event.send("group", groupid, "你画我猜本轮已结束！开启新游戏请使用指令：开启游戏 你画我猜 人数")
        engine.mark_game_ended(data, groupid)
        engine.send_final_score_forward(plugin_event, data, groupid)
    else:
        plugin_event.send("group", groupid, "没有可用题目！请玩家先私聊/个人群提交题目。")
    setData("game.json", data)


def check_timeout(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    if game.get("type") != GAME_TYPE or not engine.is_round_timeout(game):
        return False
    plugin_event.reply(f"本轮已超过{engine.round_timeout_minutes_text(game)}，自动进入下一题。")
    start_round(plugin_event, data, groupid)
    return True
