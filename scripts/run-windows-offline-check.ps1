# Root-owned native-check lease. SOURCE ONLY until a distinct pinned Root grant.
# The job bounds the retained checker and actual inherited members. Shell-brokered
# app processes may be outside it; checker app-RSS/owned-tree evidence is separate.
param(
 [Parameter(Mandatory=$true)][string]$NativeCheck,
 [Parameter(Mandatory=$true)][string]$Installer,
 [Parameter(Mandatory=$true)][string]$WorkRoot,
 [Parameter(Mandatory=$true)][string]$Logs,
 [Parameter(Mandatory=$true)][string]$RootGrant,
 [Parameter(Mandatory=$true)][string]$RootGrantSha256,
 [Parameter(Mandatory=$true)][string]$OfflineVideo
)
$supervisorOrigin=[Diagnostics.Stopwatch]::GetTimestamp()
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$result=$null
$outputRoot=$null
$resultPath=$null
$firstFailure=$null
try{
 if($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7 -or -not $IsWindows -or -not [Environment]::Is64BitProcess){throw 'Native supervisor requires64-bit Windows PowerShell Core7+'}
 $WorkRoot=[IO.Path]::GetFullPath($WorkRoot)
 if(-not(Test-Path -LiteralPath $WorkRoot -PathType Container)){throw 'Existing dedicated native WorkRoot required'}
 $outputRoot=Join-Path $WorkRoot 'offline-supervisor'
 if(Test-Path -LiteralPath $outputRoot){throw 'Supervisor output already exists; no replay/overwrite'}
 [void][IO.Directory]::CreateDirectory($outputRoot)
 $resultPath=Join-Path $outputRoot 'final.json'
 if($RootGrantSha256 -cnotmatch '^[0-9a-f]{64}$' -or -not(Test-Path -LiteralPath $RootGrant -PathType Leaf) -or (Get-Item -LiteralPath $RootGrant).Length -gt 65536){throw 'Distinct bounded Root grant missing'}
 if((Get-FileHash -LiteralPath $RootGrant -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RootGrantSha256){throw 'Root grant digest changed'}
 $grant=Get-Content -LiteralPath $RootGrant -Raw -Encoding UTF8|ConvertFrom-Json
 if($grant.actualAuthorization -isnot [bool] -or $grant.actualAuthorization -ne $true -or $grant.kind -isnot [string] -or $grant.kind -cne 'ROOT_ADMITTED_GENERATED_OFFLINE_NATIVE_GRANT'){throw 'Only an actual generated Root authorization admits the native scenario'}
 if($grant.sourceCommit -isnot [string] -or $grant.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or $grant.sourceCommit -cne $env:GITHUB_SHA){throw 'Root grant commit must match actual current GitHub Source commit'}
 if($grant.sourceRef -isnot [string] -or $grant.sourceRef -cne 'refs/heads/release/v0.2.5' -or $grant.sourceRef -cne $env:GITHUB_REF){throw 'Root grant must match the exact admitted release branch'}
 foreach($binding in @(@('runId','GITHUB_RUN_ID'),@('runAttempt','GITHUB_RUN_ATTEMPT'))){
  $value=$grant.($binding[0]);$actual=[Environment]::GetEnvironmentVariable($binding[1])
  if($value -isnot [string] -or $value -cnotmatch '^[1-9][0-9]*$' -or $value -cne $actual){throw 'Root grant run identity must match current nonempty GitHub run/attempt'}
 }
 if($grant.scope -cne 'windows-offline-native-check-v025' -or $grant.allowInstall -ne $true -or $grant.allowGUI -ne $true -or $grant.allowNN -ne $true -or $grant.publicVideo -ne $true){throw 'Root grant does not admit this native scenario'}
 if($grant.supervisorSha256 -cnotmatch '^[0-9a-f]{64}$' -or (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $grant.supervisorSha256){throw 'Root supervisor Source digest missing/changed'}
 if($grant.nativeCheckSha256 -cnotmatch '^[0-9a-f]{64}$' -or -not(Test-Path -LiteralPath $NativeCheck -PathType Leaf) -or (Get-FileHash -LiteralPath $NativeCheck -Algorithm SHA256).Hash.ToLowerInvariant() -cne $grant.nativeCheckSha256){throw 'Root native checker Source digest missing/changed'}
 if($grant.supervisorWholeSeconds -ne 630 -or $grant.supervisorWorkSeconds -ne 600 -or $grant.supervisorCleanupSeconds -ne 30 -or $grant.supervisorJobCommittedBytes -ne 4294967296 -or $grant.supervisorSavedOutputBytes -ne 262144 -or $grant.retry -ne 0){throw 'Root supervisor lease differs from630whole/600work/30cleanup/4GiB/256KiB/retry0'}
 foreach($path in $NativeCheck,$Installer,$RootGrant,$OfflineVideo){
  $item=Get-Item -LiteralPath $path -ErrorAction Stop
  if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Native inputs must be existing non-reparse regular files'}
 }
 $Logs=[IO.Path]::GetFullPath($Logs)
 if(-not(Test-Path -LiteralPath $Logs -PathType Container) -or -not $Logs.StartsWith($WorkRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Dedicated native Logs directory must already exist inside WorkRoot'}

 Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;

public sealed class OfflineNativeResult {
 public string status="failed", firstFailure, jobName, checkerCreationFileTime;
 public int? checkerPid, checkerExitCode;
 public bool childStarted, assignedBeforeGate, gateReleased, retainedWaitCompleted;
 public bool jobTerminationRequested, jobHandleClosed, retainedProcessDisposed;
 public bool stdoutComplete, stderrComplete;
 public uint? finalActiveJobProcesses, totalJobProcesses;
 public string kernelPeakJobCommittedBytes;
 public long observedStreamBytes, savedStreamBytes;
 public double elapsedSeconds;
 public string[] childArgv;
 public List<string> cleanupErrors=new List<string>();
 public List<uint> sampledJobMemberPids=new List<uint>();
 public int jobMemberSamples;
 public uint maximumAssignedProcessSample;
 public bool sampledJobMemberPidsTruncated;
 public string resourceQualification="4GiB hard aggregate committed memory applies only to checker and actual Job members; app working-set samples/escaped Shell children are separate, continuous whole-app coverage unknown";
}

public static class OfflineNativeController {
 const uint JOB_OBJECT_LIMIT_JOB_MEMORY=0x200, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000;
 const int StreamBudget=196608; // Reserve64KiB for final.json inside256KiB saved-output cap.
 sealed class JobHandle:SafeHandleZeroOrMinusOneIsInvalid {
  public bool CloseSucceeded;
  public JobHandle():base(true){}
  protected override bool ReleaseHandle(){CloseSucceeded=CloseHandle(handle);return CloseSucceeded;}
 }
 [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
  public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
  public uint LimitFlags;
  public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
  public uint ActiveProcessLimit;
  public UIntPtr Affinity;
  public uint PriorityClass, SchedulingClass;
 }
 [StructLayout(LayoutKind.Sequential)] struct IoCounters {
  public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount;
 }
 [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
  public BasicLimits BasicLimitInformation;
  public IoCounters IoInfo;
  public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
 }
 [StructLayout(LayoutKind.Sequential)] struct Accounting {
  public long TotalUserTime, TotalKernelTime, ThisPeriodTotalUserTime, ThisPeriodTotalKernelTime;
  public uint TotalPageFaultCount, TotalProcesses, ActiveProcesses, TotalTerminatedProcesses;
 }
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
 static extern JobHandle CreateJobObject(IntPtr attributes,string name);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(JobHandle job,int kind,ref ExtendedLimits limits,uint length);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(JobHandle job,IntPtr process);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool IsProcessInJob(IntPtr process,JobHandle job,out bool member);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool TerminateJobObject(JobHandle job,uint code);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetProcessTimes(IntPtr process,out ulong creation,out ulong exit,out ulong kernel,out ulong user);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool QueryInformationJobObject(JobHandle job,int kind,IntPtr buffer,uint length,out uint returned);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool QueryInformationJobObject(JobHandle job,int kind,out Accounting info,uint length,out uint returned);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool QueryInformationJobObject(JobHandle job,int kind,out ExtendedLimits info,uint length,out uint returned);

 sealed class Capture {
  public readonly object Sync=new object();
  public readonly MemoryStream Out=new MemoryStream(), Err=new MemoryStream();
  public long Observed, Saved;
  public bool Overflow;
  public string ReadFailure;
  public async Task Pump(Stream stream,MemoryStream target) {
   byte[] buffer=new byte[8192];
   try{
    for(;;){
     int count=await stream.ReadAsync(buffer,0,buffer.Length).ConfigureAwait(false);
     if(count==0)return;
     lock(Sync){
      Observed+=count;
      int keep=(int)Math.Min(count,Math.Max(0,StreamBudget-Saved));
      if(keep>0){target.Write(buffer,0,keep);Saved+=keep;}
      if(keep!=count)Overflow=true;
     }
    }
   }catch(Exception e){lock(Sync){if(ReadFailure==null)ReadFailure=Short(e.Message);}}
  }
 }
 static string Short(string text){return text==null?null:(text.Length<=2048?text:text.Substring(0,2048));}
 static void Fail(OfflineNativeResult result,string text){if(result.firstFailure==null)result.firstFailure=Short(text);}
 static void CleanupError(OfflineNativeResult result,string text){if(result.cleanupErrors.Count<8)result.cleanupErrors.Add(Short(text));Fail(result,text);}
 static Exception NativeError(string label){return new Win32Exception(Marshal.GetLastWin32Error(),label);}
 static double Elapsed(long origin){return (Stopwatch.GetTimestamp()-origin)/(double)Stopwatch.Frequency;}
 static int RemainingMs(long origin,double deadline){return (int)Math.Max(0,Math.Min(1000,(deadline-Elapsed(origin))*1000));}
 static Accounting Account(JobHandle job){Accounting value;uint size;if(!QueryInformationJobObject(job,1,out value,(uint)Marshal.SizeOf<Accounting>(),out size))throw NativeError("Query Job accounting");return value;}
 static void SampleMembers(JobHandle job,OfflineNativeResult result){
  // A bounded sampled PID list is evidence of members seen, not process identity,
  // continuous ancestry, or proof that all Shell-brokered app children joined.
  IntPtr buffer=Marshal.AllocHGlobal(8+1024*IntPtr.Size);
  try{
   uint returned;
   if(!QueryInformationJobObject(job,3,buffer,(uint)(8+1024*IntPtr.Size),out returned))throw NativeError("Query bounded Job member list");
   uint assigned=unchecked((uint)Marshal.ReadInt32(buffer,0));
   result.jobMemberSamples++;
   result.maximumAssignedProcessSample=Math.Max(result.maximumAssignedProcessSample,assigned);
   int count=Marshal.ReadInt32(buffer,4);
   if(count<0||count>1024)throw new InvalidOperationException("Job member list exceeded1024 entries");
   for(int i=0;i<count;i++){
    long raw=IntPtr.Size==8?Marshal.ReadInt64(buffer,8+i*8):unchecked((uint)Marshal.ReadInt32(buffer,8+i*4));
    if(raw<=0||raw>UInt32.MaxValue)throw new InvalidOperationException("Invalid native Job PID");
    uint pid=(uint)raw;
    if(!result.sampledJobMemberPids.Contains(pid)){
     if(result.sampledJobMemberPids.Count<128)result.sampledJobMemberPids.Add(pid);
     else result.sampledJobMemberPidsTruncated=true;
    }
   }
  }finally{Marshal.FreeHGlobal(buffer);}
 }
 public static OfflineNativeResult Run(string pwsh,string script,string installer,string workRoot,string logs,string grant,string grantSha,string video,string outputRoot,long origin){
  var result=new OfflineNativeResult();
  JobHandle job=null;Process child=null;Capture capture=new Capture();Task stdout=null,stderr=null;
  bool exited=false,terminated=false;
  try{
   if(Elapsed(origin)>=600)throw new TimeoutException("Original600s work deadline already exhausted before controller admission");
   result.jobName="Local\\FS_elem_offline_supervisor_"+Guid.NewGuid().ToString("N");
   job=CreateJobObject(IntPtr.Zero,result.jobName);
   if(job.IsInvalid)throw NativeError("Create own native Job");
   var limits=new ExtendedLimits();
   limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_JOB_MEMORY|JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
   limits.JobMemoryLimit=new UIntPtr(4294967296UL);
   if(!SetInformationJobObject(job,9,ref limits,(uint)Marshal.SizeOf<ExtendedLimits>()))throw NativeError("Set4GiB aggregate committed-memory/KILL_ON_JOB_CLOSE Job limits");

   // Fixed wrapper: user paths are only environment values, never interpolated
   // into PowerShell source. Target script cannot run before the single gate byte.
   string wrapper="$ErrorActionPreference='Stop'; try { if([Console]::Read() -ne 71){exit 78}; & $env:FS_ELEM_NATIVE_CHECK -Installer $env:FS_ELEM_NATIVE_INSTALLER -WorkRoot $env:FS_ELEM_NATIVE_WORK -Logs $env:FS_ELEM_NATIVE_LOGS -RootGrant $env:FS_ELEM_NATIVE_GRANT -RootGrantSha256 $env:FS_ELEM_NATIVE_GRANT_SHA -OfflineVideo $env:FS_ELEM_NATIVE_VIDEO; if(-not $?){exit 1}; exit 0 } catch { [Console]::Error.WriteLine($_.Exception.ToString()); exit 1 }";
   string encoded=Convert.ToBase64String(Encoding.Unicode.GetBytes(wrapper));
   var start=new ProcessStartInfo(pwsh);
   start.UseShellExecute=false;start.CreateNoWindow=true;
   start.RedirectStandardInput=true;start.RedirectStandardOutput=true;start.RedirectStandardError=true;
   start.WorkingDirectory=workRoot;
   string[] args={"-NoLogo","-NoProfile","-NonInteractive","-EncodedCommand",encoded};
   foreach(string arg in args)start.ArgumentList.Add(arg);
   result.childArgv=new string[]{pwsh,args[0],args[1],args[2],args[3],args[4]};
   start.Environment["FS_ELEM_NATIVE_CHECK"]=script;
   start.Environment["FS_ELEM_NATIVE_INSTALLER"]=installer;
   start.Environment["FS_ELEM_NATIVE_WORK"]=workRoot;
   start.Environment["FS_ELEM_NATIVE_LOGS"]=logs;
   start.Environment["FS_ELEM_NATIVE_GRANT"]=grant;
   start.Environment["FS_ELEM_NATIVE_GRANT_SHA"]=grantSha;
   start.Environment["FS_ELEM_NATIVE_VIDEO"]=video;
   start.Environment["FS_ELEM_NATIVE_SUPERVISOR_JOB"]=result.jobName;
   child=new Process();child.StartInfo=start;
   if(!child.Start())throw new InvalidOperationException("Retained checker process did not start");
   result.childStarted=true;result.checkerPid=child.Id;
   ulong creation,exitTime,kernel,user;
   if(!GetProcessTimes(child.Handle,out creation,out exitTime,out kernel,out user))throw NativeError("Read retained checker creation identity");
   result.checkerCreationFileTime=creation.ToString(CultureInfo.InvariantCulture);
   stdout=capture.Pump(child.StandardOutput.BaseStream,capture.Out);
   stderr=capture.Pump(child.StandardError.BaseStream,capture.Err);
   if(!AssignProcessToJobObject(job,child.Handle))throw NativeError("Assign retained checker before gate");
   bool member;
   if(!IsProcessInJob(child.Handle,job,out member)||!member)throw NativeError("Retained checker Job membership unresolved");
   result.assignedBeforeGate=true;
   SampleMembers(job,result);
   if(Elapsed(origin)>=600)throw new TimeoutException("Original600s work deadline exhausted before gate");
   child.StandardInput.BaseStream.WriteByte(71);child.StandardInput.BaseStream.Flush();
   result.gateReleased=true;child.StandardInput.Close();

   while(!child.WaitForExit(100)){
    SampleMembers(job,result);
    lock(capture.Sync){
     if(capture.Overflow)throw new InvalidOperationException("Combined native child streams exceeded192KiB retention budget");
     if(capture.ReadFailure!=null)throw new IOException("Native pipe read failed: "+capture.ReadFailure);
    }
    if(Elapsed(origin)>=600)throw new TimeoutException("Original600s complete-check work deadline exceeded");
   }
   if(Elapsed(origin)>600)throw new TimeoutException("Native checker terminal exit arrived after original600s work deadline");
   exited=true;result.retainedWaitCompleted=true;result.checkerExitCode=child.ExitCode;
   if(child.ExitCode!=0)throw new InvalidOperationException("Retained native checker exited "+child.ExitCode);
   if(Account(job).ActiveProcesses!=0)throw new InvalidOperationException("Native checker exited with own Job members still active");
  }catch(Exception e){Fail(result,e.Message);}
  finally{
   // Cleanup shares the original entry origin: never a renewed30s horizon.
   if(child!=null){
    try{child.StandardInput.Close();}catch(Exception e){CleanupError(result,"Close checker gate pipe: "+e.Message);}
    try{if(!exited)exited=child.WaitForExit(0);}catch(Exception e){CleanupError(result,"Observe retained checker: "+e.Message);}
   }
   if(job!=null&&!job.IsInvalid){
    try{
     if(Account(job).ActiveProcesses!=0){
      result.jobTerminationRequested=true;
      if(!TerminateJobObject(job,1))throw NativeError("Terminate only own Job");
      terminated=true;
      if(result.firstFailure==null)Fail(result,"Forced own Job closure required");
     }
    }catch(Exception e){CleanupError(result,e.Message);}
   }
   // If admission failed before assignment, only the retained gated pwsh exists.
   // Kill that exact retained handle, never a PID search or foreign process tree.
   if(child!=null&&!result.assignedBeforeGate&&!exited){
    try{child.Kill();}catch(Exception e){CleanupError(result,"Stop unadmitted retained gated checker: "+e.Message);}
   }
   while(Elapsed(origin)<630){
    bool processDone=child==null||exited;
    if(child!=null&&!exited){
     try{exited=child.WaitForExit(Math.Min(100,RemainingMs(origin,630)));processDone=exited;}catch(Exception e){CleanupError(result,"Retained checker wait: "+e.Message);break;}
    }
    bool jobDone=job==null||job.IsInvalid;
    if(job!=null&&!job.IsInvalid){
     try{var state=Account(job);result.finalActiveJobProcesses=state.ActiveProcesses;result.totalJobProcesses=state.TotalProcesses;jobDone=state.ActiveProcesses==0;}catch(Exception e){CleanupError(result,e.Message);break;}
    }
    bool streamsDone=(stdout==null||stdout.IsCompleted)&&(stderr==null||stderr.IsCompleted);
    if(processDone&&jobDone&&streamsDone)break;
    Thread.Sleep(Math.Min(50,RemainingMs(origin,630)));
   }
   if(child!=null){
    try{
     result.retainedWaitCompleted=exited;
     if(exited)result.checkerExitCode=child.ExitCode;
     else CleanupError(result,"Original630s retained-checker termination unresolved");
    }catch(Exception e){CleanupError(result,"Retained checker terminal status: "+e.Message);}
   }
   result.stdoutComplete=stdout==null||stdout.IsCompleted;
   result.stderrComplete=stderr==null||stderr.IsCompleted;
   if(!result.stdoutComplete||!result.stderrComplete)CleanupError(result,"Original630s native stream drain unresolved");
   if(job!=null&&!job.IsInvalid){
    try{
     var state=Account(job);result.finalActiveJobProcesses=state.ActiveProcesses;result.totalJobProcesses=state.TotalProcesses;
     if(state.ActiveProcesses!=0)CleanupError(result,"Original own Job active-process count is not zero");
     ExtendedLimits limits;uint bytes;
     if(!QueryInformationJobObject(job,9,out limits,(uint)Marshal.SizeOf<ExtendedLimits>(),out bytes))throw NativeError("Read kernel Job committed-memory peak");
     result.kernelPeakJobCommittedBytes=limits.PeakJobMemoryUsed.ToUInt64().ToString(CultureInfo.InvariantCulture);
     if(limits.PeakJobMemoryUsed.ToUInt64()>4294967296UL)CleanupError(result,"Kernel own Job committed-memory peak exceeded4GiB");
    }catch(Exception e){CleanupError(result,e.Message);}
    try{job.Dispose();result.jobHandleClosed=job.IsClosed&&job.CloseSucceeded;if(!result.jobHandleClosed)CleanupError(result,"Close own Job native handle failed");}catch(Exception e){CleanupError(result,"Close own Job handle: "+e.Message);}
   }
   if(child!=null){
    try{child.StandardOutput.Dispose();child.StandardError.Dispose();child.Dispose();result.retainedProcessDisposed=true;}catch(Exception e){CleanupError(result,"Dispose retained checker/pipes: "+e.Message);}
   }
   lock(capture.Sync){
    result.observedStreamBytes=capture.Observed;result.savedStreamBytes=capture.Saved;
    if(capture.Overflow)Fail(result,"Combined native child stream retention overflow");
    if(capture.ReadFailure!=null)Fail(result,"Native pipe read failure: "+capture.ReadFailure);
    try{
     File.WriteAllBytes(Path.Combine(outputRoot,"stdout.bin"),capture.Out.ToArray());
     File.WriteAllBytes(Path.Combine(outputRoot,"stderr.bin"),capture.Err.ToArray());
    }catch(Exception e){CleanupError(result,"Save bounded native streams: "+e.Message);}
   }
   result.elapsedSeconds=Elapsed(origin);
   if(result.elapsedSeconds>630)Fail(result,"Original630s supervisor lease exceeded");
   if(terminated)Fail(result,"Forced own Job termination does not establish checker finally/escaped-Shell cleanup");
   if(result.firstFailure==null&&result.gateReleased&&result.retainedWaitCompleted&&result.checkerExitCode==0&&result.finalActiveJobProcesses==0&&result.jobHandleClosed&&result.retainedProcessDisposed&&result.stdoutComplete&&result.stderrComplete)result.status="passed";
  }
  return result;
 }
}
'@
 $result=[OfflineNativeController]::Run((Join-Path $PSHOME 'pwsh.exe'),[IO.Path]::GetFullPath($NativeCheck),[IO.Path]::GetFullPath($Installer),$WorkRoot,[IO.Path]::GetFullPath($Logs),[IO.Path]::GetFullPath($RootGrant),$RootGrantSha256,[IO.Path]::GetFullPath($OfflineVideo),$outputRoot,$supervisorOrigin)
}catch{
 $firstFailure=$_.Exception.Message
 if($firstFailure.Length -gt 2048){$firstFailure=$firstFailure.Substring(0,2048)}
 $result=[ordered]@{status='failed';firstFailure=$firstFailure;childStarted=$false;gateReleased=$false;retainedWaitCompleted=$false;nativeEvidence='No target admission after Source/bootstrap failure'}
}
$receipt=[ordered]@{
 schema='fs-elem-windows-offline-supervisor-v1';rootGrantSha256=$RootGrantSha256;
 wholeSeconds=630;workSeconds=600;cleanupSeconds=30;jobCommittedBytes='4294967296';
 capturedStreamsCapBytes=196608;finalReceiptCapBytes=65536;savedOutputCapBytes=262144;
 sampledMemberLedgerMaxPids=128;sampledMembersAreCompleteHistory=$false;
 entryOriginTicks=$supervisorOrigin.ToString([Globalization.CultureInfo]::InvariantCulture);
 stopwatchFrequency=[Diagnostics.Stopwatch]::Frequency.ToString([Globalization.CultureInfo]::InvariantCulture);
 admission=[ordered]@{kind=$grant.kind;actualAuthorization=$grant.actualAuthorization;sourceCommit=$grant.sourceCommit;sourceRef=$grant.sourceRef;runId=$grant.runId;runAttempt=$grant.runAttempt}
 result=$result
}
try{
 $json=$receipt|ConvertTo-Json -Depth 10 -Compress
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes($json)
 if($bytes.Length -gt 65536){throw 'Final supervisor receipt exceeded reserved64KiB'}
 if($resultPath){[IO.File]::WriteAllBytes($resultPath,$bytes)}
 [Console]::Out.WriteLine($json)
}catch{
 [Console]::Error.WriteLine('Supervisor terminal receipt unavailable: '+$_.Exception.Message)
 exit 1
}
if($result.status -cne 'passed'){exit 1}
