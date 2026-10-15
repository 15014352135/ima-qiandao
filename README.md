# ima-qiandao

ima（ima.copilot）「每日登录福利」自动签到 —— 通过 GitHub Actions 每天自动领取算力。

签到脚本为纯 Python 标准库实现；登录凭证只存放在 GitHub Secrets（`IMA_CREDENTIALS`），不进入代码。

> **想用这个仓库？** 把它复制到你自己的 GitHub 账号（Fork，或下载文件后新建仓库皆可），
> 按下方流程准备**你自己账号**的凭证。永远不要使用别人提供的凭证文件——它等同于账号钥匙。

## 什么时候需要扫码？

| 场景 | 需要扫码吗 |
|---|---|
| 日常自动签到（凭证有效期内） | ❌ 零扫码——access token 由脚本自动刷新，永远不用管 |
| 首次获取凭证 | ✅ 扫一次码（约 10 秒） |
| refresh token（大票）失效后恢复 | ✅ 扫一次码（约 10 秒） |

> 为什么：签到的「钥匙」是凭证文件里的 refresh token，它的有效期由服务端控制；
> 过期后必须重新登录，而 ima 登录走微信授权——微信要求本人扫码确认，没有账号密码通道可以绕过
>（除非逆向微信客户端本身，不建议）。所以「扫码」只发生在**获取 / 恢复凭证**这两个时刻，日常签到永远不碰。

## 获取 / 恢复凭证（同一条命令，二选一路径）

### 方式 A：扫码授权 —— 推荐，不需要安装 ima 客户端，任何机器可跑

```bash
python ima_recover.py            # 首次获取 / 失效恢复, 都是这一条
python ima_recover.py --to <邮箱> # 额外把二维码发到邮箱(需配置 IMA_SMTP_* 环境变量)
```

流程：脚本生成微信扫码登录二维码（保存为 `login_qr.png`）→ 手机微信扫码 / 长按识别图片并确认登录 → 脚本轮询拿到授权 code → 自动换取新凭证写入 `credentials.json`。

- 全新机器没有 `credentials.json` 也能跑（设备 GUID 自动生成并随新凭证落盘）
- 二维码约 5 分钟有效，过期自动换新重发（最多 3 次）
- 邮件发送需配置 `IMA_SMTP_HOST` / `IMA_SMTP_PORT` / `IMA_SMTP_USER` / `IMA_SMTP_PASS`（QQ 邮箱用「授权码」）
- 恢复成功后旧凭证自动备份为 `credentials.json.bak`，新凭证先做一次刷新验证再落盘

### 方式 B：从 ima 客户端提取 —— 备选

前置：装了 ima 且已登录的 Windows 电脑。

```bash
python extract_credentials.py
```

原理：读取 ima 内置浏览器的 Cookie 库（Chromium AES-256-GCM 加密，密钥由 Windows DPAPI 保护），在本机解密出 refresh token。全程本地完成，不联网。

### 写入 GitHub Secret（Actions 场景）

把 `credentials.json` 的完整 JSON 内容填入仓库 Secret：
Settings → Secrets and variables → Actions → New repository secret
- Name: `IMA_CREDENTIALS`
- Value: credentials.json 的全部内容

## 凭证失效自动恢复（GitHub Actions 一键版）

refresh token 失效后，在 Actions 页面运行「ima 凭证恢复（扫码）」工作流：它生成二维码发到你邮箱、等你扫码、成功后自动更新 `IMA_CREDENTIALS` Secret 并验证签到。需提前配置额外 Secrets：

| Secret | 说明 |
|---|---|
| `IMA_SMTP_HOST` / `IMA_SMTP_PORT` / `IMA_SMTP_USER` / `IMA_SMTP_PASS` | 发件邮箱（二维码发到这个邮箱自己） |
| `GH_PAT` | 有 repo 权限的 GitHub PAT（用于回写 `IMA_CREDENTIALS`；工作流的 GITHUB_TOKEN 无权写 Secret） |

## 日常签到

- 本地：`python ima_checkin.py`（`--dry-run` 只查状态 / `--json` 机器可读输出）
- GitHub Actions：每天北京时间 **09:07 / 21:07** 自动跑（双跑互为兜底，接口幂等，重复执行无害）
- 每次运行结果追加到 `history.jsonl` 并自动提交——既留签到记录，也避免 GitHub 因 60 天无活动停用定时任务
- 运行失败时任务标红，GitHub 发送失败通知邮件（不会悄悄断签）

## 文件说明

| 文件 | 说明 |
|---|---|
| `ima_checkin.py` | 签到脚本（运行时读取同目录 `credentials.json`） |
| `ima_recover.py` | 凭证获取 / 失效恢复（扫码授权，无需 ima 客户端） |
| `extract_credentials.py` | 凭证提取器（备选：从 ima 客户端本地存储提取，Windows 专用） |
| `history.jsonl` | 每日运行结果（自动提交） |

## 说明

- 仅供本人账号使用；请勿将 `credentials.json` 提交到仓库或分享给他人
- GitHub 定时任务存在平台性延迟（数分钟到数十分钟），双时间点已做兜底
- 若某天发现定时任务被停用：Actions 页面点「Enable workflow」重新启用即可
