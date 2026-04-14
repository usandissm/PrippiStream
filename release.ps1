# ============================================================
# release.ps1 - Script di rilascio PrippiStream
# Uso: .\release.ps1
# Opzionale: .\release.ps1 -Message "Descrizione aggiornamento"
# ============================================================

param(
    [string]$Message = "Aggiornamento addon"
)

$ErrorActionPreference = "Stop"
$rootDir   = $PSScriptRoot
$addonId   = "plugin.video.prippistream"
$repoId    = "repository.prippistream"
$docsDir   = Join-Path $rootDir "docs"
$addonDocs = Join-Path $docsDir $addonId
$repoDocs  = Join-Path $docsDir $repoId

# --- 1. Leggi versione da addon.xml ---
[xml]$addonXml = Get-Content (Join-Path $rootDir "addon.xml") -Encoding UTF8
$version = $addonXml.addon.version
Write-Host "Versione rilevata: $version" -ForegroundColor Cyan

# --- 2. Crea zip dell addon ---
$zipName = "$addonId-$version.zip"
$zipPath = Join-Path $addonDocs $zipName

# Rimuovi vecchi zip se esistono
if (Test-Path $addonDocs) {
    Get-ChildItem $addonDocs -Filter "*.zip" | Remove-Item -Force
}
New-Item -ItemType Directory -Path $addonDocs -Force | Out-Null

python (Join-Path $rootDir "tools\make_addon_zip.py")
Write-Host "ZIP creato: $zipPath" -ForegroundColor Green

# --- 3. Copia icona/fanart nel docs/plugin.video.prippistream ---
$iconSrc = Join-Path $rootDir "resources\media\logo.png"
$fanartSrc = Join-Path $rootDir "resources\media\fanart.jpg"
if (Test-Path $iconSrc)   { Copy-Item $iconSrc   (Join-Path $addonDocs "icon.png")   -Force }
if (Test-Path $fanartSrc) { Copy-Item $fanartSrc (Join-Path $addonDocs "fanart.jpg") -Force }

# Copia icona anche nel repository addon
New-Item -ItemType Directory -Path $repoDocs -Force | Out-Null
if (Test-Path $iconSrc) { Copy-Item $iconSrc (Join-Path $repoDocs "icon.png") -Force }

# --- 4. Genera addons.xml e md5 ---
python (Join-Path $rootDir "tools\make_addons_xml.py")
Write-Host "addons.xml generato" -ForegroundColor Green

# --- 5. Rigenera zip del repository ---
python (Join-Path $rootDir "tools\make_repo_zip.py")
Write-Host "repository zip aggiornato" -ForegroundColor Green

# --- 6. Commit e push su GitHub ---
Set-Location $rootDir
git add docs/
git add addon.xml
$commitMsg = "Release v$version - $Message"
git commit -m $commitMsg
git push origin main
Write-Host ""
Write-Host "=====================================================" -ForegroundColor Green
Write-Host " Rilascio v$version completato e pushato su GitHub!" -ForegroundColor Green
Write-Host " URL repository Kodi:" -ForegroundColor Green
Write-Host " https://usandissm.github.io/PrippiStream/addons.xml" -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Green
