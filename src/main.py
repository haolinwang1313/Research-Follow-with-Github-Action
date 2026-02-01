import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import feedparser
import requests
import yaml
from dateutil import parser as dateparser
from openai import OpenAI
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

USER_AGENT = "ResearchFollow/1.0 (+https://github.com)"


@dataclass
class Paper:
    title: str
    authors: List[str]
    journal: str
    link: str
    abstract: str
    published: datetime
    source: str
    source_group: str
    doi: Optional[str] = None
    keyword_hits: int = 0
    group_hits: int = 0
    relevance_score: Optional[int] = None
    relevance_reason: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"last_run": None, "sent_ids": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9]+", "", title)
    return title


def parse_entry_date(entry: Dict[str, Any]) -> Optional[datetime]:
    for key in ("published", "updated", "pubDate"):
        val = entry.get(key)
        if val:
            try:
                dt = dateparser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                continue
    return None


def fetch_url(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def collect_rss_sources(sources: List[Dict[str, Any]], default_group: str) -> List[Paper]:
    papers: List[Paper] = []
    for src in sources:
        url = src["url"]
        group = src.get("group", default_group)
        try:
            content = fetch_url(url)
        except Exception as exc:
            print(f"[warn] RSS fetch failed: {url} ({exc})")
            continue
        feed = feedparser.parse(content)
        journal_name = src.get("name") or feed.feed.get("title", "Unknown Source")
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            if not title:
                continue
            authors = [a.get("name", "").strip() for a in entry.get("authors", []) if a.get("name")]
            link = entry.get("link", "")
            abstract = strip_html(entry.get("summary", "") or entry.get("description", ""))
            published = parse_entry_date(entry)
            if not published:
                published = datetime.now(timezone.utc)
            doi = None
            for key in ("doi", "dc_identifier"):
                doi_val = entry.get(key)
                if doi_val:
                    doi = str(doi_val)
                    break
            papers.append(
                Paper(
                    title=title,
                    authors=authors,
                    journal=journal_name,
                    link=link,
                    abstract=abstract,
                    published=published,
                    source=src.get("name", journal_name),
                    source_group=group,
                    doi=doi,
                )
            )
    return papers


def collect_arxiv(categories: List[str], max_results: int, use_updated: bool) -> List[Paper]:
    if not categories:
        return []
    query = " OR ".join([f"cat:{c}" for c in categories])
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query={query}&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )
    try:
        content = fetch_url(url)
    except Exception as exc:
        print(f"[warn] arXiv fetch failed: {exc}")
        return []
    feed = feedparser.parse(content)
    papers: List[Paper] = []
    for entry in feed.entries:
        title = entry.get("title", "").replace("\n", " ").strip()
        if not title:
            continue
        authors = [a.get("name", "").strip() for a in entry.get("authors", []) if a.get("name")]
        link = entry.get("link", "")
        abstract = strip_html(entry.get("summary", ""))
        published = parse_entry_date({"published": entry.get("updated" if use_updated else "published", "")})
        if not published:
            published = datetime.now(timezone.utc)
        papers.append(
            Paper(
                title=title,
                authors=authors,
                journal="arXiv",
                link=link,
                abstract=abstract,
                published=published,
                source="arXiv",
                source_group="arxiv",
                doi=None,
            )
        )
    return papers


def dedupe(papers: List[Paper], sent_ids: Iterable[str]) -> List[Paper]:
    seen = set(sent_ids)
    unique: List[Paper] = []
    for p in papers:
        fingerprint = None
        if p.doi:
            fingerprint = f"doi:{p.doi.lower().strip()}"
        else:
            fingerprint = f"title:{normalize_title(p.title)}"
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(p)
    return unique


def filter_by_date(papers: List[Paper], start: datetime) -> List[Paper]:
    return [p for p in papers if p.published >= start]


def keyword_score(text: str, keywords: List[str]) -> int:
    score = 0
    text_low = text.lower()
    for kw in keywords:
        if kw.lower() in text_low:
            score += 1
    return score


def group_score(text: str, groups: List[Dict[str, Any]]) -> int:
    if not groups:
        return 0
    text_low = text.lower()
    matched = 0
    for group in groups:
        any_list = group.get("any", [])
        for kw in any_list:
            if kw.lower() in text_low:
                matched += 1
                break
    return matched


def should_exclude_title(title: str, prefixes: List[str]) -> bool:
    if not prefixes:
        return False
    title_low = title.strip().lower()
    for prefix in prefixes:
        if title_low.startswith(prefix.lower()):
            return True
    return False


def build_client() -> Optional[OpenAI]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://openapi.coreshub.cn/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


def extract_json(content: str) -> Dict[str, Any]:
    content = content.strip()
    try:
        return json.loads(content)
    except Exception:
        pass
    match = re.search(r"\{.*\}", content, re.S)
    if not match:
        raise ValueError("No JSON found")
    return json.loads(match.group(0))


def llm_relevance(client: OpenAI, model: str, focus: str, paper: Paper) -> Dict[str, Any]:
    system = (
        "你是学术文献筛选助手。只使用给定的论文信息判断相关性，"
        "不得凭空编造。输出严格 JSON。"
    )
    user = (
        f"研究方向：{focus}\n\n"
        "论文信息：\n"
        f"标题：{paper.title}\n"
        f"期刊/来源：{paper.journal}\n"
        f"作者：{', '.join(paper.authors) if paper.authors else '未知'}\n"
        f"摘要：{paper.abstract or '无'}\n\n"
        "请给出与研究方向的相关性评分（0-100），并给出不超过40字理由。"
        "返回 JSON：{\"score\": 0-100, \"reason\": \"...\"}"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return extract_json(resp.choices[0].message.content)
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
        )
        return extract_json(resp.choices[0].message.content)


def llm_summary(client: OpenAI, model: str, focus: str, paper: Paper, language: str) -> Dict[str, Any]:
    system = (
        "你是学术研究助理。只使用给定的论文信息，不得臆造或扩写未提供的事实。"
        "如果信息缺失，请写“未在摘要中给出”。"
        "问题2与问题3如果是通用性解释，请在句尾标注“[通用判断]”。"
        "输出严格 JSON。"
    )
    user = (
        f"研究方向：{focus}\n\n"
        "论文信息：\n"
        f"标题：{paper.title}\n"
        f"期刊/来源：{paper.journal}\n"
        f"作者：{', '.join(paper.authors) if paper.authors else '未知'}\n"
        f"发布日期：{paper.published.strftime('%Y-%m-%d')}\n"
        f"摘要：{paper.abstract or '无'}\n\n"
        "请用中文回答以下问题，并返回 JSON，字段如下：\n"
        "brief：文献名称/期刊/作者的简要介绍\n"
        "problem：这篇文章具体解决的问题\n"
        "necessity：对建筑/电网侧韧性评估开展的必要性\n"
        "why_ieee_nodes：为何很多研究电力系统的人只对 IEEE 标准节点研究\n"
        "why_city_level_missing：为何之前的研究难以做到城市级别韧性评估\n"
        "data_cases：算例数据是什么？建筑侧/电网侧数据有哪些？来源哪里\n"
        "innovation：创新点体现在哪里（数学/建模/其他）\n"
        "reviewer_critique：作为 reviewer 的锐评（优势/不足/改进方向），并对后续研究给出指导\n"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return extract_json(resp.choices[0].message.content)
    except Exception:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
        return extract_json(resp.choices[0].message.content)


def build_email(papers: List[Paper], window_start: datetime, window_end: datetime, subject_prefix: str) -> Dict[str, str]:
    date_str = window_end.strftime("%Y-%m-%d")
    subject = f"{subject_prefix} {date_str}"

    if not papers:
        text = (
            f"{date_str} 文献日报\n"
            f"时间范围：{window_start.isoformat()} - {window_end.isoformat()}\n\n"
            "今日未发现满足条件的新论文。"
        )
        html = (
            f"<h2>{date_str} 文献日报</h2>"
            f"<p>时间范围：{window_start.isoformat()} - {window_end.isoformat()}</p>"
            "<p>今日未发现满足条件的新论文。</p>"
        )
        return {"subject": subject, "text": text, "html": html}

    lines = [
        f"{date_str} 文献日报",
        f"时间范围：{window_start.isoformat()} - {window_end.isoformat()}",
        "",
        "目录：",
    ]
    for idx, p in enumerate(papers, 1):
        score = p.relevance_score if p.relevance_score is not None else p.keyword_hits
        lines.append(f"{idx}. {p.title} ({p.journal}) [score={score}]")
    lines.append("")

    html_parts = [
        f"<h2>{date_str} 文献日报</h2>",
        f"<p>时间范围：{window_start.isoformat()} - {window_end.isoformat()}</p>",
        "<ol>",
    ]
    for p in papers:
        score = p.relevance_score if p.relevance_score is not None else p.keyword_hits
        html_parts.append(
            f"<li><a href=\"{p.link}\">{p.title}</a> "
            f"({p.journal}) [score={score}]</li>"
        )
    html_parts.append("</ol>")

    for idx, p in enumerate(papers, 1):
        summary = p.summary or {}
        lines.extend(
            [
                f"\n==== {idx}. {p.title} ====",
                f"期刊/来源：{p.journal}",
                f"作者：{', '.join(p.authors) if p.authors else '未知'}",
                f"链接：{p.link}",
                f"0 文献简介：{summary.get('brief', '未生成')}",
                f"1 解决的问题：{summary.get('problem', '未生成')}",
                f"2 必要性：{summary.get('necessity', '未生成')}",
                f"3 IEEE 标准节点：{summary.get('why_ieee_nodes', '未生成')}",
                f"4 城市级韧性评估难点：{summary.get('why_city_level_missing', '未生成')}",
                f"5 算例数据：{summary.get('data_cases', '未生成')}",
                f"6 创新点：{summary.get('innovation', '未生成')}",
                f"7 Reviewer 评述：{summary.get('reviewer_critique', '未生成')}",
            ]
        )

        html_parts.extend(
            [
                f"<hr><h3>{idx}. {p.title}</h3>",
                f"<p><b>期刊/来源</b>：{p.journal}</p>",
                f"<p><b>作者</b>：{', '.join(p.authors) if p.authors else '未知'}</p>",
                f"<p><b>链接</b>：<a href=\"{p.link}\">{p.link}</a></p>",
                f"<p><b>0 文献简介</b>：{summary.get('brief', '未生成')}</p>",
                f"<p><b>1 解决的问题</b>：{summary.get('problem', '未生成')}</p>",
                f"<p><b>2 必要性</b>：{summary.get('necessity', '未生成')}</p>",
                f"<p><b>3 IEEE 标准节点</b>：{summary.get('why_ieee_nodes', '未生成')}</p>",
                f"<p><b>4 城市级韧性评估难点</b>：{summary.get('why_city_level_missing', '未生成')}</p>",
                f"<p><b>5 算例数据</b>：{summary.get('data_cases', '未生成')}</p>",
                f"<p><b>6 创新点</b>：{summary.get('innovation', '未生成')}</p>",
                f"<p><b>7 Reviewer 评述</b>：{summary.get('reviewer_critique', '未生成')}</p>",
            ]
        )

    text = "\n".join(lines)
    html = "".join(html_parts)
    return {"subject": subject, "text": text, "html": html}


def send_email(subject: str, text: str, html: str, from_name: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "0"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    mail_to = os.getenv("MAIL_TO")

    missing = [k for k in (smtp_host, smtp_port, smtp_user, smtp_pass, mail_to) if not k]
    if missing:
        raise RuntimeError("SMTP 配置不完整，请检查环境变量")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{smtp_user}>"
    msg["To"] = mail_to

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    if smtp_port == 465:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        server.starttls()

    try:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [addr.strip() for addr in mail_to.split(",")], msg.as_string())
    finally:
        server.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="src/config.yaml")
    parser.add_argument("--state", default="state/state.json")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    state = load_state(args.state)

    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    llm_cfg = cfg.get("llm", {})
    require_llm = bool(llm_cfg.get("require", False))
    print(f"[info] LLM key present: {bool(os.getenv('DEEPSEEK_API_KEY'))}")

    last_run = state.get("last_run")
    if last_run:
        try:
            window_start = dateparser.parse(last_run).astimezone(timezone.utc)
        except Exception:
            window_start = now_utc - timedelta(hours=cfg.get("lookback_hours", 36))
    else:
        window_start = now_utc - timedelta(hours=cfg.get("lookback_hours", 36))

    sources = cfg.get("sources", {})
    papers: List[Paper] = []
    papers += collect_rss_sources(sources.get("rss", []), "rss")
    papers += collect_rss_sources(sources.get("nature_rss", []), "nature")
    papers += collect_rss_sources(sources.get("elsevier_rss", []), "elsevier")
    if cfg.get("output", {}).get("include_preprints", True):
        arxiv_cfg = cfg.get("arxiv", {})
        papers += collect_arxiv(
            arxiv_cfg.get("categories", []),
            arxiv_cfg.get("max_results", 50),
            arxiv_cfg.get("use_updated", True),
        )

    papers = filter_by_date(papers, window_start)
    papers = dedupe(papers, state.get("sent_ids", []))

    keywords = cfg.get("filter", {}).get("keywords", [])
    groups = cfg.get("filter", {}).get("required_groups", [])
    min_groups = cfg.get("filter", {}).get("min_groups_matched", 0)
    exclude_prefixes = cfg.get("filter", {}).get("exclude_title_prefixes", [])
    exclude_keywords = cfg.get("filter", {}).get("exclude_keywords", [])
    filtered: List[Paper] = []
    for p in papers:
        if should_exclude_title(p.title, exclude_prefixes):
            continue
        text = f"{p.title} {p.abstract}"
        p.keyword_hits = keyword_score(text, keywords)
        p.group_hits = group_score(text, groups)
        text_low = text.lower()
        if exclude_keywords and any(k.lower() in text_low for k in exclude_keywords):
            continue
        filtered.append(p)
    papers = filtered

    min_hits = cfg.get("min_keyword_hits", 1)
    papers = [p for p in papers if p.keyword_hits >= min_hits or not keywords]
    if min_groups > 0:
        papers = [p for p in papers if p.group_hits >= min_groups]

    window_start_local = window_start.astimezone(tz)
    if not papers:
        email = build_email(
            [],
            window_start_local,
            now_local,
            cfg.get("email", {}).get("subject_prefix", "[文献日报]"),
        )
        if not args.no_email and not args.dry_run:
            send_email(email["subject"], email["text"], email["html"], cfg.get("email", {}).get("from_name", "ResearchFollow Bot"))
        if not args.dry_run:
            state["last_run"] = now_utc.isoformat()
            save_state(args.state, state)
        print("[info] no papers found")
        return 0

    papers.sort(key=lambda p: p.keyword_hits, reverse=True)

    client = None if args.no_llm else build_client()
    if require_llm and not client:
        raise RuntimeError("LLM 必需但未配置 DEEPSEEK_API_KEY")
    if client:
        focus = cfg.get("filter", {}).get("focus_statement", "")
        max_eval = cfg.get("max_llm_eval", 30)
        for p in papers[:max_eval]:
            try:
                data = llm_relevance(client, cfg.get("llm", {}).get("model", "DeepSeek-R1"), focus, p)
                p.relevance_score = int(data.get("score", 0))
                p.relevance_reason = str(data.get("reason", ""))
            except Exception as exc:
                print(f"[warn] relevance LLM failed: {p.title} ({exc})")
    else:
        print("[warn] LLM 不可用，使用关键词打分")

    source_weight = cfg.get("ranking", {}).get("source_weight", {})
    def final_score(p: Paper) -> float:
        base = p.relevance_score if p.relevance_score is not None else p.keyword_hits
        weight = source_weight.get(p.source_group, 0)
        return base + weight

    papers.sort(key=final_score, reverse=True)
    min_llm_score = int(llm_cfg.get("min_relevance_score", 0))
    if client and min_llm_score > 0:
        papers = [p for p in papers if (p.relevance_score or 0) >= min_llm_score]
    papers = papers[: cfg.get("max_papers", 10)]

    if client:
        focus = cfg.get("filter", {}).get("focus_statement", "")
        language = cfg.get("output", {}).get("language", "zh-CN")
        for p in papers:
            try:
                p.summary = llm_summary(client, cfg.get("llm", {}).get("model", "DeepSeek-R1"), focus, p, language)
            except Exception as exc:
                print(f"[warn] summary LLM failed: {p.title} ({exc})")
                p.summary = {"brief": "未生成", "problem": "未生成"}
    else:
        for p in papers:
            p.summary = {
                "brief": f"{p.title}（{p.journal}）",
                "problem": "未生成（需要 LLM）",
                "necessity": "未生成（需要 LLM）",
                "why_ieee_nodes": "未生成（需要 LLM）",
                "why_city_level_missing": "未生成（需要 LLM）",
                "data_cases": "未生成（需要 LLM）",
                "innovation": "未生成（需要 LLM）",
                "reviewer_critique": "未生成（需要 LLM）",
            }

    email = build_email(
        papers,
        window_start_local,
        now_local,
        cfg.get("email", {}).get("subject_prefix", "[文献日报]"),
    )

    if not args.no_email and not args.dry_run:
        send_email(email["subject"], email["text"], email["html"], cfg.get("email", {}).get("from_name", "ResearchFollow Bot"))

    if not args.dry_run:
        sent_ids = state.get("sent_ids", [])
        for p in papers:
            if p.doi:
                sent_ids.append(f"doi:{p.doi.lower().strip()}")
            else:
                sent_ids.append(f"title:{normalize_title(p.title)}")
        state["sent_ids"] = sent_ids[-5000:]
        state["last_run"] = now_utc.isoformat()
        save_state(args.state, state)

    print(f"[info] processed {len(papers)} papers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
