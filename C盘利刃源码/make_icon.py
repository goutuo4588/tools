# -*- coding: utf-8 -*-
"""把 AI 生成的 1024 图标处理成标准应用图标集。

要做两件事：
  1)抠掉白底/投影 -> 真正透明（Windows 桌面图标带投影会显脏）
  2) 导出多尺寸 ico（16/24/32/48/64/128/256）+ 独立 png，供 exe/网站/favicon 用
"""
import os
from PIL import Image, ImageChops

SRC = r"E:\Temp\2026-10-17-19-01-52\generated-images\A_premium_professional_Windows_2026-10-18T16-15-17.png"
OUTDIR = r"E:\Temp\2026-10-17-19-01-52\C盘利刃_优化版\icons"
os.makedirs(OUTDIR, exist_ok=True)

im = Image.open(SRC).convert("RGBA")
r, g, b, a = im.split()

# --- 抠背景：白->透明。阈值取 >=246 全透明，240-246 给一档羽化避免白边 ---
def bg_lut(v):
    if v >= 246:
        return 0
    if v >= 240:
        return int((246 - v) / 6 * 255)
    return 255

alpha = r.point(bg_lut)
# 保证白底像素的RGB 也清成徽标主色，避免半透明边缘出现白边
im.putalpha(alpha)

# --- 裁掉底部投影：投影在最下方、很淡。按"每行不透明像素占比"找主体底边 ---
w, h = im.size
ap = im.getchannel("A").load()
rows = []
for y in range(h):
    n = sum(1 for x in range(w) if ap[x, y] > 40)
    rows.append(n)
# 主体结束 = 最后一行占比 >= 全图最大占比 20% 的位置
mx = max(rows)
body_end = h - 1
for y in range(h):
    if rows[y] >= mx * 0.20:
        body_end = y
# 再往下留 4% 余量，保留徽标底部圆角
pad = int(h * 0.04)
bottom = min(h - 1, body_end + pad)
cropped = im.crop((0, 0, w, bottom + 1))
print("原图 %dx%d -> 裁剪后 %dx%d (底部投影已去除)" % (w, h, cropped.width, cropped.height))

# 居中放进正方形画布，四周留 4% 边距（Windows 图标视觉更饱满）
side = max(cropped.size)
margin = int(side * 0.04)
canvas = side + margin * 2
square = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
square.paste(cropped, ((canvas - cropped.width) // 2,
                        (canvas - cropped.height) // 2), cropped)
master = square
print("正方形主图:", master.size)

master.save(os.path.join(OUTDIR, "icon_1024.png"), "PNG")

SIZES = [16, 24, 32, 48, 64, 128, 256]
for s in SIZES:
    # 大尺寸用 LANCZOS 缩放；<=32 的小图标先 4 倍超采样再降，提升边缘质量
    if s <= 32:
        big = master.resize((s * 4, s * 4), Image.LANCZOS)
        img = big.resize((s, s), Image.LANCZOS)
    else:
        img = master.resize((s, s), Image.LANCZOS)
    img.save(os.path.join(OUTDIR, "icon_%d.png" % s), "PNG")
    print("  icon_%d.png" % s)

# 多尺寸 ico
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
master.save(os.path.join(OUTDIR, "icon.ico"),
            "ICO", sizes=ico_sizes)
print("icon.ico 生成完毕")
for f in sorted(os.listdir(OUTDIR)):
    print("   %-16s %7d bytes" % (f, os.path.getsize(os.path.join(OUTDIR, f))))