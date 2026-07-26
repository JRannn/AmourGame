import random
import time
import requests, json, os

PERSONAL_KEY = "个人"


def get_game(data, groupid):
    group = data.get(groupid, {})
    game = group.get("game", {})
    if not isinstance(game, dict):
        game = {}
        if groupid in data:
            data[groupid]["game"] = game
    return game


def get_personal(data, groupid):
    return data.get(groupid, {}).get(PERSONAL_KEY, {})


def active_seats(data, groupid, alive_only=False):
    game = get_game(data, groupid)
    dead = set(str(i) for i in game.get("dead", [])) if alive_only else set()
    seats = []
    for seat, player in get_personal(data, groupid).items():
        uid = str(player.get("uid", ""))
        if uid and uid not in dead:
            seats.append(str(seat))
    return sorted(seats, key=lambda x: int(x))


def active_players(data, groupid, alive_only=False):
    personal = get_personal(data, groupid)
    return [personal[seat] for seat in active_seats(data, groupid, alive_only)]


def seat_by_uid(data, groupid, uid):
    uid = str(uid)
    for seat, player in get_personal(data, groupid).items():
        if str(player.get("uid", "")) == uid:
            return str(seat)
    return None


def player_by_uid(data, groupid, uid):
    seat = seat_by_uid(data, groupid, uid)
    if not seat:
        return None
    return get_personal(data, groupid).get(seat)


def player_by_seat(data, groupid, seat):
    return get_personal(data, groupid).get(str(seat))


def player_name(player, fallback="未知玩家"):
    if not player:
        return fallback
    return player.get("name") or fallback


def uid_name(data, groupid, uid, fallback=None):
    player = player_by_uid(data, groupid, uid)
    return player_name(player, fallback or str(uid))


def at(uid):
    return f"[OP:at,id={uid}]"


def find_play_group(data, uid, game_type=None):
    uid = str(uid)
    for groupid, group_data in data.items():
        if not isinstance(group_data, dict):
            continue
        if game_type is not None:
            game = group_data.get("game", {})
            if (
                not isinstance(game, dict)
                or game.get("type") != game_type
            ):
                continue
        if seat_by_uid(data, groupid, uid):
            return groupid
    return ""


def next_active_seat(data, groupid, current_seat, alive_only=False, include_current=False):
    seats = active_seats(data, groupid, alive_only)
    if not seats:
        return None

    current = int(current_seat or 0)
    if include_current and str(current) in seats:
        return str(current)

    for seat in seats:
        if int(seat) > current:
            return seat
    return seats[0]


def set_turn(game, seat):
    game["turn"] = int(seat) if seat is not None else None


def advance_turn(data, groupid, alive_only=False):
    game = get_game(data, groupid)
    next_seat = next_active_seat(data, groupid, game.get("turn", 0), alive_only)
    set_turn(game, next_seat)
    return next_seat


def current_player(data, groupid):
    game = get_game(data, groupid)
    return player_by_seat(data, groupid, game.get("turn"))


def is_current_player(data, groupid, uid):
    player = current_player(data, groupid)
    return bool(player and str(player.get("uid")) == str(uid))


def ensure_game(data, groupid, game_type, phase="prepare", turn=1):
    data[groupid]["game"] = {
        "type": game_type,
        "phase": phase,
        "turn": turn,
        "round": {},
        "scores": {},
        "submissions": {},
        "history": [],
        "dead": [],
    }
    return data[groupid]["game"]


def ensure_common_fields(game):
    if not isinstance(game, dict):
        game = {}
    game.setdefault("phase", "prepare")
    game.setdefault("turn", 1)
    game.setdefault("round", {})
    game.setdefault("scores", {})
    game.setdefault("submissions", {})
    game.setdefault("history", [])
    game.setdefault("dead", [])
    return game


def clear_round(game, phase=None):
    game["round"] = {}
    if phase:
        game["phase"] = phase


def mark_round_start(game):
    game["round_start_time"] = time.time()


def is_round_timeout(game, seconds=180):
    start = game.get("round_start_time", 0)
    return bool(start) and time.time() - start > seconds


def finish_game(data, groupid, keep_type=True):
    old_type = data[groupid].get("game", {}).get("type")
    data[groupid]["game"] = {"type": old_type} if keep_type and old_type else {}


def mark_game_ended(data, groupid):
    game = ensure_common_fields(get_game(data, groupid))
    game["phase"] = "ended"
    game["round"] = {}
    game["round_start_time"] = 0
    return game


def add_score(data, groupid, uid, delta=1):
    game = ensure_common_fields(get_game(data, groupid))
    uid = str(uid)
    game["scores"][uid] = game["scores"].get(uid, 0) + int(delta)
    return game["scores"][uid]


def set_score(data, groupid, uid, score):
    game = ensure_common_fields(get_game(data, groupid))
    uid = str(uid)
    game["scores"][uid] = int(score)
    return game["scores"][uid]


def get_score(data, groupid, uid):
    return get_game(data, groupid).get("scores", {}).get(str(uid), 0)


def score_lines(data, groupid, title="计分统计："):
    scores = get_game(data, groupid).get("scores", {})
    personal = get_personal(data, groupid)
    rows = []
    for seat, player in personal.items():
        uid = str(player.get("uid", ""))
        if not uid:
            continue
        rows.append((int(seat), player_name(player, f"{seat}号"), scores.get(uid, 0)))
    rows.sort(key=lambda item: (-item[2], item[0]))
    if not rows:
        return title + "\n暂无计分。"
    return title + "\n" + "\n".join(f"{name}：{score}" for _, name, score in rows)


def record_submission(data, groupid, uid, payload, bucket="submissions"):
    game = ensure_common_fields(get_game(data, groupid))
    game.setdefault(bucket, {})
    game[bucket][str(uid)] = payload
    return game[bucket]


def get_submission(data, groupid, uid, bucket="submissions"):
    return get_game(data, groupid).get(bucket, {}).get(str(uid))


def submitted_count(data, groupid, bucket="submissions"):
    return len(get_game(data, groupid).get(bucket, {}))


def active_submitted_count(data, groupid, bucket="submissions"):
    submissions = get_game(data, groupid).get(bucket, {})
    active = [str(p.get("uid")) for p in active_players(data, groupid)]
    return len([uid for uid in active if uid in submissions])


def all_active_submitted(data, groupid, bucket="submissions"):
    submissions = get_game(data, groupid).get(bucket, {})
    active = [p.get("uid") for p in active_players(data, groupid)]
    return bool(active) and all(str(uid) in submissions for uid in active)


def all_seated_submitted(data, groupid, bucket="submissions"):
    submissions = get_game(data, groupid).get(bucket, {})
    players = list(get_personal(data, groupid).values())
    if not players or any(not p.get("uid") for p in players):
        return False
    return all(str(p.get("uid")) in submissions for p in players)


def send_to_player(plugin_event, data, groupid, player, message):
    if not player:
        return
    if data[groupid].get("playname") and player.get("groupid"):
        plugin_event.send("group", player["groupid"], message)
    else:
        plugin_event.send("private", player.get("uid"), message)


def send_to_uid(plugin_event, data, groupid, uid, message):
    send_to_player(plugin_event, data, groupid, player_by_uid(data, groupid, uid), message)


def random_seat_order(data, groupid, alive_only=False):
    seats = active_seats(data, groupid, alive_only)
    random.shuffle(seats)
    return seats


def format_seat_order(data, groupid, seats, title="本轮顺序："):
    personal = get_personal(data, groupid)
    lines = [title]
    for idx, seat in enumerate(seats, start=1):
        player = personal.get(str(seat), {})
        lines.append(f"{idx}. {player_name(player, f'{seat}号')}")
    return "\n".join(lines)


def parse_choice(message, minimum=1, maximum=3):
    text = message.strip()
    if not text.isdigit():
        return None
    value = int(text)
    if minimum <= value <= maximum:
        return value
    return None


def first_answer(game, uid):
    uid = str(uid)
    if game.get("winner"):
        return False
    game["winner"] = uid
    game["answer_time"] = time.time()
    return True


def build_forward_node(name, uin, text):
    return {
        "type": "node",
        "data": {
            "name": name,
            "uin": str(uin),
            "content": [
                {
                    "type": "text",
                    "data": {
                        "text": text
                    }
                }
            ]
        }
    }


def send_score_forward(plugin_event, data, groupid, title="计分统计："):
    text = score_lines(data, groupid, title)
    send_forward_text(plugin_event, groupid, 0, [build_forward_node(" ", plugin_event.bot_info.id, text)])


def send_final_score_forward(plugin_event, data, groupid):
    game_type = get_game(data, groupid).get("type") or "游戏"
    send_score_forward(plugin_event, data, groupid, f"{game_type}最终计分：")

def get_account_config(plugin_event):
    """从 conf/account.json 读取账号配置"""
    config_path = os.path.join('conf', 'account.json')
    try:
        if not os.path.exists(config_path):
            return None
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        if 'account' not in config_data or not config_data['account']:
            return None

        current_bot_id = str(plugin_event.bot_info.id)
        for account_config in config_data['account']:
            if 'id' in account_config and str(account_config['id']) == current_bot_id:
                if 'server' not in account_config:
                    return None

                server_config = account_config['server']
                required_fields = ['host', 'port', 'access_token']
                for field in required_fields:
                    if field not in server_config:
                        return None
                return server_config
        return None
    except Exception:
        return None

def send_forward_text(plugin_event, group_id, user_id,  messages):
    server_config = get_account_config(plugin_event)
    if server_config is None:
        plugin_event.reply("无法获取服务器配置！")
        return

    if group_id:
        api_url = f"http://{server_config['host'].replace('http://', '').replace('https://', '')}:{server_config['port']}/send_group_forward_msg"
        payload = {
            "group_id": group_id,
            "messages": messages
        }
    else:
        api_url = f"http://{server_config['host'].replace('http://', '').replace('https://', '')}:{server_config['port']}/send_private_forward_msg"
        payload = {
            "user_id": user_id,
            "messages": messages
        }
    headers = {
        "Authorization": f"Bearer {server_config['access_token']}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            api_url,
            data=json.dumps(payload),
            headers=headers
        )
    except Exception:
        # 如果转发失败，正常发送消息
        plugin_event.reply("发送失败！")
        return
