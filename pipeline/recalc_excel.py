"""Recalculate the scorecard in Excel, so its formula values are stored in the file and can be read anywhere.

Excel recalculates by itself when a person opens the file. This step is for previews and tools that only read stored
values. Without Excel it prints a note and carries on, because the workbook is still correct once opened.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS  # noqa: E402

SCRIPT = r"""
param([string]$Path)
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $book = $excel.Workbooks.Open($Path)
    $excel.CalculateFullRebuild()
    $book.Save()
    $formulas = 0; $errors = 0
    foreach ($sheet in $book.Worksheets) {
        try { $found = $sheet.UsedRange.SpecialCells(-4123) } catch { $found = $null }
        if ($found -ne $null) {
            $formulas += $found.Count
            try { $bad = $sheet.UsedRange.SpecialCells(-4123, 16) } catch { $bad = $null }
            if ($bad -ne $null) { $errors += $bad.Count; Write-Output ("errors in " + $sheet.Name + ": " + $bad.Address()) }
        }
    }
    Write-Output "formulas: $formulas, errors: $errors"
    $book.Close($true)
    if ($errors -gt 0) { exit 2 }
} finally {
    $excel.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
}
"""


def run() -> None:
    book = OUTPUTS / "data_quality_scorecard.xlsx"
    shell = shutil.which("powershell.exe")
    if not shell:
        print("Excel recalculation skipped: PowerShell not found. Formula values appear when the file is opened in Excel.", flush=True)
        return
    script = OUTPUTS / "_recalc.ps1"
    script.write_text(SCRIPT, encoding="utf8")
    try:
        done = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(book)], capture_output=True, text=True)
    finally:
        script.unlink(missing_ok=True)
    print(done.stdout.strip(), flush=True)
    if done.returncode == 2:
        raise SystemExit("The workbook has formula errors.")
    if done.returncode != 0:
        print("Excel recalculation skipped: Excel could not be started. Formula values appear when the file is opened in Excel.", flush=True)


if __name__ == "__main__":
    run()
