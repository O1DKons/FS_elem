param(
 [Parameter(Mandatory=$true)][string]$Installer,
 [Parameter(Mandatory=$true)][string]$WorkRoot,
 [Parameter(Mandatory=$true)][string]$Logs
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$installed=Join-Path $WorkRoot 'Установка & проверка\FS_elem'
$summary=@{status='pending';NN=0;acceptedVideoUploads=0;desktopQualification='Windows Server CI; desktop10/11 manual user flow remains separate'}
$launcher=$null
$logPath=Join-Path $env:LOCALAPPDATA 'FS_elem\logs\launcher.log'
function Run([string]$Label,[string]$Exe,[string[]]$Arguments){
 $text=(&$Exe @Arguments 2>&1|Out-String)
 $exit=$LASTEXITCODE
 if($text.Length -gt 2097152){throw "$Label exceeded2MiB log"}
 [IO.File]::WriteAllText((Join-Path $Logs ($Label+'.log')),$text,[Text.UTF8Encoding]::new($false))
 if($exit -ne 0){throw "$Label failed ($exit): $text"}
 return $text
}
function Snapshot([int]$RootProcess){
 $all=@(Get-CimInstance Win32_Process|Select-Object ProcessId,ParentProcessId,CreationDate,Name)
 $ids=[Collections.Generic.HashSet[int]]::new()
 [void]$ids.Add($RootProcess)
 do{
  $changed=$false
  foreach($p in $all){
   if($ids.Contains([int]$p.ParentProcessId) -and -not $ids.Contains([int]$p.ProcessId)){
    [void]$ids.Add([int]$p.ProcessId);$changed=$true
   }
  }
 }while($changed)
 return @($all|Where-Object{$ids.Contains([int]$_.ProcessId)})
}
function Require-Gone($Old){
 $current=@(Get-CimInstance Win32_Process)
 $remaining=@($current|Where-Object{
  $now=$_
  @($Old|Where-Object{[int]$_.ProcessId -eq [int]$now.ProcessId -and $_.CreationDate -eq $now.CreationDate}).Count -gt 0
 })
 if($remaining.Count -gt 0){throw 'Owned original process generation remains'}
}
function Wait-Ready($Process){
 $deadline=[DateTime]::UtcNow.AddSeconds(90)
 while([DateTime]::UtcNow -lt $deadline){
  if($Process.HasExited){throw 'Installed GUI exited before ready'}
  try{
   $health=Invoke-WebRequest 'http://127.0.0.1:5174/api/analysis/health' -TimeoutSec 2 -UseBasicParsing -NoProxy
   $ui=Invoke-WebRequest 'http://127.0.0.1:5174/analysis' -TimeoutSec 2 -UseBasicParsing -NoProxy
   $body=$health.Content|ConvertFrom-Json
   if($health.StatusCode -eq 200 -and $ui.StatusCode -eq 200 -and $body.status -eq 'ready' -and $body.inferenceAvailable -eq $true -and $body.PSObject.Properties.Name -contains 'activeJobId' -and $null -eq $body.activeJobId){return}
  }catch{}
  Start-Sleep -Milliseconds 500
 }
 throw 'Installed application readiness deadline exceeded'
}
function Controller-Pid($Process){
 $events=@(Get-Content -LiteralPath $logPath -Encoding UTF8|ForEach-Object{
  try{$v=$_|ConvertFrom-Json;if($v.type -eq 'child-start' -and $v.role -eq 'desktop'){$v}}catch{}
 })
 $current=@(Get-CimInstance Win32_Process -Filter ("ParentProcessId="+$Process.Id)|Where-Object{
  $_.Name -eq 'node.exe' -and $_.CreationDate.ToUniversalTime() -ge $Process.StartTime.ToUniversalTime()
 })
 $matching=@($current|Where-Object{
  $pidNow=[int]$_.ProcessId
  @($events|Where-Object{[int]$_.pid -eq $pidNow}).Count -gt 0
 })
 if($matching.Count -ne 1){throw 'Current own desktop controller generation missing or ambiguous'}
 return [int]$matching[0].ProcessId
}
try{
 # Reject foreign localhost services instead of accepting them as this installer.
 foreach($port in 5174,5175){
  $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port)
  try{$listener.Start()}finally{$listener.Stop()}
 }
 $installLog=Join-Path $Logs 'installer.log'
 $setup=Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS=desktopicon',('/DIR="'+$installed+'"'),('/LOG="'+$installLog+'"')) -PassThru -Wait
 $summary.installerExitCode=$setup.ExitCode
 if($setup.ExitCode -ne 0){throw 'Installer failed'}
 $shortcut=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\FS_elem\FS_elem.lnk'
 if(-not(Test-Path -LiteralPath $shortcut)){throw 'Start Menu shortcut missing'}
 $link=(New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
 $summary.shortcutPath=$shortcut
 $summary.shortcutTarget=$link.TargetPath
 $summary.expectedLauncher=Join-Path $installed 'FS_elem.exe'
 # WScript may expose an ANSI target. Read the actual .lnk via IShellLinkW.
 Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class InstallerFilePath {
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW {
        [PreserveSig]
        int GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, IntPtr findData, uint flags);
    }
    public static string ShortcutTarget(string path) {
        object link = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046"), true));
        try {
            ((System.Runtime.InteropServices.ComTypes.IPersistFile)link).Load(path, 0);
            var result = new StringBuilder(32768);
            int status = ((IShellLinkW)link).GetPath(result, result.Capacity, IntPtr.Zero, 0);
            if (status != 0) throw new IOException("IShellLinkW.GetPath failed: " + status);
            if (result.Length == 0) throw new IOException("IShellLinkW returned an empty target");
            return result.ToString();
        } finally {Marshal.FinalReleaseComObject(link);}
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle handle, StringBuilder path, uint size, uint flags);
    public static string Resolve(string path) {
        using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
            var result = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandle(stream.SafeFileHandle, result, (uint)result.Capacity, 0);
            if (length == 0 || length >= result.Capacity)
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Cannot resolve installed file path");
            return result.ToString();
        }
    }
}
'@
 $summary.shortcutUnicodeTarget=[InstallerFilePath]::ShortcutTarget($shortcut)
 $target=[IO.Path]::GetFullPath($summary.shortcutUnicodeTarget)
 $expected=[IO.Path]::GetFullPath($summary.expectedLauncher)
 $summary.shortcutTargetExists=Test-Path -LiteralPath $target -PathType Leaf
 $summary.expectedLauncherExists=Test-Path -LiteralPath $expected -PathType Leaf
 if(-not $summary.shortcutTargetExists -or -not $summary.expectedLauncherExists){
  throw "Shortcut/app file missing: WScript=$($summary.shortcutTarget) unicode=$target expected=$expected actualExists=$($summary.shortcutTargetExists) expectedExists=$($summary.expectedLauncherExists)"
 }
 # Both existing files must still resolve to the same installed executable.
 $summary.shortcutCanonicalTarget=[InstallerFilePath]::Resolve($target)
 $summary.installedCanonicalLauncher=[InstallerFilePath]::Resolve($expected)
 if(-not [string]::Equals($summary.shortcutCanonicalTarget,$summary.installedCanonicalLauncher,[StringComparison]::OrdinalIgnoreCase)){
  throw "Shortcut points outside installed app: actual=$target expected=$expected actualCanonical=$($summary.shortcutCanonicalTarget) expectedCanonical=$($summary.installedCanonicalLauncher)"
 }
 $env:PATH=(Join-Path $installed '.runtime\node')+';'+$env:SystemRoot+'\System32;'+$env:SystemRoot
 foreach($key in 'PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','NODE_OPTIONS'){[Environment]::SetEnvironmentVariable($key,$null,'Process')}
 $env:PYTHONDONTWRITEBYTECODE='1'
 $env:PYTHONUTF8='1'
 $env:PYTHONIOENCODING='utf-8'
 $science=Join-Path $installed '.runtime\venv-science\Scripts\python.exe'
 $pose=Join-Path $installed '.runtime\venv-pose\Scripts\python.exe'
 $node=Join-Path $installed '.runtime\node\node.exe'
 $summary.cleanPath=$env:PATH
 Run 'science-relocated-pip-check' $science @('-I','-m','pip','check')|Out-Null
 Run 'pose-relocated-pip-check' $pose @('-I','-m','pip','check')|Out-Null
 $dllCheck=@'
import ctypes,json,pathlib,sys
k=ctypes.WinDLL("kernel32",use_last_error=True)
k.GetModuleHandleW.argtypes=[ctypes.c_wchar_p]
k.GetModuleHandleW.restype=ctypes.c_void_p
k.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
k.GetModuleFileNameW.restype=ctypes.c_uint
expected=pathlib.Path(sys.executable).resolve().parent.parent
loaded={}
for name in ("vcruntime140.dll","vcruntime140_1.dll","msvcp140.dll"):
    handle=k.GetModuleHandleW(name)
    if not handle: continue
    buffer=ctypes.create_unicode_buffer(32768)
    count=k.GetModuleFileNameW(handle,buffer,len(buffer))
    assert 0<count<len(buffer), (name,ctypes.get_last_error())
    actual=pathlib.Path(buffer.value).resolve()
    loaded[name]=str(actual)
    assert expected in actual.parents, ("Non-app-local VC runtime",name,str(actual),str(expected))
assert loaded, "No loaded VC runtime identity"
print(json.dumps({"loadedVCRuntimePaths":loaded,"approvedRuntimeRoot":str(expected),"NN":0}))
'@
 Run 'science-relocated-imports' $science @('-I','-c',('import numpy,sklearn,joblib;print(numpy.__version__)'+[Environment]::NewLine+$dllCheck))|Out-Null
 Run 'pose-relocated-imports' $pose @('-I','-c',('import cv2,onnxruntime,rtmlib;assert "CPUExecutionProvider" in onnxruntime.get_available_providers();print(onnxruntime.__version__)'+[Environment]::NewLine+$dllCheck))|Out-Null
 $importProbe='import json,pathlib,runpy,sys;root=pathlib.Path(sys.argv[1]);results=[{"path":relative,"runName":runpy.run_path(str(root/relative),run_name="__installer_import_probe__")["__name__"]} for relative in sys.argv[2:]];print(json.dumps({"inertImports":results,"NN":0}))'
 Run 'science-installed-entrypoint-imports' $science @('-I','-c',$importProbe,$installed,'services/analysis/server.py','runtime/pipeline/run.py')|Out-Null
 Run 'pose-installed-entrypoint-imports' $pose @('-I','-c',$importProbe,$installed,'runtime/pipeline/worker.py')|Out-Null
 foreach($flag in '-version','-L','-buildconf'){Run ('ffmpeg-'+$flag.TrimStart('-')) (Join-Path $installed '.runtime\bin\ffmpeg.exe') @($flag)|Out-Null}
 $watch=[Diagnostics.Stopwatch]::StartNew()
 Run 'first-run-full-setup' $science @('-I',(Join-Path $installed 'scripts\windows-first-run.py'),'--root',$installed)|Out-Null
 $summary.fullSetupSeconds=$watch.Elapsed.TotalSeconds
 $watch.Restart()
 $second=Run 'second-run-cached-setup' $science @('-I',(Join-Path $installed 'scripts\windows-first-run.py'),'--root',$installed)
 $summary.cachedSetupSeconds=$watch.Elapsed.TotalSeconds
 $downloadEvents=@($second -split [Environment]::NewLine|Where-Object{$_ -match '"stage"\s*:\s*"download"'})
 if($downloadEvents.Count -gt 0){throw 'Second startup downloads again'}
 Run 'node-python-receipt-parity' $node @('--input-type=module','-e',
  'const m=await import(process.argv[1]);console.log(m.requireDesktopReady(process.argv[2]));',
  ([Uri](Join-Path $installed 'scripts\windows-bundle.mjs')).AbsoluteUri,$installed)|Out-Null

 $watch.Restart()
 $shortcutLaunch=[Diagnostics.ProcessStartInfo]::new($shortcut)
 $shortcutLaunch.UseShellExecute=$true
 $shortcutLaunch.WorkingDirectory=$installed
 $launcher=[Diagnostics.Process]::Start($shortcutLaunch)
 if($null -eq $launcher){throw 'Unicode Shell shortcut launch returned no process handle'}
 $summary.shortcutLaunchedViaShell=$true
 Wait-Ready $launcher
 $summary.desktopReadySeconds=$watch.Elapsed.TotalSeconds
 $launcher.Refresh()
 if($launcher.MainWindowHandle -eq 0){throw 'Native launcher window missing'}
 $summary.guiWindowTitle=$launcher.MainWindowTitle
 $summary.healthStatus=200;$summary.analysisStatus=200
 $controller=Controller-Pid $launcher
 # The user's browser is deliberately outside the owned service Job Object.
 $owned=Snapshot $controller
 $owned+=@(Get-CimInstance Win32_Process -Filter ("ProcessId="+$launcher.Id)|Select-Object ProcessId,ParentProcessId,CreationDate,Name)
 $summary.cooperativeSnapshot=$owned
 if(@($owned|Where-Object{$_.Name -eq 'conhost.exe'}).Count -gt 0){throw 'Unexpected owned console process'}
 $summary.ownedConsoleProcessCount=0
 $bad=Invoke-WebRequest 'http://127.0.0.1:5174/api/analysis/jobs' -Method POST -Headers @{'X-Filename'='not-a-video.txt'} -ContentType 'application/octet-stream' -Body ([Text.Encoding]::UTF8.GetBytes('invalid')) -SkipHttpErrorCheck -TimeoutSec 10 -NoProxy
 $summary.unsupportedUploadStatus=$bad.StatusCode
 if($bad.StatusCode -ne 415){throw 'Unsupported upload did not return415'}
 if(-not $launcher.CloseMainWindow()){throw 'Cannot request GUI shutdown'}
 if(-not $launcher.WaitForExit(15000)){throw 'GUI cooperative shutdown exceeded15s'}
 $summary.guiExitCode=$launcher.ExitCode
 if($launcher.ExitCode -ne 0){throw 'GUI cooperative shutdown failed'}
 Require-Gone $owned
 $summary.cooperativeOwnedTreeStopped=$true
 $launcher.Dispose();$launcher=$null

 $launcher=Start-Process -FilePath (Join-Path $installed 'FS_elem.exe') -WorkingDirectory $installed -PassThru
 Wait-Ready $launcher
 $controller=Controller-Pid $launcher
 $force=Snapshot $controller
 $force+=@(Get-CimInstance Win32_Process -Filter ("ProcessId="+$launcher.Id)|Select-Object ProcessId,ParentProcessId,CreationDate,Name)
 $summary.forcedSnapshot=$force
 $launcher.Kill()
 if(-not $launcher.WaitForExit(10000)){throw 'Forced GUI stop did not signal'}
 Start-Sleep -Seconds 2
 Require-Gone $force
 $summary.forcedOwnedTreeStopped=$true
 $launcher.Dispose();$launcher=$null
 $state=Join-Path $env:LOCALAPPDATA 'FS_elem\data'
 New-Item -ItemType Directory -Path $state -Force|Out-Null
 $sentinel=Join-Path $state 'installer-check-preserved.txt'
 [IO.File]::WriteAllText($sentinel,'user data must survive uninstall')
 $uninstall=Start-Process -FilePath (Join-Path $installed 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru -Wait
 $summary.uninstallExitCode=$uninstall.ExitCode
 if($uninstall.ExitCode -ne 0 -or -not(Test-Path -LiteralPath $sentinel)){throw 'Uninstall did not preserve user data'}
 $summary.userDataPreserved=$true
 $summary.status='passed'
}catch{
 $summary.status='failed';$summary.firstFailure=$_.Exception.Message
 throw
}finally{
 if($launcher -and -not $launcher.HasExited){
  [void]$launcher.CloseMainWindow()
  if(-not $launcher.WaitForExit(10000)){$launcher.Kill();[void]$launcher.WaitForExit(10000)}
 }
 if($launcher){$launcher.Dispose()}
 if(Test-Path -LiteralPath $logPath){Copy-Item -LiteralPath $logPath -Destination (Join-Path $Logs 'installed-launcher.log')}
 [IO.File]::WriteAllText((Join-Path $WorkRoot 'native-install-check.json'),($summary|ConvertTo-Json -Depth 15),[Text.UTF8Encoding]::new($false))
}
