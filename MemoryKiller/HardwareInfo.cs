using System;
using System.Collections.Generic;
using System.Globalization;
using System.Management;

namespace MemoryKiller
{
    /// <summary>
    /// 通过 WMI 读取本机硬件配置：CPU / GPU / 物理内存。
    /// 所有查询均带 try/catch，任一失败不会让程序崩溃，只会回退到“未知”。
    /// </summary>
    internal static class HardwareInfo
    {
        public sealed class CpuInfo
        {
            public string Name = "未知";
            public int Cores;
            public int Logical;
            public double MaxClockMHz;
        }

        public sealed class GpuInfo
        {
            public string Name = "未知";
            public long AdapterRAMBytes;
            public string DriverVersion = "";
        }

        public sealed class RamInfo
        {
            public long TotalBytes;
            public uint SpeedMHz;
            public string Manufacturer = "";
        }

        public static CpuInfo GetCpu()
        {
            var info = new CpuInfo();
            try
            {
                using var searcher = new ManagementObjectSearcher(
                    "SELECT Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed FROM Win32_Processor");
                foreach (ManagementObject mo in searcher.Get())
                {
                    if (mo["Name"] is string n) info.Name = n.Trim();
                    if (mo["NumberOfCores"] != null) info.Cores = Convert.ToInt32(mo["NumberOfCores"]);
                    if (mo["NumberOfLogicalProcessors"] != null) info.Logical = Convert.ToInt32(mo["NumberOfLogicalProcessors"]);
                    if (mo["MaxClockSpeed"] != null) info.MaxClockMHz = Convert.ToDouble(mo["MaxClockSpeed"], CultureInfo.InvariantCulture);
                    break; // 取第一个物理处理器即可
                }
            }
            catch (Exception ex)
            {
                info.Name = "读取失败：" + ex.GetType().Name;
            }
            return info;
        }

        public static List<GpuInfo> GetGpus()
        {
            var list = new List<GpuInfo>();
            try
            {
                // Availability = 3 表示运行正常；部分机型该字段为 null，也一并纳入
                using var searcher = new ManagementObjectSearcher(
                    "SELECT Name, AdapterRAM, DriverVersion FROM Win32_VideoController");
                foreach (ManagementObject mo in searcher.Get())
                {
                    var g = new GpuInfo();
                    if (mo["Name"] is string n) g.Name = n.Trim();
                    if (mo["AdapterRAM"] != null)
                    {
                        try { g.AdapterRAMBytes = Convert.ToInt64(mo["AdapterRAM"]); } catch { }
                    }
                    if (mo["DriverVersion"] is string d) g.DriverVersion = d;
                    list.Add(g);
                }
            }
            catch (Exception ex)
            {
                list.Add(new GpuInfo { Name = "读取失败：" + ex.GetType().Name });
            }
            if (list.Count == 0) list.Add(new GpuInfo());
            return list;
        }

        public static RamInfo GetRam()
        {
            var info = new RamInfo();
            try
            {
                using var searcher = new ManagementObjectSearcher(
                    "SELECT Capacity, Speed, Manufacturer FROM Win32_PhysicalMemory");
                long total = 0;
                foreach (ManagementObject mo in searcher.Get())
                {
                    if (mo["Capacity"] != null)
                    {
                        try { total += Convert.ToInt64(mo["Capacity"]); } catch { }
                    }
                    if (info.SpeedMHz == 0 && mo["Speed"] != null)
                    {
                        try { info.SpeedMHz = Convert.ToUInt32(mo["Speed"]); } catch { }
                    }
                    if (string.IsNullOrEmpty(info.Manufacturer) && mo["Manufacturer"] is string m)
                        info.Manufacturer = m.Trim();
                }
                info.TotalBytes = total;
            }
            catch (Exception ex)
            {
                info.Manufacturer = "读取失败：" + ex.GetType().Name;
            }
            return info;
        }
    }
}
