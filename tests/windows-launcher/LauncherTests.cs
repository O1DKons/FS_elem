using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;

internal static class LauncherTests
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--child")
        {
            Console.WriteLine("reader failure fixture");
            Thread.Sleep(30000);
            return 0;
        }
        int cases = 0;
        Action<bool, string> check = (value, message) => {
            if (!value) throw new Exception(message);
            cases++;
        };
        check(WindowsChild.Quote("") == "\"\"", "empty argument");
        check(WindowsChild.Quote("a & b") == "\"a & b\"", "shell metacharacters stay one argument");
        check(WindowsChild.Quote("a\"b") == "\"a\\\"b\"", "embedded quote");
        check(WindowsChild.Quote("C:\\data\\") == "\"C:\\data\\\\\"", "trailing slash before quote");
        check(LauncherForm.ApplicationUrl("http://127.0.0.1:5174/analysis") != null, "own application route");
        foreach (string value in new[] {
            "https://example.com/analysis", "http://localhost:5174/analysis",
            "http://127.0.0.1:5174/analysis?token=private", "file:///C:/private",
            "http://user:password@127.0.0.1:5174/analysis", "http://127.0.0.1:5174/other" })
            check(LauncherForm.ApplicationUrl(value) == null, "reject non-application ready URL");
        using (var outputObserved = new ManualResetEventSlim(false))
        using (var job = new WindowsJob())
        {
            var child = WindowsChild.Start(job, Assembly.GetExecutingAssembly().Location,
                new[] {"--child"}, Environment.CurrentDirectory,
                line => {outputObserved.Set(); throw new IOException("controlled reader failure");});
            using (var retained = Process.GetProcessById((int)child.ProcessId))
            {
                bool outputReached = outputObserved.Wait(10000);
                job.Dispose();
                check(child.WaitStopped(10000).GetAwaiter().GetResult(), "retained native handle stop after reader failure");
                check(outputReached, "reader failure fixture reached output callback");
                check(child.Completion.IsFaulted, "reader failure remains a failure");
                check(retained.WaitForExit(1000), "owned process physically exited");
            }
            child.Dispose();
        }
        string temporary = Path.Combine(Path.GetTempPath(), "FS_elem-prerequisites-" + Guid.NewGuid().ToString("N"));
        File.WriteAllText(temporary, "blocked directory fixture");
        using (var form = new LauncherForm())
        {
            typeof(LauncherForm).GetField("state", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(form, temporary);
            var prepare = typeof(LauncherForm).GetMethod("Prepare", BindingFlags.Instance | BindingFlags.NonPublic);
            bool failed = false;
            try {prepare.Invoke(form, null);} catch (TargetInvocationException) {failed = true;}
            check(failed, "initial prerequisites fail before Job creation");
            File.Delete(temporary);
            prepare.Invoke(form, null);
            var job = (WindowsJob)typeof(LauncherForm).GetField("job", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form);
            check(job != null && job.Handle != IntPtr.Zero, "prerequisites can be retried after initial failure");
            job.Dispose();
            ((StreamWriter)typeof(LauncherForm).GetField("log", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form)).Dispose();
        }
        Directory.Delete(temporary, true);
        Console.WriteLine("{\"launcherCases\":" + cases + ",\"NN\":0}");
        return 0;
    }
}
