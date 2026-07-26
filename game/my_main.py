import shutil
import time
import OlivOS
import OlivaDiceCore
from importlib import import_module
from datetime import datetime
import threading
import json, os, re
import traceback

admin_list = [
]  # 除骰主外的本插件管理员qq号列表，按格式填写，修改记得重载
gamelock = threading.Lock()

class Event(object):
    def init(plugin_event, Proc):
        pass

    def group_message(plugin_event, Proc):
        try:
            reply(plugin_event, Proc)
        except Exception as e:
            error(plugin_event, traceback.format_exc(), e)

    def private_message(plugin_event, Proc):        
        try:
            pri_reply(plugin_event, Proc)
        except Exception as e:
            error(plugin_event, traceback.format_exc(), e)

    def poke(plugin_event, Proc):
        pass

    def save(plugin_event, Proc):
        pass

def error(plugin_event, e, simple_e):
    l= plugin_event.get_friend_list()
    i_list = [g["id"] for g in l["data"]]
    if "2803450053" in i_list:
        plugin_event.send("private", 2803450053, e)
        plugin_event.reply(f"错误！请联系管理员，将此信息发送给反季节生物处理：{simple_e}")
    else:
        plugin_event.reply(f"错误！请联系管理员，将此信息发送给反季节生物处理：{e}")

GAME_NAME = ["数字炸弹", "女巫毒药", "偏执狂", "你有我没有", "两真一假", "两假一真", "国王游戏", "你画我猜"]

ROUND_GAME_TYPES = ["你有我没有", "两真一假", "两假一真", "国王游戏", "你画我猜"]

COLLECT_GAME_TYPES = ["偏执狂", "两真一假", "两假一真", "国王游戏", "你画我猜"]

GAME_MODULES = {
    "数字炸弹": "bomb",
    "女巫毒药": "bomb",
    "偏执狂": "paranoia",
    "你有我没有": "never_have_i",
    "两真一假": "truths_lies",
    "两假一真": "truths_lies",
    "国王游戏": "king",
    "你画我猜": "draw_guess",
}

def pri_reply(plugin_event, Proc):
    message = plugin_event.data.message
    uid = str(plugin_event.data.user_id)
    data = get_daily_game_data()

    dispatch_private_submission(plugin_event, data, uid, message)

def reply(plugin_event, Proc):
    message = plugin_event.data.message
    groupid = str(plugin_event.data.group_id)
    uid = str(plugin_event.data.user_id)
    platfrom = plugin_event.platform["platform"]
    tmp_botHash = plugin_event.bot_info.hash
    masterlist = getMaster(tmp_botHash, platfrom)
    privategroup = getGroup("privategroup.json")
    data = get_daily_game_data()

    if message == "游戏插件手册":
        send_game_manual(plugin_event, groupid)
        return

    if message.startswith("晚间游戏 "):
        args = message.split()
        if len(args) != 3:
            plugin_event.reply("指令格式：晚间游戏 恋综名 人数")
            return
        playname = args[1]
        if not args[2].isdigit():
            plugin_event.reply("人数必须是数字！")
            return
        if playname not in privategroup:
            plugin_event.reply(f"未找到恋综【{playname}】的数据！")
            return
        num = int(args[2])
        data[groupid] = {
            "playname": playname,
            "gamename": "晚间游戏",
            "上次报数时间": datetime.now().timestamp(),
            "个人": {str(i): {} for i in range(1, num + 1)}
        }
        setData("game.json", data)
        plugin_event.reply("晚间游戏座位表已开启，请参与者发送“坐 序号”入座。（发送“不坐 序号”取消）")
        plugin_event.reply(format_seating_table(data, groupid))
        return

    if message.startswith("开启游戏"):
        args = message.split()
        if len(args) < 3:
            plugin_event.reply("指令格式：开启游戏 游戏名 [恋综名] 人数")
            return
        if not args[-1].isdigit():
            plugin_event.reply("人数必须是数字！")
            return
        gamename = args[1]
        if gamename not in GAME_NAME:
            plugin_event.reply("未配备该游戏！")
            return
        # 判断有没有恋综名
        if len(args) == 3:
            playname = None  # 没有恋综名
        else:
            playname = args[2]
        num = int(args[-1])
        timestamp = datetime.now().timestamp()
        # 初始化
        data[groupid] = {
            "playname": playname,
            "gamename": gamename,
            "上次报数时间": timestamp,
            "个人": {str(i): {} for i in range(1, num+1)}
        }
        setData("game.json", data)
        plugin_event.reply("请参与者发送“坐 序号”入座。（发送“不坐 序号”取消）")
        send_open_game_hint(plugin_event, data, groupid, gamename)
        return

    if message == "结束游戏":
        if groupid not in data:
            return
        del data[groupid]
        setData("game.json", data)
        plugin_event.reply("当前群游戏已结束。")
        return

    if groupid not in data:
        if is_player_submit_group(data, groupid, uid):
            dispatch_private_submission(plugin_event, data, uid, message)
        return

    if message == "查看座位":
        plugin_event.reply(format_seating_table(data, groupid))
        return

    if message.startswith("坐"):
        m = re.match(r"^坐\s*(\d+)$", message.strip())
        if not m:
            return
        idx = m.group(1)
        personal = data[groupid]["个人"]
        if idx not in personal:
            plugin_event.reply("序号不存在，请检查开启时设置的人数。")
            return
        playname = data[groupid]["playname"]
        if playname:
            p_name = privategroup[playname]["data"][uid]["嘉宾姓名"]
            group = privategroup[playname]["data"][uid]["个人群号"]
            personal[idx] = {"name": p_name, "uid": uid, "groupid": group}
        else:
            p_name = plugin_event.get_stranger_info(uid)["data"]["name"]
            personal[idx] = {"name": p_name, "uid": uid}
        game = data[groupid].get("game", {})
        if game.get("type") == "你有我没有":
            seated_count = len([p for p in personal.values() if p.get("uid")])
            game.setdefault("scores", {}).setdefault(str(uid), seated_count)
        setData("game.json", data)

        plugin_event.reply(f"{idx}：{p_name}")
        if data[groupid].get("gamename") == "晚间游戏":
            plugin_event.reply(format_seating_table(data, groupid))
            return

        timestamp = datetime.now().timestamp()
        last_report_time = data[groupid].get("上次报数时间", 0)
        time_diff = timestamp - last_report_time
        trigger = False
        if time_diff > 60:
            trigger = True
            data[groupid]["上次报数时间"] = timestamp
        all_filled = all(v.get("name") for v in personal.values())
        if all_filled or trigger:
            msg = "游戏顺序：\n"
            for k, v in sorted(personal.items(), key=lambda x: int(x[0])):
                name = v.get("name","")
                msg += f"{k}. {name}\n"
            plugin_event.reply(msg.strip())
        if all_filled:
            gamename = data[groupid].get("gamename")
            handle_game_ready(plugin_event, data, groupid, gamename)
        return

    if message.startswith("不坐"):
        m = re.match(r"^不坐\s*(\d+)$", message.strip())
        if not m:
            return
        idx = m.group(1)
        personal = data[groupid]["个人"]
        if idx not in personal:
            plugin_event.reply("序号不存在，请检查开启时设置的人数。")
            return
        personal[idx] = {}
        setData("game.json", data)
        plugin_event.reply(f"{idx}号位置已空！")
        if data[groupid].get("gamename") == "晚间游戏":
            plugin_event.reply(format_seating_table(data, groupid))
        return

    from .score import handle_score
    if (
        message in ["计分", "计分榜", "计分项", "清空计分"]
        or message.startswith("添加计分项 ")
        or message.startswith("删除计分项 ")
    ):
        if handle_score(plugin_event, data, groupid, uid, message, masterlist):
            return

    if dispatch_game_message(plugin_event, data, groupid, uid, message, masterlist):
        return

    if handle_score(plugin_event, data, groupid, uid, message, masterlist):
        return

def dispatch_private_submission(plugin_event, data, uid, message):
    from .bomb import handle_private as handle_bomb_private
    if handle_bomb_private(plugin_event, data, uid, message):
        return True

    from .paranoia import handle_private as handle_paranoia_private
    if handle_paranoia_private(plugin_event, data, uid, message):
        return True

    from .truths_lies import handle_submission as handle_truth_submission
    if handle_truth_submission(plugin_event, data, uid, message):
        return True

    from .king import handle_submission as handle_king_submission
    if handle_king_submission(plugin_event, data, uid, message):
        return True

    from .draw_guess import handle_submission as handle_draw_submission
    if handle_draw_submission(plugin_event, data, uid, message):
        return True

    return False

def is_player_submit_group(data, groupid, uid):
    uid = str(uid)
    groupid = str(groupid)
    for game_data in data.values():
        for player in game_data.get("个人", {}).values():
            if str(player.get("uid", "")) == uid and str(player.get("groupid", "")) == groupid:
                return True
    return False

def dispatch_game_message(plugin_event, data, groupid, uid, message, masterlist):
    gamename = data[groupid].get("gamename")
    game = data[groupid].get("game", {})
    if not isinstance(game, dict):
        game = {}
        data[groupid]["game"] = game
        setData("game.json", data)
    game_type = game.get("type")

    if check_round_timeout(plugin_event, data, groupid, game_type):
        return True

    if message == "直接开始游戏" and not game_type and gamename == "你有我没有":
        start_configured_game(plugin_event, data, groupid, gamename)
        return True

    module_name = get_command_module(message) or GAME_MODULES.get(game_type) or GAME_MODULES.get(gamename)
    if not module_name:
        return False
    module = import_module(f".{module_name}", __package__)
    return module.handle(plugin_event, data, groupid, uid, message, masterlist)

def get_command_module(message):
    if message.startswith(("开始数字炸弹", "开始女巫毒药", "放毒")):
        return "bomb"
    if message.startswith("偏执狂"):
        return "paranoia"
    return None

def handle_game_ready(plugin_event, data, groupid, gamename):
    if gamename == "晚间游戏":
        plugin_event.reply(format_seating_table(data, groupid))
        return
    game_started = data[groupid].get("game", {}).get("type") == gamename
    if game_started:
        return
    if gamename == "你有我没有":
        start_configured_game(plugin_event, data, groupid, gamename)
        return
    send_open_game_hint(plugin_event, data, groupid, gamename)

def send_open_game_hint(plugin_event, data, groupid, gamename):
    if gamename == "数字炸弹":
        plugin_event.reply("管理员可发送：直接开始游戏（默认 1~100）\n"
                           "自定义范围：开始数字炸弹 下限 上限\n"
                           "炸后自动按原范围继续新一轮；可重新发送范围指令修改范围。")
    elif gamename == "女巫毒药":
        plugin_event.reply("请管理员发送：\n  开始女巫毒药 下限 上限\n"
                           "若未坐满/放满毒药时需要强行开始游戏，请管理员发送：直接开始游戏")
    elif gamename == "偏执狂":
        from .paranoia import start_paranoia
        plugin_event.reply(start_paranoia(data, groupid))
    elif gamename in ["两真一假", "两假一真"]:
        from .truths_lies import start_truths_lies
        plugin_event.reply(start_truths_lies(data, groupid, gamename))
    elif gamename == "国王游戏":
        from .king import start_king
        plugin_event.reply(start_king(data, groupid))
    elif gamename == "你画我猜":
        from .draw_guess import start_draw_guess
        plugin_event.reply(start_draw_guess(data, groupid))
    elif gamename == "你有我没有":
        plugin_event.reply("坐满后将自动开始；未坐满也可由管理员发送：直接开始游戏\n"
                           "管理员可发送：开启反折 / 关闭反折（默认开启）")

def format_seating_table(data, groupid):
    lines = ["游戏顺序："]
    for k, v in sorted(data[groupid].get("个人", {}).items(), key=lambda x: int(x[0])):
        lines.append(f"{k}. {v.get('name', '')}")
    return "\n".join(lines)

def send_game_manual(plugin_event, groupid):
    from .engine import build_forward_node, send_forward_text
    sections = [
        (
            "【恋综游戏插件】by反季节生物\n"
            "已支持游戏：\n"
            "[直接开始类] \n数字炸弹、你有我没有\n"
            "[投稿类]\n女巫毒药、偏执狂、你画我猜、国王游戏、两真一假、两假一真\n\n"
            "1. 本插件没有检验管理员权限，“管理员”仅指代带游戏者。\n"
            "2. 投稿类游戏：开启→入座→个人群提交题目→自动开始，或管理员直接开始游戏。\n"
            "3. 每轮超过三分钟后，机器人再接收到群内消息，会自动进入下一轮。【一直没人说话需要管理员手动跳过一下】\n"
            "4. 每日自动清空之前的游戏数据。"
        ),
        (
            "【管理指令】\n"
            "⭐晚间游戏 恋综名 人数\n（只记录入座并发送座位表，不开启玩法）\n"
            "⭐开启游戏 游戏名 [恋综名] 人数\n"
            "（不填写恋综名则在小窗发送指令，填写则在恋综相应的个人群，[]是可省略的意思不要真的加括号）\n"
            "（使用普通青果骰应该NPC不能参加游戏）\n"
            "-❗️开启游戏和晚间游戏指令二选一，不是先晚间游戏再开启游戏。"
            "⭐直接开始游戏（未坐满直接开始）\n"
            "⭐跳过（结束当前回合）\n"
            "⭐计分（查看当前分数）\n"
            "⭐查看座位 / 结束游戏"
        ),
        (
            "【通用自定义功能：计分】\n"
            "管理员可以给当前游戏添加自定义计分触发词：\n"
            "  添加计分项 指令 分数\n"
            "  删除计分项 指令\n"
            "  计分项\n"
            "  清空计分\n\n"
            "示例：\n"
            "  添加计分项 对 1\n"
            "  添加计分项 罚 -1\n\n"
            "添加后，玩家公屏只发送对应指令，就会自动加/扣分，发送“计分”查看所有人分数。"
        ),
        (
            "【以下是游戏具体规则，但不阅读直接用也可以】\n"
            "【指令都放在了机器人的回复文案中，不需要从这里复制发给嘉宾，此处仅为整理】"
        ),
        (
            "【数字炸弹】\n"
            "直接开始游戏（默认 1~100）\n"
            "开始数字炸弹 下限 上限\n（自定义范围；炸后自动按上次开始的范围继续新游戏，如需修改上下限可以重新发送该指令）\n"
            "【女巫毒药】（玩家自己设定炸弹数字及惩罚的数字炸弹）\n"
            "开始女巫毒药 下限 上限\n"
            "玩家私聊/个人群发送：放毒 数字 描述\n"
            "放毒结束后自动开始，也可提前发送：直接开始游戏\n\n"
            "炸后都从下一位玩家继续游戏。"
        ),
        (
            "【偏执狂】\n"
            "开启游戏后，玩家私聊/个人群发送：偏执狂 问题内容\n"
            "每轮玩家公屏回答后，想看题的其他玩家三分钟内发送：喝\n\n"
            "【你画我猜】\n"
            "开启游戏后，玩家提前私聊/个人群发送：你画我猜 答案\n"
            "每轮玩家自行发送画作，其他人发送答案抢答，第一个答对的人 +1 分。\n\n"
            "【国王游戏】\n"
            "开启游戏后，玩家私聊/个人群发送：国王游戏 题目内容\n"
            "每轮机器人发送题目和所有玩家的随机排序列表。\n"
            "特殊指令：查看顺序\n本游戏不计分。"
        ),
        (
            "【你有我没有】\n"
            "管理员指令：开启反折/关闭反折（默认开启）\n"
            "坐满后自动开始游戏，本轮玩家发言，其他人发送：折 / 不折\n"
            "补历史未选轮次：补折 轮数 折/不折（已操作过不能事后修改）\n"
            "初始分数为开启游戏时的入座人数。\n"
            "折：-1 分，不折：不扣分\n"
            "开启反折后，如其他玩家本轮全部折或全部不折，出题人 -1 分。"
        ),
        (
            "【两真一假/两假一真】\n"
            "管理员指令：开启出题人加分/关闭出题人加分（默认关闭）\n"
            "开启游戏后，玩家私聊/个人群发送：\n"
            "两真一假/两假一真\n"
            "1.\n"
            "2.\n"
            "3.\n"
            "答案：1/2/3\n\n"
            "每轮机器人公屏发题，其他玩家直接发送 1 / 2 / 3。\n"
            "猜对者 +1 分；开启出题人加分后，猜错人数会给出题人加分。"
        ),
        
        
    ]
    send_forward_text(
        plugin_event,
        groupid,
        0,
        [build_forward_node(" ", plugin_event.bot_info.id, text) for text in sections]
    )

def start_configured_game(plugin_event, data, groupid, gamename):
    seated = [
        player
        for player in data[groupid].get("个人", {}).values()
        if player.get("uid")
    ]
    if not seated:
        plugin_event.reply("还没有玩家入座，不能开始游戏。")
        return
    if gamename == "你有我没有" and len(seated) < 2:
        plugin_event.reply("你有我没有至少需要2名玩家入座。")
        return
    if gamename == "你有我没有":
        from .never_have_i import start_never_have_i
        plugin_event.reply(start_never_have_i(data, groupid))
    elif gamename in ["两真一假", "两假一真"]:
        from .truths_lies import start_truths_lies
        plugin_event.reply(start_truths_lies(data, groupid, gamename))
    elif gamename == "国王游戏":
        from .king import start_king
        plugin_event.reply(start_king(data, groupid))
    elif gamename == "你画我猜":
        from .draw_guess import start_draw_guess
        plugin_event.reply(start_draw_guess(data, groupid))

def check_round_timeout(plugin_event, data, groupid, game_type):
    if game_type == "偏执狂":
        from .paranoia import check_timeout
        return check_timeout(plugin_event, data, groupid)
    if game_type == "你有我没有":
        from .never_have_i import check_timeout
        return check_timeout(plugin_event, data, groupid)
    if game_type in ["两真一假", "两假一真"]:
        from .truths_lies import check_timeout
        return check_timeout(plugin_event, data, groupid)
    if game_type == "国王游戏":
        from .king import check_timeout
        return check_timeout(plugin_event, data, groupid)
    if game_type == "你画我猜":
        from .draw_guess import check_timeout
        return check_timeout(plugin_event, data, groupid)
    return False

def getData(filename):
    path = "./plugin/data/game/"
    if not os.path.exists(path):
        os.makedirs(path)
    with gamelock:
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

def get_daily_game_data():
    data = getData("game.json")
    meta = getData("game_meta.json")
    today = datetime.now().strftime("%Y-%m-%d")
    saved_date = meta.get("date")

    if saved_date != today:
        if saved_date and data:
            data = {}
            setData("game.json", data)
        meta["date"] = today
        setData("game_meta.json", meta)

    return data


def setData(filename, data):
    path = "./plugin/data/game/"
    with gamelock:
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                check = json.load(f)
            shutil.copy(path + filename, path + filename + ".bak")
        except:
            pass
        with open(path + filename, "w", encoding="utf-8") as w:
            json.dump(data, w, indent=4, ensure_ascii=False)

def getGroup(filename):
    path = "./plugin/data/groupcollection/"
    with gamelock:
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

last_notice = 0
def maybe_notice():
    global last_notice
    if time.time() - last_notice > 15:
        last_notice = time.time()
        return True
    return False
