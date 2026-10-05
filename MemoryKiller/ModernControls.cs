using System;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace MemoryKiller
{
    /// <summary>
    /// shadcn 风格暗色调色板（zinc 系 + 红色强调 + emerald 成功色）。
    /// </summary>
    internal static class Theme
    {
        public static readonly Color Bg = Color.FromArgb(9, 9, 11);            // zinc-950
        public static readonly Color Card = Color.FromArgb(24, 24, 27);        // zinc-900
        public static readonly Color Border = Color.FromArgb(39, 39, 42);      // zinc-800
        public static readonly Color BorderStrong = Color.FromArgb(63, 63, 70);// zinc-700
        public static readonly Color Fg = Color.FromArgb(250, 250, 250);       // zinc-50
        public static readonly Color Muted = Color.FromArgb(161, 161, 170);    // zinc-400
        public static readonly Color Accent = Color.FromArgb(239, 68, 68);     // red-500
        public static readonly Color AccentHover = Color.FromArgb(248, 113, 113); // red-400
        public static readonly Color AccentPress = Color.FromArgb(220, 38, 38);   // red-600
        public static readonly Color Success = Color.FromArgb(16, 185, 129);   // emerald-500
        public static readonly Color SuccessLight = Color.FromArgb(52, 211, 153); // emerald-400

        public static readonly Font UiFont = new Font("Segoe UI", 11F);
        public static readonly Font UiFontSmall = new Font("Segoe UI", 9.5F);
        public static readonly Font MonoFont = new Font("Consolas", 10F);
        // 硬件详细信息（CPU / GPU / 内存）正文：比常规正文小一档，信息更密集
        public static readonly Font DetailFont = new Font("Segoe UI", 8.5F);

        // 全局 UI 缩放系数：想整体放大/缩小改这一个值即可（MainForm 与 ModernCard 标题都用它）
        public const float Scale = 1.8f;
        public static int S(int v) => (int)Math.Round(v * Scale);

        // 字号单独倍率：只作用于「乘了 Scale 的大号白字」（卡片标题、按钮文字），
        // 与布局缩放解耦，方便单独调小/调大而不影响整体布局。
        public const float FontScale = 1.35f;

        public static GraphicsPath RoundedRect(Rectangle bounds, int radius)
        {
            radius = Math.Min(radius, bounds.Width / 2);
            radius = Math.Min(radius, bounds.Height / 2);
            int r = radius * 2;
            var path = new GraphicsPath();
            path.AddArc(bounds.X, bounds.Y, r, r, 180, 90);
            path.AddArc(bounds.Right - r, bounds.Y, r, r, 270, 90);
            path.AddArc(bounds.Right - r, bounds.Bottom - r, r, r, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - r, r, r, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    /// <summary>
    /// 圆角卡片：填充 Card 色 + 1px Border 描边，可选标题与分隔线。
    /// </summary>
    internal class ModernCard : Panel
    {
        [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
        public string HeaderText { get; set; } = "";

        public ModernCard()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint
                     | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.UserPaint
                     | ControlStyles.ResizeRedraw
                     | ControlStyles.SupportsTransparentBackColor, true);
            UpdateStyles();
            Padding = new Padding(0);
            BackColor = Color.Transparent;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;

            var rect = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var path = Theme.RoundedRect(rect, 12))
            {
                using (var brush = new SolidBrush(Theme.Card))
                    g.FillPath(brush, path);
                using (var pen = new Pen(Theme.Border, 1))
                    g.DrawPath(pen, path);
            }

            if (!string.IsNullOrEmpty(HeaderText))
            {
                using (var b = new SolidBrush(Theme.Fg))
                using (var f = new Font("Segoe UI", 12F * Theme.FontScale, FontStyle.Bold))
                    g.DrawString(HeaderText, f, b, new PointF(Theme.S(16), Theme.S(12)));
                using (var pen = new Pen(Theme.Border, 1))
                    g.DrawLine(pen, Theme.S(16), Theme.S(38), Width - Theme.S(16), Theme.S(38));
            }

            base.OnPaint(e);
        }
    }

    /// <summary>
    /// 圆角输入框容器：内嵌无边框 TextBox，外描边模拟 shadcn input。
    /// </summary>
    internal class ModernField : Panel
    {
        public TextBox Inner;

        public ModernField(bool multiline = false)
        {
            DoubleBuffered = true;
            ResizeRedraw = true;
            Padding = new Padding(Theme.S(8));
            Inner = new TextBox
            {
                BorderStyle = BorderStyle.None,
                BackColor = Theme.Bg,
                ForeColor = Theme.Fg,
                Multiline = multiline,
                ReadOnly = true,
                Dock = DockStyle.Fill,
                Font = Theme.UiFont
            };
            Controls.Add(Inner);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var rect = new Rectangle(0, 0, Width - 1, Height - 1);
            using (var path = Theme.RoundedRect(rect, 8))
            {
                using (var brush = new SolidBrush(Theme.Bg))
                    g.FillPath(brush, path);
                using (var pen = new Pen(Theme.Border, 1))
                    g.DrawPath(pen, path);
            }
            base.OnPaint(e);
        }
    }

    /// <summary>
    /// 圆角主按钮：纯自绘，带 hover / press / disabled 三态。
    /// </summary>
    internal class ModernButton : Button
    {
        private bool _hover, _press;

        public ModernButton()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.ResizeRedraw | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.SupportsTransparentBackColor, true);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            BackColor = Color.Transparent;
            ForeColor = Color.White;
            Cursor = Cursors.Hand;
        }

        protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { _hover = false; _press = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { _press = true; Invalidate(); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { _press = false; Invalidate(); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            var rect = new Rectangle(0, 0, Width - 1, Height - 1);
            Color fill = !Enabled ? Theme.BorderStrong
                        : _press ? Theme.AccentPress
                        : _hover ? Theme.AccentHover
                        : Theme.Accent;
            using (var path = Theme.RoundedRect(rect, 10))
            using (var brush = new SolidBrush(fill))
                g.FillPath(brush, path);

            var flags = TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine;
            TextRenderer.DrawText(g, Text, Font, ClientRectangle, !Enabled ? Theme.Muted : Color.White, flags);
        }
    }

    /// <summary>
    /// 圆角勾选框：自绘方块 + 对勾，点击切换 Checked。
    /// </summary>
    internal class ModernCheckBox : Control
    {
        private bool _hover;
        [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
        public bool Checked { get; set; }
        public event EventHandler? CheckedChanged;

        public ModernCheckBox()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                     ControlStyles.ResizeRedraw | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.SupportsTransparentBackColor, true);
            DoubleBuffered = true;
            BackColor = Color.Transparent;
            ForeColor = Color.FromArgb(212, 212, 216);
            Font = Theme.UiFont;
            Cursor = Cursors.Hand;
            AutoSize = true;
        }

        public override Size GetPreferredSize(Size proposedSize)
        {
            using var g = CreateGraphics();
            var ts = TextRenderer.MeasureText(g, Text, Font);
            return new Size(Theme.S(24) + ts.Width + Theme.S(4), Math.Max(Theme.S(20), ts.Height));
        }

        protected override void OnMouseEnter(EventArgs e) { _hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { _hover = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnClick(EventArgs e)
        {
            Checked = !Checked;
            CheckedChanged?.Invoke(this, e);
            Invalidate();
            base.OnClick(e);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int box = Theme.S(18);
            var boxRect = new Rectangle(0, (Height - box) / 2, box, box);
            using (var path = Theme.RoundedRect(boxRect, Theme.S(4)))
            {
                using (var brush = new SolidBrush(Checked ? Theme.Accent : Theme.Bg))
                    g.FillPath(brush, path);
                using (var pen = new Pen(Checked ? Theme.Accent : (_hover ? Theme.Accent : Theme.BorderStrong), 1.5f))
                    g.DrawPath(pen, path);
            }
            if (Checked)
            {
                using var pen = new Pen(Color.White, Theme.S(2));
                int cx = boxRect.X, cy = boxRect.Y;
                g.DrawLine(pen, cx + Theme.S(4), cy + Theme.S(9), cx + Theme.S(7), cy + Theme.S(12));
                g.DrawLine(pen, cx + Theme.S(7), cy + Theme.S(12), cx + Theme.S(14), cy + Theme.S(5));
            }
            var textRect = new Rectangle(box + 8, 0, Width - box - 8, Height);
            TextRenderer.DrawText(g, Text, Font, textRect, ForeColor,
                TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
        }
    }

    /// <summary>
    /// 圆角进度条：轨道 + 渐变填充，随 Value 增长。
    /// </summary>
    internal class ModernProgressBar : Control
    {
        [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
        public int Maximum { get; set; } = 100;
        private int _value;
        [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
        public int Value
        {
            get => _value;
            set { _value = Math.Max(0, Math.Min(Maximum, value)); Invalidate(); }
        }

        public ModernProgressBar()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint
                     | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.UserPaint
                     | ControlStyles.ResizeRedraw
                     | ControlStyles.SupportsTransparentBackColor, true);
            UpdateStyles();
            Height = 22;
            BackColor = Color.Transparent;
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int h = Height;
            var track = new Rectangle(0, 0, Width - 1, h - 1);
            using (var path = Theme.RoundedRect(track, h / 2))
            using (var brush = new SolidBrush(Theme.Border))
                g.FillPath(brush, path);

            if (_value > 0)
            {
                int w = (int)((Width - 1) * (double)_value / Maximum);
                w = Math.Max(h, w);
                var fill = new Rectangle(0, 0, w, h - 1);
                using (var path = Theme.RoundedRect(fill, h / 2))
                using (var brush = new LinearGradientBrush(fill, Theme.Success, Theme.SuccessLight, LinearGradientMode.Vertical))
                    g.FillPath(brush, path);
            }
        }
    }
}
