/* ============================================================
   site-data.js —— 全站唯一内容源
   ------------------------------------------------------------
   【怎么用】只改这一个文件就能换掉全站的文字、链接、版本号、截图、
            更新日志与系统要求；index.html 只负责结构与样式。
   【占位符】每个字段上方的注释里写着对应占位符名，形如 {{VERSION}}，
            与 README.md 的「占位符汇总表」一一对应。
   【默认值】下面的值都是可直接使用的推荐示例，请按需替换。
   ============================================================ */
window.SITE = {

  /* ---------- 基本信息 ---------- */
  appName:      'C 盘之刃',                       /* {{APP_NAME}}      软件名 */
  appNameEn:    'CDiskBlade',                     /* {{APP_NAME_EN}}   英文名（用于 URL / 文件名） */
  version:      'v2.9',                           /* {{VERSION}}       版本号（首屏 / 下载区 / 页脚） */
  releaseDate:  '2026-10-21',                     /* {{UPDATE_DATE}}   更新日期 */
  fileSize:     '安装版 38.3 MB · 绿色版 36.6 MB', /* {{FILE_SIZE}}     两个版本的大小总览 */
  sha256:       'a94031f7ede41be8b4c9f3372ab84c0b3ad5d778506e69f3e0e520af69ee4921', /* {{SHA256}} 校验值（默认给绿色版） */
  tagline:      '一把给 Windows 用的 C 盘清理小刀：扫得快、删得准，系统组件碰不得。', /* {{TAGLINE}} 一句话定位 */

  /* ---------- 链接（都换成你自己的地址） ---------- */
  downloadUrl:  'https://raw.githubusercontent.com/goutuo4588/tools/main/files/cdiskblade-v2.9-win64.exe', /* {{DOWNLOAD_URL}} 自建站点直链（默认同绿色版） */
  officialUrl:  'https://github.com/goutuo4588/tools/releases/tag/cdiskblade-v2.9',                       /* {{OFFICIAL_PAGE_URL}} 官方下载页（GitHub Releases） */
  homeUrl:      'https://goutuo4588.github.io/tools/',                                                    /* {{HOME_URL}} 具坊首页（返回入口） */
  repoUrl:      'https://github.com/goutuo4588/tools',                                                    /* {{REPO_URL}} 源码仓库 */

  /* ---------- 两种下载方式：程序完全一样，只是分发形式不同 ---------- */
  setupName:    '安装版',                                                                                   /* {{SETUP_NAME}} */
  setupTag:     '推荐 · 长期用',                                                                            /* {{SETUP_TAG}} */
  setupDesc:    '带安装向导，双击后可以自己选装到哪个盘、哪个目录；开始菜单有入口，控制面板 / 设置里能正常卸载。适合装在常用电脑上一直用。', /* {{SETUP_DESC}} */
  setupFile:    'cdiskblade-setup-v2.9.exe',                                                               /* {{SETUP_FILE}} */
  setupSize:    '38.3 MB（40,173,081 字节）',                                                               /* {{SETUP_SIZE}} */
  setupSha256:  '8fe2f1fa5e4ad833a3e66064bfb058e321d30d57308bec6fe97c528141c61b58',                        /* {{SETUP_SHA256}} */
  setupUrl:     'https://raw.githubusercontent.com/goutuo4588/tools/main/files/cdiskblade-setup-v2.9.exe', /* {{SETUP_URL}} 安装版直链 */

  portableName: '绿色版',                                                                                   /* {{PORTABLE_NAME}} */
  portableTag:  '免安装 · 可带走的',                                                                        /* {{PORTABLE_TAG}} */
  portableDesc: '一个单文件 EXE，下载完双击就能跑，不用装、不用配环境。可以放 U 盘里随身带，也可以整个目录拷给别人。', /* {{PORTABLE_DESC}} */
  portableFile: 'cdiskblade-v2.9-win64.exe',                                                               /* {{PORTABLE_FILE}} */
  portableSize: '36.6 MB（38,386,667 字节）',                                                               /* {{PORTABLE_SIZE}} */
  portableSha256:'a94031f7ede41be8b4c9f3372ab84c0b3ad5d778506e69f3e0e520af69ee4921',                       /* {{PORTABLE_SHA256}} */
  portableUrl:  'https://raw.githubusercontent.com/goutuo4588/tools/main/files/cdiskblade-v2.9-win64.exe', /* {{PORTABLE_URL}} 绿色版直链 */

  /* ---------- 署名 ---------- */
  author:       '狗托儿',                          /* {{AUTHOR_NAME}}     作者署名 */
  authorEmail:  'goutuoshigesha@163.com',          /* {{AUTHOR_EMAIL}}    联系邮箱 */
  authorSign:   '2026 年秋 · 于斋',                /* {{AUTHOR_SIGN_DATE}} 署名时间与地点 */

  /* ---------- 软件简介 ---------- */
  intro: 'C 盘之刃是一个面向个人用户的 Windows C 盘维护工具。它把「扫描残留 → 迁移缓存 → 必要时重置 C 盘」这条链路做成三步按钮，内置安全围栏，系统目录与受保护档案永远不会被删除。', /* {{INTRO_TEXT}} */

  /* ---------- 开发故事（四段：出发点 / 过程 / 耗时 / 结果） ---------- */
  story: [
    { when:'出发点', title:'C 盘红了，却不敢乱删',          /* {{STORY_1_TITLE}} */
      text:'电脑用久了 C 盘常年飘红，网上那些清理工具要么删一半留一半，要么动不动误伤系统文件。我想要一个「敢让它自己动手」的工具。' }, /* {{STORY_1_TEXT}} */
    { when:'开发过程', title:'先把安全围栏画好，再写清理',   /* {{STORY_2_TITLE}} */
      text:'先花时间把 Windows 系统目录、Program Files 下的系统组件、常见软件的受保护档案列成白名单，再写扫描与删除；清理、迁移、初始化三条链路都跑后台线程，界面不卡死。' }, /* {{STORY_2_TEXT}} */
    { when:'耗时', title:'断断续续两周，虚拟机里反复实测',    /* {{STORY_3_TITLE}} */
      text:'从第一行代码到 v2.9 前后两周：先在虚拟机里造 10 GB 靶机文件实测 C 盘初始化会不会崩，再回头补快捷方式只建一次、资源删除后自动补回、异常兜底这些细节。' }, /* {{STORY_3_TEXT}} */
    { when:'最终结果', title:'一个 37 MB 的单文件，零依赖',  /* {{STORY_4_TITLE}} */
      text:'最终产物是一个 37 MB 的 Windows x64 单文件 EXE：双击即用、不用装环境，系统组件保护、资源自愈、崩溃日志全部内置，直接分发给别人也能跑。' } /* {{STORY_4_TEXT}} */
  ],

  /* ---------- 核心功能亮点（3–6 项，icon 可选值见 main.js 的 ICONS） ---------- */
  featuresLead: '六项能力，围绕「快、准、稳」三件事。', /* {{FEATURES_LEAD}} */
  features: [
    { icon:'broom',  title:'残留一键清理',        /* {{FEATURE_1_TITLE}} */
      desc:'扫描第三方软件残留、临时文件与卸载残留，批量勾选后一次清干净，全程后台线程不卡界面。' }, /* {{FEATURE_1_DESC}} */
    { icon:'move',   title:'缓存安全迁移',        /* {{FEATURE_2_TITLE}} */
      desc:'把微信、QQ 等软件的缓存目录整体搬到其他盘并保留可访问入口，源文件删除前先确认迁移成功。' }, /* {{FEATURE_2_DESC}} */
    { icon:'reset',  title:'C 盘初始化',          /* {{FEATURE_3_TITLE}} */
      desc:'需要重装又不愿重做系统时，调用系统重置能力彻底清空 C 盘；高危操作二次确认，运行前强制提示备份。' }, /* {{FEATURE_3_DESC}} */
    { icon:'shield', title:'系统组件安全围栏',    /* {{FEATURE_4_TITLE}} */
      desc:'Common Files、Internet Explorer、Defender、WindowsPowerShell 等系统组件列入永久白名单，扫得到也删不掉。' }, /* {{FEATURE_4_DESC}} */
    { icon:'heal',   title:'资源自愈',            /* {{FEATURE_5_TITLE}} */
      desc:'桌面快捷方式、配置文件、程序本体被误删后，下次启动自动补回，并带熔断保护避免反复失败。' }, /* {{FEATURE_5_DESC}} */
    { icon:'bolt',   title:'秒级扫描',            /* {{FEATURE_6_TITLE}} */
      desc:'扫描走后台线程 + 分批提交，点下去立刻出结果，不再出现鼠标长时间转圈。' } /* {{FEATURE_6_DESC}} */
  ],

  /* ---------- 版本更新说明（只保留当前版本；要加历史版本就往数组后面追加） ---------- */
  logs: [
    { version:'v2.9', date:'2026-10-21',           /* {{LOG_1_VERSION}} / {{LOG_1_DATE}} */
      items:[
        'Program Files 下的系统组件列入永久保护，不再出现在清理列表',  /* {{LOG_1_ITEM_1}} */
        '桌面快捷方式改为「只创建一次」，后续启动不再重复生成',        /* {{LOG_1_ITEM_2}} */
        '新增资源守卫：快捷方式 / 配置 / 本体被删后下次启动自动补回',  /* {{LOG_1_ITEM_3}} */
        '迁移与初始化链路补充异常兜底，出错不再闪退'                  /* {{LOG_1_ITEM_4}} */
      ]}
  ],

  /* ---------- 系统环境要求（左侧表头 / 右侧说明，warn:true 会标红） ---------- */
  requirementsLead: '装之前先对一眼，省得下载完发现跑不起来。', /* {{REQUIREMENTS_LEAD}} */
  requirements: [
    { k:'操作系统',   v:'Windows 10（1809 及以上）或 Windows 11，64 位' },                 /* {{REQ_OS}} */
    { k:'处理器',     v:'x64 架构，近五年内的 Intel / AMD 均可' },                          /* {{REQ_CPU}} */
    { k:'内存',       v:'4 GB 及以上（建议 8 GB）' },                                       /* {{REQ_RAM}} */
    { k:'磁盘空间',   v:'安装包 37.8 MB；C 盘初始化会清空 C 盘，务必先备份' },              /* {{REQ_DISK}} */
    { k:'运行依赖',   v:'无。单文件自带 Qt6 / Python 3.13 运行环境与 VC++ 运行库，免安装' }, /* {{REQ_DEP}} */
    { k:'权限',       v:'需要管理员权限（右键「以管理员身份运行」），否则部分目录无法清理' }, /* {{REQ_PERM}} */
    { k:'网络',       v:'离线可用；仅「检查更新」会联网' },                                 /* {{REQ_NET}} */
    { k:'不支持',     v:'Windows 7 / 8 / 32 位系统、非 x64 设备（依赖 Qt6 运行环境）', warn:true } /* {{REQ_NOTSUPPORT}} */
  ]
};
