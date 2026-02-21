# xpost

通过真实 Chrome 浏览器 + CDP（Chrome DevTools Protocol）操作 X (Twitter) 的命令行工具。

通过操控真实浏览器绕过 X 的反自动化检测，支持 7 种功能：

**发布功能：**
- **普通帖子** — 文本 + 最多 4 张图片
- **视频帖子** — 文本 + 视频（MP4/MOV/WebM）
- **引用推文** — 对已有推文添加评论转发
- **X 长文** — 从 Markdown 文件发布长篇文章（需 X Premium）

**读取功能：**
- **读取推文** — 读取单条推文的完整内容和数据
- **读取时间线** — 批量读取用户主页的推文
- **搜索推文** — 按关键词搜索推文

## 环境要求

- macOS
- Python >= 3.9
- Google Chrome（或 Chromium / Edge / Brave）
- macOS 辅助功能权限（用于模拟键盘粘贴）

## 安装

```bash
pip install -e .
```

## 首次使用

### 1. 环境检查

```bash
xpost check
```

确认所有检查项为 ✅。如果辅助功能权限未通过，前往：

**系统设置 → 隐私与安全性 → 辅助功能** → 添加你的终端应用（Terminal / iTerm 等）

### 2. 登录 X 账号

首次运行任何发帖命令时，会启动 Chrome 并打开 X 页面。此时需要**手动登录**你的 X 账号。

登录状态会保存在 `~/.local/share/x-poster-profile` 目录，后续运行无需重复登录。

```bash
# 先用预览模式启动 Chrome，手动登录
xpost post "test"
# 登录后关闭 Chrome 即可
```

## 使用方法

> **安全机制**：所有命令默认为**预览模式**（只填入内容，不提交）。加 `--submit` / `-s` 才会真正发布。

### 普通帖子

```bash
# 纯文本（注意：zsh 中 ! 是特殊字符，建议用单引号）
xpost post 'Hello world!'

# 带图片（最多 4 张）
xpost post '看看这张照片' -i photo1.jpg -i photo2.png

# 真正发布
xpost post '正式发布' -i image.jpg --submit
```

### 视频帖子

```bash
# 预览
xpost video '精彩视频' -V clip.mp4

# 发布
xpost video '精彩视频' -V clip.mp4 --submit
```

支持格式：MP4、MOV、WebM

### 引用推文

```bash
# 预览
xpost quote 'https://x.com/user/status/123456' '好文推荐！'

# 发布
xpost quote 'https://x.com/user/status/123456' '好文推荐！' --submit
```

### X 长文（Article）

从 Markdown 文件发布，支持 YAML frontmatter：

```markdown
---
title: 我的文章标题
cover_image: ./cover.jpg
---

# 正文标题

这里是文章内容...
```

```bash
# 预览
xpost article my-post.md

# 指定标题和封面
xpost article my-post.md --title '自定义标题' --cover hero.jpg

# 发布
xpost article my-post.md --submit
```

## 全局选项

```bash
# 指定 Chrome 路径
xpost --chrome-path /path/to/chrome post 'text'

# 指定 Profile 目录（多账号切换）
xpost --profile ~/.local/share/x-poster-account2 post 'text'

# 开启调试日志
xpost -v post 'text'
```

## 读取功能

### 读取单条推文

```bash
# 文本输出
xpost read 'https://x.com/user/status/123456'

# JSON 输出（适合程序处理）
xpost read 'https://x.com/user/status/123456' --json
```

输出内容包括：推文文本、作者、时间、图片/视频链接、互动数据（点赞/转发/回复/浏览量）、引用推文等。

### 读取用户时间线

```bash
# 读取最近 10 条（默认）
xpost timeline '@elonmusk'

# 读取最近 20 条
xpost timeline 'elonmusk' -n 20

# JSON 输出
xpost timeline 'https://x.com/elonmusk' -n 5 --json
```

支持直接传 `@handle`、`handle` 或完整 URL。

### 搜索推文

```bash
# 按相关度搜索（默认 Top）
xpost search 'Python programming' -n 5

# 按最新排序
xpost search '#AI' -n 20 --latest

# 搜索特定用户的推文
xpost search 'from:elonmusk' -n 10 --json
```

## 多账号

通过不同的 `--profile` 目录实现多账号切换：

```bash
# 账号 A
xpost --profile ~/.x-poster/account-a post 'from A'

# 账号 B
xpost --profile ~/.x-poster/account-b post 'from B'
```

每个 profile 目录独立保存 Chrome 登录状态。

## 常见问题

### Chrome 启动失败

```bash
# 清理残留进程
pkill -f 'Chrome.*remote-debugging-port'
# 清理端口文件
rm -f ~/.local/share/x-poster-profile/DevToolsActivePort
```

### 图片/视频粘贴无反应

确认终端已获得辅助功能权限：**系统设置 → 隐私与安全性 → 辅助功能**

### 长文功能不可用

X 长文（Articles）需要 X Premium 订阅。

## 项目结构

```
src/x_poster/
├── cli.py                 # CLI 主入口（click）
├── cdp_client.py          # CDP WebSocket 异步客户端
├── chrome.py              # Chrome 生命周期管理
├── page.py                # 页面 DOM 操作辅助
├── clipboard.py           # macOS 剪贴板操作（Swift/AppKit）
├── paste.py               # macOS 按键模拟（osascript）
├── markdown_converter.py  # Markdown → HTML 转换
└── commands/
    ├── post.py            # 普通帖子
    ├── video.py           # 视频帖子
    ├── quote.py           # 引用推文
    ├── article.py         # X 长文
    ├── read.py            # 读取单条推文
    ├── timeline.py        # 读取用户时间线
    ├── search.py          # 搜索推文
    └── check.py           # 环境检查
```
