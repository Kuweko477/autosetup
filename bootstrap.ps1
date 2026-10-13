#Requires -Version 5.1
<#
.SYNOPSIS
    Telecharge et lance AutoSetup. Concu pour un Windows fraichement installe.

.DESCRIPTION
    Ce script est appele par la one-liner :
        irm https://raw.githubusercontent.com/<OWNER>/<REPO>/main/bootstrap.ps1 | iex

    Il telecharge la derniere release, verifie son empreinte SHA-256,
    retire le "Mark of the Web" pour contourner le blocage SmartScreen,
    puis lance l'application (qui s'auto-eleve en administrateur).
#>

[CmdletBinding()]
param(
    # Seul parametre a modifier en general.
    [string]$Repo = 'Kuweko477/autosetup',

    # Retelecharge meme si une copie deja installee est presente.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# PowerShell 5.1 est nettement plus rapide sans la barre de progression,
# qui rend le telechargement d'un binaire de ~46 Mo pénible.
$ProgressPreference = 'SilentlyContinue'

# TLS 1.2 : sans effet sur Windows 10 1809+ / 11, mais evite les echecs
# sur les images plus anciennes ou derriere certains proxys.
try {
    $current = [Net.ServicePointManager]::SecurityProtocol
    if ($current -notmatch 'Tls12') {
        [Net.ServicePointManager]::SecurityProtocol = $current -bor 3072
    }
} catch {
    # Negligeable : on continue avec le protocole par defaut.
}

$exeName  = 'AutoSetup.exe'
$baseUrl  = "https://github.com/$Repo/releases/latest/download"
$exeUrl   = "$baseUrl/$exeName"
$jsonUrl  = "$baseUrl/latest.json"

$installDir = Join-Path $env:LOCALAPPDATA 'Programs\AutoSetup'
$exePath    = Join-Path $installDir $exeName

function Write-Step  { param($m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "    $m" -ForegroundColor Yellow }

Write-Host ''
Write-Host '  AutoSetup - installation' -ForegroundColor White
Write-Host '  -----------------------' -ForegroundColor DarkGray
Write-Host ''

# ── 1. Manifeste : version + empreinte attendue ─────────────────────────────
# S'il est absent (vieille release, CDN en cache), on continue sans verifier.
$expectedHash = $null
try {
    $manifest     = Invoke-RestMethod -Uri $jsonUrl -UseBasicParsing -ErrorAction Stop
    $expectedHash = "$($manifest.sha256)".ToLower()
    Write-Ok "Manifeste detecte : version $($manifest.version)"
} catch {
    Write-Warn2 'Manifeste introuvable, verification SHA-256 ignoree.'
}

# ── 2. Reutiliser une copie deja presente et intacte ────────────────────────
$alreadyThere = $false
if ((Test-Path -LiteralPath $exePath) -and -not $Force) {
    if ($expectedHash) {
        $local = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLower()
        $alreadyThere = ($local -eq $expectedHash)
    }
    if ($alreadyThere) {
        Write-Ok 'Deja installe et a jour, telechargement ignore.'
    }
}

# ── 3. Telechargement ───────────────────────────────────────────────────────
if (-not $alreadyThere) {
    Write-Step 'Telechargement...'
    if (-not (Test-Path -LiteralPath $installDir)) {
        New-Item -ItemType Directory -Path $installDir -Force | Out-Null
    }

    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("AutoSetup." + [Guid]::NewGuid().ToString('N') + '.exe')
    try {
        try {
            Invoke-WebRequest -Uri $exeUrl -OutFile $tmp -UseBasicParsing -ErrorAction Stop
        } catch {
            # Repli : utile quand Invoke-WebRequest bute sur un proxy/TLS strict.
            Write-Warn2 "Invoke-WebRequest a echoue ($($_.Exception.Message)), essai via WebClient..."
            (New-Object Net.WebClient).DownloadFile($exeUrl, $tmp)
        }

        $size = (Get-Item -LiteralPath $tmp).Length
        if ($size -lt 1MB) {
            throw "Fichier recu trop petit ($size octets). L'URL est-elle correcte ?"
        }
        Write-Ok ("{0:N1} Mo telecharges" -f ($size / 1MB))

        # ── 4. Verification d'integrite ──────────────────────────────────────
        if ($expectedHash) {
            $got = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash.ToLower()
            if ($got -ne $expectedHash) {
                throw "Empreinte SHA-256 non conforme. Telechargement corrompu ou attaque MITM."
            }
            Write-Ok 'Empreinte SHA-256 valide.'
        }

        Move-Item -LiteralPath $tmp -Destination $exePath -Force
    } catch {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        Write-Host ''
        Write-Host "  ECHEC : $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ''
        throw
    }
}

# ── 5. Retirer le Mark of the Web ───────────────────────────────────────────
# Un binaire telecharge porte un Zone.Identifier ; Windows le refuse ensuite
# avec "Windows a protege votre PC". Unblock-File est sans effet si absent.
try { Unblock-File -LiteralPath $exePath -ErrorAction SilentlyContinue } catch {}

# ── 6. Raccourci Bureau ─────────────────────────────────────────────────────
try {
    $shell = New-Object -ComObject WScript.Shell
    $lnk   = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'AutoSetup.lnk'))
    $lnk.TargetPath       = $exePath
    $lnk.WorkingDirectory = $installDir
    $lnk.IconLocation     = "$exePath,0"
    $lnk.Save()
} catch {
    # Raccourci non critique.
}

# ── 7. Lancement ────────────────────────────────────────────────────────────
Write-Step 'Lancement (une demande UAC va apparaitre, cliquez Oui)...'
Write-Host ''
Write-Host "    Installe dans : $installDir" -ForegroundColor DarkGray
Write-Host "    Relancer sans re-telecharger : & '$exePath'" -ForegroundColor DarkGray
Write-Host ''

Start-Process -FilePath $exePath
