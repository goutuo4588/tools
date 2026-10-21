# C盘利刃 · 源码（v2.8）

Windows C 盘维护工具，PyQt6 单文件实现，PyInstaller 一键打包为零依赖 exe。

## 文件说明

| 文件 | 说明 |
|---|---|
| `main.py` | 全部程序逻辑（UI / 扫描 / 迁移 / C盘初始化 / 资源守卫），单文件约 20 万字符 |
| `C盘利刃.spec` | PyInstaller 打包配置（图标烧进 PE 头、附带 ico/png/jpg 资源） |
| `icon.ico` | 应用图标（写进 exe 的 PE 资源，决定桌面/任务栏显示） |
| `icon_256.png` | 运行时窗口图标 |
| `bg_blur.jpg` | 玻璃拟态背景（模糊已离线烘好，运行时零模糊运算） |
| `make_icon.py` / `make_bg.py` | 图标与背景的生成脚本（PyQt6 绘制） |

## 构建

```bat
python -m PyInstaller "C盘利刃.spec" --noconfirm --distpath dist --workpath build
dist\C盘利刃.exe
```

依赖：Python 3.11+ / PyQt6 / PyInstaller 6.x，仅 Windows。

## v2.8 关键机制

1. **系统组件保护**：`plan_clean_targets()` 对 `Program Files` / `(x86)` 下条目用
   `PF_NAME_WHITELIST` + `windows*` 前缀规则判定，Windows 内置组件永不删除，保证系统自身
   重置（PBR / WinRE）仍可用。
2. **资源守卫（Resource Guardian）**：`RESOURCE_SPECS` 登记表 + `%LOCALAPPDATA%\C盘利刃\`
   隐藏目录。桌面快捷方式、配置、本体、图标缺失时按来源自动补回；已存在且被用户修改过
   （指纹比对）不覆盖；失败计数 ≥5 熔断 24 小时防死循环；动作写 `guardian.log`。
   触发点：启动后台线程 / 访问功能前 / `--notify` 定时任务。
3. **只创建一次的快捷方式**：标记文件 `.shortcut_created` 存在即跳过；程序本体放在隐藏目录，
   桌面只暴露快捷方式。

> 高危提示：C盘初始化会清空 C 盘全部个人数据且不可逆，运行前务必备份。

同步时间：2026-10-21 08:59 UTC
