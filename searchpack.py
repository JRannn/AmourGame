#  coding=UTF-8
#
# _     /)---(\
# \\   (/ . . \)
#  \\__)-\(*)/
#  \_       (_
#  (___/-(____)
#
# 「技术支持」探丸借客@临皋闲人@白羽
import shutil
import OlivOS
import OlivaDiceCore
from .reconnoiter import reconnoiterlock
import json
import re
import os
from datetime import datetime
import threading

searchpacklock = threading.Lock()


def reply(plugin_event, Proc):
    message = plugin_event.data.message
    groupid = str(plugin_event.data.group_id)
    uid = str(plugin_event.data.user_id)
    bot_id = str(plugin_event.bot_info.id)
    sender = plugin_event.data.sender["name"]
    platfrom = plugin_event.platform["platform"]
    tmp_botHash = plugin_event.bot_info.hash
    masterlist = getMaster(tmp_botHash, platfrom)

    if message.startswith("设置searchpack标题"):
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可设置")
            return
        title = message[len("设置searchpack标题") :].strip()
        if not title:
            return plugin_event.reply("请输入内容噢！\n\n如：设置searchpack标题 恋综名")
        playname_data = getData("playname.json")
        if not isinstance(playname_data, dict):
            playname_data = {"title": ""}
        playname_data["title"] = title
        setData("playname.json", playname_data)
        return plugin_event.reply(f"标题已设置为：{title}")

    if re.match(r"\[OP:at,id=(\d+)\]\s*确认拾取(.+)$", message):
        pickup_match = re.match(r"\[OP:at,id=(\d+)\]\s*确认拾取(.+)$", message)
        if pickup_match:
            at_id = pickup_match[1]
            if at_id != bot_id:
                return
            item_name = pickup_match.group(2).strip()
            pending_pickups = getData("pending_pickups.json")
            if uid not in pending_pickups or item_name not in pending_pickups[uid]:
                plugin_event.reply("没有找到待拾取的物品，请先调查地点噢！")
                return
            item_info = pending_pickups[uid][item_name]
            packdata = getPackData("backpack.json")
            if uid not in packdata:
                packdata[uid] = {}
            if item_name in packdata[uid]:
                packdata[uid][item_name][0] += 1
            else:
                packdata[uid][item_name] = [1, item_info["description"]]
            setPackData("backpack.json", packdata)
            if not item_info.get("special"):
                alladrdata = getData("adrdata.json")
                adr_path = item_info["adr_path"]
                group_id = item_info["group_id"]
                current_level = alladrdata
                for loc in adr_path[:-1]:
                    if loc in current_level:
                        current_level = current_level[loc]
                    else:
                        break
                if adr_path[-1] in current_level:
                    current_level[adr_path[-1]]["物品"] = "空"
                setData("adrdata.json", alladrdata)
            del pending_pickups[uid][item_name]
            if not pending_pickups[uid]:
                del pending_pickups[uid]
            setData("pending_pickups.json", pending_pickups)
            plugin_event.reply(
                f"<{item_name}>已经放入背包啦！\n\n"
                f"物品简介：{item_info['description']}"
            )

    if re.match(r"\[OP:at,id=(\d+)\]\s*(前往.+)$", message):
        at_match = re.match(r"\[OP:at,id=(\d+)\]\s*(前往.+)$", message)
        if at_match:
            at_id = at_match[1]
            if at_id != bot_id:
                return
            command = at_match[2].strip()
            if command.startswith("前往"):
                adr = command.replace("前往", "").strip()
                adrdata = getData("adrdata.json")
                nowadr = getData("nowadr.json")
                adr = adr.replace(" ", "")
                adrl = adr.split("-")
                if groupid in nowadr:
                    if nowadr[groupid] == adrl:
                        reply = "当前已经在" + adr + "了"
                        plugin_event.reply(reply)
                        return
                nowadrl = []
                if groupid in nowadr:
                    outcome = adrcheck(nowadr[groupid], adrdata, nowadrl)
                    adrdata = outcome[1]
                    nowadrl = outcome[2]
                outcome = adrcheck(adrl, adrdata, nowadrl)
                if outcome[0]:
                    adrdata = outcome[1]
                    if "物品" in adrdata:
                        reply = "该地区无须前往，请直接调查"
                        plugin_event.reply(reply)
                        return
                    if "介绍" in adrdata:
                        reply = adrdata["介绍"]
                        if len(adrdata.keys()) != 1:
                            nowadr[groupid] = outcome[2]
                            setData("nowadr.json", nowadr)
                        else:
                            reply += (
                                "\n\n（该地点无法调查，请使用前往指令前往其他地点）"
                            )
                        plugin_event.reply(reply)
                        return
                    else:
                        nowadr[groupid] = outcome[2]
                        setData("nowadr.json", nowadr)
                        reply = outcome[2][-1] + "：\n"
                        for i in outcome[1]:
                            reply += i + "、"
                        reply = (
                            reply.rstrip("、") + "\n\n请继续发送“@骰子 前往对应地点”"
                        )
                        plugin_event.reply(reply)
                else:
                    if len(outcome[2]) == 0:
                        reply = outcome[1] + "不存在"
                        plugin_event.reply(str(reply))
                    else:
                        reply = outcome[2][-1] + "没有" + outcome[1]
                        plugin_event.reply(str(reply))

    if re.match(r"\[OP:at,id=(\d+)\]\s*踩点位置重置$", message):
        reset_match = re.match(r"\[OP:at,id=(\d+)\]\s*踩点位置重置$", message)
        if reset_match:
            at_id = reset_match[1]
            if at_id != bot_id:
                return
            nowadr = getData("nowadr.json")
            if groupid not in nowadr:
                reply = "当前群无位置信息"
                plugin_event.reply(reply)
                return
            else:
                del nowadr[groupid]
                setData("nowadr.json", nowadr)
                reply = "位置重置成功，请使用前往指令重新设置位置"
                plugin_event.reply(reply)
    else:
        nowadr = getData("nowadr.json")
        if groupid in nowadr:
            alladrdata = getData("adrdata.json")
            packdata = getPackData("backpack.json")
            nowadrl = []
            outcome = adrcheck(nowadr[groupid], alladrdata, nowadrl)
            adrdata = outcome[1]
            nowadrl = outcome[2]
            adrl = list(adrdata.keys())
            adrl = sorted(adrl, key=lambda x: len(x), reverse=True)
            adr = ""
            for i in adrl:
                if i in message and i != "介绍":
                    adr = i
                    break
            if adr == "":
                return
            if "物品" not in adrdata[adr]:
                reply = "该地点无法直接调查，请前往该地点后再进行调查噢！"
                plugin_event.reply(reply)
                return
            if adrdata[adr]["物品"] == "空":
                reply = "该点位没有东西了噢！可继续调查本地点其他点位！"
                plugin_event.reply(reply)
                return
            if adrdata[adr]["物品"] == "文本":
                reply = adrdata[adr]["介绍"]
                plugin_event.reply(reply)
                return
            playname_data = getData("playname.json")
            if (
                not playname_data
                or not isinstance(playname_data, dict)
                or not playname_data.get("title")
            ):
                plugin_event.reply("当前没有进行中的恋综，无法拾取物品噢！")
                return

            permission_group_name = playname_data["title"]
            privategroup = getGroup("privategroup.json")

            # 适配新格式：直接检查恋综标题下是否存在该用户ID
            if not (
                permission_group_name in privategroup
                and uid in privategroup[permission_group_name]
            ):
                plugin_event.reply(f"{sender}未参与本场恋综，无法拾取物品")
                return

            # 获取玩家个人群号（新格式中直接存放于用户对象下）
            group_id = privategroup[permission_group_name][uid].get("个人群号")
            if not group_id:
                plugin_event.reply(f"未找到{sender}的个人群信息，请先录入个人群")
                return

            # 将物品添加到待拾取列表
            item_name = adrdata[adr]["物品"]
            pending_pickups = getData("pending_pickups.json")
            if uid not in pending_pickups:
                pending_pickups[uid] = {}

            # 存储物品信息
            pending_pickups[uid][item_name] = {
                "description": adrdata[adr]["介绍"],
                "adr_path": nowadrl + [adr],
                "special": adrdata[adr].get("特殊"),
                "group_id": groupid,
            }
            setData("pending_pickups.json", pending_pickups)
            plugin_event.send(
                "group",
                group_id,
                f"你在{adr}发现了<{item_name}>！\n"
                f"请ra对应的数值，若ra成功\n\n回复<@骰子 确认拾取{item_name}>带走噢！",
            )


def getGroup(filename):
    path = "./plugin/data/amourgame/groupcollection/"
    with searchpacklock:
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


def getData(filename):
    path = "./plugin/data/searchpack/"
    if not os.path.exists(path):
        os.makedirs(path)
    with searchpacklock:
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            try:
                with open(path + filename + ".bak", "r", encoding="utf-8") as f:
                    data = json.load(f)
                    shutil.copy(path + filename + ".bak", path + filename)
            except Exception:
                with open(path + filename, "w", encoding="utf-8") as f:
                    pass
        with open(path + filename, "r", encoding="utf-8") as f:
            file = f.read()
            return json.loads(file) if file else {}


def setData(filename, data):
    path = "./plugin/data/searchpack/"
    with searchpacklock:
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                json.load(f)
            shutil.copy(path + filename, path + filename + ".bak")
        except Exception:
            pass
        with open(path + filename, "w", encoding="utf-8") as w:
            json.dump(data, w, indent=4, ensure_ascii=False)


def getPackData(filename):
    path = "./plugin/data/reconnoiter/"
    with reconnoiterlock:
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


def setPackData(filename, data):
    path = "./plugin/data/reconnoiter/"
    with reconnoiterlock:
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                check = json.load(f)
                shutil.copy(path + filename, path + filename + ".bak")
        except:
            pass
        with open(path + filename, "w", encoding="utf-8") as w:
            json.dump(data, w, indent=4, ensure_ascii=False)


def adrcheck(adrl, adrdata, nowadrl):
    if len(adrl) == 0:
        return [True, adrdata, nowadrl]
    newl = adrl.pop(0)
    if newl not in adrdata:
        return [False, newl, nowadrl]
    nowadrl.append(newl)
    return adrcheck(adrl, adrdata[newl], nowadrl)


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
