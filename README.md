# ima-qiandao

ima（ima.copilot）「每日登录福利」自动签到 —— 通过 GitHub Actions 每天自动领取算力。

签到脚本为纯 Python 标准库实现；登录凭证只存放在 GitHub Secrets（`IMA_CREDENTIALS`），不进入代码。

## 工作方式

- `.github/workflows/checkin.yml` 定时触发：北京时间 **09:07 / 21:07** 各一次（双跑互为兜底，接口幂等，重复执行无害）
- 每次运行结果追加到 `history.jsonl` 并自动提交——既保留签到记录，也避免 GitHub 因 60 天无活动而停用定时任务
- 运行失败时任务标红，GitHub 会发送失败通知邮件（不会悄悄断签）

## 首次配置

1. 仓库 → Settings → Secrets and variables → Actions → New repository secret
   - Name: `IMA_CREDENTIALS`
   - Value: 本地生成的 `credentials.json` 的完整 JSON 内容
2. Actions → 「ima 每日签到」 → Run workflow（手动触发一次验证）

## 凭证失效后

在本地（ima 客户端所在电脑，Windows）重新运行 `extract_credentials.py` 生成新凭证，
然后把内容更新到 `IMA_CREDENTIALS` Secret（Settings → Secrets → Update）即可，约 30 秒。

## 文件说明

| 文件 | 说明 |
|---|---|
| `ima_checkin.py` | 签到脚本（运行时读取同目录 `credentials.json`） |
| `extract_credentials.py` | 凭证提取器（Windows 本地使用，需先完全退出 ima 客户端） |
| `history.jsonl` | 每日运行结果（自动提交） |

## 说明

- 仅供本人账号使用；请勿将 `credentials.json` 提交到仓库或分享给他人
- GitHub 定时任务存在平台性延迟（数分钟到数十分钟），双时间点已做兜底
- 若某天发现定时任务被停用：Actions 页面点「Enable workflow」重新启用即可
