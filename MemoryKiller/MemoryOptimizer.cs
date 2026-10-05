using System;
using System.Collections.Generic;
using System.Linq;
using System.Management;
using System.Runtime.InteropServices;
using System.Text;

namespace MemoryKiller
{
    /// <summary>
    /// 内存优化核心逻辑：
    /// 枚举全部进程 -> 过滤保护进程 -> 对其余后台进程调用 EmptyWorkingSet
    /// -> 可选清理系统待机列表（Standby List）。
    /// </summary>
    internal sealed class OptimizeResult
    {
        public int Trimmed;
        public int Skipped;
        public int Failed;
        public long FreedWorkingSetBytes;
        public bool StandbyPurged;
        public List<string> Log = new List<string>();
    }

    /// <summary>
    /// 可回收内存估算结果（全部为「理论上限」，实际以优化后的实测为准）。
    /// 依据：EmptyWorkingSet 会把进程工作集压缩到不低于 MinimumWorkingSetSize。
    /// </summary>
    public sealed class EstimateItem
    {
        public string Name = "";
        public int Pid;
        public long ReclaimBytes;
    }

    public sealed class EstimateResult
    {
        public int TargetCount;                 // 会被优化的进程数
        public long TargetWorkingSetBytes;      // 目标进程当前工作集合计
        public long ReclaimableWorkingSetBytes; // 进程侧可回收上限 = Σ(工作集 - 最小工作集)
        public long StandbyBytes;               // 系统待机列表 Standby List
        public long ModifiedPageListBytes;      // 已修改页列表
        public long TotalUpperBoundBytes => ReclaimableWorkingSetBytes + StandbyBytes + ModifiedPageListBytes;
        public List<EstimateItem> Top = new List<EstimateItem>();
    }

    internal static class MemoryOptimizer
    {
        // 受保护的系统/关键进程：绝不触碰，避免系统不稳定。
        // 名称取自镜像文件名（含 .exe 不含路径），大小写不敏感。
        private static readonly HashSet<string> ProtectedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "system", "idle",
            "csrss.exe",            // 客户端/服务端运行时子系统
            "wininit.exe",          // Windows 初始化
            "services.exe",         // 服务控制管理器
            "lsass.exe",            // 本地安全认证
            "smss.exe",             // 会话管理
            "winlogon.exe",         // 登录/安全桌面
            "lsaiso.exe",           // 凭据隔离
            "explorer.exe",         // 桌面外壳（清了会闪屏）
            "dwm.exe",              // 桌面窗口管理器（清了会黑闪）
            "audiodg.exe",          // 音频设备图
            "conhost.exe",          // 控制台宿主
            "fontdrvhost.exe",      // 字体驱动
            "sihost.exe",           // Shell 输入托管
            "ctfmon.exe",           // 输入法
            "taskhostw.exe",        // 任务宿主
            "shellhost.exe",
            "securityhealthservice.exe",
            "memorykiller.exe",     // 自身
            "memorycompression.exe",// 内存压缩
            "registry.exe",         // 注册表
            "memcompress.exe"
        };

        public static OptimizeResult Optimize(bool includeSvchost, bool skipForeground)
        {
            var result = new OptimizeResult();

            // 前台活动进程：默认跳过，避免让正在用的程序卡顿
            uint fgPid = 0;
            if (skipForeground)
            {
                IntPtr hwnd = NativeMethods.GetForegroundWindow();
                if (hwnd != IntPtr.Zero)
                    NativeMethods.GetWindowThreadProcessId(hwnd, out fgPid);
            }

            int[] pids = EnumProcesses();
            int currentPid = NativeMethods.GetCurrentProcessId();
            result.Log.Add($"枚举到 {pids.Length} 个进程。");

            foreach (int pid in pids)
            {
                if (pid <= 0) continue;
                if (pid == 4) { result.Skipped++; continue; }   // System 进程
                if (pid == currentPid) { result.Skipped++; continue; }
                if (skipForeground && pid == (int)fgPid) { result.Skipped++; continue; }

                IntPtr hProc = NativeMethods.OpenProcess(
                    NativeMethods.PROCESS_QUERY_INFORMATION |
                    NativeMethods.PROCESS_SET_QUOTA |
                    NativeMethods.PROCESS_VM_OPERATION,
                    false, pid);
                if (hProc == IntPtr.Zero) { result.Failed++; continue; }

                try
                {
                    string name = GetImageName(hProc);
                    if (string.IsNullOrEmpty(name) || name == "?")
                    {
                        // 拿不到镜像名（受保护/访问拒绝），保守跳过
                        result.Skipped++;
                        continue;
                    }
                    if (ProtectedNames.Contains(name))
                    {
                        result.Skipped++;
                        continue;
                    }
                    if (!includeSvchost && name.Equals("svchost.exe", StringComparison.OrdinalIgnoreCase))
                    {
                        // svchost 承载大量系统服务，默认不碰；勾选后才清
                        result.Skipped++;
                        continue;
                    }

                    long before = GetWorkingSet(hProc);
                    if (NativeMethods.EmptyWorkingSet(hProc))
                    {
                        long after = GetWorkingSet(hProc);
                        long freed = before - after;
                        if (freed > 0) result.FreedWorkingSetBytes += freed;
                        result.Trimmed++;
                        if (result.Trimmed <= 40)
                            result.Log.Add($"已清空工作集: {name} (PID {pid}) 释放约 {BytesToMb(freed)} MB");
                    }
                    else
                    {
                        result.Failed++;
                    }
                }
                catch
                {
                    result.Failed++;
                }
                finally
                {
                    NativeMethods.CloseHandle(hProc);
                }
            }

            // ==== 系统级清理（无条件执行）====
            // 关键：清待机列表需要 SeProfileSingleProcessPrivilege，而它默认处于禁用状态，
            // 不先启用就会返回 0xC0000061（权限未持有），待机列表一个字节都清不掉。
            long standbyBefore = GetStandbyBytes();
            EnablePurgePrivileges(result);

            TryNtMemoryCommand("写回已修改页列表 (Modified List)", NativeMethods.MemoryFlushModifiedList, result);
            TryNtMemoryCommand("清理低优先级待机列表", NativeMethods.MemoryPurgeLowPriorityStandbyList, result);
            TryNtMemoryCommand("清理待机列表 (Standby List)", NativeMethods.MemoryPurgeStandbyList, result);

            long standbyAfter = GetStandbyBytes();
            result.StandbyPurged = standbyAfter < standbyBefore;
            result.Log.Add($"待机列表：{standbyBefore >> 20} MB → {standbyAfter >> 20} MB。");

            // 兜底：系统策略若拒绝清待机列表（返回 0xC0000061 等），改用物理页“硬挤”，
            // 即申请并触碰等量物理内存，迫使内存管理器交出待机页，然后立刻全部释放。
            if (standbyAfter > 64L * 1024 * 1024)
            {
                result.Log.Add("待机列表仍有较多残留，启用兜底：临时申请物理页强制回收缓存，随后立即释放。");
                ForceEvictStandby(result, Math.Min(standbyAfter, standbyBefore));
                long standbyFinal = GetStandbyBytes();
                result.Log.Add($"兜底后待机列表：{standbyFinal >> 20} MB。");
            }

            result.Log.Add(
                $"完成：清空 {result.Trimmed} 个进程，跳过 {result.Skipped} 个，失败 {result.Failed} 个，" +
                $"累计释放工作集约 {BytesToMb(result.FreedWorkingSetBytes)} MB。");
            return result;
        }

        /// <summary>
        /// 实时估算「点击优化后理论上最多能释放多少」。
        /// 进程过滤规则与 Optimize() 完全一致（受保护名单 / 前台 / svchost 开关），保证估算与实际动作对得上。
        /// 返回的是理论上限，不做玄学系数折算。
        /// </summary>
        public static EstimateResult EstimateReclaimable(bool includeSvchost, bool skipForeground)
        {
            var r = new EstimateResult();

            uint fgPid = 0;
            if (skipForeground)
            {
                IntPtr hwnd = NativeMethods.GetForegroundWindow();
                if (hwnd != IntPtr.Zero)
                    NativeMethods.GetWindowThreadProcessId(hwnd, out fgPid);
            }

            int currentPid = NativeMethods.GetCurrentProcessId();

            foreach (int pid in EnumProcesses())
            {
                if (pid <= 0) continue;
                if (pid == 4) continue;                 // System 进程
                if (pid == currentPid) continue;        // 自身
                if (skipForeground && pid == (int)fgPid) continue;

                IntPtr hProc = NativeMethods.OpenProcess(
                    NativeMethods.PROCESS_QUERY_INFORMATION | NativeMethods.PROCESS_VM_READ,
                    false, pid);
                if (hProc == IntPtr.Zero) continue;

                try
                {
                    string name = GetImageName(hProc);
                    if (string.IsNullOrEmpty(name) || name == "?") continue;
                    if (ProtectedNames.Contains(name)) continue;
                    if (!includeSvchost && name.Equals("svchost.exe", StringComparison.OrdinalIgnoreCase)) continue;

                    long ws = GetWorkingSet(hProc);
                    long min = 0;
                    if (NativeMethods.GetProcessWorkingSetSizeEx(hProc, out IntPtr minWs, out _, out _))
                        min = minWs.ToInt64();

                    long reclaim = Math.Max(0, ws - min);
                    r.TargetCount++;
                    r.TargetWorkingSetBytes += ws;
                    r.ReclaimableWorkingSetBytes += reclaim;
                    r.Top.Add(new EstimateItem { Name = name, Pid = pid, ReclaimBytes = reclaim });
                }
                catch
                {
                    // 单个进程读取失败不影响整体估算
                }
                finally
                {
                    NativeMethods.CloseHandle(hProc);
                }
            }

            r.Top.Sort((a, b) => b.ReclaimBytes.CompareTo(a.ReclaimBytes));

            // 待机列表与已修改页列表已固定纳入极限优化，估算始终计入
            ReadStandbyList(r);

            return r;
        }

        /// <summary>
        /// 通过 WMI 性能类读取待机列表与已修改页列表。性能类偶尔不可用/缺字段，全部 try/catch 兜底为 0。
        /// Standby 总量 = Core + NormalPriority + Reserve。
        /// </summary>
        private static void ReadStandbyList(EstimateResult r)
        {
            try
            {
                using var searcher = new ManagementObjectSearcher(
                    "SELECT StandbyCacheCoreBytes, StandbyCacheNormalPriorityBytes, StandbyCacheReserveBytes, ModifiedPageListBytes " +
                    "FROM Win32_PerfFormattedData_PerfOS_Memory");
                foreach (ManagementObject mo in searcher.Get())
                {
                    r.StandbyBytes = SumBytes(mo, "StandbyCacheCoreBytes", "StandbyCacheNormalPriorityBytes", "StandbyCacheReserveBytes");
                    r.ModifiedPageListBytes = SumBytes(mo, "ModifiedPageListBytes");
                    break;
                }
            }
            catch
            {
                r.StandbyBytes = 0;
                r.ModifiedPageListBytes = 0;
            }
        }

        private static long SumBytes(ManagementObject mo, params string[] props)
        {
            long total = 0;
            foreach (var p in props)
            {
                try
                {
                    if (mo[p] != null) total += Convert.ToInt64(mo[p]);
                }
                catch { }
            }
            return total;
        }

        private static int[] EnumProcesses()
        {
            int[] buffer = new int[1024];
            for (int attempt = 0; attempt < 6; attempt++)
            {
                if (NativeMethods.EnumProcesses(buffer, buffer.Length * 4, out int cbNeeded))
                {
                    int count = cbNeeded / 4;
                    if (count < buffer.Length)
                        return buffer.Take(count).ToArray();
                    buffer = new int[buffer.Length * 2];
                }
                else
                {
                    break;
                }
            }
            // 兜底：用托管 API 再试一次
            try
            {
                return System.Diagnostics.Process.GetProcesses().Select(p => p.Id).ToArray();
            }
            catch
            {
                return Array.Empty<int>();
            }
        }

        private static string GetImageName(IntPtr hProc)
        {
            var sb = new StringBuilder(1024);
            int size = sb.Capacity;
            if (NativeMethods.QueryFullProcessImageName(hProc, 0, sb, ref size))
                return System.IO.Path.GetFileName(sb.ToString());
            return "?";
        }

        private static long GetWorkingSet(IntPtr hProc)
        {
            NativeMethods.PROCESS_MEMORY_COUNTERS_EX pmc;
            pmc.cb = Marshal.SizeOf<NativeMethods.PROCESS_MEMORY_COUNTERS_EX>();
            if (NativeMethods.GetProcessMemoryInfo(hProc, out pmc, pmc.cb))
                return pmc.WorkingSetSize.ToInt64();
            return 0;
        }

        /// <summary>
        /// 启用清理待机列表所需的特权。管理员进程里 SeProfileSingleProcessPrivilege /
        /// SeIncreaseQuotaPrivilege 默认是「已拥有但未启用」，不开启则 NtSetSystemInformation 会失败。
        /// </summary>
        private static void EnablePurgePrivileges(OptimizeResult result)
        {
            string[] wanted = { "SeProfileSingleProcessPrivilege", "SeIncreaseQuotaPrivilege" };
            IntPtr hToken;
            if (!NativeMethods.OpenProcessToken(
                    NativeMethods.GetCurrentProcess(),
                    NativeMethods.TOKEN_QUERY | NativeMethods.TOKEN_ADJUST_PRIVILEGES,
                    out hToken))
            {
                result.Log.Add("无法打开进程令牌，跳过特权启用（Win32 错误 " + Marshal.GetLastWin32Error() + "）。");
                return;
            }

            try
            {
                foreach (string name in wanted)
                {
                    var tp = new NativeMethods.TOKEN_PRIVILEGES
                    {
                        PrivilegeCount = 1,
                        Privileges = new NativeMethods.LUID_AND_ATTRIBUTES
                        {
                            Attributes = NativeMethods.SE_PRIVILEGE_ENABLED
                        }
                    };

                    if (!NativeMethods.LookupPrivilegeValue(null, name, out tp.Privileges.Luid))
                    {
                        result.Log.Add($"查询特权 {name} 失败（Win32 错误 {Marshal.GetLastWin32Error()}）。");
                        continue;
                    }

                    if (NativeMethods.AdjustTokenPrivileges(hToken, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero))
                        result.Log.Add($"已启用特权 {name}。");
                    else
                        result.Log.Add($"启用特权 {name} 失败（Win32 错误 {Marshal.GetLastWin32Error()}）。");
                }
            }
            finally
            {
                NativeMethods.CloseHandle(hToken);
            }
        }

        /// <summary>
        /// 执行一条内存列表命令，并把 NTSTATUS 翻译成人话写进日志。
        /// </summary>
        private static void TryNtMemoryCommand(string label, int command, OptimizeResult result)
        {
            try
            {
                int cmd = command;
                int status = NativeMethods.NtSetSystemInformation(
                    NativeMethods.SystemMemoryListInformation, ref cmd, Marshal.SizeOf<int>());

                if (status >= 0)
                {
                    result.Log.Add("已" + label + "。");
                    return;
                }

                uint nt = (uint)(status & 0xFFFFFFFF);
                string hint = nt == NativeMethods.StatusPrivilegeNotHeld
                    ? " —— 原因：未持有所需特权（SeProfileSingleProcessPrivilege）"
                    : nt == 0xC0000005u
                        ? " —— 原因：访问被拒绝（可能被组策略或安全软件拦截）"
                        : "";
                result.Log.Add($"{label}返回 NTSTATUS 0x{nt:X8}{hint}。");
            }
            catch (Exception ex)
            {
                result.Log.Add(label + "异常: " + ex.Message);
            }
        }

        /// <summary>
        /// 兜底回收：申请并提交等量物理页（逐页触碰确保真正落到物理内存），
        /// 迫使内存管理器交出待机页/缓存，随后一次性全部释放。
        /// 代价：过程中会把其他进程的工作集挤到分页文件，所以只在常规清理失败时使用，且留安全余量。
        /// </summary>
        private static void ForceEvictStandby(OptimizeResult result, long targetBytes)
        {
            const int blockSize = 8 * 1024 * 1024;
            var blocks = new List<IntPtr>();
            long committed = 0;

            try
            {
                while (committed < targetBytes)
                {
                    if (TryGetAvailPhys(out ulong avail) && avail < 192UL * 1024 * 1024)
                    {
                        result.Log.Add("已接近系统可用内存下限（192 MB），提前停止申请并开始释放。");
                        break;
                    }

                    IntPtr p = NativeMethods.VirtualAlloc(IntPtr.Zero, (IntPtr)blockSize,
                        NativeMethods.MEM_RESERVE | NativeMethods.MEM_COMMIT, NativeMethods.PAGE_READWRITE);
                    if (p == IntPtr.Zero)
                        break;

                    // 逐页写一个字节，确保页面真正落到物理内存，而不是只保留在有备用的提交额度里
                    for (int off = 0; off < blockSize; off += 4096)
                        Marshal.WriteByte(IntPtr.Add(p, off), 1);

                    blocks.Add(p);
                    committed += blockSize;

                    if (blocks.Count >= 2048)
                        break;
                }

                result.Log.Add($"已临时占用 {(committed >> 20)} MB 物理内存，正在释放…");
            }
            catch (Exception ex)
            {
                result.Log.Add("兜底回收异常: " + ex.Message);
            }
            finally
            {
                foreach (var p in blocks)
                {
                    try { NativeMethods.VirtualFree(p, IntPtr.Zero, NativeMethods.MEM_RELEASE); } catch { }
                }
                result.Log.Add($"已释放全部临时占用的 {(committed >> 20)} MB 内存。");
            }
        }

        private static bool TryGetAvailPhys(out ulong avail)
        {
            var ms = new NativeMethods.MEMORYSTATUSEX();
            ms.dwLength = (uint)Marshal.SizeOf<NativeMethods.MEMORYSTATUSEX>();
            bool ok = NativeMethods.GlobalMemoryStatusEx(ref ms);
            avail = ok ? ms.ullAvailPhys : 0UL;
            return ok && avail > 0;
        }

        /// <summary>读取当前待机列表总量（字节），失败返回 0。</summary>
        public static long GetStandbyBytes()
        {
            var tmp = new EstimateResult();
            ReadStandbyList(tmp);
            return tmp.StandbyBytes;
        }

        private static long BytesToMb(long bytes) => bytes >> 20;
    }
}
