#Requires -Version 5.1
<#
.SYNOPSIS
    Smoke test de la chaine de distribution AutoSetup sur un Windows vierge.

.DESCRIPTION
    A lancer dans Windows Sandbox via autosetup.wsb. Verifie que sur une
    machine reellementVierge (rien d'installe) la one-liner fonctionne :
        telechargement -> verification SHA-256 -> deblocage -> installation.

    Ecrit un rapport dans le dossier mappe pour etre recupere apres
    fermeture du bac a sable.
#>

[CmdletBinding()]
param(
    [string]$Repo    = 'Kuweko477/autosetup',
    [string]$ReportDir = $PSScriptRoot
)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

$reportPath = Join-Path $ReportDir ('sandbox-report-{0}.txt' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$results    = New-Object System.Collections.ArrayList
$failed    = 0

function Add-Line { param($t = '') Write-Host $t; Add-Content -LiteralPath $reportPath -Value $t -Encoding UTF8 }

function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = '')
    if ($Ok) { Add-Line ("  [OK]   {0}{1}" -f $Name, $(if ($Detail) { " - $Detail" })) }
    else     { $script:failed++; Add-Line ("  [FAIL] {0}{1}" -f $Name, $(if ($Detail) { " - $Detail" })) -ForegroundColor Red }
}

function Add-Section { param($t) Add-Line ''; Add-Line "== $t" }

Add-Line '=========================================================='
Add-Line ' AutoSetup - rapport de test Windows Sandbox'
Add-Line (' ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Line '=========================================================='

# ── Contexte de la machine ─────────────────────────────────────────────────
Add-Section 'Environnement'
$os  = Get-CimInstance Win32_OperatingSystem
Add-Line ("  OS          : {0} (build {1}, {2})" -f $os.Caption, $os.BuildNumber, $os.OSArchitecture)
Add-Line ("  PowerShell  : {0}" -f $PSVersionTable.PSVersion)
Add-Line ("  Utilisateur : {0}  (admin : {1})" -f $env:USERNAME, (
    (New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    )).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)))

Add-Line ''
Add-Line '  Outils deja presents avant test (doivent tous etre absents sur un OS vierge) :'
foreach ($tool in @('winget', 'choco', 'git', 'python')) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    Add-Line ("    - {0,-8} : {1}" -f $tool, $(if ($found) { "PRESENT (inattendu)" } else { 'absent' }))
}

# ── 1. Connectivite ────────────────────────────────────────────────────────
Add-Section '1. Connectivite vers GitHub'
try {
    $probe = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
                               -Headers @{ 'User-Agent' = 'autosetup-sandbox-test' } -TimeoutSec 30 -ErrorAction Stop
    Add-Line ("  Derniere release : {0}" -f $probe.tag_name)
    $probe.assets | ForEach-Object { Add-Line ("    - {0} ({1:N1} Mo)" -f $_.name, ($_.size / 1MB)) }
    Add-Check 'API GitHub joignable' $true $probe.tag_name
} catch {
    Add-Check 'API GitHub joignable' $false $_.Exception.Message
}

# ── 2. Recuperation du bootstrap comme le ferait la one-liner ──────────────
Add-Section '2. Recuperation du bootstrap (equivalent one-liner)'
$bootstrapUrl = "https://raw.githubusercontent.com/$Repo/main/bootstrap.ps1"
try {
    $remote = Invoke-RestMethod -Uri $bootstrapUrl -TimeoutSec 30 -ErrorAction Stop
    Add-Check 'bootstrap.ps1 telecharge' ($remote.Length -gt 1000) "$($remote.Length) caracteres"
    Add-Check 'URL de repo correcte' ($remote -match [regex]::Escape($Repo)) $Repo
} catch {
    Add-Check 'bootstrap.ps1 telecharge' $false $_.Exception.Message
    $remote = $null
}

# ── 3. Execution reelle du bootstrap (sans lancer l'app) ───────────────────
Add-Section '3. Execution du bootstrap (-NoLaunch)'
if ($remote) {
    $tmpScript = Join-Path ([IO.Path]::GetTempPath()) 'autosetup-bootstrap-test.ps1'
    Set-Content -LiteralPath $tmpScript -Value $remote -Encoding UTF8

    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        & $tmpScript -Repo $Repo -NoLaunch 2>&1 | ForEach-Object { Add-Line ('  | ' + $_) }
        $sw.Stop()
        Add-Check 'bootstrap termine sans exception' $true ("{0:N1}s" -f $sw.Elapsed.TotalSeconds)
    } catch {
        $sw.Stop()
        Add-Check 'bootstrap termine sans exception' $false $_.Exception.Message
    } finally {
        Remove-Item -LiteralPath $tmpScript -Force -ErrorAction SilentlyContinue
    }
}

# ── 4. Verification de ce que le bootstrap a pose ──────────────────────────
Add-Section '4. Verification de l installation'
$exePath    = Join-Path $env:LOCALAPPDATA 'Programs\AutoSetup\AutoSetup.exe'
$installDir = Split-Path -Parent $exePath

Add-Check 'Repertoire d installation cree' (Test-Path -LiteralPath $installDir) $installDir
$exeExists = Test-Path -LiteralPath $exePath
Add-Check 'AutoSetup.exe present' $exeExists $exePath

if ($exeExists) {
    $item = Get-Item -LiteralPath $exePath
    Add-Line ("  Taille       : {0:N1} Mo" -f ($item.Length / 1MB))
    Add-Check 'Taille plausible (> 10 Mo)' ($item.Length -gt 10MB)

    # Le fichier est-il bien un PE executable ?
    try {
        $fs = [IO.File]::OpenRead($exePath)
        $mz = New-Object byte[] 2
        $null = $fs.Read($mz, 0, 2)
        $fs.Dispose()
        Add-Check 'En-tete PE valide (MZ)' ($mz[0] -eq 0x4D -and $mz[1] -eq 0x5A)
    } catch {
        Add-Check 'En-tete PE valide (MZ)' $false $_.Exception.Message
    }

    # Correspondance avec le manifeste publie
    try {
        $m = Invoke-RestMethod -Uri "https://github.com/$Repo/releases/latest/download/latest.json" -TimeoutSec 30 -ErrorAction Stop
        $h = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLower()
        Add-Check 'SHA-256 conforme au manifeste' ($h -eq "$($m.sha256)".ToLower()) $h
    } catch {
        Add-Check 'SHA-256 conforme au manifeste' $false $_.Exception.Message
    }

    # Mark of the Web : principalPiege sur OS neuf
    $zone = Get-Item -LiteralPath $exePath -Stream Zone.Identifier -ErrorAction SilentlyContinue
    Add-Check 'Mark of the Web retire' ($null -eq $zone) $(if ($zone) { 'bloquera SmartScreen' } else { 'SmartScreen ne bloquera pas' })
}

# ── 5. Raccourci Bureau ────────────────────────────────────────────────────
Add-Section '5. Integration Bureau'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk     = Join-Path $desktop 'AutoSetup.lnk'
Add-Check 'Raccourci Bureau cree' (Test-Path -LiteralPath $lnk) $lnk

# ── 6. SmartScreen / reputation ────────────────────────────────────────────
Add-Section '6. Signature numerique (information)'
try {
    $sig = Get-AuthenticodeSignature -LiteralPath $exePath -ErrorAction Stop
    Add-Line ("  Statut de signature : {0}" -f $sig.Status)
    Add-Line ("  Signataire          : {0}" -f $(if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { 'aucun' }))
    Add-Line ''
    Add-Line "  Un EXE non signe est Signataire=Non valide et declenche SmartScreen"
    Add-Line "  sur les postes qui n'ont pas encore de reputation. C'est connu et attendu."
} catch {
    Add-Line ("  Signature non verifiable : {0}" -f $_.Exception.Message)
}

# ── Verdict ────────────────────────────────────────────────────────────────
Add-Section 'VERDICT'
if ($failed -eq 0) {
    Add-Line '  TOUT EST VERT - la one-liner fonctionne sur OS vierge.' -ForegroundColor Green
} else {
    Add-Line ("  {0} test(s) en ECHEC - voir les lignes [FAIL] ci-dessus." -f $failed) -ForegroundColor Red
}

Add-Line ''
Add-Line "Rapport complet : $reportPath"
Add-Line "Ferme le bac a sable pour conserver ce fichier sur ta vraie machine."
Add-Line ''
Read-Host 'Appuie sur Entree pour fermer'
