# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置
#   icon.ico     -> 写进 PE 头，决定 exe 在桌面/任务栏/资源管理器/安装包里的图标
#   icon_256.png -> 运行时窗口图标（QApplication.setWindowIcon）
#   bg_blur.jpg  -> 玻璃拟态背景（模糊已离线烘好，运行时零模糊运算）

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('bg_blur.jpg', '.'), ('icon.ico', '.'), ('icon_256.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='C盘利刃',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 图标烧进 PE 资源：桌面 / 任务栏 / 资源管理器 / 安装包都会正确显示
    icon='icon.ico',
)
