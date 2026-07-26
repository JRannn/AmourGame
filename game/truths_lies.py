import re

from .main import setData
from . import engine


GAME_TYPES = ["两真一假", "两假一真"]


def start_truths_lies(data, groupid, game_type):
    game = engine.ensure_game(data, groupid, game_type, phase="collect", turn=1)
    game["submissions"] = {}
    game["host_score"] = False
    game["used_hosts"] = []
    setData("game.json", data)
    send_place = "个人群" if data[groupid]["playname"] else "我的小窗发送（如不回复请加好友）"
    return (
        f"{game_type}游戏已开启！\n"
        "管理员可发送：开启出题人加分 / 关闭出题人加分\n"
        f"玩家入座后，请按以下格式于{send_place}发送：\n"
        f"{game_type}\n"
        "1.\n"
        "2.\n"
        "3.\n"
        "答案：1/2/3"
    )


def handle_submission(plugin_event, data, uid, message):
    game_type = get_message_type(message)
    if not game_type:
        return False
    play_group = engine.find_play_group(data, uid, game_type)
    if not play_group:
        plugin_event.reply("您尚未参加任何游戏！")
        return True
    game = data[play_group].get("game", {})
    if game.get("type") != game_type:
        return False
    parsed = parse_submission(message, game_type)
    if not parsed:
        plugin_event.reply(
            f"格式错误！请按以下格式发送：\n{game_type}\n1.\n2.\n3.\n答案：1/2/3"
        )
        return True
    engine.record_submission(data, play_group, uid, parsed)
    setData("game.json", data)
    plugin_event.reply("题目已记录。")
    plugin_event.send(
        "group",
        play_group,
        f"已提交题目（{engine.active_submitted_count(data, play_group)}/{len(engine.active_players(data, play_group))}）"
    )
    if data[play_group]["game"].get("phase") == "collect" and engine.all_active_submitted(data, play_group):
        data[play_group]["game"]["phase"] = "ask"
        data[play_group]["game"]["used_hosts"] = []
        setData("game.json", data)
        start_round(plugin_event, data, play_group)
    return True


def handle(plugin_event, data, groupid, uid, message, masterlist=None):
    message = message.strip()
    game = engine.ensure_common_fields(data[groupid].get("game"))

    if message in ["计分", "计分榜"]:
        engine.send_score_forward(plugin_event, data, groupid, f"{game.get('type')}计分：")
        return True

    if message in ["开启出题人加分", "关闭出题人加分"]:
        if masterlist is not None and uid not in masterlist:
            plugin_event.reply("权限不足！")
            return True
        game["host_score"] = message == "开启出题人加分"
        setData("game.json", data)
        plugin_event.reply("出题人加分已开启。" if game["host_score"] else "出题人加分已关闭。")
        return True

    if message == "直接开始游戏":
        game["phase"] = "ask"
        game["used_hosts"] = []
        setData("game.json", data)
        start_round(plugin_event, data, groupid)
        return True

    if message in ["跳过", "下一轮"]:
        finish_round(plugin_event, data, groupid, skipped=True)
        return True

    if game.get("phase") == "vote":
        choice = engine.parse_choice(message, 1, 3)
        if choice is None:
            return False
        round_data = game.get("round", {})
        host = str(round_data.get("host", ""))
        if str(uid) == host:
            plugin_event.reply("出题人不用作答。")
            return True
        if not engine.player_by_uid(data, groupid, uid):
            return False
        round_data.setdefault("votes", {})[str(uid)] = choice
        setData("game.json", data)
        plugin_event.reply(f"{engine.uid_name(data, groupid, uid)} ：{choice}")
        if is_vote_complete(data, groupid):
            finish_round(plugin_event, data, groupid)
        return True
    return False


def get_message_type(message):
    for game_type in GAME_TYPES:
        if message.startswith(game_type):
            return game_type
    return None


def parse_submission(message, game_type):
    content = message.replace(game_type, "", 1).strip()
    line_options = {}
    answer = None
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        option_match = re.match(r"^([123])[\.\。．、]\s*(.+)$", line)
        if option_match:
            line_options[int(option_match.group(1))] = option_match.group(2).strip()
            continue
        answer_match = re.match(r"^答案\s*[:：]\s*([123])$", line)
        if answer_match:
            answer = int(answer_match.group(1))

    if len(line_options) == 3 and answer:
        return {
            "options": [line_options[1], line_options[2], line_options[3]],
            "answer": answer
        }

    answer_match = re.search(r"答案\s*[:：]?\s*([123])", content)
    if not answer_match:
        answer_match = re.search(r"([123])\s*$", content)
    if not answer_match:
        return None
    answer = int(answer_match.group(1))
    content = content[:answer_match.start()].strip()
    parts = [p.strip() for p in re.split(r"\s*[/／|｜]\s*", content) if p.strip()]
    if len(parts) != 3:
        return None
    return {
        "options": parts,
        "answer": answer
    }


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
            game["phase"] = "vote"
            game["round"] = {
                "host": host_uid,
                "seat": seat,
                "options": submission["options"],
                "answer": submission["answer"],
                "votes": {}
            }
            game.setdefault("used_hosts", []).append(host_uid)
            engine.mark_round_start(game)
            setData("game.json", data)
            lines = [
                f"本轮出题人：{engine.player_name(player)}",
                "请判断哪一项是答案："
            ]
            for idx, option in enumerate(submission["options"], start=1):
                lines.append(f"{idx}. {option}")
            lines.append("请直接发送 1 / 2 / 3 作答。")
            plugin_event.send("group", groupid, "\n".join(lines))
            return
        start = int(seat)

    if game.get("used_hosts"):
        plugin_event.send("group", groupid, f"{game.get('type')}本轮已结束！开启新游戏请使用指令：开启游戏 {game.get('type')} 人数")
        engine.mark_game_ended(data, groupid)
        engine.send_final_score_forward(plugin_event, data, groupid)
    else:
        plugin_event.send("group", groupid, "没有可用题目！请玩家先私聊/个人群提交题目，或发送：跳过")
    setData("game.json", data)


def is_vote_complete(data, groupid):
    game = data[groupid]["game"]
    host = str(game.get("round", {}).get("host", ""))
    votes = game.get("round", {}).get("votes", {})
    need = [
        p.get("uid")
        for p in engine.active_players(data, groupid)
        if str(p.get("uid")) != host
    ]
    return bool(need) and all(str(uid) in votes for uid in need)


def finish_round(plugin_event, data, groupid, skipped=False):
    game = engine.ensure_common_fields(data[groupid].get("game"))
    round_data = game.get("round", {})
    if game.get("phase") == "vote" and round_data and not skipped:
        answer = int(round_data.get("answer"))
        votes = round_data.get("votes", {})
        correct = []
        wrong = []
        for uid, choice in votes.items():
            if int(choice) == answer:
                engine.add_score(data, groupid, uid, 1)
                correct.append(engine.uid_name(data, groupid, uid))
            else:
                wrong.append(engine.uid_name(data, groupid, uid))
        host = round_data.get("host")
        if wrong and game.get("host_score"):
            engine.add_score(data, groupid, host, len(wrong))
        target = "假话" if game.get("type") == "两真一假" else "真话"
        msg = [
            f"本轮答案：{answer}（{target}）",
            f"猜对：{'、'.join(correct) if correct else '无'}",
            f"猜错：{'、'.join(wrong) if wrong else '无'}",
        ]
        if wrong and game.get("host_score"):
            msg.append(f"出题人 {engine.uid_name(data, groupid, host)} +{len(wrong)}分")
        plugin_event.reply("\n".join(msg))

    next_seat = engine.advance_turn(data, groupid)
    game["phase"] = "ask"
    game["round"] = {}
    engine.mark_round_start(game)
    setData("game.json", data)
    if next_seat:
        start_round(plugin_event, data, groupid)


def check_timeout(plugin_event, data, groupid):
    game = data[groupid].get("game", {})
    if game.get("type") not in GAME_TYPES or not engine.is_round_timeout(game):
        return False
    plugin_event.reply("本轮已超过三分钟，自动公布结果。")
    finish_round(plugin_event, data, groupid)
    return True
