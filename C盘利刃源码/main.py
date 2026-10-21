# -*- coding: utf-8 -*-
"""
=============================================================================
 C盘利刃  V2.2  (单文件合并版)
 一个exe两用：
   双击运行        -> 主程序（C盘迁出 + C盘初始化）
   C盘利刃.exe --notify  -> 直接弹出重置成功/失败通知窗
=============================================================================
"""
import sys
import os
import re
import json
import ctypes
import winreg
import subprocess
import shutil
import tempfile
import datetime
import hashlib
import webbrowser
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QTextEdit, QMessageBox,
                             QFileDialog, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
                             QCheckBox, QLabel, QHBoxLayout, QDialog, QDialogButtonBox, QProgressBar,
                             QGraphicsDropShadowEffect, QAbstractItemView, QRubberBand,
                             QLineEdit, QFormLayout)
from PyQt6.QtGui import QColor, QTextCharFormat, QIcon, QPixmap, QDesktopServices, QPainter
from PyQt6.QtCore import (Qt, QPropertyAnimation, QTimer, QThread, pyqtSignal, QUrl, QRect, QRectF, QPoint, QSize,
                          QEvent, QElapsedTimer)

# 背景图候选（按优先级）。bg_blur.jpg 由 make_bg.py 离线生成：
# 模糊/抠图/羽化全部在开发期烘进静态图，运行时不做任何模糊运算
# （Qt 的 QGraphicsBlurEffect 是逐帧重算的，那是全局卡顿的头号来源）。
BG_CANDIDATES = ("bg_blur.jpg", "bg_blur.png", "bg.jpg", "bg.png")
# 单个背景图的像素上限：缩放代价与源图面积成正比，源图越大每次缩放越贵。
# 1600x1080 已足够铺满任何常见窗口（含 2K 屏），再大只是白烧 CPU。
BG_MAX_SRC_PIXELS = 1600 * 1080


def load_bg_pixmap():
    """加载背景图并在必要时降采样到 BG_MAX_SRC_PIXELS，控制运行时缩放开销。"""
    for cand in BG_CANDIDATES:
        p = res_path(cand)
        if not os.path.exists(p):
            continue
        pm = QPixmap(p)
        if pm.isNull():
            continue
        if pm.width() * pm.height() > BG_MAX_SRC_PIXELS:
            # 一次性降采样（启动时做一次，之后不再处理）
            ratio = (BG_MAX_SRC_PIXELS / (pm.width() * pm.height())) ** 0.5
            pm = pm.scaled(max(1, int(pm.width() * ratio)), max(1, int(pm.height() * ratio)),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        return pm
    return None


# ===================== 玻璃拟态弹窗基类（无灰色实底，铺虚化背景 + 蒙版） =====================
class GlassDialog(QDialog):
    def __init__(self, parent=None, dark=False):
        super().__init__(parent)
        self.dark = dark
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowIcon(QIcon(res_path("icon_256.png")))
        self._bg = load_bg_pixmap()
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(False)
        self.scrim = QLabel(self)
        self.bg_label.stackUnder(self.scrim)
        self._apply_scrim()
        self._update_bg()
        # 背景图缩放防抖：拖拽改变大小时只调度，停止 50ms 后才真正做平滑缩放
        # （原版每次 resizeEvent 都 Synchronous 全图 SmoothTransformation，拖窗口边框会明显掉帧）
        self._bg_timer = QTimer(self)
        self._bg_timer.setSingleShot(True)
        self._bg_timer.setInterval(50)
        self._bg_timer.timeout.connect(self._update_bg)

    def _apply_scrim(self):
        tint = "rgba(17,24,39,0.72)" if self.dark else "rgba(255,255,255,0.60)"
        self.scrim.setStyleSheet(f"background-color:{tint};")

    def _update_bg(self):
        w, h = max(self.width(), 1), max(self.height(), 1)
        self.bg_label.setGeometry(0, 0, w, h)
        self.scrim.setGeometry(0, 0, w, h)
        if self._bg is None:
            return
        # 与主窗口同一套做法：铺满+居中裁切，但不生成多余的中间图
        sw, sh = self._bg.width(), self._bg.height()
        ratio = max(w / sw, h / sh)
        tw, th = max(1, min(w, round(sw * ratio))), max(1, min(h, round(sh * ratio)))
        pm = self._bg.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        if tw != w or th != h:
            pm = pm.copy((tw - w) // 2, (th - h) // 2, w, h)
        self.bg_label.setPixmap(pm)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._bg_timer.start()


# ===================== 下载窗口（选保存位置 → 下载 → 完成） =====================
# 放在 GlassDialog 定义之后导入：DownloadDialog 会自动复用主程序这个玻璃拟态基类，
# 视觉/层级/背景与主窗口完全一致（放文件顶部也能跑，只是会降级用模块自带的同款基类）。
from download_dialog import DownloadDialog, DownloadItem


# 启动时要下载的文件清单。留空 = 只做「选择保存位置」，不下载任何东西。
# 想真正下载时往这里填，例：
#   DownloadItem("C盘利刃_V2.3.exe", url="https://你的站点/C盘利刃_V2.3.exe", size=18 * 1024 * 1024)
#   DownloadItem("手势刷.apk", path=r"D:\打包产物\手势刷.apk")   # path = 本地复制模式，不走网络
# size 填预估字节数用于提前校验磁盘空间；不知道就填 0（进度改为按文件个数推进）。
DOWNLOAD_MANIFEST = [
    # DownloadItem("示例工具.exe", url="https://example.com/示例工具.exe", size=0),
]


def run_download_window_if_needed(parent=None, dark=False):
    """启动阶段弹出下载窗口。

    返回 (保存目录, 已下载文件列表)；用户取消 / 本次不弹 → ("", [])。
    全生命周期只有这一个实例：exec() 模态显示，下载在 QThread 里跑，
    主线程不阻塞；实例函数结束即销毁，closeEvent 里已兜底停线程，不会重复弹出。

    弹出时机取舍（这是刻意设计的，不是随手写的）：
      · 清单非空（有真实东西要下）→ 每次启动都弹，用户要有机会确认/改保存位置
      · 清单为空                  → 一律不弹（安装器已经让用户选过安装位置了，
                                    启动再问一次就是重复劳动，纯属打扰）
      · config.download_popup_on_start = False → 彻底关掉，不再弹
    理由：软件分发已经改成 Inno Setup 安装器，"装到哪"由安装器负责；
    这个窗口回归本职——只在真有文件要下载时出现。
    """
    cfg = load_config()
    if not cfg.get("download_popup_on_start", True):
        return ("", [])
    # 没有下载内容就不弹：安装器已经问过安装位置，这里再问一次没意义
    if not DOWNLOAD_MANIFEST:
        return ("", [])

    dlg = DownloadDialog(parent, DOWNLOAD_MANIFEST, dark=dark, title="下载工具")
    try:
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ("", [])
        return (dlg.saved_dir, list(dlg.saved_files))
    finally:
        # 关窗即释放：切断信号连接，避免线程回调打到已销毁的控件上
        try:
            if dlg.worker is not None:
                dlg.worker.quit()
                dlg.worker.wait(3000)
        except Exception:
            pass
        dlg.deleteLater()


# ===================== 全局常量配置 =====================
APP_NAME = "C盘利刃"
APP_VERSION = "V2.9"   # 与线上已发布的 v2.9 对齐（原常量漏改成 V2.2，功能其实是同一版）


def _user_desktop_dir():
    """返回用户桌面目录（兼容 OneDrive 桌面重定向），取不到返回 None。"""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(cand):
            return cand
    # 兜底：读 shell 的真实桌面路径
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, "Desktop")
            val = os.path.expandvars(val)
            if os.path.isdir(val):
                return val
    except Exception:
        pass
    return None


def _shortcut_marker_path():
    """「桌面快捷方式已创建过」的标记文件。
    放在 %LOCALAPPDATA%\\C盘利刃\\ 下而不是桌面，避免被用户整理桌面时顺手删掉。"""
    return os.path.join(os.path.expanduser("~"), "AppData", "Local", APP_NAME, ".shortcut_created")


def _write_shortcut_marker(marker, lnk_path, target, note=""):
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        import json, datetime
        with open(marker, "w", encoding="utf-8") as f:
            json.dump({"lnk": lnk_path, "target": target, "note": note,
                       "version": APP_VERSION,
                       "time": datetime.datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False)
    except Exception:
        pass


# ===================== 受管资源 = 定义（Resource Registry） =====================
# 资源守卫（Resource Guardian）维护的全部资源都在这里登记：
#   id / 说明 / 类型 / 原始来源 / 是否参与指纹校验 / 对应开关
# 「程序本体」与「安装目录」一律放在隐藏的 %LOCALAPPDATA%\C盘利刃\ 下，
# 桌面上只暴露一个快捷方式。
def _stable_dir():
    return os.path.join(os.path.expanduser("~"), "AppData", "Local", APP_NAME)


def _stable_exe_path():
    return os.path.join(_stable_dir(), APP_NAME + ".exe")


def _stable_icon_path():
    return os.path.join(_stable_dir(), APP_NAME + ".ico")


def _config_path():
    return os.path.join(_stable_dir(), "config.json")


# 配置文件默认值（代码中的默认定义 = 配置类资源的原始来源）
DEFAULT_CONFIG = {
    "version": 1,
    "auto_restore_shortcut": True,    # 桌面快捷方式缺失 -> 下次启动自动补回
    "auto_restore_stable_exe": True,  # 程序本体/图标缺失 -> 下次启动自动补回
    "hide_exe_from_desktop": True,    # 桌面只保留快捷方式，本体归位到隐藏目录
    "guardian_log": True,             # 记录资源守卫执行日志
    "download_popup_on_start": True,  # 启动时弹「下载/选择保存位置」窗口（False = 彻底不弹）
    "download_last_dir": "",          # 上次选择的保存目录（由下载窗口自动写入）
}

# 资源登记表（顺序 = 补回顺序，被依赖的排在前面）
RESOURCE_SPECS = (
    {"id": "app_config",      "title": "程序配置",       "fp": False, "cfg": None},
    {"id": "stable_exe",      "title": "程序本体(隐藏)", "fp": False, "cfg": "auto_restore_stable_exe"},
    {"id": "stable_icon",     "title": "图标资源",       "fp": False, "cfg": "auto_restore_stable_exe"},
    {"id": "desktop_shortcut", "title": "桌面快捷方式",   "fp": True,  "cfg": "auto_restore_shortcut"},
)

GUARDIAN_STATE_VERSION = 1
GUARDIAN_MAX_FAIL = 5          # 连续失败达此数 -> 熔断，24 小时内不再尝试（防死循环）
GUARDIAN_LOG_MAX = 256 * 1024  # 日志轮转阈值
GUARDIAN_LOG_KEEP = 200        # 轮转后保留行数


def _guardian_state_path():
    return os.path.join(_stable_dir(), "guardian_state.json")


def _guardian_log_path():
    return os.path.join(_stable_dir(), "guardian.log")


def _resource_path(res_id):
    """返回资源当前应当在的位置。"""
    if res_id == "app_config":
        return _config_path()
    if res_id == "stable_exe":
        return _stable_exe_path()
    if res_id == "stable_icon":
        return _stable_icon_path()
    if res_id == "desktop_shortcut":
        d = _user_desktop_dir()
        return os.path.join(d, APP_NAME + ".lnk") if d else ""
    return ""


def _fp_of(path):
    """小文件的内容指纹（sha256 前 16 位），用于判断「用户是否改过」。
    大文件（38MB 本体）不做指纹，用 存在性 + 大小 判断即可。"""
    try:
        if not path or not os.path.isfile(path):
            return ""
        if os.path.getsize(path) > 8 * 1024 * 1024:
            return ""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _guardian_log(msg):
    """守卫执行日志：时间戳 + 内容，超阈值自动轮转。"""
    try:
        p = _guardian_log_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            if os.path.exists(p) and os.path.getsize(p) > GUARDIAN_LOG_MAX:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                with open(p, "w", encoding="utf-8") as f:
                    f.writelines(lines[-GUARDIAN_LOG_KEEP:])
        except Exception:
            pass
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), msg))
    except Exception:
        pass


def _guardian_load():
    try:
        with open(_guardian_state_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("resources", {})
            return d
    except Exception:
        pass
    return {"version": GUARDIAN_STATE_VERSION, "resources": {}}


def _guardian_save(state):
    try:
        os.makedirs(_stable_dir(), exist_ok=True)
        with open(_guardian_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_config():
    """读取配置；文件缺失/损坏时返回默认值（真正的补回由守卫负责）。"""
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict):
            return c
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def _write_config(cfg):
    try:
        os.makedirs(_stable_dir(), exist_ok=True)
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ---------- 各资源的「按原始来源重建」实现 ----------
def ensure_app_config():
    """配置类资源：缺失 -> 按 DEFAULT_CONFIG 写回；
    已存在 -> 只补齐缺失的键，绝不覆盖用户已改过的值。"""
    p = _config_path()
    try:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cur = json.load(f)
            except Exception:
                cur = {}
            if not isinstance(cur, dict):
                cur = {}
            missing = [k for k in DEFAULT_CONFIG if k not in cur]
            if not missing:
                return "exists"
            for k in missing:
                cur[k] = DEFAULT_CONFIG[k]
            return "merged_defaults" if _write_config(cur) else "failed"
        return "restored" if _write_config(dict(DEFAULT_CONFIG)) else "failed"
    except Exception:
        return "failed"


def _sync_stable_exe():
    """补回/同步「程序本体」到隐藏目录。返回本体路径。
    判定用「文件大小」而不是 mtime（单文件解压副本的 mtime 恒为"刚解压"，
    用 mtime 会导致每次启动白复制一个 38MB 的 exe）。"""
    exe = sys.executable
    stable_dir, stable_exe = _stable_dir(), _stable_exe_path()
    try:
        os.makedirs(stable_dir, exist_ok=True)
        need = True
        if os.path.exists(stable_exe):
            try:
                need = os.path.getsize(stable_exe) != os.path.getsize(exe)
            except Exception:
                need = False
        if need:
            shutil.copyfile(exe, stable_exe)
        if os.path.exists(stable_exe):
            return stable_exe
    except Exception:
        pass
    return exe


def ensure_stable_exe():
    """本体资源：缺失则按「随包 exe」复制一份到隐藏目录。"""
    before = os.path.exists(_stable_exe_path())
    p = _sync_stable_exe()
    after = os.path.exists(_stable_exe_path())
    if after and not before:
        return "restored"
    if after:
        return "exists"
    return "failed"


def ensure_stable_icon():
    """图标资源：缺失则按「随包 icon.ico」复制一份到隐藏目录。"""
    dst = _stable_icon_path()
    before = os.path.exists(dst)
    try:
        src = res_path("icon.ico")
        if not os.path.exists(src):
            return "exists" if before else "failed"
        os.makedirs(_stable_dir(), exist_ok=True)
        if (not os.path.exists(dst)
                or os.path.getsize(dst) != os.path.getsize(src)):
            shutil.copyfile(src, dst)
        if os.path.exists(dst):
            return "restored" if not before else "exists"
    except Exception:
        pass
    return "failed"


def _make_shortcut(lnk_path, target, icon_location):
    """底层：用 WScript.Shell COM 写一个 .lnk。"""
    q = lambda s: s.replace("'", "''")
    ps = (
        "$ws=New-Object -ComObject WScript.Shell;"
        "$lk=$ws.CreateShortcut('" + q(lnk_path) + "');"
        "$lk.TargetPath='" + q(target) + "';"
        "$lk.WorkingDirectory='" + q(os.path.dirname(target)) + "';"
        "$lk.IconLocation='" + q(icon_location) + "';"
        "$lk.Description='" + q(APP_NAME) + "';"
        "$lk.Save()"
    )
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                       capture_output=True, creationflags=0x08000000)
    except Exception:
        pass
    return os.path.exists(lnk_path)


def ensure_desktop_shortcut(force=False, cfg=None, state=None):
    """「桌面快捷方式」资源的补回实现，返回动作码（供守卫记日志）：
      exists              在位且未被改动 -> 什么都不做（幂等）
      restored            缺失已补回
      merged_defaults     配置类：补齐了缺失键
      keep_user_modified  在位但内容被用户改过 -> 保留用户版本，不覆盖
      skip_opt_out        用户在 config.json 里关掉了自动补回 -> 尊重（软删除标记）
      skip_no_desktop     找不到桌面目录
      failed              补回失败（计入失败次数，达阈值熔断）
    """
    if sys.platform != "win32":
        return "skip_no_desktop"
    if cfg is None:
        cfg = load_config()
    if state is None:
        state = _guardian_load()
    try:
        desktop = _user_desktop_dir()
        if not desktop:
            return "skip_no_desktop"
        lnk_path = os.path.join(desktop, APP_NAME + ".lnk")
        # ① 软删除标记（显式 opt-out）：用户主动关掉自动补回 -> 永不重建
        if not force and not cfg.get("auto_restore_shortcut", True):
            return "skip_opt_out"
        # ② 存在性校验 + 用户修改保护
        if os.path.exists(lnk_path) and not force:
            rec = ((state.get("resources") or {}).get("desktop_shortcut") or {})
            fp = _fp_of(lnk_path)
            if rec.get("fp") and fp and rec["fp"] != fp:
                # 内容变了：多半是用户自己改了目标/图标 -> 保留，不覆盖
                return "keep_user_modified"
            return "exists"
        # ③ 缺失 -> 按原始来源重建（目标=隐藏目录里的本体，图标=隐藏目录里的 ico）
        if force and os.path.exists(lnk_path):
            try:
                os.remove(lnk_path)
            except Exception:
                pass
        target = _sync_stable_exe()
        icon = _stable_icon_path() + ",0" if os.path.exists(_stable_icon_path()) else target + ",0"
        if _make_shortcut(lnk_path, target, icon):
            _write_shortcut_marker(_shortcut_marker_path(), lnk_path, target, "自动补回/首次创建")
            return "restored"
        return "failed"
    except Exception:
        return "failed"


def ensure_resource(res_id, cfg=None, state=None):
    """按资源 id 分发到各自的补回实现。"""
    if cfg is None:
        cfg = load_config()
    if state is None:
        state = _guardian_load()
    if res_id == "app_config":
        return ensure_app_config()
    if res_id == "stable_exe":
        if not cfg.get("auto_restore_stable_exe", True):
            return "skip_opt_out"
        return ensure_stable_exe()
    if res_id == "stable_icon":
        if not cfg.get("auto_restore_stable_exe", True):
            return "skip_opt_out"
        return ensure_stable_icon()
    if res_id == "desktop_shortcut":
        return ensure_desktop_shortcut(False, cfg, state)
    return "unknown"


def _relocate_desktop_exe(cfg=None):
    """「桌面只保留快捷方式」：把留在桌面的程序本体归位到隐藏目录。
    只处理与本体同尺寸的副本，绝不误动用户自己放的其他 exe；
    正在运行中的那个本体无法移动 -> 记 failed，下次启动再试（幂等）。"""
    if cfg is None:
        cfg = load_config()
    if not cfg.get("hide_exe_from_desktop", True):
        return "skip_opt_out"
    try:
        d = _user_desktop_dir()
        if not d:
            return "skip_no_desktop"
        src = os.path.join(d, APP_NAME + ".exe")
        if not os.path.exists(src):
            return "absent"
        # 正在从这个文件运行 —— 本次不动它
        try:
            if os.path.samefile(src, sys.executable):
                return "skip_running"
        except Exception:
            pass
        stable = _stable_exe_path()
        try:
            ss = os.path.getsize(src)
            if os.path.exists(stable) and os.path.getsize(stable) == ss:
                os.remove(src)          # 隐藏目录已有同版本，桌面这份是重复副本
                return "removed_duplicate"
            os.makedirs(_stable_dir(), exist_ok=True)
            shutil.move(src, stable)
            return "moved"
        except Exception:
            return "failed"
    except Exception:
        return "failed"


def run_resource_guardian(trigger="startup", ids=None):
    """资源守卫主入口：检测受管资源是否缺失，缺失则按原始来源自动补回。

    幂等与安全：
      * 先做存在性校验，在位即跳过，绝不无意义重写；
      * 在位但被用户改过（指纹不符）-> 保留用户版本；
      * 每个资源有失败计数，连续失败 >= GUARDIAN_MAX_FAIL 熔断 24 小时，防死循环；
      * 全部动作写 guardian.log，异常一律吞掉，绝不影响主程序。
    触发时机：trigger="startup" 下次启动；"feature:*" 下次访问功能；"notify" 定时任务周期。
    返回 {资源id: 动作} 摘要。
    """
    if sys.platform != "win32":
        return {}
    try:
        cfg = load_config()
        state = _guardian_load()
        res = state.get("resources") or {}
        now = datetime.datetime.now()
        summary = {}
        for spec in RESOURCE_SPECS:
            rid = spec.get("id")
            if not rid or (ids and rid not in ids):
                continue
            rec = dict(res.get(rid) or {})
            # 熔断检查
            if int(rec.get("fail", 0) or 0) >= GUARDIAN_MAX_FAIL:
                try:
                    last_fail = datetime.datetime.fromisoformat(rec.get("last_fail", ""))
                    if (now - last_fail).total_seconds() < 86400:
                        summary[rid] = "circuit_open"
                        res[rid] = rec
                        continue
                except Exception:
                    pass
                rec["fail"] = 0
            action = ensure_resource(rid, cfg, state)
            summary[rid] = action
            path = _resource_path(rid)
            fp = _fp_of(path) if spec.get("fp") else ""
            if action in ("restored", "exists", "merged_defaults"):
                rec["fail"] = 0
                res[rid] = dict(rec, fp=fp or rec.get("fp", ""),
                                last_seen=now.isoformat(timespec="seconds"),
                                **({"last_restore": now.isoformat(timespec="seconds")}
                                   if action == "restored" else {}))
            elif action == "keep_user_modified":
                rec["fail"] = 0
                res[rid] = dict(rec, user_modified=True,
                                last_seen=now.isoformat(timespec="seconds"))
            elif action == "failed":
                rec["fail"] = int(rec.get("fail", 0) or 0) + 1
                res[rid] = dict(rec, last_fail=now.isoformat(timespec="seconds"))
            else:
                res[rid] = rec
        # 附加：桌面只保留快捷方式（本体归位）
        if not ids or "desktop_exe" in ids:
            summary["desktop_exe"] = _relocate_desktop_exe(cfg)
        state["resources"] = res
        state["last_run"] = now.isoformat(timespec="seconds")
        state["last_trigger"] = trigger
        _guardian_save(state)
        if cfg.get("guardian_log", True):
            _guardian_log("[%s] %s" % (trigger, ", ".join(
                "%s=%s" % (k, v) for k, v in summary.items())))
        return summary
    except Exception:
        return {}


# 作者与商务合作信息
AUTHOR_NAME = "狗托是个啥"
AUTHOR_EMAIL = "goutuoshigehsa@163.com"
AUTHOR_SITE = "https://goutuo4588.github.io/tools/"

HELP_TEXT = f"""{APP_NAME}  {APP_VERSION} 使用手册（单文件版）

【一个exe两用】
- 双击运行        -> 主程序
- C盘利刃.exe --notify  -> 重置后弹窗通知（开机任务自动调用）

【功能1：C盘文件迁出】
1. 点击【C盘文件迁出】按钮，后台线程扫描C盘非系统目录（界面不卡，秒级完成）
2. 在列表里勾选要迁移的文件夹：可单击单个勾选；也可在列表空白处按住鼠标左键拖拽，像桌面框选图标一样成片批量勾选（红色[高危·勿迁]默认不勾选，谨慎选择）
3. 只要勾选了≥1个可迁移文件夹，界面右下角会自动出现【开始迁移】按钮
4. 点击【开始迁移】：程序自动选择剩余空间最大的非C盘符，并在其下创建落地文件夹「非c盘文件迁移落脚点」
5. 后台计算总大小 + 容量校验（绿/黄/红三态），点击【确认并开始迁移】
6. 后台线程实时复制，进度条+当前文件名实时更新
7. 复制完成后自动删除C盘源文件，导出迁移日志

【功能2：C盘初始化】
- PBR引擎（WinRE可用时）：调用Windows原生重置，清空C盘，D/E保留
- 降级引擎（精简系统）：批量卸载软件+删除文件
- 触发前自动把自身exe复制到 D:\\ResetToolBootstrap\\
- 配合开机任务，新系统登录自动弹成功/失败提示

【按钮说明】
- 添加开机提醒任务：创建schtasks登录自启任务（自动带--notify参数；预埋程序缺失时会自动补齐）。建好任务后执行【C盘初始化】，下次开机自动弹出重置结果通知；重置中途断电/崩溃则弹失败+日志
- 删除开机提醒任务：移除任务
- 切换深色/浅色：一键换肤
- 关于/合作：查看作者信息与商务合作方式

【支持系统】Win10 1709+ / Win11
【不支持】Win7/8/XP / Server / ARM
"""


def about_html() -> str:
    return f"""
<div style="font-family:'Microsoft YaHei'; font-size:10.5pt; line-height:1.65;">
<h2 style="margin:2px 0 10px;">关于作者 &amp; 商务合作</h2>
<p><b>作者昵称：</b>{AUTHOR_NAME}</p>
<p><b>联系邮箱：</b><span style="color:#2563eb;">{AUTHOR_EMAIL}</span></p>
<p><b>开源主页：</b><a href="{AUTHOR_SITE}">{AUTHOR_SITE}</a></p>
<hr/>
<p><b>关于本工具</b><br/>
C盘利刃（C盘维护之刃）是一款面向个人与小微团队的 Windows C盘维护工具，
提供 C盘文件安全迁出与系统重置/清理能力，所有高危操作均带明确风险提示与确认拦截。</p>
<p><b>商务合作</b><br/>
如果您或所在团队有以下需求，欢迎来信沟通，我们可以按需合作：</p>
<ul>
<li>定制化的系统维护 / 批量部署工具开发</li>
<li>面向企业内网的离线版、去联网依赖改造</li>
<li>新功能模块外包（自动备份、定时任务、报表导出等）</li>
<li>技术答疑与一对一支持</li>
</ul>
<p>我们秉持「实用、安全、零依赖、可直接分发」的理念，期待与有意向的朋友共同打磨更顺手的小工具。</p>
</div>"""

WHITE_LIST = [
    r"C:\Windows",
    r"C:\$Recycle.Bin",
    r"C:\Program Files\WindowsApps",
    r"C:\Program Files\Windows Defender",
    r"C:\ProgramData\Microsoft",
    r"C:\Boot",
    r"C:\Recovery",
    r"C:\System Volume Information"
]

# ===================== Program Files 下的「Windows 内置组件」保护名单 =====================
# 背景（2026-10-20 VM 实测发现）：plan_clean_targets 只保护顶层系统根（Windows/Users/
# Program Files/ProgramData…），不保护它们的**子目录**。结果 C 盘初始化会把
# C:\Program Files\Internet Explorer、Windows NT、WindowsPowerShell、Windows Mail、
# Windows Media Player、Common Files 等 Windows 自带组件一并删掉 —— 这不只是"误删"，
# 更致命的是：删掉这些系统组件后，系统自身的重置（PBR / 恢复环境）会失败或跑出残废系统。
# 因此这里按【目录名】做保护（大小写不敏感，同时作用于 Program Files 与 Program Files (x86)）。
# 判定规则（命中任一条即保护）：
#   1) 目录名以 "windows" 开头（覆盖 WindowsApps / Windows Defender / Windows NT /
#      WindowsPowerShell / Windows Media Player / Windows Mail / Windows Security /
#      Windows Sidebar / ModifiableWindowsApps 等全部内置组件与运行时）
#   2) 目录名在下方精确名单中（Common Files 等被大量软件共享的系统级目录）
PF_NAME_WHITELIST = {
    "common files",            # 系统级共享目录，大量软件依赖
    "internet explorer",       # IE 内核组件（不随第三方软件卸载）
    "modifiablewindowsapps",   # 应用商店可写镜像目录
    "desktopappinstaller",     # Microsoft 商店安装器
}
# 按完整路径保护的条目（目录名规则覆盖不到的系统组件）
PF_PATH_WHITELIST = (
    r"c:\program files\microsoft\edge",        # Edge 属 Windows 系统组件，
    r"c:\program files (x86)\microsoft\edge",  # 删除会破坏 WebView2 / 更新链路
)
PF_PREFIX_PROTECTED = ("windows",)

def _is_pf_builtin(path: str) -> bool:
    """判断 Program Files / Program Files (x86) 下的条目是否为 Windows 内置组件（受保护，不删）。"""
    try:
        lp = path.rstrip("\\").lower()
        name = os.path.basename(lp)
    except Exception:
        return False
    if not name:
        return False
    if name in PF_NAME_WHITELIST:
        return True
    for w in PF_PATH_WHITELIST:
        if lp == w or lp.startswith(w + "\\"):
            return True
    return name.startswith(PF_PREFIX_PROTECTED)

NOTIFY_EXE_NAME = "C盘利刃.exe"   # 合并后同一个exe
TASK_NAME = "ResetNotifyAutoRun"


def pick_bootstrap_dir() -> str:
    """预埋文件目录：优先【可写的非 C 本地盘】，退化 ProgramData，再退化 %TEMP%。
    绝不写死某个盘符（旧版写死 D:，遇到只读光盘/无 D 盘/被占用就直接崩）。"""
    def _try_dir(cand: str):
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".wb_probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("1")
            os.remove(probe)
            return cand
        except Exception:
            return None

    # 1) 可写非 C 本地盘（list_writable_fixed_drives 会真实试写，排除只读盘/光驱）
    try:
        for drv in list_writable_fixed_drives():
            got = _try_dir(os.path.join(drv, "ResetToolBootstrap"))
            if got:
                return got
    except Exception:
        pass
    # 2) ProgramData（管理员权限下可写）
    pd = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    got = _try_dir(os.path.join(pd, "ResetToolBootstrap"))
    if got:
        return got
    # 3) 兜底：当前用户临时目录
    tmp = os.environ.get("TEMP") or r"C:\Windows\Temp"
    return os.path.join(tmp, "ResetToolBootstrap")


# BOOTSTRAP_DIR 依赖上面的探测逻辑，改为懒计算（见 get_bootstrap_dir）

# ===================== 资源路径（兼容 PyInstaller 单文件解包与源码运行） =====================
def res_path(name: str) -> str:
    """获取打包资源路径：冻结时从 _MEIPASS 取（onedir 模式下数据文件位于 _internal 子目录，做兜底探测），源码运行从脚本同目录取。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        cand = os.path.join(base, name)
        if os.path.exists(cand):
            return cand
        cand2 = os.path.join(base, "_internal", name)
        if os.path.exists(cand2):
            return cand2
        return cand
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

# ===================== 工具函数 =====================
def get_folder_size(path: str, stop_check=None) -> int:
    """统计目录体积（迭代式栈遍历，深目录不会爆递归上限；函数调用开销也更低）。
    stop_check: 可选的可中断检查（返回 True 时提前结束），供后台扫描支持取消。"""
    total = 0
    stack = [path]
    while stack:
        if stop_check is not None and stop_check():
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except PermissionError:
                        continue
                    except OSError:
                        continue
        except PermissionError:
            continue
        except OSError:
            continue
    return total

def bytes_human(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes/(1024**2):.2f} MB"
    else:
        return f"{size_bytes/(1024**3):.2f} GB"

def get_disk_free(path: str) -> int:
    """查询剩余空间。UNC 路径（如 \\\\vboxsvr\\share2）没有盘符，直接对路径本身查询。"""
    try:
        drv = os.path.splitdrive(path)[0]
        statv = shutil.disk_usage(drv if drv else path)
        return statv.free
    except (OSError, ValueError):
        return 0


def disk_usage_of(path: str):
    """返回 (总容量, 已用, 可用)，取不到返回 (0,0,0)。"""
    try:
        u = shutil.disk_usage(path)
        return u.total, u.used, u.free
    except (OSError, ValueError):
        return 0, 0, 0


def c_drive_usage():
    """C 盘实时容量（总/已用/可用）——所有"释放了多少"的数字都来自它，不估算、不编造。"""
    return disk_usage_of("C:\\")


def force_rmtree(path: str):
    """强删除目录：desktop.ini 这类带 只读/隐藏/系统属性 的文件会让普通 rmtree 直接报
    "拒绝访问"，导致"内容已复制但源删不掉"。这里在删除失败时先清掉文件属性再重试，
    仍失败（如 Explorer 正占用）则抛出原异常，由上层按"源已保留"处理。"""
    FILE_ATTRIBUTE_NORMAL = 0x80

    def _onexc(func, p, _exc):
        try:
            ctypes.windll.kernel32.SetFileAttributesW(p, FILE_ATTRIBUTE_NORMAL)
        except Exception:
            pass
        func(p)     # 清属性后重试；还失败就把异常抛回给上层

    kwargs = {"onexc": _onexc}
    if sys.version_info < (3, 12):
        kwargs = {"onerror": _onexc}
    shutil.rmtree(path, **kwargs)


def _drive_type(d: str) -> int:
    """DRIVE_FIXED=3 本地硬盘；DRIVE_REMOVABLE=2 / DRIVE_REMOTE=4 网络映射盘 / DRIVE_CDROM=5。"""
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(d))
    except Exception:
        return 0

def _drive_writable(d: str) -> bool:
    """真实试写：在盘根建临时文件夹再删掉，成功才算可写（能识别出 Z: 这类只读共享映射盘）。"""
    try:
        probe = os.path.join(d, "_rb_write_probe_tmp")
        os.makedirs(probe, exist_ok=True)
        os.rmdir(probe)
        return True
    except OSError:
        return False

def list_writable_fixed_drives() -> list:
    """返回所有【可写、非 C、非网络、非光驱】的候选盘，按 本地固定硬盘优先 + 剩余空间从大到小 排序。
    兼容性设计（确保在其他电脑上也能检测到非C盘）：
      1. 枚举双保险：先 GetLogicalDrives 位图，异常时退化为 D~Z 逐盘探测；
      2. 同时接受 本地固定硬盘(DRIVE_FIXED=3) 与 USB移动硬盘(U盘/移动盘 DRIVE_REMOVABLE=2)；
      3. 硬性排除：网络映射盘(4，如只读共享Z:)、光驱(5)、RAM盘外不可读盘；
      4. 每个候选盘真实试写（建临时目录再删除），只读盘/BitLocker锁定盘自动淘汰。"""
    letters = []
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                letters.append(chr(65 + i))
    except Exception:
        letters = []
    if not letters:                     # 兜底：逐个盘符直接探测
        letters = list("DEFGHIJKLMNOPQRSTUVWXYZ")
    fixed, removable = [], []
    for L in letters:
        if L.upper() == "C":
            continue
        d = f"{L}:\\"
        if not os.path.isdir(d):
            continue
        t = _drive_type(d)
        if t == 4 or t == 5:            # 网络映射盘 / 光驱：一律淘汰
            continue
        try:
            free = shutil.disk_usage(d).free
        except OSError:
            continue
        if not _drive_writable(d):      # 只读盘（如Z:共享）真实试写不过：淘汰
            continue
        (fixed if t == 3 else removable).append((free, d))
    fixed.sort(reverse=True)
    removable.sort(reverse=True)
    return [d for _, d in fixed] + [d for _, d in removable]

def find_non_c_drive() -> str | None:
    """返回最合适的非 C 盘符（本地固定硬盘·可写·剩余空间最大，带末尾反斜杠），没有则 None。"""
    drives = list_writable_fixed_drives()
    return drives[0] if drives else None


# 预埋目录：运行时智能探测（可写非 C 盘 → ProgramData → %TEMP%）
# 改为懒计算：原版在 import 阶段就对每个盘符做真实试写探测，拖慢启动；
# 现在只有真正用到（通知/预埋/任务）时才探测一次并缓存。
_BOOTSTRAP_DIR = None

def get_bootstrap_dir() -> str:
    global _BOOTSTRAP_DIR
    if _BOOTSTRAP_DIR is None:
        _BOOTSTRAP_DIR = pick_bootstrap_dir()
    return _BOOTSTRAP_DIR

def get_flag_running_path() -> str:
    return os.path.join(get_bootstrap_dir(), "ResetRunning.flag")

def get_pbr_log_path() -> str:
    return os.path.join(get_bootstrap_dir(), "PBR_Reset_Log.txt")

def get_notify_target() -> str:
    return os.path.join(get_bootstrap_dir(), NOTIFY_EXE_NAME)

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except:
        return False

def elevate_self():
    """启动即向用户索取管理员权限（弹出 UAC 提权确认框）。
    - 已是管理员：直接放行；
    - 用户同意 UAC：本进程退出，由提权后的新进程接管；
    - 用户拒绝/失败：弹窗警告后仍以普通权限继续（迁移系统目录可能受限）。"""
    if is_admin():
        return
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv[1:])
        else:
            exe = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if ret > 32:            # UAC 已弹出且用户同意
            sys.exit(0)
        ctypes.windll.user32.MessageBoxW(
            None,
            "未获得管理员权限，继续运行可能导致：\n"
            "  · 系统目录文件无法复制/删除（拒绝访问）\n"
            "  · 部分迁移操作失败\n\n"
            "建议重新启动本软件并在弹出的权限框中点击【是】。",
            "C盘利刃 - 权限提示", 0x30)
    except Exception:
        pass  # 提权失败不阻断程序，按普通权限继续

def run_cmd(cmd: str):
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out + err

def check_winre() -> bool:
    ret, out = run_cmd("reagentc /info")
    if ret != 0:
        return False
    return ("Windows RE" in out or "Windows RE 位置" in out) and ("已启用" in out or "Enabled" in out)

def get_windows_ver() -> str:
    ret, out = run_cmd("ver")
    return out

def check_bitlocker() -> bool:
    ret, out = run_cmd("manage-bde C: -status")
    return ("Protection" in out and "On" in out) or ("保护方法" in out and "已开启" in out)

def is_domain_joined() -> bool:
    """是否已加入域。
    旧版跑 `systeminfo | findstr` —— 这条命令在部分机器上要 10~30 秒，且全程卡死界面。
    改用环境变量瞬时判定：已加域的机器 USERDOMAIN=域名，未加域（工作组）USERDOMAIN=计算机名。"""
    try:
        ud = os.environ.get("USERDOMAIN", "").strip()
        cn = os.environ.get("COMPUTERNAME", "").strip()
        if ud and cn and ud.upper() != cn.upper():
            return True
        return False
    except Exception:
        return False

def scan_c_non_system_files():
    # 系统档案基础设施：绝不能当"第三方残留"清理（删了会导致新建用户档案缺组件、公共目录损坏）
    clean_protected = (
        r"c:\users\default",        # 新用户模板档案（含 Default User 变体，前缀匹配一并保护）
        r"c:\users\public",         # 公共文件夹
        r"c:\users\all users",      # 公共 junction 别名
    )
    def _is_protected(p: str) -> bool:
        lp = p.lower().rstrip("\\")
        return any(lp == w or lp.startswith(w + "\\") for w in clean_protected)

    scan_results = []
    roots = [r"C:\Users", r"C:\Program Files", r"C:\Program Files (x86)"]
    for root in roots:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            skip = False
            for w in WHITE_LIST:
                if dirpath.startswith(w):
                    skip = True
                    break
            # Program Files 第一层：剔除 Windows 内置组件（深层子目录不套用，避免误伤
            # 形如 C:\Program Files\SomeApp\Windows 的第三方目录）
            if not skip and root.lower().startswith(r"c:\program files"):
                if os.path.relpath(dirpath, root) == ".":
                    dirnames[:] = [d for d in dirnames
                                   if not _is_pf_builtin(os.path.join(root, d))]
            if skip or _is_protected(dirpath):
                dirnames[:] = []
                continue
            scan_results.append(dirpath)
    for item in os.listdir("C:\\"):
        fullp = os.path.join("C:\\", item)
        if os.path.isdir(fullp) and not os.path.islink(fullp):
            if not any(fullp.startswith(w) for w in WHITE_LIST):
                # 系统根目录绝不整体 rmtree：其一 rmtree 撞到锁定文件会整体中止，
                # 其二这些树已由上面的递归扫描逐子目录覆盖（逐个删，失败不影响其余）。
                if fullp.lower() in (r"c:\windows", r"c:\users", r"c:\program files",
                                     r"c:\program files (x86)", r"c:\programdata", r"c:\perflogs"):
                    continue
                scan_results.append(fullp)
    return sorted(set(scan_results), key=lambda s: s.lower())

# 判定迁移风险等级：high=破坏系统/应用运行，safe=纯用户数据
CRITICAL_PREFIXES = [
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\Recovery",
    r"C:\Boot",
    r"C:\$Recycle.Bin",
    r"C:\System Volume Information",
]

def classify_risk(path: str) -> str:
    p = path.lower()
    for c in CRITICAL_PREFIXES:
        if p.startswith(c.lower()):
            return "high"
    # 用户配置目录根（C:\Users\<名> 或 C:\Users 本身）：整个用户档案含 AppData/注册表/
    # 运行中缓存，迁移必大量失败且可能损坏系统，禁止迁移
    if re.fullmatch(r"c:\\users(\\[^\\]+)?", p.rstrip("\\")):
        return "high"
    if "\\appdata" in p or "\\programdata" in p:
        return "high"
    return "safe"

# ===================== 快速扫描（限深 2 层，后台线程调用，避免全递归卡死） =====================
def _is_whitelisted_dir(path: str) -> bool:
    lp = path.lower().rstrip("\\")
    for w in WHITE_LIST:
        wl = w.lower().rstrip("\\")
        if lp == wl or lp.startswith(wl + "\\"):
            return True
    return False

def _is_reparse_dir(path: str) -> bool:
    """判断是否为重解析目录（junction 连接点 / 符号链接）。
    这类目录（如 C:\\Users\\xxx\\PrintHood、Recent、SendTo）自带拒绝访问 ACL，
    复制必报 WinError 5，且迁移它们毫无意义（只是个指向 别处的路标），扫描阶段直接排除。"""
    try:
        st = os.stat(path, follow_symlinks=False)
        return bool(getattr(st, "st_reparse_tag", 0))
    except OSError:
        return True      # 连 stat 都失败的目录一定迁不动，也排除

def _walk_depth(root: str, cur_depth: int, max_depth: int, out: list):
    """深度受限的目录遍历（用 scandir，不递归进入符号链接/junction），大幅缩短扫描耗时。"""
    if cur_depth > max_depth:
        return
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    p = entry.path
                    if _is_whitelisted_dir(p) or _is_reparse_dir(p):
                        continue
                    out.append(p)
                    _walk_depth(p, cur_depth + 1, max_depth, out)
    except (PermissionError, OSError):
        return

def scan_c_migratable_fast(max_depth: int = 2) -> list:
    """快速扫描可迁移目录：仅遍历有限层级（默认 2 层），不递归整个用户树，几乎瞬时完成。"""
    results = []
    try:
        for item in os.listdir("C:\\"):
            fullp = os.path.join("C:\\", item)
            if os.path.isdir(fullp) and not os.path.islink(fullp) and not _is_reparse_dir(fullp):
                if not _is_whitelisted_dir(fullp):
                    results.append(fullp)
    except (PermissionError, OSError):
        pass
    for root in (r"C:\Users", r"C:\Program Files", r"C:\Program Files (x86)"):
        if os.path.exists(root):
            _walk_depth(root, 0, max_depth, results)
    return sorted(set(results), key=lambda s: s.lower())

class ScanWorker(QThread):
    progress = pyqtSignal(str)
    scan_done = pyqtSignal(list, int)   # (路径列表, 高危数量)
    error = pyqtSignal(str)

    def __init__(self, max_depth: int = 2):
        super().__init__()
        self.max_depth = max_depth

    def run(self):
        try:
            self.progress.emit("正在后台扫描 C 盘可迁移目录（界面可正常操作）...")
            paths = scan_c_migratable_fast(self.max_depth)
            high = sum(1 for p in paths if classify_risk(p) == "high")
            self.scan_done.emit(paths, high)
        except Exception as e:
            self.error.emit(str(e))

class SizeCalcWorker(QThread):
    """后台计算选中目录总大小，避免选大目录时界面卡顿。"""
    done = pyqtSignal(int)

    def __init__(self, paths: list):
        super().__init__()
        self.paths = paths
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = 0
        for p in self.paths:
            if self._stop:
                break
            total += get_folder_size(p, stop_check=lambda: self._stop)
        self.done.emit(total)


class PrecheckWorker(QThread):
    """C盘初始化预检（BitLocker / 域环境 / 系统版本）后台线程。
    旧版在按钮点击回调里同步跑 manage-bde / systeminfo，一卡就是几秒到几十秒。"""
    done = pyqtSignal(bool, bool, str)   # (bitlocker_on, domain_joined, ver_text)

    def run(self):
        try:
            bit = check_bitlocker()
        except Exception:
            bit = False
        try:
            dom = is_domain_joined()
        except Exception:
            dom = False
        try:
            ver = get_windows_ver().strip()
        except Exception:
            ver = "未知"
        self.done.emit(bool(bit), bool(dom), ver)


class ShortcutWorker(QThread):
    """启动后后台跑一次「资源守卫」：受管资源缺失则自动补回（下次启动生效），
    在位则跳过、被用户改过则不覆盖。放后台是因为补回要起 COM，会冻结启动界面 1~3 秒。"""
    def run(self):
        try:
            run_resource_guardian("startup")
        except Exception:
            pass

def get_installed_software():
    """枚举已安装的 MSI 软件 [(DisplayName, ProductCode)]。
    旧版用 WMI Win32_Product：枚举一次普遍 30~60 秒，还会触发 MSI 安装包自检/自修复，
    界面干等一分钟且可能弹出修复框。改为直接读注册表卸载项，毫秒级返回，
    只取 GUID 形式的 MSI 安装项，与旧版 msiexec /x 调用方式完全兼容。"""
    sw_list = []
    seen = set()
    uninstall_roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, path in uninstall_roots:
        try:
            with winreg.OpenKey(hive, path) as key:
                sub_count = winreg.QueryInfoKey(key)[0]
                for i in range(sub_count):
                    try:
                        sub = winreg.EnumKey(key, i)
                    except OSError:
                        continue
                    if not (sub.startswith("{") and sub.endswith("}")):
                        continue          # 只保留 MSI 安装项（GUID 子键名）
                    if sub.lower() in seen:
                        continue
                    try:
                        with winreg.OpenKey(key, sub) as ik:
                            try:
                                name, _ = winreg.QueryValueEx(ik, "DisplayName")
                            except OSError:
                                continue
                            try:
                                syscomp, _ = winreg.QueryValueEx(ik, "SystemComponent")
                                if syscomp:
                                    continue      # 隐藏的组件/更新项，不出现在软件列表
                            except OSError:
                                pass
                    except OSError:
                        continue
                    name = str(name).strip()
                    if not name:
                        continue
                    seen.add(sub.lower())
                    sw_list.append((name, sub))
        except OSError:
            continue
    return sw_list


# ===================== C盘初始化：后台清理（不卡界面 + 可取消 + 实时进度 + 极速 rd /s /q） =====================
def plan_clean_targets():
    """快速规划「本次将删除」的顶层目标（只列顶层，不做深度递归，毫秒级）。
    保护规则：
      - C:\\Users 下除 Default/Public/All Users/Default User 外的所有用户档案（整树删）；
      - C:\\Program Files 与 (x86) 下：除 WHITE_LIST 条目外，
        **还排除 Windows 内置组件**（见 _is_pf_builtin，例如 Internet Explorer / Windows NT /
        WindowsPowerShell / Windows Defender / Windows Media Player / Common Files 等）。
        理由：这些组件被删后系统自身重置（PBR / WinRE）会失败或产出残废系统，
        与「C盘初始化」的目标（清个人数据 + 卸载第三方软件）不符。
      - C:\\ 根下除系统根目录与 WHITE_LIST 外的所有目录。"""
    clean_protected = (
        r"c:\users\default",
        r"c:\users\public",
        r"c:\users\all users",
        r"c:\users\default user",
    )
    sys_roots = {r"c:\windows", r"c:\users", r"c:\program files",
                 r"c:\program files (x86)", r"c:\programdata", r"c:\perflogs",
                 r"c:\documents and settings"}

    def _protected(p: str) -> bool:
        lp = p.lower().rstrip("\\")
        return any(lp == w or lp.startswith(w + "\\") for w in clean_protected)

    targets = []
    try:
        for name in os.listdir(r"C:\Users"):
            p = os.path.join(r"C:\Users", name)
            if _protected(p):
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                targets.append(p)
    except Exception:
        pass
    # 注意：下面两个循环原本缩进在 Users 循环的 except 里，只有 C:\Users 列举失败时才会执行，
    # 导致正常情况下 Program Files 下的第三方软件目录漏扫。现修正为独立分支。
    for root in (r"C:\Program Files", r"C:\Program Files (x86)"):
        if not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                p = os.path.join(root, name)
                # 只收目录：rd /s /q 对文件无效，混进来只会产生无意义的日志
                if not os.path.isdir(p) or os.path.islink(p):
                    continue
                if any(p.lower().startswith(w.lower()) for w in WHITE_LIST):
                    continue
                # 只删第三方软件目录，Windows 内置组件一律保留（否则系统重置会失败）
                if _is_pf_builtin(p):
                    continue
                targets.append(p)
        except Exception:
            pass
    try:
        for name in os.listdir("C:\\"):
            p = os.path.join("C:\\", name)
            if os.path.isdir(p) and not os.path.islink(p):
                lp = p.lower()
                if lp in sys_roots:
                    continue
                if any(p.lower().startswith(w.lower()) for w in WHITE_LIST):
                    continue
                targets.append(p)
    except Exception:
        pass
    return sorted(set(targets), key=lambda s: s.lower())


class CleanWorker(QThread):
    progress_update = pyqtSignal(int, str)   # (百分比, 当前项文本)
    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(bool, str)  # (是否取消, 摘要)

    def __init__(self, targets):
        super().__init__()
        self.targets = targets
        self.before = 0
        self.after = 0
        self._stop = False

    def stop(self):
        self._stop = True

    @staticmethod
    def _fast_rmdir(path: str):
        """最快删除：优先系统 rd /s /q，失败回退 Python rmtree。"""
        try:
            subprocess.run(f'rd /s /q "{path}"', shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        except Exception:
            pass
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)

    def run(self):
        self.before = c_drive_usage()[2]
        self.log_signal.emit(f"===== 开始 C盘初始化（文件清理）===== 共 {len(self.targets)} 个顶层目标", "blue")
        # 阶段1：卸载第三方软件（msiexec 静默，后台不卡界面）
        try:
            sw = get_installed_software()
        except Exception:
            sw = []
        self.log_signal.emit(f"扫描到 {len(sw)} 个第三方软件，开始卸载", "blue")
        for name, idc in sw:
            if self._stop:
                break
            try:
                run_cmd(f'msiexec /x "{idc}" /qn')
                self.log_signal.emit(f"成功卸载：{name}", "green")
            except Exception as e:
                self.log_signal.emit(f"卸载失败：{name} | {e}", "red")
        # 阶段2：删除目标（rd /s /q 极快，每个目标之间可取消）
        total = len(self.targets)
        for i, fp in enumerate(self.targets):
            if self._stop:
                self.log_signal.emit("⏹ 用户已取消，停止清理（已处理项已删除，未处理项保留）", "gray")
                break
            try:
                if os.path.isdir(fp) and not os.path.islink(fp):
                    self._fast_rmdir(fp)
                elif os.path.isfile(fp):
                    os.remove(fp)
                self.log_signal.emit(f"已删除：{fp}", "green")
            except Exception as e:
                self.log_signal.emit(f"删除失败（保留）：{fp} | {e}", "red")
            pct = int(((i + 1) / total) * 100) if total else 100
            self.progress_update.emit(pct, fp)
        self.after = c_drive_usage()[2]
        delta = self.after - self.before
        if self._stop:
            self.finished_signal.emit(True, f"已取消 | 当前可用 {bytes_human(self.after)}")
        else:
            self.progress_update.emit(100, "完成")
            self.finished_signal.emit(
                False,
                (f"已释放 {bytes_human(delta)}" if delta >= 0 else f"可用反而减少 {bytes_human(-delta)}"))


# ===================== 迁移线程 =====================
# Windows 运行期间必然被系统独占锁定的文件（注册表配置单元 / 搜索/Web缓存数据库等）。
# 这类文件任何程序都无法复制（Errno 13 拒绝访问），遇到时智能跳过且【不算迁移失败】。
LOCKED_FILE_KEYWORDS = ("usrclass.dat", "ntuser.dat", "webcache")


class MigrateWorker(QThread):
    progress_update = pyqtSignal(int, str)
    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(bool)

    # 复制块大小：原 1MB 改为 8MB，减少 Python 层循环次数（大文件迁移显著更快）
    CHUNK_SIZE = 8 * 1024 * 1024
    # 进度信号最小间隔（毫秒）：原版每 1MB 发一次信号，10GB 文件 = 上万次跨线程信号 +
    # 界面重绘，直接把 UI 打爆。100ms 节流后视觉上仍是实时进度条。
    PROGRESS_INTERVAL_MS = 100

    def __init__(self, src_list, target_root, total_bytes):
        super().__init__()
        self.src_list = src_list
        self.target_root = target_root
        self.total_bytes = total_bytes
        self.copied_bytes = 0
        self.skipped_locked = 0
        self._stop = False
        self._emit_timer = QElapsedTimer()
        self._made_dirs = set()

    def stop(self):
        self._stop = True

    def _ensure_dir(self, d: str):
        """带缓存的建目录：同一目录下的连续文件只付一次系统调用。"""
        if d not in self._made_dirs:
            os.makedirs(d, exist_ok=True)
            self._made_dirs.add(d)

    def copy_file_with_progress(self, src_file, dst_file):
        """返回 'ok' / 'skip'（系统占用/重解析，不算失败）/ 'fail'（真失败，计入目录失败）。"""
        try:
            self._ensure_dir(os.path.dirname(dst_file))
            with open(src_file, "rb") as fsrc, open(dst_file, "wb") as fdst:
                while chunk := fsrc.read(self.CHUNK_SIZE):
                    if self._stop:
                        return "stop"
                    fdst.write(chunk)
                    self.copied_bytes += len(chunk)
                    if self._emit_timer.elapsed() >= self.PROGRESS_INTERVAL_MS:
                        self._emit_timer.restart()
                        pct = int((self.copied_bytes / self.total_bytes) * 100) if self.total_bytes > 0 else 0
                        self.progress_update.emit(pct, src_file)
            # 文件收尾：无论节流与否都刷新一次最终进度（小文件占比高时进度条也实时）
            self._emit_timer.restart()
            pct = int((self.copied_bytes / self.total_bytes) * 100) if self.total_bytes > 0 else 0
            self.progress_update.emit(pct, src_file)
            return "ok"
        except OSError as e:
            errno = e.errno
            if errno in (13, 5, 22, 32):
                # 拒绝访问/共享冲突/无效参数/占用：系统运行中锁死或重解析文件，任何工具都拷不动，
                # 静默跳过（只计数，不刷屏），源目录将因此保留，绝不丢数据
                self.skipped_locked += 1
                return "skip"
            self.log_signal.emit(f"文件复制失败（跳过）：{src_file} : {e}", "red")
            return "fail"
        except Exception as e:
            self.log_signal.emit(f"文件复制异常（跳过）：{src_file} : {str(e)}", "red")
            return "fail"

    def copy_dir_recursive(self, src_dir, dst_dir) -> bool:
        """复制目录树（迭代式：先展开全树再逐目录复制，深目录不会爆 Python 递归上限）。
        单个文件失败：继续复制其余内容。只要有真失败（非系统占用跳过）就返回 False。"""
        # 1) 迭代展开目录树
        dirs = []          # [(src_dir, entries)]
        stack = [src_dir]
        expand_failed = False   # 有任何目录读不出（权限/占用）：与旧版一致按失败处理，保留源目录
        while stack:
            cur = stack.pop()
            try:
                entries = list(os.scandir(cur))
            except OSError:
                self.skipped_locked += 1
                expand_failed = True
                continue
            dirs.append((cur, entries))
            for e in entries:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False) and not _is_reparse_dir(e.path):
                        stack.append(e.path)
                except OSError:
                    continue
        # 2) 逐目录复制（父目录先建，子目录文件随后，顺序无关）
        all_ok = not expand_failed
        for cur_src, entries in dirs:
            if self._stop:
                return False
            rel = os.path.relpath(cur_src, src_dir)
            cur_dst = dst_dir if rel == "." else os.path.join(dst_dir, rel)
            self._ensure_dir(cur_dst)
            for entry in entries:
                if self._stop:
                    return False
                src_p = entry.path
                dst_p = os.path.join(cur_dst, entry.name)
                try:
                    # 跳过符号链接 / junction 连接点（复制它们只会报拒绝访问，且没有意义）
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        continue          # 子目录已在阶段1展开，这里只处理文件
                    nm = entry.name.lower()
                    if nm.startswith(LOCKED_FILE_KEYWORDS):
                        # 注册表配置单元/WebCache 等系统独占文件：跳过且不算失败
                        self.skipped_locked += 1
                        continue
                    if _is_reparse_dir(src_p):
                        # WindowsApps 应用执行别名等重解析文件：0字节路标，静默排除
                        continue
                    st = self.copy_file_with_progress(src_p, dst_p)
                    if st == "stop":
                        return False
                    if st == "fail":
                        all_ok = False
                except OSError:
                    self.skipped_locked += 1
        return all_ok

    def run(self):
        self._emit_timer.start()
        all_ok = True
        ok_cnt, keep_cnt, fail_cnt = 0, 0, 0
        for src in self.src_list:
            if self._stop:
                break
            base_name = os.path.basename(src)
            dst_folder = os.path.join(self.target_root, base_name)
            self.log_signal.emit(f"开始迁移目录：{src} -> {dst_folder}", "black")
            before = self.skipped_locked
            try:
                res = self.copy_dir_recursive(src, dst_folder)
            except Exception as e:
                self.log_signal.emit(f"❌ 迁移异常 {src} : {str(e)}", "red")
                res = False
            if self._stop:
                self.log_signal.emit("⏹ 迁移任务被手动终止", "gray")
                all_ok = False
                break
            delta = self.skipped_locked - before
            if res and delta == 0:
                try:
                    force_rmtree(src)
                    ok_cnt += 1
                    self.log_signal.emit(f"✅ 迁移完成：{src}", "green")
                except Exception as e:
                    keep_cnt += 1
                    self.log_signal.emit(f"⚠️ 内容已复制到目标，但源目录删除失败（源已保留）：{src}", "red")
                    all_ok = False
            elif res and delta > 0:
                # 内容全部复制，但源目录含系统占用文件（注册表/缓存等，复制时被锁跳过）
                # 这类文件同样无法删除：保留源目录，绝不静默丢数据
                keep_cnt += 1
                self.log_signal.emit(f"✔ 内容已复制到目标；源目录含 {delta} 个系统占用文件无法删除，源已保留：{src}", "gray")
            else:
                fail_cnt += 1
                self.log_signal.emit(f"⚠️ 部分内容未能复制（详见上方红色日志），源目录已完整保留：{src}", "red")
                all_ok = False
        self.log_signal.emit(
            f"===== 迁移总结：✅ 完全迁移 {ok_cnt} 个 | ✔ 已复制但源保留(系统占用文件) {keep_cnt} 个 | ❌ 失败 {fail_cnt} 个（源已保留） =====",
            "black")
        self.finished_signal.emit(all_ok)

# ===================== Junction 目录链接搬家（缓存搬家） =====================
# 为什么用 junction 而不是"复制走就完事"：
#   微信/QQ/QQ音乐这类应用，缓存目录路径是写死的，你把目录删了/搬走了，它下次启动会
#   在 C 盘原地重建一份，空间白释放。junction（NTFS 目录连接点）对应用程序完全透明：
#   实体搬到 D 盘、C 盘原位留一个"传送门"，应用照旧往原路径写，实际落到 D 盘。
# 执行顺序（任何一步失败都保证数据不丢）：
#   复制 -> 文件数校验 -> 删源 -> 原位建链接 -> 写探针文件验证穿透
# 源目录被占用（应用没关）删不掉时：内容已复制但保留源，提示关闭应用后点"继续完成"。
JUNCTION_STATE_FILE = os.path.join(os.path.expandvars("%APPDATA%"), "ResetBlade", "junction_state.json")
CUSTOM_RULES_FILE = os.path.join(os.path.expandvars("%APPDATA%"), "ResetBlade", "cache_rules.json")


def is_junction(path: str) -> bool:
    """是否是目录链接（junction / 符号链接目录）。"""
    try:
        st = os.stat(path, follow_symlinks=False)
        if not getattr(st, "st_reparse_tag", 0):
            return False
        return os.path.isdir(path)
    except OSError:
        return False


def read_junction_target(path: str) -> str | None:
    """读取链接指向的真实目录；不是链接返回 None。"""
    if not is_junction(path):
        return None
    try:
        t = os.readlink(path)
    except OSError:
        return None
    if t.startswith("\\\\?\\"):
        t = t[4:]
    return os.path.normpath(t)


def _junction_via_api(link: str, target: str):
    """用 DeviceIoControl(FSCTL_SET_REPARSE_POINT) 直接建 junction：
    不需要管理员、不走 cmd（避免中文路径代码页问题）。link 必须已存在且为空目录。"""
    import struct
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CreateFileW = k32.CreateFileW
        CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        CreateFileW.restype = ctypes.c_void_p
        DeviceIoControl = k32.DeviceIoControl
        DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        DeviceIoControl.restype = ctypes.c_int32
        CloseHandle = k32.CloseHandle
        CloseHandle.argtypes = [ctypes.c_void_p]

        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x00000001
        OPEN_EXISTING = 3
        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
        FSCTL_SET_REPARSE_POINT = 0x000900A4
        IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003

        t = os.path.abspath(target)
        subst = "\\??\\" + t
        sub_b = subst.encode("utf-16-le") + b"\x00\x00"
        prn_b = t.encode("utf-16-le") + b"\x00\x00"
        rdlen = 8 + len(sub_b) + len(prn_b)
        header = struct.pack("<IHHHHHH", IO_REPARSE_TAG_MOUNT_POINT, rdlen, 0,
                             0, len(sub_b) - 2, len(sub_b), len(prn_b) - 2)
        data = header + sub_b + prn_b
        # 关键：必须显式给长度，否则 create_string_buffer 会多补一个 NUL，
        # nInBufferSize 多 1 字节，I/O 管理器校验直接报 WinError 4392
        buf = ctypes.create_string_buffer(data, len(data))

        h = CreateFileW(link, GENERIC_WRITE, FILE_SHARE_READ, None, OPEN_EXISTING,
                        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None)
        if h is None or (isinstance(h, int) and (h == -1 or h >= 0xFFFFFFFF)):
            return False, f"打开目录句柄失败(WinError {ctypes.get_last_error()})"
        try:
            returned = ctypes.c_uint32(0)
            ok = DeviceIoControl(h, FSCTL_SET_REPARSE_POINT, buf, len(buf),
                                 None, 0, ctypes.byref(returned), None)
            if not ok:
                return False, f"设置重解析点失败(WinError {ctypes.get_last_error()})"
            return True, "ok"
        finally:
            CloseHandle(h)
    except Exception as e:
        return False, f"API 异常: {e}"


def _junction_via_mklink(link: str, target: str):
    """回退方案：cmd 的 mklink /J（普通用户权限即可，不需要管理员）。"""
    try:
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode == 0:
            return True, "ok"
        return False, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return False, str(e)


def create_junction(link: str, target: str):
    """在 link 位置建立指向 target 的 junction。link 可以是已存在的空目录，也可以不存在。"""
    # 护栏：链接位置必须为空（或不存在），非空目录上建链接会把里面的数据"藏起来"
    try:
        if os.path.isdir(link) and os.listdir(link):
            return False, "链接位置目录非空，拒绝创建（避免把数据封在链接下面）"
    except OSError:
        return False, "无法检查链接位置"
    ok, msg = _junction_via_api(link, target)
    if ok:
        return True, "ok"
    # mklink /J 要求链接位置不能已存在：是空目录就先移走再试
    try:
        if os.path.isdir(link) and not os.listdir(link):
            os.rmdir(link)
    except OSError:
        pass
    ok2, msg2 = _junction_via_mklink(link, target)
    if ok2:
        return True, "ok(mklink 回退)"
    return False, f"{msg} || mklink: {msg2}"


def remove_junction(path: str):
    """只删链接本身，绝不动目标目录里的内容。悬空链接（目标已消失）也能删。"""
    try:
        st = os.stat(path, follow_symlinks=False)
        if not getattr(st, "st_reparse_tag", 0):
            return False, "不是目录链接"
    except OSError:
        return False, "不是目录链接（或已不存在）"
    try:
        os.rmdir(path)          # 对 junction 有效，不会递归删除目标
        return True, "ok"
    except OSError as e:
        try:
            r = subprocess.run(["cmd", "/c", "rmdir", path], capture_output=True,
                               text=True, encoding="utf-8", errors="ignore")
            if r.returncode == 0:
                return True, "ok(rmdir 回退)"
            return False, f"{e} || rmdir: {(r.stdout or '') + (r.stderr or '')}"
        except Exception as e2:
            return False, f"{e} || {e2}"


def count_files(path: str) -> int:
    n = 0
    for _, _, fs in os.walk(path):
        n += len(fs)
    return n


def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip() or "cache"


# ---- 会产生缓存的应用规则库（可扩展；用户自定义项会持久化到 cache_rules.json） ----
# detect : 命中任一即认为该应用已安装
# dirs   : 它的缓存/数据目录（支持 %APPDATA% 等环境变量）
CACHE_APP_RULES = [
    {"id": "wechat", "name": "微信 WeChat",
     "detect": [r"%APPDATA%\Tencent\WeChat", r"%USERPROFILE%\Documents\WeChat Files"],
     "dirs": [r"%APPDATA%\Tencent\WeChat\Cache",
              r"%APPDATA%\Tencent\WeChat\FileStorage",
              r"%USERPROFILE%\Documents\WeChat Files"]},
    {"id": "qq", "name": "QQ",
     "detect": [r"%APPDATA%\Tencent\QQ", r"%USERPROFILE%\Documents\Tencent Files"],
     "dirs": [r"%APPDATA%\Tencent\QQ\Misc",
              r"%USERPROFILE%\Documents\Tencent Files"]},
    {"id": "qqmusic", "name": "QQ音乐",
     "detect": [r"%APPDATA%\Tencent\QQMusic", r"%LOCALAPPDATA%\Tencent\QQMusic"],
     "dirs": [r"%APPDATA%\Tencent\QQMusic\Cache",
              r"%LOCALAPPDATA%\Tencent\QQMusic\Cache"]},
    {"id": "wxwork", "name": "企业微信 WXWork",
     "detect": [r"%APPDATA%\Tencent\WXWork", r"%USERPROFILE%\Documents\WXWork"],
     "dirs": [r"%APPDATA%\Tencent\WXWork\Cache",
              r"%USERPROFILE%\Documents\WXWork"]},
    {"id": "dingtalk", "name": "钉钉 DingTalk",
     "detect": [r"%APPDATA%\DingTalk"],
     "dirs": [r"%APPDATA%\DingTalk"]},
    {"id": "cloudmusic", "name": "网易云音乐",
     "detect": [r"%LOCALAPPDATA%\Netease\CloudMusic"],
     "dirs": [r"%LOCALAPPDATA%\Netease\CloudMusic\Cache"]},
    {"id": "chrome", "name": "Chrome 浏览器缓存",
     "detect": [r"%LOCALAPPDATA%\Google\Chrome\User Data"],
     "dirs": [r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache"]},
    {"id": "edge", "name": "Edge 浏览器缓存",
     "detect": [r"%LOCALAPPDATA%\Microsoft\Edge\User Data"],
     "dirs": [r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache"]},
    {"id": "baidunetdisk", "name": "百度网盘",
     "detect": [r"%APPDATA%\baidu\BaiduNetdisk"],
     "dirs": [r"%APPDATA%\baidu\BaiduNetdisk"]},
    {"id": "thunder", "name": "迅雷",
     "detect": [r"%APPDATA%\Thunder Network"],
     "dirs": [r"%APPDATA%\Thunder Network\Xmp"]},
]

# 缓存搬家：绝对禁止碰的目录（搬家=删源+建链接，误操作代价太大）
# 子树全禁：系统与程序目录，下面任何东西都不许动
JUNCTION_FORBIDDEN_SUBTREE = (r"c:\windows", r"c:\program files", r"c:\program files (x86)")
# 仅根禁：这些目录的"根"是系统约定路径不许动，但其下的应用缓存子目录允许搬家
JUNCTION_FORBIDDEN_EXACT = (r"c:\users", r"c:\programdata", r"c:\$recycle.bin",
                            r"c:\system volume information", r"c:\boot", r"c:\recovery")


def junction_forbidden(path: str) -> bool:
    p = os.path.abspath(os.path.expandvars(path)).lower().rstrip("\\")
    if not p.startswith("c:"):
        return True
    for f in JUNCTION_FORBIDDEN_SUBTREE:
        if p == f or p.startswith(f + "\\"):
            return True
    if p in JUNCTION_FORBIDDEN_EXACT:
        return True
    # C 盘根目录直属文件夹（如 C:\inetpub、C:\PerfLogs）不放行：它们是系统/服务约定路径
    return os.path.dirname(p).rstrip("\\").lower() == "c:"


def _expand(p: str) -> str:
    return os.path.normpath(os.path.expandvars(p))


def detect_cache_apps(extra_rules: list | None = None) -> list:
    """检测本机已安装的、会产生缓存的应用及其缓存目录。
    返回 [{'app':名称, 'src':目录, 'exists':bool, 'size':int, 'junction':bool, 'target':str|None}]"""
    rules = list(CACHE_APP_RULES) + list(extra_rules or [])
    out, seen = [], set()
    for r in rules:
        detect = [_expand(d) for d in r.get("detect", [])]
        if detect and not any(os.path.exists(d) for d in detect):
            continue                       # 应用没装，整条跳过
        for d in r.get("dirs", []):
            p = _expand(d)
            if p.lower() in seen:
                continue
            seen.add(p.lower())
            ex = os.path.exists(p)
            if is_junction(p):
                out.append({"app": r["name"], "src": p, "exists": True, "size": 0,
                            "junction": True, "target": read_junction_target(p)})
            elif ex:
                out.append({"app": r["name"], "src": p, "exists": True, "size": 0,
                            "junction": False, "target": None})
    return out


class JunctionScanWorker(QThread):
    """后台检测 + 计算缓存目录体积（避免大目录卡界面）。"""
    item = pyqtSignal(str, int, bool, str)      # (src, size, junction, target)
    finished_all = pyqtSignal()

    def __init__(self, extra_rules: list | None = None):
        super().__init__()
        self.extra_rules = extra_rules
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            for it in detect_cache_apps(self.extra_rules):
                if self._stop:
                    break
                size = 0
                if not it["junction"]:
                    try:
                        size = get_folder_size(it["src"], stop_check=lambda: self._stop)
                    except OSError:
                        size = 0
                self.item.emit(it["src"], size, it["junction"], it["target"] or "")
        finally:
            self.finished_all.emit()


class JunctionWorker(QThread):
    """缓存搬家执行线程：复制 -> 校验 -> 删源 -> 建链接 -> 探针验证。
    支持 mode='move'（搬家建链接）/ 'revert'（还原） / 'finish'（源删不掉时的续做）。"""
    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(int, int)     # (成功数, 失败数)

    def __init__(self, items: list, dst_root: str, mode: str = "move"):
        super().__init__()
        self.items = items          # [{'app':..,'src':..,'dst':..}]
        self.dst_root = dst_root
        self.mode = mode
        self._stop = False

    def stop(self):
        self._stop = True

    def log(self, msg, color="black"):
        self.log_signal.emit(str(msg), color)

    # ---------- 复制（跳过被占用文件，不算失败） ----------
    def _copy_tree(self, src, dst):
        os.makedirs(dst, exist_ok=True)
        skipped = 0
        for root, dirs, files in os.walk(src):
            if self._stop:
                return False, skipped
            rel = os.path.relpath(root, src)
            dst_dir = dst if rel == "." else os.path.join(dst, rel)
            os.makedirs(dst_dir, exist_ok=True)
            for d in list(dirs):
                if os.path.islink(os.path.join(root, d)):
                    dirs.remove(d)
            for f in files:
                s = os.path.join(root, f)
                t = os.path.join(dst_dir, f)
                if os.path.islink(s):
                    continue
                try:
                    shutil.copy2(s, t)
                except OSError as e:
                    if e.errno in (13, 5, 22, 32):
                        skipped += 1          # 应用运行中锁定，静默跳过
                        continue
                    self.log(f"  复制失败（跳过）：{s} : {e}", "red")
                    skipped += 1
        return True, skipped

    def _do_move(self, it):
        src, dst = it["src"], it["dst"]
        app = it.get("app", "")
        if is_junction(src):
            self.log(f"⊙ 已是目录链接，跳过：{src} -> {read_junction_target(src)}", "gray")
            return "skip"
        if junction_forbidden(src):
            self.log(f"❌ 受保护目录，拒绝搬家：{src}", "red")
            return "fail"
        if not os.path.isdir(src):
            self.log(f"❌ 源目录不存在：{src}", "red")
            return "fail"
        if os.path.abspath(dst).lower().startswith(os.path.abspath(src).lower()):
            self.log(f"❌ 目标不能在源目录内部：{dst}", "red")
            return "fail"

        already = os.path.isdir(dst)
        if already:
            self.log(f"ℹ 目标已存在（上次已复制），直接进入删源+建链接：{dst}", "gray")
        else:
            size = get_folder_size(src)
            free = get_disk_free(os.path.splitdrive(dst)[0] + "\\") if os.path.splitdrive(dst)[0] else 0
            if free and size > free:
                self.log(f"❌ 目标盘空间不足（需 {bytes_human(size)}，可用 {bytes_human(free)}）：{src}", "red")
                return "fail"
            self.log(f"▶ [{app}] 复制 {src} → {dst}（{bytes_human(size)}）", "black")
            ok, skipped = self._copy_tree(src, dst)
            if self._stop:
                return "fail"
            if not ok:
                self.log(f"❌ 复制中断：{src}", "red")
                return "fail"
            n_src, n_dst = count_files(src), count_files(dst)
            if n_dst < n_src - skipped:
                self.log(f"❌ 文件数校验失败（源 {n_src} → 目标 {n_dst}，跳过 {skipped}），保留源目录：{src}", "red")
                return "fail"
            self.log(f"  复制完成（{n_dst} 文件，跳过占用 {skipped} 个）", "green")

        # 删源（应用没关的时候这里会失败）
        try:
            force_rmtree(src)
        except Exception as e:
            self.log(f"⚠ 源目录无法删除（多半是应用正在运行，请先退出 {app}）：{src}", "red")
            self.log(f"  内容已搬到 {dst}，关闭应用后重新点【开始搬家】即可建链接（数据不会丢）", "gray")
            return "pending"
        try:
            os.makedirs(src, exist_ok=True)
            ok, msg = create_junction(src, dst)
            if not ok:
                # 建链接失败：把内容倒回源，绝不留下"源没了/链接也没有"的悬空状态
                self.log(f"❌ 建立目录链接失败：{msg}", "red")
                self.log(f"  正在把内容回退到原位置：{dst} → {src}", "gray")
                shutil.rmtree(src, ignore_errors=True)
                self._copy_tree(dst, src)
                return "fail"
        except Exception as e:
            self.log(f"❌ 建链接异常：{e}", "red")
            return "fail"

        # 探针验证：往原路径写文件，看是否真的落到目标盘
        probe = os.path.join(src, "__rb_probe.tmp")
        try:
            with open(probe, "wb") as f:
                f.write("C盘利刃".encode("utf-8"))
            landed = os.path.exists(os.path.join(dst, "__rb_probe.tmp"))
            os.remove(probe)
            if landed:
                self.log(f"✅ [{app}] 搬家完成并验证穿透：{src} → {dst}", "green")
                return "ok"
            self.log(f"❌ 链接未生效（写入未落到目标盘）：{src}", "red")
            return "fail"
        except Exception as e:
            self.log(f"❌ 探针验证失败：{e}", "red")
            return "fail"

    def _do_revert(self, it):
        src = it["src"]
        if not is_junction(src):
            self.log(f"⊙ 不是目录链接，无需还原：{src}", "gray")
            return "skip"
        target = read_junction_target(src)
        if not target or not os.path.isdir(target):
            self.log(f"❌ 链接目标不存在，放弃还原：{src}", "red")
            return "fail"
        self.log(f"▶ 还原 {src} ← {target}", "black")
        tmp = src + "__rb_tmp"
        if os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        ok, skipped = self._copy_tree(target, tmp)
        if not ok:
            return "fail"
        ok2, msg = remove_junction(src)
        if not ok2:
            self.log(f"❌ 删除链接失败：{msg}", "red")
            shutil.rmtree(tmp, ignore_errors=True)
            return "fail"
        try:
            os.rename(tmp, src)
        except Exception:
            os.makedirs(src, exist_ok=True)
            self._copy_tree(tmp, src)
            shutil.rmtree(tmp, ignore_errors=True)
        n_src, n_tgt = count_files(src), count_files(target)
        if n_src < n_tgt:
            self.log(f"⚠ 还原后文件数偏少（{n_src} < {n_tgt}），目标目录已保留未删除：{target}", "red")
            return "fail"
        try:
            shutil.rmtree(target)
        except Exception as e:
            self.log(f"⚠ 还原成功，但目标目录删除失败（可手动删除）：{target} : {e}", "red")
        self.log(f"✅ 已还原为真实目录：{src}", "green")
        return "ok"

    def run(self):
        ok_n = fail_n = 0
        # 防撞车：两个目录不许搬到同一个目标（否则后搬的会把先搬的覆盖掉）
        seen_dst = {}
        for it in self.items:
            d = os.path.abspath(it["dst"]).lower() if it.get("dst") else ""
            if d and d in seen_dst:
                self.log(f"❌ 目标目录重复（{seen_dst[d]} 也要搬到 {it['dst']}），跳过：{it['src']}", "red")
                fail_n += 1
                continue
            if d:
                seen_dst[d] = it["src"]
        for it in self.items:
            if self._stop:
                self.log("⏹ 任务被终止", "gray")
                break
            d = os.path.abspath(it["dst"]).lower() if it.get("dst") else ""
            if d and seen_dst.get(d, it["src"]) != it["src"]:
                continue          # 重复目标，上面已计失败
            try:
                r = self._do_revert(it) if self.mode == "revert" else self._do_move(it)
            except Exception as e:
                self.log(f"❌ 异常：{e}", "red")
                r = "fail"
            if r == "ok":
                ok_n += 1
            elif r == "fail":
                fail_n += 1
        self.log(f"===== 缓存搬家总结：✅ 成功 {ok_n} | ❌ 失败/待完成 {fail_n} =====", "black")
        self.finished_signal.emit(ok_n, fail_n)


# ===================== C 盘空间变化报告弹窗 =====================
class CapacityResultDialog(GlassDialog):
    """操作完成后弹出：C 盘操作前/后可用空间 + 实测差值。
    所有数字均由系统实时查询（shutil.disk_usage）得出，不做任何估算/美化；
    若期间有其他程序写入，差值会如实反映（必要时显示为负数），绝不虚构"已释放"。"""

    def __init__(self, parent=None, title="C 盘空间变化报告", before=0, after=0,
                 moved_bytes=0, detail="", dark=False, show_moved=True):
        super().__init__(parent, dark)
        self.setWindowTitle(title)
        self.resize(560, 320)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        t = QLabel(f"📊 {title}")
        t.setStyleSheet("font-size:16px;font-weight:bold;")
        lay.addWidget(t)

        total, _used, _free = c_drive_usage()
        delta = after - before
        up = delta >= 0
        color = "#1e8449" if up else "#c0392b"

        rows = [
            ("C 盘总容量", bytes_human(total) if total else "—"),
            ("操作前可用空间", bytes_human(before) if before else "—"),
            ("操作后可用空间", bytes_human(after) if after else "—"),
            (f"实测{'释放' if up else '占用'}", f"{'+' if up else '-'}{bytes_human(abs(delta))}"
             + ("（C 盘可用空间增加）" if up else "（C 盘可用空间减少）")),
        ]
        # 文件清理模式下删除前不统计目录体积（那需要额外全量遍历一遍，会明显拖慢速度），
        # 因此该行无数据、直接隐藏，避免出现误导性的"—"。
        if show_moved:
            rows.append(("本次处理目录体积", bytes_human(moved_bytes) if moved_bytes else "—"))
        for k, v in rows:
            r = QHBoxLayout()
            a = QLabel(k)
            a.setStyleSheet("color:#4b5563;")
            b = QLabel(v)
            b.setStyleSheet(f"font-weight:bold; font-size:12pt; color:{color if '实测' in k else '#111827'};")
            r.addWidget(a)
            r.addStretch(1)
            r.addWidget(b)
            lay.addLayout(r)

        if detail:
            d = QLabel(detail)
            d.setWordWrap(True)
            d.setStyleSheet("color:#4b5563;")
            lay.addWidget(d)

        note = QLabel("说明：以上均为系统实时查询值。C 盘空间同时受系统/其他程序写入影响，"
                      "故实测差值可能略大于或小于本次处理体积，本工具如实展示，不做任何修饰。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280; font-size:9pt;")
        lay.addWidget(note)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("知道了")
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)


# ===================== C盘初始化：预扫描确认 / 进度弹窗 =====================
class CleanScanDialog(GlassDialog):
    """预扫描确认：列出将要删除的顶层目标，用户二次确认（可取消）。"""
    def __init__(self, parent=None, targets=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("C盘初始化 · 待删除清单预览")
        self.resize(620, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        t = QLabel("⚠️ 以下顶层目录将被永久删除（操作不可逆）")
        t.setStyleSheet("font-size:15px;font-weight:bold;color:#c0392b;")
        lay.addWidget(t)

        sub = QLabel(
            f"共 <b>{len(targets)}</b> 个顶层目标，<b>将被删除</b>的是：各用户档案（桌面/文档/下载/AppData 等）、"
            f"Program Files 与 Program Files (x86) 下的<b>第三方软件目录</b>、C 盘根下的非系统目录。<br>"
            f"<b>不会被删除</b>的是：C:\\Windows、Program Files 下的 <b>Windows 内置组件</b>"
            f"（Common Files / Internet Explorer / Windows Defender / Windows NT / WindowsPowerShell / "
            f"Windows Media Player / Windows Mail 等）及其他受保护系统目录"
            f"（删除它们会导致系统自身重置 PBR/WinRE 失败，故一律保留）。")
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#4b5563;")
        lay.addWidget(sub)

        lst = QListWidget()
        lst.setAlternatingRowColors(True)
        show = targets[:300]
        for p in show:
            lst.addItem(p)
        if len(targets) > len(show):
            lst.addItem(f"… 等共 {len(targets)} 项")
        lay.addWidget(lst, 1)

        note = QLabel("提示：D/E 盘文件不受影响；删除前请确认已用【C盘文件迁出】备份重要资料。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280;font-size:9pt;")
        lay.addWidget(note)

        btns = QDialogButtonBox()
        btns.addButton("取消（不删除）", QDialogButtonBox.ButtonRole.RejectRole)
        b_ok = btns.addButton("我已知风险，继续删除", QDialogButtonBox.ButtonRole.AcceptRole)
        b_ok.setStyleSheet("background-color:#c0392b;color:white;font-weight:bold;padding:6px 14px;")
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)


class CleanProgressDialog(GlassDialog):
    """后台清理进度：实时进度条 + 当前项 + 取消按钮（界面绝不卡死）。"""
    def __init__(self, parent=None, worker=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("C盘初始化 · 执行中")
        self.resize(560, 220)
        self._worker = worker
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        self.label = QLabel("正在准备…")
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-size:12pt;")
        lay.addWidget(self.label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setStyleSheet(
            "QProgressBar{height:22px;border-radius:6px;background:#e5e7eb;}"
            "QProgressBar::chunk{background:#1e8449;border-radius:6px;}")
        lay.addWidget(self.bar)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("background-color:#c0392b;color:white;padding:6px 16px;")
        self.btn_cancel.clicked.connect(self._on_cancel)
        lay.addWidget(self.btn_cancel, alignment=Qt.AlignmentFlag.AlignCenter)

        if worker is not None:
            worker.progress_update.connect(self.on_progress)
            worker.finished_signal.connect(self.accept)
            if worker.isFinished():
                QTimer.singleShot(0, self.accept)

    def on_progress(self, pct, text):
        self.bar.setValue(pct)
        self.label.setText(f"进度 {pct}% ｜ 当前：{os.path.basename(text) or text}")

    def _on_cancel(self):
        self.btn_cancel.setText("正在停止…")
        self.btn_cancel.setEnabled(False)
        if self._worker is not None:
            self._worker.stop()


# ===================== 容量校验弹窗 =====================
class MigrateCapacityDialog(GlassDialog):
    def __init__(self, parent, selected_paths, target_root, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("迁移容量预览与校验")
        self.resize(660, 360)
        self.selected_paths = selected_paths
        self.target_root = target_root
        self.total_size_bytes = 0
        self.free_bytes = 0
        self.anim = None
        self.flash_timer = QTimer()
        self.flash_timer.timeout.connect(self.flash_color)
        self.flash_state = True

        layout = QVBoxLayout()
        self.label_selected = QLabel("正在后台计算选中目录总大小，请稍候...")
        self.label_total = QLabel("待迁移总容量：--")
        self.label_target = QLabel(f"迁移目标：{target_root}（已自动创建，自动选择非C盘符）")
        self.label_target.setStyleSheet("font-weight:bold; color:#2563eb;")
        self.label_free = QLabel("目标磁盘剩余空间：--")
        self.label_tip = QLabel("容量状态：等待计算")
        self.label_tip.setStyleSheet("font-weight:bold; font-size:12pt;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        layout.addWidget(self.label_selected)
        layout.addWidget(self.label_total)
        layout.addWidget(self.label_target)
        layout.addWidget(self.label_free)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.label_tip)

        btnbox = QDialogButtonBox()
        self.btn_start = btnbox.addButton("确认并开始迁移", QDialogButtonBox.ButtonRole.AcceptRole)
        btn_cancel = btnbox.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_start.setEnabled(False)
        layout.addWidget(btnbox)
        self.setLayout(layout)

        btnbox.accepted.connect(self.accept)
        btnbox.rejected.connect(self.reject)

        # 目标盘剩余空间（目标盘已由主流程自动选定并建好落地文件夹）
        self.free_bytes = get_disk_free(target_root)
        self.label_free.setText(f"目标磁盘剩余空间：{bytes_human(self.free_bytes)}")

        # 总大小放到后台线程计算，避免选大目录时界面卡顿
        self.size_worker = SizeCalcWorker(selected_paths)
        self.size_worker.done.connect(self.on_size_done)
        self.size_worker.start()

    def on_size_done(self, total: int):
        self.total_size_bytes = total
        self.label_selected.setText(f"已选中 {len(self.selected_paths)} 个目录")
        self.label_total.setText(f"待迁移总容量：{bytes_human(total)}")
        if self.check_capacity():
            self.label_tip.setText("✅ 空间充足，可以迁移")
            self.label_tip.setStyleSheet("font-weight:bold; font-size:12pt; color:green;")
            self.btn_start.setEnabled(True)
        # 空间不足时 check_capacity 内部已禁用按钮并闪烁提示

    def flash_color(self):
        self.flash_state = not self.flash_state
        if self.free_bytes < self.total_size_bytes:
            self.label_tip.setStyleSheet(
                f"font-weight:bold; font-size:12pt; color:{'red' if self.flash_state else '#ff4444'};")
        else:
            self.label_tip.setStyleSheet(
                f"font-weight:bold; font-size:12pt; color:{'#cc9900' if self.flash_state else '#bb8800'};")

    def check_capacity(self) -> bool:
        """根据已选定的目标盘剩余空间做容量校验，返回是否允许迁移。"""
        need_buf = self.total_size_bytes * 1.2
        if self.free_bytes < self.total_size_bytes:
            self.label_tip.setText("❌ 磁盘空间不足！无法迁移")
            self.flash_timer.start(450)
            self.btn_start.setEnabled(False)
            return False
        elif self.free_bytes < need_buf:
            self.label_tip.setText("⚠️ 空间紧张！复制可能中途失败，仍可继续")
            self.flash_timer.start(450)
            self.btn_start.setEnabled(True)
            return True
        else:
            self.flash_timer.stop()
            return True

# ========== 免责弹窗 ==========
class DisclaimDialog(GlassDialog):
    def __init__(self, parent=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("重要免责协议 - C盘利刃")
        self.resize(740, 540)
        layout = QVBoxLayout()
        text_box = QTextEdit()
        text_box.setReadOnly(True)
        disclaimer_text = """⚠️ 重要免责协议，使用前请仔细阅读

本【C盘利刃】为辅助工具，具备高危系统操作能力：
1. 【C盘文件迁出】：移动C盘文件至其他磁盘，文件复制、删除操作存在文件丢失、损坏风险；
2. 【C盘初始化】：
   ✅ PBR重置引擎：调用Windows官方PBR/WinRE重置，会清空C盘全部数据，此操作不可逆；
   ✅ 文件清理降级引擎：精简系统无法使用PBR时，将批量卸载软件、删除C盘用户文件，无法彻底清除注册表、驱动残留。

风险提示：
① 操作前请务必手动备份全部重要资料，重要文档、照片建议多份异地备份；
② 执行C盘初始化后，C盘所有个人文件、软件、配置全部清除；
③ 重置中途断电、硬盘故障、BitLocker密钥丢失、精简系统异常，可能导致系统无法正常启动；
④ 本工具并非微软官方软件，杀毒软件（Windows Defender、360等）会误报病毒，属于高危操作程序正常现象；
⑤ 请勿在公司域电脑、服务器、ARM设备、Win7/XP系统运行本软件；
⑥ 若D盘开启BitLocker加密，预埋的重置成功/失败弹窗功能会失效。

使用本软件即代表您充分知晓全部风险，并同意：
✅ 所有因使用、误操作、硬件异常、系统环境问题产生的数据丢失、系统损坏、硬件故障等一切后果，全部由使用者本人承担；
✅ 软件作者不承担任何直接、间接损失与相关赔偿责任；
✅ 禁止将本软件用于恶意破坏他人计算机。
"""
        text_box.setText(disclaimer_text)
        layout.addWidget(text_box)
        self.check_agree = QCheckBox("我已完整阅读、理解全部风险，自愿承担全部后果，同意使用本工具")
        layout.addWidget(self.check_agree)
        btn_layout = QHBoxLayout()
        self.btn_enter = QPushButton("进入软件")
        self.btn_exit = QPushButton("退出")
        self.btn_enter.setEnabled(False)
        btn_layout.addWidget(self.btn_enter)
        btn_layout.addWidget(self.btn_exit)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self.check_agree.stateChanged.connect(self.on_check_change)
        self.btn_enter.clicked.connect(self.accept)
        self.btn_exit.clicked.connect(self.reject)

    def on_check_change(self):
        self.btn_enter.setEnabled(self.check_agree.isChecked())

# ===================== 重置通知弹窗（原 notify.py 合并进来） =====================
def read_pbr_log():
    try:
        log_path = get_pbr_log_path()
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                return f.read()[:2000]
        ret = subprocess.run(
            'wevtutil qe System /q:"*[System[Provider[@Name=\'Microsoft-Windows-Recovery\']]]" /c:5 /f:text',
            capture_output=True, text=True, shell=True, timeout=10
        )
        if ret.stdout.strip():
            return ret.stdout[:2000]
    except Exception:
        pass
    return "未捕获到详细报错信息，重置流程意外中断。"


class NotifyDialog(GlassDialog):
    def __init__(self, is_success: bool, err_msg: str, parent=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(560, 340)

        if is_success:
            self.setWindowTitle("✅ 重置成功 - C盘利刃")
            txt = f"""✅ C盘重置已成功完成！

说明：
1. C盘已重置为纯净Windows系统
2. D盘、E盘所有用户文件已保留
3. 所有软件、C盘资料已清除，需要重新安装应用
4. 之前迁移文件的日志保存在 {get_bootstrap_dir()}\\迁移日志.txt
"""
        else:
            self.setWindowTitle("⚠️ 重置未完成 - C盘利刃")
            txt = f"""本次重置过程发生中断（可能原因：中途断电、手动重启、程序异常退出）

【报错详情】
{err_msg}

重置未完成，请检查系统后再次执行重置。
"""

        lay = QVBoxLayout()
        label = QLabel(txt)
        label.setWordWrap(True)
        lay.addWidget(label)

        lay.addWidget(QLabel("详细日志："))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlainText("正在读取详细日志…")
        lay.addWidget(self.log_text)
        # wevtutil 查询最坏要等 10 秒：放到事件循环里跑，弹窗先出来不冻结
        QTimer.singleShot(30, self._fill_log)

        btn_ok = QPushButton("确认")
        btn_ok.clicked.connect(self.on_ok)
        lay.addWidget(btn_ok)
        self.setLayout(lay)

    def _fill_log(self):
        try:
            self.log_text.setPlainText(read_pbr_log())
        except Exception:
            self.log_text.setPlainText("日志读取失败。")

    def on_ok(self):
        flag = get_flag_running_path()
        if os.path.exists(flag):
            try:
                os.remove(flag)
            except Exception:
                pass
        self.accept()


def run_notify_mode():
    """--notify 模式：直接弹通知窗，不走主程序。
    判定逻辑（V2.3 修复）：旧版靠 C:\\ResetBlade_Exist.marker 判断成败，但那个文件全代码
    没人写，导致永远弹"成功"。现改为读预埋标志内容：
      RESET_OK       = 重置流程完整跑完 -> 弹成功
      RESET_RUNNING  = 中途断电/崩溃被打断 -> 弹失败 + 日志
    没有标志文件（用户没跑过重置）-> 静默退出，不打扰。"""
    flag = get_flag_running_path()
    if not os.path.exists(flag):
        sys.exit(0)
    try:
        with open(flag, "r", encoding="utf-8") as f:
            state = f.read().strip()
    except OSError:
        state = ""
    is_success = (state == "RESET_OK")
    err_msg = "" if is_success else read_pbr_log()
    dlg = NotifyDialog(is_success=is_success, err_msg=err_msg, dark=False)
    dlg.exec()
    sys.exit(0)

# ===================== 支持鼠标拖拽框选的列表（类似桌面按住左键成片选中图标） =====================
class RubberBandList(QListWidget):
    """在列表空白处按住鼠标左键拖拽 -> 橡皮筋框选，框内的可迁移项被批量勾选（框外还原为拖拽前状态）；
    单击某个条目则单独切换其勾选状态。

    性能说明（V2.3 优化）：原版每次 MouseMove 都全表遍历（indexFromItem + visualRect +
    setChecked 逐个触发 stateChanged -> 主窗口再全表扫描一次），几百行的表拖一下框选就掉帧。
    现改为：
      1) 只遍历【可见行区间】（indexAt 求首末行），行数从全表降到 ~一屏；
      2) 差量更新：只处理「新进入/离开选框」的行，其余不动；
      3) 批量 setChecked 期间屏蔽复选框信号，拖拽结束发一次 checkedTouched 合并信号。"""
    keyDelete = pyqtSignal()      # 按下 Delete 键（用于"移出列表"）
    rowClicked = pyqtSignal(int)  # 单击了第 i 行（NoSelection 模式下 currentItem 不可靠，用它定位行）
    checkedTouched = pyqtSignal() # 拖拽框选结束/进行中批量改过勾选状态（合并信号，供外部刷新按钮态）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)     # 行高一致：indexAt/visualRect 更快，滚动更顺
        self._origin = None
        self._dragging = False
        self._before = {}
        self._drag_checked = set()         # 本次拖拽中因框选而被勾上的行号
        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self.viewport().installEventFilter(self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.keyDelete.emit()
            return
        super().keyPressEvent(event)

    def _is_checked(self, i: int) -> bool:
        w = self.itemWidget(self.item(i))
        return bool(w.isChecked()) if w else False

    def _set_checked(self, i: int, val: bool, block=True) -> bool:
        """设置某行勾选状态；block=True 时屏蔽复选框自身信号（批量操作用）。
        返回是否有实际改变。"""
        w = self.itemWidget(self.item(i))
        if w and w.isEnabled():          # 禁用态（高危项）不可被框选/切换
            if w.isChecked() == val:
                return False
            if block:
                w.blockSignals(True)
            w.setChecked(val)
            if block:
                w.blockSignals(False)
            return True
        return False

    def _row_at(self, pos):
        idx = self.indexAt(pos)
        return idx.row() if idx.isValid() else None

    def _visible_row_range(self, rect):
        """求选框覆盖的可见行区间 [first, last]；选框完全在列表外时返回 None。"""
        vp_w = max(self.viewport().width() - 1, 1)
        top_pt = QPoint(min(max(rect.left(), 1), vp_w), rect.top())
        bot_pt = QPoint(min(max(rect.left(), 1), vp_w), rect.bottom())
        i0 = self.indexAt(top_pt)
        i1 = self.indexAt(bot_pt)
        if i0.isValid():
            first = i0.row()
        elif i1.isValid():
            first = 0                       # 顶部落在行间空隙：从第一行算起
        else:
            # 上下都取不到行：选框在列表可视区外
            if rect.top() >= self.viewport().height():
                return None
            first = 0
        last = i1.row() if i1.isValid() else self.count() - 1
        return (first, max(first, last))

    def eventFilter(self, obj, event):
        if obj is self.viewport():
            et = event.type()
            if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._origin = event.pos()
                self._dragging = True
                self._before = {i: self._is_checked(i) for i in range(self.count())}
                self._drag_checked = set()
                self._rubber.setGeometry(QRect(self._origin, QSize(0, 0)))
                self._rubber.show()
                # 吞掉本次按下事件：避免复选框在拖拽起始时自己翻转，勾选统一由拖拽/单击逻辑处理
                return True
            elif et == QEvent.Type.MouseMove and self._dragging:
                rect = QRect(self._origin, event.pos()).normalized()
                self._rubber.setGeometry(rect)
                rng = self._visible_row_range(rect)
                if rng is not None:
                    first, last = rng
                    want = set()
                    for i in range(first, last + 1):
                        idx = self.indexFromItem(self.item(i))
                        if not idx.isValid():
                            continue
                        if rect.intersects(self.visualRect(idx)):
                            w = self.itemWidget(self.item(i))
                            if w and w.isEnabled():
                                want.add(i)
                    changed = False
                    for i in want - self._drag_checked:          # 新进入选框：勾上
                        changed |= self._set_checked(i, True)
                    for i in self._drag_checked - want:          # 离开选框：还原拖拽前状态
                        changed |= self._set_checked(i, self._before.get(i, False))
                    self._drag_checked = want
                    if changed:
                        self.checkedTouched.emit()
                return True
            elif et == QEvent.Type.MouseButtonRelease and self._dragging:
                self._rubber.hide()
                dragged = (event.pos() - self._origin).manhattanLength() > 4
                if not dragged:
                    i = self._row_at(event.pos())
                    if i is not None:
                        if self._set_checked(i, not self._is_checked(i), block=False):
                            self.checkedTouched.emit()
                        self.rowClicked.emit(i)
                else:
                    self.checkedTouched.emit()
                self._dragging = False
                self._origin = None
                self._drag_checked = set()
                return True
        return super().eventFilter(obj, event)


# ===================== 主窗口 =====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  {APP_VERSION}")
        self.resize(960, 680)      # 768p 屏幕下留出任务栏空间，避免底部按钮被裁出屏幕
        self.scan_items = []
        self.worker = None
        self.scan_worker = None
        self.precheck_worker = None
        self.shortcut_worker = None
        self.dark_mode = False
        # 渲染缓存 / 防抖定时器（见 update_background / _update_shadow / log）
        self._bg_cache_key = None
        self._bg_cache_pm = None
        self._shadow_cache_key = None
        self._shadow_margin = 16
        # 日志批量刷新：缓冲 120ms 一次性写入，避免每个文件/每条进度都触发一次全文重绘
        self._log_buf = []
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(120)
        self._log_timer.timeout.connect(self._flush_log)
        # 勾选状态刷新防抖：复选框/框选连发 stateChanged 时只做一次全表扫描
        self._sel_timer = QTimer(self)
        self._sel_timer.setSingleShot(True)
        self._sel_timer.setInterval(80)
        self._sel_timer.timeout.connect(self._refresh_migrate_btn)
        # 背景高清精修防抖：拖拽中先用低质量缩放保响应，停止 60ms 后补高清
        self._bg_refine_timer = QTimer(self)
        self._bg_refine_timer.setSingleShot(True)
        self._bg_refine_timer.setInterval(60)
        self._bg_refine_timer.timeout.connect(lambda: self.update_background(smooth=True))

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        btn_lay = QHBoxLayout()
        self.btn_scan = QPushButton("C盘文件迁出")
        self.btn_junction = QPushButton("缓存搬家(Junction)")
        self.btn_init = QPushButton("C盘初始化")
        self.btn_task_add = QPushButton("添加开机提醒任务")
        self.btn_task_del = QPushButton("删除开机提醒任务")
        self.btn_toggle_theme = QPushButton("切换深色/浅色")
        self.btn_help = QPushButton("帮助文档")
        self.btn_about = QPushButton("关于/合作")
        for b in [self.btn_scan, self.btn_junction, self.btn_init, self.btn_task_add,
                  self.btn_task_del, self.btn_toggle_theme, self.btn_help, self.btn_about]:
            btn_lay.addWidget(b)
        lay.addLayout(btn_lay)

        # C 盘容量条：实时显示总容量/可用，迁移前与迁移后各记录一次，用于计算真实释放量
        self.c_free_before = None
        self.lbl_cfree = QLabel("C 盘容量：读取中…")
        self.lbl_cfree.setStyleSheet("font-size:11pt; font-weight:bold; color:#1565c0;")
        lay.addWidget(self.lbl_cfree)
        self._refresh_cfree()

        # 【开始迁移】按钮：默认隐藏，用户在列表里勾选≥1个可迁移文件夹后才出现在界面右下角
        self.btn_do_migrate = QPushButton("开始迁移")
        self.btn_do_migrate.hide()

        lay.addWidget(QLabel("扫描列表（可单击勾选，或在空白处按住鼠标左键拖拽成片框选）："))
        self.list_widget = RubberBandList()
        lay.addWidget(self.list_widget)
        self.list_widget.checkedTouched.connect(self._schedule_sel_refresh)

        self.mig_progress_label = QLabel("迁移实时进度：0% | 等待任务")
        self.mig_progress_bar = QProgressBar()
        self.mig_progress_bar.setRange(0, 100)
        self.mig_progress_bar.setValue(0)
        lay.addWidget(self.mig_progress_label)
        lay.addWidget(self.mig_progress_bar)

        lay.addWidget(QLabel("运行日志："))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.document().setMaximumBlockCount(20000)   # 限长：长时间迁移不再无限膨胀拖慢重绘
        lay.addWidget(self.log_box)

        # 开始迁移按钮固定落在界面右下角（选完可迁移文件夹后由 _refresh_migrate_btn 控制显隐）
        self.mig_lay = QHBoxLayout()
        self.mig_lay.addStretch(1)
        self.mig_lay.addWidget(self.btn_do_migrate)
        lay.addLayout(self.mig_lay)

        self.btn_scan.clicked.connect(self.on_scan_click)
        self.btn_junction.clicked.connect(self.open_junction_dialog)
        self.btn_do_migrate.clicked.connect(self.on_migrate_click)
        self.btn_init.clicked.connect(self.on_init_click)
        self.btn_help.clicked.connect(self.show_help_dialog)
        self.btn_about.clicked.connect(self.show_about_dialog)
        self.btn_toggle_theme.clicked.connect(self.switch_theme)
        self.btn_task_add.clicked.connect(self.add_auto_run_task)
        self.btn_task_del.clicked.connect(self.remove_auto_run_task)

        self.setup_background()
        self.load_light_style()
        if is_admin():
            self.log("C盘利刃 启动成功，当前以管理员权限运行", color="green")
        else:
            self.log("⚠️ 当前未以管理员权限运行（启动时拒绝了UAC或提权失败），迁移系统文件可能报拒绝访问", color="red")
        self.log("点击【C盘文件迁出】开始扫描（后台线程，不卡界面）；绿色可迁移项自动勾选并排在前面。", color="gray")

    # ---------- 虚化背景（玻璃拟态） ----------
    def setup_background(self):
        """铺一层虚化背景图 + 半透明蒙版，保证前景文字清晰。
        同时创建「预渲染阴影」：用多层半透明圆角矩形手搓一张柔和阴影图，
        取代原来的 QGraphicsDropShadowEffect —— 后者挂在中央控件上时，
        任何子控件重绘（日志追加、进度条刷新）都会让 Qt 重新模糊整块半透明区域，
        是全局卡顿的头号来源；预渲染图每帧零成本。"""
        self.bg_pixmap_orig = load_bg_pixmap()
        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(False)
        self.scrim = QLabel(self)
        # 预渲染阴影层：鼠标穿透，压在 bg 之上、蒙版之下
        self._shadow_label = QLabel(self)
        self._shadow_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # 层级：bg(最底) < shadow < scrim < central(内容)
        self.scrim.stackUnder(self.centralWidget())
        self.bg_label.stackUnder(self.scrim)
        self._shadow_label.stackUnder(self.scrim)
        self.update_background()
        self._update_shadow()

    def update_background(self, smooth=True):
        """缩放背景图。smooth=False 用快速变换（拖拽中每帧调用，保响应）；
        smooth=True 用平滑变换（停止拖拽后精修一次）。按尺寸缓存，重复调用不重复缩放。

        性能要点：源图已在开发期烘成预模糊静态图，运行时这里只做纯缩放采样，
        没有高斯模糊这类逐像素重计算；再加上按尺寸缓存 + 拖拽期降级，
        背景的开销远低于原来挂QGraphicsDropShadowEffect 时的实时模糊。
        """
        w, h = max(self.width(), 1), max(self.height(), 1)
        self.bg_label.setGeometry(0, 0, w, h)
        self.scrim.setGeometry(0, 0, w, h)
        if not self.bg_pixmap_orig:
            return
        key = (w, h, smooth)
        if self._bg_cache_key == key and self._bg_cache_pm is not None:
            self.bg_label.setPixmap(self._bg_cache_pm)
            return
        mode = (Qt.TransformationMode.SmoothTransformation if smooth
                else Qt.TransformationMode.FastTransformation)
        # 直接缩放并居中裁剪到目标尺寸（等价于"铺满+居中裁切"，
        # 但不会先生成一张放大后的中间图再 copy，省掉一次全尺寸分配）
        sw, sh = self.bg_pixmap_orig.width(), self.bg_pixmap_orig.height()
        ratio = max(w / sw, h / sh)
        tw, th = max(1, min(w, round(sw * ratio))), max(1, min(h, round(sh * ratio)))
        pm = self.bg_pixmap_orig.scaled(tw, th, Qt.AspectRatioMode.IgnoreAspectRatio, mode)
        if tw != w or th != h:
            pm = pm.copy((tw - w) // 2, (th - h) // 2, w, h)
        self._bg_cache_key = key
        self._bg_cache_pm = pm
        self.bg_label.setPixmap(pm)

    def _update_shadow(self):
        """按当前窗口尺寸生成/复用预渲染阴影图（多层半透明矩形模拟模糊，只画一次）。"""
        if not hasattr(self, "_shadow_label"):
            return
        w, h = self.width(), self.height()
        m = self._shadow_margin
        cw, ch = w - 2 * m, h - 2 * m
        if cw < 60 or ch < 60:
            return
        key = (cw, ch)
        if self._shadow_cache_key != key:
            pad = 18
            pm = QPixmap(cw + 2 * pad, ch + 2 * pad)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            # 由外向内叠 16 层、逐层加深，形成柔和阴影；偏移 (3,3) 与原特效一致
            layers = 16
            for k in range(layers, 0, -1):
                grow = pad * k / layers
                alpha = int(70 * (k / layers) ** 2)
                if alpha < 1:
                    continue
                p.setBrush(QColor(0, 0, 0, alpha))
                r = QRectF(pad - grow + 3, pad - grow + 3, cw + 2 * grow, ch + 2 * grow)
                p.drawRoundedRect(r, 8 + grow, 8 + grow)
            # 挖掉中心区域（DestinationOut），只留四周阴影
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            p.setBrush(QColor(0, 0, 0, 255))
            p.drawRoundedRect(QRectF(pad + 3, pad + 3, cw, ch), 8, 8)
            p.end()
            self._shadow_cache_key = key
            self._shadow_cache_pm = pm
        self._shadow_label.setPixmap(self._shadow_cache_pm)
        self._shadow_label.setGeometry(0, 0, w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 拖拽改变大小：立即用低质量缩放刷新视觉 + 同步阴影，停止 60ms 后再精修高清背景
        self.update_background(smooth=False)
        self._update_shadow()
        self._bg_refine_timer.start()

    def load_light_style(self):
        self.dark_mode = False
        if hasattr(self, "scrim"):
            self.scrim.setStyleSheet("background-color: rgba(255,255,255,0.60);")
        self.setStyleSheet("""
        QMainWindow{ background:transparent; }
        QWidget{ font-family:"Microsoft YaHei"; font-size:10pt; }
        QPushButton{ background-color:rgba(255,255,255,0.55); border:1px solid #d1d5db; border-radius:8px; padding:7px 12px; color:#1f2937; }
        QPushButton:hover{ background-color:#eff6ff; border-color:#93c5fd; }
        QPushButton:pressed{ background-color:#dbeafe; }
        QPushButton:disabled{ background-color:rgba(243,244,246,0.5); color:#9ca3af; }
        QListWidget{ background-color:rgba(255,255,255,0.32); border:1px solid #d1d5db; border-radius:8px; padding:4px; }
        QTextEdit{ background-color:rgba(255,255,255,0.32); border:1px solid #d1d5db; border-radius:8px; padding:6px; }
        QProgressBar{ border:1px solid #d1d5db; border-radius:8px; height:22px; background-color:rgba(255,255,255,0.32); }
        QProgressBar::chunk{ background-color:#3b82f6; border-radius:7px; }
        QCheckBox{ spacing:6px; }
        QDialog{ background:transparent; }
        QLabel{ color:#1f2937; }
        """)
        if getattr(self, "bg_pixmap_orig", None) is None:
            self.setStyleSheet(self.styleSheet() + "\nQMainWindow{ background-color:#f2f4f7; }")

    def load_dark_style(self):
        self.dark_mode = True
        if hasattr(self, "scrim"):
            self.scrim.setStyleSheet("background-color: rgba(17,24,39,0.72);")
        self.setStyleSheet("""
        QMainWindow{ background:transparent; }
        QWidget{ font-family:"Microsoft YaHei"; font-size:10pt; }
        QPushButton{ background-color:rgba(31,41,55,0.55); border:1px solid #4b5563; border-radius:8px; padding:7px 12px; color:#f9fafb; }
        QPushButton:hover{ background-color:#374151; border-color:#60a5fa; }
        QPushButton:pressed{ background-color:#4b5563; }
        QPushButton:disabled{ background-color:rgba(31,41,55,0.4); color:#6b7280; }
        QListWidget{ background-color:rgba(31,41,55,0.42); border:1px solid #4b5563; border-radius:8px; padding:4px; color:#f9fafb; }
        QTextEdit{ background-color:rgba(31,41,55,0.42); border:1px solid #4b5563; border-radius:8px; padding:6px; color:#f9fafb; }
        QProgressBar{ border:1px solid #4b5563; border-radius:8px; height:22px; background-color:rgba(31,41,55,0.42); }
        QProgressBar::chunk{ background-color:#3b82f6; border-radius:7px; }
        QCheckBox{ spacing:6px; color:#f9fafb; }
        QDialog{ background:transparent; }
        QLabel{ color:#f9fafb; }
        """)
        if getattr(self, "bg_pixmap_orig", None) is None:
            self.setStyleSheet(self.styleSheet() + "\nQMainWindow{ background-color:#111827; }")

    def switch_theme(self):
        if self.dark_mode:
            self.load_light_style()
        else:
            self.load_dark_style()
        self.log(f"已切换至：{'浅色模式' if not self.dark_mode else '深色模式'}")

    def add_auto_run_task(self):
        notify_target = get_notify_target()
        if not os.path.exists(notify_target):
            # 旧版这里直接弹"请先执行C盘初始化预埋文件"然后返回——但部署函数根本没人调用，
            # 按钮永远点不成功。现在自动补部署：没有预埋 exe 就现场复制一个（不写运行标志，
            # 不会误触发开机通知），然后再创建计划任务。
            if not getattr(sys, "frozen", False):
                QMessageBox.warning(
                    self, "无法预埋",
                    "当前是源码运行模式，预埋的必须是打包后的 exe。\n"
                    "请使用打包好的「C盘利刃.exe」再创建开机提醒任务。")
                return
            self.log(f"预埋程序不存在（{notify_target}），自动补部署...", "gray")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                ok = self.deploy_bootstrap_files(write_flag=False)
            finally:
                QApplication.restoreOverrideCursor()
            if not ok or not os.path.exists(notify_target):
                QMessageBox.warning(self, "提示", f"自动预埋失败：{notify_target}\n请检查磁盘权限后重试。")
                return
            self.log("✅ 已自动补齐预埋程序", "green")
        # 任务计划启动时带 --notify 参数
        quoted_path = f'"{notify_target}" --notify'
        cmd = rf'schtasks /create /tn "{TASK_NAME}" /tr {quoted_path} /sc onlogon /rl highest /f'
        rc, out = run_cmd(cmd)
        if rc == 0:
            QMessageBox.information(self, "成功", "开机任务创建完成！\n用户登录自动弹出重置结果通知")
            self.log("✅ 开机任务【ResetNotifyAutoRun】创建成功", color="green")
        else:
            QMessageBox.critical(self, "失败", f"任务创建失败:\n{out}")
            self.log(f"❌ 创建开机任务失败: {out}", color="red")

    def remove_auto_run_task(self):
        cmd = rf'schtasks /delete /tn "{TASK_NAME}" /f'
        rc, out = run_cmd(cmd)
        if rc == 0:
            QMessageBox.information(self, "成功", "开机任务已删除")
            self.log("✅ 开机任务【ResetNotifyAutoRun】删除成功", color="green")
        else:
            QMessageBox.warning(self, "提示", f"删除任务信息:\n{out}")
            self.log(f"删除开机任务：{out}", color="black")

    def log(self, msg: str, color="black"):
        """缓冲日志：只入队不刷新，由 _flush_log 每 120ms 批量写入一次。
        原版每条日志都触发一次 QTextEdit 全文重绘 + ensureCursorVisible，
        迁移/清理时每秒上百条，直接拖垮界面。"""
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log_buf.append((f"【{t}】{msg}\n", color))
        if not self._log_timer.isActive():
            self._log_timer.start()

    def _flush_log(self):
        if not self._log_buf:
            self._log_timer.stop()
            return
        batch, self._log_buf = self._log_buf, []
        dark = getattr(self, "dark_mode", False)
        cursor = self.log_box.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        for full_msg, color in batch:
            fmt = QTextCharFormat()
            if color == "green":
                fmt.setForeground(QColor("#22c55e" if dark else "#00aa00"))
            elif color == "red":
                fmt.setForeground(QColor("#f87171" if dark else "#dd0000"))
            elif color == "gray":
                fmt.setForeground(QColor("#9ca3af" if dark else "#888888"))
            elif color == "blue":
                fmt.setForeground(QColor("#60a5fa" if dark else "#1565c0"))
            else:
                fmt.setForeground(QColor("#e5e7eb" if dark else "#000000"))
            cursor.insertText(full_msg, fmt)
        self.log_box.setTextCursor(cursor)
        self.log_box.ensureCursorVisible()

    def open_junction_dialog(self):
        """打开缓存搬家窗口：自动检测会产生缓存的应用，用 junction 把缓存实体搬离 C 盘。"""
        d = CacheJunctionDialog(self, dark=self.dark_mode)
        d.exec()

    def on_scan_click(self):
        """【C盘文件迁出】按钮：后台线程扫描，界面不卡。扫描完成点亮【开始迁移】。"""
        if self.scan_worker is not None and self.scan_worker.isRunning():
            return
        self.btn_scan.setEnabled(False)
        self.btn_do_migrate.hide()
        self.list_widget.clear()
        self.log("开始扫描 C 盘可迁移文件（后台线程执行，界面可正常操作）...")
        self.scan_worker = ScanWorker(max_depth=2)
        self.scan_worker.progress.connect(self.log)
        self.scan_worker.scan_done.connect(self.on_scan_finished)
        self.scan_worker.error.connect(lambda e: self.log(f"扫描异常：{e}", "red"))
        self.scan_worker.start()

    @staticmethod
    def _safe_risk(path: str) -> str:
        """classify_risk 的安全包装：任何异常都按 safe 处理，避免单条坏路径拖垮整个列表。"""
        try:
            return classify_risk(path)
        except Exception:
            return "safe"

    def on_scan_finished(self, paths, high_cnt):
        self.scan_items = paths
        self.list_widget.clear()
        try:
            # 排序：绿色[可迁移]全部排在红色[高危]前面（各组内部按路径字母序）
            safes = sorted((p for p in paths if self._safe_risk(p) == "safe"), key=str.lower)
            highs = sorted((p for p in paths if self._safe_risk(p) != "safe"), key=str.lower)
        except Exception as e:
            self.log(f"扫描结果排序异常（已降级为原序）：{e}", "red")
            safes, highs = list(paths), []
        shown = 0
        # 批量填充：填充期间冻结列表重绘、行高按一致处理、布局批量模式，
        # 几千项也能一次性刷完（原版逐项 addItem+setItemWidget，每项都触发一次布局重排）
        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.setLayoutMode(QListWidget.LayoutMode.Batched)
        try:
            for path in safes + highs:
                try:
                    risk = self._safe_risk(path)
                    if risk == "high":
                        box = QCheckBox(f"[高危·禁止迁移] {path}")
                        box.setStyleSheet("color:#c0392b;")
                        box.setEnabled(False)   # 高危目录彻底禁止勾选（点击/框选均无效），从源头杜绝误迁
                        box.setToolTip("系统关键目录（注册表/应用核心等），迁移会导致系统或软件损坏，已禁止选择")
                    else:
                        box = QCheckBox(f"[可迁移] {path}")
                        box.setStyleSheet("color:#1e8449;")
                        box.setChecked(True)   # 自动勾选全部绿色可迁移项
                    box.setProperty("path", path)
                    li = QListWidgetItem()
                    self.list_widget.addItem(li)
                    self.list_widget.setItemWidget(li, box)
                    # 连接放在入表之后：避免初始 setChecked 触发一次全表扫描
                    box.stateChanged.connect(self._schedule_sel_refresh)
                    shown += 1
                except Exception as e:
                    self.log(f"跳过无法显示的目录：{path}（{e}）", "gray")
        finally:
            self.list_widget.setUpdatesEnabled(True)
        self.log(f"扫描完成，共 {shown} 个目录：绿色可迁移 {len(safes)} 个（已自动全部勾选），红色高危 {len(highs)} 个（已禁止勾选，防止误迁）。")
        self.log("绿色项已排前并自动勾选，可直接点右下角【开始迁移】；也可单击取消/补充勾选或拖拽框选。")
        self.btn_scan.setEnabled(True)
        self.btn_do_migrate.show()
        self.btn_do_migrate.setEnabled(len(safes) > 0)

    def _schedule_sel_refresh(self, *args):
        """勾选状态可能连发（框选一次改几百项）：80ms 防抖合并成一次全表扫描。"""
        self._sel_timer.start()

    def _refresh_migrate_btn(self):
        """只要有≥1个被勾选，就让右下角的【开始迁移】出现。"""
        any_checked = False
        for i in range(self.list_widget.count()):
            w = self.list_widget.itemWidget(self.list_widget.item(i))
            if w is not None and w.isChecked():
                any_checked = True
                break
        if any_checked:
            self.btn_do_migrate.show()
            self.btn_do_migrate.setEnabled(True)
        else:
            self.btn_do_migrate.hide()

    def _refresh_cfree(self):
        """刷新 C 盘实时容量显示（操作前/后各调一次即可算出真实释放量）。"""
        total, _used, free = c_drive_usage()
        self.lbl_cfree.setText(f"C 盘容量：总 {bytes_human(total)} ｜ 可用 {bytes_human(free)}"
                               + (f" ｜ 本次操作前可用 {bytes_human(self.c_free_before)}"
                                  if self.c_free_before else ""))

    def on_migrate_click(self):
        """【开始迁移】入口：整段 try/except 兜底，任何异常只弹窗报告，绝不让软件闪退。"""
        try:
            self._on_migrate_click_impl()
        except SystemExit:
            raise
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                self.log(f"【C盘文件迁出】执行出错：{e}", color="red")
                self.log(tb, color="red")
            except Exception:
                pass
            QMessageBox.critical(
                self, "执行出错（软件未退出）",
                "文件迁出准备阶段出现异常，操作已中止，未迁移的源文件保持原样：\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "如重复出现，请把下方日志截图反馈。")

    def _on_migrate_click_impl(self):
        """【开始迁移】按钮：收集勾选项 -> 自动选非C盘+建落地文件夹 -> 容量校验 -> 迁移。"""
        # 惰性触发：访问该功能时也校验一次受管资源
        try:
            run_resource_guardian("feature:migrate")
        except Exception:
            pass
        selected_paths = []
        high_picked = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            w = self.list_widget.itemWidget(item)
            if w is None:
                continue
            if w.isChecked():
                real = w.property("path") or w.text()
                selected_paths.append(real)
                if self._safe_risk(real) == "high":
                    high_picked.append(real)
        if not selected_paths:
            QMessageBox.warning(self, "提示", "没有勾选任何目录！")
            return

        # 记录迁移前的 C 盘可用空间（实时查询），迁移结束后再查一次，差值=真实释放量
        self.c_free_before = c_drive_usage()[2]
        self._refresh_cfree()
        self.log(f"迁移前 C 盘可用空间：{bytes_human(self.c_free_before)}（系统实时查询）", color="blue")

        if high_picked:
            reply = QMessageBox.warning(
                self, "高危警告",
                "你勾选了 %d 个系统/应用核心目录，迁移（=复制后删除源文件）可能导致:\n"
                "  · 软件无法启动、配置丢失\n"
                "  · 系统功能异常、需重新登录\n\n"
                "是否仍要继续？" % len(high_picked),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                self.log("用户取消了高危迁移操作。")
                return

        # 自动选择非 C 盘符：只挑【本地固定硬盘 + 真实可写】（自动跳过 Z: 只读共享映射盘），
        # 按剩余空间从大到小逐个尝试创建落地文件夹「非c盘文件迁移落脚点」
        candidates = list_writable_fixed_drives()
        target_dir = None
        drive = None
        last_err = None
        for drv in candidates:
            td = os.path.join(drv, "非c盘文件迁移落脚点")
            try:
                os.makedirs(td, exist_ok=True)
                target_dir = td
                drive = drv
                break
            except Exception as e:
                last_err = e
                self.log(f"⚠️ {drv} 创建落地文件夹失败（{e}），尝试下一个候选盘...", color="gray")

        if target_dir is None:
            if last_err is not None:
                self.log(f"⚠️ 所有候选盘均创建失败：{last_err}", color="red")
            QMessageBox.warning(
                self, "无可用盘",
                "未找到任何【可写的本地非 C 盘】（D:/E:/F: 等本地硬盘）。\n"
                "（只读的网络映射盘 / 共享目录盘 / 光驱已自动跳过）\n\n"
                "请先在「磁盘管理」里准备一个本地非 C 盘；\n"
                "或点击确定后手动选择一个非 C 盘目标目录。")
            target_dir = QFileDialog.getExistingDirectory(self, "手动选择迁移目标目录（必须是非 C 盘）")
            if not target_dir or target_dir.lower().startswith("c:"):
                self.log("未选择有效的非 C 盘目标目录，已取消迁移。", color="gray")
                return
            self.log(f"用户手动指定目标目录：{target_dir}", color="gray")
        else:
            self.log(f"✅ 已自动选择目标盘 {drive}（本地硬盘·剩余空间最大），落地文件夹：{target_dir}", color="green")
            # 明确弹窗告知用户：已自动选择哪个盘、建了哪个文件夹（避免“点了没反应”的错觉）
            QMessageBox.information(
                self, "已自动选择迁移目标",
                f"已自动选择剩余空间最大的本地非 C 盘：{drive}\n"
                f"并已在其下创建落地文件夹：\n{target_dir}\n\n"
                f"接下来将计算选中文件总大小并做容量校验，请点击【确认并开始迁移】。")

        cap_dlg = MigrateCapacityDialog(self, selected_paths, target_dir, dark=self.dark_mode)
        if cap_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        self.mig_progress_bar.setValue(0)
        self.mig_progress_label.setText("迁移实时进度：0% | 开始复制")
        self.worker = MigrateWorker(selected_paths, target_dir, cap_dlg.total_size_bytes)
        self.worker.progress_update.connect(self.on_mig_progress)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_mig_finish)
        self.worker.start()
        self.btn_do_migrate.setEnabled(False)
        self.btn_scan.setEnabled(False)

    def on_mig_progress(self, pct, current_file):
        self.mig_progress_bar.setValue(pct)
        self.mig_progress_label.setText(f"迁移实时进度：{pct}% | 当前文件：{os.path.basename(current_file)}")

    def on_mig_finish(self, success_flag):
        self.btn_scan.setEnabled(True)
        if success_flag:
            self.mig_progress_label.setText("迁移实时进度：100% | 任务全部完成")
        else:
            self.mig_progress_label.setText("迁移实时进度：任务存在失败项，请查看日志")

        # ---- C 盘真实空间变化（迁移前/后各实时查一次，绝不估算） ----
        after = c_drive_usage()[2]
        before = self.c_free_before if self.c_free_before else after
        delta = after - before
        self._refresh_cfree()
        self.log(f"迁移后 C 盘可用空间：{bytes_human(after)}（系统实时查询）", color="blue")
        self.log(f"C 盘可用空间变化：{'+' if delta >= 0 else '-'}{bytes_human(abs(delta))}"
                 f"{'（已释放）' if delta >= 0 else '（可用空间反而减少）'}",
                 color="green" if delta >= 0 else "red")
        self.c_free_before = None
        CapacityResultDialog(
            self, title="C 盘空间变化报告（文件迁出）", before=before, after=after,
            moved_bytes=getattr(self.worker, "copied_bytes", 0) if self.worker else 0,
            detail="迁移完成：文件已复制到非 C 盘并从 C 盘删除。若个别目录因被占用而未删除源，"
                   "该部分空间尚未释放，日志中有明确记录。",
            dark=self.dark_mode).exec()
        try:
            log_text = self.log_box.toPlainText()
            log_save_path = os.path.join(self.worker.target_root, "迁移日志.txt")
            with open(log_save_path, "w", encoding="utf-8") as f:
                f.write(log_text)
            self.log(f"✅ 迁移日志已保存到：{log_save_path}", "green")
        except Exception as e:
            self.log(f"⚠️ 迁移日志保存失败：{str(e)}", "red")
        self.worker = None
        # 迁移完成：已迁出的文件夹已从C盘删除，清空列表并隐藏【开始迁移】，等待下一次扫描
        self.list_widget.clear()
        self.scan_items = []
        self.btn_do_migrate.hide()

    def deploy_bootstrap_files(self, write_flag: bool = True, flag_state: str = "RESET_RUNNING"):
        """把当前 exe 预埋到非 C 盘目录（C 盘被清后计划任务还能找到它），并按需写运行标志。
        write_flag=False 时不写标志（仅补齐 exe，不触发开机通知）。"""
        try:
            target = get_bootstrap_dir()
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            self.log(f"⚠️ 预埋目录创建失败：{e}", "red")
            return False
        # 合并版：预埋的是同一个exe（C盘利刃.exe）
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
        try:
            if os.path.exists(exe_path):
                shutil.copy2(exe_path, os.path.join(target, NOTIFY_EXE_NAME))
                self.log(f"已预埋程序到 {target}")
        except Exception as e:
            self.log(f"⚠️ 预埋程序复制失败（不影响重置流程）：{e}", "red")
            return False
        if write_flag:
            flag = get_flag_running_path()
            try:
                with open(flag, "w", encoding="utf-8") as f:
                    f.write(flag_state)
                self.log(f"标记文件已写入：{flag}（{flag_state}）")
            except Exception as e:
                self.log(f"⚠️ 标记文件写入失败（不影响重置流程）：{e}", "red")
        return True

    def on_init_click(self):
        """【C盘初始化】入口：高危确认 -> 预检 -> PBR重置 / 降级文件清理。
        整段 try/except 兜底：任何异常只弹窗报告，绝不让软件闪退。"""
        try:
            self._on_init_click_impl()
        except SystemExit:
            raise
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                self.log(f"【C盘初始化】执行出错：{e}", color="red")
                self.log(tb, color="red")
            except Exception:
                pass
            QMessageBox.critical(
                self, "执行出错（软件未退出）",
                "C盘初始化过程中出现异常，操作已中止，您的数据未被改动：\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "如重复出现，请把下方日志截图反馈。")

    def _on_init_click_impl(self):
        msg_text = """⚠️ 极高风险警告：C盘初始化（文件清理模式）

本工具将【删除 C 盘全部个人文件与第三方软件】（含各用户档案 AppData、桌面、文档、下载等），
仅保留 Windows 系统本身及其内置组件目录（Program Files 下的 Common Files、Internet Explorer、
Windows Defender、Windows NT、WindowsPowerShell、Windows Media Player 等永不删除，
以确保系统重置 PBR/WinRE 仍可正常执行）。
⚠️ 操作不可逆，删除后 C 盘资料无法恢复；D/E 盘文件不受影响。

执行时界面会显示实时进度，并可随时点击【取消】中止（已删除的部分不会恢复）。

强烈建议：优先使用【C盘文件迁出】模块，把重要资料备份到 D/E 后再执行。

确认继续执行 C盘初始化？"""
        mb = QMessageBox(self)
        mb.setWindowTitle("高危确认 - C盘利刃")
        mb.setText(msg_text)
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        mb.setIcon(QMessageBox.Icon.Critical)
        if mb.exec() != QMessageBox.StandardButton.Yes:
            return

        # 预检改后台线程：manage-bde / reagentc 等同步跑会冻结界面数秒到数十秒
        self.log("===== 开始C盘初始化预检（后台检测 BitLocker / 域环境 / 系统版本，界面不卡） =====")
        if self.precheck_worker is not None and self.precheck_worker.isRunning():
            return
        self.btn_init.setEnabled(False)
        self.precheck_worker = PrecheckWorker()
        self.precheck_worker.done.connect(self._on_precheck_done)
        self.precheck_worker.start()

    def _on_precheck_done(self, bitlock_on, domain, ver):
        self.btn_init.setEnabled(True)
        self.precheck_worker = None
        self.log(f"系统版本:{ver}")
        self.log(f"BitLocker状态: {'已开启' if bitlock_on else '关闭'}")
        self.log(f"域环境: {'是' if domain else '否'}")
        if bitlock_on:
            QMessageBox.warning(self, "BitLocker警告", "检测到C盘BitLocker已开启，请提前保存恢复密钥！")
        if domain:
            QMessageBox.warning(self, "域环境警告", "当前电脑加入域，组策略可能限制清理范围！")
        self.file_clean_mode()

    def file_clean_mode(self):
        # 后台线程执行：先预扫描出「将删除清单」让用户二次确认，再后台删除并显示实时进度。
        # 保护规则与旧版完全一致（Default/Public/All Users、WHITE_LIST、系统根目录不动）。
        # 惰性触发：访问该功能时也校验一次受管资源（本体/图标/快捷方式）
        try:
            run_resource_guardian("feature:clean")
        except Exception:
            pass
        try:
            targets = plan_clean_targets()
        except Exception as e:
            QMessageBox.critical(self, "扫描失败", f"预扫描出错：{e}")
            return
        if not targets:
            QMessageBox.information(self, "无需清理", "未发现可清理的非系统目录。")
            return
        dlg = CleanScanDialog(self, targets=targets, dark=self.dark_mode)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.log("用户取消了 C盘初始化。", "gray")
            return
        # 重置真正开始：把 exe 预埋到非 C 盘并写下运行标志——
        # C 盘清完之后，开机计划任务靠非C盘上的这个副本弹重置结果通知
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.deploy_bootstrap_files(write_flag=True, flag_state="RESET_RUNNING")
        finally:
            QApplication.restoreOverrideCursor()
        self.c_free_before = c_drive_usage()[2]
        self._refresh_cfree()
        self.log(f"清理前 C 盘可用空间：{bytes_human(self.c_free_before)}（系统实时查询）", "blue")
        self.worker = CleanWorker(targets)
        self.worker.log_signal.connect(self.log)
        self._clean_cancelled = None
        self.worker.finished_signal.connect(self._on_clean_finished_state)
        pd = CleanProgressDialog(self, worker=self.worker, dark=self.dark_mode)
        self.worker.start()
        pd.exec()  # 模态但界面不卡：进度/取消均走后台线程信号
        self._finalize_reset_flag(self._clean_cancelled)
        after = c_drive_usage()[2]
        before = self.c_free_before
        delta = after - before
        self._refresh_cfree()
        self.log(f"清理后 C 盘可用空间：{bytes_human(after)}（系统实时查询）", "blue")
        self.log(f"C 盘可用空间变化：{'+' if delta >= 0 else '-'}{bytes_human(abs(delta))}"
                 f"{'（已释放）' if delta >= 0 else '（可用空间反而减少）'}",
                 color="green" if delta >= 0 else "red")
        self.c_free_before = None
        CapacityResultDialog(
            self, title="C 盘空间变化报告（C盘初始化·文件清理）", before=before, after=after,
            moved_bytes=0, show_moved=False,
            detail="文件清理模式：后台线程逐顶层目录删除，执行期间界面实时显示进度且可随时取消。<br>"
                   "已保留未删：C:\\Windows，以及 Program Files / Program Files (x86) 下的 "
                   "Windows 内置组件（Common Files、Internet Explorer、Windows Defender、Windows NT、"
                   "WindowsPowerShell、Windows Media Player 等）—— 删除这些会导致系统自身重置"
                   "（PBR / WinRE）失败，因此始终不动。<br>"
                   "被占用而删不掉的目录同样会保留，日志中有明确记录。",
            dark=self.dark_mode).exec()
        self.worker = None

    def _on_clean_finished_state(self, cancelled, summary):
        """记录清理线程的结束状态（供 _finalize_reset_flag 判断该写成功标志还是撤标志）。"""
        self._clean_cancelled = bool(cancelled)

    def _finalize_reset_flag(self, cancelled):
        """重置收尾：完成 -> 标志改 RESET_OK（下次开机弹成功）；
        用户主动取消 -> 撤掉标志（不弹通知）；进程崩溃/断电 -> 标志停在 RESET_RUNNING（弹失败+日志）。"""
        flag = get_flag_running_path()
        try:
            if cancelled:
                if os.path.exists(flag):
                    os.remove(flag)
                self.log("已取消重置，开机提醒标志已撤除（不会弹通知）", "gray")
                return
            with open(flag, "w", encoding="utf-8") as f:
                f.write("RESET_OK")
            self.log(f"重置完成标志已写入：{flag}（下次开机自动弹出结果通知）", "green")
        except OSError as e:
            self.log(f"⚠️ 重置标志更新失败（不影响本次清理）：{e}", "red")

    def show_help_dialog(self):
        dlg = HelpDialog(self, dark=self.dark_mode)
        dlg.exec()

    def show_about_dialog(self):
        dlg = AboutDialog(self, dark=self.dark_mode)
        dlg.exec()


# ===================== 帮助文档弹窗（玻璃拟态） =====================
class HelpDialog(GlassDialog):
    def __init__(self, parent=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("帮助文档")
        self.resize(780, 600)
        lay = QVBoxLayout(self)
        text_box = QTextEdit()
        text_box.setReadOnly(True)
        text_box.setPlainText(HELP_TEXT)
        lay.addWidget(text_box, 1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close)


# ===================== 关于作者 & 商务合作弹窗（玻璃拟态） =====================
class AboutDialog(GlassDialog):
    def __init__(self, parent=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("关于作者 & 商务合作 - C盘利刃")
        self.resize(720, 600)
        lay = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml(about_html())
        lay.addWidget(text, 1)
        row = QHBoxLayout()
        btn_copy = QPushButton("复制邮箱")
        btn_mail = QPushButton("发邮件")
        btn_site = QPushButton("访问开源主页")
        btn_close = QPushButton("关闭")
        row.addWidget(btn_copy)
        row.addWidget(btn_mail)
        row.addWidget(btn_site)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        btn_copy.clicked.connect(self.copy_email)
        btn_mail.clicked.connect(self.open_mail)
        btn_site.clicked.connect(self.open_site)
        btn_close.clicked.connect(self.accept)

    def copy_email(self):
        QApplication.clipboard().setText(AUTHOR_EMAIL)
        QMessageBox.information(self, "已复制", f"邮箱已复制到剪贴板：\n{AUTHOR_EMAIL}")

    def open_mail(self):
        QDesktopServices.openUrl(QUrl(f"mailto:{AUTHOR_EMAIL}"))

    def open_site(self):
        QDesktopServices.openUrl(QUrl(AUTHOR_SITE))


# ===================== 缓存搬家 UI（Junction 目录链接） =====================
def load_custom_rules() -> list:
    """读取用户自定义/改过的缓存目录规则（跨次启动记住）。"""
    try:
        with open(CUSTOM_RULES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [d for d in data if isinstance(d, dict) and d.get("src")]
    except Exception:
        return []


def save_custom_rules(rules: list):
    try:
        os.makedirs(os.path.dirname(CUSTOM_RULES_FILE), exist_ok=True)
        with open(CUSTOM_RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class EditPathDialog(GlassDialog):
    """编辑某条缓存目录的源路径 / 搬家后的目标路径（用户可自行指定 app 缓存放哪）。"""

    def __init__(self, parent=None, app="", src="", dst="", dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("编辑缓存目录路径")
        self.resize(720, 230)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        form = QFormLayout()
        self.ed_app = QLineEdit(app)
        self.ed_src = QLineEdit(src)
        self.ed_dst = QLineEdit(dst)
        form.addRow("应用名称：", self.ed_app)
        form.addRow("C 盘原目录（源）：", self.ed_src)
        form.addRow("搬到的目标目录：", self.ed_dst)
        lay.addLayout(form)
        tip = QLabel("目标目录必须位于非 C 盘（或网络存储）；源目录必须真实存在且不是链接。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#666;")
        lay.addWidget(tip)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self):
        return self.ed_app.text().strip(), self.ed_src.text().strip(), self.ed_dst.text().strip()


class CacheJunctionDialog(GlassDialog):
    """缓存搬家主窗口：自动检测会产生缓存的应用 -> 勾选 -> 搬到非 C 盘并在原位建目录链接。
    应用照旧读写原路径，实际空间落在目标盘，C 盘真正瘦身且不会被应用重建回弹。"""

    def __init__(self, parent=None, dark=False):
        super().__init__(parent, dark)
        self.setWindowTitle("缓存搬家 · Junction 目录链接")
        self.resize(920, 660)
        self.rows = []              # [{'app','src','dst','size','junction','target','custom'}]
        self.worker = None
        self.scan_worker = None
        self._last_clicked = None
        self.custom_rules = load_custom_rules()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        title = QLabel("缓存搬家（Junction 目录链接）")
        title.setStyleSheet("font-size:17px;font-weight:bold;")
        lay.addWidget(title)
        tip = QLabel("自动检测会产生缓存的应用。搬家后实体文件搬到目标盘，C 盘原位保留一个“传送门”，"
                     "应用无感知照常读写，C 盘空间真正释放且不会被应用重建。\n"
                     "操作：单击行=勾选/取消  双击行=编辑路径  选中后按 Del=移出列表。"
                     "🔗 项 = 已搬完的链接，勾选它再点【还原】即可搬回 C 盘（点开始搬家会自动跳过）；"
                     "嫌占地方就勾【隐藏已完成项】；点【开始搬家】会自动续做上次没完成的部分。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#555;")
        lay.addWidget(tip)

        # 目标根目录
        root_lay = QHBoxLayout()
        root_lay.addWidget(QLabel("搬家到："))
        self.ed_root = QLineEdit(self._default_root())
        root_lay.addWidget(self.ed_root, 1)
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self.on_browse)
        root_lay.addWidget(self.btn_browse)
        lay.addLayout(root_lay)

        # C 盘容量条：搬家/还原前后各实时查一次，算出真实释放量
        self.c_free_before = None
        self.job_bytes = 0
        self.lbl_cfree = QLabel("C 盘容量：读取中…")
        self.lbl_cfree.setStyleSheet("font-size:11pt; font-weight:bold; color:#1565c0;")
        lay.addWidget(self.lbl_cfree)
        self._refresh_cfree()

        lay.addWidget(QLabel("检测到的缓存目录（单击勾选，双击编辑）："))
        self.list_widget = RubberBandList()   # 与主窗口同一套点击/框选勾选逻辑（鼠标点击实测可靠）
        self.list_widget.setUniformItemSizes(True)   # 行高一致：滚动/布局开销大幅下降
        lay.addWidget(self.list_widget, 1)

        row1 = QHBoxLayout()
        self.btn_rescan = QPushButton("重新检测")
        self.btn_toggle_all = QPushButton("全选/全不选")
        self.btn_add = QPushButton("添加自定义目录")
        for b in (self.btn_rescan, self.btn_toggle_all, self.btn_add):
            row1.addWidget(b)
        row1.addStretch(1)
        self.hide_done = QCheckBox("隐藏已完成项(🔗)")
        self.hide_done.setToolTip("已搬家的目录是灰色的链接项，勾上后直接从列表里隐藏，界面更清爽")
        self.hide_done.stateChanged.connect(self.on_hide_done_changed)
        row1.addWidget(self.hide_done)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_start = QPushButton("开始搬家（自动续做未完成项）")
        self.btn_revert = QPushButton("还原（拆链接搬回来）")
        self.btn_close = QPushButton("关闭")
        for b in (self.btn_start, self.btn_revert, self.btn_close):
            row2.addWidget(b)
        lay.addLayout(row2)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFixedHeight(120)
        self.log_box.document().setMaximumBlockCount(20000)   # 限长防膨胀
        lay.addWidget(self.log_box)

        self.btn_rescan.clicked.connect(self.refresh)
        self.btn_toggle_all.clicked.connect(self.on_toggle_all)
        self.btn_add.clicked.connect(self.on_add)
        self.btn_start.clicked.connect(lambda: self.run_job("move"))
        self.btn_revert.clicked.connect(lambda: self.run_job("revert"))
        self.btn_close.clicked.connect(self.close)
        self.list_widget.itemDoubleClicked.connect(lambda _i: self.on_edit())
        self.list_widget.keyDelete.connect(self.on_del)
        self.list_widget.rowClicked.connect(self._on_row_clicked)

        # 日志批量刷新缓冲（与主窗口同款：120ms 合一帧，避免搬家时逐条重绘）
        self._log_buf = []
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(120)
        self._log_timer.timeout.connect(self._flush_log)
        # 扫描代次：重复点【重新检测】时忽略旧 worker 的迟到信号
        self._scan_gen = 0

        self.refresh()

    # ---------- 基础 ----------
    def _default_root(self) -> str:
        d = find_non_c_drive()
        if d:
            return os.path.join(d, "ResetBladeCache")
        # 没有第二块盘时，回退到共享/网络位置（用户也可自行浏览选择）
        for cand in (r"\\vboxsvr\share2\ResetBladeCache",):
            if os.path.isdir(os.path.dirname(cand)):
                return cand
        return ""

    def log(self, msg, color="black"):
        self._log_buf.append((str(msg), color))
        if not self._log_timer.isActive():
            self._log_timer.start()

    def _flush_log(self):
        if not self._log_buf:
            self._log_timer.stop()
            return
        batch, self._log_buf = self._log_buf, []
        cmap = {"black": "#222", "red": "#c0392b", "green": "#1e8449",
                "gray": "#777", "blue": "#1565c0"}
        for msg, color in batch:
            self.log_box.append(f'<span style="color:{cmap.get(color, "#222")}">{msg}</span>')
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_cfree(self):
        total, _used, free = c_drive_usage()
        self.lbl_cfree.setText(f"C 盘容量：总 {bytes_human(total)} ｜ 可用 {bytes_human(free)}"
                               + (f" ｜ 本次操作前可用 {bytes_human(self.c_free_before)}"
                                  if self.c_free_before else ""))

    def on_browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择缓存搬到的目标位置")
        if d:
            self.ed_root.setText(d)

    # ---------- 检测 ----------
    def refresh(self):
        self.list_widget.clear()
        self.rows = []
        self.log("正在检测已安装应用的缓存目录...", "gray")
        # 停掉上一个还在跑的扫描线程（信号已随代次隔离，迟到结果会被丢弃）
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.stop()
        self._scan_gen += 1
        gen = self._scan_gen
        extra = [{"name": r.get("app", "自定义"), "detect": [], "dirs": [r["src"]]}
                 for r in self.custom_rules]
        self.scan_worker = JunctionScanWorker(extra)
        self.scan_worker.item.connect(lambda *a: self._on_scan_item(gen, *a))
        self.scan_worker.finished_all.connect(lambda: self._on_scan_done(gen))
        self.scan_worker.start()

    def _on_scan_item(self, gen, src, size, junction, target):
        if gen != self._scan_gen:
            return          # 旧 worker 的迟到结果，丢弃
        self._add_row(src, size, junction, target)

    def _on_scan_done(self, gen):
        if gen != self._scan_gen:
            return
        self.log(f"检测完成，共 {self.list_widget.count()} 项", "gray")

    def _add_row(self, src, size, junction, target):
        app = "自定义"
        for r in CACHE_APP_RULES:
            for d in r.get("dirs", []):
                if _expand(d).lower() == src.lower():
                    app = r["name"]
        root = self.ed_root.text().strip()
        dst = os.path.join(root, _safe_name(app), os.path.basename(src.rstrip("\\"))) if root else ""
        row = {"app": app, "src": src, "dst": dst, "size": size,
               "junction": junction, "target": target or "",
               "custom": src.lower() in [c["src"].lower() for c in self.custom_rules]}
        self.rows.append(row)
        if not (self.hide_done.isChecked() and junction):
            self._add_item(len(self.rows) - 1)

    def _add_item(self, idx: int):
        """按 rows[idx] 往列表里加一条（隐藏已完成时，已搬家项不入列）。"""
        row = self.rows[idx]
        it = QListWidgetItem()
        it.setData(Qt.ItemDataRole.UserRole, idx)
        self.list_widget.addItem(it)
        w = QCheckBox(self._row_text(row))
        if row["junction"]:
            # 已搬家的项默认不勾（搬家无意义），但必须可勾选——用户要靠勾选它来做【还原】
            w.setChecked(False)
            w.setToolTip("已搬家的目录链接：勾选后点【还原】可把数据搬回 C 盘；"
                         "点【开始搬家】时会自动跳过，不会重复搬运。")
        else:
            w.setChecked(True)
            w.setToolTip("待搬家的缓存目录：勾选后点【开始搬家】搬到目标盘并在原位建链接。")
        self.list_widget.setItemWidget(it, w)

    def on_hide_done_changed(self):
        """切换"隐藏已完成项"：整表重建（只改可见性，不动数据）。"""
        self.list_widget.clear()
        self._last_clicked = None
        hidden = 0
        for idx, row in enumerate(self.rows):
            if self.hide_done.isChecked() and row["junction"]:
                hidden += 1
                continue
            self._add_item(idx)
        self._last_clicked = None
        self.log(f"列表已更新：显示 {self.list_widget.count()} 项"
                 f"{f'，已隐藏 {hidden} 个已完成项' if hidden else ''}", "gray")

    def _on_row_clicked(self, idx: int):
        self._last_clicked = idx

    def on_toggle_all(self):
        n_checked = sum(1 for i in range(self.list_widget.count())
                        if self._row_widget(i) and self._row_widget(i).isChecked()
                        and self._row_widget(i).isEnabled())
        n_active = sum(1 for i in range(self.list_widget.count())
                       if self._row_widget(i) and self._row_widget(i).isEnabled())
        target = n_checked < n_active     # 有未勾选的活动行 -> 全选；否则全不选
        # 批量勾选期间屏蔽复选框信号，避免每个 setChecked 都触发一次全表刷新
        for i in range(self.list_widget.count()):
            w = self._row_widget(i)
            if w and w.isEnabled():
                w.blockSignals(True)
                w.setChecked(target)
                w.blockSignals(False)

    def _row_widget(self, i: int):
        return self.list_widget.itemWidget(self.list_widget.item(i))

    def _row_text(self, r):
        if r["junction"]:
            return f'🔗 {r["app"]}  {r["src"]}  →  已搬家到 {r["target"]}（勾选后点【还原】可搬回）'
        sz = bytes_human(r["size"]) if r["size"] else "?"
        return f'💾 {r["app"]}  {r["src"]}  （{sz}）  →  {r["dst"] or "未设置目标"}'

    def _refresh_texts(self):
        for i in range(self.list_widget.count()):
            w = self._row_widget(i)
            if w:
                idx = self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                w.setText(self._row_text(self.rows[idx]))

    def _checked_rows(self):
        out = []
        for i in range(self.list_widget.count()):
            w = self._row_widget(i)
            if w and w.isEnabled() and w.isChecked():
                idx = self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                out.append(self.rows[idx])
        return out

    def _current_row(self):
        it = self.list_widget.currentItem()
        if it is None:
            return None
        return self.rows[it.data(Qt.ItemDataRole.UserRole)]

    # ---------- 编辑 / 增删 ----------
    def _active_row(self):
        """优先取最后单击的行（NoSelection 模式下 currentItem 不可靠），键盘导航的 current 作后备。"""
        if self._last_clicked is not None and self._last_clicked < len(self.rows):
            it = self.list_widget.item(self._last_clicked)
            if it is not None:
                return self.rows[it.data(Qt.ItemDataRole.UserRole)]
        return self._current_row()

    def on_edit(self):
        row = self._active_row()
        if row is None:
            QMessageBox.information(self, "提示", "请先在列表里点一下某一行")
            return
        d = EditPathDialog(self, row["app"], row["src"], row["dst"], dark=self.dark)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        app, src, dst = d.values()
        if src and not os.path.isdir(src):
            QMessageBox.warning(self, "路径无效", f"源目录不存在：\n{src}")
            return
        if dst and os.path.splitdrive(dst)[0].upper().startswith("C"):
            QMessageBox.warning(self, "路径无效", "目标目录不能位于 C 盘")
            return
        row["app"], row["src"], row["dst"] = app, src, dst
        if not any(c["src"].lower() == src.lower() for c in self.custom_rules):
            self.custom_rules.append({"app": app, "src": src})
            save_custom_rules(self.custom_rules)
        self._refresh_texts()
        self.log(f"已更新：{src} → {dst}", "blue")

    def on_add(self):
        d = EditPathDialog(self, "自定义", "", "", dark=self.dark)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        app, src, dst = d.values()
        if not src or not os.path.isdir(src):
            QMessageBox.warning(self, "路径无效", "请填写真实存在的 C 盘目录")
            return
        if junction_forbidden(src):
            QMessageBox.warning(self, "受保护目录", "系统/程序目录不允许搬家，请换一个缓存目录")
            return
        self.rows.append({"app": app or "自定义", "src": src, "dst": dst, "size": 0,
                          "junction": is_junction(src), "target": read_junction_target(src) or "",
                          "custom": True})
        idx = len(self.rows) - 1
        it = QListWidgetItem()
        it.setData(Qt.ItemDataRole.UserRole, idx)
        self.list_widget.addItem(it)
        self.list_widget.setItemWidget(it, QCheckBox(self._row_text(self.rows[idx])))
        if not any(c["src"].lower() == src.lower() for c in self.custom_rules):
            self.custom_rules.append({"app": app or "自定义", "src": src})
            save_custom_rules(self.custom_rules)
        self.log(f"已添加自定义目录：{src}", "blue")

    def on_del(self):
        row = self._active_row()
        if row is None:
            QMessageBox.information(self, "提示", "请先在列表里点一下要移除的行")
            return
        # 按行号定位（rows 与列表项一一对应）
        it_idx = None
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if self.rows[it.data(Qt.ItemDataRole.UserRole)] is row:
                it_idx = i
                break
        if it_idx is None:
            return
        if row.get("custom"):
            self.custom_rules = [c for c in self.custom_rules if c["src"].lower() != row["src"].lower()]
            save_custom_rules(self.custom_rules)
        self.list_widget.takeItem(it_idx)
        self._last_clicked = None
        self.log(f"已移出列表：{row['src']}", "gray")

    # ---------- 执行 ----------
    def run_job(self, mode):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示", "任务正在执行中")
            return
        rows = self._checked_rows()

        # 还原场景：用户常搞不清"要先勾已搬家项"，这里没勾就自动帮他勾上所有已搬家项
        if mode == "revert":
            if not any(r["junction"] for r in self.rows):
                QMessageBox.information(self, "无可还原项", "当前列表里没有已搬家的目录链接，无需还原。")
                return
            if not any(r["junction"] for r in rows):
                for i in range(self.list_widget.count()):
                    it = self.list_widget.item(i)
                    w = self.list_widget.itemWidget(it)
                    if w and self.rows[it.data(Qt.ItemDataRole.UserRole)]["junction"]:
                        w.setChecked(True)
                rows = self._checked_rows()
                self.log(f"已自动选中 {len(rows)} 个已搬家项用于还原", "blue")
        if not rows:
            QMessageBox.information(self, "提示", "请先勾选要处理的目录")
            return
        root = self.ed_root.text().strip()
        if mode == "move" and not root:
            QMessageBox.warning(self, "缺少目标", "请先选择（或填写）缓存搬到的目标位置")
            return
        items = []
        skipped_done = 0
        for r in rows:
            if mode == "move" and r["junction"]:
                skipped_done += 1      # 已搬家项在搬家里无意义，自动跳过
                continue
            dst = r["dst"] or (os.path.join(root, _safe_name(r["app"]),
                                            os.path.basename(r["src"].rstrip("\\"))) if root else "")
            if mode == "move" and not dst:
                continue
            items.append({"app": r["app"], "src": r["src"], "dst": dst})
        if skipped_done:
            self.log(f"⊙ 已跳过 {skipped_done} 个已搬家项（无需重复搬家，要搬回请用【还原】）", "gray")
        if not items:
            return

        # 记录操作前 C 盘可用空间（实时查询），结束后再查一次 = 真实释放量
        self.c_free_before = c_drive_usage()[2]
        self.job_bytes = sum(r.get("size", 0) for r in rows)
        self._refresh_cfree()
        self.log(f"操作前 C 盘可用空间：{bytes_human(self.c_free_before)}（系统实时查询）", "blue")
        self.log(f"===== 开始{'还原' if mode == 'revert' else '搬家'}（{len(items)} 项）=====", "blue")
        self.worker = JunctionWorker(items, root, mode)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(lambda ok, fail: self.on_job_done(ok, fail, mode))
        self.worker.start()

    def on_job_done(self, ok_n, fail_n, mode="move"):
        self.log(f"处理结束：成功 {ok_n}，失败/待完成 {fail_n}", "green" if ok_n else "red")
        after = c_drive_usage()[2]
        before = self.c_free_before if self.c_free_before else after
        delta = after - before
        self.log(f"操作后 C 盘可用空间：{bytes_human(after)}（系统实时查询）", "blue")
        self.log(f"C 盘可用空间变化：{'+' if delta >= 0 else '-'}{bytes_human(abs(delta))}"
                 f"{'（已释放）' if delta >= 0 else '（可用空间反而减少）'}",
                 "green" if delta >= 0 else "red")
        CapacityResultDialog(
            self, title=f"C 盘空间变化报告（缓存{'搬家' if mode == 'move' else '还原'}）",
            before=before, after=after, moved_bytes=self.job_bytes,
            detail="搬家=实体搬到目标盘、C 盘原位留链接，C 盘空间立刻释放且应用照常读写；"
                   "还原=把实体搬回 C 盘并拆掉链接，C 盘可用空间会相应减少。"
                   "若某项因应用占用而只复制未删除源，该部分空间暂未释放，日志有明确记录。",
            dark=self.dark).exec()
        self.c_free_before = None
        self.job_bytes = 0
        self._refresh_cfree()
        self.refresh()


def run_selftest_migrate(argv):
    """命令行自检模式：真实调用产品自身的 MigrateWorker 逻辑做一次迁移，
    并输出可读的验证报告。用法：
        ResetBlade.exe --selftest-migrate <目标根目录> <源目录1> [源目录2 ...]
    结果同时写入 <目标根目录>/_selftest_report.txt
    """
    args = [a for a in argv[1:] if a != "--selftest-migrate"]
    if len(args) < 2:
        print("USAGE: ResetBlade.exe --selftest-migrate <target_root> <src1> [src2 ...]")
        return 2
    target_root = args[0]
    sources = args[1:]

    out_lines = []

    def emit(msg):
        print(msg)
        out_lines.append(msg)

    emit("=" * 68)
    emit("ResetBlade 迁移功能自检 (调用产品自身 MigrateWorker 逻辑)")
    emit("=" * 68)
    emit(f"目标根目录 : {target_root}")
    emit(f"源目录数量 : {len(sources)}")

    # 1) 容量校验（复刻 MigrateCapacityDialog 的判断）
    total_bytes = 0
    for src in sources:
        if not os.path.isdir(src):
            emit(f"  [跳过] 源目录不存在: {src}")
            continue
        for dirpath, dirnames, filenames in os.walk(src):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    if not os.path.islink(fp):
                        total_bytes += os.path.getsize(fp)
                except OSError:
                    pass
    emit(f"待迁移总容量: {bytes_human(total_bytes)}")

    try:
        drive = os.path.splitdrive(target_root)[0]
        free_bytes = get_disk_free(target_root)
    except Exception as e:
        emit(f"[致命] 无法读取目标盘剩余空间: {e}")
        return 3
    emit(f"目标盘剩余空间: {bytes_human(free_bytes)}  (盘符 {drive})")

    if target_root.lower().startswith("c:"):
        emit("[致命] 禁止迁移到 C 盘 —— 与产品校验逻辑一致，终止。")
        return 4
    if free_bytes < total_bytes:
        emit("[致命] 空间不足 —— 与产品校验逻辑一致，终止。")
        return 5
    emit("[校验通过] 容量与目标盘检查 OK")

    os.makedirs(target_root, exist_ok=True)

    # 2) 记录迁移前快照（用于验证源是否真的被删除）
    before = {}
    for src in sources:
        if os.path.isdir(src):
            cnt = sum(len(f) for _, _, f in os.walk(src))
            before[src] = cnt

    # 3) 用事件循环驱动 MigrateWorker（真产品代码路径）
    app = QApplication.instance() or QApplication(sys.argv[:1])
    worker = MigrateWorker(sources, target_root, total_bytes)
    done = {"ok": False}

    def on_log(msg, color):
        emit("  [LOG] " + msg)

    def on_finish(ok):
        done["ok"] = ok
        app.quit()

    worker.log_signal.connect(on_log)
    worker.finished_signal.connect(on_finish)
    worker.progress_update.connect(lambda p, f: None)
    worker.finished_signal.connect(lambda _o: app.quit())
    worker.start()

    timer = QTimer()
    timer.timeout.connect(lambda: worker.stop())
    timer.start(600000)  # 10 分钟上限
    app.exec()
    worker.wait(15000)

    emit("-" * 68)
    emit("[结果] MigrateWorker 报告 success = %s" % done["ok"])

    # 4) 逐项核验：目标存在 + 源已删除 + 文件数一致
    all_verified = True
    emit("-" * 68)
    for src in sources:
        if src not in before:
            continue
        base = os.path.basename(src)
        dst = os.path.join(target_root, base)
        src_exists = os.path.exists(src)
        dst_exists = os.path.isdir(dst)
        dst_cnt = sum(len(f) for _, _, f in os.walk(dst)) if dst_exists else 0
        exp_cnt = before[src]
        ok = (not src_exists) and dst_exists and dst_cnt == exp_cnt
        all_verified = all_verified and ok
        emit(f"[核验] {src}")
        emit(f"         源是否已删除 : {'否(仍存在)' if src_exists else '是'}")
        emit(f"         目标目录     : {dst}  存在={dst_exists}")
        emit(f"         文件数       : 源 {exp_cnt} -> 目标 {dst_cnt}  一致={dst_cnt == exp_cnt}")
        emit(f"         结论         : {'PASS' if ok else 'FAIL'}")

    emit("=" * 68)
    final = "SELFTEST_PASS" if (all_verified and done["ok"]) else "SELFTEST_FAIL"
    emit(final)
    emit("=" * 68)

    try:
        with open(os.path.join(target_root, "_selftest_report.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines))
    except Exception as e:
        emit(f"(报告写入失败: {e})")

    return 0 if final == "SELFTEST_PASS" else 1


# ===================== 无人值守自检（共享盘标志文件触发，供虚拟机自动验证迁移） =====================
SELFTEST_FLAG_CANDIDATES = (
    r"\\vboxsvr\share2\rb_selftest.flag",
    r"D:\vm_share\rb_selftest.flag",
)
SELFTEST_REPORT_CANDIDATES = (
    r"\\vboxsvr\share2\rb_selftest_report.txt",
    r"D:\vm_share\rb_selftest_report.txt",
)

def run_selftest_flag():
    """存在共享盘标志文件时自动执行（无 GUI、无 UAC 提权）：
    1) 在 C 盘造一个真实测试源目录（文件+子目录）；
    2) 跑产品真实扫描 scan_c_migratable_fast + classify_risk，断言高危目录零入选；
    3) 用产品真实 MigrateWorker 把测试源目录迁移到共享盘（非 C 盘，物理离开 C 盘）；
    4) 核验：源已删除 / 目标存在 / 目标文件数与源一致。
    报告实时写回共享盘供宿主机读取；结束即删除标志文件，下次启动恢复正常 GUI。"""
    flag_path = next((p for p in SELFTEST_FLAG_CANDIDATES if os.path.exists(p)), None)
    report_path = next((p for p in SELFTEST_REPORT_CANDIDATES
                        if os.path.isdir(os.path.dirname(p))), None)
    lines = []

    def emit(msg):
        lines.append(str(msg))
        if report_path:
            try:
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except OSError:
                pass

    emit("=" * 70)
    emit(f"C盘利刃 V2.2 无人值守自检报告   {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    emit("=" * 70)

    if flag_path:
        try:
            os.remove(flag_path)   # 先删标志，防止异常退出后每次启动都进自检
            emit("[初始化] 标志文件已读取并删除（下次启动恢复正常 GUI）")
        except OSError as e:
            emit(f"[初始化] 标志文件删除失败（忽略）：{e}")
    else:
        emit("[初始化] 警告：未找到标志文件（防御性分支）")

    # ---- 1) 造测试源 ----
    src_root = r"C:\RB_Selftest_Src"
    try:
        shutil.rmtree(src_root, ignore_errors=True)
        os.makedirs(os.path.join(src_root, "sub1"), exist_ok=True)
        os.makedirs(os.path.join(src_root, "sub2", "deep"), exist_ok=True)
        files = {
            "hello.txt": "ResetBlade selftest 迁移测试 " * 20,
            os.path.join("sub1", "a.bin"): "A" * 65536,
            os.path.join("sub1", "b.txt"): "BB测试BB\n" * 500,
            os.path.join("sub2", "c.txt"): "CCCC" * 4096,
            os.path.join("sub2", "deep", "d.dat"): "D" * 131072,
        }
        for rel, content in files.items():
            with open(os.path.join(src_root, rel), "w", encoding="utf-8") as f:
                f.write(content)
        # 复刻真实场景：加一个 只读+隐藏+系统 属性的 desktop.ini
        # （用户资料夹里就有这种文件，普通 rmtree 会报"拒绝访问"导致"源目录删除失败"）
        ini = os.path.join(src_root, "desktop.ini")
        with open(ini, "w", encoding="utf-8") as f:
            f.write("[.ShellClassInfo]\nLocalizedResourceName=自检测试\n")
        ctypes.windll.kernel32.SetFileAttributesW(ini, 0x01 | 0x02 | 0x04)   # 只读|隐藏|系统
        files["desktop.ini"] = "[.ShellClassInfo]\n"
        expected_cnt = len(files)
        total_bytes = sum(len(c.encode("utf-8")) for c in files.values())
        emit(f"[步骤1] 测试源目录已创建：{src_root}（文件数 {expected_cnt}，共 {total_bytes} 字节）")
    except Exception as e:
        emit(f"[致命] 测试源创建失败：{e}")
        emit("SELFTEST_FAIL")
        return 1

    # ---- 2) 产品真实扫描 + 分类断言 ----
    no_high_selected = users_locked = appdata_locked = False
    try:
        paths = scan_c_migratable_fast(max_depth=2)
        safes = [p for p in paths if classify_risk(p) == "safe"]
        highs = [p for p in paths if classify_risk(p) != "safe"]
        emit(f"[步骤2] 产品真实扫描完成：共 {len(paths)} 目录，绿色可迁移 {len(safes)}，红色高危 {len(highs)}")
        no_high_selected = all(classify_risk(p) == "safe" for p in safes)
        users_locked = any(p.lower() == "c:\\users" for p in highs)
        appdata_locked = any(p.lower().startswith(r"c:\users\administrator\appdata") for p in highs)
        emit(f"        断言A 高危目录零入选             : {'PASS' if no_high_selected else 'FAIL'}")
        emit(rf"        断言B C:\Users 根目录在红区锁定  : {'PASS' if users_locked else 'FAIL'}")
        emit(rf"        断言C AppData 全部在红区锁定     : {'PASS' if appdata_locked else 'FAIL'}")
    except Exception as e:
        emit(f"[致命] 扫描失败：{e}")
        emit("SELFTEST_FAIL")
        return 1

    # ---- 3) 产品真实 MigrateWorker 迁移到非 C 盘（共享盘 = 宿主机 D 盘） ----
    target_root = r"\\vboxsvr\share2\RB_Selftest_Dst"
    try:
        shutil.rmtree(target_root, ignore_errors=True)
    except OSError:
        pass
    emit(f"[步骤3] 开始迁移：{src_root}  ->  {target_root}（非 C 盘）")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    worker = MigrateWorker([src_root], target_root, total_bytes)
    done = {"ok": False, "quit": False}

    def on_log(msg, color):
        if color in ("red", "green"):
            emit("    [迁移日志] " + msg)

    def on_finish(ok):
        done["ok"] = bool(ok)
        if not done["quit"]:
            done["quit"] = True
            app.quit()

    worker.log_signal.connect(on_log)
    worker.finished_signal.connect(on_finish)
    worker.start()
    guard = QTimer()
    guard.timeout.connect(worker.stop)
    guard.start(300000)              # 5 分钟：先请求停止
    hard = QTimer()
    hard.timeout.connect(lambda: (done.__setitem__("quit", True), app.quit()))
    hard.start(360000)               # 6 分钟：强制退出兜底
    app.exec()
    worker.wait(15000)
    emit(f"        MigrateWorker 返回 success = {done['ok']}")

    # ---- 4) 逐项核验 ----
    dst = os.path.join(target_root, os.path.basename(src_root))
    src_gone = not os.path.exists(src_root)
    dst_ok = os.path.isdir(dst)
    dst_cnt = sum(len(f) for _, _, f in os.walk(dst)) if dst_ok else 0
    cnt_ok = (dst_cnt == expected_cnt)
    migrate_ok = done["ok"] and src_gone and dst_ok and cnt_ok
    emit(f"[步骤4] 核验：源已删除={src_gone}  目标存在={dst_ok}  "
         f"文件数 {expected_cnt}->{dst_cnt} {'一致' if cnt_ok else '不一致'}")

    emit("=" * 70)
    final_pass = all([no_high_selected, users_locked, appdata_locked, migrate_ok])
    emit("SELFTEST_PASS" if final_pass else "SELFTEST_FAIL")
    emit("=" * 70)
    return 0 if final_pass else 1


# ===================== 缓存场景自检（微信/QQ/QQ音乐） =====================
CACHE_SELFTEST_FLAG = r"\\vboxsvr\share2\rb_selftest_cache.flag"
CACHE_SELFTEST_REPORT = r"\\vboxsvr\share2\rb_selftest_cache_report.txt"

# 仿真缓存目录：微信/QQ/QQ音乐 的 AppData 缓存 + 微信接收文件（Documents，非 AppData）
CACHE_PROBE_SPECS = [
    (r"C:\Users\Administrator\AppData\Roaming\Tencent\WeChat\Cache", 3, 300000),
    (r"C:\Users\Administrator\AppData\Roaming\Tencent\WeChat\FileStorage", 2, 200000),
    (r"C:\Users\Administrator\AppData\Roaming\Tencent\QQ\Misc", 2, 200000),
    (r"C:\Users\Administrator\AppData\Roaming\Tencent\QQMusic\Cache", 3, 300000),
    (r"C:\Users\Administrator\AppData\Local\Tencent\QQMusic\Cache", 2, 200000),
    (r"C:\Users\Administrator\Documents\WeChat Files\wxid_selftest\FileStorage", 3, 300000),
]

def _migrate_once(app, srcs, target_root, total_bytes, log_red):
    """跑一次产品真实 MigrateWorker，返回 (success, 红日志条数)。"""
    w = MigrateWorker(srcs, target_root, total_bytes)
    res = {"ok": False}

    def on_log(msg, color):
        if color == "red":
            log_red.append(msg)

    def on_finish(ok):
        res["ok"] = bool(ok)
        app.quit()

    w.log_signal.connect(on_log)
    w.finished_signal.connect(on_finish)
    w.start()
    t1 = QTimer(); t1.timeout.connect(w.stop);  t1.start(120000)
    t2 = QTimer(); t2.timeout.connect(app.quit); t2.start(150000)
    app.exec()
    w.wait(10000)
    return res["ok"]

def run_selftest_cache():
    """缓存场景自检（无 GUI）：造仿真微信/QQ/QQ音乐缓存树 ->
    1) 产品真实扫描，看这些目录扫不扫得到；
    2) 看 classify_risk 判定（绿=可迁 / 红=UI 禁止勾选）；
    3) 绕过 UI 锁定强行用真实 MigrateWorker 迁移，测技术上到底迁不迁得动。"""
    lines = []

    def emit(msg):
        lines.append(str(msg))
        try:
            with open(CACHE_SELFTEST_REPORT, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError:
            pass

    emit("=" * 72)
    emit(f"C盘利刃 V2.2 缓存场景自检（微信/QQ/QQ音乐）  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    emit("=" * 72)
    try:
        os.remove(CACHE_SELFTEST_FLAG)
    except OSError:
        pass

    # ---- 1) 造仿真缓存树 ----
    built = []
    for path, nfiles, size in CACHE_PROBE_SPECS:
        try:
            os.makedirs(path, exist_ok=True)
            for i in range(nfiles):
                with open(os.path.join(path, f"cache_{i}.dat"), "wb") as f:
                    f.write(b"C" * size)
            cnt = len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))])
            built.append((path, cnt))
            emit(f"[步骤1] 已造仿真目录 {path}（{cnt} 文件）")
        except OSError as e:
            emit(f"[步骤1] 造目录失败 {path} : {e}")

    # ---- 2) 产品真实扫描 + 分类判定 ----
    try:
        paths = scan_c_migratable_fast(max_depth=2)
        safes = [p for p in paths if classify_risk(p) == "safe"]
        emit(f"[步骤2] 产品真实扫描（max_depth=2）共 {len(paths)} 目录，绿 {len(safes)} / 红 {len(paths)-len(safes)}")
    except Exception as e:
        paths, safes = [], []
        emit(f"[步骤2] 扫描失败：{e}")

    emit("")
    emit("  路径 | 扫描可见 | 风险判定 | UI 是否允许勾选迁移")
    emit("  " + "-" * 68)
    probe_rows = []
    for path, cnt in built:
        visible = path in paths
        # 扫描深度不足时，逐层找它的可见祖先
        shown = visible
        risk = classify_risk(path)
        allowed = (risk == "safe")
        probe_rows.append((path, shown, risk, allowed))
        emit(f"  {path}")
        emit(f"     扫描可见={'是' if visible else '否(扫描深度2层未覆盖)'}  判定={'绿色可迁移' if risk=='safe' else '红色高危'}  UI允许迁移={'是' if allowed else '否(禁止勾选)'}")

    # ---- 3) 绕过 UI 锁定，强行用真实 MigrateWorker 迁移（测技术可行性） ----
    emit("")
    emit("[步骤3] 强行迁移实验（绕过 UI 锁定，直接调产品真实 MigrateWorker）")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    target_root = r"\\vboxsvr\share2\Cache_Selftest_Dst"
    try:
        shutil.rmtree(target_root, ignore_errors=True)
    except OSError:
        pass

    results = []
    for idx, (path, cnt) in enumerate(built):
        slot = os.path.join(target_root, f"slot{idx}")
        total = sum(os.path.getsize(os.path.join(dp, f))
                    for dp, _, fs in os.walk(path) for f in fs)
        log_red = []
        ok = _migrate_once(app, [path], slot, total, log_red)
        dst = os.path.join(slot, os.path.basename(path))
        src_gone = not os.path.exists(path)
        dst_cnt = sum(len(f) for _, _, f in os.walk(dst)) if os.path.isdir(dst) else 0
        results.append((path, ok, src_gone, cnt, dst_cnt, len(log_red)))
        emit(f"  {path}")
        emit(f"     MigrateWorker success={ok}  源已删除={src_gone}  文件数 {cnt}->{dst_cnt}  红日志 {len(log_red)} 条")
        for m in log_red[:4]:
            emit(f"       [红] {m[:90]}")

    # ---- 4) 结论 ----
    emit("")
    emit("=" * 72)
    emit("[结论] 分两类看：")
    appdata_rows = [r for r in probe_rows if "\\appdata" in r[0].lower()]
    other_rows = [r for r in probe_rows if "\\appdata" not in r[0].lower()]
    if appdata_rows:
        emit("  ▸ AppData 下的缓存（微信/QQ/QQ音乐 Cache）：")
        emit(f"    产品判定：{'/'.join(sorted({r[2] for r in appdata_rows}))} → UI 全部禁止勾选，用户无法迁移")
        tech = sum(1 for r in results if "\\appdata" in r[0].lower() and r[1] and r[2] and r[3] == r[4])
        tech_all = sum(1 for r in results if "\\appdata" in r[0].lower())
        emit(f"    技术上限：强行迁移 {tech_all} 个，其中 {tech} 个 复制+删源 完整成功（说明技术能搬，是产品主动锁死）")
    if other_rows:
        emit("  ▸ 非 AppData 的微信接收文件（Documents\\WeChat Files）：")
        emit(f"    产品判定：{'/'.join(sorted({r[2] for r in other_rows}))}")
        for r in results:
            if "\\appdata" not in r[0].lower():
                emit(f"    实测：success={r[1]} 源已删={r[2]} 文件数 {r[3]}->{r[4]} → {'PASS' if (r[1] and r[2] and r[3]==r[4]) else 'FAIL'}")
    emit("=" * 72)
    return 0


# ===================== Junction 缓存搬家自检（虚拟机内实测） =====================
JUNCTION_SELFTEST_FLAG = r"\\vboxsvr\share2\rb_selftest_junction.flag"
JUNCTION_SELFTEST_REPORT = r"\\vboxsvr\share2\rb_selftest_junction_report.txt"
JUNCTION_TARGET_FILE = r"\\vboxsvr\share2\rb_junction_target.txt"

# 仿真缓存目录（与真实微信/QQ音乐路径一致，让产品自带的规则库能检测到）
JUNCTION_PROBE_SPECS = [
    (r"%APPDATA%\Tencent\WeChat\Cache", 3),
    (r"%APPDATA%\Tencent\WeChat\FileStorage", 2),
    (r"%APPDATA%\Tencent\QQMusic\Cache", 3),
    (r"%USERPROFILE%\Documents\WeChat Files", 2),
]


def _run_junction_worker(app, items, mode, emit):
    """跑真实 JunctionWorker，返回 (成功数, 失败数)。"""
    w = JunctionWorker(items, items[0]["dst"] if items else "", mode)
    res = {"ok": 0, "fail": 0}

    def on_log(msg, color):
        emit("    [LOG] " + msg)

    def on_finish(ok_n, fail_n):
        res["ok"], res["fail"] = ok_n, fail_n
        app.quit()

    w.log_signal.connect(on_log)
    w.finished_signal.connect(on_finish)
    QTimer.singleShot(0, w.start)
    t = QTimer(); t.timeout.connect(app.quit); t.start(300000)
    app.exec()
    w.wait(15000)
    return res["ok"], res["fail"]


def run_selftest_junction():
    """Junction 缓存搬家自检（无 GUI）：造仿真微信/QQ音乐缓存 -> 产品真实检测 ->
    真实搬家（复制+删源+建链接）-> 探针验证穿透 -> 还原。全程用产品自身代码。"""
    lines = []

    def emit(msg):
        lines.append(str(msg))
        try:
            with open(JUNCTION_SELFTEST_REPORT, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError:
            pass

    emit("=" * 72)
    emit(f"C盘利刃 V2.2 Junction 缓存搬家自检  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    emit("=" * 72)
    try:
        os.remove(JUNCTION_SELFTEST_FLAG)
    except OSError:
        pass

    # ---- 0) 选目标盘 ----
    target = ""
    try:
        if os.path.exists(JUNCTION_TARGET_FILE):
            with open(JUNCTION_TARGET_FILE, "r", encoding="utf-8") as f:
                target = f.read().strip()
    except OSError:
        target = ""
    if not target:
        d = find_non_c_drive()
        target = os.path.join(d, "ResetBladeCache") if d else ""
    if not target:
        target = r"\\vboxsvr\share2\Junction_Dst"
    emit(f"[步骤0] 搬家目标根目录 = {target}")
    emit(f"        目标盘可用空间 = {bytes_human(get_disk_free(target)) if os.path.isdir(target) or os.path.isdir(os.path.dirname(target)) else '未知'}")

    # ---- 1) 造仿真缓存目录 ----
    built = []
    for p, nf in JUNCTION_PROBE_SPECS:
        path = _expand(p)
        try:
            # 先拆掉上次测试可能残留的 junction（含悬空链接：rmtree 删不掉，会让 makedirs 报"已存在"）
            try:
                _st = os.stat(path, follow_symlinks=False)
                if getattr(_st, "st_reparse_tag", 0):
                    remove_junction(path)
            except OSError:
                pass
            shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path, exist_ok=True)
            for i in range(nf):
                with open(os.path.join(path, f"cache_{i}.dat"), "wb") as f:
                    f.write(b"C" * 200000)
            built.append((path, count_files(path)))
            emit(f"[步骤1] 造仿真缓存目录 {path}（{count_files(path)} 文件）")
        except OSError as e:
            emit(f"[步骤1] 造目录失败 {path} : {e}")

    # ---- 2) 产品真实检测 ----
    detected = detect_cache_apps()
    emit("")
    emit(f"[步骤2] 产品 detect_cache_apps() 检测到 {len(detected)} 个缓存目录：")
    for d in detected:
        emit(f"    {d['app']:<16} {d['src']}  (链接={d['junction']})")

    app = QApplication.instance() or QApplication(sys.argv[:1])

    # ---- 3) 安全护栏测试：受保护目录必须被拒绝 ----
    emit("")
    emit("[步骤3] 安全护栏：受保护目录必须拒绝搬家")
    guard_ok = True
    for bad in (r"C:\Windows", r"C:\Program Files", r"C:\inetpub", r"C:\Users"):
        blocked = junction_forbidden(bad)
        guard_ok = guard_ok and blocked
        emit(f"    {bad:<20} junction_forbidden={blocked}  {'✔' if blocked else '❌ 未拦截！'}")
    # 反向断言：应用缓存目录必须允许搬家（护栏修过一轮：C:\Users 只拦根、不拦子树）
    for good in (r"C:\Users\Administrator\AppData\Roaming\Tencent\WeChat\Cache",
                 r"C:\Users\Administrator\Documents\WeChat Files"):
        allowed = not junction_forbidden(good)
        guard_ok = guard_ok and allowed
        emit(f"    {good:<62} 允许搬家={allowed}  {'✔' if allowed else '❌ 误拦截！'}")
    # 真跑一次，确认 worker 也会拒绝
    items_bad = [{"app": "护栏测试", "src": r"C:\PerfLogs", "dst": os.path.join(target, "bad")}]
    guard_hits = []
    gw = JunctionWorker(items_bad, target, "move")
    gw.log_signal.connect(lambda m, c: guard_hits.append(m))
    gw.finished_signal.connect(lambda a, b: app.quit())
    QTimer.singleShot(0, gw.start)
    t = QTimer(); t.timeout.connect(app.quit); t.start(60000)
    app.exec(); gw.wait(10000)
    refused = any("拒绝搬家" in m for m in guard_hits)
    emit(f"    JunctionWorker 实际执行拒绝 = {refused}  {'✔' if refused else '❌'}")
    guard_ok = guard_ok and refused

    # ---- 4) 真实搬家 ----
    emit("")
    emit("[步骤4] 真实搬家（JunctionWorker mode=move）")
    items = [{"app": next((d["app"] for d in detected if d["src"].lower() == p.lower()), "缓存"),
              "src": p,
              "dst": os.path.join(target, "Selftest", _safe_name(
                  next((d["app"] for d in detected if d["src"].lower() == p.lower()), "缓存")),
                  os.path.basename(p))}
             for p, n in built]
    ok_n, fail_n = _run_junction_worker(app, items, "move", emit)
    emit(f"    worker 返回：成功 {ok_n} / 失败或待完成 {fail_n}")

    # ---- 5) 逐项核验：链接生效 + 文件数一致 + 探针穿透 ----
    emit("")
    emit("[步骤5] 核验（链接生效 / 文件数一致 / 写入穿透到目标盘）")
    all_ok = True
    for p, n_src in built:
        isj = is_junction(p)
        tgt = read_junction_target(p)
        n_dst = count_files(tgt) if (tgt and os.path.isdir(tgt)) else 0
        # 探针：往"C盘原路径"写文件，看是否真落到目标盘
        probe = os.path.join(p, "__probe.tmp")
        landed = False
        try:
            with open(probe, "wb") as f:
                f.write(b"P")
            landed = os.path.exists(os.path.join(tgt or "", "__probe.tmp"))
            os.remove(probe)
        except OSError:
            landed = False
        c_ok = isj and (n_dst >= n_src) and landed
        all_ok = all_ok and c_ok
        emit(f"    {p}")
        emit(f"       是目录链接={isj}  指向={tgt}")
        emit(f"       文件数 {n_src} -> {n_dst}   写入穿透={'是' if landed else '否'}")
        emit(f"       {'PASS' if c_ok else 'FAIL'}")

    # ---- 6) 还原 ----
    emit("")
    emit("[步骤6] 还原（JunctionWorker mode=revert）")
    ok_r, fail_r = _run_junction_worker(app, items, "revert", emit)
    emit(f"    worker 返回：成功 {ok_r} / 失败 {fail_r}")
    revert_ok = True
    for p, n_src in built:
        real = os.path.isdir(p) and not is_junction(p)
        n_now = count_files(p) if os.path.isdir(p) else 0
        dst_i = next((it["dst"] for it in items if it["src"].lower() == p.lower()), "")
        gone = not os.path.exists(dst_i) if dst_i else True
        r_ok = real and n_now >= n_src and gone
        revert_ok = revert_ok and r_ok
        emit(f"    {p}")
        emit(f"       还原为真实目录={real}  文件数 {n_src} -> {n_now}  目标已清理={gone}")
        emit(f"       {'PASS' if r_ok else 'FAIL'}")

    # ---- 7) 清理 ----
    for p, _n in built:
        shutil.rmtree(p, ignore_errors=True)
        if is_junction(p):
            remove_junction(p)
    shutil.rmtree(os.path.join(target, "Selftest"), ignore_errors=True)
    shutil.rmtree(os.path.join(target, "bad"), ignore_errors=True)

    emit("")
    emit("=" * 72)
    final = all_ok and revert_ok and guard_ok and ok_n == len(built) and fail_n == 0
    emit(f"搬家 {ok_n}/{len(built)} 成功 | 核验全部通过={all_ok} | 还原通过={revert_ok} | 安全护栏通过={guard_ok}")
    emit("JUNCTION_SELFTEST_PASS" if final else "JUNCTION_SELFTEST_FAIL")
    emit("=" * 72)
    return 0 if final else 1


def install_crash_handler():
    """全局崩溃捕获：任何未被处理的 Python 异常都会被记录到日志文件并弹窗提示，
    彻底杜绝窗口程序「静默闪退、无任何提示」的情况（窗口 exe 不显示 stderr）。"""
    import tempfile as _tf
    import time as _time
    _log_path = os.path.join(_tf.gettempdir(), "C盘利刃_crash.log")

    def _handler(etyp, eval_, etb):
        import traceback as _tb
        msg = "".join(_tb.format_exception(etyp, eval_, etb))
        try:
            with open(_log_path, "a", encoding="utf-8") as f:
                f.write("==== " + _time.strftime("%Y-%m-%d %H:%M:%S") + " ====\n" + msg + "\n")
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None, "C盘利刃 - 运行出错（已捕获，未闪退）",
                    "程序遇到一个未预期的错误，已捕获并记录到：\n" + _log_path +
                    "\n\n请把该文件内容反馈给开发者。错误信息：\n\n" + msg[-1500:])
        except Exception:
            pass
        sys.__excepthook__(etyp, eval_, etb)

    sys.excepthook = _handler


if __name__ == "__main__":
    # PyQt6 / Qt6 默认已开启高 DPI 缩放与高分 pixmap，以下两个属性在 Qt6 已移除
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    install_crash_handler()

    # 自检/命令行模式统一按 UTF-8 输出：GBK 控制台遇到 ✅ 等 emoji 会直接 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Junction 缓存搬家自检——必须在 UAC 提权之前
    if os.path.exists(JUNCTION_SELFTEST_FLAG):
        sys.exit(run_selftest_junction())

    # 缓存场景自检（微信/QQ/QQ音乐缓存能否迁移）——必须在 UAC 提权之前
    if os.path.exists(CACHE_SELFTEST_FLAG):
        sys.exit(run_selftest_cache())

    # 无人值守自检：共享盘存在标志文件即自动执行（必须在 UAC 提权之前，避免弹窗）
    if any(os.path.exists(p) for p in SELFTEST_FLAG_CANDIDATES):
        sys.exit(run_selftest_flag())

    # 迁移功能自检模式（无 GUI，纯命令行，直接跑产品自身迁移逻辑）
    if "--selftest-migrate" in sys.argv:
        sys.exit(run_selftest_migrate(sys.argv))

    # --notify 模式：直接弹重置结果通知窗
    if "--notify" in sys.argv:
        app = QApplication(sys.argv)
        app.setWindowIcon(QIcon(res_path("icon_256.png")))
        # 定时任务周期触发：顺带做一次资源守卫（重置后本体/快捷方式被清掉时由此补回）
        try:
            run_resource_guardian("notify")
        except Exception:
            pass
        run_notify_mode()

    elevate_self()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setWindowIcon(QIcon(res_path("icon_256.png")))

    d_disclaim = DisclaimDialog()
    if d_disclaim.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    # 免责协议通过后、主窗口出现前：弹「下载 / 选择保存位置」窗口。
    # 放在主窗口之前是为了让用户第一眼就看到（对齐安装器那种「先选位置」的体感）；
    # 用户取消也只是跳过，不影响后面任何启动逻辑。
    # 主题跟主窗口默认一致（MainWindow 默认浅色，dark_mode 不持久化）
    download_result = run_download_window_if_needed(parent=None, dark=False)

    # 桌面快捷方式创建（复制 exe + 起 PowerShell COM，同步做会冻结启动界面 1~3 秒）
    # 改为主窗口显示后由后台线程执行，启动零等待
    w = MainWindow()
    w.show()
    if download_result[1]:
        # 有实际下载才写日志，避免每次启动都刷一行没意义的话
        w.log(f"启动下载完成：{len(download_result[1])} 个文件已保存到 {download_result[0]}")
    w.shortcut_worker = ShortcutWorker()
    w.shortcut_worker.start()
    sys.exit(app.exec())
