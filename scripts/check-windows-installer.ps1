param(
 [Parameter(Mandatory=$true)][string]$Installer,
 [Parameter(Mandatory=$true)][string]$WorkRoot,
 [Parameter(Mandatory=$true)][string]$Logs,
 [Parameter(Mandatory=$true)][string]$RootGrant,
 [Parameter(Mandatory=$true)][string]$RootGrantSha256,
 [Parameter(Mandatory=$true)][string]$OfflineVideo
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$installed=Join-Path $WorkRoot 'Установка & проверка\FS_elem'
$summary=@{status='pending';NN=0;acceptedVideoUploads=0;desktopQualification='Windows Server CI; desktop10/11 manual user flow remains separate'}
$launcher=$null
$firewallGroup='FS_elem-offline-check-'+[Guid]::NewGuid().ToString('N')
$firewallPrograms=@()
$firewallStarted=$false
$firewallProfilesTouched=$false
$firewallPriorPersistent=@()
$firewallPriorActive=@()
$firewallChangedNames=@()
$userState=Join-Path $env:LOCALAPPDATA 'FS_elem'
$logPath=Join-Path $env:LOCALAPPDATA 'FS_elem\logs\launcher.log'
function Save-LauncherEvidence([string]$Label){
 foreach($name in 'launcher.log','startup-failure.json'){
  $path=Join-Path (Split-Path $logPath -Parent) $name
  if(Test-Path -LiteralPath $path -PathType Leaf){
   $bound=if($name -eq 'launcher.log'){263168}else{65536}
   if((Get-Item -LiteralPath $path).Length -gt $bound){throw 'Launcher evidence exceeds retained bound'}
   Copy-Item -LiteralPath $path -Destination (Join-Path $Logs ($Label+'-'+$name))
  }
 }
}
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
function Limit-Text([string]$Value,[int]$MaxBytes){
 $bytes=[Text.Encoding]::UTF8.GetBytes($Value)
 if($bytes.Length -le $MaxBytes){return $Value}
 $encoding=[Text.UTF8Encoding]::new($false,$true)
 for($size=$MaxBytes;$size -ge $MaxBytes-3;$size--){
  try{return $encoding.GetString($bytes,0,$size)}catch [Text.DecoderFallbackException]{}
 }
 throw 'Cannot retain bounded UTF8 response prefix'
}
function Wait-Ready($Process,[int]$TimeoutSeconds=90){
 $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
 $lastProxy=$null;$lastUi=$null;$lastError=$null
 while([DateTime]::UtcNow -lt $deadline){
  if($Process.HasExited){throw 'Installed GUI exited before ready'}
  try{
   $health=Invoke-WebRequest 'http://127.0.0.1:5174/api/analysis/health' -TimeoutSec 2 -UseBasicParsing -NoProxy -SkipHttpErrorCheck
   $content=[string]$health.Content
   $lastProxy=@{status=[int]$health.StatusCode;body=(Limit-Text $content 8192);bodyTruncated=([Text.Encoding]::UTF8.GetByteCount($content) -gt 8192)}
   $ui=Invoke-WebRequest 'http://127.0.0.1:5174/analysis' -TimeoutSec 2 -UseBasicParsing -NoProxy -SkipHttpErrorCheck
   $content=[string]$ui.Content
   $lastUi=@{status=[int]$ui.StatusCode;body=(Limit-Text $content 8192);bodyTruncated=([Text.Encoding]::UTF8.GetByteCount($content) -gt 8192)}
   $body=$health.Content|ConvertFrom-Json
   if($health.StatusCode -eq 200 -and $ui.StatusCode -eq 200 -and $body.status -eq 'ready' -and $body.inferenceAvailable -eq $true -and $body.PSObject.Properties.Name -contains 'activeJobId' -and $null -eq $body.activeJobId){return}
  }catch{$failure=$_.Exception.Message;$lastError=Limit-Text $failure 4096}
  Start-Sleep -Milliseconds 500
 }
 # Preserve actual HTTP evidence while owned services are still running.
 # These diagnostic responses never satisfy or weaken the readiness gate.
 $summary.lastProxyReadiness=$lastProxy;$summary.lastUiReadiness=$lastUi;$summary.lastReadinessError=$lastError
 $probeEvidence=[Collections.Generic.List[object]]::new()
 foreach($url in 'http://127.0.0.1:5175/health','http://127.0.0.1:5174/api/analysis/health','http://127.0.0.1:5174/analysis'){
  try{
   $response=Invoke-WebRequest $url -TimeoutSec 2 -UseBasicParsing -NoProxy -SkipHttpErrorCheck -MaximumRedirection 0
   $content=[string]$response.Content
   $probeEvidence.Add(@{url=$url;status=[int]$response.StatusCode;body=(Limit-Text $content 8192);bodyTruncated=([Text.Encoding]::UTF8.GetByteCount($content) -gt 8192)})
  }catch{
   $failure=$_.Exception.Message
   $probeEvidence.Add(@{url=$url;error=(Limit-Text $failure 4096)})
  }
 }
 $summary.readinessFailure=$probeEvidence
 [IO.File]::WriteAllText((Join-Path $Logs 'readiness-http.json'),($probeEvidence|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
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
function Confirm-ConsoleTopology($Owned,[int]$Controller){
 $brokers=@($Owned|Where-Object{$_.Name -eq 'conhost.exe'})
 $summary.lastConsoleTopologySnapshot=$Owned
 $summary.lastConsoleBrokerIdentityFacts=@()
 $windows=@([InstallerFilePath]::OwnedWindows([uint[]]@($Owned|ForEach-Object{$_.ProcessId})))
 if(@($windows|Where-Object{[string]::IsNullOrEmpty($_.ClassName)}).Count -gt 0){throw 'Cannot classify an owned console-topology window'}
 if(@($windows|Where-Object{$_.Visible -and ($_.ClassName -eq 'ConsoleWindowClass' -or $_.ProcessId -in @($brokers.ProcessId))}).Count -gt 0){throw 'Visible owned console window is forbidden'}
 $facts=@()
 foreach($broker in $brokers){
  $parent=@($Owned|Where-Object{$_.ProcessId -eq $broker.ParentProcessId})
  if($parent.Count -ne 1){throw 'Hidden broker parent is not a known owned generation'}
  $currentBroker=@(Get-CimInstance Win32_Process -Filter ('ProcessId='+$broker.ProcessId))
  $currentParent=@(Get-CimInstance Win32_Process -Filter ('ProcessId='+$parent[0].ProcessId))
  if($currentBroker.Count -ne 1 -or $currentParent.Count -ne 1 -or $currentBroker[0].CreationDate -ne $broker.CreationDate -or $currentParent[0].CreationDate -ne $parent[0].CreationDate){throw 'Hidden broker/parent original identity changed'}
  $canonical=[InstallerFilePath]::Resolve($currentBroker[0].ExecutablePath)
  $expected=[InstallerFilePath]::Resolve((Join-Path $env:SystemRoot 'System32\conhost.exe'))
  if(-not [string]::Equals($canonical,$expected,[StringComparison]::OrdinalIgnoreCase)){throw 'Hidden broker is not canonical system conhost'}
  $role=$null
  $image=[IO.Path]::GetFullPath($currentParent[0].ExecutablePath)
  $line=([string]$currentParent[0].CommandLine).Replace('/','\')
  if($parent[0].ProcessId -eq $Controller -and [string]::Equals($image,(Join-Path $installed '.runtime\node\node.exe'),[StringComparison]::OrdinalIgnoreCase) -and $line.IndexOf((Join-Path $installed 'scripts\start-release.mjs'),[StringComparison]::OrdinalIgnoreCase) -ge 0 -and $line -match '(?:^|\s)"?--desktop"?(?:\s|$)'){$role='desktop-controller'}
  elseif([string]::Equals($image,(Join-Path $installed '.runtime\venv-science\Scripts\python.exe'),[StringComparison]::OrdinalIgnoreCase) -and $line.IndexOf((Join-Path $installed 'services\analysis\server.py'),[StringComparison]::OrdinalIgnoreCase) -ge 0){$role='analysis-backend'}
  $parentProgram=if($role -eq 'desktop-controller'){'.runtime/node/node.exe'}elseif($role -eq 'analysis-backend'){'.runtime/venv-science/Scripts/python.exe'}else{$null}
  $fact=@{pid=$broker.ProcessId;creationDate=$broker.CreationDate;parentPid=$parent[0].ProcessId;parentCreationDate=$parent[0].CreationDate;parentRole=$role;canonicalSystemConhost=$true;canonicalConhostImage=$canonical;parentInstalledProgram=$parentProgram;acceptedInstalledParentImage=($null -ne $role);acceptedCommandLine=($null -ne $role);visible=$false}
  $summary.lastConsoleBrokerIdentityFacts+=$fact
  if(-not $role -or $role -notin $grant.allowedHiddenConsoleParentRoles){throw 'Hidden broker has an unadmitted parent role'}
  $facts+=$fact
 }
 # Cold startup has one desktop-controller broker and one API broker. Each
 # must prove its identity/role before aggregate policy is evaluated.
 if($brokers.Count -gt 2 -or @($facts.parentRole|Sort-Object -Unique).Count -ne $facts.Count){throw 'Additional/duplicate-role hidden console broker is forbidden'}
 return $facts
}
try{
 if(-not(Test-Path -LiteralPath $RootGrant -PathType Leaf) -or (Get-Item -LiteralPath $RootGrant).Length -gt 65536){throw 'Distinct bounded Root native grant missing'}
 if($RootGrantSha256 -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $RootGrant -Algorithm SHA256).Hash.ToLowerInvariant() -ne $RootGrantSha256){throw 'Root native grant pin mismatch'}
 $grant=Get-Content -LiteralPath $RootGrant -Raw -Encoding UTF8|ConvertFrom-Json
 if($grant.nativeCheckSha256 -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $grant.nativeCheckSha256){throw 'Root native operator Source binding missing/changed'}
 if($grant.scope -ne 'windows-offline-native-check-v025' -or $grant.allowInstall -ne $true -or $grant.allowGUI -ne $true -or $grant.allowNN -ne $true -or $grant.publicVideo -ne $true){throw 'Root grant does not admit this install/GUI/public-video inference scope'}
 if($grant.installerSha256 -notmatch '^[0-9a-f]{64}$' -or $grant.installerBytes -le 0 -or -not(Test-Path -LiteralPath $Installer -PathType Leaf) -or (Get-Item -LiteralPath $Installer).Length -ne $grant.installerBytes -or (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant() -cne $grant.installerSha256){throw 'Root generated Setup artifact binding missing/changed'}
 if($grant.videoSha256 -notmatch '^[0-9a-f]{64}$' -or $grant.videoBytes -le 0 -or $grant.videoBytes -gt 16777216 -or $grant.maxInferenceSeconds -lt 1 -or $grant.maxInferenceSeconds -gt 5400){throw 'Root video/inference bounds missing'}
 if(-not(Test-Path -LiteralPath $OfflineVideo -PathType Leaf) -or (Get-Item -LiteralPath $OfflineVideo).Length -ne $grant.videoBytes -or (Get-FileHash -LiteralPath $OfflineVideo -Algorithm SHA256).Hash.ToLowerInvariant() -ne $grant.videoSha256){throw 'Public three-second video pin mismatch'}
 if([string]$grant.publicSourceUrl -notmatch '^https://'){throw 'Public video provenance missing'}
 if($grant.videoBytes -ne 818120 -or $grant.videoSha256 -cne 'b142e4df68b709475cc016c35b67d2a6999afc8c7644b91722093cd2e4355b5d'){throw 'Only the Root-approved existing public example-1a clip is admitted'}
 if($grant.maxInferenceSeconds -ne 120 -or $grant.wholeSeconds -ne 150 -or $grant.cleanupSeconds -ne 30 -or $grant.RSSBytes -ne 4294967296 -or $grant.newArtifactBytes -ne 67108864 -or $grant.retry -ne 0 -or $grant.intraOpThreads -ne 4 -or $grant.interOpThreads -ne 1){throw 'Root offline-analysis resource/CPU admission does not match prescribed scope'}
 $expectedModels=@{
  flight='9d6ca74b3de38dab1366c55f55b8de0bca6052ce1aa0c7dedd45ae17cf0140e7';
  family='1f696a6ab8a300320b7cdff5875ec22a6206ff32bd731c81db00f905529d5f72';
  nominal='f4c2e2b70400bd161a3c9bed62e5e892d6712134719a647a0dd53877bce792f1';
  yolox='3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23';
  rtmw='bd033156e5104c4f5d2edfe0453e02661e30a2f3da453ec93c8764d561b83054'
 }
 foreach($key in $expectedModels.Keys){if($grant.modelSha256.$key -cne $expectedModels[$key]){throw 'Root native model digest scope missing/changed'}}
 if($grant.allowedHiddenConsoleCount -ne 2 -or @($grant.allowedHiddenConsoleParentRoles).Count -ne 2 -or @($grant.allowedHiddenConsoleParentRoles|Sort-Object -Unique).Count -ne 2 -or @($grant.allowedHiddenConsoleParentRoles|Where-Object{$_ -notin @('desktop-controller','analysis-backend')}).Count -gt 0){throw 'Root cold hidden-console topology admission missing/overbroad'}
 if(Test-Path -LiteralPath $userState){throw 'Native cold-first-launch requires a genuinely new Windows user state; never erase existing user data'}
 $identity=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
 if(-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Root native offline check requires administrative firewall admission'}
 if($grant.rssEnforcement -cne 'sampled-aggregate-rss-and-stop-check'){throw 'Root grant must truthfully admit sampled RSS/stop checks; no hard JobObject proof supplied'}
 if((Get-Service MpsSvc).Status -ne 'Running'){throw 'Active Windows firewall service required; no service-state mutation is admitted'}
 $firewallPriorPersistent=@(Get-NetFirewallProfile -PolicyStore PersistentStore|Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction)
 $firewallPriorActive=@(Get-NetFirewallProfile -PolicyStore ActiveStore|Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction)
 if($firewallPriorPersistent.Count -ne 3 -or $firewallPriorActive.Count -ne 3){throw 'Exact firewall profile snapshot unresolved'}
 $disabled=@($firewallPriorActive|Where-Object{$_.Enabled -ne 'True'})
 if($disabled.Count -gt 0 -and $grant.allowTemporaryFirewallEnable -ne $true){throw 'Disabled host firewall requires explicit reversible Root profile-enable admission'}
 # Enabling a profile must not block the runner's outbound artifact/control
 # traffic. Unknown effective outbound policy is a prerequisite failure.
 if(@($disabled|Where-Object{$_.DefaultOutboundAction -ne 'Allow'}).Count -gt 0){throw 'Effective outbound-Allow policy must be proven before temporary profile enable'}
 $summary.firewallPriorPersistent=$firewallPriorPersistent
 $summary.firewallPriorActive=$firewallPriorActive
 $summary.rssEnforcement='sampled-aggregate-rss-and-stop-check'
 $summary.rootGrantSha256=$RootGrantSha256
 $summary.coldUserStateConfirmed=$true
 # Reject foreign localhost services instead of accepting them as this installer.
 foreach($port in 5174,5175){
  $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port)
  try{$listener.Start()}finally{$listener.Stop()}
 }
 $installLog=Join-Path $Logs 'installer.log'
 $setup=Start-Process -FilePath $Installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS=desktopicon',('/DIR="'+$installed+'"'),('/LOG="'+$installLog+'"')) -PassThru -Wait
 $summary.installerExitCode=$setup.ExitCode
 if($setup.ExitCode -ne 0){throw 'Installer failed'}
 if(Test-Path -LiteralPath (Join-Path $installed '.runtime\windows-ready.json')){throw 'Installer contains a warmed ready receipt'}
 foreach($profile in $disabled){
  $firewallProfilesTouched=$true
  $firewallChangedNames+=$profile.Name
  Set-NetFirewallProfile -PolicyStore PersistentStore -Name $profile.Name -Enabled True -ErrorAction Stop
 }
 $activeProfiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore)
 if(@($activeProfiles|Where-Object{$_.Enabled -ne 'True'}).Count -ne 0){throw 'Application deny policy cannot be enforced on this hosted runner'}
 $firewallPrograms=@('FS_elem.exe','.runtime\node\node.exe','.runtime\venv-science\Scripts\python.exe','.runtime\venv-pose\Scripts\python.exe','.runtime\bin\ffmpeg.exe')|ForEach-Object{Join-Path $installed $_}
 # Any covers both IP families for only these exact installed executables.
 # Classic Win32 loopback behavior is NOT assumed: Root prerequisite and
 # strict local health/public functional native gate must prove it.
 $deny='Any'
 foreach($program in $firewallPrograms){
  if(-not(Test-Path -LiteralPath $program -PathType Leaf)){throw 'Offline runtime executable missing before first GUI'}
  $firewallStarted=$true
  New-NetFirewallRule -DisplayName ('FS_elem offline deny '+[IO.Path]::GetFileName($program)) -Group $firewallGroup -Direction Outbound -Action Block -Program $program -RemoteAddress $deny -Profile Any -Enabled True -ErrorAction Stop|Out-Null
 }
 $effective=@(Get-NetFirewallRule -PolicyStore ActiveStore|Where-Object{$_.Group -eq $firewallGroup -and $_.Enabled -eq 'True' -and $_.Direction -eq 'Outbound' -and $_.Action -eq 'Block'})
 if($effective.Count -ne $firewallPrograms.Count){throw 'Non-loopback deny policy did not become active'}
 $summary.offlineNetworkPolicy=@($effective|ForEach-Object{@{name=$_.Name;program=(Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $_).Program;remoteAddresses=@((Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $_).RemoteAddress)}})
 foreach($program in $firewallPrograms){
  if(@($summary.offlineNetworkPolicy|Where-Object{$_.program -eq $program -and $_.remoteAddresses.Count -eq 1 -and $_.remoteAddresses[0] -eq 'Any'}).Count -ne 1){throw 'Effective per-program Any outbound deny binding unresolved'}
 }
 $summary.nonLoopbackNetworkPhysicallyDenied=$true

 $shortcut=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\FS_elem\FS_elem.lnk'
 if(-not(Test-Path -LiteralPath $shortcut)){throw 'Start Menu shortcut missing'}
 $link=(New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
 $summary.shortcutPath=$shortcut
 $summary.shortcutTarget=$link.TargetPath
 $summary.expectedLauncher=Join-Path $installed 'FS_elem.exe'
 # WScript may expose an ANSI target. Read the actual .lnk via IShellLinkW.
 Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public static class InstallerFilePath {
    public sealed class WindowRecord {
        public uint ProcessId;
        public string Handle, ClassName, Title;
        public bool Visible;
    }
    private delegate bool EnumWindowProc(IntPtr window, IntPtr data);
    [DllImport("user32.dll", SetLastError=true)]
    private static extern bool EnumWindows(EnumWindowProc callback, IntPtr data);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    private static extern int GetClassName(IntPtr window, StringBuilder name, int size);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr window, StringBuilder text, int size);
    public static WindowRecord[] OwnedWindows(uint[] processIds) {
        var wanted = new HashSet<uint>(processIds);
        var result = new List<WindowRecord>();
        bool overflow = false;
        EnumWindowProc callback = (window, data) => {
            uint pid;
            GetWindowThreadProcessId(window, out pid);
            if (!wanted.Contains(pid)) return true;
            if (result.Count >= 128) {overflow = true; return false;}
            var name = new StringBuilder(256);
            var title = new StringBuilder(256);
            GetClassName(window, name, name.Capacity);
            GetWindowText(window, title, title.Capacity);
            result.Add(new WindowRecord {ProcessId=pid, Handle=window.ToInt64().ToString(),
                ClassName=name.ToString(), Title=title.ToString(), Visible=IsWindowVisible(window)});
            return true;
        };
        bool enumerated = EnumWindows(callback, IntPtr.Zero);
        if (overflow) throw new IOException("Owned window snapshot exceeds128 entries");
        if (!enumerated) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "EnumWindows failed");
        return result.ToArray();
    }
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
 # The first app-owned runtime action is the GUI. No bootstrap/import/cache warmup.
 $watch=[Diagnostics.Stopwatch]::StartNew()
 $watch.Restart()
 $shortcutLaunch=[Diagnostics.ProcessStartInfo]::new($shortcut)
 $shortcutLaunch.UseShellExecute=$true
 $shortcutLaunch.WorkingDirectory=$installed
 $launcher=[Diagnostics.Process]::Start($shortcutLaunch)
 if($null -eq $launcher){throw 'Unicode Shell shortcut launch returned no process handle'}
 $summary.shortcutLaunchedViaShell=$true
 # First cold bootstrap includes local verification of the entire offline payload.
 # Relaunch retains the existing90s default; no product-speed improvement claimed.
 Wait-Ready $launcher 180
 $summary.desktopReadySeconds=$watch.Elapsed.TotalSeconds
 $launcher.Refresh()
 if($launcher.MainWindowHandle -eq 0){throw 'Native launcher window missing'}
 $summary.guiWindowTitle=$launcher.MainWindowTitle
 $summary.healthStatus=200;$summary.analysisStatus=200
 Save-LauncherEvidence 'cold-first-gui'
 $bundle=Get-Content -LiteralPath (Join-Path $installed 'windows-bundle.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $manifest=Get-Content -LiteralPath (Join-Path $installed 'assets\models\manifest-release-v1.json') -Raw -Encoding UTF8|ConvertFrom-Json
 if($bundle.offline -ne $true -or $bundle.packageVersion -ne '0.2.5' -or $manifest.models.Count -ne 5){throw 'Installed offline bundle/model declaration missing'}
 if(@($manifest.models.id|Sort-Object -Unique).Count -ne 5){throw 'Installed manifest model identities duplicated'}
 foreach($model in $manifest.models){
  $row=@($bundle.files|Where-Object{$_.path -ceq $model.path})
  if($row.Count -ne 1 -or $row[0].bytes -ne $model.sizeBytes -or $row[0].sha256 -cne $model.sha256 -or $model.sha256 -cne $expectedModels[$model.id]){throw 'Installed inventory omits/changes a manifest model'}
 }
 $summary.allFiveModelInventoryBound=$true
 $controller=Controller-Pid $launcher
 # The user's browser is deliberately outside the owned service Job Object.
 $owned=Snapshot $controller
 $owned+=@(Get-CimInstance Win32_Process -Filter ("ProcessId="+$launcher.Id)|Select-Object ProcessId,ParentProcessId,CreationDate,Name)
 $summary.cooperativeSnapshot=$owned
 $summary.ownedConsoleProcessCount=@($owned|Where-Object{$_.Name -eq 'conhost.exe'}).Count
 $shells=@($owned|Where-Object{$_.Name -in @('cmd.exe','powershell.exe','pwsh.exe')})
 if($shells.Count -gt 0){throw 'Unexpected owned command shell process'}
 $current=@(Get-CimInstance Win32_Process|Select-Object ProcessId,CreationDate)
 foreach($original in $owned){
  if(@($current|Where-Object{$_.ProcessId -eq $original.ProcessId -and $_.CreationDate -eq $original.CreationDate}).Count -ne 1){throw 'Owned window probe process generation changed'}
 }
 $windows=@([InstallerFilePath]::OwnedWindows([uint[]]@($owned|ForEach-Object{$_.ProcessId})))
 $summary.ownedWindowSnapshot=$windows
 $current=@(Get-CimInstance Win32_Process|Select-Object ProcessId,CreationDate)
 foreach($original in $owned){
  if(@($current|Where-Object{$_.ProcessId -eq $original.ProcessId -and $_.CreationDate -eq $original.CreationDate}).Count -ne 1){throw 'Owned window probe process generation changed during enumeration'}
 }
 if(@($windows|Where-Object{[string]::IsNullOrEmpty($_.ClassName)}).Count -gt 0){throw 'Cannot classify an owned window'}
 $guiWindow=@($windows|Where-Object{$_.ProcessId -eq $launcher.Id -and $_.Handle -eq $launcher.MainWindowHandle.ToInt64().ToString()})
 if($guiWindow.Count -ne 1){throw 'EnumWindows did not observe the current native GUI window'}
 $consoleBrokers=@($owned|Where-Object{$_.Name -eq 'conhost.exe'}|ForEach-Object{$_.ProcessId})
 $visibleConsoles=@($windows|Where-Object{$_.Visible -and ($_.ClassName -eq 'ConsoleWindowClass' -or $_.ProcessId -in $consoleBrokers)})
 $summary.visibleOwnedConsoleWindowCount=$visibleConsoles.Count
 if($visibleConsoles.Count -gt 0){throw 'Visible owned console window violates shortcut launch requirement'}
 $summary.ownedWindowEnumerationConfirmed=$true
 $summary.coldHiddenConsoleBrokers=@(Confirm-ConsoleTopology $owned $controller)
 $bad=Invoke-WebRequest 'http://127.0.0.1:5174/api/analysis/jobs' -Method POST -Headers @{'X-Filename'='not-a-video.txt'} -ContentType 'application/octet-stream' -Body ([Text.Encoding]::UTF8.GetBytes('invalid')) -SkipHttpErrorCheck -TimeoutSec 10 -NoProxy
 $summary.unsupportedUploadStatus=$bad.StatusCode
 if($bad.StatusCode -ne 415){throw 'Unsupported upload did not return415'}

 # One real local analysis is admitted only by the separate pinned Root grant.
 $analysisWatch=[Diagnostics.Stopwatch]::StartNew()
 $body=[IO.File]::ReadAllBytes($OfflineVideo)
 $created=Invoke-WebRequest 'http://127.0.0.1:5174/api/analysis/jobs' -Method POST -Headers @{'X-Filename'=[Uri]::EscapeDataString([IO.Path]::GetFileName($OfflineVideo))} -ContentType 'application/octet-stream' -Body $body -SkipHttpErrorCheck -TimeoutSec 15 -NoProxy
 if($created.StatusCode -ne 202){throw 'Offline public video upload was not accepted'}
 $summary.NN=1;$summary.acceptedVideoUploads=1
 $job=$created.Content|ConvertFrom-Json
 if([string]::IsNullOrEmpty($job.jobId)){throw 'Accepted offline job identity missing'}
 $publicJobId=[string]$job.jobId
 $jobUrl='http://127.0.0.1:5174/api/analysis/jobs/'+[Uri]::EscapeDataString($job.jobId)
 $summary.observedAnalysisPeakRSSBytes=0
 while($analysisWatch.Elapsed.TotalSeconds -lt 120){
  $family=Snapshot $controller
  $rss=0
  foreach($record in $family){
   $observed=Get-Process -Id $record.ProcessId -ErrorAction SilentlyContinue
   if($observed){
    try{if($observed.StartTime.ToUniversalTime() -eq $record.CreationDate.ToUniversalTime()){$rss+=$observed.WorkingSet64}}catch [InvalidOperationException]{}
   }
  }
  $summary.observedAnalysisPeakRSSBytes=[Math]::Max($summary.observedAnalysisPeakRSSBytes,$rss)
  if($rss -gt 4294967296){throw 'Observed analysis family RSS exceeds4GiB'}
  $newBytes=(@(Get-ChildItem -LiteralPath $userState -Recurse -File)|Measure-Object Length -Sum).Sum
  if($newBytes -gt 67108864){throw 'Offline user artifacts exceed64MiB'}
  $job=Invoke-RestMethod $jobUrl -TimeoutSec 3 -NoProxy
  if($job.state -in @('succeeded','failed','cancelled')){break}
  Start-Sleep -Milliseconds 500
 }
 if($job.state -ne 'succeeded'){
  $firstCause=if(-not [string]::IsNullOrEmpty([string]$job.error.message)){Limit-Text ([string]$job.error.message) 4096}else{'Real offline analysis did not succeed within Root bound'}
  $runtimeDiagnostic=@{saved=$false;jobId=$publicJobId}
  try{
   $parsed=[Guid]::Empty
   if(-not [Guid]::TryParseExact($publicJobId,'D',[ref]$parsed) -or [string]$job.jobId -cne $publicJobId -or $job.source.sha256 -cne $grant.videoSha256){throw 'Runtime-log capture is not bound to the actual public UUID job'}
   $jobDirectory=[IO.Path]::GetFullPath((Join-Path (Join-Path $userState 'jobs') $publicJobId))
   $runtimePath=Join-Path $jobDirectory 'runtime.log'
   $item=Get-Item -LiteralPath $runtimePath -Force -ErrorAction Stop
   if($item.PSIsContainer){throw 'Runtime log is not a regular file'}
   # Hold read-only/no-delete sharing while validating the named file and reading
   # its prefix, so a path replacement cannot redirect the validated capture.
   $incoming=[IO.File]::Open($runtimePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
   try{
   $cursor=$runtimePath
   while($cursor){
    $part=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
    if(($part.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Runtime-log path contains a reparse point'}
    $parent=[IO.Directory]::GetParent($cursor)
    $cursor=if($parent){$parent.FullName}else{$null}
   }
   $canonical=[InstallerFilePath]::Resolve($runtimePath)
   if($canonical.StartsWith('\\?\')){$canonical=$canonical.Substring(4)}
   if(-not [string]::Equals($canonical,[IO.Path]::GetFullPath($runtimePath),[StringComparison]::OrdinalIgnoreCase) -or -not $canonical.StartsWith($jobDirectory+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Runtime log is not canonically contained in the bound public job directory'}
    $prefix=[byte[]]::new([int][Math]::Min(65536,$incoming.Length));$count=0
    while($count -lt $prefix.Length){$read=$incoming.Read($prefix,$count,$prefix.Length-$count);if($read -eq 0){break};$count+=$read}
    $sourceBytes=$incoming.Length
   }finally{$incoming.Dispose()}
   $output=Join-Path $Logs 'offline-job-runtime-prefix.log'
   $outgoing=[IO.File]::Open($output,[IO.FileMode]::Create,[IO.FileAccess]::Write)
   try{$outgoing.Write($prefix,0,$count)}finally{$outgoing.Dispose()}
   $runtimeDiagnostic=@{saved=$true;jobId=$publicJobId;source='jobs/<bound-public-UUID>/runtime.log';sourceBytes=$sourceBytes;prefixBytes=$count;truncated=($sourceBytes -gt $count);output='offline-job-runtime-prefix.log';qualification='Raw bounded byte prefix; may end inside UTF8 codepoint; only this public-test job'}
  }catch{$runtimeDiagnostic.error=Limit-Text $_.Exception.Message 512}
  $summary.publicJobRuntimeDiagnostic=$runtimeDiagnostic
  try{
   $directJobJSON=$job|ConvertTo-Json -Depth 100 -Compress
   $responseBytes=[Text.Encoding]::UTF8.GetByteCount($directJobJSON)
   $capture=@{schemaVersion=1;kind='public-offline-test-job-failure';jobId=$job.jobId;state=$job.state;error=$job.error;elapsedSeconds=$analysisWatch.Elapsed.TotalSeconds;directJob=$job;responseBytes=$responseBytes;responseTruncated=$false;runtimeLog=$runtimeDiagnostic}
   $text=$capture|ConvertTo-Json -Depth 100 -Compress
   if([Text.Encoding]::UTF8.GetByteCount($text) -gt 65536){
    $capture=@{schemaVersion=1;kind='public-offline-test-job-failure';jobId=(Limit-Text ([string]$job.jobId) 512);state=(Limit-Text ([string]$job.state) 64);error=@{code=(Limit-Text ([string]$job.error.code) 256);message=(Limit-Text ([string]$job.error.message) 4096)};elapsedSeconds=$analysisWatch.Elapsed.TotalSeconds;directJobJSONPrefix=(Limit-Text $directJobJSON 12288);responseBytes=$responseBytes;responseTruncated=$true;runtimeLog=$runtimeDiagnostic}
    $text=$capture|ConvertTo-Json -Depth 100 -Compress
   }
   if([Text.Encoding]::UTF8.GetByteCount($text) -gt 65536){throw 'Bounded public job diagnostic exceeds64KiB'}
   [IO.File]::WriteAllText((Join-Path $Logs 'offline-job-failure.json'),$text,[Text.UTF8Encoding]::new($false))
   $summary.publicJobFailureDiagnosticSaved=$true
   $summary.publicJobFailureDiagnosticTruncated=$capture.responseTruncated
  }catch{
   $summary.publicJobFailureDiagnosticSaved=$false
   $summary.publicJobFailureDiagnosticWriteError=Limit-Text $_.Exception.Message 4096
  }
  throw $firstCause
 }
 $result=Invoke-WebRequest ($jobUrl+'/result') -TimeoutSec 3 -NoProxy
 $value=$result.Content|ConvertFrom-Json
 if($value.status -ne 'completed' -or $value.source.sha256 -ne $grant.videoSha256 -or $value.source.frameCount -ne 181 -or [Math]::Abs([double]$value.source.durationSeconds-3.0) -gt 0.1){throw 'Offline result/source/three-second binding failed'}
 if(@($value.events|Where-Object{$_.family -eq 'axel' -and $_.nominal -eq '1A'}).Count -lt 1){throw 'Familiar public clip did not produce a nonempty actual1A functional result'}
 $poseResponse=Invoke-WebRequest ($jobUrl+'/pose') -TimeoutSec 3 -NoProxy -MaximumRedirection 0
 if([Text.Encoding]::UTF8.GetByteCount([string]$poseResponse.Content) -gt 1048576){throw 'Offline pose evidence exceeds1MiB'}
 $poseValue=$poseResponse.Content|ConvertFrom-Json
 if($poseValue.source.sha256 -ne $grant.videoSha256 -or $poseValue.layout -ne 'coco-wholebody-first23' -or @($poseValue.frames|Where-Object{$_.points.Count -eq 23}).Count -lt 1){throw 'Offline actual23-point pose functional result missing'}
 $located=$false
 foreach($frame in @($poseValue.frames|Where-Object{$_.points.Count -eq 23})){
  foreach($point in $frame.points){
   if($null -eq $point){continue}
   $finite=$true
   foreach($field in 'x','y','confidence'){
    $component=$point.$field
    if($null -eq $component -or -not ($component -is [double] -or $component -is [single] -or $component -is [long] -or $component -is [int] -or $component -is [decimal])){$finite=$false;break}
    $number=[double]$component
    if([double]::IsNaN($number) -or [double]::IsInfinity($number)){$finite=$false;break}
   }
   if($finite){$located=$true;break}
  }
  if($located){break}
 }
 if(-not $located){throw 'Offline pose has no non-null landmark with finite x/y/confidence in a23-slot frame'}
 $summary.offlinePose=@{layout=$poseValue.layout;frames=$poseValue.frames.Count;pointsPerFrame=23;finiteLandmarkObserved=$true;functionalOnly=$true}
 Save-LauncherEvidence 'offline-analysis-before-relaunch'
 $resultBytes=[Text.Encoding]::UTF8.GetBytes([string]$result.Content)
 if($resultBytes.Length -gt 1048576){throw 'Offline result evidence exceeds1MiB'}
 $hash=[Security.Cryptography.SHA256]::Create()
 try{$resultSHA=([BitConverter]::ToString($hash.ComputeHash($resultBytes))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
 $summary.offlineResult=@{jobId=$job.jobId;status=$value.status;sourceSha256=$grant.videoSha256;resultSha256=$resultSHA;durationSeconds=$value.source.durationSeconds;qualityAcceptance=$false}
 $summary.offlineAnalysisWorkSeconds=$analysisWatch.Elapsed.TotalSeconds
 if($analysisWatch.Elapsed.TotalSeconds -ge 120){throw 'Offline inference exceeded120s work bound'}
 $analysisCleanupStarted=$analysisWatch.Elapsed.TotalSeconds
 $remaining=[int][Math]::Min(30,150-$analysisWatch.Elapsed.TotalSeconds)
 if($remaining -lt 1){throw 'No offline cleanup budget remains'}
 Wait-Ready $launcher $remaining
 $postAnalysis=Snapshot $controller
 $postAnalysis+=@(Get-CimInstance Win32_Process -Filter ('ProcessId='+$launcher.Id)|Select-Object ProcessId,ParentProcessId,CreationDate,Name)
 $summary.postAnalysisHiddenConsoleBrokers=@(Confirm-ConsoleTopology $postAnalysis $controller)
 $owned+=$postAnalysis
 $jobsRoot=Join-Path $userState 'jobs'
 $saved=@(Get-ChildItem -LiteralPath $jobsRoot -Recurse -File|ForEach-Object{@{path=$_.FullName;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}})
 if($saved.Count -eq 0 -or $saved.Count -gt 1024){throw 'Persisted offline job file inventory missing/unbounded'}
 if(-not $launcher.CloseMainWindow()){throw 'Cannot request GUI shutdown'}
 $remaining=[int][Math]::Min(15,[Math]::Min(150-$analysisWatch.Elapsed.TotalSeconds,30-($analysisWatch.Elapsed.TotalSeconds-$analysisCleanupStarted)))
 if($remaining -lt 1 -or -not $launcher.WaitForExit(1000*$remaining)){throw 'GUI cooperative shutdown exceeded remaining offline cleanup budget'}
 $summary.guiExitCode=$launcher.ExitCode
 if($launcher.ExitCode -ne 0){throw 'GUI cooperative shutdown failed'}
 Require-Gone $owned
 $summary.offlineAnalysisWholeSeconds=$analysisWatch.Elapsed.TotalSeconds
 $summary.offlineAnalysisCleanupSeconds=$analysisWatch.Elapsed.TotalSeconds-$analysisCleanupStarted
 if($summary.offlineAnalysisCleanupSeconds -gt 30){throw 'Offline cleanup exceeds30s bound'}
 if($analysisWatch.Elapsed.TotalSeconds -gt 150){throw 'Offline inference and cleanup exceed150s whole bound'}
 $summary.cooperativeOwnedTreeStopped=$true
 Save-LauncherEvidence 'first-launch-stopped'
 $launcher.Dispose();$launcher=$null

 $launcher=Start-Process -FilePath (Join-Path $installed 'FS_elem.exe') -WorkingDirectory $installed -PassThru
 Wait-Ready $launcher
 $restored=Invoke-WebRequest ($jobUrl+'/result') -TimeoutSec 3 -NoProxy
 $hash=[Security.Cryptography.SHA256]::Create()
 try{$restoredSHA=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$restored.Content)))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
 if($restoredSHA -ne $resultSHA){throw 'Relaunch did not preserve the existing offline analysis result'}
 $summary.relaunchResultPreserved=$true
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
 foreach($record in $saved){
  if(-not(Test-Path -LiteralPath $record.path -PathType Leaf) -or (Get-Item -LiteralPath $record.path).Length -ne $record.bytes -or (Get-FileHash -LiteralPath $record.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.sha256){throw 'Uninstall changed a persisted offline analysis file'}
 }
 $summary.offlineResultFilesPreserved=$true
 $summary.userDataPreserved=$true
 if($summary.nonLoopbackNetworkPhysicallyDenied -ne $true -or $summary.relaunchResultPreserved -ne $true -or $summary.offlineResultFilesPreserved -ne $true){throw 'Offline native evidence incomplete'}
 $summary.status='passed'
}catch{
 $summary.status='failed';$summary.firstFailure=$_.Exception.Message
 throw
}finally{
 $cleanupConfirmed=$true
 if($launcher){
  try{
   $failureOwned=@()
   if(-not $launcher.HasExited){
    # Only current direct app children recorded by this launcher's log are roots;
    # the user's browser launched by ShellExecute is outside the application Job.
    $events=@()
    if(Test-Path -LiteralPath $logPath){$events=@(Get-Content -LiteralPath $logPath -Encoding UTF8|ForEach-Object{try{$entry=$_|ConvertFrom-Json;if($entry.type -eq 'child-start'){$entry}}catch{}})}
    $direct=@(Get-CimInstance Win32_Process -Filter ("ParentProcessId="+$launcher.Id)|Where-Object{$_.CreationDate.ToUniversalTime() -ge $launcher.StartTime.ToUniversalTime()})
    foreach($record in $direct){
     if(@($events|Where-Object{[int]$_.pid -eq [int]$record.ProcessId}).Count -gt 0){$failureOwned+=Snapshot $record.ProcessId}
    }
    $failureOwned+=@(Get-CimInstance Win32_Process -Filter ("ProcessId="+$launcher.Id)|Select-Object ProcessId,ParentProcessId,CreationDate,Name)
    if($jobUrl -and $job.state -notin @('succeeded','failed','cancelled')){
     try{[void](Invoke-WebRequest $jobUrl -Method DELETE -TimeoutSec 2 -NoProxy -SkipHttpErrorCheck)}catch{}
    }
    [void]$launcher.CloseMainWindow()
    if(-not $launcher.WaitForExit(10000)){
     $launcher.Kill()
     if(-not $launcher.WaitForExit(10000)){throw 'Retained GUI termination unresolved'}
    }
   }
   if($failureOwned.Count -gt 0){Require-Gone $failureOwned}
   if($owned){Require-Gone $owned}
   if($force){Require-Gone $force}
   $summary.finalOwnedClosureConfirmed=$true
  }catch{
   $cleanupConfirmed=$false;$summary.status='failed';$summary.finalOwnedClosureConfirmed=$false
   if(-not $summary.firstFailure){$summary.firstFailure=$_.Exception.Message}
  }
  if($launcher.HasExited){$launcher.Dispose()}
 }
 if(Test-Path -LiteralPath $logPath){Copy-Item -LiteralPath $logPath -Destination (Join-Path $Logs 'installed-launcher.log')}
 try{
  if($firewallStarted){
   if(-not $cleanupConfirmed){throw 'Keep offline deny rules until original owned closure is confirmed by Root'}
   Remove-NetFirewallRule -Group $firewallGroup -ErrorAction SilentlyContinue
   if(@(Get-NetFirewallRule -ErrorAction Stop|Where-Object{$_.Group -eq $firewallGroup}).Count -ne 0){throw 'Offline-check firewall cleanup unresolved'}
  }
  $summary.offlineFirewallRulesRemoved=$true
  if($firewallProfilesTouched){
   if(-not $cleanupConfirmed){throw 'Retain deny/profile enforcement until Root confirms original closure'}
   foreach($profile in $firewallPriorPersistent){
    if($profile.Name -in $firewallChangedNames){Set-NetFirewallProfile -PolicyStore PersistentStore -Name $profile.Name -Enabled $profile.Enabled -ErrorAction Stop}
   }
   $restored=@(Get-NetFirewallProfile -PolicyStore PersistentStore|Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction)
   foreach($before in $firewallPriorPersistent){
    $after=@($restored|Where-Object{$_.Name -eq $before.Name})
    if($after.Count -ne 1 -or $after[0].Enabled -ne $before.Enabled -or $after[0].DefaultInboundAction -ne $before.DefaultInboundAction -or $after[0].DefaultOutboundAction -ne $before.DefaultOutboundAction){throw 'Exact prior persistent firewall state was not restored'}
   }
   $restoredActive=@(Get-NetFirewallProfile -PolicyStore ActiveStore)
   foreach($before in $firewallPriorActive){
    $after=@($restoredActive|Where-Object{$_.Name -eq $before.Name})
    if($after.Count -ne 1 -or $after[0].Enabled -ne $before.Enabled -or $after[0].DefaultOutboundAction -ne $before.DefaultOutboundAction -or $after[0].DefaultInboundAction -ne $before.DefaultInboundAction){throw 'Exact prior effective firewall state was not restored'}
   }
  }
  $summary.firewallPriorStateRestored=$true
 }catch{
  if(-not $summary.firstFailure){$summary.firstFailure=$_.Exception.Message}
  $summary.status='failed';$summary.offlineFirewallRulesRemoved=$false;$summary.firewallPriorStateRestored=$false
 }
 [IO.File]::WriteAllText((Join-Path $WorkRoot 'native-install-check.json'),($summary|ConvertTo-Json -Depth 15),[Text.UTF8Encoding]::new($false))
 if($summary.offlineFirewallRulesRemoved -ne $true -or $summary.firewallPriorStateRestored -ne $true){throw 'Offline firewall cleanup/prior-state restoration not confirmed'}
}
