# -*- coding: utf-8 -*-
"""
汽水音乐安卓自动化脚本 — 用户配置文件
===================================
将可调参数独立存放，方便拉取代码更新时不与核心逻辑冲突。
修改后重新上传/同步工程即可生效。
"""

# ============== 目标应用 ==============
APP_NAME = "汽水音乐"
APP_PACKAGE = "com.luna.music"          # 安卓版汽水音乐包名（iOS 为 com.soda.music）

# ============== 循环与超时控制 ==============
MAX_LOOP_COUNT = 100                    # 最大循环次数（防死循环）
TARGET_CLAIM_COUNT = 0                  # 目标领取次数（0 = 不限次数，领满或空跑达上限自动退出）
LOOP_INTERVAL = 3                       # 每轮结束后的间隔秒数
MAX_IDLE_ROUNDS = 10                    # 连续多少轮未成功就退出（兜底防空耗）
FIRST_ROUND_TIMEOUT = 70                # 首轮等待广告结束超时（秒，给手动模式或加载留足时间）
AD_COUNTDOWN_TIMEOUT = 65               # 单轮广告默认等待超时（秒，覆盖 30s~60s 长视频广告）
MAX_AD_TIMEOUT = 95                     # 动态倒计时顺延上限（秒）
COUNTDOWN_STALL_TIMEOUT = 15            # 倒计时数字连续停滞多少秒判定卡死并提前结束本轮（0=关闭）

# ============== 引擎与无人值守 ==============
# 无障碍控件检索模式：2 = FILTERED_SIMPLE（无障碍默认），9 = Root 模式，6 = HID 模式
SELECTOR_MODE = 2
KEEP_SCREEN_ON = True                   # 保持屏幕常亮，防息屏中断
AUTO_RESTART_APP = True                 # 连续失败达到 3 的倍数轮次时自动重启 App 恢复
ENABLE_COLD_RESTART_FALLBACK = False    # 重启恢复时是否尝试通过 shell 执行 am force-stop（仅 Root/Shizuku 设备建议开启）
SHOW_SUMMARY_TOAST = True               # 脚本结束时尝试通过系统 Toast 展示统计摘要

# OCR 引擎：paddle（百度 PP-OCR V5，更准） / mlkit（谷歌，更快）
OCR_ENGINE = "paddle"

# 防机械点击像素随机抖动半径（像素；设为 0 则禁用抖动，始终严格留在屏幕及目标区域内）
CLICK_JITTER_PX = 4

# ============== 「免」字入口坐标预设 ==============
# 不同版本/机型「免」字入口位置可能不同：
#   - default_top_right : 主流版本位于首页右上角 (0.937, 0.063)（如 vivo 1080x2400）
#   - huawei_play_side  : 部分华为/鸿蒙版本位于播放页右侧点赞行附近 (0.790, 0.814)（由 Issue #1 @mengsen182 实测提供）
MIAN_PRESETS = {
    "default_top_right": (0.937, 0.063),
    "huawei_play_side": (0.790, 0.814),
}

# 默认选用的预设名称
MIAN_PRESET = "default_top_right"

# 手动微调相对比例（保持为 None 时自动读取上面 MIAN_PRESET 对应的值；填 0~1 小数则优先覆盖预设）
MIAN_X_RATIO = None
MIAN_Y_RATIO = None

# 若主坐标点击后仍停在首页，依次自动尝试的备选坐标比例列表
MIAN_FALLBACK_RATIOS = (
    (0.790, 0.814),
)
AUTO_TRY_MIAN_FALLBACK = True           # 开启多位置自动回退探测

# 是否自动点击「免」字进入广告：
#   True  = 全自动模式（推荐）
#   False = 半自动模式（首轮手动点一次，后续由脚本自动接管）
AUTO_CLICK_MIAN = True
