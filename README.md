# ResearchFollow

每天北京时间 09:00 自动追踪指定期刊与 arXiv 分类的最新论文，筛选最相关的 10 篇并通过邮件汇报。

## 功能
- RSS + arXiv 抓取
- LLM 相关性排序（DeepSeek-R1）
- 按你的问题清单生成结构化“锐评式”摘要
- GitHub Actions 定时运行并自动更新状态

## 配置
- 期刊与关键词配置：`src/config.yaml`
- 状态文件：`state/state.json`

## GitHub Secrets
在仓库 Settings → Secrets and variables → Actions 添加：
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`（默认 `https://openapi.coreshub.cn/v1`，可不填）
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `MAIL_TO`

### QQ/foxmail SMTP 参考
- SMTP 服务器：`smtp.qq.com`
- SSL 端口：`465` 或 `587`
- 使用授权码作为 `SMTP_PASS`

## 本地测试
```bash
pip install -r requirements.txt
python src/main.py --no-email --no-llm --dry-run
```

## 定时任务
GitHub Actions 已配置：`0 1 * * *`（UTC），对应北京时间 09:00。
