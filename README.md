# ima-qiandao

ima（ima.copilot）「每日登录福利」自动签到 —— 通过 GitHub Actions 每天自动领取算力。

签到脚本为纯 Python 标准库实现；登录凭证只存放在 GitHub Secrets（`IMA_CREDENTIALS`），不进入代码。

> **想用这个仓库？** 把它复制到你自己的 GitHub 账号（Fork，或下载文件后新建仓库皆可），
> 再按下方「如何生成 credentials.json」准备**你自己账号**的凭证。
> 永远不要使用别人提供的凭证文件——它等同于账号钥匙。

## 工作方式

- `.github/workflows/checkin.yml` 定时触发：北京时间 **09:07 / 21:07** 各一次（双跑互为兜底，接口幂等，重复执行无害）
- 每次运行结果追加到 `history.jsonl` 并自动提交——既保留签到记录，也避免 GitHub 因 60 天无活动而停用定时任务
- 运行失败时任务标红，GitHub 会发送失败通知邮件（不会悄悄断签）
- 也可在 Actions 页面手动 Run workflow

## 如何生成 credentials.json（首次 & 失效后）

> `credentials.json` 是签到脚本唯一的「钥匙」（含 refresh token 等字段）。
> **必须在装了 ima 客户端并已登录的那台电脑上生成**——云端没有你的 ima，无法代生成。

前置条件：Windows 电脑 + 已安装并登录 ima 客户端 + Python 3.8+

步骤（约 1 分钟）：

1. 安装依赖（仅首次需要）：

   ```bat
   pip install cryptography -i https://mirrors.aliyun.com/pypi/simple/
   ```

2. **完全退出 ima**（含右下角托盘图标；否则 Cookie 数据库被占用读不了）

3. 运行提取器：

   ```bat
   python extract_credentials.py
   ```

4. 看到「完成: ...credentials.json」后，打开该文件，把**完整 JSON 内容**填入仓库 Secret：
   Settings → Secrets and variables → Actions → New repository secret
   - Name: `IMA_CREDENTIALS`
   - Value: credentials.json 的全部内容

**什么时候需要重新生成**：

- 工作流报「刷新登录失败」（refresh token 到期）
- 你在 ima 里退出过登录 / 换过账号
- 换了新电脑

**重新生成前请注意**：先打开 ima 确认处于正常登录状态（如果已被登出，先在 ima 里重新扫码登录），再完全退出后运行提取器——这样拿到的才是新凭证。

原理：提取器读取 ima 内置浏览器的 Cookie 库（Chromium AES-256-GCM 加密，密钥由 Windows DPAPI 保护），在本机解密出 refresh token。全程本地完成，不联网、不上传任何数据。

其他系统：macOS 版 ima 的存储格式不同，暂未支持。

## 文件说明

| 文件 | 说明 |
|---|---|
| `ima_checkin.py` | 签到脚本（运行时读取同目录 `credentials.json`） |
| `extract_credentials.py` | 凭证提取器（在装了 ima 的 Windows 电脑上运行） |
| `history.jsonl` | 每日运行结果（自动提交） |

## 说明

- 仅供本人账号使用；请勿将 `credentials.json` 提交到仓库或分享给他人
- GitHub 定时任务存在平台性延迟（数分钟到数十分钟），双时间点已做兜底
- 若某天发现定时任务被停用：Actions 页面点「Enable workflow」重新启用即可
