#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""从 ima 客户端本地存储提取「每日登录福利」签到所需凭证

要求:
    - Windows, 且本机已登录 ima 客户端 (ima.copilot)
    - 运行前请【完全退出 ima】(包括托盘图标), 否则 Cookie 库被占用无法读取
    - 需要 cryptography 库:  pip install cryptography -i https://mirrors.aliyun.com/pypi/simple/
    - 凭证失效后重新提取: 先打开 ima 确认登录正常(如已被登出请重新扫码), 再完全退出后运行

用法:
    python extract_credentials.py                 # 使用默认路径
    python extract_credentials.py --profile-dir "D:\path\to\User Data"

产物:
    credentials.json  (与签到脚本同目录, 请勿上传/分享)

原理:
    ima 内置浏览器把登录凭证写在 Chromium 的 Cookie 库中(AES-256-GCM 加密,
    密钥在 Local State 里由 Windows DPAPI 保护)。本脚本在本机解密后提取
    refresh_token 等字段, 供每日签到脚本使用。
"""
import argparse
import base64
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

WANTED = ("IMA-UID", "UID-TYPE", "IMA-GUID", "IMA-TOKEN", "IMA-REFRESH-TOKEN")
OUT_FILE = Path(__file__).resolve().with_name("credentials.json")


def dpapi_decrypt(data):
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI 解密失败 (CryptUnprotectData)")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return out


def load_aes_key(user_data_dir):
    local_state_path = user_data_dir / "Local State"
    if not local_state_path.exists():
        sys.exit("[错误] 找不到 %s" % local_state_path)
    with open(local_state_path, "r", encoding="utf-8") as fp:
        state = json.load(fp)
    enc_key = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if enc_key[:5] != b"DPAPI":
        sys.exit("[错误] 未知的密钥格式, 无法解密。")
    return dpapi_decrypt(enc_key[5:])


def read_cookies(db_path, aes_key):
    """返回 {name: value}；db 只读复制一份再解析, 避免文件锁冲突。"""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        sys.exit(
            "[错误] 缺少 cryptography 库, 请先安装:\n"
            "    pip install cryptography -i https://mirrors.aliyun.com/pypi/simple/"
        )

    if not db_path.exists():
        return {}
    tmp = Path(tempfile.mkdtemp(prefix="ima_cred_")) / "Cookies"
    try:
        shutil.copy2(db_path, tmp)
    except OSError:
        sys.exit(
            "[错误] 无法读取 %s\n"
            "请先【完全退出 ima 客户端】(含托盘图标) 后重试。" % db_path
        )
    result = {}
    con = sqlite3.connect(str(tmp))
    try:
        for name, enc in con.execute("SELECT name, encrypted_value FROM cookies"):
            if name not in WANTED or enc is None:
                continue
            if isinstance(enc, str):
                enc = enc.encode("latin-1")
            prefix = enc[:3]
            if prefix in (b"v10", b"v11"):
                plain = AESGCM(aes_key).decrypt(enc[3:15], enc[15:], None)
                # 新版 Chromium 在值前附加 32 字节完整性前缀, 需剥离
                value = plain[32:] if len(plain) > 32 else plain
                try:
                    value = value.decode("utf-8")
                except UnicodeDecodeError:
                    value = plain.decode("utf-8", "replace")
                result[name] = value
            elif prefix == b"v20":
                sys.exit(
                    "[错误] Cookie 使用了 v20(应用绑定)加密, 本脚本暂不支持。\n"
                    "请反馈给助手更新提取方案。"
                )
    finally:
        con.close()
        shutil.rmtree(tmp.parent, ignore_errors=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="提取 ima 签到凭证")
    default_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "ima.copilot" / "User Data"
    parser.add_argument("--profile-dir", default=str(default_dir),
                        help="ima 的 User Data 目录 (默认 %%LOCALAPPDATA%%\\ima.copilot\\User Data)")
    args = parser.parse_args()

    if sys.platform != "win32":
        sys.exit("[错误] 本脚本仅支持 Windows(需要读取 ima 客户端并使用 DPAPI 解密)。")

    user_data = Path(args.profile_dir)
    if not user_data.exists():
        sys.exit("[错误] 目录不存在: %s" % user_data)

    print("[1/3] 读取加密密钥 (Local State + DPAPI)...")
    aes_key = load_aes_key(user_data)

    print("[2/3] 解密 Cookie 库...")
    cookies = {}
    # 主库 + 扩展库都扫一遍, 兼容 ima 版本差异
    for rel in ("Default/Extension Cookies", "Default/Network/Cookies", "Default/Cookies"):
        found = read_cookies(user_data / rel, aes_key)
        if found:
            cookies.update(found)
            print("      %s -> 找到 %d 个字段" % (rel, len(found)))

    missing = [name for name in WANTED if name not in cookies]
    if "IMA-TOKEN" in missing and "IMA-REFRESH-TOKEN" in missing:
        sys.exit(
            "[错误] 未找到登录凭证。请确认:\n"
            "  1) ima 客户端已在本机登录;\n"
            "  2) 提取时已【完全退出】ima;\n"
            "  3) 若因凭证失效而重新提取, 请先打开 ima 确认登录正常(必要时重新扫码)。"
        )

    print("[3/3] 写入 credentials.json ...")
    cred = {
        "ima_uid": cookies.get("IMA-UID", ""),
        "uid_type": cookies.get("UID-TYPE", ""),
        "ima_guid": cookies.get("IMA-GUID", ""),
        "refresh_token": cookies.get("IMA-REFRESH-TOKEN", ""),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not cred["refresh_token"]:
        sys.exit("[错误] 缺少 IMA-REFRESH-TOKEN, 无法长期签到。")
    with open(OUT_FILE, "w", encoding="utf-8") as fp:
        json.dump(cred, fp, ensure_ascii=False, indent=2)
    print("完成: %s" % OUT_FILE)
    print("(该文件等同账号钥匙, 请勿上传或分享)")


if __name__ == "__main__":
    main()
