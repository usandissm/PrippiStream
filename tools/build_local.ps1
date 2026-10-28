param(
    [string[]]$Tasks = @(':app:assembleRelease', ':app:testReleaseUnitTest'),
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$gradle = Get-ChildItem -Path (Join-Path $env:USERPROFILE '.gradle\wrapper\dists\gradle-8.7-bin\*\gradle-8.7\bin\gradle.bat') -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $gradle) { throw 'Gradle 8.7 locale non trovato. Configurarlo prima tramite Android Studio.' }
$oldJava=$env:JAVA_HOME; $oldOptions=$env:JAVA_TOOL_OPTIONS
try {
    if (-not $env:JAVA_HOME -or -not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
        $jdk = Get-ChildItem -Path (Join-Path $env:USERPROFILE 'Downloads\PrippiJdk17x\*\bin\java.exe') -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($jdk) { $env:JAVA_HOME = Split-Path -Parent (Split-Path -Parent $jdk.FullName) }
        elseif (Test-Path -LiteralPath 'C:\Program Files\Android\Android Studio\jbr\bin\java.exe') { $env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr' }
        else { throw 'JDK 17+ non trovato.' }
    }
    # Validated workaround for this Windows JVM's AF_UNIX loopback failure.
    # Process-local only: no registry, global environment or JDK modifications.
    if (Test-Path -LiteralPath 'C:\Android') {
        $env:JAVA_TOOL_OPTIONS = ($oldOptions + ' -Djdk.net.unixdomain.tmpdir=C:\Android').Trim()
    }
    $arguments=@('--no-daemon','--console=plain','--max-workers=2','-Pkotlin.compiler.execution.strategy=in-process','-p',$project)
    if ($Offline) { $arguments += '--offline' }
    & $gradle.FullName @arguments @Tasks
    $code=$LASTEXITCODE
} finally {
    $env:JAVA_HOME=$oldJava; $env:JAVA_TOOL_OPTIONS=$oldOptions
}
if ($code -ne 0) { throw "Gradle terminato con codice $code" }
