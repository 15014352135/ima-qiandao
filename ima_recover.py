#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ima 凭证获取 / 失效恢复（微信扫码授权, 不需要安装 ima 客户端）

什么时候需要扫码:
  - 日常自动签到: 不需要(凭证有效期内 refresh token 每次自动换新)
  - 首次获取凭证 / refresh token(大票)失效: 扫一次码, 这是唯一的身份验证方式

流程:
  1. 已有凭证且未失效 -> 直接退出(加 --force 可跳过检查)
  2. 否则 -> 通过微信开放平台 qrconnect 生成扫码登录二维码
  3. 二维码保存为 login_qr.png; 可选通过 SMTP 邮件发送(--to)
  4. 轮询扫码结果(手机微信扫码/长按识别图片 -> 确认登录)
  5. 拿到 code 后调用 ima 登录接口换取新凭证, 写回 credentials.json

用法:
    python ima_recover.py                  # 首次获取 / 失效恢复, 同一条命令
    python ima_recover.py --to me@qq.com  # 额外把二维码发到邮箱(需配置 IMA_SMTP_* 环境变量)
    python ima_recover.py --dry-run        # 只生成二维码, 不轮询
    python ima_recover.py --force          # 跳过"凭证还活着"检查, 强制重新扫码
    python ima_recover.py --update-gh-secret --repo LeapYa/ima-qiandao
                                           # 成功后调用 gh CLI 更新 GitHub Secret(需 GH_TOKEN 环境变量)

邮件环境变量(使用 --to 时必需):
    IMA_SMTP_HOST  例如 smtp.qq.com
    IMA_SMTP_PORT  例如 465 (SSL)
    IMA_SMTP_USER  发件邮箱
    IMA_SMTP_PASS  SMTP 授权码(不是邮箱密码)

二维码有效期约 5 分钟, 过期会自动生成新的并(若配置了邮件)重发, 最多 3 次。
恢复成功后新凭证写入 credentials.json(旧文件备份为 credentials.json.bak)。
全新机器没有 credentials.json 也能跑: 设备 GUID 会自动生成并随新凭证一起落盘。
"""
import argparse
import json
import os
import re
import shutil
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuidlib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

APPID = "wx0d63f5de059f1d52"
CHECKIN_PAGE = "https://ima.qq.com/copilot-token-daily-checkin/pc"
WX_AUTH = "https://ima.qq.com/wx-auth/"
QRCONNECT_URL = "https://open.weixin.qq.com/connect/qrconnect"
QRCODE_URL = "https://open.weixin.qq.com/connect/qrcode/"
POLL_URL = "https://lp.open.weixin.qq.com/connect/l/qrconnect?uuid="
REFRESH_URL = "https://ima.qq.com/cgi-bin/auth_login/refresh"
LOGIN_URL = "https://ima.qq.com/cgi-bin/auth_login/login"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"}
BASE_HEADERS = {
    "Content-Type": "application/json",
    "from_browser_ima": "1",
    "extension_version": "5.17.2",
}

HERE = Path(__file__).resolve().parent
CRED_FILE = HERE / "credentials.json"
QR_FILE = HERE / "login_qr.png"

ACCOUNT_TYPE_WX = 2
QR_MAX_ATTEMPTS = 3
QR_LIFETIME_SECONDS = 300


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.build_opener().open(req, timeout=timeout) as resp:
        return resp.read()


def http_post_json(url, body, headers, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.build_opener().open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gen_guid():
    """生成 16 位数字设备 GUID(与 ima 客户端格式一致; 全新机器无 credentials.json 时使用)"""
    import random

    return str(random.randint(10**15, 10**16 - 1))


def try_refresh(cred):
    """用旧 refresh_token 试刷新, 返回 (是否存活, 说明)"""
    device_cookie = "IMA-GUID=%s; PLATFORM=H5" % cred.get("ima_guid", "")
    body = {
        "userId": cred.get("ima_uid", ""),
        "refreshToken": cred.get("refresh_token", ""),
        "tokenType": -1,
    }
    headers = dict(BASE_HEADERS)
    headers["x-ima-cookie"] = device_cookie
    try:
        data = http_post_json(REFRESH_URL, body, headers)
    except Exception as exc:
        return False, "网络错误: %s" % exc
    if data.get("code") == 0 and data.get("token"):
        return True, "refresh 成功, 凭证仍然有效"
    return False, "code=%s msg=%s" % (data.get("code"), data.get("msg"))


def gen_qr():
    """生成扫码登录二维码, 返回 (uuid, png_bytes, 授权页URL)"""
    state = uuidlib.uuid4().hex
    redirect_uri = WX_AUTH + "?v=2&r=" + urllib.parse.quote(CHECKIN_PAGE, safe="")
    url = (
        QRCONNECT_URL
        + "?appid=" + APPID
        + "&redirect_uri=" + urllib.parse.quote(redirect_uri, safe="")
        + "&response_type=code"
        + "&scope=snsapi_login"
        + "&state=" + state
        + "&login_type=jssdk&self_redirect=default#wechat_redirect"
    )
    html = http_get(url).decode("utf-8", "replace")
    m = (
        re.search(r'uuid\s*=\s*["\']([0-9a-zA-Z=_\-]+)["\']', html)
        or re.search(r'"uuid"\s*:\s*"([0-9a-zA-Z=_\-]+)"', html)
        or re.search(r"/qrcode/([0-9a-zA-Z=_\-]+)", html)
    )
    if not m:
        raise RuntimeError("授权页中未找到 uuid, 页面可能已改版 (len=%d)" % len(html))
    qr_uuid = m.group(1)
    png = http_get(QRCODE_URL + qr_uuid)
    return qr_uuid, png, url


def poll_code(qr_uuid, deadline):
    """轮询扫码结果; 返回 code 或 None(过期/超时)"""
    while time.time() < deadline:
        try:
            body = http_get(POLL_URL + qr_uuid, timeout=40).decode("utf-8", "replace")
        except Exception:
            time.sleep(2)
            continue
        m = re.search(r"wx_errcode=(\d+)", body)
        err = int(m.group(1)) if m else -1
        if err == 405:
            m2 = re.search(r"wx_code='([^']*)'", body)
            return (m2.group(1) if m2 else None) or None
        if err in (402, 403):
            return None  # 二维码过期/被取消
        # 408=等待扫码, 404=已扫码待确认 -> 继续轮询
        time.sleep(2)
    return None


def login_exchange(code, guid):
    """用微信 OAuth code 换取新凭证"""
    body = {
        "accountType": ACCOUNT_TYPE_WX,
        "code": code,
        "authAppid": APPID,
        "clientInfo": {"guid": guid, "platform": 4, "qimei36": ""},
    }
    headers = dict(BASE_HEADERS)
    headers["x-ima-cookie"] = "IMA-GUID=%s; PLATFORM=H5" % guid
    data = http_post_json(LOGIN_URL, body, headers)
    if data.get("code") != 0:
        raise RuntimeError("登录失败: code=%s msg=%s" % (data.get("code"), data.get("msg")))

    def pick(*names):
        for n in names:
            if data.get(n):
                return data[n]
        return None

    return {
        "token": pick("token"),
        "refresh_token": pick("refreshToken", "refresh_token"),
        "ima_uid": pick("userId", "user_id"),
        "id_type": pick("idType", "id_type"),
    }


def send_mail(to, png_path):
    host = os.environ.get("IMA_SMTP_HOST")
    port = int(os.environ.get("IMA_SMTP_PORT", "465"))
    user = os.environ.get("IMA_SMTP_USER")
    password = os.environ.get("IMA_SMTP_PASS")
    if not (host and user and password):
        print("      (未配置 IMA_SMTP_* 环境变量, 跳过邮件发送, 请直接查看 %s)" % png_path)
        return
    msg = MIMEMultipart()
    msg["Subject"] = "ima 登录二维码 - 请用微信扫码恢复自动签到"
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText("请用微信扫描附件中的二维码并确认登录, 扫码后签到凭证会自动恢复。\n二维码过期后脚本会自动补发新的。", "plain", "utf-8"))
    with open(png_path, "rb") as fp:
        img = MIMEImage(fp.read())
    img.add_header("Content-Disposition", "attachment", filename="ima_login_qr.png")
    msg.attach(img)
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        smtp = smtplib.SMTP(host, port, timeout=20)
        smtp.starttls()
    try:
        smtp.login(user, password)
        smtp.sendmail(user, [to], msg.as_string())
    finally:
        smtp.quit()
    print("      二维码已发送至 %s" % to)


def update_gh_secret(repo):
    """通过 gh CLI 更新 IMA_CREDENTIALS Secret (需要 GH_TOKEN 环境变量)"""
    import subprocess

    env = dict(os.environ)
    if not env.get("GH_TOKEN"):
        print("      (未设置 GH_TOKEN, 跳过 GitHub Secret 更新)")
        return False
    r = subprocess.run(
        ["gh", "secret", "set", "IMA_CREDENTIALS", "--repo", repo, "-R", repo],
        stdin=open(CRED_FILE, "rb"),
        env=env,
        capture_output=True,
    )
    if r.returncode == 0:
        print("      GitHub Secret IMA_CREDENTIALS 已更新 (%s)" % repo)
        return True
    print("      gh secret set 失败:", r.stderr.decode("utf-8", "replace")[:200])
    return False


def main():
    parser = argparse.ArgumentParser(description="ima 凭证获取/恢复(微信扫码授权, 无需安装 ima 客户端)")
    parser.add_argument("--to", help="接收二维码的邮箱(需配置 IMA_SMTP_* 环境变量)")
    parser.add_argument("--dry-run", action="store_true", help="只生成二维码, 不轮询不写回")
    parser.add_argument("--force", action="store_true", help="跳过'凭证还活着'检查, 强制重新扫码")
    parser.add_argument("--timeout", type=int, default=900, help="总轮询时限(秒), 默认 900")
    parser.add_argument("--guid", help="设备 GUID(默认沿用 credentials.json 中的值, 没有则自动生成)")
    parser.add_argument("--update-gh-secret", metavar="REPO", help="成功后用 gh CLI 更新该仓库的 IMA_CREDENTIALS Secret")
    args = parser.parse_args()

    if CRED_FILE.exists():
        with open(CRED_FILE, "r", encoding="utf-8") as fp:
            cred = json.load(fp)
        has_old = bool(cred.get("refresh_token"))
    else:
        cred = {}
        has_old = False
        print("[提示] 未找到 credentials.json —— 全新初始化模式(不需要安装 ima 客户端)。")

    guid = args.guid or cred.get("ima_guid") or gen_guid()

    if has_old and not args.force:
        print("[1/4] 检查旧凭证...")
        alive, why = try_refresh(cred)
        if alive:
            print("      %s —— 无需恢复, 直接退出。" % why)
            return 0
        print("      旧凭证已失效 (%s), 进入恢复流程。" % why)
    else:
        reason = "--force" if args.force else "无旧凭证"
        print("[1/4] 跳过存活检查(%s)。" % reason)

    print("[2/4] 生成扫码登录二维码...")
    deadline = time.time() + args.timeout
    code = None
    for attempt in range(1, QR_MAX_ATTEMPTS + 1):
        try:
            qr_uuid, png, _page = gen_qr()
        except Exception as exc:
            sys.exit("[错误] 生成二维码失败: %s" % exc)
        QR_FILE.write_bytes(png)
        print("      第 %d 张二维码已保存: %s" % (attempt, QR_FILE))
        if args.to:
            try:
                send_mail(args.to, str(QR_FILE))
            except Exception as exc:
                print("      邮件发送失败: %s" % exc)
        if args.dry_run:
            print("[dry-run] 已生成二维码, 不轮询。")
            return 0
        print("[3/4] 等待扫码确认 (用微信扫 %s , 或长按邮件中的二维码图片识别)..." % QR_FILE.name)
        code = poll_code(qr_uuid, min(deadline, time.time() + QR_LIFETIME_SECONDS))
        if code:
            break
        if time.time() >= deadline:
            break
        print("      二维码已过期/未扫码, 自动换新的...")
    if not code:
        sys.exit("[失败] 超时未完成扫码。请重新运行本脚本。")

    print("[4/4] 用 code 换取新凭证...")
    try:
        new = login_exchange(code, guid)
    except Exception as exc:
        sys.exit("[错误] %s" % exc)
    if not new.get("refresh_token"):
        sys.exit("[错误] 登录响应中没有 refresh_token: %s" % json.dumps(new, ensure_ascii=False)[:200])

    backup = CRED_FILE.with_suffix(".json.bak")
    if CRED_FILE.exists():
        shutil.copy2(CRED_FILE, backup)
    new_cred = {
        "ima_uid": new.get("ima_uid") or cred.get("ima_uid", ""),
        "uid_type": str(new.get("id_type") or cred.get("uid_type") or "2"),
        "ima_guid": guid,
        "refresh_token": new["refresh_token"],
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(CRED_FILE, "w", encoding="utf-8") as fp:
        json.dump(new_cred, fp, ensure_ascii=False, indent=2)
    print("      新凭证已写入 %s (旧文件备份为 %s)" % (CRED_FILE.name, backup.name))

    alive, why = try_refresh(new_cred)
    if alive:
        print("      新凭证验证通过。")
    else:
        print("      [警告] 新凭证验证未通过: %s" % why)

    if args.update_gh_secret:
        update_gh_secret(args.update_gh_secret)
    print("恢复完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
