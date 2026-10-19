# -*- coding: utf-8 -*-
"""回归测试: 满签奖励只在周日试领, 非周日完全静默(不发请求、不打日志);
周日的所有服务端返回码必须被接住, 不能抛异常打断签到。

真实返回码(2026-10-19 实测):
    0    领取成功
    1001 week not fully claimed, dayN unclaimed   未满签
    1002 today already checked in                 今天已签过
    -1   HTTP 403 + 空 body(连续被拒后限流)       必须不抛异常
"""
import io
import json
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import ima_checkin as m

CST = timezone(timedelta(hours=8))
SUNDAY = datetime(2026, 10, 18, 7, 0, tzinfo=CST)     # 周日 07:00 北京时间
MONDAY = datetime(2026, 10, 19, 7, 0, tzinfo=CST)     # 周一 07:00 北京时间
TUESDAY = datetime(2026, 10, 20, 7, 0, tzinfo=CST)    # 周二 07:00 北京时间


def snap(days, bonus_status, total, today_status=3):
    infos = [{"top": d, "status": 4} for d in ["周二", "周三", "周四", "周五", "周六", "周日"]]
    infos.insert(0, {"top": "今日", "status": today_status, "reward": "50算力"})
    infos.append({"top": "满签奖励", "status": bonus_status,
                  "reward": "额外随机奖励", "button": "领取"})
    return {"code": 0, "msg": "ok", "checkin_days": days,
            "total_reward_points": total, "infos": infos}


def run_case(fake_today, bonus_resp, argv_extra=None,
             info_before=None, info_after=None, already_checked_in=False):
    calls = {"daily": 0, "bonus": 0}
    if info_before is None:
        info_before = snap(6, 4, 300)
    if info_after is None:
        info_after = snap(7, 3, 350)
    state = {"info": info_before}

    def fake_info(cookie, token):
        return state["info"]

    def fake_check_in(cookie, token, t):
        if t == m.CHECKIN_TYPE_DAILY:
            calls["daily"] += 1
            state["info"] = info_after
            if already_checked_in:
                return {"code": 1002, "msg": "today already checked in"}
            return {"code": 0, "msg": "ok", "reward_received": 50,
                    "reward_total": 350, "type": 1}
        calls["bonus"] += 1
        state["info"] = snap(7, 2, 440)
        return bonus_resp

    m.get_activity_info = fake_info
    m.check_in = fake_check_in
    m.refresh_access_token = lambda cred: "FAKE"
    m.load_credentials = lambda: {"ima_uid": "u", "uid_type": "2",
                                  "ima_guid": "g", "refresh_token": "r"}

    # 冻结"现在"的北京时间
    m.now_cst = lambda: fake_today

    sys.argv = ["x", "--json"] + (argv_extra or [])
    buf = io.StringIO()
    with redirect_stdout(buf):
        m.main()
    return calls, json.loads(buf.getvalue().strip().splitlines()[-1])


def main():
    results = []
    succ = {"code": 0, "msg": "ok", "reward_received": 90, "reward_total": 440, "type": 2}
    not_full = {"code": 1001, "msg": "week not fully claimed, day2 unclaimed"}
    already = {"code": 1002, "msg": "today already checked in"}
    empty403 = {"code": -1, "msg": "HTTP 403 空响应(可能被限流, 稍后重试)", "http_status": 403}

    # 1) 周一: 完全不碰满签接口, 日志里也不该出现"满签奖励"
    c, r = run_case(MONDAY, succ)
    ok = c["bonus"] == 0 and c["daily"] == 1 and "满签奖励" not in (r.get("message") or "")
    results.append(("周一: 静默跳过(不发请求/不打日志)", ok, c, r.get("message")))

    # 2) 周二: 同样静默
    c, r = run_case(TUESDAY, succ)
    ok = c["bonus"] == 0 and "满签奖励" not in (r.get("message") or "")
    results.append(("周二: 静默跳过", ok, c, r.get("message")))

    # 3) 周日: 成功领到 90
    c, r = run_case(SUNDAY, succ, info_before=snap(7, 3, 350))
    ok = c["bonus"] == 1 and r["weekly_bonus_claimed"] is True \
        and r.get("weekly_bonus_reward") == 90
    results.append(("周日: 领取成功 +90算力", ok, c, r.get("message")))

    # 4) 周日但没签满: 1001 接住, 不影响签到
    c, r = run_case(SUNDAY, not_full)
    ok = c["bonus"] == 1 and r["weekly_bonus_claimed"] is False \
        and r.get("weekly_bonus_reason") == "not_full_week" \
        and r["checkin_performed"] is True
    results.append(("周日未满签: 1001 被接住", ok, c, r.get("message")))

    # 5) 周日撞 403 空响应: 必须不抛异常, 签到照常
    c, r = run_case(SUNDAY, empty403)
    ok = r.get("weekly_bonus_reason") == "error" and r["checkin_performed"] is True
    results.append(("周日 403 空响应: 不抛异常", ok, c, r.get("message")))

    # 6) 周日已签过: 1002
    c, r = run_case(SUNDAY, already, already_checked_in=True)
    ok = r.get("weekly_bonus_reason") == "already_checked_in"
    results.append(("周日重复签到: 1002 被接住", ok, c, r.get("message")))

    # 7) 时区跨天: cron UTC 23:00 在北京是次日 07:00。
    #    UTC 周日 23:00 = 北京周一 07:00, 必须判定为"周一"(静默), 不能误判成周日。
    utc_sunday_2300 = datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)
    beijing = utc_sunday_2300.astimezone(CST)
    c, r = run_case(beijing, succ)
    ok = c["bonus"] == 0 and beijing.weekday() == 0
    results.append(("时区跨天: UTC周日23:00=北京周一07:00 → 静默", ok, c,
                    "判定星期=%d" % beijing.weekday()))

    print("")
    all_ok = True
    for name, ok, c, msg in results:
        all_ok = all_ok and ok
        print("[%s] %s" % ("PASS" if ok else "FAIL", name))
        print("        calls: daily=%d bonus=%d | %s" % (c["daily"], c["bonus"], msg))
    print("")
    print("[TOTAL]", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
