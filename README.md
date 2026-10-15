# ima-qiandao

ima（ima.copilot）「每日登录福利」自动签到 —— 通过 GitHub Actions 每天自动领取算力。

签到脚本为纯 Python 标准库实现；登录凭证只存放在 GitHub Secrets（`IMA_CREDENTIALS`），不进入代码。

> **想用这个仓库？** 把它复制到你自己的 GitHub 账号（Fork，或下载文件后新建仓库皆可），
> 按下方流程准备**你自己账号**的凭证。永远不要使用别人提供的凭证文件——它等同于账号钥匙。

## 部署方法

> 全程只需扫码一次（第 1 步获取凭证时），之后每天自动签到、零人工。

### 第 1 步：获取凭证

**方式 A：扫码授权（推荐）** —— 无需安装 ima 客户端，任何电脑可跑

```bash
python ima_recover.py             # 生成二维码 login_qr.png → 微信扫码确认 → 自动写入 credentials.json
python ima_recover.py --to <邮箱>  # 把二维码额外发到邮箱（需配置 IMA_SMTP_* 环境变量）
```

- 没有任何文件也能跑（首次部署场景）：设备 GUID 自动生成并随新凭证落盘
- 二维码约 5 分钟有效，过期自动换新重发（最多 3 次）
- 邮件发送需配置 `IMA_SMTP_HOST` / `IMA_SMTP_PORT` / `IMA_SMTP_USER` / `IMA_SMTP_PASS`（QQ 邮箱用「授权码」）
- 若之前已有凭证，旧文件自动备份为 `credentials.json.bak`；新凭证落盘前先做一次刷新验证

**方式 B：从 ima 客户端提取（备选）** —— 需要装了 ima 且已登录的 Windows 电脑

```bat
:: 完全退出 ima（含托盘图标）后运行
python extract_credentials.py
```

原理：本机解密 ima 内置浏览器的 Cookie 库（Chromium AES-256-GCM，密钥由 Windows DPAPI 保护），全程本地完成、不联网。

### 第 2 步：配置 GitHub Secret

仓库 → Settings → Secrets and variables → Actions → New repository secret

- Name：`IMA_CREDENTIALS`
- Value：`credentials.json` 的全部内容

### 第 3 步：手动验证一次

Actions → 「ima 每日签到」→ Run workflow，日志出现「签到成功」或「今天已签到」即部署完成。

### 部署完成后的行为

- 每天北京时间 **09:07 / 21:07** 自动签到（双跑互为兜底；接口幂等，重复执行无害）
- 每次结果追加到 `history.jsonl` 并自动提交——既留签到记录，也避免 GitHub 因 60 天无活动停用定时任务
- 运行失败时任务标红，GitHub 发送失败通知邮件（不会悄悄断签）

## 凭证失效后怎么办

凭证（refresh token）的有效期由服务端控制，过期后重新扫一次码即可，命令与第 1 步相同：

```bash
python ima_recover.py
```

也可以在 GitHub 上一键恢复：Actions → 「ima 凭证恢复（扫码）」→ Run workflow——生成二维码发到你邮箱、等你扫码、成功后自动回写 `IMA_CREDENTIALS` Secret 并验证签到。需提前配置额外 Secrets：

| Secret | 说明 |
|---|---|
| `IMA_SMTP_HOST` / `IMA_SMTP_PORT` / `IMA_SMTP_USER` / `IMA_SMTP_PASS` | 发件邮箱（二维码发到这个邮箱自己） |
| `GH_PAT` | 有 repo 权限的 GitHub PAT（回写 Secret 用；工作流的 GITHUB_TOKEN 无权写 Secret） |

## 本地定时（可选）

不用 GitHub Actions 也可以本地跑：`python ima_checkin.py`（`--dry-run` 只查状态 / `--json` 机器可读输出），配 Windows 计划任务或 crontab 定时即可。

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
