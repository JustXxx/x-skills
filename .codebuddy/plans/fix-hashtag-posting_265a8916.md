---
name: fix-hashtag-posting
overview: 修复 xpost 发布推文时包含 `#` (hashtag) 的文本无法成功发送的问题。根因是 `page.py` 的 `type_text` 使用 `execCommand('insertText')` 注入文本，触发 X 编辑器的 hashtag 自动补全弹窗，导致文本被截断或发送失败。
todos:
  - id: fix-type-text
    content: "在 page.py 中新增 paste_text() 方法（pbcopy + send_paste），并修改 type_text() 对含 #/@ 的文本自动切换为剪贴板粘贴"
    status: completed
  - id: verify-fix
    content: "使用 [skill:x-poster] 以 preview 模式验证 post 命令能正确输入包含 # 和 @ 的推文文本"
    status: completed
    dependencies:
      - fix-type-text
---

## 用户需求

修复发布推文时包含 `#` (hashtag) 的文本无法成功发送的问题。

## 产品概述

xpost 是一个通过真实 Chrome 浏览器 + CDP 操控 X (Twitter) 的命令行工具。当前所有发布命令（post、video、quote、reply）通过 `page.type_text()` 方法向 X 编辑器输入文本，该方法使用 `document.execCommand('insertText')` 逐字插入内容。当文本包含 `#` 时，X 编辑器的 React 事件系统会触发 hashtag 自动补全面板，劫持后续输入，导致文本截断或发布失败。同理 `@` 符号也会触发 @提及自动补全。

## 核心功能

- 修复包含 `#` 的推文文本输入失败问题
- 同时兼顾 `@` 符号可能触发的同类自动补全问题
- 所有发布命令（post、video、quote、reply）统一受益于修复
- 保持向后兼容，不影响不含特殊字符的正常文本输入

## 技术栈

- 语言：Python 3.9+
- 关键依赖：项目已有的 `clipboard.py`（macOS 剪贴板操作）、`paste.py`（osascript 按键模拟）
- 平台：macOS（使用 `pbcopy` 和 osascript）

## 实现方案

### 核心策略

在 `page.py` 的 `PageHelper` 类中新增 `paste_text()` 方法，通过 macOS 系统剪贴板 + 真实 Cmd+V 粘贴文本。然后修改 `type_text()` 方法，当检测到文本包含 `#` 或 `@` 等会触发自动补全的字符时，自动切换为 `paste_text()` 方式。

**为什么这样做**：

1. `execCommand('insertText')` 是逐字符插入，X 的 React 编辑器会在每个字符输入时检查是否需要弹出自动补全。`#` 和 `@` 是触发条件。
2. 剪贴板粘贴是原子操作——整段文本一次性写入编辑器，不会触发逐字符的自动补全逻辑。
3. 项目已经有成熟的剪贴板粘贴基础设施：图片上传就是通过 `clipboard.copy_image()` + `paste.send_paste()` 实现的，完全相同的思路。

**为什么不用 `clipboard.py` 的 `copy_html()`**：

`copy_html()` 会将文本设为 HTML + RTF + plain text 三种格式，涉及 Swift 编译、HTML 解析、NSAttributedString 转换等重量级操作。对于纯文本推文来说，直接用 macOS 自带的 `pbcopy` 命令写入纯文本剪贴板，更简单、更快、零依赖。

### 关键决策

**统一切换 vs 条件切换**：选择**条件切换**。

- 当文本包含 `#` 或 `@` 时，使用 `paste_text()` 剪贴板粘贴
- 其他情况保持 `execCommand('insertText')`，因为它更快、无需激活 Chrome 窗口、无需辅助功能权限

这样做的好处是：最小化行为变更，不影响已经正常工作的场景，只在必要时走剪贴板路径。

### 性能与可靠性

- `pbcopy` 是同步管道操作，延迟 <10ms
- `send_paste()` 需要 ~0.5s（含 osascript 启动 + pre_delay），相比 `execCommand` 的近零延迟有增加，但对交互式工具而言完全可接受
- 粘贴后需要短暂等待（~0.5s）让 X 编辑器完成渲染，与当前 `type_text()` 后的 `await asyncio.sleep(0.5)` 一致

## 实现细节

### 新增 `paste_text()` 方法（page.py）

1. 先 focus 目标元素（通过 `evaluate` 执行 `el.focus()`）
2. 用 `subprocess.run` 调用 `pbcopy` 将文本写入系统剪贴板（通过 stdin 管道传入，避免 shell 转义问题）
3. `await asyncio.sleep(0.2)` 确保剪贴板就绪
4. 调用已有的 `paste.send_paste()` 发送真实 Cmd+V

### 修改 `type_text()` 方法（page.py）

在方法开头增加判断：如果 `text` 包含 `#` 或 `@`，调用 `self.paste_text()` 后直接 return。否则走原有的 `execCommand('insertText')` 路径。

### 命令层：零修改

所有命令文件（post.py、video.py、quote.py、reply.py）调用的都是 `page.type_text()`，修改在 `type_text()` 内部完成，对调用方完全透明。article.py 中的 `type_text()` 调用是用于文章标题（一般不含 `#`），但即使包含也会自动走新路径，不影响。

## 架构设计

修改范围严格限制在 `page.py` 一个文件内：

```
page.py (PageHelper)
  ├── type_text()      [MODIFY] 增加 #/@ 检测，条件分流到 paste_text()
  └── paste_text()     [NEW]    pbcopy + send_paste() 的纯文本粘贴方法
```

调用链保持不变：

```
commands/*.py → page.type_text() → (自动分流) → execCommand 或 paste_text
                                                       ↓
                                              pbcopy + paste.send_paste()
```

## 目录结构

```
src/x_poster/
└── page.py  # [MODIFY] 新增 paste_text() 方法；修改 type_text() 增加 #/@ 检测和条件分流。需新增 import subprocess 和 from .paste import send_paste。paste_text() 负责：(1) focus 目标元素，(2) pbcopy 写入剪贴板，(3) send_paste() 发送 Cmd+V。type_text() 在方法入口检测 '#' 或 '@' in text，命中则委托 paste_text()。
```

## 关键代码结构

```python
# page.py 中新增方法签名
async def paste_text(self, selector: str, text: str) -> None:
    """通过系统剪贴板 + 真实 Cmd+V 粘贴文本到元素中。

    用于包含 # 或 @ 等会触发 X 自动补全的文本。

    :param selector: 目标元素的 CSS 选择器
    :param text: 要粘贴的文本
    """
    ...
```

## Agent Extensions

### Skill

- **x-poster**
- Purpose: 了解 xpost CLI 工具的完整命令体系和工作流程，确保修复方案与工具的整体设计一致
- Expected outcome: 确认修复后所有发布命令（post、video、quote、reply）能正确处理包含 # 和 @ 的文本