# ima-qiandao

ima「每日登录福利」自动签到，GitHub Actions 每天自动领取算力。部署全程只需扫码一次，之后零人工。

> 用法：Fork 本仓库，按下面三步部署你自己的账号。不要使用任何别人提供的凭证文件。

## 部署方法

### 第 1 步：配置 SMTP Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret，逐个添加（用于把登录二维码发到你邮箱）：

| Secret | 值 |
|---|---|
| `IMA_SMTP_HOST` | SMTP 服务器，QQ 邮箱填 `smtp.qq.com` |
| `IMA_SMTP_PORT` | `465` |
| `IMA_SMTP_USER` | 你的邮箱（二维码会发到这里） |
| `IMA_SMTP_PASS` | SMTP 授权码，不是邮箱密码（QQ 邮箱：设置 → 账号 → POP3/SMTP 服务 → 生成授权码） |

### 第 2 步：扫码授权

Actions → 「ima 凭证恢复（扫码）」→ Run workflow：

1. 工作流生成微信登录二维码，发送到你的邮箱
2. 手机打开邮件，长按二维码图片用微信识别（或保存图片后用微信「扫一扫 → 相册」选取）
3. 在微信里确认登录
4. 工作流自动换取凭证、存入 Actions 缓存并验证签到，全部绿勾即授权完成

二维码 5 分钟有效，过期自动补发（最多 3 次）；错过了就重跑一次工作流。

### 第 3 步：验证

Actions → 「ima 每日签到」→ Run workflow，日志出现「签到成功」或「今天已签到」即部署完成。

### 部署完成后的行为

| 项目 | 说明 |
|---|---|
| 定时 | 每天北京时间 09:07 / 21:07 自动签到，双跑互为兜底（接口幂等，重复无害） |
| 记录 | 每次结果追加到 `history.jsonl` 并自动提交，避免 60 天无活动被停用 |
| 告警 | 运行失败任务标红，GitHub 发送失败邮件 |

> Fork 的仓库需先在 Actions 页面点「I understand…Enable workflows」启用工作流。

## 凭证存在哪？公开仓库会泄露吗？

不会。凭证（`credentials.json`）**不进 git 仓库**，持久化在 GitHub Actions Cache 中——缓存不属于仓库内容，对外没有任何下载端点，仓库访客不可见（与 [Rainyun-Qiandao](https://github.com/LeapYa/Rainyun-Qiandao) 用 actions/cache 持久化 cookie 同款方案）。仓库保持 Public 也不泄露。

## 凭证失效后怎么办

凭证有效期由服务端控制。失效后「ima 每日签到」会失败并收到邮件提醒——重新执行**第 2 步**（同一条工作流）即可，无需其他操作。

## 不想配邮箱？本地备选方案

在任意电脑上（无需安装 ima 客户端）：

```bash
python ima_recover.py
```

脚本在当前目录生成 `login_qr.png`，微信扫码后凭证写入 `credentials.json`。GitHub 环境请把该文件内容存入 Actions Cache 或 Secret（勿提交进仓库）。装了 ima 客户端的 Windows 机器也可以用 `python extract_credentials.py` 直接提取，效果相同。

## 文件说明

| 文件 | 说明 |
|---|---|
| `.github/workflows/checkin.yml` | 每日签到工作流 |
| `.github/workflows/recover.yml` | 扫码授权 / 凭证恢复工作流 |
| `ima_checkin.py` | 签到脚本（纯标准库） |
| `ima_recover.py` | 扫码授权脚本（被 recover 工作流调用，也可本地运行） |
| `extract_credentials.py` | 从 ima 客户端提取凭证（备选，Windows 专用） |
| `history.jsonl` | 每日签到记录（自动提交） |
