# 更新日志 (Changelog)

## v2.0.0 (2026-11-25)

### 新增 (Added)
- **独立用户配置文件 `config.py`**：解耦所有可调参数（超时、预设坐标、防抖半径、目标次数等），升级脚本不再覆盖个人配置。
- **多机型入口预设与自动回退 (`enter_ad_from_home`)**：内置 `default_top_right` `(0.937, 0.063)` 与 `huawei_play_side` `(0.790, 0.814)`（感谢 Issue #1 `@mengsen182` 实测反馈）；主入口点击后若仍停留在首页，自动尝试备选坐标并提示校准。
- **领奖进度弹窗与 App 内广告落地页处理**：新增 `_find_progress_unlock_button()` 与 `handle_ad_landing_page()`，支持华为等版本「立即解锁 第N天畅听 / 解锁第N天畅听」按钮变体，同时在无倒计时且无继续观看的安全前提下自动关闭 `立即购买 / SVIP / 汽水音乐会员` 落地页。
- **倒计时卡死提前退出 (`COUNTDOWN_STALL_TIMEOUT`)**：同一倒计时秒数停滞超过 15 秒时提前结束本轮等待并进入恢复流程。
- **防机械点击微抖动 (`CLICK_JITTER_PX`) & 目标领取次数 (`TARGET_CLAIM_COUNT`) & Toast 汇总 (`SHOW_SUMMARY_TOAST`)**。
- **自动打包发布工作流 (`.github/workflows/release.yml`)** 与 Issue/PR 模板：打 tag 时自动打包仅含运行必需文件的手机端 `.zip`。

### 修复与优化 (Fixed & Improved)
- **精准首页锚点校验 (`is_on_home_page`)**：顶部锚点限定 `y < 25%`，底部导航限定 `y > 84%` 且精确匹配短标签，彻底避免广告文案含「发现好物 / 汽水音乐」引发误判。
- **消除 `ocr_find()` 双重 OCR 扫描**：带 `rect` 未命中返回 `None` 时不再二次全屏扫 OCR（仅在抛异常或后端忽略 `rect` 返回区外坐标时回退）。
- **更安全的 `dismiss_popups()` 兜底**：以 `action.Key.back()` 替代原顶部 `y=8%` 盲点，避免在挖孔屏上误点搜索栏。
- **分层重启恢复 (`restart_app`)**：重启前先发 `Home` 键打断卡死 Activity，并支持 Root/Shizuku 可选 `am force-stop` 冷重启。
- **单元测试扩充至 36/36**：新增 12 组针对上述场景与 Issue #1 的回归测试。

---

## v1.x (2026-11-20 ~ 2026-11-23)
- 完成从 iOS 版（原作者 `@wei6718189`）到 Android `ascript.android.*` 的完整适配。
- 实现单次全屏 OCR（提速 14×）、短剧挽留 vs 直播诱导区分、前台防劫持拉回与跨平台 CI。
