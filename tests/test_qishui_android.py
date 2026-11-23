# -*- coding: utf-8 -*-
"""
汽水音乐安卓自动化脚本单元测试套件（纯标准库，无需真机环境即可本地与 CI 闭环验证）
"""

import importlib.util
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT_DIR, "__init__.py")


class FakeAScriptRect:
    """模拟 AScript Rect(x1, y1, x2, y2)"""

    def __init__(self, x1, y1, x2, y2):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2


class FakeAndroidRect:
    """模拟 Android Rect(left, top, right, bottom)"""

    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeNode:
    """模拟无障碍控件节点"""

    def __init__(self, bounds=None, rect=None, callable_bounds=False):
        if bounds is not None:
            self.bounds = (lambda: bounds) if callable_bounds else bounds
        if rect is not None:
            self.rect = rect


class FakeOcrText:
    """模拟 AScript OcrText 对象"""

    def __init__(self, text, center_x=0, center_y=0, rect=None, bounds=None):
        self.text = text
        self.center_x = center_x
        self.center_y = center_y
        self.rect = rect
        self.bounds = bounds


class _StubRegistry:
    """集中管理所有 AScript API Stub，便于每个用例隔离重置"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clicks = []
        self.backs = 0
        self.opened_packages = []
        self.foreground_app = "com.luna.music"
        self.display_size = (1080, 2400)
        self.ocr_engine_set = None
        self.keep_screen_on_calls = 0
        self.wake_up_calls = 0

        self.selector_modes = []
        self.selector_handler = lambda by, val: None
        self.selector_supports_mode = True
        self.selector_has_find_all = True

        self.ocr_find_calls = []
        self.ocr_find_handler = lambda text, rect=None, confidence=0.1: None

        self.ocr_find_all_calls = 0
        self.ocr_find_all_handler = lambda: []


STUBS = _StubRegistry()


def _install_ascript_stubs():
    """向 sys.modules 注入轻量 ascript.android.* 桩模块"""
    ascript_mod = types.ModuleType("ascript")
    android_mod = types.ModuleType("ascript.android")

    action_mod = types.ModuleType("ascript.android.action")

    class _Key:
        @staticmethod
        def back():
            STUBS.backs += 1

    action_mod.Key = _Key
    action_mod.click = lambda x, y: STUBS.clicks.append((x, y))

    system_mod = types.ModuleType("ascript.android.system")
    system_mod.open = lambda pkg: STUBS.opened_packages.append(pkg)
    system_mod.get_foreground_app = lambda: STUBS.foreground_app

    class _DisplayObj:
        @property
        def widthPixels(self):
            return STUBS.display_size[0]

        @property
        def heightPixels(self):
            return STUBS.display_size[1]

    class _Device:
        @staticmethod
        def display():
            return _DisplayObj()

        @staticmethod
        def keep_screen_on():
            STUBS.keep_screen_on_calls += 1

        @staticmethod
        def wake_up():
            STUBS.wake_up_calls += 1

    system_mod.Device = _Device

    screen_mod = types.ModuleType("ascript.android.screen")

    class _Ocr:
        @staticmethod
        def set_engine(engine):
            STUBS.ocr_engine_set = engine

        @staticmethod
        def find(text, rect=None, confidence=0.1):
            STUBS.ocr_find_calls.append((text, rect, confidence))
            return STUBS.ocr_find_handler(text, rect=rect, confidence=confidence)

        @staticmethod
        def find_all():
            STUBS.ocr_find_all_calls += 1
            return STUBS.ocr_find_all_handler()

    screen_mod.Ocr = _Ocr

    node_mod = types.ModuleType("ascript.android.node")

    class _SelectorQuery:
        def __init__(self, by, val):
            self._by = by
            self._val = val

        def find(self):
            res = STUBS.selector_handler(self._by, self._val)
            if isinstance(res, list):
                return res[0] if res else None
            return res

        def find_all(self):
            if not STUBS.selector_has_find_all:
                return None
            res = STUBS.selector_handler(self._by, self._val)
            if res is None:
                return []
            return res if isinstance(res, list) else [res]

    class _Selector:
        def __init__(self, mode=None):
            if mode is not None and not STUBS.selector_supports_mode:
                raise TypeError("Selector() takes no keyword arguments")
            STUBS.selector_modes.append(mode)

        def text(self, val):
            return _SelectorQuery("text", val)

        def desc(self, val):
            return _SelectorQuery("desc", val)

    node_mod.Selector = _Selector

    android_mod.action = action_mod
    android_mod.system = system_mod
    android_mod.screen = screen_mod
    android_mod.node = node_mod
    ascript_mod.android = android_mod

    sys.modules["ascript"] = ascript_mod
    sys.modules["ascript.android"] = android_mod
    sys.modules["ascript.android.action"] = action_mod
    sys.modules["ascript.android.system"] = system_mod
    sys.modules["ascript.android.screen"] = screen_mod
    sys.modules["ascript.android.node"] = node_mod


def _load_target_module():
    os.environ["QISHUI_TEST_MODE"] = "1"
    _install_ascript_stubs()
    spec = importlib.util.spec_from_file_location("qishui_android_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qishui = _load_target_module()


def _ocr_dicts(*entries):
    """构造真实 AScript Ocr.find_all() 返回的 dict 列表"""
    return [{"text": t, "center_x": x, "center_y": y} for t, x, y in entries]


class _FakeClock:
    """确定性可控时钟，让超时与动态顺延测试毫秒级完成"""

    def __init__(self, step=1.0):
        self.now = 1000.0
        self.step = step
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, secs):
        self.sleeps.append(secs)
        self.now += max(secs, self.step)


class TestQishuiAndroid(unittest.TestCase):
    def setUp(self):
        STUBS.reset()
        qishui.SCREEN_W = 1080
        qishui.SCREEN_H = 2400
        qishui.AUTO_CLICK_MIAN = True
        qishui.AUTO_RESTART_APP = True
        qishui.MAX_IDLE_ROUNDS = 10
        qishui.MAX_LOOP_COUNT = 100
        qishui.FIRST_ROUND_TIMEOUT = 70
        qishui.AD_COUNTDOWN_TIMEOUT = 65
        qishui.MAX_AD_TIMEOUT = 95

    # ---------- 1. _parse_rect / _node_bounds ----------

    def test_node_bounds_ascript_rect_x1_y1_x2_y2(self):
        node = FakeNode(rect=FakeAScriptRect(100, 200, 300, 400))
        self.assertEqual(qishui._node_bounds(node), [100, 200, 300, 400])

    def test_node_bounds_android_rect_and_callable_bounds(self):
        node = FakeNode(bounds=FakeAndroidRect(10, 20, 110, 120), callable_bounds=True)
        self.assertEqual(qishui._node_bounds(node), [10, 20, 110, 120])

    def test_parse_rect_dict_list_and_degenerate_rejection(self):
        self.assertEqual(qishui._parse_rect({"l": 1, "t": 2, "r": 50, "b": 60}), [1, 2, 50, 60])
        self.assertEqual(qishui._parse_rect({"x1": 5, "y1": 10, "x2": 25, "y2": 40}), [5, 10, 25, 40])
        self.assertEqual(qishui._parse_rect((10, 20, 30, 40)), [10, 20, 30, 40])
        self.assertIsNone(qishui._parse_rect([100, 100, 100, 200]))  # 宽度为 0 退化矩形
        self.assertIsNone(qishui._parse_rect([10, 200, 50, 100]))    # bottom <= top
        self.assertIsNone(qishui._parse_rect(None))

    # ---------- 2. safe_click ----------

    def test_safe_click_bounds_clamp_and_out_of_range(self):
        with patch.object(qishui.time, "sleep"):
            self.assertTrue(qishui.safe_click(500, 600, "normal"))
            self.assertEqual(STUBS.clicks[-1], (500, 600))

            # 精确边界值钳位至 SCREEN_W - 1 / SCREEN_H - 1
            self.assertTrue(qishui.safe_click(1080, 2400, "edge"))
            self.assertEqual(STUBS.clicks[-1], (1079, 2399))

            # 越界坐标被拦截
            self.assertFalse(qishui.safe_click(-5, 100, "neg"))
            self.assertFalse(qishui.safe_click(1200, 100, "over_x"))
            self.assertFalse(qishui.safe_click(100, 2500, "over_y"))
            self.assertEqual(len(STUBS.clicks), 2)

    # ---------- 3. ocr_find & Selector mode & OcrText ----------

    def test_ocr_find_selector_mode_and_rect_filtering(self):
        outside_node = FakeNode(rect=FakeAScriptRect(100, 1800, 300, 1900))
        inside_node = FakeNode(rect=FakeAScriptRect(900, 80, 1020, 160))
        STUBS.selector_handler = lambda by, val: [outside_node, inside_node]

        hit = qishui.ocr_find("跳过", rect=[600, 0, 1080, 500])
        self.assertIsNotNone(hit)
        self.assertEqual(hit["source"], "selector")
        self.assertEqual((hit["center_x"], hit["center_y"]), (960, 120))
        self.assertIn(qishui.SELECTOR_MODE, STUBS.selector_modes)

        # 所有匹配都在 rect 外时应返回 None
        STUBS.selector_handler = lambda by, val: [outside_node]
        self.assertIsNone(qishui.ocr_find("跳过", rect=[600, 0, 1080, 500]))

    def test_ocr_find_accepts_ocrtext_object_and_enforces_rect(self):
        # 模拟 Ocr.find 返回 OcrText 对象，且带 rect 过滤验证
        def _fake_find(text, rect=None, confidence=0.1):
            if rect is not None:
                return FakeOcrText(text, center_x=200, center_y=1800)  # 故意返回区外坐标
            return FakeOcrText(text, center_x=0, center_y=0, rect=FakeAScriptRect(900, 50, 1000, 150))

        STUBS.ocr_find_handler = _fake_find
        hit = qishui.ocr_find("领取成功", rect=[0, 0, 1080, 600])
        self.assertIsNotNone(hit)
        self.assertEqual((hit["center_x"], hit["center_y"]), (950, 100))

    # ---------- 4. skip_splash_ad ----------

    def test_skip_splash_ad_hits_top_right_and_ignores_outside(self):
        clock = _FakeClock()
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(
            ("跳过", 200, 2100),      # 底部非开屏区域，应忽略
            ("跳过广告", 980, 120),   # 右上角区域，应点击
        )
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            ok = qishui.skip_splash_ad(timeout=5)
        self.assertTrue(ok)
        self.assertEqual(STUBS.clicks, [(980, 120)])

    def test_skip_splash_ad_short_circuits_on_home_anchor(self):
        clock = _FakeClock()
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(("模式探索", 200, 180), ("发现", 540, 2300))
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            ok = qishui.skip_splash_ad(timeout=5)
        self.assertFalse(ok)
        self.assertEqual(STUBS.ocr_find_all_calls, 1)  # 首轮见到首页锚点直接结束，不再白等 5 秒

    # ---------- 5. dismiss_popups ----------

    def test_dismiss_popups_single_pass_ocr_when_clean(self):
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(("发现", 540, 2300), ("推荐歌单", 400, 600))
        closed = qishui.dismiss_popups(max_rounds=3)
        self.assertEqual(closed, 0)
        self.assertEqual(STUBS.ocr_find_all_calls, 1)  # 14 个关键词只扫 1 次全屏 OCR

    def test_dismiss_popups_clicks_close_keyword_or_desc_fallback(self):
        rounds = iter([
            _ocr_dicts(("续费会员享专属", 540, 1000), ("以后再说", 540, 1500)),
            _ocr_dicts(("发现", 540, 2300)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(rounds, _ocr_dicts(("发现", 540, 2300)))
        with patch.object(qishui.time, "sleep"):
            closed = qishui.dismiss_popups(max_rounds=3)
        self.assertEqual(closed, 1)
        self.assertEqual(STUBS.clicks, [(540, 1500)])

        # 测试 OCR 未扫到关闭文字时回退无障碍 desc("关闭")
        STUBS.reset()
        rounds2 = iter([
            _ocr_dicts(("开通会员", 540, 1000)),
            _ocr_dicts(("发现", 540, 2300)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(rounds2, _ocr_dicts(("发现", 540, 2300)))
        STUBS.selector_handler = lambda by, val: (
            FakeNode(rect=FakeAScriptRect(880, 680, 960, 760))
            if (by == "desc" and val == "关闭") else None
        )
        with patch.object(qishui.time, "sleep"):
            closed2 = qishui.dismiss_popups(max_rounds=3)
        self.assertEqual(closed2, 1)
        self.assertEqual(STUBS.clicks, [(920, 720)])

    # ---------- 6. wait_ad_countdown ----------

    def test_wait_ad_countdown_multidigit_logging_and_dynamic_extension(self):
        clock = _FakeClock(step=5.0)
        # 即使初始 timeout=10s，识别到 29秒 -> 28秒 -> 15秒 -> 领取成功 时应动态顺延并完整解析两位数秒数
        timeline = [
            _ocr_dicts(("29秒后可领取奖励", 300, 120)),
            [FakeOcrText("28秒后可领取奖励", center_x=300, center_y=120)],  # 同步验证 OcrText 对象
            _ocr_dicts(("15秒后可领取奖励", 300, 120)),
            _ocr_dicts(("领取成功", 960, 120)),
        ]
        idx = {"i": 0}

        def _next_screen():
            pos = min(idx["i"], len(timeline) - 1)
            idx["i"] += 1
            return timeline[pos]

        STUBS.ocr_find_all_handler = _next_screen
        buf = io.StringIO()
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            with redirect_stdout(buf):
                status, pos = qishui.wait_ad_countdown(timeout=10)
        out = buf.getvalue()
        self.assertEqual(status, "ready")
        self.assertEqual(pos, (960, 120))
        self.assertIn("29秒后可领取奖励", out)
        self.assertIn("28秒后可领取奖励", out)
        self.assertIn("15秒后可领取奖励", out)

    def test_wait_ad_countdown_ignores_bottom_reward_text(self):
        clock = _FakeClock(step=1.0)
        frames = iter([
            _ocr_dicts(("领取成功即领红包", 540, 2100), ("10秒后可领取", 260, 100)),  # 底部广告伪装文案应忽略
            _ocr_dicts(("领取成功", 950, 110)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(frames)
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            status, pos = qishui.wait_ad_countdown(timeout=30)
        self.assertEqual(status, "ready")
        self.assertEqual(pos, (950, 110))

    def test_wait_ad_countdown_quota_exhausted_early_exit(self):
        clock = _FakeClock()
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(("今日已领完", 540, 1200))
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            status, pos = qishui.wait_ad_countdown(timeout=30)
        self.assertEqual((status, pos), ("quota_exhausted", None))

    def test_wait_ad_countdown_live_prompt_clicks_exit_never_continue(self):
        clock = _FakeClock()
        frames = iter([
            _ocr_dicts(("5秒后自动进入直播间", 540, 1000), ("继续互动", 540, 1300), ("退出", 540, 1500)),
            _ocr_dicts(("领取成功", 960, 110)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(frames)
        stats = {"live_prompts": 0}
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            status, _ = qishui.wait_ad_countdown(timeout=30, stats=stats)
        self.assertEqual(status, "ready")
        self.assertEqual(stats["live_prompts"], 1)
        self.assertEqual(STUBS.clicks, [(540, 1500)])  # 点"退出"，绝不点"继续互动"

    def test_wait_ad_countdown_short_drama_retention_never_clicks_give_up_exit(self):
        clock = _FakeClock()
        frames = iter([
            _ocr_dicts(
                ("再看05秒继续解锁 第24日免费听", 540, 1000),
                ("是否继续", 540, 1080),
                ("继续观看", 538, 1282),
                ("坚持退出", 540, 1480),
            ),
            _ocr_dicts(("领取成功", 960, 110)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(frames)
        stats = {"live_prompts": 0}
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            status, _ = qishui.wait_ad_countdown(timeout=30, stats=stats)
        self.assertEqual(status, "ready")
        self.assertEqual(stats["live_prompts"], 0)
        self.assertEqual(STUBS.clicks, [(538, 1282)])  # 准确点"继续观看"，绝不误点"坚持退出"

    def test_wait_ad_countdown_exits_live_room_and_force_reopens_after_3_stuck(self):
        clock = _FakeClock()
        frames = iter([
            _ocr_dicts(("在线观众 1200", 200, 150), ("更多直播", 900, 2200)),  # 第 1 次：无关闭按钮走返回键
            _ocr_dicts(("在线观众 1200", 200, 150), ("X", 990, 110)),          # 第 2 次：点右上角 X
            _ocr_dicts(("在线观众 1200", 200, 150)),                           # 第 3 次：连续卡死直接拉回 App
            _ocr_dicts(("领取成功", 960, 110)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(frames)
        stats = {"live_rooms": 0}
        with patch.object(qishui.time, "time", clock.time), patch.object(qishui.time, "sleep", clock.sleep):
            status, _ = qishui.wait_ad_countdown(timeout=40, stats=stats)
        self.assertEqual(status, "ready")
        self.assertEqual(stats["live_rooms"], 3)
        self.assertEqual(STUBS.backs, 1)
        self.assertEqual(STUBS.clicks, [(990, 110)])
        self.assertEqual(STUBS.opened_packages, [qishui.APP_PACKAGE])

    def test_wait_ad_countdown_hijack_recovery_and_safe_system_dialog(self):
        clock = _FakeClock()
        call_idx = {"n": 0}

        def _fg():
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                return "com.android.permissioncontroller"  # 系统授权弹窗放行
            return "com.bbk.appstore"                      # 第 2 次检出应用商店劫持

        with patch.object(qishui.system, "get_foreground_app", _fg), patch.object(qishui.time, "sleep", clock.sleep):
            self.assertFalse(qishui.ensure_in_app())
            self.assertEqual(STUBS.opened_packages, [])
            self.assertTrue(qishui.ensure_in_app())
            self.assertEqual(STUBS.opened_packages, [qishui.APP_PACKAGE])

        # 在 wait_ad_countdown 循环中检出劫持并记录统计
        STUBS.reset()
        clock = _FakeClock()
        fg_calls = {"n": 0}

        def _loop_fg():
            fg_calls["n"] += 1
            return "com.bbk.appstore" if fg_calls["n"] == 1 else qishui.APP_PACKAGE

        screen_seq = iter([
            _ocr_dicts(("正在加载广告", 540, 1200)),
            _ocr_dicts(("正在加载广告", 540, 1200)),
            _ocr_dicts(("正在加载广告", 540, 1200)),
            _ocr_dicts(("领取成功", 960, 110)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(screen_seq, _ocr_dicts(("领取成功", 960, 110)))
        stats = {"hijacks": 0}
        with patch.object(qishui.system, "get_foreground_app", _loop_fg), \
             patch.object(qishui.time, "time", clock.time), \
             patch.object(qishui.time, "sleep", clock.sleep):
            status, _ = qishui.wait_ad_countdown(timeout=30, stats=stats)
        self.assertEqual(status, "ready")
        self.assertEqual(stats["hijacks"], 1)
        self.assertEqual(STUBS.opened_packages, [qishui.APP_PACKAGE])

    # ---------- 7. claim_reward ----------

    def test_claim_reward_reuses_reward_pos_and_clicks_step2(self):
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(("再看1个视频得 今日免费听", 540, 900), ("领取奖励", 540, 1300))
        with patch.object(qishui.time, "sleep"):
            res = qishui.claim_reward(reward_pos=(960, 120))
        self.assertEqual(res, "claimed")
        self.assertEqual(STUBS.clicks, [(960, 120), (540, 1300)])
        self.assertEqual(STUBS.ocr_find_calls, [])  # 复用阶段四坐标，省去步骤 1 重复找字

    def test_claim_reward_retries_step1_if_still_on_screen(self):
        seq = iter([
            _ocr_dicts(("领取成功", 960, 120)),
            _ocr_dicts(("领取奖励", 540, 1300)),
        ])
        STUBS.ocr_find_all_handler = lambda: next(seq)
        with patch.object(qishui.time, "sleep"):
            res = qishui.claim_reward(reward_pos=(960, 120))
        self.assertEqual(res, "claimed")
        self.assertEqual(STUBS.clicks, [(960, 120), (960, 120), (540, 1300)])

    def test_claim_reward_detects_quota_exhausted_and_home_autocredit(self):
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(("今日已领完", 540, 1100), ("关闭", 540, 1500))
        with patch.object(qishui.time, "sleep"):
            res = qishui.claim_reward(reward_pos=(960, 120))
        self.assertEqual(res, "quota_exhausted")
        self.assertEqual(STUBS.clicks, [(960, 120), (540, 1500)])

        STUBS.reset()
        STUBS.ocr_find_all_handler = lambda: _ocr_dicts(("模式探索", 200, 150), ("发现", 540, 2300))
        with patch.object(qishui.time, "sleep"):
            res2 = qishui.claim_reward(reward_pos=(960, 120))
        self.assertEqual(res2, "claimed")

    # ---------- 8. run_ad_loop ----------

    def test_run_ad_loop_exits_immediately_on_quota_exhausted(self):
        qishui.MAX_IDLE_ROUNDS = 5
        wait_calls = {"n": 0}

        def _fake_wait(timeout=65, stats=None):
            wait_calls["n"] += 1
            return ("quota_exhausted", None)

        with patch.object(qishui, "wait_ad_countdown", _fake_wait), patch.object(qishui.time, "sleep"):
            total = qishui.run_ad_loop()
        self.assertEqual(total, 0)
        self.assertEqual(wait_calls["n"], 1)  # 命中额度用尽直接退出，不空耗 5 轮

    def test_run_ad_loop_restarts_at_idle_3_and_6_and_clicks_mian_only_on_home(self):
        qishui.MAX_IDLE_ROUNDS = 7
        qishui.MAX_LOOP_COUNT = 8
        outcomes = iter([
            ("timeout", None),  # idle=1
            ("timeout", None),  # idle=2
            ("timeout", None),  # idle=3 -> 重启 + 回首页 + 点免字
            ("timeout", None),  # idle=4 -> 确保在首页后也点免字（修复原版 >3 永不点免字漏洞）
            ("timeout", None),  # idle=5 -> 若不在首页则禁止盲点免字
            ("timeout", None),  # idle=6 -> 再次重启 + 回首页 + 点免字
            ("ready", (960, 120)),
        ])
        home_states = iter([True, True, True, True, False, True])

        with patch.object(qishui, "wait_ad_countdown", lambda timeout=65, stats=None: next(outcomes)), \
             patch.object(qishui, "skip_splash_ad", lambda timeout=4: False), \
             patch.object(qishui, "dismiss_popups", lambda max_rounds=1: 0), \
             patch.object(qishui, "ensure_home_page", lambda max_rounds=3: next(home_states)), \
             patch.object(qishui, "is_on_home_page", lambda texts=None: False), \
             patch.object(qishui, "claim_reward", lambda reward_pos=None: "claimed"), \
             patch.object(qishui.time, "sleep"):
            stats = {"claimed": 0, "live_prompts": 0, "live_rooms": 0, "hijacks": 0, "restarts": 0}
            # 限制轮数后通过第 7 轮成功 + 第 8 轮退出结束
            qishui.MAX_LOOP_COUNT = 7
            total = qishui.run_ad_loop(stats=stats)

        self.assertEqual(total, 1)
        self.assertEqual(stats["restarts"], 2)  # 第 3 轮与第 6 轮各重启一次
        mian_x = int(1080 * qishui.MIAN_X_RATIO)
        mian_y = int(2400 * qishui.MIAN_Y_RATIO)
        # 5 次处于首页时点了免字，第 5 次（不在首页）拦截未盲点
        self.assertEqual(STUBS.clicks, [(mian_x, mian_y)] * 5)

    # ---------- 9. AScript 入口契约校验 ----------

    def test_ascript_top_level_entry_contract(self):
        with open(MODULE_PATH, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('__name__ == "__main__"', src)
        self.assertNotIn("__name__ == '__main__'", src)
        self.assertIn('os.environ.get("QISHUI_TEST_MODE") != "1"', src)


if __name__ == "__main__":
    unittest.main()
