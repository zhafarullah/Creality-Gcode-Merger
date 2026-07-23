#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, messagebox
import threading, queue, os, re, sys, subprocess, platform
from copy import copy as shallow_copy
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
#  THEME — Colors & Fonts
# ══════════════════════════════════════════════════════════════════════════════
BG       = '#0d1117'
SURFACE  = '#161b22'
SURFACE2 = '#21262d'
BORDER   = '#30363d'
ACCENT   = '#6366f1'
A_LT     = '#818cf8'
A_DK     = '#4338ca'
FC_CLR   = '#0ea5e9'
FC_DRK   = '#0284c7'
CR_CLR   = '#8b5cf6'
CR_DRK   = '#7c3aed'
CTR_CLR  = '#10b981'    # emerald — centering panel color
CTR_DRK  = '#059669'
STL_CLR  = '#f97316'    # orange — STL export panel color
STL_DRK  = '#ea580c'
SUCCESS  = '#22c55e'
WARN     = '#f59e0b'
ERR      = '#ef4444'
INFO     = '#38bdf8'
TEXT     = '#c9d1d9'
MUTED    = '#8b949e'
DIM      = '#484f58'
WHITE    = '#ffffff'

_FF = ('Segoe UI'   if platform.system() == 'Windows' else
       'SF Pro Text' if platform.system() == 'Darwin'  else 'DejaVu Sans')
_FM = ('Consolas'   if platform.system() == 'Windows' else
       'Menlo'       if platform.system() == 'Darwin'  else 'Monospace')

FH1  = (_FF, 15, 'bold')
FH2  = (_FF, 12, 'bold')
FH3  = (_FF, 11, 'bold')
FB   = (_FF, 10)
FSM  = (_FF,  9)
FMO  = (_FM,  9)
FBTL = (_FF, 13, 'bold')
FBT  = (_FF, 10, 'bold')

# ══════════════════════════════════════════════════════════════════════════════
#  REGEX PATTERNS
# ══════════════════════════════════════════════════════════════════════════════
PAT_EXEC_START = re.compile(r'^\s*;\s*EXECUTABLE_BLOCK_START\s*$')
PAT_EXEC_END   = re.compile(r'^\s*;\s*EXECUTABLE_BLOCK_END\s*$')
PAT_THUMB_S    = re.compile(r'^\s*;\s*THUMBNAIL_BLOCK_START\s*$')
PAT_THUMB_E    = re.compile(r'^\s*;\s*THUMBNAIL_BLOCK_END\s*$')
PAT_EXC_DEF    = re.compile(r'^EXCLUDE_OBJECT_DEFINE\b')
PAT_EXC_S      = re.compile(r'^EXCLUDE_OBJECT_START\b')
PAT_EXC_E      = re.compile(r'^EXCLUDE_OBJECT_END\b')
PAT_SP_TEMPS   = re.compile(r'START_PRINT.*EXTRUDER_TEMP=(\d+).*BED_TEMP=(\d+)', re.I)
PAT_CHAMBER    = re.compile(r'M141\s+S(\d+)')
PAT_TEMP_BED   = re.compile(r'M(?:190|140)\s+S(\d+)')
PAT_TEMP_HOT   = re.compile(r'M(?:109|104)\s+S(\d+)')
PAT_FAN        = re.compile(r'M106\s+S(\d+)')
PAT_M73        = re.compile(r'^M73\b')
PAT_OBJ_ID     = re.compile(r'^;\s*OBJECT_ID:')
PAT_TIME_EL    = re.compile(r'^;TIME_ELAPSED:')
PAT_FC_PRIM_S  = re.compile(r';\s*START OF PRIMER PROCEDURE')
PAT_FC_PRIM_E  = re.compile(r';\s*END OF PRIMER PROCEDURE')
PAT_FC_FOOTER  = re.compile(r'^;\s*model\s*:', re.I)
PAT_FC_SEP     = re.compile(r'^;-{3,}\s*$')
PAT_MOVE       = re.compile(r'^G[01]\b', re.I)
PAT_G90        = re.compile(r'^G90\b', re.I)
PAT_G91        = re.compile(r'^G91\b', re.I)
# Coordinates — only match a number that directly follows X, Y or Z (not inside comments)
PAT_COORD_X    = re.compile(r'(X)([-+]?\d*\.?\d+)')
PAT_COORD_Y    = re.compile(r'(Y)([-+]?\d*\.?\d+)')
PAT_COORD_Z    = re.compile(r'(Z)([-+]?\d*\.?\d+)')

# ══════════════════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class ParsedCreality:
    header:        List[str] = field(default_factory=list)
    start_seq:     List[str] = field(default_factory=list)
    end_seq:       List[str] = field(default_factory=list)
    extruder_temp: int  = 220
    bed_temp:      int  = 50
    chamber_temp:  int  = 35
    warnings:      List[str] = field(default_factory=list)
    start_method:  str  = ''
    end_method:    str  = ''

@dataclass
class ParsedFullControl:
    primer:        List[str] = field(default_factory=list)
    toolpath:      List[str] = field(default_factory=list)
    footer:        List[str] = field(default_factory=list)
    skipped:       List[str] = field(default_factory=list)
    extruder_temp: int  = 210
    bed_temp:      int  = 65
    fan_speed:     int  = 255
    has_primer:    bool = False
    warnings:      List[str] = field(default_factory=list)

@dataclass
class CenterInfo:
    applied:     bool  = False
    reason:      str   = ''
    min_x:       float = 0.0
    max_x:       float = 0.0
    min_y:       float = 0.0
    max_y:       float = 0.0
    model_w:     float = 0.0
    model_h:     float = 0.0
    offset_x:    float = 0.0
    offset_y:    float = 0.0
    bed_cx:      float = 130.0
    bed_cy:      float = 130.0
    warnings:    List[str] = field(default_factory=list)

# ══════════════════════════════════════════════════════════════════════════════
#  PARSER — Creality Print
# ══════════════════════════════════════════════════════════════════════════════
def parse_creality(lines: List[str]) -> ParsedCreality:
    r = ParsedCreality()
    exec_s = first_exc_s = last_exc_e = exec_e = -1
    in_thumb = False

    for i, raw in enumerate(lines):
        s = raw.rstrip().strip()
        if PAT_THUMB_S.match(s): in_thumb = True;  continue
        if PAT_THUMB_E.match(s): in_thumb = False; continue
        if in_thumb: continue
        if exec_s == -1 and not PAT_EXEC_START.match(s):
            if s: r.header.append(raw.rstrip())
            continue
        if PAT_EXEC_START.match(s):  exec_s = i; continue
        if exec_s >= 0:
            if first_exc_s == -1 and PAT_EXC_S.match(s): first_exc_s = i
            if PAT_EXC_E.match(s):                         last_exc_e  = i
            if PAT_EXEC_END.match(s):                      exec_e      = i
            m = PAT_SP_TEMPS.search(s)
            if m: r.extruder_temp, r.bed_temp = int(m.group(1)), int(m.group(2))
            m2 = PAT_CHAMBER.search(s)
            if m2: r.chamber_temp = int(m2.group(1))

    # Start sequence: EXECUTABLE_BLOCK_START → before the first EXCLUDE_OBJECT_START
    if exec_s >= 0 and first_exc_s > exec_s:
        r.start_method = 'EXECUTABLE_BLOCK_START → EXCLUDE_OBJECT_START'
        for i in range(exec_s + 1, first_exc_s):
            s = lines[i].rstrip().strip()
            if PAT_EXC_DEF.match(s) or PAT_OBJ_ID.match(s) or PAT_TIME_EL.match(s): continue
            if PAT_M73.match(s): r.start_seq.append('M73 P0 R0  ; reset progress'); continue
            r.start_seq.append(lines[i].rstrip())
    else:
        r.warnings.append('Could not detect the start sequence using the EXECUTABLE_BLOCK method.')

    # End sequence: after the last EXCLUDE_OBJECT_END → EXECUTABLE_BLOCK_END
    if last_exc_e >= 0 and exec_e > last_exc_e:
        r.end_method = 'last EXCLUDE_OBJECT_END → EXECUTABLE_BLOCK_END'
        for i in range(last_exc_e + 1, exec_e):
            s = lines[i].rstrip().strip()
            if PAT_M73.match(s): r.end_seq.append('M73 P100 R0  ; finished 100%'); continue
            r.end_seq.append(lines[i].rstrip())
    else:
        r.warnings.append('Could not detect the end sequence using the EXECUTABLE_BLOCK method.')

    if not r.start_seq: r.warnings.append('Start sequence is empty — is this really a Creality Print file?')
    if not r.end_seq:   r.warnings.append('End sequence is empty — is this really a Creality Print file?')
    return r

# ══════════════════════════════════════════════════════════════════════════════
#  PARSER — FullControl
# ══════════════════════════════════════════════════════════════════════════════
def parse_fullcontrol(lines: List[str]) -> ParsedFullControl:
    r  = ParsedFullControl()
    st = 'preamble'
    for raw in lines:
        s = raw.rstrip().strip()
        if st == 'preamble':
            if PAT_FC_PRIM_S.match(s):
                st = 'primer'; r.has_primer = True; r.primer.append(raw.rstrip()); continue
            if PAT_MOVE.match(s):
                st = 'toolpath'; r.toolpath.append(raw.rstrip()); continue
            m_b = PAT_TEMP_BED.search(s)
            if m_b and int(m_b.group(1)) > 0: r.bed_temp = int(m_b.group(1))
            m_h = PAT_TEMP_HOT.search(s)
            if m_h and int(m_h.group(1)) > 0: r.extruder_temp = int(m_h.group(1))
            m_f = PAT_FAN.search(s)
            if m_f: r.fan_speed = int(m_f.group(1))
            r.skipped.append(raw.rstrip())
        elif st == 'primer':
            r.primer.append(raw.rstrip())
            if PAT_FC_PRIM_E.match(s): st = 'between'
        elif st == 'between':
            if PAT_FC_SEP.match(s) or not s: continue
            if PAT_FC_FOOTER.match(s): st = 'footer'; r.footer.append(raw.rstrip()); continue
            st = 'toolpath'; r.toolpath.append(raw.rstrip())
        elif st == 'toolpath':
            if PAT_FC_FOOTER.match(s): st = 'footer'; r.footer.append(raw.rstrip()); continue
            r.toolpath.append(raw.rstrip())
        elif st == 'footer':
            r.footer.append(raw.rstrip())
    if not r.toolpath:
        r.warnings.append('FullControl toolpath is empty — is this really a FullControl.xyz file?')
    return r

# ══════════════════════════════════════════════════════════════════════════════
#  CENTERING — Bounding Box & XY Offset
# ══════════════════════════════════════════════════════════════════════════════
def find_bounding_box(toolpath: List[str]) -> Optional[Tuple[float, float, float, float]]:
    """
    Scan every G0/G1 move in absolute mode (G90, the default) and return
    (min_x, max_x, min_y, max_y). Returns None if no XY coordinates are found.
    Z is left untouched — this matters for non-planar printing!
    """
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')
    in_rel  = False
    found   = False

    for line in toolpath:
        code = line.split(';')[0].strip()
        if not code: continue
        up = code.upper()
        if PAT_G90.match(up): in_rel = False; continue
        if PAT_G91.match(up): in_rel = True;  continue
        if in_rel or not PAT_MOVE.match(up): continue
        for m in PAT_COORD_X.finditer(code):
            v = float(m.group(2)); min_x = min(min_x, v); max_x = max(max_x, v); found = True
        for m in PAT_COORD_Y.finditer(code):
            v = float(m.group(2)); min_y = min(min_y, v); max_y = max(max_y, v); found = True

    if not found or min_x == float('inf') or min_y == float('inf'):
        return None
    return min_x, max_x, min_y, max_y


def find_bounding_box_3d(toolpath: List[str]) -> Optional[Tuple[float, float, float, float, float, float]]:

    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    in_rel   = False
    found_xy = False
    found_z  = False

    for line in toolpath:
        code = line.split(';')[0].strip()
        if not code: continue
        up = code.upper()
        if PAT_G90.match(up): in_rel = False; continue
        if PAT_G91.match(up): in_rel = True;  continue
        if in_rel or not PAT_MOVE.match(up): continue
        for m in PAT_COORD_X.finditer(code):
            v = float(m.group(2)); min_x = min(min_x, v); max_x = max(max_x, v); found_xy = True
        for m in PAT_COORD_Y.finditer(code):
            v = float(m.group(2)); min_y = min(min_y, v); max_y = max(max_y, v); found_xy = True
        for m in PAT_COORD_Z.finditer(code):
            v = float(m.group(2)); min_z = min(min_z, v); max_z = max(max_z, v); found_z = True

    if not found_xy:
        return None
    if not found_z:
        min_z = max_z = 0.0
    return min_x, max_x, min_y, max_y, min_z, max_z


def apply_centering(toolpath: List[str], bed_w: float, bed_h: float) -> Tuple[List[str], CenterInfo]:

    ci = CenterInfo(bed_cx=bed_w / 2, bed_cy=bed_h / 2)
    bbox = find_bounding_box(toolpath)

    if bbox is None:
        ci.reason = 'No XY coordinates were found in the toolpath'
        return toolpath, ci

    ci.min_x, ci.max_x, ci.min_y, ci.max_y = bbox
    ci.model_w   = ci.max_x - ci.min_x
    ci.model_h   = ci.max_y - ci.min_y
    orig_cx      = (ci.min_x + ci.max_x) / 2
    orig_cy      = (ci.min_y + ci.max_y) / 2
    ci.offset_x  = ci.bed_cx - orig_cx
    ci.offset_y  = ci.bed_cy - orig_cy

    # Check whether the model fits on the bed
    new_min_x = ci.min_x + ci.offset_x;  new_max_x = ci.max_x + ci.offset_x
    new_min_y = ci.min_y + ci.offset_y;  new_max_y = ci.max_y + ci.offset_y
    if new_min_x < -0.1 or new_max_x > bed_w + 0.1:
        ci.warnings.append(
            f'⚠ Model ({ci.model_w:.1f} mm) is wider than the bed ({bed_w:.0f} mm)! '
            f'After centering: X {new_min_x:.1f}–{new_max_x:.1f} mm')
    if new_min_y < -0.1 or new_max_y > bed_h + 0.1:
        ci.warnings.append(
            f'⚠ Model ({ci.model_h:.1f} mm) is deeper than the bed ({bed_h:.0f} mm)! '
            f'After centering: Y {new_min_y:.1f}–{new_max_y:.1f} mm')

    # Apply the offset to every line
    ox = ci.offset_x
    oy = ci.offset_y
    new_tp   = []
    in_rel   = False

    for line in toolpath:
        # Split off the comment (never touch anything inside a comment)
        sc = line.find(';')
        if sc == 0:                            # pure comment line
            new_tp.append(line); continue
        code    = line[:sc] if sc > 0 else line
        comment = line[sc:] if sc > 0 else ''

        up = code.strip().upper()
        if PAT_G90.match(up): in_rel = False; new_tp.append(line); continue
        if PAT_G91.match(up): in_rel = True;  new_tp.append(line); continue

        # Only change G0/G1 moves in absolute mode
        if in_rel or not PAT_MOVE.match(up.strip()):
            new_tp.append(line); continue

        new_code = PAT_COORD_X.sub(
            lambda m: f'{m.group(1)}{float(m.group(2)) + ox:.4f}', code)
        new_code = PAT_COORD_Y.sub(
            lambda m: f'{m.group(1)}{float(m.group(2)) + oy:.4f}', new_code)
        new_tp.append(new_code + comment)

    ci.applied = True
    return new_tp, ci


def centering_header_block(ci: CenterInfo, bed_w: float, bed_h: float) -> List[str]:
    """Comment block inserted at the start of the toolpath documenting the centering result."""
    sx = '+' if ci.offset_x >= 0 else ''
    sy = '+' if ci.offset_y >= 0 else ''
    return [
        '',
        '; ┌───────────────────────────────────────────────────────┐',
        '; │  AUTO-CENTERING — Coordinate Correction Summary       │',
        '; ├───────────────────────────────────────────────────────┤',
        f'; │  Bed size        : {bed_w:.0f} × {bed_h:.0f} mm                        │',
        f'; │  Bed center      : ({ci.bed_cx:.1f}, {ci.bed_cy:.1f}) mm                 │',
        f'; │  Original bbox   : X {ci.min_x:.3f}–{ci.max_x:.3f}  '
        f'Y {ci.min_y:.3f}–{ci.max_y:.3f} │',
        f'; │  Model size      : {ci.model_w:.3f} × {ci.model_h:.3f} mm               │',
        f'; │  Offset applied  : X{sx}{ci.offset_x:.4f}  Y{sy}{ci.offset_y:.4f} mm      │',
        '; │  Z untouched (non-planar geometry intact)             │',
        '; └───────────────────────────────────────────────────────┘',
        '',
    ]

# ══════════════════════════════════════════════════════════════════════════════
#  STL EXPORT — Same-Size Placeholder Box (for slicing a matching template)
# ══════════════════════════════════════════════════════════════════════════════
def generate_bbox_stl(path: str, width: float, depth: float, height: float,
                      model_name: str = 'model') -> None:
    
    w = max(float(width), 0.01)
    d = max(float(depth), 0.01)
    h = max(float(height), 0.01)
    name = re.sub(r'\s+', '_', model_name.strip()) or 'model'

    v = [
        (0, 0, 0), (w, 0, 0), (w, d, 0), (0, d, 0),   # bottom 0-3
        (0, 0, h), (w, 0, h), (w, d, h), (0, d, h),   # top    4-7
    ]
    tris = [
        (0, 2, 1), (0, 3, 2),   # bottom  (-z)
        (4, 5, 6), (4, 6, 7),   # top     (+z)
        (0, 1, 5), (0, 5, 4),   # front   (-y)
        (3, 6, 2), (3, 7, 6),   # back    (+y)
        (0, 4, 7), (0, 7, 3),   # left    (-x)
        (1, 2, 6), (1, 6, 5),   # right   (+x)
    ]

    def facet_normal(a: int, b: int, c: int) -> Tuple[float, float, float]:
        ax, ay, az = v[b][0] - v[a][0], v[b][1] - v[a][1], v[b][2] - v[a][2]
        bx, by, bz = v[c][0] - v[a][0], v[c][1] - v[a][1], v[c][2] - v[a][2]
        nx, ny, nz = ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx
        length = (nx ** 2 + ny ** 2 + nz ** 2) ** 0.5 or 1.0
        return nx / length, ny / length, nz / length

    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'solid {name}\n')
        for a, b, c in tris:
            nx, ny, nz = facet_normal(a, b, c)
            f.write(f'  facet normal {nx:.6f} {ny:.6f} {nz:.6f}\n')
            f.write('    outer loop\n')
            for idx in (a, b, c):
                x, y, z = v[idx]
                f.write(f'      vertex {x:.4f} {y:.4f} {z:.4f}\n')
            f.write('    endloop\n')
            f.write('  endfacet\n')
        f.write(f'endsolid {name}\n')

# ══════════════════════════════════════════════════════════════════════════════
#  TRANSITION BLOCK & ASSEMBLER
# ══════════════════════════════════════════════════════════════════════════════
def build_transition(cr: ParsedCreality, fc: ParsedFullControl, skip_primer: bool) -> List[str]:
    L = [
        '',
        '; ══════════════════════════════════════════════════════════',
        '; TRANSITION BLOCK — Creality K2 Start → FullControl Toolpath',
        '; ══════════════════════════════════════════════════════════',
        '; After the Creality start sequence, E is retracted -1mm (G1 E-1 F2400).',
        '; Un-retracting here is required, otherwise FullControl will print in mid-air.',
        '',
        'G1 E1 F2400      ; un-retract 1mm (compensates the Creality retract)',
        'G92 E0           ; reset E counter to 0',
        '',
    ]
    if fc.fan_speed > 0:
        L += [f'M106 S{fc.fan_speed}          ; enable fan at {round(fc.fan_speed/2.55)}%', '']
    td = abs(fc.extruder_temp - cr.extruder_temp)
    if td > 5:
        L += [
            f'; ⚠ Temperature mismatch: Creality={cr.extruder_temp}°C vs FullControl={fc.extruder_temp}°C',
            f'; The printer is already heated to {cr.extruder_temp}°C via START_PRINT.',
            f'; M104 S{fc.extruder_temp}  ; ← uncomment if you want the FullControl temperature', '',
        ]
    if skip_primer:
        L.append('; FullControl primer SKIPPED (Creality already ran a purge line)')
    L += ['; ══════════════════════════════════════════════════════════', '']
    return L


def assemble_output(cr_path: str, fc_path: str,
                    cr: ParsedCreality, fc: ParsedFullControl,
                    toolpath: List[str],
                    skip_primer: bool, include_footer: bool,
                    center_info: Optional[CenterInfo],
                    bed_w: float, bed_h: float) -> List[str]:
    """
    Assemble the final merged G-code file.
    `toolpath` is the toolpath after centering (or the original if centering is off).
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    center_status = (f'Applied (offset X{center_info.offset_x:+.4f} Y{center_info.offset_y:+.4f} mm)'
                     if (center_info and center_info.applied)
                     else 'Off')
    out = [
        '; ████████████████████████████████████████████████████████████████',
        '; GCode Merger v1.0 — Creality K2 + FullControl',
        f'; Created      : {now}',
        f'; Template     : {Path(cr_path).name}',
        f'; FullControl  : {Path(fc_path).name}',
        f'; Hotend       : {cr.extruder_temp}°C  |  Bed: {cr.bed_temp}°C',
        f'; Fan          : S{fc.fan_speed} ({round(fc.fan_speed/2.55)}%)',
        f'; Bed size     : {bed_w:.0f} × {bed_h:.0f} mm',
        f'; Auto-center  : {center_status}',
        '; ████████████████████████████████████████████████████████████████',
        '',
        '',
        '; ╔══════════════════════════════════════════════════════════════╗',
        '; ║  SECTION 1 — CREALITY K2 START SEQUENCE                    ║',
        '; ║  (START_PRINT, chamber heating, auto bed-leveling, etc.)   ║',
        '; ╚══════════════════════════════════════════════════════════════╝',
        '',
    ]
    out += cr.start_seq
    out.append('')

    if not skip_primer and fc.has_primer and fc.primer:
        out += ['', '; ─── FullControl Primer Procedure ───', '']
        for ln in fc.primer:
            if PAT_FC_PRIM_S.match(ln.strip()) or PAT_FC_PRIM_E.match(ln.strip()): continue
            out.append(ln)
        out += ['G92 E0  ; reset E after the FullControl primer', '']

    out += build_transition(cr, fc, skip_primer)

    out += [
        '; ╔══════════════════════════════════════════════════════════════╗',
        '; ║  SECTION 2 — FULLCONTROL TOOLPATH (non-planar)             ║',
        '; ╚══════════════════════════════════════════════════════════════╝',
        '',
    ]
    if center_info and center_info.applied:
        out += centering_header_block(center_info, bed_w, bed_h)

    out += toolpath
    out.append('')

    if include_footer and fc.footer:
        out += ['', '; === FullControl Info ==='] + fc.footer + ['']

    out += [
        '',
        '; ╔══════════════════════════════════════════════════════════════╗',
        '; ║  SECTION 3 — CREALITY K2 END SEQUENCE                      ║',
        '; ║  (END_PRINT, fan off, chamber off, head park, etc.)        ║',
        '; ╚══════════════════════════════════════════════════════════════╝',
        '',
    ]
    out += cr.end_seq
    out += ['', '; ████ End of Merged G-code — Happy Printing! 🖨 ████']
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET — LogPanel
# ══════════════════════════════════════════════════════════════════════════════
class LogPanel(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=SURFACE,
                         highlightthickness=1, highlightbackground=BORDER, **kw)
        hdr = tk.Frame(self, bg=SURFACE2, height=28)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text='📋  Log Output', bg=SURFACE2, fg=MUTED,
                 font=FSM, anchor='w').pack(side='left', padx=10, fill='y')
        tk.Button(hdr, text='Clear', bg=SURFACE2, fg=DIM, font=FSM,
                  bd=0, cursor='hand2', relief='flat',
                  activebackground=BORDER, activeforeground=TEXT,
                  command=self.clear).pack(side='right', padx=8)
        frm = tk.Frame(self, bg=SURFACE)
        frm.pack(fill='both', expand=True)
        sb = tk.Scrollbar(frm, bg=SURFACE2, troughcolor=SURFACE2,
                          activebackground=BORDER, relief='flat', bd=0)
        self.txt = tk.Text(frm, bg=SURFACE, fg=TEXT, font=FMO,
                           wrap='word', bd=0, padx=10, pady=6,
                           state='disabled', cursor='arrow', relief='flat',
                           yscrollcommand=sb.set, selectbackground=SURFACE2)
        sb.config(command=self.txt.yview)
        sb.pack(side='right', fill='y')
        self.txt.pack(fill='both', expand=True)
        self.txt.tag_configure('info',    foreground=MUTED)
        self.txt.tag_configure('success', foreground=SUCCESS)
        self.txt.tag_configure('warning', foreground=WARN)
        self.txt.tag_configure('error',   foreground=ERR)
        self.txt.tag_configure('head',    foreground=INFO, font=(_FM, 9, 'bold'))
        self.txt.tag_configure('center',  foreground=CTR_CLR, font=(_FM, 9, 'bold'))
        self.txt.tag_configure('stl',     foreground=STL_CLR, font=(_FM, 9, 'bold'))

    def _append(self, icon, msg, tag):
        self.txt.configure(state='normal')
        ts = datetime.now().strftime('%H:%M:%S')
        self.txt.insert('end', f'[{ts}]  {icon}  {msg}\n', tag)
        self.txt.see('end')
        self.txt.configure(state='disabled')

    def add_info(self, m):    self._append('ℹ', m, 'info')
    def add_success(self, m): self._append('✅', m, 'success')
    def add_warning(self, m): self._append('⚠', m, 'warning')
    def add_error(self, m):   self._append('❌', m, 'error')
    def add_head(self, m):    self._append('►', m, 'head')
    def add_center(self, m):  self._append('🎯', m, 'center')
    def add_stl(self, m):     self._append('📦', m, 'stl')

    def clear(self):
        self.txt.configure(state='normal')
        self.txt.delete('1.0', 'end')
        self.txt.configure(state='disabled')

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET — FileCard
# ══════════════════════════════════════════════════════════════════════════════
class FileCard(tk.Frame):
    def __init__(self, parent, step, title, subtitle, accent, accent_dk, on_load, **kw):
        super().__init__(parent, bg=SURFACE,
                         highlightthickness=1, highlightbackground=BORDER, **kw)
        self.step      = step
        self._title    = title
        self.subtitle  = subtitle
        self.accent    = accent
        self.accent_dk = accent_dk
        self.on_load   = on_load
        self.filepath  = None
        self._draw_empty()

    def _draw_empty(self):
        self._clear()
        # Header
        hdr = tk.Frame(self, bg=SURFACE2, height=48)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text=f'  {self.step}  ', bg=self.accent, fg=WHITE,
                 font=(_FF, 11, 'bold')).pack(side='left', padx=10, pady=10)
        info = tk.Frame(hdr, bg=SURFACE2)
        info.pack(side='left', fill='y', pady=7)
        tk.Label(info, text=self._title,   bg=SURFACE2, fg=TEXT, font=FH3).pack(anchor='w')
        tk.Label(info, text=self.subtitle, bg=SURFACE2, fg=MUTED, font=FSM).pack(anchor='w')
        # Canvas zone (dashed drop border)
        self._cv = tk.Canvas(self, bg=SURFACE, bd=0, highlightthickness=0, cursor='hand2')
        self._cv.pack(fill='both', expand=True)
        self._cv.bind('<Configure>', self._redraw)
        self._cv.bind('<Button-1>',  lambda e: self._browse())
        self._cv.bind('<Enter>',     lambda e: self._cv.configure(bg='#1a2030'))
        self._cv.bind('<Leave>',     lambda e: self._cv.configure(bg=SURFACE))
        self.after(10, self._draw_canvas_inner)

    def _redraw(self, e=None):
        self._cv.delete('dashed')
        w, h = self._cv.winfo_width(), self._cv.winfo_height()
        if w < 10 or h < 10: return
        self._cv.create_rectangle(12, 8, w-12, h-8, outline=BORDER,
                                  dash=(6, 5), width=1, tags='dashed')
        # Reposition content window
        self._cv.delete('content')
        inner = getattr(self, '_inner_frame', None)
        if inner:
            self._cv.create_window(w//2, h//2, window=inner, anchor='center', tags='content')

    def _draw_canvas_inner(self):
        inner = tk.Frame(self._cv, bg=SURFACE)
        self._inner_frame = inner
        tk.Label(inner, text='📄', bg=SURFACE, fg=DIM,
                 font=(_FF, 26)).pack()
        tk.Label(inner, text='Click to select a .gcode file',
                 bg=SURFACE, fg=MUTED, font=FB).pack(pady=(4, 1))
        tk.Label(inner, text='Format: .gcode  /  .gco  /  .g',
                 bg=SURFACE, fg=DIM, font=FSM).pack()
        btn = tk.Button(inner, text='  📂  Browse File  ',
                        bg=self.accent, fg=WHITE, font=FBT, bd=0, pady=7,
                        cursor='hand2', relief='flat',
                        activebackground=self.accent_dk, activeforeground=WHITE,
                        command=self._browse)
        btn.pack(pady=(12, 0))
        for w in [inner, btn]:
            w.bind('<Enter>', lambda e: self._cv.configure(bg='#1a2030'))
            w.bind('<Leave>', lambda e: self._cv.configure(bg=SURFACE))
        cw = self._cv.winfo_width()
        ch = self._cv.winfo_height()
        self._cv.create_window(max(cw//2, 50), max(ch//2, 50),
                               window=inner, anchor='center', tags='content')
        self._redraw()

    def _draw_loaded(self, rows):
        self._clear()
        hdr = tk.Frame(self, bg=SURFACE2, height=48)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text='  ✓  ', bg=SUCCESS, fg=WHITE,
                 font=(_FF, 11, 'bold')).pack(side='left', padx=10, pady=10)
        info = tk.Frame(hdr, bg=SURFACE2)
        info.pack(side='left', fill='y', pady=7, expand=True)
        tk.Label(info, text=self._title, bg=SURFACE2, fg=SUCCESS, font=FH3).pack(anchor='w')
        fname = Path(self.filepath).name
        if len(fname) > 38: fname = fname[:35] + '…'
        tk.Label(info, text=fname, bg=SURFACE2, fg=MUTED, font=FSM).pack(anchor='w')
        tk.Button(hdr, text='↺  Change', bg=SURFACE2, fg=DIM, font=FSM,
                  bd=0, cursor='hand2', relief='flat',
                  activebackground=BORDER, activeforeground=TEXT,
                  command=self._browse).pack(side='right', padx=12)
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')
        body = tk.Frame(self, bg=SURFACE)
        body.pack(fill='both', expand=True, padx=16, pady=10)
        for (icon, label, value, color) in rows:
            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill='x', pady=3)
            tk.Label(row, text=f'{icon}  {label}', bg=SURFACE, fg=MUTED,
                     font=FSM, width=18, anchor='w').pack(side='left')
            tk.Label(row, text=value, bg=SURFACE, fg=color,
                     font=(_FM, 10, 'bold'), anchor='w').pack(side='left')

    def _clear(self):
        for w in self.winfo_children(): w.destroy()

    def _browse(self, _=None):
        path = filedialog.askopenfilename(
            title=f'Select {self._title}',
            filetypes=[('GCode files', '*.gcode *.gco *.g'), ('All files', '*.*')])
        if path:
            self.filepath = path
            self.on_load(path)

    def show_loaded(self, rows): self._draw_loaded(rows)
    def reset(self):
        self.filepath = None
        self._draw_empty()

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class GCodeMergerApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title('GCode Merger  —  Creality K2 × FullControl')
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(860, 760)
        self.geometry('1000x900')
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'+{max(0,(sw-1000)//2)}+{max(0,(sh-900)//2)}')

        # State
        self.fc_data: Optional[ParsedFullControl] = None
        self.cr_data: Optional[ParsedCreality]    = None
        self.log_q   = queue.Queue()
        self._fc_bbox3d: Optional[Tuple] = None   # cached (min_x,max_x,min_y,max_y,min_z,max_z)

        # Options
        self.opt_primer  = tk.BooleanVar(value=False)
        self.opt_footer  = tk.BooleanVar(value=True)
        self.opt_center  = tk.BooleanVar(value=True)
        self.bed_w       = tk.StringVar(value='260')
        self.bed_h       = tk.StringVar(value='260')

        # Refresh the centering preview whenever the bed size changes
        self.bed_w.trace_add('write', lambda *_: self.after(100, self._update_center_preview))
        self.bed_h.trace_add('write', lambda *_: self.after(100, self._update_center_preview))

        self._build()
        self._poll_log()

    # ── BUILD UI ─────────────────────────────────────────────────────────────
    def _build(self):
        self._build_header()
        self._build_body()

    def _build_header(self):
        hdr = tk.Frame(self, bg=A_DK, height=58)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        left = tk.Frame(hdr, bg=A_DK)
        left.pack(side='left', padx=18, fill='y')
        tk.Label(left, text='🖨', bg=A_DK, fg=WHITE,
                 font=(_FF, 22)).pack(side='left', padx=(0, 10))
        txt = tk.Frame(left, bg=A_DK)
        txt.pack(side='left', fill='y')
        tk.Label(txt, text='GCode Merger',
                 bg=A_DK, fg=WHITE, font=(_FF, 15, 'bold')).pack(anchor='sw', pady=(11, 0))
        tk.Label(txt, text='Creality K2  ×  FullControl  |  Non-Planar Printing Toolkit',
                 bg=A_DK, fg='#a5b4fc', font=FSM).pack(anchor='nw')
        tk.Button(hdr, text=' ? ', bg=A_DK, fg='#a5b4fc',
                  font=(_FF, 10, 'bold'), bd=0, cursor='hand2', relief='flat',
                  activebackground=A_LT, activeforeground=WHITE,
                  command=self._show_help).pack(side='right', padx=18)
        tk.Label(hdr, text='v4.0', bg=A_DK, fg='#a5b4fc', font=FSM).pack(side='right')

    def _build_body(self):
        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=20, pady=(14, 16))

        # Breadcrumb
        bc = tk.Frame(body, bg=BG)
        bc.pack(fill='x', pady=(0, 4))
        for txt, col in [('1  Load FullControl', FC_CLR), ('  →  ', MUTED),
                         ('2  Generate STL (optional)', STL_CLR), ('  →  ', MUTED),
                         ('3  Load Creality Template', CR_CLR), ('  →  ', MUTED),
                         ('4  Merge & Save', SUCCESS)]:
            tk.Label(bc, text=txt, bg=BG, fg=col, font=(_FF, 9, 'bold')).pack(side='left')

        tk.Label(body,
                 text="New here? Don't have a matching Creality template yet? Use Step 2 to generate one.",
                 bg=BG, fg=DIM, font=FSM, anchor='w').pack(fill='x', pady=(0, 8))

        # ── File cards (fixed height) ──
        card_area = tk.Frame(body, bg=BG, height=245)
        card_area.pack(fill='x'); card_area.pack_propagate(False)
        card_area.columnconfigure(0, weight=1, uniform='col')
        card_area.columnconfigure(1, weight=1, uniform='col')
        card_area.grid_rowconfigure(0, weight=1)

        self.fc_card = FileCard(
            card_area, step=1, title='FullControl G-code',
            subtitle='Non-planar toolpath from FullControl.xyz',
            accent=FC_CLR, accent_dk=FC_DRK, on_load=self._load_fc)
        self.fc_card.grid(row=0, column=0, sticky='nsew', padx=(0, 6))

        self.cr_card = FileCard(
            card_area, step=3, title='Creality Print Template',
            subtitle='A same-size template G-code from Creality Print',
            accent=CR_CLR, accent_dk=CR_DRK, on_load=self._load_cr)
        self.cr_card.grid(row=0, column=1, sticky='nsew', padx=(6, 0))

        # ── STL export panel (optional Step 2) ──
        self._build_stl_panel(body)

        # ── Centering panel ──
        self._build_centering_panel(body)

        # ── Options bar ──
        opts = tk.Frame(body, bg=SURFACE,
                        highlightthickness=1, highlightbackground=BORDER)
        opts.pack(fill='x', pady=(8, 0))
        oi = tk.Frame(opts, bg=SURFACE)
        oi.pack(fill='x', padx=14, pady=7)
        tk.Label(oi, text='⚙  Options:', bg=SURFACE, fg=MUTED, font=FSM).pack(side='left', padx=(0,12))
        def _cb(txt, var):
            return tk.Checkbutton(oi, text=txt, variable=var, bg=SURFACE, fg=TEXT,
                                  selectcolor=SURFACE2, activebackground=SURFACE,
                                  activeforeground=TEXT, font=FSM, cursor='hand2', bd=0)
        _cb('Include FullControl primer', self.opt_primer).pack(side='left')
        tk.Label(oi, text='  ·  Creality already ran a purge line (usually not needed)',
                 bg=SURFACE, fg=DIM, font=FSM).pack(side='left', padx=(0, 18))
        _cb('Include FullControl footer comments', self.opt_footer).pack(side='left')

        # ── Merge button ──
        bw = tk.Frame(body, bg=BG)
        bw.pack(fill='x', pady=(10, 0))
        self.merge_btn = tk.Button(
            bw, text='🔀   Step 4 — Merge & Save G-code',
            bg=SURFACE2, fg=DIM, font=FBTL,
            bd=0, pady=13, cursor='arrow', relief='flat',
            state='disabled', command=self._do_merge)
        self.merge_btn.pack(fill='x')
        self.merge_btn.bind('<Enter>', lambda e: self.merge_btn.configure(bg=A_LT)
                            if str(self.merge_btn['state'])=='normal' else None)
        self.merge_btn.bind('<Leave>', lambda e: self.merge_btn.configure(bg=ACCENT)
                            if str(self.merge_btn['state'])=='normal' else None)
        self.status_var = tk.StringVar(value='Select both files to get started')
        self.status_lbl = tk.Label(bw, textvariable=self.status_var, bg=BG, fg=DIM, font=FSM)
        self.status_lbl.pack(pady=(5, 0))

        # ── Log panel ──
        self.log = LogPanel(body)
        self.log.pack(fill='both', expand=True, pady=(10, 0))
        self.log.add_info('Welcome to GCode Merger v4.0 for the Creality K2!')
        self.log.add_info('Step 1: load your FullControl file. Step 2 (optional): generate a '
                          'same-size STL and slice it. Step 3: load your Creality template. '
                          'Step 4: merge & save.')
        self.log.add_center('Auto-centering is ON — the toolpath will be shifted to the middle '
                            'of a 260×260 mm bed by default.')

    def _build_stl_panel(self, parent):
        """Optional Step 2 panel: generate a bounding-box STL sized to the FullControl model."""
        wrapper = tk.Frame(parent, bg=STL_CLR)
        wrapper.pack(fill='x', pady=(10, 0))
        inner_bg = tk.Frame(wrapper, bg=SURFACE)
        inner_bg.pack(fill='both', expand=True, padx=(3, 0))

        content = tk.Frame(inner_bg, bg=SURFACE)
        content.pack(fill='x', padx=14, pady=10)

        row1 = tk.Frame(content, bg=SURFACE)
        row1.pack(fill='x')
        tk.Label(row1, text='  2  ', bg=STL_CLR, fg=WHITE,
                 font=(_FF, 10, 'bold')).pack(side='left', padx=(0, 8))
        tk.Label(row1, text='📦  Optional: generate a same-size STL for your slicer',
                 bg=SURFACE, fg=TEXT, font=(_FF, 10, 'bold')).pack(side='left')

        desc = ("Don't have a Creality template G-code sized to this object yet? Generate a "
                "placeholder box matching your model's exact width, depth and height, slice it "
                "in your slicer (e.g. Creality Print) with your printer profile, then load the "
                "result as the Creality Template in Step 3 below.")
        tk.Label(content, text=desc, bg=SURFACE, fg=MUTED, font=FSM,
                 wraplength=900, justify='left').pack(fill='x', pady=(4, 8), anchor='w')

        row2 = tk.Frame(content, bg=SURFACE)
        row2.pack(fill='x')
        self.stl_btn = tk.Button(
            row2, text='📦  Generate & Save STL', bg=SURFACE2, fg=DIM, font=FBT,
            bd=0, pady=7, padx=14, cursor='arrow', relief='flat', state='disabled',
            activebackground=STL_DRK, activeforeground=WHITE,
            command=self._generate_stl)
        self.stl_btn.pack(side='left')
        self.stl_btn.bind('<Enter>', lambda e: self.stl_btn.configure(bg=STL_DRK)
                          if str(self.stl_btn['state'])=='normal' else None)
        self.stl_btn.bind('<Leave>', lambda e: self.stl_btn.configure(bg=STL_CLR)
                          if str(self.stl_btn['state'])=='normal' else None)

        self.stl_dim_var = tk.StringVar(value='Load a FullControl file above to enable this.')
        tk.Label(row2, textvariable=self.stl_dim_var, bg=SURFACE, fg=DIM,
                 font=FSM).pack(side='left', padx=(12, 0))

    def _build_centering_panel(self, parent):
        """Auto-centering configuration panel with a live preview."""
        # Frame with a colored (emerald) left border
        wrapper = tk.Frame(parent, bg=CTR_CLR)
        wrapper.pack(fill='x', pady=(10, 0))
        inner_bg = tk.Frame(wrapper, bg=SURFACE)
        inner_bg.pack(fill='both', expand=True, padx=(3, 0))

        content = tk.Frame(inner_bg, bg=SURFACE)
        content.pack(fill='x', padx=14, pady=10)

        # ── Row 1: checkbox + title ──
        row1 = tk.Frame(content, bg=SURFACE)
        row1.pack(fill='x')
        self._center_cb = tk.Checkbutton(
            row1, text='🎯  Automatically center the toolpath on the bed',
            variable=self.opt_center, bg=SURFACE, fg=TEXT,
            selectcolor=SURFACE2, activebackground=SURFACE, activeforeground=TEXT,
            font=(_FF, 10, 'bold'), cursor='hand2', bd=0,
            command=self._on_center_toggle)
        self._center_cb.pack(side='left')
        tk.Label(row1,
                 text='  (only X and Y are shifted — Z stays untouched)',
                 bg=SURFACE, fg=DIM, font=FSM).pack(side='left')

        # ── Row 2: bed size inputs ──
        self._bed_cfg = tk.Frame(content, bg=SURFACE)
        self._bed_cfg.pack(fill='x', pady=(6, 0))

        tk.Label(self._bed_cfg, text='Printer bed size:',
                 bg=SURFACE, fg=MUTED, font=FSM).pack(side='left', padx=(20, 10))

        for label, var, unit in [('Width', self.bed_w, ' mm  ×  '),
                                  ('Depth', self.bed_h, ' mm')]:
            tk.Label(self._bed_cfg, text=label, bg=SURFACE, fg=MUTED,
                     font=FSM).pack(side='left', padx=(0, 4))
            e = tk.Entry(self._bed_cfg, textvariable=var, width=5, font=FMO,
                         bg=SURFACE2, fg=TEXT, insertbackground=TEXT, bd=0,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=CTR_CLR, justify='center')
            e.pack(side='left', padx=(0, 2))
            tk.Label(self._bed_cfg, text=unit, bg=SURFACE,
                     fg=MUTED, font=FSM).pack(side='left')

        # ── Row 3: preview (appears once a FullControl file is loaded) ──
        self.preview_var = tk.StringVar(value='')
        self.preview_lbl = tk.Label(content, textvariable=self.preview_var,
                                    bg=SURFACE, fg=CTR_CLR,
                                    font=(_FM, 9, 'bold'), anchor='w')
        self.preview_lbl.pack(fill='x', pady=(6, 0))

    def _on_center_toggle(self):
        if self.opt_center.get():
            self._bed_cfg.pack(fill='x', pady=(6, 0))
            self._update_center_preview()
        else:
            self._bed_cfg.pack_forget()
            self.preview_var.set('')

    def _update_center_preview(self):
        """Compute and display a live centering preview from the FullControl bounding box."""
        if not self.opt_center.get() or self._fc_bbox3d is None:
            return
        try:
            bw = float(self.bed_w.get() or 0)
            bh = float(self.bed_h.get() or 0)
            if bw <= 0 or bh <= 0:
                return
        except ValueError:
            return

        mn_x, mx_x, mn_y, mx_y, _mn_z, _mx_z = self._fc_bbox3d
        mw  = mx_x - mn_x;       mh  = mx_y - mn_y
        cx  = (mn_x + mx_x) / 2; cy  = (mn_y + mx_y) / 2
        ox  = bw / 2 - cx;       oy  = bh / 2 - cy
        sx  = '+' if ox >= 0 else ''; sy = '+' if oy >= 0 else ''

        # Check whether the model fits
        if mn_x + ox < -0.1 or mx_x + ox > bw + 0.1:
            self.preview_var.set(f'  ⚠ Model ({mw:.1f} mm) is wider than the bed ({bw:.0f} mm)!')
            self.preview_lbl.configure(fg=WARN)
        elif mn_y + oy < -0.1 or mx_y + oy > bh + 0.1:
            self.preview_var.set(f'  ⚠ Model ({mh:.1f} mm) is deeper than the bed ({bh:.0f} mm)!')
            self.preview_lbl.configure(fg=WARN)
        else:
            self.preview_var.set(
                f'  Model: {mw:.1f} × {mh:.1f} mm  |  '
                f'Offset: X{sx}{ox:.2f} Y{sy}{oy:.2f} mm  →  '
                f'Bed center ({bw/2:.0f}, {bh/2:.0f}) mm  ✓'
            )
            self.preview_lbl.configure(fg=CTR_CLR)

    # ── Thread-safe logging ─────────────────────────────────────────────────
    def _log(self, lvl, msg): self.log_q.put((lvl, msg))

    def _poll_log(self):
        d = {'info': self.log.add_info, 'success': self.log.add_success,
             'warning': self.log.add_warning, 'error': self.log.add_error,
             'head': self.log.add_head, 'center': self.log.add_center,
             'stl': self.log.add_stl}
        try:
            while True:
                lvl, msg = self.log_q.get_nowait()
                d.get(lvl, self.log.add_info)(msg)
        except queue.Empty: pass
        self.after(80, self._poll_log)

    # ── Update merge button state ───────────────────────────────────────────
    def _update_btn(self):
        ready = self.fc_data is not None and self.cr_data is not None
        if ready:
            self.merge_btn.configure(state='normal', bg=ACCENT, fg=WHITE, cursor='hand2')
            self.status_var.set('✅  Ready! Click the button above to merge and save your G-code.')
            self.status_lbl.configure(fg=SUCCESS)
        else:
            self.merge_btn.configure(state='disabled', bg=SURFACE2, fg=DIM, cursor='arrow')
            miss = [n for n, d in [('FullControl', self.fc_data), ('Creality template', self.cr_data)] if not d]
            self.status_var.set(f'Waiting for: {" & ".join(miss)}')
            self.status_lbl.configure(fg=DIM)

    # ── File loaders ──────────────────────────────────────────────────────────
    def _load_fc(self, path):
        self._log('head', f'Reading FullControl file: {Path(path).name}')
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            p = parse_fullcontrol(lines)
            self.fc_data          = p
            self.fc_card.filepath = path

            # Compute the 3D bounding box for the centering preview and the STL export
            bbox3d = find_bounding_box_3d(p.toolpath)
            self._fc_bbox3d = bbox3d

            fan_pct = round(p.fan_speed / 2.55)
            rows = [
                ('📐', 'Toolpath',   f'{len(p.toolpath)} lines',      SUCCESS),
                ('🌡', 'Hotend',     f'{p.extruder_temp}°C',           INFO),
                ('🛏', 'Bed',        f'{p.bed_temp}°C',                INFO),
                ('💨', 'Fan',        f'S{p.fan_speed} ({fan_pct}%)',   INFO),
            ]
            if bbox3d:
                mn_x, mx_x, mn_y, mx_y, mn_z, mx_z = bbox3d
                mw = mx_x - mn_x; mh = mx_y - mn_y; mz = mx_z - mn_z
                rows.append(('📏', 'Model size', f'{mw:.1f} × {mh:.1f} × {mz:.1f} mm', CTR_CLR))
            if p.has_primer:
                rows.append(('🖊', 'Primer', f'{len(p.primer)} lines', MUTED))

            self.fc_card.show_loaded(rows)
            self._log('success', f'FullControl loaded — {len(p.toolpath)} toolpath lines | '
                                f'{p.extruder_temp}°C | bed {p.bed_temp}°C')
            if bbox3d:
                mn_x, mx_x, mn_y, mx_y, mn_z, mx_z = bbox3d
                mw = mx_x - mn_x; mh = mx_y - mn_y; mz = mx_z - mn_z
                self._log('center',
                          f'Model bbox: X {mn_x:.2f}–{mx_x:.2f}  Y {mn_y:.2f}–{mx_y:.2f}  '
                          f'Z {mn_z:.2f}–{mx_z:.2f}  ({mw:.1f}×{mh:.1f}×{mz:.1f} mm)')
                self.stl_btn.configure(state='normal', bg=STL_CLR, fg=WHITE, cursor='hand2')
                self.stl_dim_var.set(f'Model size: {mw:.1f} × {mh:.1f} × {mz:.1f} mm — ready to export.')
            else:
                self.stl_btn.configure(state='disabled', bg=SURFACE2, fg=DIM, cursor='arrow')
                self.stl_dim_var.set('No XY coordinates found — cannot generate an STL.')
            if p.has_primer:
                self._log('info', f'FullControl primer detected ({len(p.primer)} lines)')
            for w in p.warnings: self._log('warning', w)
            self._update_center_preview()
            if self.cr_data: self._check_temp()
        except Exception as e:
            self._log('error', f'Failed to read FullControl file: {e}')
            self.fc_data = None; self._fc_bbox3d = None
            self.fc_card.reset()
            self.stl_btn.configure(state='disabled', bg=SURFACE2, fg=DIM, cursor='arrow')
            self.stl_dim_var.set('Load a FullControl file above to enable this.')
        self._update_btn()

    def _load_cr(self, path):
        self._log('head', f'Reading Creality file: {Path(path).name}')
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            p = parse_creality(lines)
            self.cr_data          = p
            self.cr_card.filepath = path
            temp_ok = self.fc_data is None or abs(self.fc_data.extruder_temp - p.extruder_temp) <= 10
            rows = [
                ('▶',  'Start seq', f'{len(p.start_seq)} lines', SUCCESS),
                ('⏹', 'End seq',    f'{len(p.end_seq)} lines',   SUCCESS),
                ('🌡', 'Hotend',     f'{p.extruder_temp}°C',
                 SUCCESS if temp_ok else WARN),
                ('🛏', 'Bed',        f'{p.bed_temp}°C',           INFO),
            ]
            if p.chamber_temp:
                rows.append(('📦', 'Chamber', f'{p.chamber_temp}°C', MUTED))
            self.cr_card.show_loaded(rows)
            self._log('success', f'Creality template loaded — start {len(p.start_seq)} lines | '
                                f'end {len(p.end_seq)} lines | {p.extruder_temp}°C')
            if self.fc_data: self._check_temp()
            for w in p.warnings: self._log('warning', w)
        except Exception as e:
            self._log('error', f'Failed to read Creality file: {e}')
            self.cr_data = None; self.cr_card.reset()
        self._update_btn()

    def _check_temp(self):
        if not self.fc_data or not self.cr_data: return
        td = abs(self.fc_data.extruder_temp - self.cr_data.extruder_temp)
        if td > 10:
            self._log('warning',
                      f'Hotend temperature differs: Creality={self.cr_data.extruder_temp}°C '
                      f'vs FullControl={self.fc_data.extruder_temp}°C — the printer will use '
                      f'the Creality temperature (set by the START_PRINT macro).')

    # ── STL EXPORT (Step 2) ──────────────────────────────────────────────────
    def _generate_stl(self):
        if not self.fc_data or not self._fc_bbox3d:
            messagebox.showwarning('No Model Loaded', 'Load a FullControl G-code file first (Step 1).')
            return

        min_x, max_x, min_y, max_y, min_z, max_z = self._fc_bbox3d
        w = max_x - min_x
        d = max_y - min_y
        h = max_z - min_z

        fc_stem   = Path(self.fc_card.filepath).stem
        save_path = filedialog.asksaveasfilename(
            title='Save Same-Size STL',
            defaultextension='.stl',
            initialfile=f'{fc_stem}_bbox.stl',
            filetypes=[('STL files', '*.stl'), ('All files', '*.*')])
        if not save_path:
            return

        try:
            generate_bbox_stl(save_path, w, d, h, model_name=fc_stem or 'model')
            self._log('stl', f'STL saved: {Path(save_path).name}  ({w:.1f} × {d:.1f} × {h:.1f} mm)')
            self._log('info', 'Import this STL into your slicer, slice it with your printer '
                              'profile, then load the resulting G-code as the Creality Template '
                              'in Step 3.')
            if messagebox.askyesno(
                'STL Saved 📦',
                f"Saved a placeholder box matching your model's size:\n\n"
                f'📄  {Path(save_path).name}\n'
                f'📏  {w:.1f} × {d:.1f} × {h:.1f} mm (W × D × H)\n\n'
                'Note: this is only a bounding-box stand-in for slicing — not a copy of your '
                'actual model geometry.\n\n'
                'Next: open it in your slicer (e.g. Creality Print), slice it with your '
                'printer profile, and load the resulting G-code as the Creality Template file '
                'in Step 3.\n\n'
                'Open the containing folder now?', icon='info'):
                folder = os.path.dirname(os.path.abspath(save_path))
                try:
                    if platform.system() == 'Windows':   os.startfile(folder)
                    elif platform.system() == 'Darwin':   subprocess.run(['open', folder])
                    else:                                  subprocess.run(['xdg-open', folder])
                except Exception: pass
        except Exception as e:
            self._log('error', f'Failed to generate STL: {e}')
            messagebox.showerror('STL Generation Failed', str(e))

    # ── MERGE (Step 4) ───────────────────────────────────────────────────────
    def _do_merge(self):
        if not self.fc_data or not self.cr_data:
            messagebox.showwarning('Not Ready', 'Please select both G-code files first.'); return

        errors = []
        if not self.cr_data.start_seq: errors.append('Creality start sequence is empty!')
        if not self.cr_data.end_seq:   errors.append('Creality end sequence is empty!')
        if not self.fc_data.toolpath:  errors.append('FullControl toolpath is empty!')
        if errors:
            messagebox.showerror('Validation Failed', '\n'.join(errors)); return

        # Validate bed size if centering is enabled
        bed_w = bed_h = 0.0
        if self.opt_center.get():
            try:
                bed_w = float(self.bed_w.get())
                bed_h = float(self.bed_h.get())
                if bed_w <= 0 or bed_h <= 0: raise ValueError()
            except ValueError:
                messagebox.showerror('Invalid Bed Size',
                    'Enter a valid bed size (positive numbers) or turn off auto-centering.')
                return

        # Save dialog
        fc_stem   = Path(self.fc_card.filepath).stem
        save_path = filedialog.asksaveasfilename(
            title='Save Merged G-code',
            defaultextension='.gcode',
            initialfile=f'merged_{fc_stem}.gcode',
            filetypes=[('GCode', '*.gcode'), ('All files', '*.*')])
        if not save_path: return

        # Lock the UI
        self.merge_btn.configure(state='disabled', bg=DIM,
                                 text='⏳   Merging…', cursor='arrow')
        self.status_var.set('Processing…')
        self.status_lbl.configure(fg=WARN)

        # Read option values in the main thread before entering the background thread
        do_center    = self.opt_center.get()
        skip_primer  = not self.opt_primer.get()
        incl_footer  = self.opt_footer.get()
        _bed_w, _bed_h = bed_w, bed_h

        def _run():
            try:
                self._log('head', '════ STARTING MERGE ════')
                self._log('info', f'Template    : {Path(self.cr_card.filepath).name}')
                self._log('info', f'FullControl : {Path(self.fc_card.filepath).name}')

                # ── Centering ──
                toolpath   = self.fc_data.toolpath
                center_info = CenterInfo()
                if do_center:
                    self._log('center', f'Calculating centering for a {_bed_w:.0f}×{_bed_h:.0f} mm bed…')
                    toolpath, center_info = apply_centering(toolpath, _bed_w, _bed_h)
                    if center_info.applied:
                        sx = '+' if center_info.offset_x >= 0 else ''
                        sy = '+' if center_info.offset_y >= 0 else ''
                        self._log('center',
                            f'Model: {center_info.model_w:.2f}×{center_info.model_h:.2f} mm')
                        self._log('center',
                            f'Original bbox: X {center_info.min_x:.2f}–{center_info.max_x:.2f}  '
                            f'Y {center_info.min_y:.2f}–{center_info.max_y:.2f}')
                        self._log('center',
                            f'Offset applied: X{sx}{center_info.offset_x:.4f}  '
                            f'Y{sy}{center_info.offset_y:.4f} mm')
                        self._log('center',
                            f'Model center after shift: ({_bed_w/2:.1f}, {_bed_h/2:.1f}) mm ✓')
                        for w in center_info.warnings:
                            self._log('warning', w)
                    else:
                        self._log('warning', f'Centering not applied: {center_info.reason}')
                else:
                    self._log('info', 'Auto-centering is disabled — original coordinates are used.')

                # ── Assemble ──
                out_lines = assemble_output(
                    cr_path=self.cr_card.filepath,
                    fc_path=self.fc_card.filepath,
                    cr=self.cr_data, fc=self.fc_data,
                    toolpath=toolpath,
                    skip_primer=skip_primer, include_footer=incl_footer,
                    center_info=center_info if do_center else None,
                    bed_w=_bed_w, bed_h=_bed_h)

                with open(save_path, 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write('\n'.join(out_lines) + '\n')

                n  = len(out_lines)
                kb = os.path.getsize(save_path) / 1024
                self._log('success', f'Saved      : {Path(save_path).name}')
                self._log('success', f'Stats      : {n:,} lines  |  {kb:.1f} KB')
                self._log('success',
                    f'Start seq: {len(self.cr_data.start_seq)} lines  |  '
                    f'Toolpath: {len(toolpath)} lines  |  '
                    f'End seq: {len(self.cr_data.end_seq)} lines')
                self._log('success', '════ DONE ════')
                self.after(0, lambda: self._on_done(save_path, n, kb, center_info, do_center))
            except Exception as exc:
                import traceback
                self._log('error', f'Merge failed: {exc}')
                self._log('error', traceback.format_exc().split('\n')[-2])
                self.after(0, self._on_fail)

        threading.Thread(target=_run, daemon=True).start()

    def _on_done(self, path, n, kb, ci, centered):
        self.merge_btn.configure(state='normal', bg=ACCENT, fg=WHITE,
                                 text='🔀   Step 4 — Merge & Save G-code', cursor='hand2')
        self.status_var.set(f'✅  Saved: {Path(path).name}  ({kb:.1f} KB)')
        self.status_lbl.configure(fg=SUCCESS)

        center_msg = ''
        if centered and ci.applied:
            sx = '+' if ci.offset_x >= 0 else ''
            sy = '+' if ci.offset_y >= 0 else ''
            center_msg = (f'\n\n🎯  Auto-centering applied:\n'
                         f'   Model {ci.model_w:.1f}×{ci.model_h:.1f} mm\n'
                         f'   Offset X{sx}{ci.offset_x:.2f}  Y{sy}{ci.offset_y:.2f} mm\n'
                         f'   Model center → ({ci.bed_cx:.0f}, {ci.bed_cy:.0f}) mm ✓')

        if messagebox.askyesno(
            'Success! 🎉',
            f'Your file has been saved!\n\n'
            f'📄  {Path(path).name}\n'
            f'📊  {n:,} lines  |  {kb:.1f} KB'
            f'{center_msg}\n\n'
            f'Open the containing folder?', icon='info'):
            folder = os.path.dirname(os.path.abspath(path))
            try:
                if platform.system() == 'Windows':   os.startfile(folder)
                elif platform.system() == 'Darwin':   subprocess.run(['open', folder])
                else:                                  subprocess.run(['xdg-open', folder])
            except Exception: pass

    def _on_fail(self):
        self.merge_btn.configure(state='normal', bg=ACCENT, fg=WHITE,
                                 text='🔀   Step 4 — Merge & Save G-code', cursor='hand2')
        self.status_var.set('❌  Merge failed — check the log for details')
        self.status_lbl.configure(fg=ERR)

    # ── Help dialog ───────────────────────────────────────────────────────────
    def _show_help(self):
        dlg = tk.Toplevel(self)
        dlg.title('Help — GCode Merger v4.0')
        dlg.configure(bg=SURFACE)
        dlg.geometry('640x580')
        dlg.resizable(False, False)
        dlg.geometry(f'+{self.winfo_x()+(self.winfo_width()-640)//2}'
                     f'+{self.winfo_y()+(self.winfo_height()-580)//2}')
        dlg.transient(self); dlg.grab_set()

        frm = tk.Frame(dlg, bg=SURFACE)
        frm.pack(fill='both', expand=True, padx=24, pady=20)
        tk.Label(frm, text='📖  User Guide — v4.0', bg=SURFACE,
                 fg=TEXT, font=FH1, anchor='w').pack(fill='x', pady=(0, 12))

        txt = tk.Text(frm, bg=SURFACE2, fg=TEXT, font=FB, wrap='word',
                      bd=0, padx=14, pady=10, relief='flat', state='normal',
                      highlightthickness=1, highlightbackground=BORDER)
        txt.pack(fill='both', expand=True)
        txt.tag_configure('h', foreground=INFO, font=(_FF, 10, 'bold'))
        txt.tag_configure('b', foreground=MUTED)
        txt.tag_configure('g', foreground=CTR_CLR)
        txt.tag_configure('o', foreground=STL_CLR)

        sections = [
            ('h', '🔵  Step 1 — FullControl File (.gcode)'),
            ('b', 'A .gcode file exported from FullControl.xyz. It contains a non-planar '
                  'toolpath with XYZ coordinates that vary layer by layer. This file has no '
                  'Creality K2 start/end sequence.'),
            ('o', '📦  Step 2 (Optional) — Generate a Same-Size STL'),
            ('b', "Don't already have a Creality-sliced file cut to this object's exact size? "
                  'Click "Generate & Save STL" after loading your FullControl file. This '
                  "creates a simple placeholder box matching your model's width, depth and "
                  'height — NOT a copy of the real geometry. Slice that box in Creality Print '
                  '(or any slicer) with your printer profile, then use the resulting G-code as '
                  'your Step 3 template.'),
            ('h', '🟣  Step 3 — Creality Print Template File (.gcode)'),
            ('b', 'A .gcode file from Creality Print sliced for an object of the SAME SIZE. It '
                  'supplies the START_PRINT, END_PRINT, chamber temperature, purge line, auto '
                  'bed-leveling, and all the other Klipper macros for the Creality K2.'),
            ('g', '🎯  Auto-Centering'),
            ('b', "The app automatically works out the bounding box of your FullControl "
                  "toolpath, then shifts it in X and Y so the model sits dead-center on the "
                  'bed.\n'
                  '• Only X and Y are shifted — Z is NEVER touched (critical for non-planar prints!)\n'
                  '• Only G0/G1 moves in absolute mode (G90) are modified\n'
                  '• A live preview appears once the FullControl file is loaded\n'
                  "• Enter your printer's real bed size (default: 260×260 mm for the K2)"),
            ('h', '⚠  Important Notes'),
            ('b', '• START_PRINT and END_PRINT are Creality Klipper macros — never remove them\n'
                  '• After merging, the printer un-retracts 1 mm (transition block) before printing\n'
                  '• If the FullControl temperature differs from the template, the printer will '
                  'use the Creality temperature\n'
                  '• The output file can be uploaded straight to the Creality K2 via USB, SD '
                  'card, or Creality Cloud\n'
                  '• The bounding-box STL from Step 2 is only a placeholder for slicing — '
                  "don't print it directly"),
        ]

        for tag, text in sections:
            txt.insert('end', f'\n{text}\n', tag)
        txt.configure(state='disabled')

        tk.Button(frm, text='Close', bg=ACCENT, fg=WHITE, font=FBT,
                  bd=0, pady=8, padx=24, cursor='hand2', relief='flat',
                  activebackground=A_LT, activeforeground=WHITE,
                  command=dlg.destroy).pack(pady=(14, 0))


if __name__ == '__main__':
    app = GCodeMergerApp()
    app.mainloop()