#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ima「每日登录福利」自动签到

用法:
    python ima_checkin.py            执行签到
    python ima_checkin.py --dry-run  只查询状态, 不签到
    python ima_checkin.py --json     机器可读的一行 JSON 输出

凭证放在同目录 credentials.json (由 extract_credentials.py 生成)。
仅使用 Python 标准库, 任何 3.8+ 的 Python 都可运行。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_URL = "https://ima.qq.com"
REFRESH_URL = BASE_URL + "/cgi-bin/auth_login/refresh"
ACTIVITY_INFO_URL = BASE_URL + "/cgi-bin/daily_login_activity/get_activity_info"
CHECK_IN_URL = BASE_URL + "/cgi-bin/daily_login_activity/check_in"

# 与 ima 内置浏览器一致的固定请求头(服务器不严格校验具体值)
FROM_BROWSER_IMA = "1"
EXTENSION_VERSION = "5.17.2"

CHECKIN_TYPE_DAILY = 1
CHECKIN_TYPE_WEEKLY_BONUS = 2

# 服务端状态枚举(来自页面 JS): 1=已过期 2=已领取 3=可领取 4=未解锁
STATUS_CLAIMED = 2
STATUS_AVAILABLE = 3
STATUS_TEXT = {0: "未知", 1: "已过期", 2: "已领取", 3: "可领取", 4: "未解锁"}

CRED_FILE = Path(__file__).resolve().with_name("credentials.json")


def _to_int32(value):
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def bkn(token):
    """复刻页面 JS 的 djb2 签名算法(l_ 函数), 输出 x-ima-bkn 头。"""
    result = 5381
    for ch in token:
        result += _to_int32(_to_int32(result) << 5) + ord(ch)
    return _to_int32(result) & 0x7FFFFFFF


def http_post_json(url, body, headers, timeout=20):
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            raise RuntimeError("HTTP %s: %s" % (exc.code, raw[:200])) from None


def load_credentials():
    if not CRED_FILE.exists():
        sys.exit(
            "[错误] 找不到 credentials.json。\n"
            "请先完全退出 ima 客户端, 再运行: python extract_credentials.py"
        )
    with open(CRED_FILE, "r", encoding="utf-8") as fp:
        cred = json.load(fp)
    for key in ("ima_uid", "uid_type", "ima_guid", "refresh_token"):
        if not cred.get(key):
            sys.exit("[错误] credentials.json 缺少字段 %r, 请重新提取。" % key)
    return cred


def build_cookie(cred, token):
    parts = [
        "IMA-UID=%s" % cred["ima_uid"],
        "IMA-TOKEN=%s" % token,
        "IMA-REFRESH-TOKEN=%s" % cred["refresh_token"],
        "UID-TYPE=%s" % cred["uid_type"],
        "IMA-GUID=%s" % cred["ima_guid"],
        "PLATFORM=H5",
    ]
    return "; ".join(parts)


def auth_headers(cookie, token=None):
    headers = {
        "Content-Type": "application/json",
        "from_browser_ima": FROM_BROWSER_IMA,
        "extension_version": EXTENSION_VERSION,
        "x-ima-cookie": cookie,
    }
    if token:
        headers["x-ima-bkn"] = str(bkn(token))
    return headers


def refresh_access_token(cred):
    """用长期 refresh_token 换 2 小时有效的 access token。"""
    device_cookie = "IMA-GUID=%s; PLATFORM=H5" % cred["ima_guid"]
    body = {
        "userId": cred["ima_uid"],
        "refreshToken": cred["refresh_token"],
        "tokenType": -1,
    }
    data = http_post_json(REFRESH_URL, body, auth_headers(device_cookie))
    token = data.get("token")
    if data.get("code") != 0 or not token:
        sys.exit(
            "[错误] 刷新登录失败: code=%s msg=%s\n"
            "refresh_token 可能已失效。请完全退出 ima 后运行 extract_credentials.py 重新提取。"
            % (data.get("code"), data.get("msg"))
        )
    return token


def get_activity_info(cookie, token):
    return http_post_json(ACTIVITY_INFO_URL, {}, auth_headers(cookie, token))


def check_in(cookie, token, checkin_type):
    return http_post_json(CHECK_IN_URL, {"type": checkin_type}, auth_headers(cookie, token))


def find_item(info, top):
    for item in info.get("infos") or []:
        if item.get("top") == top:
            return item
    return None


def week_summary(info):
    cells = []
    for item in info.get("infos") or []:
        top = item.get("top") or "?"
        status = item.get("status")
        mark = {2: "已领", 3: "今天", 4: "未解锁"}.get(status, STATUS_TEXT.get(status, "?"))
        cells.append("%s:%s" % (top, mark))
    return "  ".join(cells)


def main():
    parser = argparse.ArgumentParser(description="ima 每日登录福利自动签到")
    parser.add_argument("--dry-run", action="store_true", help="只查询状态, 不签到")
    parser.add_argument("--json", dest="as_json", action="store_true", help="输出一行 JSON")
    args = parser.parse_args()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cred = load_credentials()

    token = refresh_access_token(cred)
    cookie = build_cookie(cred, token)

    info = get_activity_info(cookie, token)
    if info.get("code") != 0:
        sys.exit("[错误] 查询活动失败: code=%s msg=%s" % (info.get("code"), info.get("msg")))

    today = find_item(info, "今日")
    if today is None:
        sys.exit("[错误] 未找到今日条目, 活动可能已改版, 请检查。")

    result = {
        "time": now,
        "today_status": today.get("status"),
        "dry_run": args.dry_run,
        "checkin_performed": False,
        "checkin_result": None,
        "weekly_bonus_claimed": False,
        "checkin_days": info.get("checkin_days"),
        "total_reward_points": info.get("total_reward_points"),
    }

    if today.get("status") == STATUS_AVAILABLE:
        if args.dry_run:
            result["message"] = "今天可签到 (dry-run, 未执行)"
        else:
            resp = check_in(cookie, token, CHECKIN_TYPE_DAILY)
            result["checkin_performed"] = True
            result["checkin_result"] = resp
            if resp.get("code") == 0:
                result["message"] = "签到成功, 获得 %s" % (
                    resp.get("rewardReceived") or today.get("reward") or "奖励"
                )
            else:
                result["message"] = "签到返回 code=%s msg=%s" % (resp.get("code"), resp.get("msg"))
    elif today.get("status") == STATUS_CLAIMED:
        result["message"] = "今天已签到"
    else:
        result["message"] = "今天不可签到 (status=%s)" % today.get("status")

    # 满签奖励: 连续 7 天时可领, 顺手自动领取
    bonus = find_item(info, "满签奖励")
    if (
        bonus is not None
        and bonus.get("status") == STATUS_AVAILABLE
        and not args.dry_run
    ):
        resp = check_in(cookie, token, CHECKIN_TYPE_WEEKLY_BONUS)
        result["weekly_bonus_claimed"] = resp.get("code") == 0
        result["weekly_bonus_result"] = resp

    # 签到后刷新一次状态
    if result["checkin_performed"]:
        info = get_activity_info(cookie, token)
        result["total_reward_points"] = info.get("total_reward_points")
        result["checkin_days"] = info.get("checkin_days")

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
        return

    print("[ima 每日签到] %s" % now)
    print("本周进度: %s" % week_summary(info))
    print("累计: 已签到 %s 天, 共 %s 算力" % (info.get("checkin_days"), info.get("total_reward_points")))
    print(result["message"])


if __name__ == "__main__":
    main()
