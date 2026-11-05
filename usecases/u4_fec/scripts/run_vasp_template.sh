#!/usr/bin/env bash
# Example driver for the Fe-C kit (bash/Linux version of run_vasp_template.ps1).
#
#   POTCAR_DIR=~/paw/potpaw_PBE.54 ./run_vasp_template.ps1
#   STATIC=1 ./run_vasp_template.sh          # static step on relaxed CONTCARs
#
# NOT tested against a real VASP installation here (no VASP in the build env).
# POTCAR is not shipped (VASP licence).
set -euo pipefail

KIT_ROOT="${KIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
VASP_BIN="${VASP_BIN:-vasp_std}"
POTCAR_DIR="${POTCAR_DIR:-}"
MODE="${MODE:-relax}"            # relax | static
OUT_DIR="$KIT_ROOT/out"
CSV="$OUT_DIR/energies_raw.csv"
mkdir -p "$OUT_DIR"
echo "name,E0_eV,status" > "$CSV"

paw_for() {  # element -> PAW folder name
    case "$1" in
        Fe) echo "Fe_pv" ;;
        *)  echo "$1" ;;
    esac
}

for src in "$KIT_ROOT"/vasp_inputs/*/; do
    name="$(basename "$src")"
    work="$OUT_DIR/$name"
    mkdir -p "$work"

    if [ "$MODE" = "static" ]; then
        incar="INCAR.static"; kpts="KPOINTS.static"
        if [ -f "$work/CONTCAR" ]; then cp "$work/CONTCAR" "$work/POSCAR";
        else cp "$src/POSCAR" "$work/POSCAR"; echo "WARN $name: no CONTCAR, using input POSCAR"; fi
    else
        incar="INCAR"; kpts="KPOINTS"; cp "$src/POSCAR" "$work/POSCAR"
    fi
    cp "$src/$incar" "$work/INCAR"
    cp "$src/$kpts" "$work/KPOINTS"

    if [ -n "$POTCAR_DIR" ]; then
        species=$(sed -n '6p' "$work/POSCAR")
        : > "$work/POTCAR"
        for el in $species; do
            p="$POTCAR_DIR/$(paw_for "$el")/POTCAR"
            [ -f "$p" ] || { echo "ERROR missing $p"; exit 1; }
            cat "$p" >> "$work/POTCAR"
        done
        echo "$name: built POTCAR for [$species]"
    elif [ ! -f "$work/POTCAR" ]; then
        echo "WARN $name: no POTCAR (set POTCAR_DIR), skipped"
        echo "$name,,skipped-no-potcar" >> "$CSV"
        continue
    fi

    echo "==> $name ($incar / $kpts)"
    ( cd "$work" && "$VASP_BIN" | tee stdout.log )

    e0=$(grep -E 'free  energy   TOTEN' "$work/OUTCAR" | tail -1 | \
         sed -E 's/.*=\s*(-?[0-9.]+).*/\1/' || true)
    if [ -n "${e0:-}" ]; then
        printf '%s,%.8f,ok\n' "$name" "$e0" >> "$CSV"
        echo "    E0 = $e0 eV"
    else
        echo "$name,,no-energy" >> "$CSV"
        echo "WARN $name: could not parse TOTEN"
    fi
done

echo
echo "raw energies -> $CSV"
echo "next: build E_form, then: python scripts/build_hull.py --energies my_energies.csv"
