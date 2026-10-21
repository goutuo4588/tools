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

## 六、部署位置与依赖资源路径（已上线）

仓库：`github.com/goutuo4588/tools`（Pages 根目录 = `https://goutuo4588.github.io/tools/`）

| 仓库路径 | 线上地址 | 说明 |
|---|---|---|
| `cdiskblade/index.html` | `https://goutuo4588.github.io/tools/cdiskblade/` | 官网首页（5 个界面都在这一页内） |
| `cdiskblade/assets/css/tokens.css` | 同上目录 + `assets/css/tokens.css` | 设计变量 |
| `cdiskblade/assets/css/base.css` | 同上 + `assets/css/base.css` | 骨架与无障碍 |
| `cdiskblade/assets/css/components.css` | 同上 + `assets/css/components.css` | 界面转场、卡片、表格 |
| `cdiskblade/assets/js/site-data.js` | 同上 + `assets/js/site-data.js` | 内容源（要改文本只动它） |
| `cdiskblade/assets/js/main.js` | 同上 + `assets/js/main.js` | 路由与交互 |
| `cdiskblade/README.md` | — | 说明文档（不参与渲染） |
| `assets/shots/*.png` | 未上传（截图区已删，目录为空） | 若以后加截图，放这里并改 `site-data.js` 的 `shots` |

全部用**相对路径**引用（`assets/css/...`），所以整目录换个位置也照样能跑；只有「返回具坊」「下载链接」这类外链是绝对地址，写在 `site-data.js` 里。

## 七、接入「具坊」主站的方式（已实际应用）

### 采用的方案：同站独立页面 + 卡片按钮跳转（**不用 iframe、不合入源码**）

| 方案 | 结论 | 原因 |
|---|---|---|
| 把官网 HTML 结构合进具坊 `index.html` | ❌ 不采用 | 具坊首页是 130KB 单页应用，自带 `.view` 路由、`.sidebar`、`:root` CSS 变量；官网也有同名类名与变量，合并后样式互相覆盖、两套 JS 路由打架，且首页体积再涨一大截 |
| iframe 内嵌 | ⚠️ 备选 | 需要固定高度、会出现第二根滚动条，移动端体验与收录都不好；真要内嵌看 `integration/iframe-embed.snippet.html`（含自适应高度脚本） |
| **同站独立页面 + 入口按钮** | ✅ 采用 | 零冲突、零性能影响、可单独收录与分享，点按钮 `target="_blank"` 打开，不把访客带离具坊 |

### 具体插入位置与代码

**位置**：具坊 `index.html` → 搜索 `data-slug="cdiskblade"` → 该卡片的 `<div class="tool-links">`，**GitHub 下载按钮的右侧**（即原来的 `.dl-sub` 次按钮位）。

**改动**：把原先指向具坊首页的「项目主页 ↗」替换为（代码见 `integration/jufang-card-entry.snippet.html`）：

```html
<a class="dl dl-site" href="https://goutuo4588.github.io/tools/cdiskblade/"
   target="_blank" rel="noopener" title="C 盘之刃 官方网址">官方网址 ↗</a>
```

同时新增两处配套内容：
1. `.dl-sub:hover` 规则后加 `.dl-site` 样式（青绿底，呼应「查看介绍」而非「下载」）；
2. 卡片的 `<ul class="note">` 说明区加一行「官方网址」链接。
3. `sitemap.xml` 增加官网地址，方便搜索引擎收录。

### 桌面端 / 移动端

官网自身是响应式：≤900px 左侧导航自动变顶部横条、≤480px 按钮撑满、表格转卡片堆叠，已在 1440 / 390 两档实测无横向溢出；具坊侧按钮沿用现有 `.dl` 弹性布局，卡片内自动换行，不挤坏原有布局。

### 性能影响

具坊首页只多了 1 个 `<a>` 和 2 行 CSS（+392 字节），官网的 CSS/JS 全部只在 `cdiskblade/` 页面加载，不影响具坊首屏与加载速度。
