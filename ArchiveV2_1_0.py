#  coding=UTF-8
#
# _     /)---(\
# \\   (/ . . \)
#  \\__)-\(*)/
#  \_       (_
#  (___/-(____)
#
# 「技术支持」探丸借客@临皋闲人
import OlivOS
import OlivaDiceCore
import json
import os
import threading
import shutil
import re

pclock = threading.Lock()


def getPcHash(uid, platform):
    import hashlib

    hash_tmp = hashlib.new("md5")
    hash_tmp.update(str(uid).encode(encoding="UTF-8"))
    hash_tmp.update(str(platform).encode(encoding="UTF-8"))
    return hash_tmp.hexdigest()


def getHagId(plugin_event):
    tmp_hagID = None
    flag_is_from_host = False
    flag_is_from_group = False
    if plugin_event.plugin_info["func_type"] == "group_message":
        if plugin_event.data.host_id is not None:
            flag_is_from_host = True
        flag_is_from_group = True
    elif plugin_event.plugin_info["func_type"] == "private_message":
        flag_is_from_group = False

    if flag_is_from_host and flag_is_from_group:
        tmp_hagID = f"{plugin_event.data.host_id}|{plugin_event.data.group_id}"
    elif flag_is_from_group:
        tmp_hagID = str(plugin_event.data.group_id)

    return tmp_hagID


def get_current_card(data, groupid):
    for card_name, card_data in data.get("cards", {}).items():
        if (
            card_data.get("locked", False)
            and str(card_data.get("locked_group", "")) == groupid
        ):
            return card_name, card_data
    current_card_name = data.get("current", "")
    if current_card_name and current_card_name in data.get("cards", {}):
        return current_card_name, data["cards"][current_card_name]
    return "", {}


def reply(plugin_event, Proc):
    message = plugin_event.data.message
    groupid = str(getattr(plugin_event.data, "group_id", ""))
    uid = str(plugin_event.data.user_id)
    sender = plugin_event.data.sender["name"]
    filename = f"{uid}.json"
    platfrom = plugin_event.platform["platform"]
    tmp_botHash = plugin_event.bot_info.hash
    masterlist = getMaster(tmp_botHash, platfrom)

    def get_target_uid_and_clean_msg(message, bot_id):
        all_at_ids = re.findall(r"\[OP:at,id=(\d+)\]", message)
        other_at_ids = [aid for aid in all_at_ids if aid != bot_id]
        clean_msg = re.sub(r"\[OP:[^\]]+\]", "", message).strip()
        return other_at_ids, clean_msg

    bot_id = str(plugin_event.bot_info.id)

    if message.startswith("<创建>"):
        other_at_ids, clean_msg = get_target_uid_and_clean_msg(message, bot_id)
        # 确定操作目标
        if other_at_ids:
            if uid not in masterlist:
                plugin_event.reply(f"{sender}没有权限代他人创建档案。")
                return
            target_uid = other_at_ids[0]
        else:
            target_uid = uid

        char_name = clean_msg[len("<创建>") :].strip()
        if not char_name:
            plugin_event.reply("请输入档案名噢！\n如：<创建>张三")
            return

        target_filename = f"{target_uid}.json"
        data = getData(target_filename)
        if char_name in data.get("cards", {}):
            plugin_event.reply(f"<{char_name}>的档案已经存在啦！")
            return

        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(target_uid, platform)
        hag_id = getHagId(plugin_event)

        new_card = {"attributes": {}, "locked": False, "locked_group": ""}
        if "cards" not in data:
            data["cards"] = {}
        data["cards"][char_name] = new_card
        data["current"] = char_name
        setData(target_filename, data)

        try:
            OlivaDiceCore.pcCard.getPcNameAPI(pc_hash, hag_id, char_name)
        except Exception as e:
            plugin_event.reply(f"同步到核心代码失败: {e}")

        plugin_event.reply(f"<{char_name}>创建成功！")
        return

    elif message.startswith("<档案>"):
        other_at_ids, clean_msg = get_target_uid_and_clean_msg(message, bot_id)
        # 确定目标（仅管理员可查他人）
        if other_at_ids:
            if uid not in masterlist:
                plugin_event.reply(f"{sender}没有权限查看他人档案。")
                return
            target_uid = other_at_ids[0]
        else:
            target_uid = uid

        target_filename = f"{target_uid}.json"
        data = getData(target_filename)
        if not data:
            plugin_event.reply(f"<用户{target_uid}>数值\n空")
            return
        card_name, card_data = get_current_card(data, groupid)
        if not card_name:
            plugin_event.reply(f"<用户{target_uid}>数值\n空")
            return
        attributes = card_data.get("attributes", {})
        if not attributes:
            plugin_event.reply(f"<{card_name}>数值\n空")
            return

        # 回复前缀（代查时显示代查人）
        prefix = f"<{sender}>代查\n\n" if target_uid != uid else ""
        reply_msg = f"{prefix}<{card_name}>数值\n"
        for attr, value in attributes.items():
            reply_msg += f"{attr}：{value}\n"
        plugin_event.reply(reply_msg.strip())
        return

    elif message.startswith("<重命名>"):
        other_at_ids, clean_msg = get_target_uid_and_clean_msg(message, bot_id)
        if other_at_ids:
            if uid not in masterlist:
                plugin_event.reply(f"{sender}没有权限代他人重命名。")
                return
            target_uid = other_at_ids[0]
        else:
            target_uid = uid

        new_name = clean_msg[len("<重命名>") :].strip()
        if not new_name:
            plugin_event.reply("请输入新的档案名噢！\n\n如：<重命名>李四")
            return

        target_filename = f"{target_uid}.json"
        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(target_uid, platform)
        hag_id = getHagId(plugin_event)

        data = getData(target_filename)
        current_name = data.get("current", "")

        if not current_name:
            if "cards" not in data:
                data["cards"] = {}
            data["cards"][new_name] = {
                "attributes": {},
                "locked": False,
                "locked_group": "",
            }
            data["current"] = new_name
            setData(target_filename, data)
            try:
                OlivaDiceCore.pcCard.getPcNameAPI(pc_hash, hag_id, new_name)
            except Exception as e:
                plugin_event.reply(f"同步到核心代码失败: {e}")
            plugin_event.reply(f"<{sender}>已将目标重命名为<{new_name}>")
            return

        if new_name in data.get("cards", {}):
            plugin_event.reply(f"<{new_name}>已存在，请使用其他名称噢！")
            return

        current_card = data["cards"].get(current_name)
        if not current_card:
            plugin_event.reply("当前档案数据异常！")
            return

        del data["cards"][current_name]
        data["cards"][new_name] = current_card
        data["current"] = new_name
        setData(target_filename, data)

        try:
            OlivaDiceCore.pcCard.pcCardRebase(pc_hash, new_name, hag_id)
        except Exception as e:
            plugin_event.reply(f"同步到核心代码失败: {e}")

        plugin_event.reply(f"<{current_name}>已重命名为<{new_name}>")
        return

    elif message.startswith("<数值>"):
        other_at_ids, clean_msg = get_target_uid_and_clean_msg(message, bot_id)
        if other_at_ids:
            if uid not in masterlist:
                plugin_event.reply(f"{sender}没有权限代他人修改数值。")
                return
            target_uid = other_at_ids[0]
        else:
            target_uid = uid

        input_str = clean_msg[len("<数值>") :].strip()
        target_filename = f"{target_uid}.json"
        data = getData(target_filename)
        card_name, card_data = get_current_card(data, groupid)
        if not card_name:
            plugin_event.reply(f"<{sender}>代改失败：未找到目标用户的档案")
            return

        if not input_str:
            plugin_event.reply(
                "请输入设置的数值名和数值噢！\n\n如：<数值>体力10 魔法+10 san-10"
            )
            return

        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(target_uid, platform)
        hag_id = getHagId(plugin_event)

        attributes = {}
        pattern = r"([\u4e00-\u9fa5a-zA-Z]+)([-+*/]?\d+)"
        matches = re.findall(pattern, input_str)

        if not matches:
            plugin_event.reply("正确的格式：<数值>体力10魔法+10san-10")
            return

        errors = []
        for match in matches:
            attr_name = match[0].strip()
            value_str = match[1].strip()
            if not re.match(r"^([-+*/]?\d+)$", value_str):
                errors.append(f"非法数值格式：{value_str}")
                continue
            attributes[attr_name] = value_str

        if errors:
            error_msg = "格式错误：\n" + "\n".join(errors)
            plugin_event.reply(error_msg)
            return

        if not attributes:
            plugin_event.reply(
                "请输入设置的数值名和数值噢！\n\n正确格式：<数值>体力10魔法+10san-10"
            )
            return

        updated_attributes = {}
        for attr, value in attributes.items():
            current_value = card_data["attributes"].get(attr, 0)
            if re.match(r"^[-+*/]", value):
                operator = value[0]
                number = int(value[1:])
                if operator == "+":
                    new_value = current_value + number
                elif operator == "-":
                    new_value = current_value - number
                elif operator == "*":
                    new_value = current_value * number
                elif operator == "/":
                    new_value = (
                        current_value // number if number != 0 else current_value
                    )
                else:
                    new_value = current_value
            else:
                try:
                    new_value = int(value)
                except:
                    new_value = current_value

            card_data["attributes"][attr] = new_value
            updated_attributes[attr] = {
                "old": current_value,
                "new": new_value,
                "operation": value,
            }

            try:
                OlivaDiceCore.pcCard.getPcNameAPI(pc_hash, hag_id, card_name)
                OlivaDiceCore.pcCard.setPcSkillAPI(
                    pc_hash, attr, new_value, hag_id, card_name
                )
            except Exception as e:
                plugin_event.reply(f"同步到核心代码失败: {e}")

        data["cards"][card_name] = card_data
        setData(target_filename, data)

        prefix = f"<{sender}>代改\n\n" if target_uid != uid else ""
        reply_msg = f"{prefix}<{card_name}>的数值已更新：\n"
        for attr, info in updated_attributes.items():
            if re.match(r"^[-+*/]", info["operation"]):
                operator = info["operation"][0]
                num = info["operation"][1:]
                reply_msg += f"{attr}：{info['old']}{operator}{num}={info['new']}\n"
            else:
                reply_msg += f"{attr}：{info['old']}→{info['new']}\n"
        plugin_event.reply(reply_msg.strip())
        return

    elif message.startswith("<删除>"):
        other_at_ids, clean_msg = get_target_uid_and_clean_msg(message, bot_id)
        if other_at_ids:
            if uid not in masterlist:
                plugin_event.reply(f"{sender}没有权限代他人删除数值。")
                return
            target_uid = other_at_ids[0]
        else:
            target_uid = uid

        input_str = clean_msg[len("<删除>") :].strip()
        if not input_str:
            plugin_event.reply("请输入删除的数值名噢！\n\n如：<删除>体力 精神")
            return

        target_filename = f"{target_uid}.json"
        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(target_uid, platform)
        hag_id = getHagId(plugin_event)

        attr_names = [name.strip() for name in input_str.split()]
        data = getData(target_filename)
        card_name, card_data = get_current_card(data, groupid)

        if not card_name:
            plugin_event.reply(f"<{sender}>未找到目标档案，无法删除")
            return

        deleted_attrs = []
        not_found_attrs = []

        for attr_name in attr_names:
            if attr_name in card_data["attributes"]:
                del card_data["attributes"][attr_name]
                deleted_attrs.append(attr_name)
                try:
                    OlivaDiceCore.pcCard.pcCardDataDelBySkillName(
                        pc_hash, attr_name, card_name
                    )
                except Exception as e:
                    plugin_event.reply(f"同步到核心代码失败: {e}")
            else:
                not_found_attrs.append(attr_name)

        if not deleted_attrs:
            plugin_event.reply(f"<{card_name}>指定的内容不存在，无法删除")
            return

        data["cards"][card_name] = card_data
        setData(target_filename, data)

        reply_msg = f"<{card_name}>档案中的以下内容已删除：\n" + "\n".join(
            deleted_attrs
        )
        if not_found_attrs:
            reply_msg += f"\n\n以下内容不存在：\n" + "\n".join(not_found_attrs)
        if target_uid != uid:
            reply_msg = f"<{sender}>代删除\n\n" + reply_msg
        plugin_event.reply(reply_msg)
        return

    elif message == "<档案锁定至本群>":
        # 获取核心代码需要的参数
        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(uid, platform)
        hag_id = getHagId(plugin_event)

        data = getData(filename)
        current_card_name = data.get("current", "")
        if not current_card_name:
            plugin_event.reply(f"<{sender}>的档案不存在，无法锁定")
            return

        card_data = data["cards"][current_card_name]
        card_data["locked"] = True
        card_data["locked_group"] = groupid
        setData(filename, data)

        # 同步到核心代码
        try:
            OlivaDiceCore.pcCard.setPcLockAPI(pc_hash, hag_id, True, current_card_name)
        except Exception as e:
            plugin_event.reply(f"同步到核心代码失败: {e}")

        plugin_event.reply(f"<{sender}>的档案<{current_card_name}>已锁定至本群！")
        return

    elif message == "<解锁本群档案>":
        # 获取核心代码需要的参数
        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(uid, platform)
        hag_id = getHagId(plugin_event)

        data = getData(filename)
        found_locked_card = False
        card_to_unlock = None
        card_name_to_unlock = ""

        for card_name, card_data in data.get("cards", {}).items():
            if (
                card_data.get("locked", False)
                and str(card_data.get("locked_group", "")) == groupid
            ):
                found_locked_card = True
                card_to_unlock = card_data
                card_name_to_unlock = card_name
                break

        if not found_locked_card:
            plugin_event.reply("当前群没有锁定的档案噢！")
            return

        card_to_unlock["locked"] = False
        card_to_unlock["locked_group"] = ""
        setData(filename, data)

        # 同步到核心代码
        try:
            OlivaDiceCore.pcCard.setPcLockAPI(
                pc_hash, hag_id, False, card_name_to_unlock
            )
        except Exception as e:
            plugin_event.reply(f"同步到核心代码失败: {e}")

        plugin_event.reply(f"<{sender}>的档案<{card_name_to_unlock}>已从本群解锁！")

    elif message.startswith("<切换>"):
        char_name = message[len("<切换>") :].strip()
        if not char_name:
            plugin_event.reply("请输入要切换的档案名噢！\n\n如：<切换>张三")
            return

        # 获取核心代码需要的参数
        platform = plugin_event.platform["platform"]
        pc_hash = getPcHash(uid, platform)
        hag_id = getHagId(plugin_event)

        data = getData(filename)
        if char_name not in data.get("cards", {}):
            plugin_event.reply(f"<{sender}>的档案<{char_name}>不存在，无法切换")
            return

        data["current"] = char_name
        setData(filename, data)

        # 同步到核心代码
        try:
            OlivaDiceCore.pcCard.setPcSwitchAPI(pc_hash, hag_id, char_name)
        except Exception as e:
            plugin_event.reply(f"同步到核心代码失败: {e}")

        plugin_event.reply(f"<{sender}>当前档案已切换为：{char_name}")
        return

    elif message == "<档案列表>":
        data = getData(filename)
        cards = data.get("cards", {})
        if not cards:
            plugin_event.reply(f"<{sender}>的档案列表：\n空")
            return
        locked_card = None
        for name, card in cards.items():
            if (
                card.get("locked", False)
                and str(card.get("locked_group", "")) == groupid
            ):
                locked_card = name
                break
        reply_msg = f"<{sender}>的档案列表：\n"
        reply_msg += "\n".join(cards.keys()) + "\n"
        if locked_card:
            reply_msg += f"当前使用：{locked_card}（锁定至本群）"
        elif data.get("current", ""):
            reply_msg += f"当前使用：{data['current']}"
        plugin_event.reply(reply_msg.strip())
        return

    elif message == "<清空>":
        data = getData(filename)
        card_name, card_data = get_current_card(data, groupid)
        if not card_name:
            plugin_event.reply(f"<{sender}>未创建人物卡，无法清空")
        if card_data.get("locked", False):
            locked_group = str(card_data.get("locked_group", ""))
            if locked_group and locked_group != groupid:
                plugin_event.reply(
                    f"当前档案<{card_name}>锁定在群{locked_group}，请前往解锁后清空"
                )
        card_data["attributes"] = {}
        setData(filename, data)
        plugin_event.reply(f"<{sender}>的档案<{card_name}>已清空！")

    elif message.startswith("<删除档案>"):
        data = getData(filename)
        card_to_delete = message[len("<删除档案>") :].strip()
        if not card_to_delete:
            card_to_delete = data.get("current", "")
        if card_to_delete not in data.get("cards", {}):
            plugin_event.reply(f"<{sender}>的档案<{card_to_delete}>不存在，无法删除")
            return
        del data["cards"][card_to_delete]
        if data.get("current") == card_to_delete:
            if data["cards"]:
                data["current"] = next(iter(data["cards"].keys()))
            else:
                data["current"] = ""
        setData(filename, data)
        plugin_event.reply(f"<{sender}>的档案<{card_to_delete}>已删除")

    elif message.startswith("<设置档案标题>"):
        if uid not in masterlist:
            plugin_event.reply("权限不足，仅骰主可设置")
            return
        title = message[len("<设置档案标题>") :].strip()
        if not title:
            return plugin_event.reply("请输入内容噢！\n\n如：<设置档案标题>恋综名")
        playname_data = getData("playname.json")
        if not isinstance(playname_data, dict):
            playname_data = {"title": ""}
        playname_data["title"] = title
        setData("playname.json", playname_data)
        return plugin_event.reply(
            f"档案标题已更新为：{title}\n\n<数值名 运算符 数字>格式的操作将会更新到对应的个人群。\n如需骰主代操作，可在指令末尾@用户。"
        )

    elif message == "<档案帮助>":
        plugin_event.reply(
            "<档案使用说明>\n\n"
            "创建人物卡：\n"
            "<创建>姓名\n\n"
            "查看人物卡：\n"
            "<档案>\n\n"
            "重命名当前人物卡：\n"
            "<重命名>姓名\n\n"
            "录入/更新数值：\n"
            "<数值>数值名 数值\n\n"
            "四则运算更新：\n"
            "<数值>数值名 运算符 数字\n\n"
            "删除数值：\n"
            "<删除>数值名\n\n"
            "清空当前人物卡：\n"
            "<清空>\n\n"
            "删除人物卡/删除指定人物卡：\n"
            "<删除档案>/<删除档案>姓名\n\n"
            "扩展命令请输入<档案帮助 stex>进行查询\n"
            "如需骰主代操作，可在指令末尾@用户"
        )
        return

    elif message == "<档案帮助 stex>":
        plugin_event.reply(
            "<档案扩展命令>\n\n"
            "特殊数值变更：\n"
            "<数值名 运算符 数字>\n\n"
            "特殊数值变更通知群：\n"
            "<设置档案标题>恋综名\n\n"
            "查看人物卡列表：\n"
            "<档案列表>\n\n"
            "切换人物卡：\n"
            "<切换>姓名\n\n"
            "锁定人物卡：\n"
            "<档案锁定至本群>\n\n"
            "解锁人物卡：\n"
            "<解锁本群档案>"
        )
        return

    elif "<" in message and ">" in message:
        pattern = r"<([^\s<>]+?)\s*([+\-*/])\s*(\d+)>"
        matches = re.findall(pattern, message)
        if not matches:
            return
        playname_data = getData("playname.json")
        if (
            not playname_data
            or not isinstance(playname_data, dict)
            or not playname_data.get("title")
        ):
            return
        permission_group_name = playname_data["title"]
        privategroup = getGroup("privategroup.json")
        if permission_group_name not in privategroup:
            return
        uid_str = str(uid)
        if uid_str not in privategroup[permission_group_name]:
            return
        user_info = privategroup[permission_group_name][uid_str]
        group_id = user_info.get("个人群号") or user_info.get("NPC群号")
        if not group_id:
            return
        data = getData(filename)
        card_name, card_data = get_current_card(data, groupid)
        if not card_name:
            return
        reply_msg = f"<{card_name}>的数值已更新：\n"
        updated = False
        for match in matches:
            attr_name = match[0].strip()
            operator = match[1].strip()
            value_str = match[2].strip()
            try:
                value = int(value_str)
                current_value = card_data["attributes"].get(attr_name, 0)
                exists_before = attr_name in card_data["attributes"]
                if operator == "+":
                    new_value = current_value + value
                elif operator == "-":
                    new_value = current_value - value
                elif operator == "*":
                    new_value = current_value * value
                elif operator == "/":
                    if value != 0:
                        new_value = current_value // value
                    else:
                        new_value = current_value
                else:
                    continue
                card_data["attributes"][attr_name] = new_value
                updated = True
                if exists_before:
                    reply_msg += (
                        f"{attr_name}：{current_value}{operator}{value}={new_value}\n"
                    )
                else:
                    reply_msg += f"{attr_name}：0{operator}{value}={new_value}\n"
            except ValueError:
                return
        if updated:
            data["cards"][card_name] = card_data
            setData(filename, data)
            plugin_event.send(
                "group",
                group_id,
                reply_msg.strip(),
            )


def getData(filename):
    path = "./plugin/data/DIYpccard/"
    if not os.path.exists(path):
        os.makedirs(path)
    with pclock:
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
    path = "./plugin/data/DIYpccard/"
    with pclock:
        try:
            with open(path + filename, "r", encoding="utf-8") as f:
                check = json.load(f)
            shutil.copy(path + filename, path + filename + ".bak")
        except:
            pass
        with open(path + filename, "w", encoding="utf-8") as w:
            json.dump(data, w, indent=4, ensure_ascii=False)


def getGroup(filename):
    path = "./plugin/data/amourgame/groupcollection/"
    with pclock:
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
