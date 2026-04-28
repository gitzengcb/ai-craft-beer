# ai-craft-beer

自动收集 AI 相关开源项目的 star 增长榜单，并每日 10:00（北京时间）通过钉钉机器人推送到指定手机号。

配置步骤：

1. 在仓库 Settings → Secrets and variables → Actions（或直接访问 https://github.com/gitzengcb/ai-craft-beer/settings/secrets/actions）中添加一个 repository secret：
    - Name: dindin
    - Value: https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN

2. 可选配置（在 workflow 中通过环境变量修改）：
    - DINGTALK_KEYWORD: 要在消息标题中显示的关键词（默认为 `github`）
    - DINGTALK_AT_MOBILE: 如果想 @ 某人，填手机号（例如 `13996477307`）
    - MAX_CANDIDATES / RATE_SLEEP: 控制扫描候选仓库数量与速率

运行与测试：

- 手动触发 Actions：在仓库的 Actions 页面选择 "daily-ai-trending-to-dingtalk" workflow，点击 "Run workflow"。
- 本地测试：
    - 安装依赖：pip install -r requirements.txt
    - 导出 webhook：export DINDIN="https://oapi.dingtalk.com/robot/send?access_token=..."
    - 运行：python scripts/ai_trending_notify.py

安全建议：
- 请将钉钉 webhook 保存为 GitHub Secret（不要明文写入仓库）。
- 若钉钉机器人启用加签（signing），请把签名 secret 另存为仓库 Secret（例如 dindin_sign）并让我帮你把脚本扩展为支持加签。
