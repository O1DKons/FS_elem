using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Reflection;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32.SafeHandles;

[assembly: AssemblyTitle("FS_elem")]
[assembly: AssemblyVersion("0.2.3.0")]
[assembly: AssemblyFileVersion("0.2.3.0")]

internal static class Program
{
    [STAThread]
    private static int Main()
    {
        bool created;
        string user = WindowsIdentity.GetCurrent().User.Value;
        using (var mutex = new Mutex(true, @"Local\FS_elem_" + user, out created))
        {
            if (!created)
            {
                MessageBox.Show("FS_elem уже запущен. Используйте открытое окно FS_elem.",
                                "FS_elem", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 0;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new LauncherForm());
            return 0;
        }
    }
}

internal sealed class LauncherForm : Form
{
    private readonly string app = Application.StartupPath;
    private readonly string state;
    private readonly Label title = new Label();
    private readonly Label status = new Label();
    private readonly ProgressBar progress = new ProgressBar();
    private readonly Button action = new Button();
    private readonly Button close = new Button();
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly object logLock = new object();
    private StreamWriter log;
    private long loggedBytes;
    private bool logTruncated;
    private WindowsJob job;
    private WindowsChild child;
    private bool closing;
    private bool mayClose;
    private bool busy;
    private string url;
    private string error;
    private TaskCompletionSource<bool> nodeReady;
    private Task<bool> ownedStop;

    public LauncherForm()
    {
        Text = "FS_elem";
        ClientSize = new Size(510, 230);
        Font = new Font("Segoe UI", 10);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        title.SetBounds(24, 20, 462, 35);
        title.Font = new Font("Segoe UI", 17, FontStyle.Bold);
        title.Text = "FS_elem";
        status.SetBounds(24, 67, 462, 67);
        status.Text = "Подготовка приложения…";
        progress.SetBounds(24, 140, 462, 20);
        progress.Style = ProgressBarStyle.Marquee;
        action.SetBounds(24, 182, 260, 32);
        action.Text = "Подготовка…";
        action.Enabled = false;
        close.SetBounds(326, 182, 160, 32);
        close.Text = "Завершить";
        Controls.AddRange(new Control[] {title, status, progress, action, close});
        state = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FS_elem");
        action.Click += async (sender, args) => {
            if (url != null) OpenApplication();
            else await StartApplication();
        };
        close.Click += (sender, args) => Close();
        Shown += async (sender, args) => await StartApplication();
        FormClosing += async (sender, args) => {
            if (mayClose) return;
            args.Cancel = true;
            if (closing) return;
            closing = true;
            action.Enabled = false;
            close.Enabled = false;
            status.Text = "Завершаем приложение…";
            var active = child;
            if (active != null && (ownedStop == null || ownedStop.IsCompleted))
            {
                active.SendShutdown();
                await Task.WhenAny(active.Completion, Task.Delay(5000));
            }
            if (!await StopOwned())
            {
                closing = false;
                ShowUnresolvedStop();
                return;
            }
            lock (logLock) {if (log != null) {log.Dispose(); log = null;}}
            mayClose = true;
            Close();
        };
    }

    private void Prepare()
    {
        Directory.CreateDirectory(state);
        Directory.CreateDirectory(Path.Combine(state, "logs"));
        if (log == null)
        {
            log = new StreamWriter(Path.Combine(state, "logs", "launcher.log"), false, new UTF8Encoding(false));
            log.AutoFlush = true;
        }
        foreach (string name in new[] {"PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "NODE_OPTIONS"})
            Environment.SetEnvironmentVariable(name, null);
        Environment.SetEnvironmentVariable("PYTHONIOENCODING", "utf-8");
        Environment.SetEnvironmentVariable("PYTHONUTF8", "1");
        Environment.SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "1");
        Environment.SetEnvironmentVariable("PATH", Path.Combine(app, ".runtime", "node") + ";" +
            Environment.GetFolderPath(Environment.SpecialFolder.System) + ";" +
            Environment.GetEnvironmentVariable("SystemRoot"));
        if (job == null || job.Handle == IntPtr.Zero) job = new WindowsJob();
    }

    private Task<bool> StopOwned()
    {
        if (ownedStop != null && !ownedStop.IsCompleted) return ownedStop;
        ownedStop = StopOwnedCore();
        return ownedStop;
    }

    private async Task<bool> StopOwnedCore()
    {
        // Completion may be faulted while the process is still running.
        // Always close our Job, then independently verify retained kernel handles.
        if (job != null) job.Dispose();
        var active = child;
        bool stopped = active == null || await active.WaitStopped(10000);
        bool failedStartStopped = job == null || await job.WaitFailedStart(10000);
        if (!stopped || !failedStartStopped) return false;
        if (active != null) {active.Dispose(); if (child == active) child = null;}
        return true;
    }

    private void ShowUnresolvedStop()
    {
        url = null;
        status.Text = "Не удалось подтвердить остановку приложения. Повторите завершение окна.";
        progress.Style = ProgressBarStyle.Blocks;
        action.Enabled = false;
        close.Enabled = true;
        Log("Owned process stop unresolved; retry disabled.");
    }

    internal static string ApplicationUrl(string value)
    {
        Uri parsed;
        if (!Uri.TryCreate(value, UriKind.Absolute, out parsed) ||
            parsed.Scheme != "http" || parsed.Host != "127.0.0.1" ||
            parsed.Port < 1024 || parsed.Port > 65535 ||
            parsed.AbsolutePath != "/analysis" || parsed.Query.Length != 0 ||
            parsed.Fragment.Length != 0 || parsed.UserInfo.Length != 0)
            return null;
        return parsed.AbsoluteUri;
    }

    private void Log(string line)
    {
        lock (logLock)
        {
            if (log == null) return;
            int bytes = Encoding.UTF8.GetByteCount(line) + 1;
            if (loggedBytes + bytes > 262144)
            {
                if (!logTruncated) log.WriteLine("Log limit reached; output is still drained.");
                logTruncated = true;
                return;
            }
            log.WriteLine(line);
            loggedBytes += bytes;
        }
    }

    private void Output(string line)
    {
        Log(line);
        Dictionary<string, object> message;
        try {message = json.Deserialize<Dictionary<string, object>>(line.TrimStart('\uFEFF'));}
        catch (Exception) {return;}
        if (message == null || !message.ContainsKey("type")) return;
        string type = Convert.ToString(message["type"]);
        string text = message.ContainsKey("message") ? Convert.ToString(message["message"]) : null;
        if (closing || IsDisposed) return;
        try
        {
            BeginInvoke((Action)(() => {
                if (closing || IsDisposed) return;
                if (type == "error")
                {
                    error = text ?? "Не удалось запустить FS_elem.";
                    if (nodeReady != null) nodeReady.TrySetException(new IOException(error));
                    return;
                }
                if (type == "progress")
                {
                    status.Text = text ?? "Подготовка FS_elem…";
                    if (message.ContainsKey("bytes") && message.ContainsKey("total"))
                    {
                        double bytes = Convert.ToDouble(message["bytes"]);
                        double total = Convert.ToDouble(message["total"]);
                        if (total > 0)
                        {
                            progress.Style = ProgressBarStyle.Blocks;
                            progress.Value = Math.Max(0, Math.Min(100, (int)(100 * bytes / total)));
                            status.Text += String.Format("\n{0:0.0} / {1:0.0} МБ", bytes / 1048576, total / 1048576);
                        }
                    }
                }
                else if (type == "ready" && message.ContainsKey("url"))
                {
                    url = ApplicationUrl(Convert.ToString(message["url"]));
                    if (url == null) {error = "Приложение сообщило неверный адрес."; return;}
                    progress.Style = ProgressBarStyle.Blocks;
                    progress.Value = 100;
                    status.Text = "Приложение работает. Для остановки закройте это окно.\nВкладку браузера можно открыть снова.";
                    action.Text = "Открыть FS_elem";
                    action.Enabled = true;
                    if (nodeReady != null) nodeReady.TrySetResult(true);
                    OpenApplication();
                }
            }));
        }
        catch (InvalidOperationException) {}
    }

    private string Required(string relative)
    {
        string path = Path.Combine(app, relative.Replace('/', Path.DirectorySeparatorChar));
        if (!File.Exists(path)) throw new IOException("Компоненты приложения отсутствуют. Повторно установите FS_elem.");
        return path;
    }

    private async Task StartApplication()
    {
        if (busy || closing) return;
        busy = true;
        action.Enabled = false;
        error = null;
        url = null;
        progress.Style = ProgressBarStyle.Marquee;
        status.Text = "Проверяем компоненты FS_elem…";
        Exception failure = null;
        try
        {
        try
        {
            if (child != null) throw new IOException("Предыдущий процесс ещё не завершён.");
            Prepare();
            string config = Path.Combine(state, "release-web.json");
            if (!File.Exists(config))
            {
                var settings = new Dictionary<string, object> {
                    {"host", "127.0.0.1"}, {"port", 5174}, {"analysisPort", 5175},
                    {"python", ".runtime/venv-science/Scripts/python.exe"},
                    {"dataDir", Path.Combine(state, "data")}
                };
                using (var stream = new FileStream(config, FileMode.CreateNew, FileAccess.Write))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false)))
                    writer.Write(json.Serialize(settings));
            }
            child = WindowsChild.Start(job, Required(".runtime/venv-science/Scripts/python.exe"),
                new[] {Required("scripts/windows-first-run.py"), "--root", app}, app, Output);
            Log("{\"type\":\"child-start\",\"role\":\"bootstrap\",\"pid\":" + child.ProcessId + "}");
            int code = await child.Completion;
            Log("{\"type\":\"child-exit\",\"role\":\"bootstrap\",\"pid\":" + child.ProcessId + ",\"exitCode\":" + code + ",\"nativeWaitSignaled\":true,\"readerJoined\":true}");
            child.Dispose();
            child = null;
            if (closing) return;
            if (code != 0) throw new IOException(error ?? "Не удалось подготовить приложение. Проверьте интернет и нажмите «Повторить».");
            status.Text = "Запускаем интерфейс…";
            nodeReady = new TaskCompletionSource<bool>();
            child = WindowsChild.Start(job, Required(".runtime/node/node.exe"),
                new[] {Required("scripts/start-release.mjs"), "--desktop", "--config", config}, app, Output);
            Log("{\"type\":\"child-start\",\"role\":\"desktop\",\"pid\":" + child.ProcessId + "}");
            var startup = await Task.WhenAny(child.Completion, nodeReady.Task, Task.Delay(60000));
            if (startup != nodeReady.Task)
            {
                throw new IOException(error ?? "Не удалось запустить интерфейс. Журнал: " + Path.Combine(state, "logs", "launcher.log"));
            }
            await nodeReady.Task;
            busy = false;
            int exit = await child.Completion;
            Log("{\"type\":\"child-exit\",\"role\":\"desktop\",\"pid\":" + child.ProcessId + ",\"exitCode\":" + exit + ",\"nativeWaitSignaled\":true,\"readerJoined\":true}");
            child.Dispose();
            child = null;
            if (!closing) ShowError(error ?? "FS_elem остановился (код " + exit + "). Нажмите «Повторить».");
        }
        catch (Exception ex) {failure = ex;}
        // The stock Framework compiler is C#5: await must be outside catch.
        if (failure != null)
        {
            if (closing) return; // FormClosing owns the same retained handles.
            if (await StopOwned()) ShowError(failure.Message);
            else ShowUnresolvedStop();
        }
        }
        finally {busy = false; nodeReady = null;}
    }

    private void ShowError(string message)
    {
        if (closing) return;
        Log(message);
        url = null;
        status.Text = message;
        progress.Style = ProgressBarStyle.Blocks;
        progress.Value = 0;
        action.Text = "Повторить";
        action.Enabled = true;
    }

    private void OpenApplication()
    {
        if (url == null) return;
        try {Process.Start(new ProcessStartInfo(url) {UseShellExecute = true});}
        catch (Exception ex) {status.Text = "Откройте адрес в браузере: " + url + "\n" + ex.Message;}
    }
}

internal sealed class WindowsJob : IDisposable
{
    internal IntPtr Handle;
    private IntPtr failedStart;
    internal void RetainFailedStart(IntPtr handle) {failedStart = handle;}
    internal async Task<bool> WaitFailedStart(uint timeout)
    {
        IntPtr handle = failedStart;
        if (handle == IntPtr.Zero) return true;
        uint result = await Task.Run(() => Native.WaitForSingleObject(handle, timeout));
        if (result != 0) return false;
        Native.CloseHandle(handle);
        failedStart = IntPtr.Zero;
        return true;
    }
    public WindowsJob()
    {
        Handle = Native.CreateJobObject(IntPtr.Zero, null);
        if (Handle == IntPtr.Zero) throw Native.Error("CreateJobObject");
        var limits = new Native.JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        limits.BasicLimitInformation.LimitFlags = 0x2000; // KILL_ON_JOB_CLOSE
        int size = Marshal.SizeOf(limits);
        IntPtr memory = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(limits, memory, false);
            if (!Native.SetInformationJobObject(Handle, 9, memory, (uint)size))
                throw Native.Error("SetInformationJobObject");
        }
        catch {Dispose(); throw;}
        finally {Marshal.FreeHGlobal(memory);}
    }
    public void Dispose()
    {
        if (Handle != IntPtr.Zero) {Native.CloseHandle(Handle); Handle = IntPtr.Zero;}
    }
}

internal sealed class WindowsChild : IDisposable
{
    private IntPtr process;
    private StreamWriter input;
    private readonly Task reader;
    private bool stopped;
    internal readonly Task<int> Completion;
    internal uint ProcessId;

    private WindowsChild(IntPtr handle, uint pid, StreamWriter writer, Task read)
    {
        process = handle;
        ProcessId = pid;
        input = writer;
        reader = read;
        Completion = Task.Run(async () => {
            uint waited = Native.WaitForSingleObject(handle, 0xFFFFFFFF);
            if (waited != 0) throw Native.Error("WaitForSingleObject");
            uint code;
            if (!Native.GetExitCodeProcess(handle, out code)) throw Native.Error("GetExitCodeProcess");
            await read;
            return unchecked((int)code);
        });
    }

    internal async Task<bool> WaitStopped(uint timeout)
    {
        if (stopped) return true;
        IntPtr handle = process;
        if (handle == IntPtr.Zero) return false;
        var elapsed = Stopwatch.StartNew();
        uint result = await Task.Run(() => Native.WaitForSingleObject(handle, timeout));
        if (result != 0) return false;
        // A failed reader is closed, but is never reported as successful output.
        int remaining = Math.Max(0, (int)timeout - (int)elapsed.ElapsedMilliseconds);
        if (await Task.WhenAny(reader, Task.Delay(remaining)) != reader) return false;
        remaining = Math.Max(0, (int)timeout - (int)elapsed.ElapsedMilliseconds);
        if (await Task.WhenAny(Completion, Task.Delay(remaining)) != Completion) return false;
        if (reader.IsFaulted) {var observed = reader.Exception;}
        if (Completion.IsFaulted) {var observed = Completion.Exception;}
        stopped = true;
        return true;
    }

    internal static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') {slashes++; continue;}
            if (c == '"') {result.Append('\\', slashes * 2 + 1); result.Append(c);}
            else {result.Append('\\', slashes); result.Append(c);}
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    internal static WindowsChild Start(WindowsJob job, string executable, string[] args,
                                      string directory, Action<string> output)
    {
        if (job.Handle == IntPtr.Zero) throw new IOException("Владение процессами приложения закрыто.");
        IntPtr outRead = IntPtr.Zero, outWrite = IntPtr.Zero, inRead = IntPtr.Zero, inWrite = IntPtr.Zero;
        var security = new Native.SECURITY_ATTRIBUTES {nLength = Marshal.SizeOf(typeof(Native.SECURITY_ATTRIBUTES)), bInheritHandle = true};
        var info = new Native.PROCESS_INFORMATION();
        try
        {
            if (!Native.CreatePipe(out outRead, out outWrite, ref security, 0) ||
                !Native.CreatePipe(out inRead, out inWrite, ref security, 0) ||
                !Native.SetHandleInformation(outRead, 1, 0) ||
                !Native.SetHandleInformation(inWrite, 1, 0))
                throw Native.Error("CreatePipe");
            var startup = new Native.STARTUPINFO {
                cb = Marshal.SizeOf(typeof(Native.STARTUPINFO)), dwFlags = 0x100,
                hStdInput = inRead, hStdOutput = outWrite, hStdError = outWrite
            };
            var command = new StringBuilder(Quote(executable));
            foreach (string arg in args) command.Append(" ").Append(Quote(arg));
            if (!Native.CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                    0x08000004, IntPtr.Zero, directory, ref startup, out info))
                throw Native.Error("CreateProcess");
            // Assign before the process executes, so descendants cannot escape ownership.
            if (!Native.AssignProcessToJobObject(job.Handle, info.hProcess))
                throw Native.Error("AssignProcessToJobObject");
            if (Native.ResumeThread(info.hThread) == 0xFFFFFFFF) throw Native.Error("ResumeThread");
            Native.CloseHandle(info.hThread); info.hThread = IntPtr.Zero;
            Native.CloseHandle(outWrite); outWrite = IntPtr.Zero;
            Native.CloseHandle(inRead); inRead = IntPtr.Zero;
            var readHandle = new SafeFileHandle(outRead, true); outRead = IntPtr.Zero;
            var writeHandle = new SafeFileHandle(inWrite, true); inWrite = IntPtr.Zero;
            var writer = new StreamWriter(new FileStream(writeHandle, FileAccess.Write), new UTF8Encoding(false));
            writer.AutoFlush = true;
            Task read = Task.Run(() => {
                using (var stream = new FileStream(readHandle, FileAccess.Read))
                using (var reader = new StreamReader(stream, Encoding.UTF8, true))
                {
                    var line = new StringBuilder();
                    bool overflow = false;
                    while (true)
                    {
                        int c = reader.Read();
                        if (c < 0) break;
                        if (c == '\n')
                        {
                            if (!overflow) output(line.ToString().TrimEnd('\r'));
                            else output("Output line exceeded 64KiB; discarded.");
                            line.Clear(); overflow = false;
                        }
                        else if (line.Length < 65536) line.Append((char)c);
                        else overflow = true;
                    }
                    if (line.Length > 0 && !overflow) output(line.ToString().TrimEnd('\r'));
                }
            });
            var child = new WindowsChild(info.hProcess, info.dwProcessId, writer, read);
            info.hProcess = IntPtr.Zero;
            return child;
        }
        finally
        {
            if (info.hProcess != IntPtr.Zero)
            {
                bool terminated = Native.TerminateProcess(info.hProcess, 1);
                uint waited = Native.WaitForSingleObject(info.hProcess, 10000);
                if (waited == 0) Native.CloseHandle(info.hProcess);
                else
                {
                    job.RetainFailedStart(info.hProcess);
                    job.Dispose();
                    output("Failed-start termination unresolved (TerminateProcess=" + terminated + ", wait=" + waited + ").");
                }
            }
            if (info.hThread != IntPtr.Zero) Native.CloseHandle(info.hThread);
            foreach (IntPtr handle in new[] {outRead, outWrite, inRead, inWrite})
                if (handle != IntPtr.Zero) Native.CloseHandle(handle);
        }
    }

    internal void SendShutdown()
    {
        try {if (input != null) input.WriteLine("{\"type\":\"shutdown\"}");}
        catch (IOException) {}
        catch (ObjectDisposedException) {}
    }

    public void Dispose()
    {
        if (!stopped && Completion.Status != TaskStatus.RanToCompletion)
            throw new IOException("Cannot release an unverified process handle.");
        if (input != null) {input.Dispose(); input = null;}
        if (process != IntPtr.Zero) {Native.CloseHandle(process); process = IntPtr.Zero;}
    }
}

internal static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct SECURITY_ATTRIBUTES {internal int nLength; internal IntPtr lpSecurityDescriptor; [MarshalAs(UnmanagedType.Bool)] internal bool bInheritHandle;}
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    internal struct STARTUPINFO {
        internal int cb; internal string lpReserved, lpDesktop, lpTitle;
        internal uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        internal ushort wShowWindow, cbReserved2; internal IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct PROCESS_INFORMATION {internal IntPtr hProcess, hThread; internal uint dwProcessId, dwThreadId;}
    [StructLayout(LayoutKind.Sequential)]
    internal struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        internal long PerProcessUserTimeLimit, PerJobUserTimeLimit; internal uint LimitFlags;
        internal UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize; internal uint ActiveProcessLimit;
        internal UIntPtr Affinity; internal uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    internal struct IO_COUNTERS {internal ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount;}
    [StructLayout(LayoutKind.Sequential)]
    internal struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        internal JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation; internal IO_COUNTERS IoInfo;
        internal UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern bool SetInformationJobObject(IntPtr job, int informationClass, IntPtr information, uint size);
    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref SECURITY_ATTRIBUTES security, uint size);
    [DllImport("kernel32.dll", SetLastError = true)]
    internal static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern bool CreateProcess(string application, StringBuilder command, IntPtr processAttributes,
        IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory,
        ref STARTUPINFO startup, out PROCESS_INFORMATION information);
    [DllImport("kernel32.dll", SetLastError = true)] internal static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] internal static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] internal static extern bool GetExitCodeProcess(IntPtr handle, out uint code);
    [DllImport("kernel32.dll", SetLastError = true)] internal static extern bool TerminateProcess(IntPtr handle, uint code);
    [DllImport("kernel32.dll", SetLastError = true)] internal static extern bool CloseHandle(IntPtr handle);
    internal static Exception Error(string operation) {return new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), operation);}
}
