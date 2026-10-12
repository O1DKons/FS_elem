using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
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
        if (args.Length > 0 && args[0] == "--watchdog") return SuperviseFixture();
        int cases = 0;
        Action<bool, string> check = (value, message) => {
            Console.WriteLine("assert " + (cases + 1) + ": " + message);
            Console.Out.Flush();
            if (!value) throw new Exception(message);
            cases++;
        };
        var diagnostic = new LauncherDiagnostics();
        diagnostic.RecordFailure("First startup cause");
        diagnostic.RecordFailure("Later cleanup failure");
        check(diagnostic.FirstFailure == "First startup cause", "first startup cause survives cleanup failure");
        for (int i = 0; i < 100; i++) diagnostic.RecordOutput("tail-" + i + new string('x', 1024));
        check(diagnostic.Tail.Length <= 8192 && diagnostic.Tail.Contains("tail-99") && !diagnostic.Tail.Contains("tail-0"), "bounded tail retains newest actual output");
        check(LauncherDiagnostics.StartupFailure(true, 7).Contains("7"), "desktop exit code remains visible");
        check(LauncherDiagnostics.StartupFailure(false, null).Contains("60"), "readiness deadline distinguished from exit");
        using (var failedForm = new LauncherForm())
        {
            var output = typeof(LauncherForm).GetMethod("Output", BindingFlags.Instance | BindingFlags.NonPublic);
            output.Invoke(failedForm, new object[] {"{\"type\":\"error\",\"message\":\"Fast child first cause\"}"});
            output.Invoke(failedForm, new object[] {"{\"type\":\"error\",\"message\":\"Later child cause\"}"});
            var captured = (LauncherDiagnostics)typeof(LauncherForm).GetField("diagnostics", BindingFlags.Instance | BindingFlags.NonPublic).GetValue(failedForm);
            check(captured.FirstFailure == "Fast child first cause", "reader captures first cause without a UI-dispatch turn");
        }
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
            Console.WriteLine("stage fault-child-start; context=" + (SynchronizationContext.Current == null ? "null" : SynchronizationContext.Current.GetType().FullName));
            Console.Out.Flush();
            var child = WindowsChild.Start(job, Assembly.GetExecutingAssembly().Location,
                new[] {"--child"}, Environment.CurrentDirectory,
                line => {outputObserved.Set(); throw new IOException("controlled reader failure");});
            using (var retained = Process.GetProcessById((int)child.ProcessId))
            {
                bool outputReached = outputObserved.Wait(10000);
                Console.WriteLine("stage fault-output; observed=" + outputReached + "; completion=" + child.Completion.Status);
                job.Dispose();
                Console.WriteLine("stage retained-stop-before; context=" + (SynchronizationContext.Current == null ? "null" : SynchronizationContext.Current.GetType().FullName));
                Console.Out.Flush();
                bool stopped = child.WaitStopped(10000).GetAwaiter().GetResult();
                Console.WriteLine("stage retained-stop-after; stopped=" + stopped + "; completion=" + child.Completion.Status + "; nativeExited=" + retained.HasExited);
                check(stopped, "retained native handle stop after reader failure");
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

    private static int SuperviseFixture()
    {
        // This branch runs before any Form constructor, with no message-loop
        // dependency. The real fixture deliberately keeps its WinForms context.
        var clock = Stopwatch.StartNew();
        var terminal = new ManualResetEventSlim(false);
        var supervisor = Process.GetCurrentProcess();
        IntPtr retainedSupervisorHandle = supervisor.Handle;
        if (retainedSupervisorHandle == IntPtr.Zero) throw new IOException("Supervisor native handle missing");
        var terminalGuard = new Thread(() => {
            int remaining = Math.Max(0, 90000 - (int)clock.ElapsedMilliseconds);
            // A blocked reader/final Console write cannot outlive this original
            // endpoint. Retained self termination closes our kill-on-close Job.
            if (!terminal.Wait(remaining)) supervisor.Kill();
        });
        terminalGuard.IsBackground = true;
        terminalGuard.Start();
        int captured = 0;
        var job = new WindowsJob();
        WindowsChild child = null;
        Process retained = null;
        bool closed = false;
        int code = 1;
        try
        {
            child = WindowsChild.Start(job, Assembly.GetExecutingAssembly().Location,
                new string[0], Environment.CurrentDirectory, line => {
                    if (Interlocked.Add(ref captured, Encoding.UTF8.GetByteCount(line) + 1) > 245760)
                        throw new IOException("Fixture combined output exceeds240KiB");
                    Console.WriteLine(line);
                });
            retained = Process.GetProcessById((int)child.ProcessId);
            Console.WriteLine("fixture-watchdog child-start pid=" + child.ProcessId + "; work80s/whole90s/cleanup10s");
            int workRemaining = Math.Max(0, 80000 - (int)clock.ElapsedMilliseconds);
            var winner = Task.WhenAny(child.Completion, Task.Delay(workRemaining)).GetAwaiter().GetResult();
            if (workRemaining == 0 || winner != child.Completion || clock.ElapsedMilliseconds > 80000)
                Console.Error.WriteLine("Fixture work deadline reached; terminating only own Job");
            else code = child.Completion.GetAwaiter().GetResult();
            if (clock.ElapsedMilliseconds > 80000) code = 1;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Fixture first failure: " + ex.GetType().FullName + ": " + ex.Message);
            code = 1;
        }
        finally
        {
            job.Dispose(); // Kill-on-close applies to the fixture and its children.
            if (child != null)
            {
                int remaining = Math.Max(0, Math.Min(10000, 90000 - (int)clock.ElapsedMilliseconds));
                closed = child.WaitStopped((uint)remaining).GetAwaiter().GetResult();
                closed = closed && retained != null && retained.WaitForExit(0);
                Console.WriteLine("fixture-watchdog retained-stop=" + closed + "; completion=" + child.Completion.Status);
                if (closed) child.Dispose();
                else code = 1;
            }
            if (retained != null && closed) retained.Dispose();
            if (clock.ElapsedMilliseconds > 90000 || !closed) code = 1;
            Console.WriteLine("fixture-watchdog terminal; elapsedMs=" + clock.ElapsedMilliseconds + "; capturedBytes=" + captured + "; exitCode=" + code);
        }
        terminal.Set();
        bool guardJoined = terminalGuard.Join(Math.Max(0, 90000 - (int)clock.ElapsedMilliseconds));
        if (guardJoined) {terminal.Dispose(); supervisor.Dispose();}
        // Even terminal output cannot turn a late completion into a pass.
        return clock.ElapsedMilliseconds <= 90000 && closed && guardJoined ? code : 1;
    }
}
