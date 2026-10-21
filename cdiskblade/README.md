# C 盘之刃 · 独立官网（静态站）

纯 HTML / CSS / JS，无后端、无构建、无第三方库。双击 `index.html` 就能看，丢到 GitHub Pages 就能上线。

## 一、信息架构：五个模块 = 五个独立界面

不是「一页滑到底」，而是**点哪个模块就进哪个界面**，一次只显示一个模块：

| 界面 | 路由 | 内容（与原模块一致，未删减） |
|---|---|---|
| 下载（默认首界面） | `#download` | 软件名 + 一句话定位 + 版本/大小/日期/SHA256 + 主下载按钮（自建直链）与次按钮（官方下载页）+ 首次运行三步 |
| 简介与故事 | `#story` | 软件简介 + 四段故事（出发点 / 开发过程 / 耗时 / 结果）+ 署名 |
| 核心功能 | `#features` | 6 张卡片，图标为内联 SVG |
| 更新日志 | `#changelog` | 只列当前版本 v2.9（无外部跳转入口） |
| 系统要求 | `#requirements` | 8 行表格，移动端自动转卡片堆叠 |

**导航闭环**：左侧导航（≤900px 转顶部横条）常驻，任意界面都能直达其他四个；每个界面底部还有一组「上一个模块 / 下一个模块」翻页按钮，首尾循环 —— 不存在孤立页面。

**转场（一镜到底）**：
- 旧界面脱离文档流原地淡出上移（300ms），新界面自下方淡入（640ms），两者**交叠**进行，中间不露白、不闪烁；
- 容器高度用 `min-height` 平滑过渡，切换瞬间页面不塌陷；
- 左侧激活胶囊在导航项之间**滑动跟随**，把五个界面在视觉上串成一条线；
- 地址栏带 `#模块名`，支持直接分享、刷新、浏览器前进/后退；
- `prefers-reduced-motion: reduce` 下自动关闭全部动效；禁用 JS 时五个界面平铺显示，内容照样完整。

## 二、目录结构

```
cdiskblade-site/
├── index.html                  # 页面结构（骨架 + 语义标签，内容由 JS 注入）
├── assets/
│   ├── css/
│   │   ├── tokens.css          # 设计变量：配色 / 字阶 / 间距 / 圆角 / 阴影 / 动效
│   │   ├── base.css            # 重置、排版、页面骨架、无障碍、降级动效
│   │   └── components.css      # 区块、按钮、卡片、时间线、表格、下载区
│   ├── js/
│   │   ├── site-data.js        # ★ 全站唯一内容源（要改的东西都在这里）
│   │   └── main.js             # 内容注入 + 滚动入场 + 导航高亮 + 复制 SHA
├── integration/
│   └── jufang-card-entry.snippet.html   # 具坊「C 盘之刃」卡片加官网入口的示例代码
└── README.md                   # 本文件
```

## 三、怎么改内容

| 内容类型 | 改哪里 | 说明 |
|---|---|---|
| **重复出现的元信息**（版本号、大小、日期、下载链接、署名、SHA256） | `assets/js/site-data.js` | 改一次，下载区 / 更新日志 / 页脚 / 浏览器标签全生效 |
| **一次性文案**（简介、故事、功能、更新日志、系统要求） | `assets/js/site-data.js` 里对应的数组 | 同样是这一个文件；`index.html` 只留结构 |
| **样式与配色** | `assets/css/tokens.css` | 与「具坊」主站一致的变量命名，改这里即可换肤 |

> `index.html` 里看到的 `{{VERSION}}`、`{{DOWNLOAD_URL}}` 这类花括号是**占位符兜底文本**：JS 没跑或被禁用时显示它，方便一眼定位没填的字段；JS 正常运行后会被 `site-data.js` 的真实值覆盖。

## 四、占位符汇总表

> 第一列是占位符名；「来源字段」指它在 `site-data.js` 里对应的键；「当前值」是已填好的推荐值。

### 4.1 基本信息与链接

| 占位符 | 来源字段 | 当前值 |
|---|---|---|
| `{{APP_NAME}}` | `appName` | C 盘之刃 |
| `{{APP_NAME_EN}}` | `appNameEn` | CDiskBlade |
| `{{VERSION}}` | `version` | v2.9 |
| `{{UPDATE_DATE}}` | `releaseDate` | 2026-10-21 |
| `{{FILE_SIZE}}` | `fileSize` | 37.8 MB（37,836,382 字节） |
| `{{SHA256}}` | `sha256` | 1ae0b0a1…7b8d（完整值见文件） |
| `{{TAGLINE}}` | `tagline` | 一把给 Windows 用的 C 盘清理小刀… |
| `{{INTRO_TEXT}}` | `intro` | C 盘之刃是一个面向个人用户的… |
| `{{DOWNLOAD_URL}}` | `downloadUrl` | `https://raw.githubusercontent.com/goutuo4588/tools/main/files/cdiskblade-v2.9-win64.exe` |
| `{{OFFICIAL_PAGE_URL}}` | `officialUrl` | `https://github.com/goutuo4588/tools/releases/tag/cdiskblade-v2.9` |
| `{{HOME_URL}}` | `homeUrl` | `https://goutuo4588.github.io/tools/` |
| `{{REPO_URL}}` | `repoUrl` | `https://github.com/goutuo4588/tools` |
| `{{AUTHOR_NAME}}` | `author` | 狗托儿 |
| `{{AUTHOR_EMAIL}}` | `authorEmail` | goutuoshigesha@163.com |
| `{{AUTHOR_SIGN_DATE}}` | `authorSign` | 2026 年秋 · 于斋 |
| `{{SITE_URL}}` | `index.html` 的 `<link rel="canonical">` | `https://goutuo4588.github.io/tools/cdiskblade.html` |
| `{{SEO_TITLE}}` / `{{SEO_DESCRIPTION}}` | `index.html` 的 `<title>` / `<meta description>` | 由 JS 按 `appName` + `intro` 自动覆盖 |

### 4.2 开发故事（`story` 数组，4 段）

| 占位符 | 来源字段 |
|---|---|
| `{{STORY_1_TITLE}}` / `{{STORY_1_TEXT}}` | `story[0].title` / `story[0].text`（出发点） |
| `{{STORY_2_TITLE}}` / `{{STORY_2_TEXT}}` | `story[1]`（开发过程） |
| `{{STORY_3_TITLE}}` / `{{STORY_3_TEXT}}` | `story[2]`（耗时） |
| `{{STORY_4_TITLE}}` / `{{STORY_4_TEXT}}` | `story[3]`（最终结果） |

### 4.3 核心功能（`features` 数组，6 项，建议 3–6 项）

| 占位符 | 来源字段 | icon 可选值 |
|---|---|---|
| `{{FEATURE_1_TITLE}}` / `{{FEATURE_1_DESC}}` | `features[0]` | `broom` |
| `{{FEATURE_2_TITLE}}` / `{{FEATURE_2_DESC}}` | `features[1]` | `move` |
| `{{FEATURE_3_TITLE}}` / `{{FEATURE_3_DESC}}` | `features[2]` | `reset` |
| `{{FEATURE_4_TITLE}}` / `{{FEATURE_4_DESC}}` | `features[3]` | `shield` |
| `{{FEATURE_5_TITLE}}` / `{{FEATURE_5_DESC}}` | `features[4]` | `heal` |
| `{{FEATURE_6_TITLE}}` / `{{FEATURE_6_DESC}}` | `features[5]` | `bolt` |
| `{{FEATURES_LEAD}}` | `featuresLead` | — |

`icon` 可选：`broom` / `move` / `reset` / `shield` / `heal` / `bolt`（内联 SVG，定义在 `main.js` 的 `ICONS` 里，可自行加）。

### 4.4 更新日志（`logs` 数组，当前只保留 v2.9）

| 占位符 | 来源字段 |
|---|---|
| `{{LOG_1_VERSION}}` / `{{LOG_1_DATE}}` / `{{LOG_1_ITEM_1…4}}` | `logs[0]`（v2.9） |

要补历史版本：往 `logs` 数组**后面**追加 `{version, date, items:[]}`（页面上按数组顺序自上而下渲染，最新的放最前面）。

### 4.5 系统环境要求（`requirements` 数组）

| 占位符 | 来源字段 | 当前值 |
|---|---|---|
| `{{REQ_OS}}` | `requirements[0]` | Windows 10（1809 及以上）或 Windows 11，64 位 |
| `{{REQ_CPU}}` | `requirements[1]` | x64 架构… |
| `{{REQ_RAM}}` | `requirements[2]` | 4 GB 及以上 |
| `{{REQ_DISK}}` | `requirements[3]` | 安装包 37.8 MB… |
| `{{REQ_DEP}}` | `requirements[4]` | 无，单文件自带运行环境 |
| `{{REQ_PERM}}` | `requirements[5]` | 需要管理员权限 |
| `{{REQ_NET}}` | `requirements[6]` | 离线可用 |
| `{{REQ_NOTSUPPORT}}` | `requirements[7]` | Win7 / 8 / 32 位不支持（带 `warn:true`，左侧标红条） |
| `{{REQUIREMENTS_LEAD}}` | `requirementsLead` | — |

## 五、设计与技术说明

- **风格对齐具坊**：沿用主站的 `--ink / --paper / --c-peach…` 大色块配色、`--accent(#ff7a59)` + `--accent-2(#5b8def)` 双强调、28px 大圆角、玻璃拟态区块、左侧 `nav-btn` 导航（≤900px 自动转顶部横条）。
- **零依赖**：不引 jQuery / Bootstrap / 图标字体；图标全部内联 SVG；字体走系统字体栈（PingFang SC / 微软雅黑），零网络请求。
- **性能**：3 个 CSS + 2 个 JS，无阻塞外部资源；动效只碰 `transform` / `opacity`。
- **可访问性**：唯一 `h1`（在下载区）、语义地标、跳转链接、`aria-label`、可见 `:focus-visible` 描边、触摸目标 ≥44px、表格移动端自动转卡片堆叠。
- **降级**：`prefers-reduced-motion: reduce` 下关闭所有动效；禁用 JS 时显示 `noscript` 直链。

## 六、部署到 GitHub Pages

1. 把整个 `cdiskblade-site/` 目录的内容放到仓库 `tools/` 下（例如 `tools/cdiskblade.html` + `tools/assets/...`），
   或单独建仓库后开启 Pages。
2. 若放在子目录，把 `site-data.js` 里的 `homeUrl` 等地址改成实际地址，`index.html` 的 `canonical` 也要改。
3. 提交后等 Pages 构建（约 1 分钟）即可访问。

## 七、在「具坊」网站的「C 盘之刃」模块加官网入口

见 `integration/jufang-card-entry.snippet.html`，里面写清了插入位置和三种写法（推荐把原来的「项目主页 ↗」次按钮直接指向本站）。
