using System;
using System.Runtime.InteropServices;
using System.Text;

namespace MemoryKiller
{
    /// <summary>
    /// Win32 / Native API 的 P/Invoke 封装。
    /// 全部走系统自带 DLL（kernel32 / psapi / ntdll / user32），无额外依赖，
    /// 在 x64 / x86 / ARM64 的 Windows 上均可调用。
    /// </summary>
    internal static class NativeMethods
    {
        // ---- 进程访问权限 ----
        public const uint PROCESS_QUERY_INFORMATION = 0x0400;
        public const uint PROCESS_VM_READ = 0x0010;
        public const uint PROCESS_SET_QUOTA = 0x0100;   // EmptyWorkingSet 必需
        public const uint PROCESS_VM_OPERATION = 0x0008; // EmptyWorkingSet 必需

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, int dwProcessId);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll")]
        public static extern int GetCurrentProcessId();

        // 清空指定进程的工作集（把物理页换入分页文件，释放物理内存）
        [DllImport("psapi.dll", SetLastError = true)]
        public static extern bool EmptyWorkingSet(IntPtr hProcess);

        // 读取进程工作集的最小/最大值。EmptyWorkingSet 会把工作集压缩到不低于 MinimumWorkingSetSize，
        // 因此「当前工作集 - 最小工作集」就是可回收量的理论上限，用于刷新按钮的估算。
        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool GetProcessWorkingSetSizeEx(
            IntPtr hProcess, out IntPtr lpMinimumWorkingSetSize, out IntPtr lpMaximumWorkingSetSize, out int Flags);

        // 枚举本机全部进程 PID
        [DllImport("psapi.dll", SetLastError = true)]
        public static extern bool EnumProcesses(int[] lpidProcess, int cb, out int cbNeeded);

        [DllImport("psapi.dll", SetLastError = true)]
        public static extern bool GetProcessMemoryInfo(
            IntPtr hProcess, out PROCESS_MEMORY_COUNTERS_EX counters, int size);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool QueryFullProcessImageName(
            IntPtr hProcess, int dwFlags, StringBuilder lpExeName, ref int lpdwSize);

        // 取前台窗口所在进程（用于跳过当前活动程序，避免卡顿）
        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

        // ---- 系统级内存清理（Native API） ----
        // NtSetSystemInformation(SystemMemoryListInformation, &cmd, sizeof(int))
        [DllImport("ntdll.dll")]
        public static extern int NtSetSystemInformation(
            int SystemInformationClass, ref int SystemInformation, int SystemInformationLength);

        public const int SystemMemoryListInformation = 80;
        public const int MemoryEmptyWorkingSets = 1;          // 清空所有进程工作集
        public const int MemoryFlushModifiedList = 2;         // 刷新已修改页列表
        public const int MemoryPurgeStandbyList = 4;          // 清理待机列表（SuperFetch 缓存）
        public const int MemoryPurgeLowPriorityStandbyList = 5;

        // 状态：NtSetSystemInformation 失败时返回 NTSTATUS 负值，据此判断原因
        public const uint StatusPrivilegeNotHeld = 0xC0000061;

        // ---- 令牌权限调整 ----
        // 清理待机列表需要 SeProfileSingleProcessPrivilege；该特权即使管理员身份也默认处于
        // “禁用”状态，必须显式 AdjustTokenPrivileges 启用，否则 NtSetSystemInformation 返回 0xC0000061。
        public const uint TOKEN_QUERY = 0x0008;
        public const uint TOKEN_ADJUST_PRIVILEGES = 0x0020;
        public const uint SE_PRIVILEGE_ENABLED = 0x00000002;

        [DllImport("kernel32.dll")]
        public static extern IntPtr GetCurrentProcess();

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern bool OpenProcessToken(IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);

        [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
        public static extern bool LookupPrivilegeValue(string? lpSystemName, string lpName, out LUID lpLuid);

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern bool AdjustTokenPrivileges(IntPtr TokenHandle, bool DisableAllPrivileges,
            ref TOKEN_PRIVILEGES NewState, int BufferLength, IntPtr PreviousState, IntPtr ReturnLength);

        [StructLayout(LayoutKind.Sequential)]
        public struct LUID { public uint LowPart; public int HighPart; }

        [StructLayout(LayoutKind.Sequential)]
        public struct LUID_AND_ATTRIBUTES { public LUID Luid; public uint Attributes; }

        [StructLayout(LayoutKind.Sequential)]
        public struct TOKEN_PRIVILEGES { public int PrivilegeCount; public LUID_AND_ATTRIBUTES Privileges; }

        // ---- 虚拟内存申请/释放：兜底方案，用物理页把待机页挤出去 ----
        public const uint MEM_COMMIT = 0x1000;
        public const uint MEM_RESERVE = 0x2000;
        public const uint MEM_RELEASE = 0x8000;
        public const uint PAGE_READWRITE = 0x04;

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern IntPtr VirtualAlloc(IntPtr lpAddress, IntPtr dwSize, uint flAllocationType, uint flProtect);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool VirtualFree(IntPtr lpAddress, IntPtr dwSize, uint dwFreeType);

        // ---- 物理内存状态 ----
        [StructLayout(LayoutKind.Sequential)]
        public struct MEMORYSTATUSEX
        {
            public uint dwLength;
            public uint dwMemoryLoad;        // 已用百分比
            public ulong ullTotalPhys;
            public ulong ullAvailPhys;
            public ulong ullTotalPageFile;
            public ulong ullAvailPageFile;
            public ulong ullTotalVirtual;
            public ulong ullAvailVirtual;
            public ulong ullAvailExtendedVirtual;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX lpBuffer);

        // ---- 结构：进程内存计数器（扩展版） ----
        [StructLayout(LayoutKind.Sequential)]
        public struct PROCESS_MEMORY_COUNTERS_EX
        {
            public int cb;
            public int PageFaultCount;
            public IntPtr PeakWorkingSetSize;
            public IntPtr WorkingSetSize;
            public IntPtr QuotaPeakPagedPoolUsage;
            public IntPtr QuotaPagedPoolUsage;
            public IntPtr QuotaPeakNonPagedPoolUsage;
            public IntPtr QuotaNonPagedPoolUsage;
            public IntPtr PagefileUsage;
            public IntPtr PeakPagefileUsage;
            public IntPtr PrivateUsage;
        }
    }
}
