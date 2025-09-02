#!/usr/bin/env python3
"""
Lightweight XLSX parser (no external deps) to extract the
"Ventilation required" sheet and export its visible table to CSV.

It reads shared strings and the specific sheet XML directly from the
ZIP package, mapping cell references to values. By default it uses the
print area defined in the workbook for that sheet; if not present,
falls back to the worksheet dimension.

Usage:
  python scripts/parse_ventilation.py \
    --xlsx "Вентиляция Минимум и максимум.xlsx" \
    --out data/ventilation_required.csv

This script avoids 3rd-party packages to work in restricted environments.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


@dataclass
class SheetInfo:
    name: str
    r_id: str
    path: str
    index: int
    print_area: Optional[str]


CELL_REF_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def col_letters_to_index(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def col_index_to_letters(idx: int) -> str:
    s = []
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        s.append(chr(ord("A") + rem))
    return "".join(reversed(s))


def parse_cell_ref(ref: str) -> Tuple[int, int]:
    m = CELL_REF_RE.match(ref)
    if not m:
        raise ValueError(f"Invalid cell reference: {ref}")
    col_letters, row_str = m.groups()
    return col_letters_to_index(col_letters), int(row_str)


def parse_range(a1: str) -> Tuple[int, int, int, int]:
    # e.g., 'A2:U52'
    if ":" not in a1:
        c, r = parse_cell_ref(a1)
        return c, r, c, r
    left, right = a1.split(":", 1)
    c1, r1 = parse_cell_ref(left)
    c2, r2 = parse_cell_ref(right)
    return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def read_xml(z: zipfile.ZipFile, path: str) -> ET.Element:
    with z.open(path) as f:
        data = f.read()
    return ET.fromstring(data)


def get_shared_strings(z: zipfile.ZipFile) -> List[str]:
    try:
        root = read_xml(z, "xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: List[str] = []
    for si in root.findall("main:si", NS):
        # A shared string can be a simple <t> or a rich text with multiple <r><t> parts.
        ts = []
        t_simple = si.find("main:t", NS)
        if t_simple is not None:
            ts.append(t_simple.text or "")
        else:
            for r in si.findall("main:r", NS):
                t = r.find("main:t", NS)
                if t is not None:
                    ts.append(t.text or "")
        strings.append("".join(ts))
    return strings


def get_sheets_and_print_areas(z: zipfile.ZipFile) -> Dict[str, SheetInfo]:
    workbook = read_xml(z, "xl/workbook.xml")
    # Map r:id -> sheet name
    sheets: Dict[str, SheetInfo] = {}
    for idx, sheet in enumerate(workbook.findall("main:sheets/main:sheet", NS), start=1):
        name = sheet.get("name") or f"sheet{idx}"
        r_id = sheet.get(f"{{{NS['r']}}}id")
        if not r_id:
            continue
        sheets[r_id] = SheetInfo(name=name, r_id=r_id, path="", index=idx, print_area=None)

    # Resolve r:id -> path via relationships
    rels = read_xml(z, "xl/_rels/workbook.xml.rels")
    rel_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    for rel in rels.findall("rel:Relationship", rel_ns):
        r_id = rel.get("Id")
        target = rel.get("Target") or ""
        if r_id in sheets:
            # Target like 'worksheets/sheet1.xml'
            path = f"xl/{target}" if not target.startswith("xl/") else target
            sheets[r_id].path = path

    # Parse defined names for Print_Area mapping to sheet localSheetId
    for dn in workbook.findall("main:definedNames/main:definedName", NS):
        if dn.get("name") == "_xlnm.Print_Area":
            local_id = dn.get("localSheetId")
            if local_id is None:
                continue
            try:
                local_idx = int(local_id)
            except ValueError:
                continue
            # Find sheet by index (1-based in our enumeration order)
            for si in sheets.values():
                if si.index - 1 == local_idx:
                    si.print_area = (dn.text or "").strip().strip("'")
                    break

    # Make a second dict keyed by sheet name for easier lookup
    by_name: Dict[str, SheetInfo] = {si.name: si for si in sheets.values()}
    return by_name


def extract_grid_from_sheet_xml(sheet_root: ET.Element, shared_strings: List[str]) -> Dict[Tuple[int, int], str]:
    grid: Dict[Tuple[int, int], str] = {}
    for row in sheet_root.findall("main:sheetData/main:row", NS):
        for c in row.findall("main:c", NS):
            ref = c.get("r")
            if not ref:
                continue
            col, rownum = parse_cell_ref(ref)
            cell_type = c.get("t")
            v = c.find("main:v", NS)
            text: Optional[str] = None
            if v is None:
                # Empty or formula-only without cached value
                text = ""
            else:
                val = v.text or ""
                if cell_type == "s":
                    # shared string
                    try:
                        idx = int(val)
                        text = shared_strings[idx]
                    except Exception:
                        text = val
                else:
                    text = val
            grid[(col, rownum)] = text if text is not None else ""
    return grid


def infer_bounds(sheet_root: ET.Element) -> Tuple[int, int, int, int]:
    dim = sheet_root.find("main:dimension", NS)
    ref = dim.get("ref") if dim is not None else None
    if ref:
        return parse_range(ref)
    # Fallback to a reasonable area
    return 1, 1, 50, 200


def a1_from_tuple(c: int, r: int) -> str:
    return f"{col_index_to_letters(c)}{r}"


def normalize_print_area(pa: str) -> str:
    # Remove sheet name if present like: 'Ventilation required'!$A$2:$U$52
    if "!" in pa:
        pa = pa.split("!", 1)[1]
    return pa.replace("$", "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, help="Path to the XLSX file")
    ap.add_argument("--out", required=True, help="Path to output CSV")
    ap.add_argument("--sheet", default="Ventilation required", help="Sheet name to export")
    args = ap.parse_args()

    with zipfile.ZipFile(args.xlsx) as z:
        shared = get_shared_strings(z)
        sheets = get_sheets_and_print_areas(z)
        if args.sheet not in sheets:
            print(f"Sheet '{args.sheet}' not found. Available: {sorted(sheets)}", file=sys.stderr)
            return 2
        si = sheets[args.sheet]
        if not si.path:
            print(f"Sheet '{args.sheet}' path not resolved", file=sys.stderr)
            return 2
        sheet_root = read_xml(z, si.path)

        grid = extract_grid_from_sheet_xml(sheet_root, shared)
        if si.print_area:
            pa = normalize_print_area(si.print_area)
            c1, r1, c2, r2 = parse_range(pa)
        else:
            c1, r1, c2, r2 = infer_bounds(sheet_root)

        # Build rows
        rows: List[List[str]] = []
        for r in range(r1, r2 + 1):
            row_vals: List[str] = []
            for c in range(c1, c2 + 1):
                row_vals.append(grid.get((c, r), ""))
            rows.append(row_vals)

    # Ensure output directory exists
    out_path = args.out
    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"Exported '{args.sheet}' {a1_from_tuple(c1, r1)}:{a1_from_tuple(c2, r2)} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

