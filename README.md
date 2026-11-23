# 汽水音乐 安卓自动化脚本

[![Unit Tests CI](https://github.com/wangyudawang1/qishuiAScriptProject/actions/workflows/test.yml/badge.svg)](https://github.com/wangyudawang1/qishuiAScriptProject/actions/workflows/test.yml)
[![Unit Tests](https://img.shields.io/badge/Tests-23%2F23%20ALL%20GREEN-brightgreen)](tests/test_qishui_android.py)
![Platform](https://img.shields.io/badge/platform-Android-green)
![Framework](https://img.shields.io/badge/framework-AScript-blue)
![Based on](https://img.shields.io/badge/based%20on-iOS%20version-orange)
![Python](https://img.shields.io/badge/python-3.x-yellow)

基于 AScript 安卓引擎的自动化脚本，自动观看汽水音乐广告以获取免费听歌时长。

> ### 📌 来源声明（原作者致谢）
>
> **本项目改造自 [@wei6718189](https://github.com/wei6718189) 的开源项目 [wei6718189/qishuiAScriptProject](https://github.com/wei6718189/qishuiAScriptProject)（iOS 版）**
>
> 原项目是 iOS 专用脚本，依赖 WebDriverAgent + `ascript.ios.*`。  
> 本项目在其基础上完成 **Android 平台完整适配**，改写为 `ascript.android.*` 引擎，并针对复杂广告生态完成了全链路稳定性加固；原 iOS 代码完整保留在 [`__init___ios_backup.py`](./__init___ios_backup.py)。
>
> 衷心感谢原作者 [@wei6718189](https://github.com/wei6718189) 的开源贡献！

---

## ⚡ 深度优化与稳定性增强说明

在适配 Android 平台基础上，对 `__init__.py` 进行了全量代码审计与工业级加固，彻底消除隐藏缺陷：

| 优化项 | 原实现隐患 | 现改进方案与收益 |
| :--- | :--- | :--- |
| **AScript `Selector` + `Rect` 修复** | 仅尝试 `.left/.top`（遗漏 AScript 原生 `Rect.x1/y1/x2/y2`），未绑定 `mode=2`，且控件查找未校 `rect` 边界 | 新增 `_parse_rect()` 兼容 `x1/y1/x2/y2` 与 `left/top/right/bottom`，绑定 `SELECTOR_MODE = 2`，强制 `_in_rect()` 校验并支持 `find_all()` |
| **弹窗清理单次扫描提速 14×** | `dismiss_popups()` 每轮对 14 个关键词逐个调用 `Ocr.find()`，耗时高达 5~11 秒 | 改为每轮单次 `scan_screen_texts()` + 内存关键词匹配，**提速约 14 倍**；无文字叉号支持控件 `desc("关闭")` 兜底 |
| **动态倒计时 & 65s+ 长广告支持** | 默认超时仅 30 秒且只解析个位数字，`45s~60s` 视频广告在中途直接误判超时 | 默认超时升级至 `AD_COUNTDOWN_TIMEOUT = 65`（首轮 `70s`），支持完整多位倒计时正则解析与动态顺延（上限 `95s`） |
| **直播诱导 vs 短剧挽留精准防误触** | `LIVE_PROMPT_HINTS` 含泛化的 `"是否继续"`，短剧弹窗出现 `"坚持退出"` 时会误判导致放弃奖励 | 精准拆分 `_is_short_drama_retention()` 与 `_is_live_prompt()`，并在退出词中强排除 `"坚持/放弃"`，绝不误点 `"坚持退出"` |
| **广告跳转前台防劫持** | 误触广告落地页跳转至应用商店或浏览器后脚本继续空等卡死 | 每 3 轮检测 `system.get_foreground_app()`，放行系统权限弹窗，一旦跳离立即拉回 `com.luna.music` |
| **顶部伪装屏蔽 & 当日额度早退** | 不限区域找 `"领取成功"` 易误点底部广告正文；额度用尽后仍白跑 10 轮 | 严格限定 `y < 25%` 顶部栏，复用坐标直达步骤 2；检出 `"今日已领完/明日再来"` 等立即体面退出 |
| **第 4+ 轮恢复断链修复** | 原 `idle_count <= 3` 限制导致连续失败第 4 轮起与重启 App 后再也不点「免」字 | 全周期 `idle_count` 每次均执行状态恢复、重启后必校验 `is_on_home_page()` 再精准点击「免」字 |
| **工程规范与自动化测试 CI** | 无测试覆盖与跨平台 Git 配置，手机同步会带入无关文件 | 新增 23 组零真机依赖单元测试（[`tests/test_qishui_android.py`](tests/test_qishui_android.py)）与 **GitHub Actions 四矩阵 CI**，完善 `.syncignore` 与 `.gitattributes` |

---

## 功能流程

```mermaid
flowchart TD
    A["启动汽水音乐 App (com.luna.music)"] --> B["跳过开屏广告 (右上角命中 / 见首页锚点即短路)"]
    B --> C["清理系统弹窗 (单次扫描 OCR + 控件 desc 兜底)"]
    C --> D{"确认停留在首页？"}
    D -- "否" --> E["防劫持拉回 / 返回键退出 / 必要时重启"]
    E --> D
    D -- "是" --> F["按比例坐标点击右上角「免」字进入广告"]
    F --> G["阶段四：wait_ad_countdown (65s~95s 动态窗口)"]
    G --> H{"顶部 y<25% 出现\n「领取成功」？"}
    H -- "前台跳应用商店" --> I["ensure_in_app() 立即拉回"] --> G
    H -- "直播互动弹窗" --> J["handle_live_prompt() 只点退出"] --> G
    H -- "误入直播间" --> K["handle_live_room() 关闭/返回/3次强拉回"] --> G
    H -- "短剧保留弹窗" --> L["check_and_click_continue_watching() 点继续观看"] --> G
    H -- "当日额度已领完" --> Z["体面退出并打印运行统计"]
    H -- "是" --> M["阶段五：复用坐标点「领取成功」→「领取奖励」"]
    M --> N["成功次数 +1，间隔后进入下一轮循环"] --> G
```

## 运行环境

- **平台**：Android（实测 vivo V2055A / Android 14 / 1080×2400）
- **AScript App**：4.0.17+，运行模式「无障碍模式」
- **必需权限**：辅助功能（无障碍）、录屏授权、悬浮窗
- **OCR 引擎**：`paddle`（百度 PP-OCR V5，默认）或 `mlkit`（谷歌，更快）

## 项目结构

```text
qishuiAScriptProject/
├── __init__.py                     # 安卓版主入口（AScript 工程约定，必须叫这个名字）
├── __init___ios_backup.py          # 原 iOS 版脚本完整备份
├── tests/
│   └── test_qishui_android.py      # 23 组核心状态机与异常恢复单元测试（纯标准库）
├── .github/workflows/
│   └── test.yml                    # GitHub Actions 跨平台自动验证（Ubuntu + Windows × Python 3.10/3.12）
├── res/img/                        # 图标与模板图
├── .vscode/
│   ├── settings.json               # 平台 / 设备地址 / Python 路径
│   └── .syncignore                 # 手机端同步排除规则（自动排除 tests/、.github/、文档等）
├── .trae/rules/ascript.md          # AScript AI 编码规则
└── .gitattributes                  # 统一 LF 换行符策略
```

## 快速开始

### 1. 手机端

1. 装 AScript App，开启**无障碍**权限
2. 进 App 的「开发者」页，开启**设备服务**（默认端口 `9096`）
3. 记下手机局域网 IP，如 `192.168.1.100`

### 2. 电脑端

1. 装 VS Code + AScript 插件
2. 确认 `uvx --version` 可用
3. 把手机 IP 填进 `.vscode/settings.json` 的 `ascript.deviceId`
4. 手机和电脑连同一个 WiFi

> `.vscode/settings.json` 里的 `192.168.1.100:9096` 是占位示例，请换成你自己手机的 IP 和端口。

### 3. 运行与本地跑测试

- **运行工程**：在 VS Code 里用 AScript 插件运行工程，或让 AI 调用 `run_project`。
- **本地运行全部单元测试（零真机依赖）**：
  ```bash
  python -m py_compile __init__.py tests/test_qishui_android.py
  python -m unittest discover -s tests -v
  ```

## 让它自己跑（无人值守）

脚本本身已经是全自动的（`AUTO_CLICK_MIAN = True`），启动后不用管。要彻底脱离电脑，按下面三步做。

### 第一步：手机端直接运行

1. 手机打开 **AScript App**
2. 进「**工程管理**」→ 找到 `qishuiAScriptProject`
3. 点 **运行**

工程已经上传到手机了，不需要电脑参与。运行后手机会自己点「免」字、看广告、领奖励，一直循环到当日额度用完（识别到领满提示或连续 10 轮没领到会自动退出）。

### 第二步：系统设置防中断

这几个设置不做，跑几分钟就会被系统掐掉：

| 设置项 | 路径（vivo 为例） | 作用 |
|--------|------------------|------|
| 电池优化白名单 | 设置 → 电池 → 后台耗电管理 → AScript → 允许后台高耗电 | 防止后台被杀 |
| 自启动 | 设置 → 应用管理 → AScript → 权限 → 自启动 | 允许后台存活 |
| 保持唤醒 | 开发者选项 → 不锁定屏幕（充电时） | 双保险 |

脚本内部已经调了 `Device.keep_screen_on()`，会保持屏幕常亮；每轮开始还会 `Device.wake_up()` 唤醒，所以息屏也能恢复。

### 第三步（可选）：打包成独立 APK

想更彻底、连 AScript App 都不用开：

1. AScript App → 首页找到「**打包独立程序**」
2. 选择 `qishuiAScriptProject` 工程
3. 生成 APK 并安装

打包后的 App 可以设桌面图标直接点、配合系统自启动实现开机跑。

### 定时每天跑

AScript 没有内置定时任务，用手机系统自带的能力：

- **vivo**：设置 → 快捷与辅助 → 自动任务 → 新建（定时启动指定应用）
- **第三方**：Tasker / MacroDroid 定时启动 AScript 并运行工程

## 关键配置

打开 `__init__.py` 头部：

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `APP_PACKAGE` | `"com.luna.music"` | 安卓版汽水音乐包名 |
| `AUTO_CLICK_MIAN` | `True` | 是否自动点「免」字（`False` = 半自动，由你手动点第一次） |
| `SELECTOR_MODE` | `2` | 无障碍控件检索模式（`2=FILTERED_SIMPLE`，root 设备改 `9`，HID 改 `6`） |
| `FIRST_ROUND_TIMEOUT` | `70` | 首轮等待广告结束超时（秒） |
| `AD_COUNTDOWN_TIMEOUT` | `65` | 单轮广告默认等待超时（秒，覆盖 30s~60s 长广告） |
| `MAX_AD_TIMEOUT` | `95` | 动态倒计时延长上限（秒） |
| `KEEP_SCREEN_ON` | `True` | 屏幕常亮，防息屏中断 |
| `AUTO_RESTART_APP` | `True` | 连续失败达到 3 的倍数轮次时自动重启 App 恢复 |
| `MIAN_X_RATIO` | `0.937` | 「免」字按钮相对屏幕 X 位置 |
| `MIAN_Y_RATIO` | `0.063` | 「免」字按钮相对屏幕 Y 位置 |
| `OCR_ENGINE` | `"paddle"` | OCR 引擎（仅支持 `"paddle"` / `"mlkit"`） |
| `LOOP_INTERVAL` | `3` | 每轮间隔秒数 |
| `MAX_LOOP_COUNT` | `100` | 最大循环次数（约 40 分钟） |
| `MAX_IDLE_ROUNDS` | `10` | 连续空跑退出阈值（若识别到今日领完文案则立即提前退出） |

## 与 iOS 版的主要差异

| 项目 | iOS 版 | 安卓版 |
|------|--------|--------|
| 模块前缀 | `ascript.ios.*` | `ascript.android.*` |
| 启动 App | `app_start(bundle_id=)` | `system.open(package)` |
| 包名 | `com.soda.music` | `com.luna.music` |
| 控件树 | WDA dump 不稳，走 OCR | 无障碍控件树，`Selector(mode=2)` 15ms 级 + `Rect(x1,y1,x2,y2)` |
| 「免」字定位 | OCR | **比例坐标**（该按钮是图片，无 text 属性，前置校验首页后再点） |
| 点击通道 | WDA（易被检测） | 无障碍通道（不被检测） |
| 屏幕尺寸 | `screen_size()` | `Device.display()` |

## 已知要点与坑点防御

1. **「免」字是图片按钮**：控件树里没有它，OCR 也识别不出。代码在 `main()` 与失败恢复分支均**先确认已停在首页**，再按比例坐标点击，绝不盲目点击。
2. **倒计时文案**：位于顶部区域（`y < 18%`），代码使用 `r"(\d+)\s*秒后"` 完整解析两位数秒数并动态顺延超时。
3. **底部假文案屏蔽**：「领取成功」严格限定在顶部栏（`y < 25%`），防止广告正文内的营销文案误触发阶段五。
4. **广告底部有「立即下载」大按钮**：「继续观看」严格限定在屏幕中段（`y: 25%~68%`），绝不误触底部下载跳转。
5. **不要写 `if __name__ == "__main__"`**：AScript 工程入口约定不同，主体代码直接写在顶层；测试时通过环境变量 `QISHUI_TEST_MODE=1` 安全隔离入口。

## 广告中途的两种挽留弹窗（重点）

广告播放到一半会弹窗，**两种弹窗的正确操作完全相反**，点错就拿不到奖励：

### ① 短剧/视频广告的挽留弹窗 → 点「继续观看」

```text
再看05秒继续解锁
   第24日免费听
┌─────────────────┐
│    继续观看      │  ← 绿色主按钮，点这个
└─────────────────┘
     坚持退出         ← 灰色小字，绝不能点（放弃奖励）
```

实测坐标：`继续观看` @ `(538, 1282)` @ 1080×2400。代码已通过 `_is_short_drama_retention()` 专门保护该弹窗不被当作直播拦截，同时在退出过滤列表屏蔽了 `"坚持"` / `"放弃"` 字样。

### ② 直播形式广告的互动弹窗 → 点「退出」

```text
继续互动还是退出？
5 秒后自动进入直播间
```

- 点「继续互动」→ 进直播间，**直播间不算广告时长**，白看
- 点「退出」→ 留在广告页，正常拿奖励

代码里的 `_is_live_prompt()` 与 `handle_live_prompt()` 会拦截该弹窗，只点 `退出互动 / 退出直播间 / 不感兴趣 / 退出 / 取消 / 关闭`，**绝不点含「继续 / 进入 / 坚持 / 放弃」的按钮**。

### ③ 已经误入直播间 → 立即退出

`handle_live_room()` 会检测 `更多直播 / 说点什么 / 在线观众 / 直播间人数` 等特征，按顺序尝试：无障碍 `desc("关闭"/"退出")` → 顶部文字/`×`/`✕`/`✖` → 右上角 `X` → 返回键兜底；若连续 3 次退出失败卡死，直接 `system.open("com.luna.music")` 强制拉回。

### 性能设计

直播互动弹窗只有 **5 秒**反应窗口，因此阶段四与弹窗清理每轮**只做一次全屏 OCR**（`scan_screen_texts()`），在内存里按优先级匹配所有条件，彻底消除重复截屏识别延迟。

> ⚠️ `Ocr.find()` 与 `Ocr.find_all()` 在不同引擎下可能返回 **`dict`** 或 **`OcrText` 对象**，项目已通过 `_extract_ocr_item()` 统一适配。

## 免责说明

脚本仅用于自动化观看广告领取官方免费权益，请遵守汽水音乐用户协议。每日有领取上限，检测到额度用完提示或连续 10 轮空跑会自动退出。

## 致谢

- 原项目：[wei6718189/qishuiAScriptProject](https://github.com/wei6718189/qishuiAScriptProject)（原作者 [@wei6718189](https://github.com/wei6718189)）
- 自动化框架：[AScript](https://www.ascript.cn)（Python 移动端自动化引擎）
