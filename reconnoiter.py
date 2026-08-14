#  coding=UTF-8
#
# _     /)---(\
# \\   (/ . . \)
#  \\__)-\(*)/
#  \_       (_
#  (___/-(____)
#
# 「技术支持」探丸借客@临皋闲人@白羽

import random
import shutil
import OlivOS
import OlivaDiceCore
import json
import re
import os
import time
from datetime import datetime
import multiprocessing

caidian = "机缘将至！"  # 踩点的指令名，修改记得重载
qiyu = "运势显现！"  # 触发奇遇的指令名，修改记得重载
admin_list = [
    "3149790940",
    "3044509570",
]  # 除骰主外的本插件管理员qq号列表，按格式填写，修改记得重载
reconnoiterlock = multiprocessing.Lock()
reconnoiter_switch = 0


def init_after(plugin_event, Proc):
    global reconnoiter_switch
    backpack = getData("backpack.json")
    reconnoiter_switch = int(backpack.get("_global_switch", 0) or 0)


def set_global_switch(value):
    backpack = getData("backpack.json")
    backpack["_global_switch"] = int(value)
    setData("backpack.json", backpack)


def reply(plugin_event, Proc):
    message = plugin_event.data.message
    groupid = str(plugin_event.data.group_id)
    uid = str(plugin_event.data.user_id)
    pcname = getPcName(uid, "qq", groupid, plugin_event.data.sender["name"])
    platfrom = plugin_event.platform["platform"]
    tmp_botHash = plugin_event.bot_info.hash
    masterlist = getMaster(tmp_botHash, platfrom)
    global reconnoiter_switch
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             骰主功能开关             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    if message == "开启背包插件":
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("该指令仅限骰主或本插件管理员使用")
            return
        if reconnoiter_switch == 0:
            reconnoiter_switch = 1
            plugin_event.reply("背包插件启用成功")
        else:
            plugin_event.reply("背包插件已开启，无需重复开启")
        set_global_switch(reconnoiter_switch)
        return
    elif message == "关闭背包插件":
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("该指令仅限骰主或本插件管理员使用")
            return
        if reconnoiter_switch == 1:
            reconnoiter_switch = 0
            plugin_event.reply("背包插件关闭成功")
        else:
            plugin_event.reply("背包插件未开启，无需关闭")
        set_global_switch(reconnoiter_switch)
        return
    if reconnoiter_switch == 0:
        return
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             背包功能细则             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    if message.startswith("背包命名"):
        packname = re.match(r"背包命名\s*(.*)的背包", message)
        if not packname:
            plugin_event.reply("指令正确格式：\n背包命名 xxx的背包")
            return
        backpack = getData("backpack.json")
        if uid not in backpack:
            backpack[uid] = {}
        for u, d in backpack.items():
            if "背包的名字" in d:
                if u != uid and d["背包的名字"] == packname.group(1) + "的背包":
                    plugin_event.reply("该背包名已被占用，请重新命名")
                    return
        backpack[uid]["背包的名字"] = packname.group(1) + "的背包"
        setData("backpack.json", backpack)
        plugin_event.reply("背包命名成功！")
    if message == "打开背包":
        backpack = getData("backpack.json")
        pcname = getPcName(uid, "qq", groupid, plugin_event.data.sender["name"])
        if uid not in backpack:
            backpack[uid] = {}
        if "背包的名字" not in backpack[uid]:
            backpack[uid]["背包的名字"] = pcname + "的背包"
        rep = backpack[uid]["背包的名字"] + "\n"
        for k, v in backpack[uid].items():
            if k == "背包的名字":
                continue
            rep += k + "   " + str(v[0]) + "\n"
        encipher = getData("encipher.json")
        if uid not in encipher:
            encipher[uid] = []
        rep += "【加密区】:"
        if len(encipher[uid]) == 0:
            rep += "空"
        else:
            rep += encipher[uid][0]
        wearing = getData("wearing.json")
        rep += "\n【当前穿戴】:"
        if uid not in wearing:
            wearing[uid] = []
        if len(wearing[uid]) == 0:
            rep += "空"
        else:
            rep += wearing[uid][0]
        plugin_event.reply(rep.strip() + "\n\n物品简介指令「物品图鉴 物品名」")
    if message.startswith("物品图鉴"):
        goods = re.match(r"物品图鉴\s*(.*)", message)
        goods = goods.group(1).strip()
        if not goods:
            return
        backpack = getData("backpack.json")
        pcname = getPcName(uid, "qq", groupid, plugin_event.data.sender["name"])
        rep = ""
        if uid not in backpack:
            backpack[uid] = {}
        for k, v in backpack[uid].items():
            if k == "背包的名字":
                continue
            if goods == k:
                rep += k + "：" + str(v[1])
                plugin_event.reply(rep)
                return
        encipher = getData("encipher.json")
        if uid in encipher:
            if len(encipher[uid]) == 2:
                if goods == encipher[uid][0]:
                    rep += goods + "：" + str(encipher[uid][1])
                    plugin_event.reply(rep)
                    return
        wearing = getData("wearing.json")
        if uid in wearing:
            if len(wearing[uid]) == 2:
                if goods == wearing[uid][0]:
                    rep += goods + "：" + str(wearing[uid][1])
                    plugin_event.reply(rep)
                    return
        rep = "你没有该物品噢！"
        plugin_event.reply(rep)
        return

    if message.startswith("背包赠送"):
        if "的背包" not in message:
            plugin_event.reply(
                "缺少要赠送的人的背包名噢！\n\n指令正确格式：\n背包赠送+物品1+空格+数量+空格+物品2+空格+数量+空格+物品3+空格+数量+...+空格+xxx的背包\n\n如：\n背包赠送 苹果 1 香蕉 2 临皋闲人的背包"
            )
            return
        backpack = getData("backpack.json")
        backpack_log = getData("backpack_log.json")
        if uid not in backpack:
            backpack[uid] = {}
        tmpstr = re.match(r"背包赠送\s*((.+)\s+(\d+))\s+(.+)的背包", message)
        if not tmpstr:
            plugin_event.reply(
                "指令正确格式：\n背包赠送+物品1+空格+数量+空格+物品2+空格+数量+...+空格+xxx的背包\n\n如：\n背包赠送 苹果 1 香蕉 2 临皋闲人的背包"
            )
            return
        tmpstr2 = re.findall(r"([\d\D]+?)\s+(\d+)", tmpstr.group(1))
        tmpstr2 = [(x[0].strip(), x[1]) for x in tmpstr2]
        target = "0"
        target_name = ""
        for u, d in backpack.items():
            if "背包的名字" in d:
                if d["背包的名字"] == tmpstr.group(4) + "的背包":
                    if u == uid:
                        plugin_event.reply("不可以赠送给自己噢！")
                        return
                    target = u
                    target_name = tmpstr.group(4)
                    break
        if target == "0":
            plugin_event.reply("没有找到该背包！")
            return
        sender_name = "未知用户"
        if uid in backpack and "背包的名字" in backpack[uid]:
            match = re.match(r"(.+)的背包", backpack[uid]["背包的名字"])
            if match:
                sender_name = match.group(1)
        sends = ""
        sendf_u = ""
        snedf_n = ""
        sent_items = []
        for tmpstr3 in tmpstr2:
            if tmpstr3[0] in backpack[uid] and tmpstr3[0] != "背包的名字":
                if backpack[uid][tmpstr3[0]][0] >= int(tmpstr3[1]):
                    backpack[uid][tmpstr3[0]][0] -= int(tmpstr3[1])
                    text = backpack[uid][tmpstr3[0]][1]
                    if backpack[uid][tmpstr3[0]][0] == 0:
                        del backpack[uid][tmpstr3[0]]
                    if target not in backpack:
                        backpack[target] = {}
                    if tmpstr3[0] not in backpack[target]:
                        backpack[target][tmpstr3[0]] = [0, text]
                    backpack[target][tmpstr3[0]][0] += int(tmpstr3[1])
                    sends += tmpstr3[0] + "*" + tmpstr3[1]
                    sent_items.append(f"{tmpstr3[0]}*{tmpstr3[1]}")
                else:
                    sendf_u += tmpstr3[0] + " "
            else:
                snedf_n += tmpstr3[0] + " "
        if sent_items:
            nowtime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_key = f"{nowtime}〖{sender_name}〗赠送给〖{target_name}〗{' '.join(sent_items)}"
            backpack_log[log_key] = "成功"
            setData("backpack_log.json", backpack_log)
        setData("backpack.json", backpack)
        rep = ""
        if sends != "":
            rep += sends + "赠送成功！\n"
        if sendf_u != "":
            rep += sendf_u.strip() + "赠送失败，数量不足噢！\n"
        if snedf_n != "":
            rep += snedf_n.strip() + "赠送失败，你的背包里没有这些物品噢！\n"
        plugin_event.reply(rep.strip())
        if sends != "":
            plugin_event.send(
                "private", target, "你收到了来自" + pcname + "赠送的" + sends
            )

    if message.startswith("背包偷窃"):
        if "的背包" not in message:
            plugin_event.reply(
                "请指定你的目标噢！\n\n指令正确格式：\n背包偷窃 xxx的背包"
            )
            return
        backpack = getData("backpack.json")
        backpack_log = getData("backpack_log.json")
        targettmp = re.match(r"背包偷窃\s*(.+的背包)", message).group(1)
        target = ""
        target_name = ""
        for u, d in backpack.items():
            if "背包的名字" in d:
                if d["背包的名字"] == targettmp:
                    target = u
                    target_name = re.match(r"(.+)的背包", d["背包的名字"]).group(1)
                    break
        if target == "":
            plugin_event.reply("没有找到该背包！")
            return
        if target == str(plugin_event.data.user_id):
            plugin_event.reply("不能偷自己的背包噢！")
            return
        if len(list(backpack[target])) <= 1 or (
            "背包的名字" in backpack[target] and len(list(backpack[target])) == 1
        ):
            plugin_event.reply("你什么都没偷到噢！")
            return
        thief_name = "未知用户"
        if uid in backpack and "背包的名字" in backpack[uid]:
            match = re.match(r"(.+)的背包", backpack[uid]["背包的名字"])
            if match:
                thief_name = match.group(1)
        goods = []
        for good in backpack[target]:
            if good != "背包的名字":
                goods += [good] * backpack[target][good][0]
        random.shuffle(goods)
        random_good = random.choice(goods)
        if uid not in backpack:
            backpack[uid] = {}
        if random_good not in backpack[uid]:
            backpack[uid][random_good] = [0, backpack[target][random_good][1]]
        backpack[uid][random_good][0] += 1
        plugin_event.reply("你偷到了一个" + random_good)
        backpack[target][random_good][0] -= 1
        if backpack[target][random_good][0] == 0:
            del backpack[target][random_good]
        nowtime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_key = f"{nowtime}〖{target_name}〗被〖{thief_name}〗偷走了{random_good}*1"
        backpack_log[log_key] = "成功"
        setData("backpack_log.json", backpack_log)
        setData("backpack.json", backpack)
        plugin_event.send("private", target, "你被偷走了1个" + random_good)

    if message.endswith("背包日志") or message.endswith(" 背包日志"):
        date_str = (
            message.split(" ")[0].strip() if " " in message else message[:6].strip()
        )
        if not re.match(r"^\d{6}$", date_str):
            plugin_event.reply("查看背包日志格式：\n\n240101 背包日志")
            return
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("权限不足，仅骰主或本插件管理员可查询")
            return
        backpack_log = getData("backpack_log.json")
        year = "20" + date_str[:2]
        month = date_str[2:4]
        day = date_str[4:6]
        filtered_logs = []
        for log_key, log_value in backpack_log.items():
            log_date = log_key.split(" ")[0]
            if log_date == f"{year}-{month}-{day}":
                filtered_logs.append(f"{log_key} {log_value}")
        if filtered_logs:
            response = "\n".join(filtered_logs)
        else:
            response = f"没有找到{year}年{month}月{day}日的背包日志或日志为空噢！"
        plugin_event.reply(response)

    if message == "清空所有背包日志数据":
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("只有骰主或本插件管理员才能使用该命令")
            return
        setData("backpack_log.json", {})
        plugin_event.reply("所有背包赠送、偷窃日志数据已清空！")

    if message.startswith("背包使用"):
        backpack = getData("backpack.json")
        tmpstr = re.match(r"背包使用\s*((.+)\s+(\d+))", message)
        if not tmpstr:
            plugin_event.reply(
                "指令正确格式：\n背包使用+物品1+空格+数量+空格+物品2+空格+数量+...\n\n如：\n背包使用 苹果 1 香蕉 2"
            )
            return
        if uid not in backpack:
            backpack[uid] = {}
        tmpstr2 = re.findall(r"([\d\D]+?)\s+(\d+)", tmpstr.group(1))
        tmpstr2 = [(x[0].strip(), x[1]) for x in tmpstr2]
        uses = ""
        usef_u = ""
        usef_n = ""
        for tmpstr3 in tmpstr2:
            if tmpstr3[0] in backpack[uid] and tmpstr3[0] != "背包的名字":
                if backpack[uid][tmpstr3[0]][0] >= int(tmpstr3[1]):
                    backpack[uid][tmpstr3[0]][0] -= int(tmpstr3[1])
                    if backpack[uid][tmpstr3[0]][0] == 0:
                        del backpack[uid][tmpstr3[0]]
                    uses += tmpstr3[0] + "*" + tmpstr3[1]
                else:
                    usef_u += tmpstr3[0] + " "
            else:
                usef_n += tmpstr3[0] + " "
        setData("backpack.json", backpack)
        rep = ""
        if uses != "":
            rep += uses + "使用成功！\n"
        if usef_u != "":
            rep += usef_u.strip() + "使用失败，数量不足噢！\n"
        if usef_n != "":
            rep += usef_n.strip() + "使用失败，你的背包里没有这些物品噢！\n"
        plugin_event.reply(rep.strip())

    if message.startswith("背包放入"):
        backpack = getData("backpack.json")
        if uid not in backpack:
            backpack[uid] = {}
        goods = re.sub(r"背包放入\s*", "", message)
        if goods == "" or len(re.findall(r"(.+)\s+(\d+)", goods)) == 0:
            plugin_event.reply(
                "指令正确格式：\n背包放入+物品1+空格+数量+空格+物品2+空格+数量+...\n\n如：\n背包放入 苹果 1 香蕉 2"
            )
            return
        goodslist = re.findall(r"([\d\D]+?)\s+(\d+)", goods)
        goodslist = [(x[0].strip(), x[1]) for x in goodslist]
        stash = getData("stash.json")
        rep = "成功放入"
        for goods in goodslist:
            if goods[0] not in backpack[uid]:
                if goods[0] in stash:
                    backpack[uid][goods[0]] = [0, stash[goods[0]][0]]
                else:
                    backpack[uid][goods[0]] = [0, "暂无简介"]
            backpack[uid][goods[0]][0] += int(goods[1])
            rep += goods[0] + "*" + goods[1]
        setData("backpack.json", backpack)
        plugin_event.reply(rep)

    if message.startswith("背包穿戴"):
        backpack = getData("backpack.json")
        if uid not in backpack:
            backpack[uid] = {}
        tmpstr = re.match(r"背包穿戴\s*(.+)", message)
        if not tmpstr:
            plugin_event.reply(
                "指令正确格式：\n背包穿戴 道具名称\n\n仅可穿戴一件道具，如需更换，重发指令即可\n道具被穿戴时，无法被使用、偷窃、赠送"
            )
            return
        if tmpstr.group(1) in backpack[uid] and tmpstr.group(1) != "背包的名字":
            wearing = getData("wearing.json")
            if uid not in wearing:
                wearing[uid] = []
            if tmpstr.group(1) in wearing[uid]:
                plugin_event.reply("你已穿戴" + tmpstr.group(1) + "，无需更换")
                return
            if len(wearing[uid]) == 0:
                wearing[uid].append(tmpstr.group(1))
                wearing[uid].append(backpack[uid][tmpstr.group(1)][1])
            else:
                if wearing[uid][0] not in backpack[uid]:
                    backpack[uid][wearing[uid][0]] = [0, "暂无简介"]
                backpack[uid][wearing[uid][0]][0] += 1
                backpack[uid][wearing[uid][0]][1] = wearing[uid][1]
                wearing[uid][0] = tmpstr.group(1)
                wearing[uid][1] = backpack[uid][tmpstr.group(1)][1]
            backpack[uid][tmpstr.group(1)][0] -= 1
            if backpack[uid][tmpstr.group(1)][0] == 0:
                del backpack[uid][tmpstr.group(1)]
            setData("backpack.json", backpack)
            setData("wearing.json", wearing)
            plugin_event.reply("穿戴" + tmpstr.group(1) + "成功！")
        else:
            plugin_event.reply("你的背包中没有" + tmpstr.group(1) + "！")

    if message.startswith("背包加密"):
        backpack = getData("backpack.json")
        if uid not in backpack:
            backpack[uid] = {}
        tmpstr = re.match(r"背包加密\s*(.+)", message)
        if not tmpstr:
            plugin_event.reply(
                "指令正确格式：\n背包加密 道具名称\n\n仅可加密一件道具，如需更换，重发指令即可\n道具被加密时，无法被使用、偷窃、赠送"
            )
            return
        if tmpstr.group(1) in backpack[uid] and tmpstr.group(1) != "背包的名字":
            encipher = getData("encipher.json")
            if uid not in encipher:
                encipher[uid] = []
            if tmpstr.group(1) in encipher[uid]:
                plugin_event.reply("你已加密" + tmpstr.group(1) + "，无需更换")
                return
            if len(encipher[uid]) == 0:
                encipher[uid].append(tmpstr.group(1))
                encipher[uid].append(backpack[uid][tmpstr.group(1)][1])
            else:
                if encipher[uid][0] not in backpack[uid]:
                    backpack[uid][encipher[uid][0]] = [0, "暂无简介"]
                backpack[uid][encipher[uid][0]][0] += 1
                backpack[uid][encipher[uid][0]][1] = encipher[uid][1]
                encipher[uid][0] = tmpstr.group(1)
                encipher[uid][1] = backpack[uid][tmpstr.group(1)][1]
            backpack[uid][tmpstr.group(1)][0] -= 1
            if backpack[uid][tmpstr.group(1)][0] == 0:
                del backpack[uid][tmpstr.group(1)]
            setData("backpack.json", backpack)
            setData("encipher.json", encipher)
            plugin_event.reply("加密" + tmpstr.group(1) + "成功！")
        else:
            plugin_event.reply("你的背包中没有" + tmpstr.group(1) + "！")

    if message.startswith("背包清空"):
        backpack = getData("backpack.json")
        wearing = getData("wearing.json")
        encipher = getData("encipher.json")
        if uid not in backpack:
            backpack[uid] = {}
        checkid = re.match(r"背包清空\s*(\d+)", message)
        if not checkid:
            plugin_event.reply("为防止误操作，指令正确格式：\n背包清空 你的QQ号码")
            return
        if checkid.group(1) != uid:
            plugin_event.reply("输入的QQ号码不是你的QQ号码，请重新输入噢！")
            return
        backpack[uid] = {k: v for k, v in backpack[uid].items() if k == "背包的名字"}
        if uid in wearing:
            wearing[uid] = []
        if uid in encipher:
            encipher[uid] = []
        setData("backpack.json", backpack)
        setData("wearing.json", wearing)
        setData("encipher.json", encipher)
        plugin_event.reply("背包已清空！")
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             踩点功能细则             │
    # │             奇遇功能细则             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    if message == caidian:
        backpack = getData("backpack.json")
        if uid not in backpack:
            backpack[uid] = {}
        stash = getData("stash.json")
        goodslist = []
        for goods in stash:
            goodslist += [goods] * stash[goods][1]
        if len(goodslist) == 0:
            plugin_event.reply("没有可以踩点的物品或骰主未配置！")
            return
        goods = random.choice(goodslist)
        if goods not in backpack[uid]:
            backpack[uid][goods] = [0, stash[goods][0]]
        backpack[uid][goods][0] += 1
        stash[goods][1] -= 1
        setData("stash.json", stash)
        setData("backpack.json", backpack)
        description = stash[goods][0]
        # 私聊
        # plugin_event.reply("（俯身查看）（伸手探向隐蔽处）（停顿片刻）（小心取出）发现了……！")
        # plugin_event.send("private", uid, "你获得了一个"+goods+"，请使用物品图鉴查看简介！")
        # 公屏
        plugin_event.reply(f"你获得了一个【{goods}】！\n\n物品简介：{description}")
    if message == qiyu:
        quest = getData("quest.json")
        goods_types = list(quest.keys())
        if len(goods_types) == 0:
            plugin_event.reply("没有可以触发的奇遇或骰主未配置！")
            return
        chosen_goods_type = random.choice(goods_types)
        goods = chosen_goods_type
        description = quest[goods][0]
        # 私聊
        # plugin_event.reply("（察觉到异样气息）（凝神感悟）……奇遇降临！")
        # plugin_event.send("private", uid, "恭喜触发奇遇【{goods}】！\n\n{description}")
        # 公屏
        plugin_event.reply(f"恭喜触发奇遇【{goods}】！\n\n{description}")
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             仓库功能细则             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    if message.startswith("仓库添加"):
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("该指令仅限骰主或本插件管理员使用")
            return
        stash = getData("stash.json")
        tmpstr = re.match(r"仓库添加\s*(.+)", message)
        if not tmpstr:
            plugin_event.reply("仓库添加+【物品名称】+简介+空格+数量")
            return
        tmpstr = re.match(r"【(.+)】\s*(.+)\s+(\d+)", tmpstr.group(1))
        if not tmpstr:
            plugin_event.reply("仓库添加+【物品名称】+简介+空格+数量")
            return
        name = tmpstr.group(1)
        info = tmpstr.group(2)
        num = int(tmpstr.group(3))
        if name not in stash:
            stash[name] = [info, num]
        else:
            stash[name][1] += num
        setData("stash.json", stash)
        plugin_event.reply("添加成功！")
    if message.startswith("仓库移除"):
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("该指令仅限骰主或本插件管理员使用")
            return
        stash = getData("stash.json")
        tmpstr = re.match(r"仓库移除\s*(.+)", message)
        if not tmpstr:
            plugin_event.reply("仓库移除+物品名称+空格+数量")
            return
        tmpstr = re.match(r"(\w+)\s+(\d+)", tmpstr.group(1))
        if not tmpstr:
            plugin_event.reply("仓库移除+物品名称+空格+数量")
            return
        name = tmpstr.group(1)
        num = int(tmpstr.group(2))
        if name not in stash:
            plugin_event.reply("仓库中没有" + name + "！")
            return
        else:
            stash[name][1] -= num
            if stash[name][1] <= 0:
                del stash[name]
        setData("stash.json", stash)
        plugin_event.reply("移除成功！")
    if message == "仓库查看":
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("该指令仅限骰主或本插件管理员使用")
            return
        stash = getData("stash.json")
        rep = "仓库中物品如下：\n"
        for goods in stash:
            rep += (
                "【"
                + goods
                + "】"
                + stash[goods][0]
                + " "
                + str(stash[goods][1])
                + "\n"
            )
        plugin_event.reply(rep.strip())
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             商店功能细则             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    if message == "查看背包商店":
        store_data = getData("store.json")
        store_list = []
        for item, details in store_data.get("items", {}).items():
            stock = details.get("current_stock", 0)  # 实时库存
            initial_stock = details.get("stock", 0)  # 初始库存
            if stock != 0:
                store_list.append(f"{item} {stock}/{initial_stock}")
        formatted = []
        for i in range(0, len(store_list), 2):
            formatted.append("，".join(store_list[i : i + 2]))
        response = "商店库存\n（售罄商品自动移除）\n\n" + (
            "\n".join(formatted) if formatted else "暂无可购买商品或骰主未配置"
        )
        plugin_event.reply(response)

    if message.startswith("背包购买"):
        backpack = getData("backpack.json")
        store_data = getData("store.json")
        store_log = getData("store_log.json")
        goods = re.sub(r"背包购买\s*", "", message)
        if not goods or len(re.findall(r"(\S+)(?:\s+(\d+))?", goods)) == 0:
            plugin_event.reply("指令正确格式：\n背包购买 物品1 数量 物品2 数量...")
            return
        # 检查背包中是否有“积分”物品
        if "积分" not in backpack.get(uid, {}):
            plugin_event.reply("你的背包中没有积分，无法购买物品噢！")
            return
        user_name = "未知用户"
        if uid in backpack and "背包的名字" in backpack[uid]:
            match = re.match(r"(.+)的背包", backpack[uid]["背包的名字"])
            if match:
                user_name = match.group(1)
        # 解析商品列表（支持多商品购买）
        goods_list = re.findall(r"(\S+)(?:\s+(\d+))?", goods)
        missing_items = []  # 不存在的商品
        out_of_stock_items = []  # 库存不足的商品
        valid_goods = []  # 有效商品清单
        purchase_details = []
        total_cost = 0
        for goods in goods_list:
            item_name = goods[0].strip()
            quantity = int(goods[1]) if goods[1] else 1
            # 检查商品是否存在
            if item_name not in store_data.get("items", {}):
                missing_items.append(item_name)
                continue
            item = store_data["items"][item_name]
            stock = item.get("stock", 0)
            current_stock = item.get("current_stock", 0)
            price = item.get("price", 0)
            if current_stock < quantity:
                out_of_stock_items.append(
                    f"{item_name}(需{quantity}/剩{current_stock})"
                )
                continue
            valid_goods.append(
                {
                    "name": item_name,
                    "quantity": quantity,
                    "price": price,
                    "item_obj": item,
                }
            )
            total_cost += price * quantity
            purchase_details.append(f"{item_name}*{quantity}")
        # 错误反馈
        error_msg = []
        if missing_items:
            error_msg.append(f"商品{'、'.join(missing_items)}不存在或骰主未配置！")
        if out_of_stock_items:
            error_msg.append(f"库存不足：\n" + "\n".join(out_of_stock_items))
        if error_msg:
            plugin_event.reply("\n\n".join(error_msg))
            return
        # 获取积分（作为物品）
        current_points = (
            backpack[uid]["积分"][0]
            if uid in backpack and "积分" in backpack[uid]
            else 0
        )
        # 检查是否有足够积分购买
        if current_points < total_cost:
            plugin_event.reply(
                f"余额不足，需要{total_cost}积分！\n\n当前：{current_points}"
            )
            return
        # 正式购买阶段
        rep = "成功购买"
        for goods in valid_goods:
            item_name = goods["name"]
            quantity = goods["quantity"]
            item = goods["item_obj"]
            # 更新商店库存中的 current_stock
            item["current_stock"] -= quantity
            if uid not in backpack:
                backpack[uid] = {}
            desc = item.get("desc", "暂无简介")  # 修改默认描述
            if item_name in backpack[uid]:
                backpack[uid][item_name][0] += quantity
            else:
                backpack[uid][item_name] = [quantity, desc]  # 添加商品描述
            rep += f"{item_name}*{quantity} "
        # 扣除积分（物品方式）
        backpack[uid]["积分"][0] -= total_cost
        # 如果积分数量为0，移除"积分"键
        if backpack[uid]["积分"][0] == 0:
            del backpack[uid]["积分"]
        setData("store.json", store_data)
        setData("backpack.json", backpack)
        nowtime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_key = f"{nowtime}〖{user_name}〗购买{' '.join(purchase_details)}"
        store_log[log_key] = "成功"
        setData("store_log.json", store_log)
        plugin_event.reply(
            f"{rep}啦！\n\n剩余积分：{backpack[uid].get('积分', [0])[0]}"
        )

    if message.startswith("背包售出"):
        backpack = getData("backpack.json")
        store_data = getData("store.json")
        store_log = getData("store_log.json")
        cmd_part = message[len("背包售出") :].strip()
        tmpstr = re.match(r"((?:.+?\s+\d+\s*)+)", cmd_part)
        if not tmpstr:
            plugin_event.reply("指令正确格式：\n背包售出 物品1 数量 物品2 数量...")
            return
        user_name = "未知用户"
        if uid in backpack and "背包的名字" in backpack[uid]:
            match = re.match(r"(.+)的背包", backpack[uid]["背包的名字"])
            if match:
                user_name = match.group(1)
        tmpstr2 = re.findall(r"(.+?)\s+(\d+)", tmpstr.group(1))
        tmpstr2 = [(x[0].strip(), x[1]) for x in tmpstr2]
        success = []  # 成功售出
        fail_store = []  # 不可回收
        fail_backpack = []  # 背包不存在
        fail_quantity = []  # 数量不足
        total_gain = 0
        for item_name, quantity_str in tmpstr2:
            quantity = int(quantity_str)
            # 验证商品是否可回收
            if item_name not in store_data.get("items", {}):
                fail_store.append(item_name)
                continue
            item = store_data["items"][item_name]
            current_stock = item.get("current_stock", 0)
            price = item.get("price", 0)
            # 验证背包中是否有该物品
            if uid not in backpack or item_name not in backpack[uid]:
                fail_backpack.append(item_name)
                continue
            # 验证数量充足
            if backpack[uid][item_name][0] < quantity:
                fail_quantity.append(item_name)
                continue
            # 计算收益
            recycle_rate = store_data.get("recycle_rate", 0.6)
            total_gain += int(price * recycle_rate * quantity)
            # 更新背包
            backpack[uid][item_name][0] -= quantity
            if backpack[uid][item_name][0] == 0:
                del backpack[uid][item_name]
            # 更新商店库存中的 current_stock
            if current_stock != -1:
                store_data["items"][item_name]["current_stock"] += quantity
            success.append(f"{item_name}*{quantity}")
        if total_gain > 0:
            if "积分" in backpack[uid]:
                backpack[uid]["积分"][0] += total_gain
            else:
                backpack[uid]["积分"] = [total_gain, "暂无简介"]
        setData("store.json", store_data)
        setData("backpack.json", backpack)
        nowtime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_key = f"{nowtime}〖{user_name}〗售出{'、'.join(success)}"
        store_log[log_key] = "成功"
        setData("store_log.json", store_log)
        rep = []
        if success:
            rep.append(
                f"成功售出{'、'.join(success)}，获得{total_gain}积分啦！\n\n剩余积分：{backpack[uid]['积分'][0]}（收益小数抹零）"
            )
        if fail_store:
            rep.append(f"{'、'.join(fail_store)}不可回收或骰主未配置噢！")
        if fail_backpack:
            rep.append(f"{'、'.join(fail_backpack)}不在背包噢！")
        if fail_quantity:
            rep.append(f"{'、'.join(fail_quantity)}数量不足噢！")
        plugin_event.reply("\n".join(rep) if rep else "未售出任何物品")

    if message.endswith("交易日志") or message.endswith(" 交易日志"):
        date_str = (
            message.split(" ")[0].strip() if " " in message else message[:6].strip()
        )
        if not re.match(r"^\d{6}$", date_str):
            plugin_event.reply("查看交易日志格式：\n\n240101 交易日志")
            return
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("权限不足，仅骰主或本插件管理员可查询")
            return
        store_log = getData("store_log.json")
        year = "20" + date_str[:2]
        month = date_str[2:4]
        day = date_str[4:6]
        filtered_logs = []
        for log_key, log_value in store_log.items():
            log_date = log_key.split(" ")[0]
            if log_date == f"{year}-{month}-{day}":
                filtered_logs.append(f"{log_key} {log_value}")
        if filtered_logs:
            response = "\n".join(filtered_logs)
        else:
            response = f"没有找到{year}年{month}月{day}日的交易日志或日志为空噢！"
        plugin_event.reply(response)

    if message == "清空所有商店日志数据":
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("只有骰主或本插件管理员才能使用该命令")
            return
        setData("store_log.json", {})
        plugin_event.reply("所有商店购买、售出日志数据已清空！")
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             积分功能细则             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    if message.startswith("积分"):
        backpack = getData("backpack.json")
        expr = message[2:].strip()
        if not expr:
            plugin_event.reply("请输入数字或四则运算表达式（+ - * /）")
            return
        # 允许的格式：
        # 1. 纯数字（直接赋值）  ->  "50"
        # 2. 以 + - * / 开头的四则运算 -> "+5" "-3" "*2" "/4"
        if re.fullmatch(r"\d+", expr):  # 纯数字（直接赋值）
            new_score = int(expr)
        elif re.fullmatch(r"[+\-*/]\d+", expr):  # 以 + - * / 开头的四则运算
            current_points = backpack.get(uid, {}).get("积分", [0, "暂无简介"])[0]
            new_score = eval(f"{current_points}{expr}")
        else:
            plugin_event.reply("请输入数字或四则运算表达式（+ - * /）")
            return
        # 获取当前背包中是否存在积分物品
        if "积分" not in backpack.get(uid, {}):
            backpack.setdefault(uid, {})["积分"] = [0, "暂无简介"]
        # 更新背包中的积分物品
        current_points = backpack[uid]["积分"][0]
        backpack[uid]["积分"][0] = new_score
        # 保存更新后的数据到背包
        setData("backpack.json", backpack)
        plugin_event.reply(f"背包内积分更新成功：\n{current_points} → {new_score}")
        return

    if message == "背包积分汇率":
        store_data = getData("store.json")
        recycle_rate = store_data.get("recycle_rate", 0.6)
        backpack = getData("backpack.json")
        user_score = backpack.get(uid, {}).get("积分", [0, "暂无简介"])[0]
        plugin_event.reply(
            "今日汇率信息\n"
            f" · 回收利率：{recycle_rate*100:.2f}%\n"
            f" · 当前积分：{user_score}"
        )

    if message == "查询积分":
        backpack = getData("backpack.json")
        user_score = backpack.get(uid, {}).get("积分", [0, "暂无简介"])[0]
        plugin_event.reply(f"背包内持有积分：{user_score}")

    if message.startswith("设置回收率"):
        store_data = getData("store.json")
        # 如果uid不在骰主列表并且不在本插件管理员列表，则拒绝
        if uid not in masterlist and uid not in admin_list:
            plugin_event.reply("权限不足，仅骰主或本插件管理员可修改")
            return
        try:
            new_rate = float(message[5:].strip())
            if not (0 <= new_rate <= 10):
                plugin_event.reply("利率需在0~10之间")
                return
            store_data["recycle_rate"] = new_rate
            setData("store.json", store_data)
            plugin_event.reply(f"回收利率已更新为 {new_rate*100:.2f}%")
            return
        except ValueError:
            plugin_event.reply("格式：设置回收率 0.5")
            return
    #########################################
    # ┌────────────────────────────────────┐
    # │                                    │
    # │             合成功能细则             │
    # │                                    │
    # └────────────────────────────────────┘
    #########################################
    elif message.startswith("背包合成"):
        materials = message[5:].strip().split()
        if not materials:
            plugin_event.reply(
                "请输入需要合成的材料，并用空格隔开[1]\n\n如：背包合成 材料A 材料A 材料B 材料C\n\n或：背包合成 材料A 2 材料B 1 材料C 1"
            )
            return
        material_counts = {}
        if len(materials) % 2 == 0:
            try:
                for i in range(1, len(materials), 2):
                    int(materials[i])
            except ValueError:
                for material in materials:
                    material_counts[material] = material_counts.get(material, 0) + 1
                pass
            else:
                for i in range(0, len(materials), 2):
                    material_counts[materials[i]] = int(materials[i + 1])
        else:
            for i in range(0, len(materials)):
                if materials[i].isdigit():
                    plugin_event.reply(
                        "请输入需要合成的材料，并用空格隔开[2]\n\n如：背包合成 材料A 材料A 材料B 材料C\n\n或：背包合成 材料A 2 材料B 1 材料C 1"
                    )
                    return
                material_counts[materials[i]] = material_counts.get(materials[i], 0) + 1
        product = getData("product.json")
        backpack = getData("backpack.json")
        matched_product = None
        missing_materials = []
        for product_name, details in product.items():
            match = True
            for material, required_count in details["materials"].items():
                if material_counts.get(material, 0) < required_count:
                    match = False
                    break
            if match:
                input_materials_set = set(material_counts.keys())
                required_materials_set = set(details["materials"].keys())
                if input_materials_set != required_materials_set:
                    match = False
                else:
                    for material, count in material_counts.items():
                        if count != details["materials"].get(material, 0):
                            match = False
                            break
            if match:
                matched_product = product_name
                product_desc = details["description"]
                break
        if matched_product:
            for material, required_count in details["materials"].items():
                if material not in backpack[uid]:
                    missing_materials.append(material)
                elif backpack[uid][material][0] < required_count:
                    missing_materials.append(material)
                else:
                    backpack[uid][material][0] -= required_count
                    if backpack[uid][material][0] == 0:
                        del backpack[uid][material]
            if missing_materials:
                missing_materials_str = "】【".join(missing_materials)
                plugin_event.reply(f"你没有足够的【{missing_materials_str}】噢！")
                return
            if matched_product not in backpack[uid]:
                backpack[uid][matched_product] = [1, product_desc]
            else:
                backpack[uid][matched_product][0] += 1
            setData("backpack.json", backpack)
            plugin_event.reply(
                f"恭喜你成功合成了【{matched_product}】\n\n{product_desc}"
            )
        else:
            plugin_event.reply("啊哦！没有找到符合该图纸的道具或骰主未配置！")


def getData(filename):
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


def setData(filename, data):
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


def getPcName(uid=None, platfrom=None, hagid=None, sendername=None):
    pc_hash = OlivaDiceCore.pcCard.getPcHash(uid, platfrom)
    name = OlivaDiceCore.pcCard.pcCardDataGetSelectionKey(pc_hash, hagid)
    if name == None:
        name = sendername
    return name


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
