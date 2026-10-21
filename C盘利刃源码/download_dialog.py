# -*- coding: utf-8 -*-
"""
=============================================================================
 C盘利刃 · 下载窗口组件 (DownloadDialog)   v1.0
=============================================================================
 用途：
   在程序里弹出一个「选择保存位置 → 开始下载 → 进度 → 完成后打开文件夹」
   的窗口，交互样式对齐企业微信安装器的「更改目录」那一套，视觉沿用
   C盘利刃 的玻璃拟态风格（半透明背景 + 毛玻璃蒙版 + 圆角控件）。

 两种用法：
   ① 独立模块（推荐）：把本文件放到 main.py 同目录，然后
        from download_dialog import DownloadDialog, DownloadItem
   ② 整段粘贴：把本文件从 "===== 配置读写 =====" 到文件末尾整段粘进 main.py
      任意位置（所有内部符号都带 _dl_ / DOWNLOAD_ 前缀，不会与主程序撞名）。

 最小调用示例：
        items = [DownloadItem("C盘利刃_V2.3.exe",
                              url="https://example.com/C盘利刃_V2.3.exe",
                              size=18 * 1024 * 1024)]
        dlg = DownloadDialog(self, items, dark=self.dark_mode)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.log(f"已下载到：{dlg.saved_dir}")

 设计要点（对应需求 1~5）：
   1. 文件列表 + 路径输入框 + 浏览按钮（系统文件夹选择框）
   2. 上次选择的路径写进 config.json 的 download_last_dir，下次自动填充
   3. 确定/取消；在下载中点「取消」会回滚删掉已写的临时文件，不留垃圾
   4. 空路径 / 路径不存在 / 无写权限 / 空间不足 —— 全部弹提示，绝不抛异常崩界面
   5. 实时进度条（文件级 + 字节级）+ 完成后提示路径 + 一键打开所在文件夹
=============================================================================
"""
import os
import sys
import json
import shutil
import tempfile
import subprocess
import urllib.request
import urllib.error

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QProgressBar, QListWidget, QListWidgetItem,
                             QFileDialog, QMessageBox, QWidget)
from PyQt6.QtGui import QIcon, QPixmap, QColor, QBrush
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer


# ===================== 配置读写（只碰自己那一个键，绝不覆盖主程序配置） =====================
APP_NAME = "C盘利刃"
_DL_CONFIG_KEY = "download_last_dir"          # 上次选择的下载目录
_DL_USER_AGENT = "CpanLiren-Downloader/1.0"


def _dl_config_path():
    """与主程序共用同一个配置文件：%LOCALAPPDATA%\\C盘利刃\\config.json"""
    return os.path.join(os.path.expanduser("~"), "AppData", "Local", APP_NAME, "config.json")


def _dl_cfg_read():
    """读配置；文件不存在 / 损坏都返回空 dict，绝不抛异常。"""
    try:
        with open(_dl_config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dl_cfg_update(**kv):
    """读-改-写：只更新传入的键，主程序的其它配置原样保留。
    写失败（目录不存在/被占用/无权限）静默放弃——记忆路径只是体验优化，不该阻断下载。"""
    try:
        cfg = _dl_cfg_read()
        cfg.update(kv)
        p = _dl_config_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ===================== 小工具 =====================
def _dl_bytes_human(n):
    """人类可读的容量文本。"""
    try:
        n = float(n)
    except Exception:
        return "--"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def _dl_disk_free(path):
    """查询目标盘剩余空间；路径取不到返回 0（上层会当未知处理）。"""
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return 0


def _dl_test_writable(folder):
    """真正下笔测试写权限：建个临时空文件再删掉。
    只看 os.access(W_OK) 在 Windows 上会误判（NTFS ACL / UAC 虚拟化都能骗过它）。"""
    try:
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".dl_perm_")
        os.close(fd)
        os.remove(tmp)
        return True
    except Exception:
        return False


def _dl_default_dir():
    """兜底默认目录：优先「下载」文件夹，其次桌面，最后用户主目录。"""
    home = os.path.expanduser("~")
    for cand in (os.path.join(home, "Downloads"),
                 os.path.join(home, "Desktop"),
                 os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(cand):
            return cand
    return home


def _dl_open_folder(folder, select_file=None):
    """用资源管理器打开目录；给了文件名就顺便选中它。"""
    try:
        if select_file and os.path.exists(select_file):
            # /select 后面必须留着那个逗号，且用紧凑写法，路径带空格也能识别
            subprocess.Popen(f'explorer /select,"{os.path.normpath(select_file)}"')
        else:
            os.startfile(os.path.normpath(folder))   # noqa: S606 (Windows 专用)
        return True
    except Exception:
        return False


# ===================== 下载项数据结构 =====================
class DownloadItem:
    """一个待下载文件。
    name:  显示名 & 最终落盘文件名（给空则从 url/path 里取 basename）
    url:   远程地址，支持 http/https/file://
    path:  本地源文件（给了 path 就是「复制」模式，不需要网络）
    size:  预知大小（字节），0 表示未知；未知时进度按「文件个数」推进
    """

    def __init__(self, name="", url=None, path=None, size=0):
        self.url = url
        self.path = path
        if not name:
            src = url or path or ""
            # 从 URL 末段取文件名，去掉 query 尾巴
            name = os.path.basename(src.split("?")[0].split("#")[0].rstrip("/")) or "download.bin"
        # 只留文件名，剥掉路径成分：防止 name 里带 "..\\" 把文件写到目标目录外面去
        self.name = os.path.basename(name.replace("\\", "/")) or "download.bin"
        self.size = int(size or 0)

    def __repr__(self):
        return f"<DownloadItem {self.name} size={self.size}>"


# ===================== 后台下载线程 =====================
class DownloadWorker(QThread):
    """逐文件下载，实时回传进度。所有异常都转成 error_signal，不往 GUI 线程里抛。"""
    progress = pyqtSignal(int, str)      # (总进度 0~100, 当前文件名)
    error_signal = pyqtSignal(str)       # 致命错误文本
    done_signal = pyqtSignal(list)       # 成功落盘的文件绝对路径列表

    CHUNK = 256 * 1024                   # 256KB 一块，兼顾吞吐与取消响应速度

    def __init__(self, items, target_dir, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.target_dir = target_dir
        self._stop = False               # 取消标志（Qt 的 requestInterruption 也行，这里用显式布尔更好读）
        self._written = []               # 已成功写出的文件，取消时用于回滚
        self._current_part = None        # 当前正在写的 .part 文件

    # ---------- 对外：请求停止 ----------
    def stop(self):
        self._stop = True

    # ---------- 内部：打开数据源，返回 (读取流, 总字节数或 0) ----------
    def _open_source(self, item):
        if item.path:                                   # 复制模式
            total = os.path.getsize(item.path)
            return open(item.path, "rb"), total
        url = item.url or ""
        if url.startswith("file://"):                   # 本地文件 URL，转成路径读
            p = urllib.request.url2pathname(url[7:])
            return open(p, "rb"), os.path.getsize(p)
        req = urllib.request.Request(url, headers={"User-Agent": _DL_USER_AGENT})
        resp = urllib.request.urlopen(req, timeout=30)
        # Content-Length 可能缺失（chunked 编码），缺失就当未知
        total = int(resp.headers.get("Content-Length") or 0)
        return resp, total

    def run(self):
        n = max(len(self.items), 1)
        finished_count = 0
        for idx, item in enumerate(self.items):
            if self._stop:
                break
            dst = os.path.join(self.target_dir, item.name)
            part = dst + ".part"                        # 先写临时名，写完再改名：避免半截文件被当成成品
            self._current_part = part
            try:
                stream, total_bytes = self._open_source(item)
                got = 0
                # 同目录已有同名文件：直接覆盖（上层已经确认过，这里不再打扰用户）
                with open(part, "wb") as out:
                    while True:
                        if self._stop:
                            break
                        chunk = stream.read(self.CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                        # 单文件进度 → 折算进总进度（总进度 = 已完成文件数 + 当前文件的比例）
                        inner = (got / total_bytes) if total_bytes else 0
                        pct = int((finished_count + inner) * 100 / n)
                        self.progress.emit(min(pct, 99),
                                           f"{item.name}  {_dl_bytes_human(got)}"
                                           + (f" / {_dl_bytes_human(total_bytes)}" if total_bytes else ""))
                try:
                    stream.close()
                except Exception:
                    pass

                if self._stop:                          # 下载途中被取消 → 删掉半成品
                    try:
                        os.remove(part)
                    except Exception:
                        pass
                    self._current_part = None
                    break

                # 落盘：直接用原子替换把临时文件转正（Windows 的 MoveFileEx 支持覆盖已存在文件，
                # 比「先删后改名」安全——中途失败时原文件还在）
                os.replace(part, dst)
                self._current_part = None
                self._written.append(dst)
                finished_count += 1
                self.progress.emit(int(finished_count * 100 / n), item.name)

            except urllib.error.HTTPError as e:
                # 404/403/500 这类服务器回绝：属于「地址不通」，不是写盘问题，提示要分开
                self._cleanup_part()
                self.error_signal.emit(f"下载「{item.name}」失败：服务器返回 HTTP {e.code} {e.reason}\n\n"
                                       f"地址：{item.url}")
                self._rollback()
                return
            except urllib.error.URLError as e:
                self._cleanup_part()
                self.error_signal.emit(f"无法连接下载地址：\n{item.url}\n\n{e.reason}\n\n"
                                       f"请检查网络，或稍后重试。")
                self._rollback()
                return
            except PermissionError:
                self._cleanup_part()
                self.error_signal.emit(f"没有权限写入：\n{self.target_dir}\n\n"
                                       f"请换一个目录，或以管理员身份运行本程序。")
                self._rollback()
                return
            except OSError as e:
                self._cleanup_part()
                # ENOSPC(28) = 磁盘空间不足；其余按系统错误原文透出，不吞掉
                if getattr(e, "errno", None) == 28 or "No space" in str(e) or "空间不足" in str(e):
                    self.error_signal.emit(f"磁盘空间不足，写入中断：\n{self.target_dir}\n\n"
                                           f"已清理未完成的临时文件。")
                else:
                    self.error_signal.emit(f"写入失败：{e}\n\n目标目录：{self.target_dir}")
                self._rollback()
                return
            except Exception as e:
                self._cleanup_part()
                self.error_signal.emit(f"下载「{item.name}」失败：\n{e}")
                self._rollback()
                return

        if self._stop:
            self._rollback()                            # 用户主动取消：已完成的多余文件也删掉
            self.done_signal.emit([])
        else:
            self.done_signal.emit(self._written)

    # ---------- 收尾：删临时文件 / 回滚已写文件 ----------
    def _cleanup_part(self):
        if self._current_part and os.path.exists(self._current_part):
            try:
                os.remove(self._current_part)
            except Exception:
                pass
        self._current_part = None

    def _rollback(self):
        """取消或失败时的回滚：把本次已经写出的文件删掉，做到「取消 = 什么都没发生」。"""
        self._cleanup_part()
        for p in self._written:
            try:
                os.remove(p)
            except Exception:
                pass
        self._written = []


# ===================== 玻璃拟态基类（宿主有就用宿主的） =====================
def _dl_glass_base():
    """能拿到宿主的 GlassDialog 就直接用它（省一份重复代码，视觉/层级与主程序完全一致）；
    拿不到就用下面这个等价实现，保证独立模块也能出同样的效果。

    判定条件刻意放宽：只要宿主进程里存在 GlassDialog（QDialog 子类）就复用，
    不再要求它定义在 __main__ 里——这样无论 python main.py、python -m main
    还是 PyInstaller 打包运行，走的都是主程序那套玻璃拟态基类。"""
    host = sys.modules.get("__main__")
    g = getattr(host, "GlassDialog", None) if host else None
    if isinstance(g, type) and issubclass(g, QDialog):
        return g
    return _MiniGlassDialog


def _dl_bg_pixmap():
    """找同目录的背景图，和主程序用同一张（bg_blur.jpg）。
    PyInstaller 单文件模式下资源在 _MEIPASS，onedir 模式在 _MEIPASS/_internal，两种都探。"""
    roots = [os.path.dirname(os.path.abspath(__file__))]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        roots += [meipass, os.path.join(meipass, "_internal")]
    for name in ("bg_blur.jpg", "bg_blur.png", "bg.jpg", "bg.png"):
        for base in roots:
            p = os.path.join(base, name)
            if os.path.exists(p):
                pm = QPixmap(p)
                if not pm.isNull():
                    return pm
    return None


class _MiniGlassDialog(QDialog):
    """主程序里没有 GlassDialog 时的兜底：无边框半透明 + 背景图 + 蒙版。"""

    def __init__(self, parent=None, dark=False):
        super().__init__(parent)
        self.dark = dark
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 独立运行（不在主程序里）时也带上自己的窗口图标，任务栏不会显示成通用白纸
        for base in (os.path.dirname(os.path.abspath(__file__)), getattr(sys, "_MEIPASS", "")):
            p = os.path.join(base, "icon_256.png") if base else ""
            if p and os.path.exists(p):
                self.setWindowIcon(QIcon(p))
                break
        self._bg = _dl_bg_pixmap()
        self.bg_label = QLabel(self)
        self.scrim = QLabel(self)
        self.bg_label.stackUnder(self.scrim)
        self._apply_scrim()
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


# ===================== 下载窗口本体 =====================
class DownloadDialog(_dl_glass_base()):
    """下载窗口：选目录 → 下载 → 进度 → 完成。

    参数：
      parent  父窗口（决定弹窗位置与模态关系）
      items   list[DownloadItem]，为空时只做「选目录」用途
      dark    是否深色主题（传主窗口的 self.dark_mode 即可）
      title   窗口标题
    """

    def __init__(self, parent=None, items=None, dark=False, title="下载文件"):
        super().__init__(parent, dark)
        self.setWindowTitle(f"{title} - {APP_NAME}")
        self.resize(580, 430)
        self.items = list(items or [])
        self.worker = None
        self.saved_dir = ""          # 下载完成后给调用方看：实际保存目录
        self.saved_files = []        # 实际落盘的文件列表
        self._downloading = False

        self._build_ui()
        self._apply_style()
        self._load_last_dir()
        # 没有待下载文件 = 纯「选保存位置」模式：列表没意义，直接收起并矮化窗口，
        # 标题/按钮文案一起换掉，不显示「开始下载」这种会误导人的字
        if not self.items:
            self.list_files.setVisible(False)
            self.setWindowTitle(f"选择保存位置 - {APP_NAME}")
            self.lbl_title.setText("选择保存位置")
            self.lbl_sub.setText("请选择文件要存放的目录，程序会记住这个位置。")
            self.btn_ok.setText("确定")
            self.resize(560, 250)

    # ---------------- UI 搭建 ----------------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        # —— 标题区 ——
        self.lbl_title = QLabel("下载文件")
        self.lbl_title.setStyleSheet("font-size:17px;font-weight:bold;")
        lay.addWidget(self.lbl_title)

        self.lbl_sub = QLabel("请选择文件的保存位置，然后开始下载。")
        self.lbl_sub.setStyleSheet("color:#6b7280;font-size:9pt;")
        lay.addWidget(self.lbl_sub)

        # —— 待下载文件列表 ——
        self.list_files = QListWidget()
        self.list_files.setMinimumHeight(110)
        self.list_files.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_files.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self.items:
            for it in self.items:
                text = it.name + (f"    （{_dl_bytes_human(it.size)}）" if it.size else "")
                self.list_files.addItem(QListWidgetItem(text))
        # 空清单时不塞「（未指定待下载文件）」这种占位文字——列表会被整个隐藏掉
        lay.addWidget(self.list_files, 1)

        # —— 保存路径 + 浏览 ——
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit_path = QLineEdit()
        self.edit_path.setPlaceholderText("选择保存位置，例如 D:\\我的工具")
        self.edit_path.setMinimumHeight(32)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.setMinimumHeight(32)
        self.btn_browse.setFixedWidth(86)
        self.btn_browse.clicked.connect(self._pick_dir)
        row.addWidget(self.edit_path, 1)
        row.addWidget(self.btn_browse)
        lay.addLayout(row)

        # —— 空间 / 状态提示 ——
        self.lbl_space = QLabel("")
        self.lbl_space.setStyleSheet("color:#6b7280;font-size:9pt;")
        lay.addWidget(self.lbl_space)

        # —— 进度条（下载时才显示）——
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        # —— 底部按钮 ——
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setMinimumHeight(34)
        self.btn_cancel.setMinimumWidth(96)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_ok = QPushButton("开始下载")
        self.btn_ok.setMinimumHeight(34)
        self.btn_ok.setMinimumWidth(120)
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_ok)
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_ok)
        lay.addLayout(btns)

        # 路径改动时顺手刷新一下可用空间提示
        self.edit_path.textChanged.connect(self._refresh_space_hint)

    # ---------------- 主题（照搬主程序深/浅两套 QSS） ----------------
    def _apply_style(self):
        if getattr(self, "dark", False):
            self.setStyleSheet("""
            QWidget{ font-family:"Microsoft YaHei"; font-size:10pt; }
            QPushButton{ background-color:rgba(31,41,55,0.55); border:1px solid #4b5563; border-radius:8px; padding:6px 12px; color:#f9fafb; }
            QPushButton:hover{ background-color:#374151; border-color:#60a5fa; }
            QPushButton:pressed{ background-color:#4b5563; }
            QPushButton:disabled{ background-color:rgba(31,41,55,0.4); color:#6b7280; }
            QLineEdit{ background-color:rgba(31,41,55,0.55); border:1px solid #4b5563; border-radius:8px; padding:4px 8px; color:#f9fafb; }
            QLineEdit:focus{ border-color:#60a5fa; }
            QListWidget{ background-color:rgba(31,41,55,0.42); border:1px solid #4b5563; border-radius:8px; padding:4px; color:#f9fafb; }
            QProgressBar{ border:1px solid #4b5563; border-radius:8px; height:20px; background-color:rgba(31,41,55,0.42); text-align:center; color:#f9fafb; }
            QProgressBar::chunk{ background-color:#3b82f6; border-radius:7px; }
            QDialog{ background:transparent; }
            QLabel{ color:#f9fafb; }
            """)
        else:
            self.setStyleSheet("""
            QWidget{ font-family:"Microsoft YaHei"; font-size:10pt; }
            QPushButton{ background-color:rgba(255,255,255,0.55); border:1px solid #d1d5db; border-radius:8px; padding:6px 12px; color:#1f2937; }
            QPushButton:hover{ background-color:#eff6ff; border-color:#93c5fd; }
            QPushButton:pressed{ background-color:#dbeafe; }
            QPushButton:disabled{ background-color:rgba(243,244,246,0.5); color:#9ca3af; }
            QLineEdit{ background-color:rgba(255,255,255,0.7); border:1px solid #d1d5db; border-radius:8px; padding:4px 8px; color:#1f2937; }
            QLineEdit:focus{ border-color:#93c5fd; }
            QListWidget{ background-color:rgba(255,255,255,0.55); border:1px solid #cfd4dc; border-radius:8px; padding:4px; color:#1f2937; }
            QProgressBar{ border:1px solid #d1d5db; border-radius:8px; height:20px; background-color:rgba(255,255,255,0.32); text-align:center; color:#1f2937; }
            QProgressBar::chunk{ background-color:#3b82f6; border-radius:7px; }
            QDialog{ background:transparent; }
            QLabel{ color:#1f2937; }
            """)
        # 深浅切换后，灰色小字要重新上色（QSS 里 QLabel 统一色会盖掉内联样式）
        sub_color = "#9ca3af" if getattr(self, "dark", False) else "#6b7280"
        self.lbl_sub.setStyleSheet(f"color:{sub_color};font-size:9pt;")
        self.lbl_space.setStyleSheet(f"color:{sub_color};font-size:9pt;")
        # 列表项文字色单独刷一遍：QListWidgetItem 的绘制不看 QSS 的 color，
        # 浅色主题下会沿用深色主题留下的白色，导致白字白底看不见
        fg = QColor("#f9fafb") if getattr(self, "dark", False) else QColor("#1f2937")
        for i in range(self.list_files.count()):
            it = self.list_files.item(i)
            if it is not None:
                it.setForeground(QBrush(fg))

    # ---------------- 需求 2：记住上次路径 ----------------
    def _load_last_dir(self):
        last = _dl_cfg_read().get(_DL_CONFIG_KEY, "")
        if last and os.path.isdir(last):
            self.edit_path.setText(last)          # 上次的目录还在 → 直接填上
        else:
            self.edit_path.setText(_dl_default_dir())   # 目录被删了 → 回退到系统下载夹
        self._refresh_space_hint()

    def _refresh_space_hint(self):
        p = self.edit_path.text().strip()
        if not p:
            self.lbl_space.setText("")
            return
        if not os.path.isdir(p):
            self.lbl_space.setText("⚠ 该路径不存在")
            return
        free = _dl_disk_free(p)
        need = sum(it.size for it in self.items)
        if free:
            txt = f"目标磁盘剩余 {_dl_bytes_human(free)}"
            if need:
                txt += f" ｜ 本次需要 {_dl_bytes_human(need)}"
            self.lbl_space.setText(txt)
        else:
            self.lbl_space.setText("")

    # ---------------- 需求 1：浏览按钮 → 系统文件夹选择框 ----------------
    def _pick_dir(self):
        start = self.edit_path.text().strip()
        if not os.path.isdir(start):
            start = _dl_default_dir()
        d = QFileDialog.getExistingDirectory(self, "选择保存位置", start,
                                             QFileDialog.Option.ShowDirsOnly)
        if d:                                    # 用户点了取消则保持原值
            self.edit_path.setText(os.path.normpath(d))

    # ---------------- 需求 4：路径合法性校验 ----------------
    def _validate(self):
        """返回 (是否通过, 错误文本)。所有可通过的检查都在这里，不通过就弹提示。"""
        path = self.edit_path.text().strip().strip('"')
        if not path:
            return False, "还没有选择保存位置。\n\n请点击「浏览…」选择，或直接输入路径。"
        # 非法字符：这几个 Windows 路径里根本不可能出现，出现就是用户手输错了
        if any(c in path for c in '<>|"'):
            return False, f"路径里有非法字符（< > | \" 不能出现在路径中）：\n{path}"
        # 冒号只允许出现在盘符位置（"D:\xxx"），其余位置一律非法
        if ":" in path and not (len(path) >= 2 and path[1] == ":" and path.count(":") == 1):
            return False, f"路径格式不正确：\n{path}\n\n冒号只能出现在盘符后面（例如 D:\\工具）。"
        if not os.path.isdir(path):
            # 路径不存在：给一次创建机会，而不是直接报错退回去
            r = QMessageBox.question(
                self, "路径不存在",
                f"目录不存在：\n{path}\n\n是否创建这个文件夹？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if r != QMessageBox.StandardButton.Yes:
                return False, ""
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                return False, f"无法创建目录：\n{path}\n\n{e}"
        # 写权限：真写一个临时文件来验证
        if not _dl_test_writable(path):
            return False, (f"这个目录没有写入权限：\n{path}\n\n"
                           f"请换一个目录，或用管理员身份重新运行本程序。")
        # 磁盘空间：只在本批文件大小已知时才敢下结论
        need = sum(it.size for it in self.items)
        free = _dl_disk_free(path)
        if need and free and free < need:
            return False, (f"磁盘空间不足。\n\n需要：{_dl_bytes_human(need)}\n"
                           f"可用：{_dl_bytes_human(free)}\n\n请清理空间或换个位置。")
        # 目标文件被别的程序占用时，落盘会失败——提前探一次，别下完才报错
        for it in self.items:
            tgt = os.path.join(path, it.name)
            if os.path.exists(tgt):
                try:
                    with open(tgt, "ab"):
                        pass
                except Exception:
                    return False, (f"目标文件正被其它程序占用，无法覆盖：\n{tgt}\n\n"
                                   f"请先关闭占用它的程序，或换个保存位置。")
        return True, ""

    # ---------------- 需求 3：确定 / 取消 ----------------
    def _on_ok(self):
        if self._downloading:
            return
        if not self.items:
            # 没有待下载文件时，这个窗口只当「选目录」用，直接返回所选路径
            self.saved_dir = self.edit_path.text().strip()
            self._save_last_dir(self.saved_dir)
            self.accept()
            return

        ok, msg = self._validate()
        if not ok:
            if msg:                              # msg 为空表示用户放弃了创建目录，静默返回
                QMessageBox.warning(self, "无法开始下载", msg)
            return

        target_dir = self.edit_path.text().strip().strip('"')
        self.saved_dir = target_dir
        self._save_last_dir(target_dir)

        # —— 进入下载态 ——
        self._downloading = True
        self.btn_ok.setEnabled(False)
        self.btn_ok.setText("下载中…")
        self.btn_browse.setEnabled(False)
        self.edit_path.setEnabled(False)
        self.btn_cancel.setText("取消下载")
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.lbl_space.setText("正在下载，请稍候…")

        self.worker = DownloadWorker(self.items, target_dir, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.error_signal.connect(self._on_error)
        self.worker.done_signal.connect(self._on_done)
        self.worker.start()

    def _on_cancel(self):
        """取消有两种含义：下载中 → 中止并回滚；未开始 → 关窗不放任何文件。"""
        if self._downloading and self.worker is not None:
            if QMessageBox.question(self, "确认取消",
                                    "确定要取消下载吗？\n已下载的部分会被删除。",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("正在取消…")
            self.worker.stop()                   # 线程会在下一个数据块处收手并回滚
            return
        # 未开始下载：直接拒掉，磁盘上不会有任何写入
        self.saved_dir = ""
        self.reject()

    def _save_last_dir(self, d):
        """把这次选的目录记进配置，下次打开自动填。"""
        if d and os.path.isdir(d):
            _dl_cfg_update(**{_DL_CONFIG_KEY: d})

    # ---------------- 需求 5：进度 / 完成 ----------------
    def _on_progress(self, pct, text):
        self.bar.setValue(max(0, min(100, pct)))
        self.lbl_space.setText(f"{pct}% ｜ {text}")

    def _on_error(self, msg):
        self._exit_download_state()
        QMessageBox.critical(self, "下载失败", msg)
        self.lbl_space.setText("下载已中断")

    def _on_done(self, files):
        self._exit_download_state()
        if not files:
            # 用户取消导致的空结果：不留文件，安静退出
            self.lbl_space.setText("已取消，未写入任何文件")
            self.saved_files = []
            self.saved_dir = ""
            return
        self.saved_files = list(files)
        self.bar.setValue(100)
        self.lbl_space.setText(f"已保存到：{self.saved_dir}")
        # 完成提示：直接问「要不要打开文件夹」，比弹一个只能点确定的框有用
        r = QMessageBox.information(
            self, "下载完成",
            f"已下载 {len(files)} 个文件到：\n{self.saved_dir}\n\n是否打开所在文件夹？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if r == QMessageBox.StandardButton.Yes:
            _dl_open_folder(self.saved_dir, files[0] if len(files) == 1 else None)
        self.accept()

    def _exit_download_state(self):
        self._downloading = False
        self.btn_ok.setEnabled(True)
        self.btn_ok.setText("开始下载")
        self.btn_browse.setEnabled(True)
        self.edit_path.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("取消")

    # 关窗时确保线程收尾，避免 QThread 还在跑而对象被销毁（会导致进程崩溃）
    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        super().closeEvent(event)


# ===================== 独立预览（直接 python download_dialog.py 就能看效果） =====================
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    demo = [
        DownloadItem("手势刷_手机版.apk", path=os.path.abspath(__file__), size=os.path.getsize(__file__)),
        DownloadItem("Wireshark-4.6.8-x64.exe", size=78 * 1024 * 1024),
    ]
    dlg = DownloadDialog(None, demo, dark=True, title="下载工具")
    dlg.exec()
