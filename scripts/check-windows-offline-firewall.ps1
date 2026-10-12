# Necessary preflight before the offline payload build. No external network.
param([Parameter(Mandatory=$true)][string]$Output)
$origin=[Diagnostics.Stopwatch]::GetTimestamp()
$frequency=[Diagnostics.Stopwatch]::Frequency
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$ruleName='FS_elem-offline-preflight-'+[Guid]::NewGuid().ToString('N')
$ruleAttempted=$false
$listener=$null;$client=$null;$server=$null;$self=$null;$accept=$null
$summary=[ordered]@{
 schema='fs-elem-windows-offline-firewall-preflight-v1';status='failed';firstFailure=$null;
 wholeSeconds=20;workSeconds=15;cleanupSeconds=5;entryOriginTicks=$origin.ToString();
 stopwatchFrequency=$frequency.ToString();NN=0;externalNetworkRequests=0;
 ownedRuleName=$ruleName;ownedRuleGroup=$ruleName;ruleCreated=$false;
 effectiveProgramBlockAny=$false;classicWin32TcpLoopbackHandshake=$false;
 ownRuleGone=$false;socketsClosed=$false;cleanupErrors=@();
 qualification='Only current pwsh.exe classic Win32 TCP-loopback tested; installed app remains a separate native check. Synchronous NetSecurity calls are not independently interruptible here; outer CI timeout remains separate.'
}
function Elapsed {return ([Diagnostics.Stopwatch]::GetTimestamp()-$origin)/[double]$frequency}
function Work-Remaining {
 $remaining=15-(Elapsed)
 if($remaining -le 0){throw 'Original15s firewall preflight work deadline exceeded'}
 return [int][Math]::Max(1,[Math]::Floor($remaining*1000))
}
function Await-Work($Task){
 if(-not $Task.Wait((Work-Remaining))){throw 'Original15s firewall TCP task deadline exceeded'}
 [void]$Task.GetAwaiter().GetResult()
 [void](Work-Remaining)
}
function Keep-Failure([string]$Text){
 if(-not $summary.firstFailure){$summary.firstFailure=$Text.Substring(0,[Math]::Min(2048,$Text.Length))}
}
function Cleanup-Failure([string]$Text){
 Keep-Failure $Text
 if($summary.cleanupErrors.Count -lt 4){$summary.cleanupErrors+=($Text.Substring(0,[Math]::Min(2048,$Text.Length)))}
}
try{
 if(-not $IsWindows -or $PSVersionTable.PSEdition -ne 'Core'){throw 'Firewall preflight requires native Windows PowerShell Core'}
 $Output=[IO.Path]::GetFullPath($Output)
 if(Test-Path -LiteralPath $Output){throw 'Fresh preflight output required; no overwrite/replay'}
 if(-not(Test-Path -LiteralPath ([IO.Path]::GetDirectoryName($Output)) -PathType Container)){throw 'Existing dedicated output directory required'}
 $self=[Diagnostics.Process]::GetCurrentProcess()
 $program=[IO.Path]::GetFullPath($self.MainModule.FileName)
 $programFile=Get-Item -LiteralPath $program -ErrorAction Stop
 if($programFile.PSIsContainer -or ($programFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -or [IO.Path]::GetFileName($program) -ine 'pwsh.exe'){throw 'Current canonical pwsh executable unresolved'}
 $summary.program=$program;$summary.processId=$self.Id
 $summary.processCreationFileTime=$self.StartTime.ToFileTimeUtc().ToString()
 [void](Work-Remaining)
 $profiles=@(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)
 if($profiles.Count -ne 3 -or @($profiles|Where-Object{$_.Enabled.ToString() -cne 'True'}).Count -ne 0){throw 'All existing active firewall profiles must already be enabled'}
 $summary.profiles=@($profiles|ForEach-Object{@{name=$_.Name.ToString();enabled=$_.Enabled.ToString()}})
 [void](Work-Remaining)
 if((Get-Service MpsSvc -ErrorAction Stop).Status -ne 'Running'){throw 'Existing Windows Firewall service must already be running'}
 [void](Work-Remaining)
 $ruleAttempted=$true
 [void](New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Group $ruleName -PolicyStore PersistentStore -Direction Outbound -Action Block -Program $program -RemoteAddress Any -Profile Any -Enabled True -ErrorAction Stop)
 $summary.ruleCreated=$true
 [void](Work-Remaining)
 $active=@(Get-NetFirewallRule -Name $ruleName -PolicyStore ActiveStore -ErrorAction Stop)
 if($active.Count -ne 1 -or $active[0].Name -cne $ruleName -or $active[0].Group -cne $ruleName -or $active[0].Action.ToString() -cne 'Block' -or $active[0].Direction.ToString() -cne 'Outbound' -or $active[0].Enabled.ToString() -cne 'True' -or $active[0].Profile.ToString() -cne 'Any'){throw 'Own active Block/Outbound/Enabled/Any-profile rule binding failed'}
 $application=@(Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $active[0] -ErrorAction Stop)
 $address=@(Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $active[0] -ErrorAction Stop)
 [void](Work-Remaining)
 $remote=@($address[0].RemoteAddress)
 if($application.Count -ne 1 -or -not [string]::Equals([IO.Path]::GetFullPath($application[0].Program),$program,[StringComparison]::OrdinalIgnoreCase) -or $address.Count -ne 1 -or $remote.Count -ne 1 -or $remote[0] -cne 'Any'){throw 'Own effective program/RemoteAddress Any filter binding failed'}
 $summary.effectiveProgramBlockAny=$true
 $summary.activeRule=@{name=$active[0].Name;group=$active[0].Group;action=$active[0].Action.ToString();direction=$active[0].Direction.ToString();enabled=$active[0].Enabled.ToString();profile=$active[0].Profile.ToString();program=$application[0].Program;remoteAddress=$remote}

 # Real TCP traffic from this exact blocked classic Win32 program. No mocks,
 # external destination, permissive extra allow rule, or profile-default change.
 $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
 $listener.Start()
 $port=([Net.IPEndPoint]$listener.LocalEndpoint).Port
 $accept=$listener.AcceptTcpClientAsync()
 $client=[Net.Sockets.TcpClient]::new([Net.Sockets.AddressFamily]::InterNetwork)
 Await-Work ($client.ConnectAsync([Net.IPAddress]::Loopback,$port))
 Await-Work $accept
 $server=$accept.Result
 $sent=[byte[]]@(71);$received=[byte[]]@(0)
 Await-Work ($client.GetStream().WriteAsync($sent,0,1))
 $read=$server.GetStream().ReadAsync($received,0,1)
 Await-Work $read
 if($read.Result -ne 1 -or $received[0] -ne 71){throw 'Real loopback request-byte mismatch'}
 $sent[0]=82;$received[0]=0
 Await-Work ($server.GetStream().WriteAsync($sent,0,1))
 $read=$client.GetStream().ReadAsync($received,0,1)
 Await-Work $read
 if($read.Result -ne 1 -or $received[0] -ne 82){throw 'Real loopback response-byte mismatch'}
 $summary.classicWin32TcpLoopbackHandshake=$true
 $summary.loopbackPort=$port;$summary.handshake='client71/server82';$summary.workElapsedSeconds=Elapsed
 [void](Work-Remaining)
}catch{Keep-Failure $_.Exception.Message}
finally{
 $cleanupStarted=Elapsed
 $cleanupDeadline=[Math]::Min(20,$cleanupStarted+5)
 if($listener){try{$listener.Stop()}catch{Cleanup-Failure $_.Exception.Message}}
 # Stop cancels a pending accept. If it already returned a socket before an
 # earlier failed await, retain that exact result and dispose it as well.
 if($accept -and -not $accept.IsCompleted){
  $remaining=[int][Math]::Max(0,[Math]::Floor(($cleanupDeadline-(Elapsed))*1000))
  if($remaining -gt 0){try{[void]$accept.Wait($remaining)}catch{}}
 }
 if($accept -and $accept.IsCompletedSuccessfully -and -not $server){$server=$accept.Result}
 if($accept -and -not $accept.IsCompleted){Cleanup-Failure 'Owned TCP accept cleanup remains unresolved'}
 foreach($socket in @($server,$client)){
  if($socket){try{$socket.Dispose()}catch{Cleanup-Failure $_.Exception.Message}}
 }
 $summary.socketsClosed=($summary.cleanupErrors.Count -eq 0)
 if($ruleAttempted){
  try{
   # Fresh read-only lookup permits zero rows after a failed creation. Never
   # silence arbitrary lookup errors or delete another name/group's policy.
   $owned=@(Get-NetFirewallRule -PolicyStore PersistentStore -ErrorAction Stop|Where-Object{$_.Name -ceq $ruleName})
   if($owned.Count -gt 1 -or @($owned|Where-Object{$_.Group -cne $ruleName}).Count -ne 0){throw 'Own unique cleanup rule identity unresolved'}
   if($owned.Count -eq 1){Remove-NetFirewallRule -Name $ruleName -PolicyStore PersistentStore -ErrorAction Stop}
   $remainingActive=@(Get-NetFirewallRule -PolicyStore ActiveStore -ErrorAction Stop|Where-Object{$_.Name -ceq $ruleName -or $_.Group -ceq $ruleName})
   $remainingStored=@(Get-NetFirewallRule -PolicyStore PersistentStore -ErrorAction Stop|Where-Object{$_.Name -ceq $ruleName -or $_.Group -ceq $ruleName})
   if($remainingActive.Count -ne 0 -or $remainingStored.Count -ne 0){throw 'Own firewall rule cleanup not confirmed by fresh active/stored policy'}
   $summary.ownRuleGone=$true
  }catch{Cleanup-Failure $_.Exception.Message}
 }
 if($self){
  try{
   $self.Refresh();$summary.processPeakWorkingSetBytes=$self.PeakWorkingSet64.ToString()
   if($self.PeakWorkingSet64 -gt 536870912){Cleanup-Failure 'Own process-reported peak working set exceeded512MiB'}
   $self.Dispose()
  }catch{Cleanup-Failure $_.Exception.Message}
 }
 $summary.elapsedSeconds=Elapsed
 $summary.cleanupElapsedSeconds=$summary.elapsedSeconds-$cleanupStarted
 if($summary.cleanupElapsedSeconds -gt 5){Cleanup-Failure 'Original-clock firewall cleanup exceeded5s'}
 if($summary.elapsedSeconds -gt 20){Cleanup-Failure 'Original20s whole firewall preflight deadline exceeded'}
 if(-not $summary.firstFailure -and $summary.effectiveProgramBlockAny -and $summary.classicWin32TcpLoopbackHandshake -and $summary.ownRuleGone -and $summary.socketsClosed){$summary.status='passed'}
}
try{
 if((Elapsed) -gt 20){Keep-Failure 'Original20s deadline exhausted before terminal receipt';$summary.status='failed'}
 $json=$summary|ConvertTo-Json -Depth 8 -Compress
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes($json)
 if($bytes.Length -gt 57342){throw 'Firewall preflight terminal JSON exceeded56KiB including newline reserve'}
 if($Output -and -not(Test-Path -LiteralPath $Output)){[IO.File]::WriteAllBytes($Output,$bytes)}else{throw 'Fresh bounded preflight receipt unavailable'}
 if((Elapsed) -gt 20){
  Keep-Failure 'Original20s deadline exceeded during terminal receipt write';$summary.status='failed';$summary.elapsedSeconds=Elapsed
  $json=$summary|ConvertTo-Json -Depth 8 -Compress
  $bytes=[Text.UTF8Encoding]::new($false).GetBytes($json)
  if($bytes.Length -gt 57342){throw 'Late failed receipt exceeded56KiB JSON reserve'}
  [IO.File]::WriteAllBytes($Output,$bytes)
 }
 [Console]::Out.WriteLine($json)
 # A blocked/late terminal emission cannot return a positive result. Preserve
 # the already emitted single JSON line; file+stderr+exit1 carry late failure.
 if((Elapsed) -gt 20){
  Keep-Failure 'Original20s deadline exceeded during terminal emission';$summary.status='failed';$summary.elapsedSeconds=Elapsed
  $failedJson=$summary|ConvertTo-Json -Depth 8 -Compress
  $failedBytes=[Text.UTF8Encoding]::new($false).GetBytes($failedJson)
  if($failedBytes.Length -gt 57342){throw 'Late emission failure receipt exceeded56KiB JSON reserve'}
  [IO.File]::WriteAllBytes($Output,$failedBytes)
  [Console]::Error.WriteLine('Offline firewall preflight FAILED: original20s deadline exceeded during terminal emission; receipt rewritten failed')
  exit 1
 }
}catch{
 [Console]::Error.WriteLine('Offline firewall preflight receipt failed: '+$_.Exception.Message.Substring(0,[Math]::Min(2048,$_.Exception.Message.Length)))
 exit 1
}
if($summary.status -cne 'passed'){exit 1}
