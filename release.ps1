# ============================================================
# release.ps1 - Script di rilascio LOCALE PrippiStream
#
# USO:
#   .\release.ps1                          → bump patch + push
#   .\release.ps1 -Message "Fix CB01"      → con messaggio custom
#   .\release.ps1 -NoBump                  → build senza bump versione
#
# Nota: il commit usa "[skip ci]" per evitare che GitHub Actions
# esegua di nuovo release.yml (che bumperebbe la versione una seconda volta).
# ============================================================

param(
    [string]$Message = "Aggiornamento addon",
    [switch]$NoBump
)

$ErrorActionPreference = "Stop"
$rootDir = $PSScriptRoot

# --- 1. Bump versione (o leggi quella attuale) ---
if ($NoBump) {
    $version = python (Join-Path $rootDir "tools\bump_version.py") --read
    Write-Host "Versione corrente (no bump): $version" -ForegroundColor Yellow
} else {
    $version = python (Join-Path $rootDir "tools\bump_version.py")
    Write-Host "Versione bumpata a: $version" -ForegroundColor Cyan
}

# --- 2. Crea zip dell'addon ---
python (Join-Path $rootDir "tools\make_addon_zip.py")
Write-Host "ZIP addon creato" -ForegroundColor Green

# --- 3. Copia icone nel docs/plugin.video.prippistream ---
$addonDocs = Join-Path $rootDir "docs\plugin.video.prippistream"
$repoDocs  = Join-Path $rootDir "docs\repository.prippistream"
$iconSrc   = Join-Path $rootDir "resources\media\logo.png"
$fanartSrc = Join-Path $rootDir "resources\media\fanart.jpg"
New-Item -ItemType Directory -Path $addonDocs -Force | Out-Null
New-Item -ItemType Directory -Path $repoDocs  -Force | Out-Null
if (Test-Path $iconSrc)   { Copy-Item $iconSrc   (Join-Path $addonDocs "icon.png")   -Force }
if (Test-Path $fanartSrc) { Copy-Item $fanartSrc (Join-Path $addonDocs "fanart.jpg") -Force }
if (Test-Path $iconSrc)   { Copy-Item $iconSrc   (Join-Path $repoDocs  "icon.png")   -Force }

# --- 4. Genera addons.xml e md5 ---
python (Join-Path $rootDir "tools\make_addons_xml.py")
Write-Host "addons.xml generato" -ForegroundColor Green

# --- 5. Rigenera zip del repository ---
python (Join-Path $rootDir "tools\make_repo_zip.py")
Write-Host "repository zip aggiornato" -ForegroundColor Green

# --- 6. Commit e push su GitHub ---
# IMPORTANTE: "[skip ci]" impedisce a release.yml di rieseguirsi dopo questo push
Set-Location $rootDir
git add docs/ addon.xml
$commitMsg = "Release v$version - $Message [skip ci]"
git commit -m $commitMsg
git push origin main

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Green
Write-Host " Rilascio v$version completato e pushato su GitHub!"  -ForegroundColor Green
Write-Host ""
Write-Host " Installa il repository in Kodi con:"                  -ForegroundColor Green
Write-Host " https://usandissm.github.io/PrippiStream/repository.prippistream.zip" -ForegroundColor Yellow
Write-Host ""
Write-Host " Kodi leggerà gli aggiornamenti da:"                   -ForegroundColor Green
Write-Host " https://usandissm.github.io/PrippiStream/addons.xml"  -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Green
