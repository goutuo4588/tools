# -*- coding: utf-8 -*-
"""一次性素材生成脚本（不参与打包，仅开发期生成背景图用）。

把 800x800 白底柴犬原图做成 1600x1080 的玻璃拟态背景 bg_blur.jpg：
  1) 抠掉白底（按亮度阈值生成 alpha，边缘做羽化，避免锯齿）
  2) 用亮度遮罩把原图里的黑色栏杆线压掉（暗部 -> 透明）
  3) 狗身做高斯模糊 + 整体降不透明度，作为"氛围层"
  4) 底层铺柔和的暖色径向渐变，保证前景文字对比度
关键原则：所有模糊/羽化都在这里离线完成，打包后的运行时零模糊运算。
"""
import os
from PIL import Image, ImageFilter, ImageDraw, ImageChops

SRC = r"C:\Users\30689\OneDrive\图片\狗托是个啥.png"
OUT = r"E:\Temp\2026-10-17-19-01-52\C盘利刃_优化版\bg_blur.jpg"
W, H = 1600, 1080
DOG_H = 1180         # 狗更高：原图只有 800px，放太小在 1600 宽画布里会被大片留白稀释
DOG_BLUR = 14.0# 狗的模糊半径：这是背景不是贴纸，要糊到"只看出轮廓"
DOG_ALPHA = 0.62# 狗的整体不透明度：压低，保证前景文字对比度
WASH_BLUR = 0# 底层渐变自身不需要模糊
RAIL_MIN_SPAN = 120# 灰像素水平连续段超过这个长度才判为"栏杆行"
RAIL_ROW_FRAC = 0.10# 单行最长灰段占图像宽度的比例下限（约118px，与MIN_SPAN 同量级）
RAIL_GRAY_TOL = 14   # R/G/B 三通道最大最小之差<=此值即视为"灰"（无彩色）
FACE = (330, 300, 560, 520)  # 五官保护区（源图坐标）


def build_gray_mask(rgb):
    """找出"无彩色"的像素：R/G/B 三通道的最大最小之差 <= RAIL_GRAY_TOL。

    实测（源图采样）：
      - 栏杆 (223,223,225) / (0,0,0)      通道差 2 / 0  -> 纯灰
      - 狗身 (248,218,104)                通道差 144      -> 黄
      - 眼白 (19,5,4)                     通道差 15       -> 接近灰，靠 tol 卡住
      - 嘴 (239,232,194)                  通道差 45       -> 淡黄
    纯白背景(255,255,255)也是灰，用亮度 <=242 排除掉。
    """
    w, h = rgb.size
    px = rgb.load()
    m = Image.new("L", (w, h), 0)
    mp = m.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            mx = r if r > g else g
            if b > mx:
                mx = b
            mn = r if r < g else g
            if b < mn:
                mn = b
            if mx - mn <= RAIL_GRAY_TOL and mx <= 242:
                mp[x, y] = 255
    return m


def kill_railing_lines(rgb, dark_mask):
    """抹掉原图里的黑色/灰色栏杆线，保留狗的五官（眼睛/鼻子/嘴）与身体轮廓。

    判据（三个条件同时成立才算栏杆）：
      1) 像素无彩色（三通道差 <= RAIL_GRAY_TOL）——狗是黄的，栏杆是纯灰
      2) 所在行的最长连续灰段 >= RAIL_MIN_SPAN 且占图宽 >= RAIL_ROW_FRAC
         ——栏杆横穿画面；狗的五官/轮廓跨度都 <13% 图宽
      3) 不在五官保护区（源图 x330-560, y300-520）内
    """
    w, h = rgb.size
    sx = DOG_H / 800.0
    fx0, fy0, fx1, fy1 = (int(v * sx) for v in FACE)

    gray = build_gray_mask(rgb)
    gp = gray.load()
    dp = list(dark_mask.getdata())
    kill = Image.new("L", (w, h), 0)
    kp = kill.load()
    rail_rows = 0
    for y in range(h):
        row = y * w
        best, cur = 0, 0
        for x in range(w):
            if gp[x, y]:
                cur += 1
                if cur > best:
                    best = cur
            else:
                cur = 0
        if best < RAIL_MIN_SPAN or best < w * RAIL_ROW_FRAC:
            continue          # 跨度不够 -> 不是栏杆行
        rail_rows += 1
        for x in range(w):
            if not gp[x, y]:
                continue
            if fy0 <= y <= fy1 and fx0 <= x <= fx1:
                continue      # 五官保护区一律不动
            dp[row + x] = 0   # 抹掉灰像素对应的暗部标记
            kp[x, y] = 255    # 并记录为"必须全透明的栏杆像素"
    print("  栏杆行数:", rail_rows, " 栏杆像素:", sum(kill.histogram()[255:]))

    out = Image.new("L", (w, h))
    out.putdata(dp)
    return out, kill


def build_dog_layer():
    im = Image.open(SRC).convert("RGB")
    # 原图 800x800，按目标高度放大（lanczos 保证边缘平滑）
    scale = DOG_H / im.height
    big = im.resize((int(im.width * scale), DOG_H), Image.LANCZOS)

    # 亮度分布实测：狗身主体集中在 208-215(16%)，白底 248-255(55%)，
    # 栏杆与轮廓 0-177(14%)。栏杆与五官同属暗部，**先按颜色+跨度抹掉栏杆**。
    dark = big.convert("L").point(lambda v: 255 if v <= 206 else 0)
    dark, kill = kill_railing_lines(big, dark)
    # 抹线后剩下的"非栏杆暗部"就是五官与轮廓，作为额外alpha 支撑
    keep = dark

    # alpha = f(亮度)：白底 -> 0；栏杆 -> 0（由 kill 掩码强制清零）；
    # 狗身/五官 -> 不透明
    lum = big.convert("L")

    def lut(v):
        if v >= 238:
            return 0          # 白底 -> 全透明
        if v >= 229:
            return int((238 - v) / 9 * 255)    # 白底边缘 -> 羽化带
        return 255            # 暗部一律保留（五官靠掩码已排除栏杆）

    alpha = lum.point(lut)
    # 把"非栏杆暗部"当作额外的 alpha 支撑：暗部像素完全不透明，
    # 这样五官不会被白底羽化带吃掉
    alpha = ImageChops.lighter(alpha, keep.filter(ImageFilter.GaussianBlur(0.8)))
    # 栏杆像素强制清零（栏杆多为中间调灰，亮度 LUT 会把它们留下）。
    # 用 MaxFilter 做形态学膨胀，把栏杆边缘的抗锯齿过渡带一并吃掉，
    # 否则会残留一圈淡灰描边。
    alpha = ImageChops.subtract(alpha, kill.filter(ImageFilter.MaxFilter(11)))
    # 轻微模糊 alpha，让抠图边缘自然（这一步同样离线完成）
    alpha = alpha.filter(ImageFilter.GaussianBlur(1.0))

    # 关键：狗身 RGB 保持原样，不做任何 point() 映射。
    # PIL 的 point() 在 RGB 图上三个通道共享同一张 256 项 LUT，按通道值索引会
    # 把柴犬黄(R249,G218,B102)映射成完全不同的颜色（实测变成 254,254,251 近白），
    # 整只狗因此发灰发白。
    dog = big.convert("RGBA")
    dog.putalpha(alpha.point(lambda v: int(v * DOG_ALPHA)))

    # 狗自身也做一次真模糊（离线）
    dog = dog.filter(ImageFilter.GaussianBlur(DOG_BLUR))
    return dog


def build_wash():
    """柔和的暖白底场：偏暖的米白，中心一片淡暖黄柔光，四周自然过渡无硬边。
    注意别做得太亮——底场越亮，狗的黄色对比度越低，整体就发灰。"""
    base = Image.new("RGB", (W, H), (248, 245, 238))

    glow = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(glow)
    d.ellipse([W // 2 - 700, H // 2 - 500, W // 2 + 700, H // 2 + 500], fill=95)
    glow = glow.filter(ImageFilter.GaussianBlur(300))
    warm = Image.new("RGB", (W, H), (250, 234, 196))
    return Image.composite(warm, base, glow)


def main():
    wash = build_wash()
    dog = build_dog_layer()

    x = (W - dog.width) // 2
    y = (H - dog.height) // 2
    out = wash.convert("RGBA")
    out.alpha_composite(dog, (x, y))

    # 整图统一轻模糊：把狗和底场的色块过渡揉在一起，去掉"贴纸感"
    out = out.filter(ImageFilter.GaussianBlur(1.2))
    out.convert("RGB").save(OUT, "JPEG", quality=92, optimize=True)
    print("saved:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()