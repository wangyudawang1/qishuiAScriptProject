# -*- coding: utf-8 -*-
"""
汽水音乐 安卓自动化脚本 — 自动看广告获取免费听歌权益
=====================================================
改造自 iOS 版（原作者 wei6718189），适配 AScript 安卓引擎。

与 iOS 版的主要差异：
  1. 模块从 ascript.ios.* 换成 ascript.android.*
  2. 安卓有完整控件树，优先用 Selector 精确查找，OCR 兜底
  3. 包名改为安卓版汽水音乐 com.luna.music
  4. 点击走无障碍通道，不会被 App 检测（iOS 的 WDA 点击容易被拦截）

功能流程：
  启动 App → 跳开屏广告 → 清弹窗 → 校验首页 → 点右上角「免」字进广告
  → 等倒计时结束（支持 60s+ 长广告/防直播诱导/防跳转劫持/防短剧误判）
  → 点「领取成功」→ 点「领取奖励」→ 自动进下一轮 → 循环（领满自动退出）
"""

import os
import re
import sys
import time
import traceback

# ============== 基础模块导入 ==============
from ascript.android import action, system  # type: ignore
from ascript.android.system import Device  # type: ignore
from ascript.android.screen import Ocr  # type: ignore
from ascript.android.node import Selector  # type: ignore


# ============== 全局配置 ==============

APP_NAME = "汽水音乐"
APP_PACKAGE = "com.luna.music"      # 安卓版包名（iOS 是 com.soda.music）

# 主循环控制
MAX_LOOP_COUNT = 100                # 最大循环次数（防死循环）
LOOP_INTERVAL = 3                   # 每轮间隔秒数
MAX_IDLE_ROUNDS = 10                # 连续多少轮没领到就退出（当日额度用完）
FIRST_ROUND_TIMEOUT = 70            # 首轮等待广告结束超时（秒，给用户充足准备时间）
AD_COUNTDOWN_TIMEOUT = 65           # 单轮广告默认等待超时（秒，覆盖 30s~60s 长视频广告）
MAX_AD_TIMEOUT = 95                 # 动态倒计时延长上限（秒，防止死等）

# 无障碍控件检索模式（详见 .trae/rules/ascript.md §3.1：2=FILTERED_SIMPLE，root=9，hid=6）
SELECTOR_MODE = 2

# 无人值守相关
KEEP_SCREEN_ON = True               # 保持屏幕常亮，防止息屏中断
AUTO_RESTART_APP = True             # 连续失败时自动重启 App

# OCR 引擎：paddle=百度 PP-OCR V5（准） / mlkit=谷歌（快）
OCR_ENGINE = "paddle"

# "免"字按钮相对屏幕位置（实测 vivo V2055A 1080x2400：约 1012, 151）
MIAN_X_RATIO = 0.937
MIAN_Y_RATIO = 0.063

# 是否自动点"免"字进入广告
# True  = 全自动（脚本自己点，每轮都自动进广告）
# False = 半自动（你自己点第一次，之后脚本接管）
AUTO_CLICK_MIAN = True

# 运行时全局
SCREEN_W = 1080
SCREEN_H = 2400


# ============== 场景特征常量 ==============

# 系统合法权限弹窗包名（前台防劫持时放行，不强杀）
SAFE_SYSTEM_PACKAGES = (
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.android.packageinstaller",
    "android",
)

# 首页特征锚点
HOME_ANCHOR_KEYWORDS = ("模式探索", "发现", "音乐")

# 开屏跳过关键词
SPLASH_SKIP_KEYWORDS = ("跳过广告", "跳过")

# 普通弹窗黑名单与安全关闭按钮（不放泛化的"跳过"，防止误点广告内部元素）
POPUP_KEYWORDS = (
    "续费会员", "会员享专属", "开通会员", "立即开通",
    "看视频领取", "领取更多时长", "看视频得",
)
CLOSE_KEYWORDS = (
    "关闭", "以后再说", "暂不", "稍后", "我知道了", "取消", "×", "✕", "✖",
)

# 广告倒计时文案与继续观看挽留提示
COUNTDOWN_KEYWORDS = ("秒后可领取", "秒后领取", "秒后关闭", "秒后获得")
CONTINUE_WATCHING_KEYWORDS = ("继续观看", "继续看视频", "继续看广告")

# 当日额度领满特征（命中后立即体面退出，不空耗 10 轮）
QUOTA_EXHAUSTED_KEYWORDS = (
    "今日已领完", "今日次数已用完", "今日已达上限",
    "明日再来", "明天再来", "次数已用完",
)

# 直播间互动弹窗与已在直播间内特征（严格排除"是否继续"，防误点短剧"坚持退出"）
LIVE_PROMPT_HINTS = (
    "继续互动", "继续观看直播", "进入直播间",
    "秒后进入直播", "自动进入直播", "即将进入直播",
    "秒后进入", "自动进入",
)
LIVE_EXIT_BUTTONS = (
    "退出互动", "退出直播间", "不感兴趣", "退出", "取消", "关闭",
)
LIVE_ROOM_HINTS = (
    "更多直播", "说点什么", "在线观众", "直播间人数",
)

# 奖励领取第二步确认按钮
CLAIM_STEP2_KEYWORDS = (
    "领取奖励", "立即领取", "开心收下", "再看一个", "继续领奖励",
)


# ============== 工具函数 ==============

def log(msg: str):
    """统一日志打印（兼容 Windows 等非 UTF-8 控制台编码，永不抛出编码异常）"""
    ts = time.strftime("%H:%M:%S", time.localtime())
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, errors="replace").decode(enc, errors="replace"))


def _parse_rect(obj):
    """
    将多种边界格式统一解析为 [left, top, right, bottom]，无效或退化矩形返回 None。
    兼容：
      - AScript Rect 对象 (.x1, .y1, .x2, .y2)
      - Android Rect 对象 (.left, .top, .right, .bottom)
      - dict ({left,top,right,bottom} / {l,t,r,b} / {x1,y1,x2,y2})
      - 4 元 list / tuple
    """
    if obj is None:
        return None
    l = t = r = b = None
    try:
        if isinstance(obj, dict):
            if all(k in obj for k in ("left", "top", "right", "bottom")):
                l, t, r, b = obj["left"], obj["top"], obj["right"], obj["bottom"]
            elif all(k in obj for k in ("l", "t", "r", "b")):
                l, t, r, b = obj["l"], obj["t"], obj["r"], obj["b"]
            elif all(k in obj for k in ("x1", "y1", "x2", "y2")):
                l, t, r, b = obj["x1"], obj["y1"], obj["x2"], obj["y2"]
        elif isinstance(obj, (list, tuple)) and len(obj) == 4:
            l, t, r, b = obj[0], obj[1], obj[2], obj[3]
        else:
            x1 = getattr(obj, "x1", None)
            y1 = getattr(obj, "y1", None)
            x2 = getattr(obj, "x2", None)
            y2 = getattr(obj, "y2", None)
            if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
                l, t, r, b = x1, y1, x2, y2
            else:
                left = getattr(obj, "left", None)
                top = getattr(obj, "top", None)
                right = getattr(obj, "right", None)
                bottom = getattr(obj, "bottom", None)
                if left is not None and top is not None and right is not None and bottom is not None:
                    l, t, r, b = left, top, right, bottom
        if l is None or t is None or r is None or b is None:
            return None
        li, ti, ri, bi = int(l), int(t), int(r), int(b)
        if ri <= li or bi <= ti:
            return None
        return [li, ti, ri, bi]
    except Exception:
        return None


def _in_rect(cx: int, cy: int, rect) -> bool:
    """判断坐标是否落在指定区域 rect=[x1, y1, x2, y2] 内"""
    if not rect or len(rect) != 4:
        return True
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _extract_ocr_item(item):
    """
    统一提取 Ocr.find() / Ocr.find_all() 返回项为 (text, cx, cy)。
    同时兼容 dict 与 OcrText 对象，并在缺少 center_x/center_y 时通过 rect/bounds 回退计算中心点。
    """
    if item is None:
        return None
    try:
        if isinstance(item, dict):
            txt = item.get("text", "") or ""
            cx = item.get("center_x", 0) or 0
            cy = item.get("center_y", 0) or 0
            raw_rect = item.get("rect") if item.get("rect") is not None else item.get("bounds")
        else:
            txt = getattr(item, "text", "") or ""
            cx = getattr(item, "center_x", 0) or 0
            cy = getattr(item, "center_y", 0) or 0
            raw_rect = getattr(item, "rect", None)
            if raw_rect is None:
                raw_rect = getattr(item, "bounds", None)
        txt = str(txt)
        if not txt.strip():
            return None
        cx_i, cy_i = int(cx), int(cy)
        if cx_i <= 0 or cy_i <= 0:
            parsed = _parse_rect(raw_rect)
            if parsed:
                cx_i = (parsed[0] + parsed[2]) // 2
                cy_i = (parsed[1] + parsed[3]) // 2
        if cx_i <= 0 or cy_i <= 0:
            return None
        return (txt, cx_i, cy_i)
    except Exception:
        return None


def get_screen_size():
    """获取屏幕尺寸，读取 Device.display() 并提供安全默认值兜底"""
    try:
        d = Device.display()
        w = int(getattr(d, "widthPixels", 0) or 0)
        h = int(getattr(d, "heightPixels", 0) or 0)
        if w > 0 and h > 0:
            return w, h
    except Exception as e:
        log(f"  Device.display() 取值失败: {e}")
    return SCREEN_W, SCREEN_H


def safe_click(x, y, desc="", sleep_after=0.6) -> bool:
    """安全点击：边界校验 + 边缘钳位 + 日志 + 异常捕获"""
    try:
        ix = int(x)
        iy = int(y)
        if ix < 0 or iy < 0 or ix > SCREEN_W or iy > SCREEN_H:
            log(f"  ⚠️ 拦截越界点击 [{desc}] -> ({ix}, {iy})，屏幕范围 {SCREEN_W}x{SCREEN_H}")
            return False
        if ix == SCREEN_W and SCREEN_W > 0:
            ix = SCREEN_W - 1
        if iy == SCREEN_H and SCREEN_H > 0:
            iy = SCREEN_H - 1
        log(f"点击 [{desc}] -> ({ix}, {iy})")
        action.click(ix, iy)
        if sleep_after > 0:
            time.sleep(sleep_after)
        return True
    except Exception as e:
        log(f"点击失败 [{desc}]: {e}")
        return False


def _node_bounds(node):
    """从控件节点上取边界 [l, t, r, b]，兼容 AScript Rect(x1/y1/x2/y2) 与 Android Rect"""
    if node is None:
        return None
    for attr in ("bounds", "rect", "frame", "getBounds"):
        try:
            b = getattr(node, attr, None)
            if b is None:
                continue
            if callable(b):
                b = b()
            parsed = _parse_rect(b)
            if parsed:
                return parsed
        except Exception:
            continue
    return None


def _make_selector():
    """构造绑定 SELECTOR_MODE 的 Selector（兼容不接受 mode 参数的精简 Mock）"""
    try:
        return Selector(mode=SELECTOR_MODE)
    except TypeError:
        return Selector()


def _selector_find(text, rect=None, by="text"):
    """
    仅使用无障碍控件树按 text/desc 查找节点（15ms 级），并严格过滤 rect 范围。
    返回 dict 或 None。
    """
    try:
        sel = _make_selector()
        builder = getattr(sel, by, None)
        if not callable(builder):
            return None
        query = builder(text)
        nodes = None
        find_all_fn = getattr(query, "find_all", None)
        if callable(find_all_fn):
            nodes = find_all_fn()
        if nodes is None:
            find_fn = getattr(query, "find", None)
            if callable(find_fn):
                single = find_fn()
                nodes = [single] if single is not None else []
        if not nodes:
            return None
        for node in nodes:
            b = _node_bounds(node)
            if not b:
                continue
            cx = (b[0] + b[2]) // 2
            cy = (b[1] + b[3]) // 2
            if _in_rect(cx, cy, rect):
                return {
                    "text": text,
                    "center_x": cx,
                    "center_y": cy,
                    "confidence": 1.0,
                    "source": "selector",
                    "node": node,
                }
    except Exception:
        pass
    return None


def ocr_find(text, rect=None, confidence=0.1):
    """
    查找文字，返回 dict 或 None。
    1) 先试控件树 Selector（严格遵守 rect 过滤）
    2) 再试 OCR 带 rect 参数（返回兼容 dict 与 OcrText，二次校验坐标范围）
    3) 兜底：OCR 全屏查找 + 手动按 rect 坐标过滤
    """
    sel_hit = _selector_find(text, rect=rect, by="text")
    if sel_hit:
        return sel_hit

    if rect:
        try:
            r = Ocr.find(text, rect=rect, confidence=confidence)
            parsed = _extract_ocr_item(r)
            if parsed:
                txt, cx, cy = parsed
                if _in_rect(cx, cy, rect):
                    return {"text": txt, "center_x": cx, "center_y": cy,
                            "confidence": confidence, "source": "ocr"}
        except Exception:
            pass

    try:
        r = Ocr.find(text, confidence=confidence)
        parsed = _extract_ocr_item(r)
        if parsed:
            txt, cx, cy = parsed
            if _in_rect(cx, cy, rect):
                return {"text": txt, "center_x": cx, "center_y": cy,
                        "confidence": confidence, "source": "ocr"}
    except Exception as e:
        log(f"  OCR 查找 '{text}' 异常: {e}")
    return None


def ocr_exists(text, rect=None, confidence=0.1) -> bool:
    """判断文字是否存在"""
    return ocr_find(text, rect=rect, confidence=confidence) is not None


def scan_screen_texts():
    """
    一次全屏 OCR，返回 [(text, cx, cy), ...]。
    比反复调用 Ocr.find 快一个数量级（单次 paddle ~0.8s / mlkit ~0.4s）。
    自动兼容 dict 与 OcrText 两种返回结构。
    """
    try:
        items = Ocr.find_all()
        if not items:
            return []
        out = []
        for it in items:
            parsed = _extract_ocr_item(it)
            if parsed:
                out.append(parsed)
        return out
    except Exception as e:
        log(f"  全屏 OCR 异常: {e}")
        return []


def _find_in_texts(texts, keywords, rect=None, exclude=None):
    """在 scan_screen_texts() 结果中按优先级在内存里匹配关键词（零额外 OCR 开销）"""
    if not texts:
        return None
    for kw in keywords:
        for t, x, y in texts:
            if kw not in t:
                continue
            if exclude and any(ex in t for ex in exclude):
                continue
            if not _in_rect(x, y, rect):
                continue
            return (t, x, y)
    return None


def init_regions():
    """初始化屏幕尺寸"""
    global SCREEN_W, SCREEN_H
    SCREEN_W, SCREEN_H = get_screen_size()
    log(f"屏幕尺寸: {SCREEN_W} x {SCREEN_H}")


def get_foreground_app() -> str:
    """安全获取当前前台应用包名"""
    try:
        return str(system.get_foreground_app() or "").strip()
    except Exception:
        return ""


def ensure_in_app() -> bool:
    """
    前台防劫持检查：防止点击广告跳转至应用商店 / 浏览器 / 第三方落地页。
    若检测到离开汽水音乐（且非系统授权弹窗），立即拉回 App 并返回 True（表示执行了拉回动作）。
    """
    fg = get_foreground_app()
    if not fg:
        return False
    if APP_PACKAGE in fg:
        return False
    if any(pkg in fg for pkg in SAFE_SYSTEM_PACKAGES):
        return False
    log(f"  ⚠️ 检测到前台跳转劫持（当前应用: {fg}），正在切回汽水音乐...")
    try:
        system.open(APP_PACKAGE)
        time.sleep(2.0)
        return True
    except Exception as e:
        log(f"  拉回汽水音乐失败: {e}")
        return False


# ============== 阶段一：启动 App ==============

def launch_app() -> bool:
    """启动汽水音乐 App（安卓用 system.open 传包名）"""
    log("=" * 50)
    log("阶段一：启动汽水音乐 App")
    try:
        system.open(APP_PACKAGE)
        log("App 启动指令已发送")
        time.sleep(2.5)
        fg = get_foreground_app()
        if fg:
            log(f"当前前台应用: {fg}")
        return True
    except Exception as e:
        log(f"启动 App 异常: {e}")
        return False


def click_mian_button() -> bool:
    """
    点击右上角"免"字按钮。
    实测该按钮是图片（无 text/desc 属性），OCR 也识别不出，只能用比例坐标。
    """
    x = int(SCREEN_W * MIAN_X_RATIO)
    y = int(SCREEN_H * MIAN_Y_RATIO)
    log(f"点击'免'字按钮（比例坐标）-> ({x}, {y})")
    return safe_click(x, y, "免字按钮")


# ============== 阶段二：开屏广告 & 弹窗清理 ==============

def skip_splash_ad(timeout=5) -> bool:
    """
    跳过开屏广告（右上角区域轮询）。
    优先用控件树快速命中，单次全屏 OCR 兜底；若已出现首页锚点则立即提前结束，避免白等。
    """
    log("阶段二：检测并跳过开屏广告")
    rect_skip = [int(SCREEN_W * 0.60), 0, SCREEN_W, int(SCREEN_H * 0.22)]
    deadline = time.time() + timeout
    scan = 0
    while time.time() < deadline:
        scan += 1
        # 1) 控件树优先检测右上角跳过控件（毫秒级）
        for kw in SPLASH_SKIP_KEYWORDS:
            sel_hit = _selector_find(kw, rect=rect_skip, by="text") or _selector_find(kw, rect=rect_skip, by="desc")
            if sel_hit:
                log(f"  [扫描#{scan} Selector] 命中开屏跳过: '{sel_hit.get('text')}'")
                safe_click(sel_hit["center_x"], sel_hit["center_y"], "跳过开屏广告")
                return True

        # 2) 单次全屏 OCR：同时检测开屏跳过与首页就绪（已进首页则直接短路退出）
        texts = scan_screen_texts()
        hit = _find_in_texts(texts, SPLASH_SKIP_KEYWORDS, rect=rect_skip)
        if hit:
            t, cx, cy = hit
            log(f"  [扫描#{scan} OCR] 命中开屏跳过: '{t}'")
            safe_click(cx, cy, "跳过开屏广告")
            return True
        if is_on_home_page(texts):
            log(f"  [扫描#{scan}] 已直接进入首页，无需等待开屏超时")
            return False
        time.sleep(0.3)
    log(f"  扫描结束（{scan} 次），未检测到开屏广告")
    return False


def dismiss_popups(max_rounds=3) -> int:
    """
    清理各类弹窗（会员续费 / 看视频领时长 等）。
    每轮只做一次 scan_screen_texts() 全屏扫描，在内存中同时检查弹窗与关闭按钮，效率提升约 14 倍。
    """
    log("阶段二B：清理弹窗")
    closed = 0
    for _ in range(max_rounds):
        texts = scan_screen_texts()
        if not texts:
            break
        hit_kw = None
        for kw in POPUP_KEYWORDS:
            if any(kw in t for t, _, _ in texts):
                hit_kw = kw
                break
        if not hit_kw:
            break
        log(f"  检测到弹窗关键词: '{hit_kw}'")

        close_hit = _find_in_texts(texts, CLOSE_KEYWORDS)
        if close_hit:
            ck, cx, cy = close_hit
            if safe_click(cx, cy, f"关闭弹窗({ck})"):
                closed += 1
                time.sleep(1.0)
                continue

        # OCR 未识别出文字关闭按钮时，尝试无障碍 desc 图标按钮（如 × 图标）
        desc_hit = _selector_find("关闭", by="desc") or _selector_find("取消", by="desc")
        if desc_hit:
            if safe_click(desc_hit["center_x"], desc_hit["center_y"], "关闭弹窗(控件desc)"):
                closed += 1
                time.sleep(1.0)
                continue

        log("  未找到关闭按钮，尝试点击屏幕上方空白区")
        safe_click(SCREEN_W // 2, int(SCREEN_H * 0.08), "空白区")
        closed += 1
        time.sleep(1.0)
    log(f"  弹窗清理完成，共处理 {closed} 个")
    return closed


# ============== 首页状态判断与恢复 ==============

def is_on_home_page(texts=None) -> bool:
    """判断当前是否停留在汽水音乐首页（支持复用已有 scan_screen_texts 结果）"""
    for kw in HOME_ANCHOR_KEYWORDS:
        if _selector_find(kw, by="text"):
            return True
    if texts is None:
        texts = scan_screen_texts()
    return _find_in_texts(texts, HOME_ANCHOR_KEYWORDS) is not None


def ensure_home_page(max_rounds=3) -> bool:
    """确保停在汽水音乐首页：先拦截外跳劫持，再尝试清弹窗与返回键退出"""
    ensure_in_app()
    for i in range(max_rounds):
        texts = scan_screen_texts()
        if is_on_home_page(texts):
            log("  已在首页")
            return True
        if any(kw in t for t, _, _ in texts for kw in POPUP_KEYWORDS):
            if dismiss_popups(max_rounds=1) > 0:
                continue
        log(f"  未在首页，按返回键（{i + 1}/{max_rounds}）")
        try:
            action.Key.back()
        except Exception as e:
            log(f"  返回键异常: {e}")
            break
        time.sleep(1.5)
    return is_on_home_page()


# ============== 阶段四：等待广告倒计时结束 ==============

def _is_short_drama_retention(joined: str) -> bool:
    """
    识别"短剧/视频广告中途挽留弹窗"（例如"再看05秒继续解锁 / 继续观看 / 坚持退出"），
    防止被直播拦截逻辑误触发而点中"坚持退出"导致放弃奖励。
    """
    has_continue = any(kw in joined for kw in CONTINUE_WATCHING_KEYWORDS)
    if has_continue and "直播" not in joined and "互动" not in joined:
        return True
    if "坚持退出" in joined and (has_continue or "再看" in joined or "免费听" in joined):
        return True
    return False


def _is_live_prompt(joined: str) -> bool:
    """判断是否为进直播间前的互动挽留弹窗"""
    if not any(kw in joined for kw in LIVE_PROMPT_HINTS):
        return False
    return not _is_short_drama_retention(joined)


def handle_live_prompt(texts) -> bool:
    """
    处理"继续互动 / 退出"弹窗（进直播间之前的拦截点）。
    只点退出类按钮，绝不点击含"继续 / 进入 / 坚持 / 放弃"的按钮。
    """
    hit = _find_in_texts(texts, LIVE_EXIT_BUTTONS, exclude=("继续", "进入", "坚持", "放弃"))
    if hit:
        t, x, y = hit
        log(f"    ⚠️  直播互动弹窗 → 点击退出 '{t}' @ ({x}, {y})")
        safe_click(x, y, f"退出直播广告({t})", sleep_after=1.5)
        return True

    log("    未找到退出按钮，按返回键兜底")
    try:
        action.Key.back()
        time.sleep(1.2)
        return True
    except Exception as e:
        log(f"    返回键异常: {e}")
    return False


def handle_live_room(texts) -> bool:
    """
    处理已进入直播间的情况：直播间不算广告时长，必须立即退出。
    优先级：1) 顶部关闭/退出无障碍控件 → 2) 顶部关闭文字/符号 → 3) 右上角 X → 4) 返回键兜底。
    """
    top_rect = [0, 0, SCREEN_W, int(SCREEN_H * 0.20)]

    # 1) 安卓优势：无障碍控件树识别纯图标关闭按钮（如 ImageView contentDescription="关闭"）
    for desc in ("关闭", "退出"):
        sel_hit = _selector_find(desc, rect=top_rect, by="desc")
        if sel_hit:
            log(f"    ⚠️  已在直播间 → 点击顶部控件[{desc}] @ ({sel_hit['center_x']}, {sel_hit['center_y']})")
            safe_click(sel_hit["center_x"], sel_hit["center_y"], f"关闭直播间(desc:{desc})", sleep_after=1.5)
            return True

    # 2) OCR 识别顶部文字或常见叉号
    hit = _find_in_texts(texts, ("关闭", "退出", "×", "✕", "✖"), rect=top_rect)
    if hit:
        t, x, y = hit
        log(f"    ⚠️  已在直播间 → 点击顶部 '{t}' @ ({x}, {y})")
        safe_click(x, y, f"关闭直播间({t})", sleep_after=1.5)
        return True

    # 3) 右上角单个 X 按钮（严格限定右上角小区域，避免误点普通文本里的 X）
    top_right_x = [int(SCREEN_W * 0.78), 0, SCREEN_W, int(SCREEN_H * 0.18)]
    for t, x, y in texts:
        if t.strip() in ("X", "x") and _in_rect(x, y, top_right_x):
            log(f"    ⚠️  已在直播间 → 点击右上角 '{t}' @ ({x}, {y})")
            safe_click(x, y, "关闭直播间(X)", sleep_after=1.5)
            return True

    # 4) 返回键兜底
    log("    未找到关闭按钮，按返回键兜底")
    try:
        action.Key.back()
        time.sleep(1.5)
        return True
    except Exception as e:
        log(f"    返回键异常: {e}")
    return False


def check_and_click_continue_watching(texts=None) -> bool:
    """
    检测并点击屏幕中间的"继续观看 / 继续看视频 / 继续看广告"。
    注意：
      - 严格限定中间区域（y: 25%~68%），绝不点底部的广告下载按钮
      - 排除包含"直播 / 互动"的按钮（点了会进直播间）
    """
    if texts is None:
        texts = scan_screen_texts()
    center_rect = [0, int(SCREEN_H * 0.25), SCREEN_W, int(SCREEN_H * 0.68)]
    for t, x, y in texts:
        if not any(kw in t for kw in CONTINUE_WATCHING_KEYWORDS):
            continue
        if "直播" in t or "互动" in t:
            log(f"  跳过 '{t}'（直播相关，点了会进直播间）")
            continue
        if not _in_rect(x, y, center_rect):
            continue
        log(f"  命中中间区'{t}' → 点击恢复广告")
        if safe_click(x, y, "继续观看(中间区)", sleep_after=2.5):
            return True
    return False


def wait_ad_countdown(timeout=AD_COUNTDOWN_TIMEOUT, stats=None):
    """
    等待广告倒计时结束，顶部区域出现"领取成功"。
    返回 (status, pos)：
      - ("ready", (cx, cy))         -> 顶部出现"领取成功"（携带坐标供阶段五直接点击）
      - ("quota_exhausted", None)   -> 检测到当日额度已领完
      - ("timeout", None)           -> 超时未检测到广告结束
    """
    log("阶段四：等待广告倒计时结束")
    start_ts = time.time()
    deadline = start_ts + timeout
    hard_deadline = start_ts + max(timeout, MAX_AD_TIMEOUT)
    checks = 0
    last_sec = -1
    consecutive_live_exits = 0

    top_reward_rect = [0, 0, SCREEN_W, int(SCREEN_H * 0.25)]
    top_countdown_rect = [0, 0, SCREEN_W, int(SCREEN_H * 0.18)]

    while time.time() < deadline:
        checks += 1

        # 每 3 轮检测一次前台应用，防止广告误触跳去应用商店/浏览器
        if checks % 3 == 0:
            if ensure_in_app():
                if stats is not None:
                    stats["hijacks"] = stats.get("hijacks", 0) + 1
                consecutive_live_exits = 0
                continue

        texts = scan_screen_texts()
        if not texts:
            time.sleep(0.5)
            continue

        # 1) 最高优先：顶部状态栏出现"领取成功"（限定顶部 y<25%，屏蔽广告底部假文案）
        reward_hit = _find_in_texts(texts, ("领取成功",), rect=top_reward_rect)
        if reward_hit:
            _, rx, ry = reward_hit
            log(f"  检测到顶部'领取成功' @ ({rx}, {ry})（轮询 {checks} 次）")
            return ("ready", (rx, ry))

        joined = " | ".join(t for t, _, _ in texts)

        # 2) 当日额度已用完，提前优雅退出
        if any(kw in joined for kw in QUOTA_EXHAUSTED_KEYWORDS):
            log("  ⚠️  检测到当日广告额度已领完，准备退出")
            return ("quota_exhausted", None)

        # 3) 直播互动弹窗（先排除短剧挽留弹窗）
        if _is_live_prompt(joined):
            log(f"  ⚠️  识别到直播互动弹窗（轮询 {checks} 次）")
            if stats is not None:
                stats["live_prompts"] = stats.get("live_prompts", 0) + 1
            if handle_live_prompt(texts):
                continue

        # 4) 已在直播间（连续 3 次退出仍卡在直播间时强制切回汽水音乐）
        if any(kw in joined for kw in LIVE_ROOM_HINTS):
            consecutive_live_exits += 1
            log(f"  ⚠️  识别到直播间界面（第 {consecutive_live_exits} 次 / 轮询 {checks} 次）")
            if stats is not None:
                stats["live_rooms"] = stats.get("live_rooms", 0) + 1
            if consecutive_live_exits >= 3:
                log("  ⚠️  连续 3 次退出直播间未生效，直接拉回汽水音乐")
                try:
                    system.open(APP_PACKAGE)
                    time.sleep(2.5)
                except Exception as e:
                    log(f"  拉回 App 异常: {e}")
                consecutive_live_exits = 0
                continue
            if handle_live_room(texts):
                continue

        # 5) 完整解析多位倒计时数字并动态顺延等待窗口（防 45s~60s 长广告中途超时）
        countdown_item = None
        for t, x, y in texts:
            if not _in_rect(x, y, top_countdown_rect):
                continue
            if any(ck in t for ck in COUNTDOWN_KEYWORDS):
                countdown_item = t
                break
            if "秒后" in t and "进入" not in t and countdown_item is None:
                countdown_item = t
        if countdown_item:
            m = re.search(r"(\d+)\s*秒后", countdown_item)
            if m:
                sec = int(m.group(1))
                if sec != last_sec:
                    log(f"  广告倒计时中... {countdown_item}")
                    last_sec = sec
                # 根据剩余秒数平滑延长截止时间（最多不超过 hard_deadline）
                deadline = min(hard_deadline, max(deadline, time.time() + sec + 15))
                consecutive_live_exits = 0

        # 6) 短剧/视频中途挽留或意外暂停 → 点击"继续观看"
        if check_and_click_continue_watching(texts):
            consecutive_live_exits = 0
            continue

        time.sleep(0.6)

    log(f"  等待超时（{int(time.time() - start_ts)}s），顶部'领取成功'未出现")
    return ("timeout", None)


# ============== 阶段五：领取奖励 ==============

def claim_reward(reward_pos=None) -> str:
    """
    两步领取（实测汽水音乐安卓版流程）：
      步骤1：点击顶部「领取成功」（优先复用阶段四坐标，省去重复找字）
      步骤2：弹窗出现「领取奖励」→ 点击进入下一轮；或已直接回首页自动到账
    返回值："claimed" | "quota_exhausted" | "failed"
    """
    log("阶段五：领取奖励")
    top_reward_rect = [0, 0, SCREEN_W, int(SCREEN_H * 0.25)]
    step2_rect = [0, int(SCREEN_H * 0.20), SCREEN_W, int(SCREEN_H * 0.85)]

    # 步骤1：点顶部「领取成功」
    ok1 = False
    if reward_pos and len(reward_pos) == 2 and reward_pos[1] < SCREEN_H * 0.25:
        ok1 = safe_click(reward_pos[0], reward_pos[1], "步骤1-领取成功")
    if not ok1:
        r = ocr_find("领取成功", rect=top_reward_rect)
        if r:
            ok1 = safe_click(r["center_x"], r["center_y"], "步骤1-领取成功")
    if not ok1:
        log("  步骤1失败：顶部未找到'领取成功'")
        return "failed"

    time.sleep(1.5)

    # 步骤2：最多轮询 3 次（每次仅 1 次全屏 OCR），兼顾弹出延迟、自动到账与额度用尽
    for attempt in range(3):
        texts = scan_screen_texts()
        joined = " | ".join(t for t, _, _ in texts)

        if any(kw in joined for kw in QUOTA_EXHAUSTED_KEYWORDS):
            log("  ⚠️  弹窗提示当日额度已领完")
            close_hit = _find_in_texts(texts, CLOSE_KEYWORDS)
            if close_hit:
                safe_click(close_hit[1], close_hit[2], f"关闭额度提示({close_hit[0]})")
            return "quota_exhausted"

        step2_hit = (
            _find_in_texts(texts, CLAIM_STEP2_KEYWORDS, rect=step2_rect)
            or _find_in_texts(texts, CLAIM_STEP2_KEYWORDS)
        )
        if step2_hit:
            kw, kx, ky = step2_hit
            if safe_click(kx, ky, f"步骤2-{kw}"):
                log("  ✅ 两步领取完成，自动进入下一轮")
                return "claimed"

        if is_on_home_page(texts):
            log("  ✅ 已回到首页（奖励已自动到账）")
            return "claimed"

        # 若首次尝试后顶部仍卡在"领取成功"，说明步骤 1 未触发有效点击，重试一次
        if attempt == 0:
            still_top = _find_in_texts(texts, ("领取成功",), rect=top_reward_rect)
            if still_top:
                log("  步骤1点击未生效，重试点一次'领取成功'")
                safe_click(still_top[1], still_top[2], "步骤1重试-领取成功")
        time.sleep(0.8)

    final_texts = scan_screen_texts()
    if _find_in_texts(final_texts, ("领取成功",), rect=top_reward_rect):
        log("  步骤1后仍停留在'领取成功'且未见奖励弹窗，判定本轮失败")
        return "failed"

    log("  步骤2未命中'领取奖励'按钮，但顶部状态已消除（视为已到账）")
    return "claimed"


# ============== 主流程 ==============

def run_ad_loop(stats=None) -> int:
    """核心广告领取循环"""
    if stats is None:
        stats = {"claimed": 0, "live_prompts": 0, "live_rooms": 0, "hijacks": 0, "restarts": 0}

    log("\n" + "#" * 60)
    log("🎯 进入核心广告领取循环")
    log("#" * 60)
    if AUTO_CLICK_MIAN:
        log("   🤖 全自动模式运行中，脚本将自动接管每轮广告与奖励领取")
    else:
        log("   ⚠️  半自动模式：请在手机上手动点一次右上角'免'字，后续由脚本接管")

    success_count = 0
    round_idx = 0
    idle_count = 0

    while round_idx < MAX_LOOP_COUNT:
        round_idx += 1
        log(f"\n---- 第 {round_idx} 轮 ----")
        ensure_awake()

        wait_sec = FIRST_ROUND_TIMEOUT if round_idx == 1 else AD_COUNTDOWN_TIMEOUT
        status, reward_pos = wait_ad_countdown(timeout=wait_sec, stats=stats)

        if status == "quota_exhausted":
            log("  🎉 今日广告奖励额度已全部领完，体面退出")
            break

        if status != "ready":
            idle_count += 1
            log(f"  本轮未检测到广告结束（连续 {idle_count}/{MAX_IDLE_ROUNDS}）")
            if idle_count >= MAX_IDLE_ROUNDS:
                log(f"  ⚠️  连续 {MAX_IDLE_ROUNDS} 轮无广告，可能当日额度已用完，退出")
                break

            # 先拦截可能已跳转至外部应用的界面
            if ensure_in_app():
                stats["hijacks"] = stats.get("hijacks", 0) + 1

            # 连续失败达到 3 的倍数：重启 App 清理异常状态并重新过开屏/弹窗
            if AUTO_RESTART_APP and idle_count % 3 == 0:
                log("  尝试重启 App 恢复状态")
                try:
                    system.open(APP_PACKAGE)
                    stats["restarts"] = stats.get("restarts", 0) + 1
                    time.sleep(3.5)
                    skip_splash_ad(timeout=4)
                    dismiss_popups(max_rounds=2)
                except Exception as e:
                    log(f"  重启异常: {e}")

            on_home = ensure_home_page(max_rounds=3)
            if AUTO_CLICK_MIAN:
                dismiss_popups(max_rounds=1)
                if on_home or is_on_home_page():
                    log("  已确认处于首页 → 尝试重新点击'免'字进入广告")
                    click_mian_button()
                    time.sleep(2.5)
                else:
                    log("  ⚠️  未确认处于首页，跳过点击'免'字以防误触")
            time.sleep(2.0)
            continue

        res = claim_reward(reward_pos=reward_pos)
        if res == "claimed":
            success_count += 1
            stats["claimed"] = success_count
            idle_count = 0
            log(f"  ✅ 第 {round_idx} 轮成功，累计 {success_count} 次")
        elif res == "quota_exhausted":
            log("  🎉 今日广告奖励额度已全部领完，体面退出")
            break
        else:
            idle_count += 1
            log(f"  ⚠️  第 {round_idx} 轮领取失败（连续 {idle_count}/{MAX_IDLE_ROUNDS}）")
            if idle_count >= MAX_IDLE_ROUNDS:
                log(f"  ⚠️  连续 {MAX_IDLE_ROUNDS} 轮失败，退出")
                break

        time.sleep(LOOP_INTERVAL)

    return success_count


def setup_unattended():
    """无人值守设置：屏幕常亮 + 唤醒"""
    if not KEEP_SCREEN_ON:
        return
    try:
        Device.keep_screen_on()
        log("已开启屏幕常亮（防止息屏中断）")
    except Exception as e:
        log(f"屏幕常亮设置失败: {e}")
    try:
        Device.wake_up()
    except Exception:
        pass


def ensure_awake():
    """每轮开始前确保屏幕亮着"""
    try:
        Device.wake_up()
    except Exception:
        pass


def main():
    """脚本入口"""
    start_time = time.time()
    stats = {"claimed": 0, "live_prompts": 0, "live_rooms": 0, "hijacks": 0, "restarts": 0}
    log("🎵 汽水音乐自动看广告脚本（安卓版）启动")
    log(f"   包名: {APP_PACKAGE} | OCR引擎: {OCR_ENGINE} | 自动点免字: {AUTO_CLICK_MIAN}")
    try:
        init_regions()
        if OCR_ENGINE in ("paddle", "mlkit"):
            try:
                Ocr.set_engine(OCR_ENGINE)
                log(f"OCR 引擎已设置为 {OCR_ENGINE}")
            except Exception as e:
                log(f"设置 OCR 引擎失败（用默认）: {e}")
        else:
            log(f"  ⚠️ 未知 OCR_ENGINE={OCR_ENGINE!r}，保持默认引擎")

        setup_unattended()

        if not launch_app():
            log("❌ 无法启动汽水音乐，脚本终止")
            return

        skip_splash_ad(timeout=6)
        dismiss_popups(max_rounds=3)

        if not ensure_home_page(max_rounds=3):
            log("  未能回到首页，重新启动 App 再试")
            try:
                system.open(APP_PACKAGE)
                stats["restarts"] += 1
                time.sleep(4)
                skip_splash_ad(timeout=4)
                dismiss_popups(max_rounds=2)
            except Exception as e:
                log(f"  重启异常: {e}")

        if AUTO_CLICK_MIAN:
            if is_on_home_page():
                log("\n自动模式（前置校验通过）：脚本将自动点'免'字进入广告")
                click_mian_button()
                time.sleep(3.5)
            else:
                log("\n⚠️  未检测到首页特征，暂不自动点'免'字，直接进入状态监听轮次")
        else:
            log("\n" + "=" * 50)
            log("✅ 准备工作完成，现在请你操作手机：")
            log("   1. 确保汽水音乐停在首页")
            log("   2. 手动点右上角'免'字（搜索框右边那个）")
            log("   3. 进入广告后不用管，脚本自动接管")
            log("=" * 50)

        run_ad_loop(stats=stats)

    except KeyboardInterrupt:
        log("⏹ 收到手动中断信号，脚本安全停止")
    except Exception as e:
        log(f"❌ 脚本异常: {e}")
        traceback.print_exc()
    finally:
        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)
        log("=" * 60)
        log(
            f"✅ 运行统计 | 耗时: {mins}分{secs}秒 | 成功领取: {stats['claimed']} 次 | "
            f"拦截直播弹窗: {stats['live_prompts']} 次 | 退出直播间: {stats['live_rooms']} 次 | "
            f"防劫持拉回: {stats['hijacks']} 次 | App重启: {stats['restarts']} 次"
        )
        log("脚本退出")


# ============== 入口：AScript 工程约定顶层直接执行 ==============
if os.environ.get("QISHUI_TEST_MODE") != "1":
    main()
