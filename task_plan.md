# Task Plan: GitHub Actions 文献追踪与邮件汇报

## Goal
在 GitHub Actions 中每天北京时间 9:00 自动抓取与研究领域高度相关的最新期刊论文并通过邮件汇报。

## Current Phase
Phase 1

## Phases

### Phase 1: Requirements & Discovery
- [x] 明确研究领域方向（UBEM+电网+极端气候+韧性）
 - [x] 确认关键词/期刊范围（Nature 子刊清单、arXiv 分类）
 - [x] 确认数据源与优先级（Feedly RSS / arXiv / Nature / Crossref / SS）
 - [x] 确认邮件发送方式与账号（SMTP/第三方服务）
- [x] 记录约束与需求到 findings.md
- **Status:** complete

### Phase 2: Planning & Structure
- [x] 设计工作流（采集→过滤/排序→汇总→邮件）
- [x] 设计 GitHub Actions 定时与状态持久化方案
- [x] 规划脚本结构与配置文件
- **Status:** complete

### Phase 3: Implementation
- [x] 实现抓取与过滤脚本
- [x] 实现日报格式化与邮件发送
- [ ] 配置 Actions 与 secrets
- **Status:** in_progress

### Phase 4: Testing & Verification
- [ ] 本地/Actions 试跑一次
- [ ] 验证时区与去重逻辑
- [ ] 记录测试结果
- **Status:** pending

### Phase 5: Delivery
- [ ] Review outputs
- [ ] Deliver to user
- **Status:** pending

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 计划使用 GitHub Actions cron 01:00 UTC | 对应北京时间 09:00，且中国无夏令时 |

## Errors Encountered
| Error | Resolution |
|-------|------------|
| session-catchup.py 路径错误（.claude） | 改用 /home/dogtoree/.codex/skills/planning-with-files/scripts/session-catchup.py |
