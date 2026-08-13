$ErrorActionPreference = 'Stop'
$payload = Join-Path $PSScriptRoot 'OranixProPayload.zip'
$installRoot = Join-Path ${env:LOCALAPPDATA} 'OranixPro'
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = Join-Path ${env:APPDATA} 'Microsoft\Windows\Start Menu\Programs'
$shortcut = Join-Path $desktop 'Oranix Pro.lnk'
$startShortcut = Join-Path $startMenu 'Oranix Pro.lnk'

New-Item -ItemType Directory -Force -Path $installRoot, $startMenu | Out-Null
Expand-Archive -LiteralPath $payload -DestinationPath $installRoot -Force
$exe = Join-Path $installRoot 'OranixPro\OranixPro.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'OranixPro.exe kuruluma dahil edilemedi.' }

$shell = New-Object -ComObject WScript.Shell
foreach ($link in @($shortcut, $startShortcut)) {
    $item = $shell.CreateShortcut($link)
    $item.TargetPath = $exe
    $item.WorkingDirectory = Split-Path -Parent $exe
    $item.Description = 'Oranix Pro canlı spor analiz motoru'
    $item.IconLocation = "$exe,0"
    $item.Save()
}

$uninstall = Join-Path $installRoot 'Uninstall-OranixPro.ps1'
$uninstallBody = @'
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = Join-Path ${env:APPDATA} 'Microsoft\Windows\Start Menu\Programs'
Remove-Item -LiteralPath (Join-Path $desktop 'Oranix Pro.lnk') -Force
Remove-Item -LiteralPath (Join-Path $startMenu 'Oranix Pro.lnk') -Force
Remove-Item -LiteralPath $root -Recurse -Force
'@
Set-Content -LiteralPath $uninstall -Value $uninstallBody -Encoding UTF8
Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
