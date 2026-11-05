<#
.SYNOPSIS
    Example driver for the Fe-C kit: run VASP on every folder in vasp_inputs/
    and collect the final total energies into a CSV.

.DESCRIPTION
    This is a TEMPLATE, not a tested production script (no VASP was available
    where the kit was built).  It shows the expected workflow:

      1. (optional) build each POTCAR from your own PAW library;
      2. run the relaxation (INCAR + KPOINTS) with vasp_std;
      3. run the static step (INCAR.static + KPOINTS.static) on the relaxed cell;
      4. parse "free  energy   TOTEN" from OUTCAR into energies_raw.csv.

    POTCAR is never shipped with the kit (VASP licence).  Supply -PotcarDir
    pointing at your potpaw_PBE.54 (or newer) installation.

.PARAMETER KitRoot
    Kit root (default: parent of this scripts/ folder).

.PARAMETER VaspBin
    VASP executable (default: vasp_std, must be on PATH).

.PARAMETER PotcarDir
    Path containing Fe_pv/POTCAR, Fe/POTCAR, C/POTCAR ...

.PARAMETER Static
    Run INCAR.static / KPOINTS.static instead of the relaxation inputs.

.EXAMPLE
    powershell -File .\run_vasp_template.ps1 -PotcarDir C:\paw\potpaw_PBE.54
    powershell -File .\run_vasp_template.ps1 -Static
#>
param(
    [string]$KitRoot   = (Split-Path -Parent $PSScriptRoot),
    [string]$VaspBin   = "vasp_std",
    [string]$PotcarDir = "",
    [string]$OutCsv    = "",
    [switch]$Static
)

$ErrorActionPreference = "Stop"

$vaspDir = Join-Path $KitRoot "vasp_inputs"
$outDir  = Join-Path $KitRoot "out"
if (-not $OutCsv) { $OutCsv = Join-Path $outDir "energies_raw.csv" }
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
"name,E0_eV,status" | Set-Content -Encoding UTF8 $OutCsv

$potMap = @{ "Fe" = "Fe_pv"; "C" = "C" }   # element -> PAW folder name

function Get-SpeciesLine {
    param([string]$Poscar)
    return ((Get-Content -Path $Poscar -TotalCount 6)[5]).Trim()
}

foreach ($dir in Get-ChildItem -Path $vaspDir -Directory | Sort-Object Name) {
    $name = $dir.Name
    $work = Join-Path $outDir $name
    New-Item -ItemType Directory -Force -Path $work | Out-Null

    $incar  = if ($Static) { "INCAR.static" } else { "INCAR" }
    $kpts   = if ($Static) { "KPOINTS.static" } else { "KPOINTS" }
    $poscar = Join-Path $work "POSCAR"
    if ($Static) {
        # static step needs the relaxed cell of the previous run
        $relaxContcar = Join-Path $work "CONTCAR"
        if (Test-Path $relaxContcar) {
            Copy-Item $relaxContcar $poscar -Force
        } else {
            Copy-Item (Join-Path $dir.FullName "POSCAR") $poscar -Force
            Write-Warning "$name : no CONTCAR from a relaxation run, using the input POSCAR"
        }
    } else {
        Copy-Item (Join-Path $dir.FullName "POSCAR") $poscar -Force
    }
    Copy-Item (Join-Path $dir.FullName $incar) (Join-Path $work "INCAR") -Force
    Copy-Item (Join-Path $dir.FullName $kpts) (Join-Path $work "KPOINTS") -Force

    # ---- POTCAR ---------------------------------------------------------
    $potcar = Join-Path $work "POTCAR"
    if ($PotcarDir) {
        $species = (Get-SpeciesLine -Poscar $poscar) -split '\s+'
        $parts = @()
        foreach ($el in $species) {
            $paw = if ($potMap.ContainsKey($el)) { $potMap[$el] } else { $el }
            $p = Join-Path (Join-Path $PotcarDir $paw) "POTCAR"
            if (-not (Test-Path $p)) { throw "missing POTCAR: $p" }
            $parts += $p
        }
        $content = $parts | ForEach-Object { Get-Content -Path $_ -Raw }
        ($content -join "`n") | Set-Content -Path $potcar -Encoding UTF8
        Write-Host "$name : built POTCAR for [$($species -join ' ')]"
    } elseif (-not (Test-Path $potcar)) {
        Write-Warning "$name : no POTCAR (pass -PotcarDir), skipped"
        Add-Content -Path $OutCsv -Value "$name,,skipped-no-potcar"
        continue
    }

    # ---- run ------------------------------------------------------------
    Write-Host "==> $name  ($incar / $kpts)"
    Push-Location $work
    try {
        & $VaspBin | Tee-Object -FilePath (Join-Path $work "stdout.log")
        if ($LASTEXITCODE -ne 0) { throw "VASP exited with $LASTEXITCODE" }
    } finally {
        Pop-Location
    }

    # ---- parse energy ---------------------------------------------------
    $outcar = Join-Path $work "OUTCAR"
    $e0 = $null
    if (Test-Path $outcar) {
        $last = Select-String -Path $outcar -Pattern 'free\s+energy\s+TOTEN' |
                Select-Object -Last 1
        if ($last) {
            $m = [regex]::Match($last.Line, 'free\s+energy\s+TOTEN\s*=\s*(-?\d+\.\d+)')
            if ($m.Success) { $e0 = [double]$m.Groups[1].Value }
        }
    }
    if ($null -eq $e0) {
        Add-Content -Path $OutCsv -Value "$name,,no-energy"
        Write-Warning "$name : could not parse TOTEN from OUTCAR"
    } else {
        Add-Content -Path $OutCsv -Value ("{0},{1:F8},ok" -f $name, $e0)
        Write-Host ("    E0 = {0:F6} eV" -f $e0)
    }
}

Write-Host ""
Write-Host "raw energies -> $OutCsv"
Write-Host "next: convert to formation enthalpies (see vasp_inputs/<name>/POTCAR.readme)"
Write-Host "      then: python scripts\build_hull.py --energies my_energies.csv"
