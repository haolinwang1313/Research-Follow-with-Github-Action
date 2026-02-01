# Findings & Decisions

## Requirements
- 每天自动追踪与研究领域高度相关的最新期刊论文
- 北京时间 09:00 定时发送邮件汇报
- 使用 GitHub Actions 实现定时与自动化
- 研究重点：城市建筑能源模拟（UBEM）+真实电网数据耦合，在极端气候下进行韧性提升分析
- 关注方向：城市/建筑-电网耦合、极端气候建模、韧性评估与提升
- 输出需用中文，并按用户关心问题进行结构化总结

## Research Findings
- GitHub Actions cron 使用 UTC，需换算北京时间 09:00 → 01:00 UTC
- 可选数据源：Crossref（期刊元数据）、arXiv（预印本）、Semantic Scholar（综合）、OpenAlex（补充元数据）
- 去重与增量：可记录上次运行时间或已发送 DOI 列表（state.json）
- 用户指定来源：Feedly RSS（IEEE Xplore TOC59）、arXiv、Nature 旗下期刊
- 期刊多为订阅制，需基于摘要/元数据进行总结；可尝试抓取开放摘要或二次数据源
- Nature 期刊通常提供 Web Feeds 页面并指向 feeds.nature.com 的 RSS（含 current 与 aop 两类）
- “npj sustainable city”更可能对应 Nature Portfolio 的 “npj Urban Sustainability”（站点路径 npjurbansustain）
- Nature Energy RSS：feeds.nature.com/nenergy/rss/current （另有 /rss/aop）
- Nature Sustainability RSS：feeds.nature.com/nsustain/rss/current （另有 /rss/aop）
- Nature Communications RSS：feeds.nature.com/ncomms/rss/current （另有 /rss/aop）
- Communications Earth & Environment RSS：feeds.nature.com/commsenv/rss/current （另有 /rss/aop）
- npj Urban Sustainability RSS：feeds.nature.com/npjurbansustain/rss/current （另有 /rss/aop）
- Nature Climate Change RSS：feeds.nature.com/nclimate/rss/current （另有 /rss/aop）
- QQ 邮箱 SMTP：服务器 smtp.qq.com，SSL 端口 465 / 587；需开启服务并使用授权码

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 日报窗口基于“上次运行时间” | 避免重复推送，便于增量追踪 |
| 先走 RSS/元数据，再用 AI 总结 | 订阅期刊全文难抓取，摘要更可行 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| session-catchup.py 初始路径不可用 | 改用 .codex/skills 路径 |

## Resources
- 用户关心问题（需逐篇回答）：
  - 文献名称/期刊/作者简介
  - 解决的问题
  - 对建筑/电网韧性评估的必要性、为何常见于 IEEE 标准节点
  - 为什么过去难以城市级韧性评估
  - 算例数据：建筑侧/电网侧数据与来源
  - 创新点（数学/建模/其他）
  - 作为 reviewer 的优缺点与改进建议、对用户研究的指导
- 待用户确认：
  - Nature 旗下期刊具体清单
  - arXiv 分类或关键词范围
  - AI 总结使用的模型与 API key（OpenAI/其他/本地）
  - 每日上限（篇数）与优先级规则
  - 邮件发送方式（SMTP 服务商、发件邮箱、收件人）
