using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MemoryKiller
{
    /// <summary>
    /// 主界面：shadcn 风格暗色，纯代码构建（无 .resx / Designer 依赖）。
    /// 展示硬件配置 + 内存状态 + 一键极限优化。核心逻辑不变。
    /// </summary>
    public sealed class MainForm : Form
    {
        private readonly ModernField _fldCpu = new ModernField(true);
        private readonly ModernField _fldGpu = new ModernField(true);
        private readonly ModernField _fldRam = new ModernField(false);
        private readonly ModernField _fldLog = new ModernField(true);

        private readonly Label _lblMemBefore = new Label();
        private readonly Label _lblMemAfter = new Label();
        private readonly ModernProgressBar _memBar = new ModernProgressBar();

        private readonly ModernCheckBox _chkSkipForeground = new ModernCheckBox();
        private readonly ModernCheckBox _chkSvchost = new ModernCheckBox();

        private readonly ModernButton _btnOptimize = new ModernButton();
        private readonly ModernButton _btnRefresh = new ModernButton();
        private readonly Label _lblEstimate = new Label();
        private readonly Label _lblDisclaimer = new Label();

        public MainForm()
        {
            InitializeComponent();
            LoadHardware();
            RefreshMemory();
        }

        private void InitializeComponent()
        {
            Text = "内存杀手  Memory Killer";
            ClientSize = new Size(Theme.S(760), Theme.S(760));
            BackColor = Theme.Bg;
            ForeColor = Theme.Fg;
            Font = Theme.UiFont;
            AutoScaleMode = AutoScaleMode.Dpi;
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            DoubleBuffered = true;

            // 顶部标题区
            var title = new Label
            {
                Text = "内存杀手",
                Location = new Point(Theme.S(20), Theme.S(16)),
                Size = new Size(Theme.S(320), Theme.S(32)),
                Font = new Font("Segoe UI", 20F, FontStyle.Bold),
                ForeColor = Theme.Fg
            };
            var subtitle = new Label
            {
                Text = "一键清空进程工作集 · 释放物理内存 · 需管理员权限",
                Location = new Point(Theme.S(22), Theme.S(50)),
                Size = new Size(Theme.S(520), Theme.S(18)),
                Font = Theme.UiFontSmall,
                ForeColor = Theme.Muted
            };

            // 硬件卡片
            var gbHw = new ModernCard { HeaderText = "硬件配置", Location = new Point(Theme.S(20), Theme.S(72)), Size = new Size(Theme.S(720), Theme.S(185)) };
            var lblCpu = new Label { Text = "CPU", Location = new Point(Theme.S(16), Theme.S(50)), Size = new Size(Theme.S(48), Theme.S(20)), ForeColor = Theme.Muted, Font = Theme.UiFont };
            var lblGpu = new Label { Text = "GPU", Location = new Point(Theme.S(16), Theme.S(92)), Size = new Size(Theme.S(48), Theme.S(20)), ForeColor = Theme.Muted, Font = Theme.UiFont };
            var lblRam = new Label { Text = "内存", Location = new Point(Theme.S(16), Theme.S(138)), Size = new Size(Theme.S(48), Theme.S(20)), ForeColor = Theme.Muted, Font = Theme.UiFont };
            _fldCpu.Location = new Point(Theme.S(70), Theme.S(46)); _fldCpu.Size = new Size(Theme.S(624), Theme.S(40));
            _fldGpu.Location = new Point(Theme.S(70), Theme.S(88)); _fldGpu.Size = new Size(Theme.S(624), Theme.S(42));
            _fldRam.Location = new Point(Theme.S(70), Theme.S(134)); _fldRam.Size = new Size(Theme.S(624), Theme.S(22));
            _fldCpu.Inner.Font = Theme.DetailFont;
            _fldGpu.Inner.Font = Theme.DetailFont;
            _fldRam.Inner.Font = Theme.DetailFont;
            gbHw.Controls.AddRange(new Control[] { lblCpu, lblGpu, lblRam, _fldCpu, _fldGpu, _fldRam });

            // 内存卡片
            var gbMem = new ModernCard { HeaderText = "内存状态", Location = new Point(Theme.S(20), Theme.S(269)), Size = new Size(Theme.S(720), Theme.S(120)) };
            _lblMemBefore.Location = new Point(Theme.S(16), Theme.S(50)); _lblMemBefore.Size = new Size(Theme.S(688), Theme.S(20)); _lblMemBefore.ForeColor = Theme.Fg;
            _memBar.Location = new Point(Theme.S(16), Theme.S(76)); _memBar.Size = new Size(Theme.S(688), Theme.S(22));
            _lblMemAfter.Location = new Point(Theme.S(16), Theme.S(102)); _lblMemAfter.Size = new Size(Theme.S(688), Theme.S(20)); _lblMemAfter.ForeColor = Theme.Muted;
            gbMem.Controls.AddRange(new Control[] { _lblMemBefore, _memBar, _lblMemAfter });

            // 选项
            _chkSkipForeground.Text = "跳过前台活动进程（避免正在用的程序卡顿，推荐）";
            _chkSkipForeground.Location = new Point(Theme.S(20), Theme.S(405)); _chkSkipForeground.Checked = true;
            _chkSvchost.Text = "包含 svchost 系统服务进程（更激进，可能导致网络/音频短暂异常，谨慎）";
            _chkSvchost.Location = new Point(Theme.S(20), Theme.S(435)); _chkSvchost.Checked = false;

            // 优化按钮 + 刷新检测按钮（同一行：优化占左侧大块，刷新占右侧）
            _btnOptimize.Text = "⚡ 极限优化内存";
            _btnOptimize.Location = new Point(Theme.S(20), Theme.S(471)); _btnOptimize.Size = new Size(Theme.S(490), Theme.S(54));
            _btnOptimize.Font = new Font("Segoe UI", 14F * Theme.FontScale, FontStyle.Bold);
            _btnOptimize.Click += OnOptimizeClick;

            _btnRefresh.Text = "⟳ 刷新检测";
            _btnRefresh.Location = new Point(Theme.S(525), Theme.S(471)); _btnRefresh.Size = new Size(Theme.S(215), Theme.S(54));
            _btnRefresh.Font = new Font("Segoe UI", 12F * Theme.FontScale, FontStyle.Bold);
            _btnRefresh.ForeColor = Color.White;
            _btnRefresh.Click += OnRefreshClick;

            // 可回收容量估算结果行
            _lblEstimate.Text = "点击「刷新检测」查看当前可回收的内存容量";
            _lblEstimate.Location = new Point(Theme.S(20), Theme.S(533)); _lblEstimate.Size = new Size(Theme.S(720), Theme.S(24));
            _lblEstimate.ForeColor = Theme.SuccessLight; _lblEstimate.Font = new Font("Segoe UI", 11F, FontStyle.Bold);

            // 日志
            _fldLog.Location = new Point(Theme.S(20), Theme.S(562)); _fldLog.Size = new Size(Theme.S(720), Theme.S(140));
            _fldLog.Inner.ScrollBars = ScrollBars.Vertical;
            _fldLog.Inner.Font = Theme.MonoFont;
            _fldLog.Inner.ForeColor = Color.FromArgb(134, 239, 172); // emerald-300

            // 说明
            _lblDisclaimer.Text = "说明：极限优化 = 清空进程工作集 ＋ 写回已修改页 ＋ 清理待机列表（Standby List），一次点完。EmptyWorkingSet 仅释放 RAM 工作集（把冷页换入分页文件），无法强制释放 GPU 显存；CPU 无需也无法被此工具优化。待机缓存被清后首次访问需重新读盘，建议仅在启动大型程序前使用一次。";
            _lblDisclaimer.Location = new Point(Theme.S(20), Theme.S(712)); _lblDisclaimer.Size = new Size(Theme.S(720), Theme.S(26));
            _lblDisclaimer.ForeColor = Theme.Muted; _lblDisclaimer.Font = Theme.UiFontSmall;

            Controls.AddRange(new Control[] {
                title, subtitle, gbHw, gbMem,
                _chkSkipForeground, _chkSvchost,
                _btnOptimize, _btnRefresh, _lblEstimate, _fldLog, _lblDisclaimer
            });
        }

        private void LoadHardware()
        {
            var cpu = HardwareInfo.GetCpu();
            _fldCpu.Inner.Text = $"{cpu.Name}\r\n物理核心 {cpu.Cores} / 逻辑核心 {cpu.Logical} · 最高 {(cpu.MaxClockMHz / 1000.0):F2} GHz";

            var gpus = HardwareInfo.GetGpus();
            var sbGpu = new System.Text.StringBuilder();
            foreach (var g in gpus)
            {
                string vram = g.AdapterRAMBytes > 0
                    ? $" · 显存约 {(g.AdapterRAMBytes >> 30):F1} GB"
                    : "";
                sbGpu.AppendLine($"{g.Name}{vram} · 驱动 {g.DriverVersion}");
            }
            _fldGpu.Inner.Text = sbGpu.ToString().TrimEnd();

            var ram = HardwareInfo.GetRam();
            string total = ram.TotalBytes > 0 ? $"{(ram.TotalBytes >> 30):F1} GB" : "未知";
            _fldRam.Inner.Text = $"已安装物理内存 {total} · 频率 {ram.SpeedMHz} MHz · 厂商 {ram.Manufacturer}";
        }

        private void RefreshMemory()
        {
            var ms = new NativeMethods.MEMORYSTATUSEX();
            ms.dwLength = (uint)MarshalSizeOfMem();
            if (NativeMethods.GlobalMemoryStatusEx(ref ms))
            {
                ulong used = ms.ullTotalPhys - ms.ullAvailPhys;
                _lblMemBefore.Text = $"优化前：已用 {(used >> 30):F1} GB / 共 {(ms.ullTotalPhys >> 30):F1} GB （占用 {ms.dwMemoryLoad}%）";
                _memBar.Value = Math.Min(100, (int)ms.dwMemoryLoad);
            }
            else
            {
                _lblMemBefore.Text = "无法读取内存状态。";
            }
        }

        private static int MarshalSizeOfMem()
        {
            return Marshal.SizeOf<NativeMethods.MEMORYSTATUSEX>();
        }

        private async void OnOptimizeClick(object? sender, EventArgs e)
        {
            _btnOptimize.Enabled = false;
            _fldLog.Inner.Clear();
            AppendLog("开始极限优化…");

            bool skipFg = _chkSkipForeground.Checked;
            bool svchost = _chkSvchost.Checked;

            ulong beforeAvail = GetAvailPhys();

            await Task.Run(() =>
            {
                var r = MemoryOptimizer.Optimize(svchost, skipFg);
                foreach (var line in r.Log)
                    AppendLog(line);
            });

            RefreshMemory();
            ulong afterAvail = GetAvailPhys();
            long delta = (long)(afterAvail - beforeAvail);
            _lblMemAfter.Text = $"优化后：可用物理内存增加约 {BytesToGb(delta)} GB";
            AppendLog($"可用物理内存变化：{(delta >= 0 ? "+" : "")}{BytesToGb(delta)} GB");
            AppendLog("完成。建议在启动大型程序前使用，日常不必频繁清理。");

            _btnOptimize.Enabled = true;
        }

        /// <summary>
        /// 刷新检测：实时估算当前「理论上最多可回收多少内存」。
        /// 进程侧依据 Σ(工作集 - 最小工作集)，系统侧加上待机列表与已修改页列表。
        /// </summary>
        private async void OnRefreshClick(object? sender, EventArgs e)
        {
            _btnRefresh.Enabled = false;
            _lblEstimate.ForeColor = Theme.Muted;
            _lblEstimate.Text = "正在实时检测可回收内存…";
            RefreshMemory();

            bool includeSvchost = _chkSvchost.Checked;
            bool skipFg = _chkSkipForeground.Checked;

            var est = await Task.Run(() => MemoryOptimizer.EstimateReclaimable(includeSvchost, skipFg));

            double wsUpper = est.ReclaimableWorkingSetBytes / 1024.0 / 1024.0 / 1024.0;
            double standbyGb = est.StandbyBytes / 1024.0 / 1024.0 / 1024.0;
            double modifiedGb = est.ModifiedPageListBytes / 1024.0 / 1024.0 / 1024.0;
            double total = est.TotalUpperBoundBytes / 1024.0 / 1024.0 / 1024.0;

            _lblEstimate.ForeColor = Theme.SuccessLight;
            _lblEstimate.Text = $"预计理论上限可回收 ≈ {total:F2} GB（{est.TargetCount} 个进程 {wsUpper:F2} GB"
                                + $" ＋ 待机列表 {standbyGb:F2} GB"
                                + "）";

            AppendLog($"[检测] 目标进程 {est.TargetCount} 个，当前工作集合计 {(est.TargetWorkingSetBytes / 1024.0 / 1024.0 / 1024.0):F2} GB。");
            AppendLog($"[检测] 进程侧可回收上限 ≈ {wsUpper:F2} GB，待机列表 ≈ {standbyGb:F2} GB，已修改页 ≈ {modifiedGb:F2} GB。");
            AppendLog($"[检测] 合计理论上限 ≈ {total:F2} GB（实际释放以执行后的实测值为准）。");
            int n = Math.Min(5, est.Top.Count);
            if (n > 0)
            {
                AppendLog("[检测] 可回收量前 " + n + " 名：");
                for (int i = 0; i < n; i++)
                {
                    var t = est.Top[i];
                    AppendLog($"   {(i + 1)}. {t.Name} (PID {t.Pid}) — {t.ReclaimBytes / 1024.0 / 1024.0:F1} MB");
                }
            }

            _btnRefresh.Enabled = true;
        }

        private void AppendLog(string text)
        {
            if (InvokeRequired)
            {
                Invoke(new Action<string>(AppendLog), text);
                return;
            }
            _fldLog.Inner.AppendText(text + Environment.NewLine);
        }

        private static ulong GetAvailPhys()
        {
            var ms = new NativeMethods.MEMORYSTATUSEX();
            ms.dwLength = (uint)Marshal.SizeOf<NativeMethods.MEMORYSTATUSEX>();
            return NativeMethods.GlobalMemoryStatusEx(ref ms) ? ms.ullAvailPhys : 0;
        }

        private static string BytesToGb(long bytes)
        {
            return (bytes / 1024.0 / 1024.0 / 1024.0).ToString("F2");
        }
    }
}
