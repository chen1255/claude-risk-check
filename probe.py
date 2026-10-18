#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py — 环境自动探测（供 CLI --auto 使用）

职责分离：
    · 纯分类逻辑（classify_*）：只做字符串/数值判断，无任何 I/O —— 便于单元测试；
    · I/O（fetch_ip_info / detect_answers）：访问公开 IP 信息 API，全程容错，
      离线 / 被墙 / 超时一律静默降级为「无建议」，绝不影响问卷作答。

探测结果仅作为问卷的“建议选项”，最终以用户作答为准。
"""

import json
import os
import urllib.request

# 探测相关的启发式常量与 questions.json 中的 probe 段保持同源
_PACK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")
with open(_PACK_PATH, "r", encoding="utf-8") as _f:
    _PACK = json.load(_f)
_PROBE = _PACK.get("probe", {})

# 题目 id 映射：探测项 → 对应问卷题
DETECT_TO_QID = {"ip_type": "q1", "ip_region": "q3", "env_consistency": "q11"}

# ASN / 组织名中出现即判为「机房 / 云 / VPS」的关键字
DATACENTER_KEYWORDS = tuple(_PROBE.get("datacenter_keywords", []))

# 组织名中出现即判为「公共代理 / VPN / 共享出口」的关键字
PROXY_KEYWORDS = tuple(_PROBE.get("proxy_keywords", []))

# Anthropic 官方支持区域（ISO 3166-1 alpha-2）。仅作“是否在支持区”的粗判，
# 官方列表会变动，以 Anthropic Supported Countries 页面为准。
SUPPORTED_COUNTRIES = set(_PROBE.get("supported_countries", []))

# UTC+8 时区名（Windows 无 tzdata 时 zoneinfo 会解析失败，用名称兜底）
UTC8_TZ_NAMES = set(_PROBE.get("utc8_tz_names", []))

# 出口 IP 信息 API（依次尝试）
IP_APIS = tuple(_PROBE.get("ip_apis", ["https://ipapi.co/json/", "https://ipinfo.io/json"]))


# ---------- 纯分类逻辑（可单元测试） ----------
def classify_ip_type(org):
    """按 ASN 组织名启发式判断出口 IP 类型。

    返回 questions.json 中 q1 的选项索引：
        0 = 住宅 IP     2 = IDC 机房/云     3 = 公共代理/共享出口
        1 = 不确定（无法判断）
    """
    if not org:
        return 1
    s = org.lower()
    if any(k in s for k in PROXY_KEYWORDS):
        return 3
    if any(k in s for k in DATACENTER_KEYWORDS):
        return 2
    return 0


def classify_region(country):
    """出口国家 / 地区是否在 Anthropic 支持区域内。

    返回 q3 选项索引：0 = 支持区；2 = 不支持区；1 = 不确定。
    """
    if not country:
        return 1
    return 0 if str(country).upper() in SUPPORTED_COUNTRIES else 2


def _tz_offset_hours(tzname):
    """把时区名解析成 UTC 偏移小时数；解析失败返回 None。"""
    if not tzname:
        return None
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        off = datetime.now(ZoneInfo(tzname)).utcoffset()
        return None if off is None else off.total_seconds() / 3600.0
    except Exception:
        return None


# UTC+8 时区名（Windows 无 tzdata 时 zoneinfo 会解析失败，用名称兜底）
# —— UTC8_TZ_NAMES 已在文件顶部从 questions.json 的 probe 段加载


def _is_utc8(tzname):
    off = _tz_offset_hours(tzname)
    if off is not None:
        return off == 8
    return str(tzname or "").strip().lower() in UTC8_TZ_NAMES


def classify_env_consistency(timezone, language, country):
    """系统语言 / 时区与出口地区的一致程度。

    返回 q11 选项索引：0 = 自洽；1 = 部分一致；2 = 矛盾（中文+UTC+8 但出海）；
    None = 信息不足，不给建议。
    """
    if not timezone or not language:
        return None
    lang = str(language).lower()
    cc = (country or "").upper()
    if cc and cc != "CN":
        if lang.startswith("zh") and _is_utc8(timezone):
            return 2
        if lang.startswith("en"):
            return 0
        return 1
    return None


# ---------- I/O：获取出口 IP 信息（全程容错） ----------
# —— IP_APIS 已在文件顶部从 questions.json 的 probe 段加载


def fetch_ip_info(timeout=4.0):
    """尝试获取出口 IP 的 country / org / asn；全部失败返回 {}。"""
    for url in IP_APIS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "claude-risk-check"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            if data:
                return {
                    "country": (data.get("country") or data.get("country_code") or "").upper(),
                    "org": data.get("org") or data.get("asn") or "",
                }
        except Exception:
            continue
    return {}


def detect_answers(timeout=4.0):
    """返回 (presets, notes)。presets: {qid: option_index}；任何失败都不抛异常。"""
    presets, notes = {}, []
    info = fetch_ip_info(timeout=timeout)
    if not info:
        notes.append("未能获取出口 IP 信息（可能离线或被拦截），已跳过 IP 相关探测。")
    else:
        cc, org = info.get("country", ""), info.get("org", "")
        presets[DETECT_TO_QID["ip_type"]] = classify_ip_type(org)
        presets[DETECT_TO_QID["ip_region"]] = classify_region(cc)
        notes.append("出口地区：%s；ASN/组织：%s" % (cc or "未知", org or "未知"))

    # 系统语言 / 时区（本机可读，无需网络）
    try:
        lang, tz = _local_locale()
        if lang or tz:
            oi = classify_env_consistency(tz, lang, info.get("country", "") if info else "")
            if oi is not None:
                presets[DETECT_TO_QID["env_consistency"]] = oi
            notes.append("本机语言：%s；时区：%s" % (lang or "未知", tz or "未知"))
    except Exception:
        pass

    return presets, notes


def _local_locale():
    """尽力读取本机语言与时区（失败返回空串）。返回 (language, timezone_name)。"""
    lang = tz = ""
    try:
        from datetime import datetime
        tzinfo = datetime.now().astimezone().tzinfo
        if tzinfo is not None:
            # zoneinfo 对象有 .key（如 Asia/Shanghai）；其它实现退回字符串
            tz = getattr(tzinfo, "key", None) or str(tzinfo)
            if tz in ("", "None"):
                tz = ""
    except Exception:
        pass
    try:
        import locale
        lang = locale.getlocale()[0] or ""
    except Exception:
        pass
    return lang, tz
