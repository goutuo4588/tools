using System;
using System.Diagnostics;
using System.IO;
using System.Security.Principal;
using System.Windows.Forms;

namespace MemoryKiller
{
    internal static class Program
    {
        private static readonly string CrashLog =
            Path.Combine(Path.GetDirectoryName(Application.ExecutablePath) ?? ".", "MemoryKiller.crash.log");

        [STAThread]
        private static void Main()
        {
            // 全局崩溃兜底：把任何未处理异常写入 exe 同目录的 crash 日志并弹窗，避免“什么都没发生”
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += (s, e) => DumpCrash(e.Exception);
            AppDomain.CurrentDomain.UnhandledException += (s, e) =>
                DumpCrash(e.ExceptionObject as Exception ?? new Exception("未知异常"));

            if (!IsRunningAsAdmin())
            {
                // manifest 不再强制提权，这里显式询问，点取消也不再静默无反应
                var r = MessageBox.Show(
                    "内存杀手需要管理员权限才能清空其他进程的工作集。\n是否立即以管理员身份重新启动？",
                    "内存杀手", MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                if (r == DialogResult.Yes)
                {
                    try
                    {
                        var psi = new ProcessStartInfo
                        {
                            UseShellExecute = true,
                            FileName = Application.ExecutablePath,
                            Verb = "runas",
                            Arguments = string.Join(" ", Environment.GetCommandLineArgs()[1..])
                        };
                        using var p = Process.Start(psi);
                        return; // 子进程已提权启动，本进程退出
                    }
                    catch (Exception ex)
                    {
                        MessageBox.Show("请求管理员权限失败：" + ex.Message,
                            "内存杀手", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    }
                }
                else
                {
                    MessageBox.Show("未获得管理员权限，无法清理其他进程的内存。已退出。",
                        "内存杀手", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                return;
            }

            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }

        private static void DumpCrash(Exception ex)
        {
            try
            {
                var sb = new System.Text.StringBuilder();
                sb.AppendLine("==== MemoryKiller 崩溃日志 " + DateTime.Now + " ====");
                sb.AppendLine(ex.ToString());
                sb.AppendLine();
                File.AppendAllText(CrashLog, sb.ToString());
            }
            catch { }
            MessageBox.Show(
                "程序启动失败，已将错误写入：\n" + CrashLog + "\n\n" + ex.GetType().Name + ": " + ex.Message,
                "内存杀手", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Environment.Exit(1);
        }

        private static bool IsRunningAsAdmin()
        {
            try
            {
                using var identity = WindowsIdentity.GetCurrent();
                var principal = new WindowsPrincipal(identity);
                return principal.IsInRole(WindowsBuiltInRole.Administrator);
            }
            catch
            {
                return false;
            }
        }
    }
}
