from .main import setData
from . import engine


def handle_score(plugin_event, data, groupid, uid, message, masterlist=None):
    if groupid not in data or "game" not in data[groupid]:
        return False
    message = message.strip()
    masterlist = masterlist or []
    game = engine.ensure_common_fields(data[groupid].get("game"))
    game.setdefault("score_items", {})

    if message in ["计分", "计分榜"]:
        if send_game_score(plugin_event, data, groupid, game):
            return True
        engine.send_score_forward(plugin_event, data, groupid, "计分统计：")
        return True

    if message == "计分项":
        items = game.get("score_items", {})
        if not items:
            plugin_event.reply("暂无计分项。")
            return True
        lines = ["计分项："]
        for key, value in items.items():
            lines.append(f"{key}：{format_delta(value)}")
        engine.send_forward_text(
            plugin_event,
            groupid,
            0,
            [engine.build_forward_node(" ", plugin_event.bot_info.id, "\n".join(lines))]
        )
        return True

    if message.startswith("添加计分项 "):
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return True
        parts = message.split()
        if len(parts) != 3 or not is_int(parts[2]):
            plugin_event.reply("指令格式：添加计分项 指令 分数\n例如：添加计分项 喝 1 / 添加计分项 折 -1")
            return True
        key = parts[1].strip()
        if key in ["计分", "计分榜", "计分项", "跳过", "下一轮"]:
            plugin_event.reply("该词是保留指令，不能作为计分项。")
            return True
        game["score_items"][key] = int(parts[2])
        setData("game.json", data)
        plugin_event.reply(f"已添加计分项：{key}（{format_delta(game['score_items'][key])}）")
        return True

    if message.startswith("删除计分项 "):
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return True
        key = message.replace("删除计分项", "", 1).strip()
        if not key:
            plugin_event.reply("指令格式：删除计分项 指令")
            return True
        if key not in game.get("score_items", {}):
            plugin_event.reply("没有这个计分项。")
            return True
        del game["score_items"][key]
        setData("game.json", data)
        plugin_event.reply(f"已删除计分项：{key}")
        return True

    if message == "清空计分":
        if uid not in masterlist:
            plugin_event.reply("权限不足！")
            return True
        game["scores"] = {}
        setData("game.json", data)
        plugin_event.reply("计分已清空。")
        return True

    if message in game.get("score_items", {}):
        if not engine.player_by_uid(data, groupid, uid):
            return False
        delta = game["score_items"][message]
        score = engine.add_score(data, groupid, uid, delta)
        setData("game.json", data)
        plugin_event.reply(f"{engine.uid_name(data, groupid, uid)} {message}，{format_delta(delta)}，当前 {score} 分")
        return True

    return False


def is_int(text):
    return text.lstrip("-").isdigit()


def format_delta(value):
    value = int(value)
    return f"+{value}" if value > 0 else str(value)


def send_game_score(plugin_event, data, groupid, game):
    game_type = game.get("type")
    if game_type == "数字炸弹":
        send_number_bomb_score(plugin_event, groupid, game)
        return True
    if game_type == "女巫毒药":
        send_witch_poison_score(plugin_event, groupid, game)
        return True
    if game_type == "偏执狂":
        send_paranoia_score(plugin_event, data, groupid, game)
        return True
    if game_type == "你有我没有":
        from .never_have_i import send_score_with_history
        send_score_with_history(plugin_event, data, groupid)
        return True
    return False


def send_number_bomb_score(plugin_event, groupid, game):
    history = game.get("hit_history", [])
    if not history:
        plugin_event.reply("暂无数字炸弹踩中记录。")
        return
    lines = ["数字炸弹踩中记录"]
    for item in history:
        lines.append(
            f"第{item.get('round')}轮：{item.get('name')}"
            f"（{item.get('seat')}号）踩中 {item.get('bomb')}"
            f"\n范围：{item.get('range')}"
        )
    send_score_nodes(plugin_event, groupid, "\n".join(lines))


def send_witch_poison_score(plugin_event, groupid, game):
    history = game.get("hit_history", [])
    if not history:
        plugin_event.reply("暂无女巫毒药踩中记录。")
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
    send_score_nodes(plugin_event, groupid, "\n\n".join(lines))


def send_paranoia_score(plugin_event, data, groupid, game):
    stats = []
    for uid, cnt in game.get("drinkers", {}).items():
        name = str(uid)
        for player in data[groupid].get("个人", {}).values():
            if str(player.get("uid", "")) == str(uid):
                name = player.get("name", name)
                break
        stats.append(f"{name}：{cnt}次")
    if not stats:
        plugin_event.reply("暂无喝酒记录。")
        return
    send_score_nodes(plugin_event, groupid, "喝酒数量统计：\n" + "\n".join(stats))


def send_score_nodes(plugin_event, groupid, text):
    engine.send_forward_text(
        plugin_event,
        groupid,
        0,
        [engine.build_forward_node(" ", plugin_event.bot_info.id, text)]
    )
