# Ouvre dans foobar2000 un lien foobar:play?<chemin> ou foobar:add?<chemin> venant de l'annuaire.
# N'accepte qu'un fichier audio ou un dossier existant. Journal : %LOCALAPPDATA%\foobar-lien\journal.txt
param([string]$Url)
$log = Join-Path $PSScriptRoot 'journal.txt'
function Note($msg) { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '  ' + $msg) -Encoding UTF8 }
Note "lien recu : $Url"
$fb = Join-Path $env:ProgramFiles 'foobar2000\foobar2000.exe'
if (-not (Test-Path -LiteralPath $fb)) { $fb = Join-Path ${env:ProgramFiles(x86)} 'foobar2000\foobar2000.exe' }
if (-not (Test-Path -LiteralPath $fb)) { Note "foobar2000.exe introuvable"; exit 1 }
if ($Url -notmatch '^foobar:(play|add)\?(.+)$') { Note "lien refuse (format)"; exit 1 }
$mode = $Matches[1]
$path = [uri]::UnescapeDataString($Matches[2]).TrimEnd('/')
Note "chemin : $path"
if (-not (Test-Path -LiteralPath $path)) { Note "chemin inaccessible"; exit 1 }
$item = Get-Item -LiteralPath $path
$audio = '.mp3', '.flac', '.wav', '.dsf', '.aiff', '.wv', '.m4a', '.ape'
if (-not $item.PSIsContainer -and $audio -notcontains $item.Extension.ToLower()) { Note "refuse (pas un fichier audio)"; exit 1 }
$fbArgs = @()
if ($mode -eq 'add') { $fbArgs += '/add' }
$fbArgs += '"' + $item.FullName + '"'
Start-Process -FilePath $fb -ArgumentList $fbArgs
Note "foobar2000 lance ($mode)"
