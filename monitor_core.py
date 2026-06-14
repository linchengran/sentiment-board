from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import sys
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlparse

import pandas as pd
import requests

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
TASKS_FILE = DATA_DIR / "tasks.json"
HISTORY_FILE = DATA_DIR / "sentiment_events.csv"
DEFAULT_INTERVAL_MINUTES = 10

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

# ── WBI 签名（B站反爬验证）────────────────────────────────────
_WBI_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
_wbi_cache: dict = {}


def _get_wbi_keys(headers: dict = HEADERS) -> tuple[str, str]:
    """从 B站 nav 接口取 img_key / sub_key，缓存10分钟。"""
    now = time.time()
    if _wbi_cache.get("ts", 0) + 600 > now:
        return _wbi_cache["img"], _wbi_cache["sub"]
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    wbi = resp.json()["data"]["wbi_img"]
    img_key = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub_key = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    _wbi_cache.update({"ts": now, "img": img_key, "sub": sub_key})
    return img_key, sub_key


def _get_mixin_key(headers: dict = HEADERS) -> str:
    img_key, sub_key = _get_wbi_keys(headers)
    raw = img_key + sub_key
    return "".join(raw[i] for i in _WBI_MIXIN_KEY_ENC_TAB)[:32]


def _wbi_sign(params: dict, headers: dict = HEADERS) -> dict:
    """给参数字典加上 wts + w_rid 签名，返回新字典。"""
    mixin = _get_mixin_key(headers)
    wts = int(time.time())
    signed = dict(params)
    signed["wts"] = wts
    cleaned = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in sorted(signed.items())
    }
    query = urllib.parse.urlencode(cleaned)
    w_rid = hashlib.md5((query + mixin).encode()).hexdigest()
    signed["w_rid"] = w_rid
    return signed

FIELDNAMES = [
    "record_id",
    "task_id",
    "task_name",
    "source_type",
    "platform",
    "target_id",
    "target_title",
    "target_url",
    "username",
    "text",
    "published_at",
    "like_count",
    "score",
    "label",
    "fetched_at",
]

SOURCE_TYPES = [
    {
        "id": "bilibili_video",
        "name": "B站视频评论",
        "hint": "输入 BV 号或 B站视频链接，抓取该视频评论。",
        "placeholder": "BV1xx411c7mD 或 https://www.bilibili.com/video/BV...",
        "query_required": True,
    },
    {
        "id": "bilibili_keyword",
        "name": "B站话题/关键词",
        "hint": "按关键词搜索相关视频，再抓取这些视频的评论。",
        "placeholder": "例如：某电影名、品牌名、事件关键词",
        "query_required": True,
    },
    {
        "id": "bilibili_popular",
        "name": "B站热门视频",
        "hint": "抓取 B站热门榜视频评论，可用关键词做标题过滤。",
        "placeholder": "可选：标题过滤关键词",
        "query_required": False,
    },
    {
        "id": "weibo_hot",
        "name": "微博热搜",
        "hint": "抓取公开热搜词条文本，用于观察热点话题情绪。",
        "placeholder": "可选：过滤关键词",
        "query_required": False,
    },
    {
        "id": "zhihu_hot",
        "name": "知乎热榜",
        "hint": "抓取知乎热榜标题和摘要文本。",
        "placeholder": "可选：过滤关键词",
        "query_required": False,
    },
    {
        "id": "rss_feed",
        "name": "RSS/网页订阅",
        "hint": "输入 RSS 地址，分析文章标题和摘要。",
        "placeholder": "https://example.com/rss.xml",
        "query_required": True,
    },
    {
        "id": "manual_text",
        "name": "自定义文本",
        "hint": "每行一条文本，适合先导入其他平台导出的评论。",
        "placeholder": "每行一条评论或帖子内容",
        "query_required": True,
    },
]

POSITIVE_WORDS = {
    "喜欢",
    "支持",
    "好看",
    "优秀",
    "厉害",
    "感动",
    "精彩",
    "赞",
    "牛",
    "快乐",
    "舒服",
    "期待",
    "值得",
    "可爱",
    "开心",
    "强",
    "稳定",
    "靠谱",
    "满意",
    "惊喜",
    "真香",
}

NEGATIVE_WORDS = {
    "差",
    "烂",
    "讨厌",
    "失望",
    "无语",
    "难看",
    "垃圾",
    "离谱",
    "恶心",
    "不行",
    "崩",
    "尴尬",
    "骂",
    "骗",
    "难受",
    "退",
    "翻车",
    "抵制",
    "虚假",
    "造假",
    "争议",
}

STOPWORDS = {
    "这个",
    "那个",
    "就是",
    "还是",
    "真的",
    "一个",
    "可以",
    "没有",
    "什么",
    "现在",
    "感觉",
    "因为",
    "所以",
    "但是",
    "如果",
    "已经",
    "不是",
    "怎么",
}


def get_source_types() -> list[dict]:
    return SOURCE_TYPES


def load_tasks() -> list[dict]:
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_tasks(tasks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def create_task(payload: dict) -> dict:
    source_type = str(payload.get("source_type") or "").strip()
    source_ids = {item["id"] for item in SOURCE_TYPES}
    if source_type not in source_ids:
        raise ValueError("不支持的数据源类型")

    query = str(payload.get("query") or "").strip()
    source_meta = next(item for item in SOURCE_TYPES if item["id"] == source_type)
    if source_meta["query_required"] and not query:
        raise ValueError("监控目标不能为空")

    task = {
        "id": uuid.uuid4().hex[:12],
        "name": str(payload.get("name") or source_meta["name"]).strip()[:80],
        "source_type": source_type,
        "query": query,
        "run_mode": "once" if str(payload.get("run_mode", "repeat")) == "once" else "repeat",
        "cookie": str(payload.get("cookie") or "").strip(),
        "interval_minutes": _bounded_int(payload.get("interval_minutes"), 1, 1440, DEFAULT_INTERVAL_MINUTES),
        "max_pages": _bounded_int(payload.get("max_pages"), 1, 50, 3),
        "top_items": _bounded_int(payload.get("top_items"), 1, 20, 5),
        "enabled": bool(payload.get("enabled", True)),
        "created_at": _now_text(),
        "last_run_at": "",
        "next_run_at": "",
        "last_status": "未运行",
        "last_error": "",
        "last_added": 0,
        "last_skipped": 0,
        "total_saved": 0,
    }
    task["next_run_at"] = _next_run_text(task)

    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)
    return task


def update_task(task_id: str, payload: dict) -> dict:
    tasks = load_tasks()
    for task in tasks:
        if task["id"] != task_id:
            continue
        for key in ("name", "query", "source_type"):
            if key in payload:
                task[key] = str(payload[key]).strip()
        if "cookie" in payload:
            task["cookie"] = str(payload["cookie"] or "").strip()
        if "interval_minutes" in payload:
            task["interval_minutes"] = _bounded_int(payload["interval_minutes"], 1, 1440, DEFAULT_INTERVAL_MINUTES)
        if "max_pages" in payload:
            task["max_pages"] = _bounded_int(payload["max_pages"], 1, 50, 3)
        if "top_items" in payload:
            task["top_items"] = _bounded_int(payload["top_items"], 1, 20, 5)
        if "enabled" in payload:
            task["enabled"] = bool(payload["enabled"])
        task["next_run_at"] = _next_run_text(task)
        save_tasks(tasks)
        return task
    raise KeyError("任务不存在")


def delete_task(task_id: str) -> None:
    tasks = load_tasks()
    filtered = [task for task in tasks if task["id"] != task_id]
    if len(filtered) == len(tasks):
        raise KeyError("任务不存在")
    save_tasks(filtered)


def seed_demo_data() -> dict:
    """Create a portfolio-safe demo dataset that does not depend on live platform APIs."""
    tasks = load_tasks()
    demo_task = next((task for task in tasks if task.get("id") == "demo-product-launch"), None)
    if demo_task is None:
        demo_task = {
            "id": "demo-product-launch",
            "name": "演示：新品发布舆情",
            "source_type": "manual_text",
            "query": "内置演示数据",
            "interval_minutes": 60,
            "max_pages": 3,
            "top_items": 5,
            "enabled": False,
            "created_at": _now_text(),
            "last_run_at": "",
            "next_run_at": "",
            "last_status": "演示数据",
            "last_error": "",
            "last_added": 0,
            "last_skipped": 0,
            "total_saved": 0,
        }
        tasks.append(demo_task)

    base = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=34)
    samples = [
        (0, "B站", "首发视频评论", "外观很高级，功能也比上一代稳定，第一印象不错。", 0.86, 124),
        (2, "微博", "热搜讨论", "价格有点高，但配置确实堆得很满，先观望一下。", 0.56, 832),
        (4, "知乎", "体验问答", "续航和屏幕是明显升级，日常使用应该挺舒服。", 0.78, 96),
        (7, "B站", "测评视频评论", "发布会节奏很好，重点功能讲得清楚，期待实测。", 0.82, 201),
        (10, "微博", "热搜讨论", "客服回应太慢，预售规则也没说清楚，有点失望。", 0.31, 1420),
        (13, "B站", "测评视频评论", "刚看到发热测试，表现不太稳定，担心翻车。", 0.24, 642),
        (16, "知乎", "体验问答", "争议主要在价格和发热，如果后续优化能跟上还可以。", 0.44, 188),
        (20, "RSS", "媒体报道", "厂商发布补充说明，承诺优化售后和预售发货节奏。", 0.57, 0),
        (24, "微博", "热搜讨论", "补偿方案出来后态度好多了，至少愿意解决问题。", 0.67, 980),
        (28, "B站", "用户追评", "系统更新后发热下降，体验比第一天稳定不少。", 0.74, 357),
        (31, "知乎", "体验问答", "目前看口碑开始回升，但价格争议还会持续。", 0.61, 149),
        (34, "B站", "用户追评", "售后处理速度提升，这次危机公关算是拉回来一些。", 0.72, 276),
    ]

    rows = []
    seeded_at = _now_text()
    for index, (hour_offset, platform, target_title, text, score, heat) in enumerate(samples):
        published_at = (base + timedelta(hours=hour_offset)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(
            {
                "record_id": _stable_id(demo_task["id"], index, text),
                "task_id": demo_task["id"],
                "task_name": demo_task["name"],
                "source_type": "demo",
                "platform": platform,
                "target_id": "demo-product-launch",
                "target_title": target_title,
                "target_url": "",
                "username": "演示用户",
                "text": text,
                "published_at": published_at,
                "like_count": heat,
                "score": score,
                "label": "正面" if score >= 0.5 else "负面",
                # fetched_at matches published_at so resample_trend spreads points across the timeline
                "fetched_at": published_at,
            }
        )

    added, skipped = append_history(rows)
    demo_task["last_run_at"] = seeded_at
    demo_task["next_run_at"] = ""
    demo_task["last_status"] = "演示数据"
    demo_task["last_error"] = ""
    demo_task["last_added"] = added
    demo_task["last_skipped"] = skipped
    demo_task["total_saved"] = int(demo_task.get("total_saved") or 0) + added
    save_tasks(tasks)
    return {"task": demo_task, "added": added, "skipped": skipped}


def run_task(task_id: str) -> dict:
    tasks = load_tasks()
    for task in tasks:
        if task["id"] != task_id:
            continue
        started = _now_text()
        try:
            raw_records = collect_records(task)
            analyzed = analyze_records(raw_records, task)
            added, skipped = append_history(analyzed)
            # 真实任务首次采集成功后，自动清除演示数据，避免混淆
            if added > 0 and task.get("source_type") != "demo":
                _clean_demo_data()
            task["last_run_at"] = started
            task["next_run_at"] = _next_run_text(task)
            task["last_status"] = "成功"
            task["last_error"] = ""
            task["last_added"] = added
            task["last_skipped"] = skipped
            task["total_saved"] = int(task.get("total_saved") or 0) + added
            # 单次分析模式：跑完就自动停用，不再重复
            if task.get("run_mode") == "once":
                task["enabled"] = False
                task["last_status"] = "已完成"
            save_tasks(tasks)
            return {"task": task, "added": added, "skipped": skipped, "fetched": len(raw_records)}
        except Exception as exc:
            task["last_run_at"] = started
            task["next_run_at"] = _next_run_text(task)
            task["last_status"] = "失败"
            task["last_error"] = str(exc)
            task["last_added"] = 0
            task["last_skipped"] = 0
            save_tasks(tasks)
            raise
    raise KeyError("任务不存在")


def run_due_tasks() -> list[dict]:
    results = []
    now = datetime.now()
    for task in load_tasks():
        if not task.get("enabled"):
            continue
        next_run_at = _parse_dt(task.get("next_run_at")) or now
        if next_run_at <= now:
            try:
                results.append({"task_id": task["id"], **run_task(task["id"])})
            except Exception as exc:
                results.append({"task_id": task["id"], "error": str(exc)})
    return results


def collect_records(task: dict) -> list[dict]:
    source_type = task["source_type"]
    query = str(task.get("query") or "").strip()
    cookie = str(task.get("cookie") or "").strip()

    # 构造带 Cookie 的请求头（各平台共用）
    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
        # 微博需要额外的 Referer
        if "weibo" in source_type:
            headers["Referer"] = "https://weibo.com"
        elif "zhihu" in source_type:
            headers["Referer"] = "https://www.zhihu.com"

    if source_type == "bilibili_video":
        return fetch_bilibili_video(query, task["max_pages"], headers)
    if source_type == "bilibili_keyword":
        videos = search_bilibili_videos(query, task["top_items"], headers)
        return fetch_bilibili_video_group(videos, task["max_pages"], headers)
    if source_type == "bilibili_popular":
        videos = fetch_bilibili_popular(task["top_items"], query, headers)
        return fetch_bilibili_video_group(videos, task["max_pages"], headers)
    if source_type == "weibo_hot":
        return fetch_weibo_hot(query, task["top_items"], headers)
    if source_type == "zhihu_hot":
        return fetch_zhihu_hot(query, task["top_items"], headers)
    if source_type == "rss_feed":
        return fetch_rss_feed(query, task["top_items"])
    if source_type == "manual_text":
        return parse_manual_text(query)

    raise ValueError("不支持的数据源类型")


def fetch_bilibili_video(query: str, max_pages: int, headers: dict = HEADERS) -> list[dict]:
    bvid = extract_bvid(query)
    if not bvid:
        raise ValueError("请输入有效的 B站 BV 号或视频链接")
    info = fetch_bilibili_video_info(bvid, headers)
    return fetch_bilibili_comments(info, max_pages, headers)


def fetch_bilibili_video_group(videos: list[dict], max_pages: int, headers: dict = HEADERS) -> list[dict]:
    records: list[dict] = []
    for video in videos:
        try:
            records.extend(fetch_bilibili_comments(video, max_pages, headers))
        except Exception:
            continue
    if not records:
        raise RuntimeError("没有抓到可分析的 B站评论")
    return records


def extract_bvid(text: str) -> str:
    match = re.search(r"BV[0-9A-Za-z]{10}", text)
    return match.group(0) if match else ""


def fetch_bilibili_video_info(bvid: str, headers: dict = HEADERS) -> dict:
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        headers=headers,
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise ValueError(f"无法获取视频信息：{data.get('message')}")
    raw = data["data"]
    owner = raw.get("owner") or {}
    return {
        "platform": "B站",
        "target_id": raw.get("bvid") or bvid,
        "oid": int(raw["aid"]),
        "target_title": raw.get("title") or bvid,
        "target_url": f"https://www.bilibili.com/video/{raw.get('bvid') or bvid}",
        "username": owner.get("name") or "",
    }


def fetch_bilibili_comments(video: dict, max_pages: int, headers: dict = HEADERS) -> list[dict]:
    records: list[dict] = []
    next_offset = ""
    for page in range(1, max_pages + 1):
        params: dict = {"type": 1, "oid": video["oid"], "mode": 3, "ps": 20}
        if next_offset:
            params["pagination_str"] = json.dumps({"offset": next_offset})
        else:
            params["next"] = 0

        try:
            signed_params = _wbi_sign(params, headers)
        except Exception:
            signed_params = params  # 签名失败则降级（少数情况）

        resp = requests.get(
            "https://api.bilibili.com/x/v2/reply/main",
            params=signed_params,
            headers=headers,
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", 0)
        if code != 0:
            # -352 风控：签名问题，停止抓取但不整个任务失败
            if code in (-352, -401, -403):
                break
            raise RuntimeError(f"第 {page} 页评论请求失败：{data.get('message')}")

        replies = (data.get("data") or {}).get("replies") or []
        if not replies:
            break

        for reply in replies:
            content = reply.get("content") or {}
            member = reply.get("member") or {}
            text = html.unescape((content.get("message") or "").strip())
            if not text:
                continue
            published_at = _from_timestamp(reply.get("ctime"))
            records.append(
                {
                    "source_record_id": str(reply.get("rpid") or ""),
                    "source_type": "bilibili",
                    "platform": "B站",
                    "target_id": video["target_id"],
                    "target_title": video["target_title"],
                    "target_url": video["target_url"],
                    "username": member.get("uname") or "",
                    "text": text,
                    "published_at": published_at,
                    "like_count": int(reply.get("like") or 0),
                }
            )

        cursor = (data.get("data") or {}).get("cursor") or {}
        pagination = cursor.get("pagination_reply") or {}
        next_offset = pagination.get("next_offset") or ""
        if cursor.get("is_end") or not next_offset:
            break

        time.sleep(0.5)

    if not records:
        raise RuntimeError("未抓取到评论，可能被风控拦截，请稍后重试")
    return records


def search_bilibili_videos(keyword: str, limit: int, headers: dict = HEADERS) -> list[dict]:
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={"search_type": "video", "keyword": keyword, "page": 1},
        headers=headers,
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"B站搜索失败：{data.get('message')}")
    results = (data.get("data") or {}).get("result") or []
    videos = []
    for item in results:
        bvid = item.get("bvid")
        if not bvid:
            continue
        try:
            videos.append(fetch_bilibili_video_info(bvid, headers))
        except Exception:
            videos.append(
                {
                    "platform": "B站",
                    "target_id": bvid,
                    "oid": int(item.get("aid") or 0),
                    "target_title": _clean_html(item.get("title") or bvid),
                    "target_url": f"https://www.bilibili.com/video/{bvid}",
                    "username": item.get("author") or "",
                }
            )
        if len(videos) >= limit:
            break
    if not videos:
        raise RuntimeError("没有找到相关 B站视频")
    return [video for video in videos if video.get("oid")]


def fetch_bilibili_popular(limit: int, keyword_filter: str = "", headers: dict = HEADERS) -> list[dict]:
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/popular",
        params={"pn": 1, "ps": max(limit * 3, 10)},
        headers=headers,
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"B站热门榜请求失败：{data.get('message')}")
    rows = (data.get("data") or {}).get("list") or []
    videos = []
    for item in rows:
        title = item.get("title") or ""
        if keyword_filter and keyword_filter not in title:
            continue
        owner = item.get("owner") or {}
        videos.append(
            {
                "platform": "B站",
                "target_id": item.get("bvid") or str(item.get("aid")),
                "oid": int(item.get("aid") or 0),
                "target_title": title,
                "target_url": f"https://www.bilibili.com/video/{item.get('bvid')}",
                "username": owner.get("name") or "",
            }
        )
        if len(videos) >= limit:
            break
    if not videos:
        raise RuntimeError("没有匹配到热门视频")
    return videos


def fetch_weibo_hot(keyword_filter: str = "", limit: int = 10, headers: dict = HEADERS) -> list[dict]:
    resp = requests.get("https://weibo.com/ajax/side/hotSearch", headers=headers, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    rows = (data.get("data") or {}).get("realtime") or []
    records = []
    for item in rows:
        word = item.get("word") or item.get("note") or ""
        note = item.get("note") or ""
        if not word:
            continue
        text = f"{word} {note}".strip()
        if keyword_filter and keyword_filter not in text:
            continue
        records.append(
            {
                "source_record_id": str(item.get("realpos") or item.get("word_scheme") or word),
                "source_type": "weibo_hot",
                "platform": "微博",
                "target_id": word,
                "target_title": word,
                "target_url": f"https://s.weibo.com/weibo?q={quote(word)}",
                "username": "",
                "text": text,
                "published_at": _now_text(),
                "like_count": _bounded_int(item.get("num"), 0, 999999999, 0),
            }
        )
        if len(records) >= limit:
            break
    if not records:
        raise RuntimeError("没有抓到微博热搜内容")
    return records


def fetch_zhihu_hot(keyword_filter: str = "", limit: int = 10, headers: dict = HEADERS) -> list[dict]:
    resp = requests.get(
        "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total",
        params={"limit": max(limit, 10), "desktop": "true"},
        headers={**headers, "Referer": "https://www.zhihu.com/hot"},
        timeout=12,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data") or []
    records = []
    for item in rows:
        target = item.get("target") or {}
        title = target.get("title") or ""
        excerpt = target.get("excerpt") or target.get("description") or ""
        text = f"{title} {excerpt}".strip()
        if not text:
            continue
        if keyword_filter and keyword_filter not in text:
            continue
        metrics = item.get("detail_text") or ""
        records.append(
            {
                "source_record_id": str(target.get("id") or title),
                "source_type": "zhihu_hot",
                "platform": "知乎",
                "target_id": str(target.get("id") or title),
                "target_title": title,
                "target_url": target.get("url") or "https://www.zhihu.com/hot",
                "username": "",
                "text": f"{text} {metrics}".strip(),
                "published_at": _now_text(),
                "like_count": 0,
            }
        )
        if len(records) >= limit:
            break
    if not records:
        raise RuntimeError("没有抓到知乎热榜内容")
    return records


def fetch_rss_feed(url: str, limit: int = 10) -> list[dict]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("请输入有效的 RSS 地址")
    resp = requests.get(url, headers=HEADERS, timeout=12)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    channel_title = _xml_text(root.find("./channel/title")) or parsed.netloc
    items = root.findall("./channel/item")
    if not items:
        items = root.findall("{http://www.w3.org/2005/Atom}entry")

    records = []
    for item in items[:limit]:
        title = _xml_text(item.find("title"))
        link = _xml_text(item.find("link"))
        if not link and item.find("{http://www.w3.org/2005/Atom}link") is not None:
            link = item.find("{http://www.w3.org/2005/Atom}link").attrib.get("href", "")
        description = _clean_html(_xml_text(item.find("description")) or _xml_text(item.find("summary")))
        published = (
            _parse_pubdate(_xml_text(item.find("pubDate")))
            or _parse_pubdate(_xml_text(item.find("{http://www.w3.org/2005/Atom}updated")))
            or _now_text()
        )
        text = f"{title} {description}".strip()
        if not text:
            continue
        records.append(
            {
                "source_record_id": link or title,
                "source_type": "rss_feed",
                "platform": "RSS",
                "target_id": channel_title,
                "target_title": title or channel_title,
                "target_url": link,
                "username": channel_title,
                "text": text,
                "published_at": published,
                "like_count": 0,
            }
        )
    if not records:
        raise RuntimeError("RSS 中没有可分析的条目")
    return records


def parse_manual_text(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("自定义文本不能为空")
    now = _now_text()
    return [
        {
            "source_record_id": _stable_id(line),
            "source_type": "manual_text",
            "platform": "自定义",
            "target_id": "manual",
            "target_title": "自定义文本",
            "target_url": "",
            "username": "",
            "text": line,
            "published_at": now,
            "like_count": 0,
        }
        for line in lines
    ]


def analyze_records(records: Iterable[dict], task: dict) -> list[dict]:
    rows = list(records)
    texts = [row["text"] for row in rows]
    scored = _analyze_with_project_model(texts)
    if scored is None:
        scored = [_rule_sentiment(text) for text in texts]

    fetched_at = _now_text()
    results = []
    for row, item in zip(rows, scored):
        score = max(0.0, min(1.0, float(item["score"])))
        label = "正面" if score >= 0.5 else "负面"
        source_record_id = str(row.get("source_record_id") or "")
        record_id = _stable_id(task["id"], row.get("source_type"), row.get("target_id"), source_record_id, row["text"])
        results.append(
            {
                "record_id": record_id,
                "task_id": task["id"],
                "task_name": task["name"],
                "source_type": task["source_type"],
                "platform": row.get("platform", ""),
                "target_id": row.get("target_id", ""),
                "target_title": row.get("target_title", ""),
                "target_url": row.get("target_url", ""),
                "username": row.get("username", ""),
                "text": row.get("text", ""),
                "published_at": row.get("published_at") or fetched_at,
                "like_count": int(row.get("like_count") or 0),
                "score": round(score, 6),
                "label": label,
                "fetched_at": fetched_at,
            }
        )
    return results


def append_history(rows: list[dict]) -> tuple[int, int]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = load_history()
    existing_ids = set(existing["record_id"].astype(str)) if not existing.empty else set()
    new_rows = [row for row in rows if str(row["record_id"]) not in existing_ids]
    skipped = len(rows) - len(new_rows)
    if not new_rows:
        return 0, skipped

    file_exists = HISTORY_FILE.exists()
    with HISTORY_FILE.open("a", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDNAMES)
        if not file_exists or HISTORY_FILE.stat().st_size == 0:
            writer.writeheader()
        for row in new_rows:
            writer.writerow({key: row.get(key, "") for key in FIELDNAMES})
    return len(new_rows), skipped


def load_history() -> pd.DataFrame:
    if not HISTORY_FILE.exists():
        return pd.DataFrame(columns=FIELDNAMES)
    df = pd.read_csv(HISTORY_FILE, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame(columns=FIELDNAMES)
    for col in FIELDNAMES:
        if col not in df.columns:
            df[col] = None
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], errors="coerce")
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["like_count"] = pd.to_numeric(df["like_count"], errors="coerce").fillna(0).astype(int)
    return df[FIELDNAMES]


def build_dashboard(task_id: str = "all", freq: str = "30min", since: str = "") -> dict:
    df = load_history()
    tasks = load_tasks()
    if task_id and task_id != "all":
        df = df[df["task_id"] == task_id].copy()
    if since:
        since_dt = pd.to_datetime(since, errors="coerce")
        if pd.notna(since_dt):
            # 用 fetched_at（你的抓取时间）过滤，而不是 published_at（评论原发布时间）
            # 这样旧视频的评论只要今天抓的就能显示，不会被"今日"过滤掉
            df = df[df["fetched_at"] >= since_dt].copy()

    trend = resample_trend(df, freq)
    turning_points = detect_turning_points(trend)
    summary = make_summary(df, tasks, turning_points)
    comments = latest_comments(df)
    keywords = top_keywords(df)
    task_metrics = build_task_metrics(df, tasks)
    platform_metrics = build_platform_metrics(df)

    return {
        "summary": summary,
        "trend": _records_for_json(trend),
        "turning_points": _records_for_json(turning_points),
        "comments": comments,
        "keywords": keywords,
        "tasks": tasks,
        "task_metrics": task_metrics,
        "platform_metrics": platform_metrics,
    }


def resample_trend(df: pd.DataFrame, freq: str = "30min") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["time", "avg_score", "comment_count", "negative_ratio", "positive_ratio"])
    work = df.copy()
    work["fetched_at"] = pd.to_datetime(work["fetched_at"], errors="coerce")
    work = work.dropna(subset=["fetched_at", "score"])
    if work.empty:
        return pd.DataFrame(columns=["time", "avg_score", "comment_count", "negative_ratio", "positive_ratio"])
    work["is_negative"] = work["score"] < 0.5
    trend = (
        work.set_index("fetched_at")
        .resample(freq)
        .agg(
            avg_score=("score", "mean"),
            comment_count=("text", "count"),
            negative_ratio=("is_negative", "mean"),
        )
        .dropna(subset=["avg_score"])
        .reset_index()
        .rename(columns={"fetched_at": "time"})
    )
    trend["positive_ratio"] = 1 - trend["negative_ratio"]
    return trend


def detect_turning_points(
    trend: pd.DataFrame,
    score_threshold: float = 0.15,
    negative_ratio_threshold: float = 0.20,
) -> pd.DataFrame:
    if trend.empty or len(trend) < 2:
        return pd.DataFrame(columns=["time", "avg_score", "score_change", "negative_ratio", "negative_ratio_change", "reason"])
    points = trend.copy()
    points["score_change"] = points["avg_score"].diff()
    points["negative_ratio_change"] = points["negative_ratio"].diff()
    mask = (points["score_change"].abs() >= score_threshold) | (
        points["negative_ratio_change"].abs() >= negative_ratio_threshold
    )
    points = points[mask].copy()
    if points.empty:
        return pd.DataFrame(columns=["time", "avg_score", "score_change", "negative_ratio", "negative_ratio_change", "reason"])

    def make_reason(row: pd.Series) -> str:
        reasons = []
        if abs(row["score_change"]) >= score_threshold:
            reasons.append("情感分上升" if row["score_change"] > 0 else "情感分下降")
        if abs(row["negative_ratio_change"]) >= negative_ratio_threshold:
            reasons.append("负面占比上升" if row["negative_ratio_change"] > 0 else "负面占比下降")
        return "、".join(reasons)

    points["reason"] = points.apply(make_reason, axis=1)
    return points


def make_summary(df: pd.DataFrame, tasks: list[dict], turning_points: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total_records": 0,
            "avg_score": 0,
            "negative_ratio": 0,
            "latest_score": 0,
            "score_delta": 0,
            "turning_points": 0,
            "active_tasks": len([task for task in tasks if task.get("enabled")]),
            "last_fetched_at": "",
        }
    work = df.dropna(subset=["score"]).copy()
    sorted_df = work.sort_values("fetched_at")
    latest_slice = sorted_df.tail(min(30, len(sorted_df)))
    previous_slice = sorted_df.iloc[-60:-30] if len(sorted_df) > 30 else sorted_df.head(0)
    latest_score = float(latest_slice["score"].mean()) if not latest_slice.empty else 0
    previous_score = float(previous_slice["score"].mean()) if not previous_slice.empty else latest_score
    return {
        "total_records": int(len(work)),
        "avg_score": round(float(work["score"].mean()), 4),
        "negative_ratio": round(float((work["score"] < 0.5).mean()), 4),
        "latest_score": round(latest_score, 4),
        "score_delta": round(latest_score - previous_score, 4),
        "turning_points": int(len(turning_points)),
        "active_tasks": len([task for task in tasks if task.get("enabled")]),
        "last_fetched_at": _json_time(work["fetched_at"].max()),
    }


def latest_comments(df: pd.DataFrame, limit: int = 80) -> list[dict]:
    if df.empty:
        return []
    rows = df.sort_values("published_at", ascending=False).head(limit).copy()
    rows["published_at"] = rows["published_at"].apply(_json_time)
    rows["fetched_at"] = rows["fetched_at"].apply(_json_time)
    return rows[
        [
            "task_name",
            "platform",
            "target_title",
            "target_url",
            "username",
            "text",
            "published_at",
            "score",
            "label",
            "like_count",
        ]
    ].fillna("").to_dict("records")


def top_keywords(df: pd.DataFrame, limit: int = 18) -> list[dict]:
    if df.empty:
        return []
    texts = " ".join(str(item) for item in df["text"].dropna().tolist())
    tokens = _tokenize(texts)
    counts: dict[str, int] = {}
    for token in tokens:
        if token in STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    return [{"word": word, "count": count} for word, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]


def build_task_metrics(df: pd.DataFrame, tasks: list[dict]) -> list[dict]:
    if df.empty:
        return [
            {
                "task_id": task["id"],
                "task_name": task["name"],
                "count": 0,
                "avg_score": 0,
                "negative_ratio": 0,
            }
            for task in tasks
        ]
    grouped = df.groupby(["task_id", "task_name"]).agg(count=("text", "count"), avg_score=("score", "mean")).reset_index()
    negative = (
        df.assign(is_negative=df["score"] < 0.5)
        .groupby("task_id", as_index=False)["is_negative"]
        .mean()
        .rename(columns={"is_negative": "negative_ratio"})
    )
    grouped = grouped.merge(negative, on="task_id", how="left")
    return _records_for_json(grouped)


def build_platform_metrics(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    grouped = df.groupby("platform").agg(count=("text", "count"), avg_score=("score", "mean")).reset_index()
    return _records_for_json(grouped)


def export_history_csv() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        with HISTORY_FILE.open("w", encoding="utf-8-sig", newline="") as fp:
            csv.DictWriter(fp, fieldnames=FIELDNAMES).writeheader()
    return HISTORY_FILE


def _analyze_with_project_model(texts: list[str]) -> list[dict] | None:
    if not texts:
        return []
    try:
        from analyze_bilibili import analyze_sentiment

        raw_results = analyze_sentiment(texts)
        if len(raw_results) != len(texts):
            return None
        return [{"score": float(item["score"])} for item in raw_results]
    except Exception:
        return None


def _rule_sentiment(text: str) -> dict:
    positive_hits = sum(text.count(word) for word in POSITIVE_WORDS)
    negative_hits = sum(text.count(word) for word in NEGATIVE_WORDS)
    raw = positive_hits - negative_hits
    score = 1 / (1 + math.exp(-raw))
    if positive_hits == 0 and negative_hits == 0:
        score = 0.5
    return {"score": score}


def _tokenize(text: str) -> list[str]:
    try:
        import jieba

        return [word.strip() for word in jieba.cut(text) if len(word.strip()) >= 2]
    except Exception:
        clean = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", " ", text)
        tokens = re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fa5]{2,4}", clean)
        return tokens


def _bounded_int(value, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(low, min(high, parsed))


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _from_timestamp(value) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return _now_text()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _next_run_text(task: dict) -> str:
    last_run = _parse_dt(task.get("last_run_at"))
    base = last_run or datetime.now()
    return (base + timedelta(minutes=int(task.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES))).strftime("%Y-%m-%d %H:%M:%S")


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _xml_text(node) -> str:
    return "" if node is None or node.text is None else node.text.strip()


def _parse_pubdate(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _stable_id(*parts) -> str:
    payload = "|".join(str(part or "") for part in parts).encode("utf-8", errors="ignore")
    return hashlib.md5(payload).hexdigest()


def _json_time(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _records_for_json(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    safe = df.copy()
    for col in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[col]):
            safe[col] = safe[col].apply(_json_time)
    return safe.replace({pd.NA: None}).fillna("").to_dict("records")


def _clean_demo_data() -> None:
    """Remove demo records from the CSV so real monitoring data isn't mixed in."""
    df = load_history()
    if df.empty:
        return
    mask = df["source_type"] == "demo"
    if not mask.any():
        return
    df = df[~mask].copy()
    for col in FIELDNAMES:
        if col in df.columns:
            df[col] = df[col].fillna("")
    df.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")


def clear_data(task_id: str = "") -> None:
    """清除采集数据。task_id 为空则清全部，否则只清指定任务的数据。"""
    df = load_history()
    if df.empty:
        return
    if task_id:
        df_clean = df[df["task_id"] != task_id].copy()
    else:
        df_clean = pd.DataFrame(columns=FIELDNAMES)

    # 重置受影响任务的统计
    tasks = load_tasks()
    for task in tasks:
        if not task_id or task["id"] == task_id:
            task["last_added"] = 0
            task["last_skipped"] = 0
            task["total_saved"] = 0
            task["last_status"] = "未运行"
    save_tasks(tasks)

    if df_clean.empty:
        HISTORY_FILE.unlink(missing_ok=True)
    else:
        for col in FIELDNAMES:
            if col in df_clean.columns:
                df_clean[col] = df_clean[col].fillna("")
        df_clean.to_csv(HISTORY_FILE, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d %H:%M:%S")
