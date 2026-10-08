param(
 [string]$PackageRoot=(Split-Path $PSScriptRoot -Parent),
 [Parameter(Mandatory=$true)][string]$WorkRoot,
 [Parameter(Mandatory=$true)][string]$SciencePython,
 [Parameter(Mandatory=$true)][string]$PosePython,
 [string]$Node=(Get-Command node.exe -ErrorAction Stop).Source,
 [switch]$NativeCheck
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$PackageRoot=[IO.Path]::GetFullPath($PackageRoot)
$WorkRoot=[IO.Path]::GetFullPath($WorkRoot)
if(Test-Path -LiteralPath $WorkRoot){throw 'Build WorkRoot must be new'}
New-Item -ItemType Directory -Path $WorkRoot | Out-Null
$logs=Join-Path $WorkRoot 'logs'
New-Item -ItemType Directory -Path $logs | Out-Null
$commands=[Collections.Generic.List[object]]::new()
$started=[DateTime]::UtcNow
$env:PIP_DISABLE_PIP_VERSION_CHECK='1'
$env:PIP_PROGRESS_BAR='off'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
function Write-Json([string]$Path,$Value){
 [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 30),[Text.UTF8Encoding]::new($false))
}
function Invoke-Tool([string]$Label,[string]$Exe,[string[]]$Arguments){
 $index=$commands.Count+1
 $path=Join-Path $logs ("{0:D2}-{1}.log" -f $index,$Label)
 Write-Host "[$index] $Label"
 $output=& $Exe @Arguments 2>&1
 $exit=$LASTEXITCODE
 $text=($output|Out-String)
 $overflow=$text.Length -gt 2097152
 if($overflow){$text=$text.Substring(0,2097152)+[Environment]::NewLine+'[log truncated]'}
 [IO.File]::WriteAllText($path,$text,[Text.UTF8Encoding]::new($false))
 $commands.Add(@{index=$index;label=$Label;exitCode=$exit;log=$path;logTruncated=$overflow})
 if($exit -ne 0){throw "$Label failed ($exit): $path"+[Environment]::NewLine+$text}
 if($overflow){throw "$Label exceeded2MiB log bound"}
}
function Fetch([string]$Url,[string]$Name){
 if(-not $Url.StartsWith('https://')){throw 'Runtime input must useHTTPS'}
 $path=Join-Path $WorkRoot $Name
 Invoke-WebRequest -Uri $Url -OutFile $path -UseBasicParsing
 return $path
}
function Fetch-Notice([string]$Url,[string]$Name){
 $path=Join-Path $WorkRoot $Name
 $client=[Net.Http.HttpClient]::new()
 $cancel=[Threading.CancellationTokenSource]::new(60000)
 $response=$null;$incoming=$null;$outgoing=$null
 try{
  $response=$client.GetAsync($Url,[Net.Http.HttpCompletionOption]::ResponseHeadersRead,$cancel.Token).GetAwaiter().GetResult()
  [void]$response.EnsureSuccessStatusCode()
  $incoming=$response.Content.ReadAsStreamAsync($cancel.Token).GetAwaiter().GetResult()
  $outgoing=[IO.File]::Open($path,[IO.FileMode]::CreateNew)
  $buffer=[byte[]]::new(65536);$total=0
  while(($count=$incoming.ReadAsync($buffer,0,$buffer.Length,$cancel.Token).GetAwaiter().GetResult()) -gt 0){
   $total+=$count
   if($total -gt 1048576){throw 'Official runtime notice exceeds1MiB'}
   $outgoing.Write($buffer,0,$count)
  }
 }finally{
  if($outgoing){$outgoing.Dispose()};if($incoming){$incoming.Dispose()};if($response){$response.Dispose()}
  $cancel.Dispose();$client.Dispose()
 }
 return $path
}
function Copy-Pip([string]$Python,[string]$Site){
 $source=(&$Python -I -c 'import pathlib,pip;print(pathlib.Path(pip.__file__).parent)'|Out-String).Trim()
 if($LASTEXITCODE -ne 0){throw 'Cannot locate build-host pip module'}
 Copy-Item -LiteralPath $source -Destination (Join-Path $Site 'pip') -Recurse
 $metadata=@(Get-ChildItem -LiteralPath (Split-Path $source -Parent) -Directory -Filter 'pip-*.dist-info')
 if($metadata.Count -ne 1){throw 'Ambiguous build-host pip metadata'}
 Copy-Item -LiteralPath $metadata[0].FullName -Destination $Site -Recurse
}
try{
 $inputs=Get-Content -LiteralPath (Join-Path $PackageRoot 'packaging\windows\runtime-inputs.json') -Raw -Encoding UTF8|ConvertFrom-Json
 $iscc='C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
 if(-not(Test-Path -LiteralPath $iscc)){throw 'Inno Setup build compiler missing'}
 $compiler=Get-Item -LiteralPath $iscc
 # Empty stdin prints the engine version then fails on the empty script (exit2).
 # Output disabled: this query cannot create an installer. Help lacks minor version.
 $probe=[Diagnostics.Process]::new()
 $probe.StartInfo=[Diagnostics.ProcessStartInfo]::new($iscc,'/O- -')
 $probe.StartInfo.UseShellExecute=$false
 $probe.StartInfo.CreateNoWindow=$true
 $probe.StartInfo.RedirectStandardInput=$true
 $probe.StartInfo.RedirectStandardOutput=$true
 $probe.StartInfo.RedirectStandardError=$true
 try{
  if(-not $probe.Start()){throw 'Cannot start official compiler version probe'}
  $stdout=$probe.StandardOutput.ReadToEndAsync()
  $stderr=$probe.StandardError.ReadToEndAsync()
  $probe.StandardInput.Close()
  if(-not $probe.WaitForExit(10000)){
   $probe.Kill()
   if(-not $probe.WaitForExit(3000)){throw 'Compiler version probe termination unresolved'}
   throw 'Compiler version probe exceeded10s'
  }
  $probeExit=$probe.ExitCode
  $banner=$stdout.GetAwaiter().GetResult()+[Environment]::NewLine+$stderr.GetAwaiter().GetResult()
 }finally{$probe.Dispose()}
 if([Text.Encoding]::UTF8.GetByteCount($banner) -gt 65536){throw 'Compiler version banner exceeds64KiB'}
 [IO.File]::WriteAllText((Join-Path $logs 'compiler-version-banner.log'),$banner,[Text.UTF8Encoding]::new($false))
 $engine=[regex]::Match($banner,'(?m)^Compiler engine version:\s+Inno Setup\s+(?<version>\d+\.\d+\.\d+(?:\.\d+)?)\s*$')
 $versionText=if($engine.Success){$engine.Groups['version'].Value}else{$null}
 Write-Json (Join-Path $WorkRoot 'compiler-input.json') @{
  publisher='JRSoftware';path=$iscc;fileVersionResource=$compiler.VersionInfo.FileVersion;resolvedVersion=$versionText;
  versionSource='actual CLI engine banner from /O- - with empty stdin';probeExitCode=$probeExit;expectedProbeExitCode=2;banner=$banner;
  bytes=$compiler.Length;sha256=(Get-FileHash -LiteralPath $iscc -Algorithm SHA256).Hash.ToLowerInvariant()
 }
 if($probeExit -ne 2 -or -not $engine.Success){throw 'Compiler empty-script version probe has unexpected output or exit'}
 $compilerVersion=[version]$versionText
 if($compilerVersion.Major -ne $inputs.innoSetup.major -or $compilerVersion -lt [version]$inputs.innoSetup.minimumVersion){throw "Incompatible Inno Setup compiler $compilerVersion"}
 $nodeVersion=(&$Node --version|Out-String).Trim().TrimStart('v')
 if($LASTEXITCODE -ne 0 -or -not $nodeVersion.StartsWith('24.')){throw 'Build requiresNode24'}
 foreach($pair in @(@($SciencePython,'3.12.10'),@($PosePython,'3.9.13'))){
  Invoke-Tool ('builder-python-'+$pair[1]) $pair[0] @('-I','-c',('import sys;assert ".".join(map(str,sys.version_info[:3]))=="'+$pair[1]+'";print(sys.version)'))
 }
 $env:FS_ELEM_TEST_NODE=$Node
 Push-Location $PackageRoot
 try{
  Invoke-Tool 'first-run-targeted-tests' $SciencePython @('-B','-m','unittest','discover','-s','tests/release','-p','test_windows_first_run.py')
  Invoke-Tool 'desktop-targeted-tests' $Node @('--test','tests/release/windows-desktop.test.mjs')
 }finally{Pop-Location}
 $nodeName="node-v$nodeVersion-win-x64.zip"
 $nodeZip=Fetch "$($inputs.node.baseUrl)/v$nodeVersion/$nodeName" $nodeName
 $sums=Fetch "$($inputs.node.baseUrl)/v$nodeVersion/SHASUMS256.txt" 'SHASUMS256.txt'
 $row=@(Get-Content -LiteralPath $sums|Where-Object{$_ -match ("^[0-9a-f]{64}\s+"+[regex]::Escape($nodeName)+'$')})
 if($row.Count -ne 1 -or (Get-FileHash -LiteralPath $nodeZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $row[0].Split(' ')[0]){throw 'Official Node checksum mismatch'}
 $scienceZip=Fetch $inputs.python.science.url 'science-embedded.zip'
 $poseZip=Fetch $inputs.python.pose.url 'pose-embedded.zip'
 $receipts=@(
  @{id='node';url="$($inputs.node.baseUrl)/v$nodeVersion/$nodeName";path=$nodeZip},
  @{id='science';url=$inputs.python.science.url;path=$scienceZip},
  @{id='pose';url=$inputs.python.pose.url;path=$poseZip}
 )
 foreach($r in $receipts){$r.bytes=(Get-Item -LiteralPath $r.path).Length;$r.sha256=(Get-FileHash -LiteralPath $r.path -Algorithm SHA256).Hash.ToLowerInvariant()}
 Write-Json (Join-Path $WorkRoot 'build-inputs.json') $receipts
 $scienceSite=Join-Path $WorkRoot 'science-site'
 $poseSite=Join-Path $WorkRoot 'pose-site'
 Invoke-Tool 'science-build-dependencies' $SciencePython @('-I','-m','pip','install','--target',$scienceSite,'--require-hashes','--only-binary=:all:','--no-compile','-r',(Join-Path $PackageRoot 'services\analysis\requirements-science-windows-x64.lock'))
 Invoke-Tool 'pose-build-dependencies' $PosePython @('-I','-m','pip','install','--target',$poseSite,'--require-hashes','--only-binary=:all:','--no-compile','-r',(Join-Path $PackageRoot 'services\analysis\requirements-pose-windows-x64.lock'))
 Copy-Pip $SciencePython $scienceSite
 Copy-Pip $PosePython $poseSite
 $vc=@(Get-ChildItem 'C:\Program Files\Microsoft Visual Studio\2022\*\VC\Redist\MSVC\*\x64\Microsoft.VC143.CRT' -Directory -ErrorAction SilentlyContinue|Sort-Object FullName -Descending)
 if($vc.Count -eq 0){throw 'Official app-local VC CRT redist directory missing'}
 $vcRuntime=$vc[0].FullName
 $dlls=@(Get-ChildItem -LiteralPath $vcRuntime -Filter '*.dll')
 if($dlls.Count -eq 0){throw 'VC CRT directory empty'}
 Write-Json (Join-Path $WorkRoot 'vc-runtime-inputs.json') @($dlls|ForEach-Object{@{name=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}})
 $web=Join-Path $WorkRoot 'web-deps'
 New-Item -ItemType Directory -Path $web|Out-Null
 Copy-Item -LiteralPath (Join-Path $PackageRoot 'apps\web\package.json') -Destination $web
 Copy-Item -LiteralPath (Join-Path $PackageRoot 'apps\web\pnpm-lock.yaml') -Destination $web
 $npm=Join-Path (Split-Path $Node -Parent) 'node_modules\npm\bin\npm-cli.js'
 $bootstrap=Join-Path $WorkRoot 'pnpm-bootstrap'
 Invoke-Tool 'pinned-build-pnpm' $Node @($npm,'install','--prefix',$bootstrap,'--no-save','--package-lock=false','--ignore-scripts','--bin-links=false','--no-audit','--no-fund','pnpm@11.19.0')
 $pnpm=Join-Path $bootstrap 'node_modules\pnpm\bin\pnpm.cjs'
 Invoke-Tool 'hoisted-web-runtime' $Node @($pnpm,'--dir',$web,'install','--prod','--frozen-lockfile','--node-linker=hoisted','--reporter=append-only')
 $csc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
 $launcher=Join-Path $WorkRoot 'FS_elem.exe'
 $cs=Join-Path $PackageRoot 'apps\windows-launcher\FS_elemLauncher.cs'
 $refs=@('/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll')
 Invoke-Tool 'compile-launcher' $csc (@('/nologo','/utf8output','/codepage:65001','/target:winexe','/platform:x64',"/out:$launcher")+$refs+@($cs))
 $testExe=Join-Path $WorkRoot 'LauncherTests.exe'
 Invoke-Tool 'compile-launcher-tests' $csc (@('/nologo','/utf8output','/codepage:65001','/target:exe','/platform:x64','/main:LauncherTests',"/out:$testExe")+$refs+@($cs,(Join-Path $PackageRoot 'tests\windows-launcher\LauncherTests.cs')))
 Invoke-Tool 'launcher-protocol-tests' $testExe @()
 Invoke-Tool 'assembly-tests' $SciencePython @('-I','-B',(Join-Path $PackageRoot 'tests\release\test_windows_bundle_assembly.py'))
 $payload=Join-Path $WorkRoot 'payload'
 Invoke-Tool 'portable-bundle-assembly' $SciencePython @('-I','-B',(Join-Path $PackageRoot 'scripts\prepare-windows-bundle.py'),
  '--source',$PackageRoot,'--output',$payload,'--node-zip',$nodeZip,'--node-version',$nodeVersion,
  '--science-zip',$scienceZip,'--science-site',$scienceSite,'--pose-zip',$poseZip,'--pose-site',$poseSite,
  '--web-modules',(Join-Path $web 'node_modules'),'--launcher',$launcher,'--vc-runtime',$vcRuntime)
 # Capture the actual pinned binary's notices inside the installed payload.
 # Refresh its inventory before Inno; these files are part of first-run verification.
 $evidence=Join-Path $payload 'docs\runtime-evidence'
 New-Item -ItemType Directory -Path $evidence -Force|Out-Null
 foreach($flag in '-version','-L','-buildconf'){
  $label='packaged-ffmpeg-'+$flag.TrimStart('-')
  Invoke-Tool $label (Join-Path $payload '.runtime\bin\ffmpeg.exe') @($flag)
  Copy-Item -LiteralPath $commands[$commands.Count-1].log -Destination (Join-Path $evidence ($label+'.txt'))
 }
 Copy-Item -LiteralPath (Join-Path $WorkRoot 'vc-runtime-inputs.json') -Destination $evidence
 Write-Json (Join-Path $evidence 'vc-runtime-source.json') @{
  publisher='Microsoft';distribution='Visual Studio 2022 Microsoft.VC143.CRT x64 app-local redistributable';
  source='GitHub windows-2022 official Visual Studio installation VC/Redist/MSVC/x64/Microsoft.VC143.CRT';
  redistributionTerms='https://learn.microsoft.com/visualstudio/releases/2022/redistribution';
  licenseTerms='https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/'
 }
 $noticeInputs=[Collections.Generic.List[object]]::new()
 foreach($notice in @(
  @('https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/','microsoft-visual-cpp-license.html'),
  @('https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution','microsoft-visual-studio-redistribution.html')
 )){
  $file=Fetch-Notice $notice[0] $notice[1]
  Copy-Item -LiteralPath $file -Destination $evidence
  $noticeInputs.Add(@{url=$notice[0];name=$notice[1];bytes=(Get-Item -LiteralPath $file).Length;sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()})
 }
 $noticeDirectory=$vcRuntime
 for($level=0;$level -lt 5;$level++){
  foreach($file in @(Get-ChildItem -LiteralPath $noticeDirectory -File|Where-Object{$_.Name -eq 'REDIST.txt' -or $_.Name -like 'LICENSE*'})){
   if($file.Length -gt 1048576){throw 'Build-host original license exceeds1MiB'}
   $name='build-host-'+$level+'-'+$file.Name
   Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $evidence $name)
   $noticeInputs.Add(@{source='official Visual Studio redist ancestor';name=$name;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()})
  }
  $noticeDirectory=Split-Path $noticeDirectory -Parent
 }
 Write-Json (Join-Path $evidence 'notice-inputs.json') $noticeInputs
 Invoke-Tool 'freeze-final-payload-inventory' $SciencePython @('-I','-B','-c',
  'import importlib.util,json,pathlib,sys;spec=importlib.util.spec_from_file_location("assembler",sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);root=pathlib.Path(sys.argv[2]);p=root/"windows-bundle.json";v=json.loads(p.read_text("utf-8"));v["files"]=m.inventory(root);p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");print(json.dumps({"files":len(v["files"]),"NN":0}))',
  (Join-Path $PackageRoot 'scripts\prepare-windows-bundle.py'),$payload)
 $out=Join-Path $WorkRoot 'artifacts'
 New-Item -ItemType Directory -Path $out|Out-Null
 Invoke-Tool 'compile-installer' $iscc @("/DPayloadDir=$payload","/DOutputDir=$out",(Join-Path $PackageRoot 'packaging\windows\FS_elem.iss'))
 $installer=Join-Path $out 'FS_elem-Setup-0.2.2-x64.exe'
 if(-not(Test-Path -LiteralPath $installer)){throw 'Installer artifact missing'}
 $hash=(Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
 [IO.File]::WriteAllText((Join-Path $out 'SHA256SUMS.txt'),"$hash  FS_elem-Setup-0.2.2-x64.exe"+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
 if($NativeCheck){
  Invoke-Tool 'native-installer-check' (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile','-File',(Join-Path $PackageRoot 'scripts\check-windows-installer.ps1'),'-Installer',$installer,'-WorkRoot',$WorkRoot,'-Logs',$logs)
 }
 Write-Json (Join-Path $WorkRoot 'build-summary.json') @{
  status='built';version='0.2.2';installer=$installer;installerBytes=(Get-Item -LiteralPath $installer).Length;
  installerSha256=$hash;startedUTC=$started.ToString('o');terminalUTC=[DateTime]::UtcNow.ToString('o');
  commands=$commands;NN=0;nativeCheckRequested=[bool]$NativeCheck
 }
}catch{
 Write-Json (Join-Path $WorkRoot 'build-summary.json') @{status='failed';firstFailure=$_.Exception.Message;
  startedUTC=$started.ToString('o');terminalUTC=[DateTime]::UtcNow.ToString('o');commands=$commands;NN=0}
 throw
}
