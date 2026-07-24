/* ══════════════════════════════════════════════════════════════════════
   GCode Merger — Creality K2 × FullControl (browser edition)
   Everything runs entirely client-side.
   ══════════════════════════════════════════════════════════════════════ */

'use strict';

/* ── Regex patterns ──────────────────────────────────────────────────── */
const PAT_EXEC_START = /^;\s*EXECUTABLE_BLOCK_START\s*$/;
const PAT_EXEC_END   = /^;\s*EXECUTABLE_BLOCK_END\s*$/;
const PAT_THUMB_S    = /^;\s*THUMBNAIL_BLOCK_START\s*$/;
const PAT_THUMB_E    = /^;\s*THUMBNAIL_BLOCK_END\s*$/;
const PAT_EXC_DEF    = /^EXCLUDE_OBJECT_DEFINE\b/;
const PAT_EXC_S      = /^EXCLUDE_OBJECT_START\b/;
const PAT_EXC_E      = /^EXCLUDE_OBJECT_END\b/;
const PAT_SP_TEMPS   = /START_PRINT.*EXTRUDER_TEMP=(\d+).*BED_TEMP=(\d+)/i;
const PAT_CHAMBER    = /M141\s+S(\d+)/;
const PAT_TEMP_BED   = /M(?:190|140)\s+S(\d+)/;
const PAT_TEMP_HOT   = /M(?:109|104)\s+S(\d+)/;
const PAT_FAN        = /M106\s+S(\d+)/;
const PAT_M73        = /^M73\b/;
const PAT_OBJ_ID     = /^;\s*OBJECT_ID:/;
const PAT_TIME_EL    = /^;TIME_ELAPSED:/;
const PAT_FC_PRIM_S  = /;\s*START OF PRIMER PROCEDURE/;
const PAT_FC_PRIM_E  = /;\s*END OF PRIMER PROCEDURE/;
const PAT_FC_FOOTER  = /^;\s*model\s*:/i;
const PAT_FC_SEP     = /^;-{3,}\s*$/;
const PAT_MOVE       = /^G[01]\b/i;
const PAT_G90        = /^G90\b/i;
const PAT_G91        = /^G91\b/i;

/* ══════════════════════════════════════════════════════════════════════
   PARSER — Creality Print
   ══════════════════════════════════════════════════════════════════════ */
function parseCreality(lines) {
  const r = {
    header: [], startSeq: [], endSeq: [],
    extruderTemp: 220, bedTemp: 50, chamberTemp: 35,
    warnings: [],
  };
  let execS = -1, firstExcS = -1, lastExcE = -1, execE = -1;
  let inThumb = false;

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const s = raw.trim();
    if (PAT_THUMB_S.test(s)) { inThumb = true; continue; }
    if (PAT_THUMB_E.test(s)) { inThumb = false; continue; }
    if (inThumb) continue;
    if (execS === -1 && !PAT_EXEC_START.test(s)) {
      if (s) r.header.push(raw.trimEnd());
      continue;
    }
    if (PAT_EXEC_START.test(s)) { execS = i; continue; }
    if (execS >= 0) {
      if (firstExcS === -1 && PAT_EXC_S.test(s)) firstExcS = i;
      if (PAT_EXC_E.test(s)) lastExcE = i;
      if (PAT_EXEC_END.test(s)) execE = i;
      const m = s.match(PAT_SP_TEMPS);
      if (m) { r.extruderTemp = parseInt(m[1], 10); r.bedTemp = parseInt(m[2], 10); }
      const m2 = s.match(PAT_CHAMBER);
      if (m2) r.chamberTemp = parseInt(m2[1], 10);
    }
  }

  if (execS >= 0 && firstExcS > execS) {
    for (let i = execS + 1; i < firstExcS; i++) {
      const s = lines[i].trim();
      if (PAT_EXC_DEF.test(s) || PAT_OBJ_ID.test(s) || PAT_TIME_EL.test(s)) continue;
      if (PAT_M73.test(s)) { r.startSeq.push('M73 P0 R0  ; reset progress'); continue; }
      r.startSeq.push(lines[i].trimEnd());
    }
  } else { r.warnings.push('Could not detect the start sequence using the EXECUTABLE_BLOCK method.'); }

  if (lastExcE >= 0 && execE > lastExcE) {
    for (let i = lastExcE + 1; i < execE; i++) {
      const s = lines[i].trim();
      if (PAT_M73.test(s)) { r.endSeq.push('M73 P100 R0  ; finished 100%'); continue; }
      r.endSeq.push(lines[i].trimEnd());
    }
  } else { r.warnings.push('Could not detect the end sequence using the EXECUTABLE_BLOCK method.'); }

  if (!r.startSeq.length) r.warnings.push('Start sequence is empty — is this really a Creality Print file?');
  if (!r.endSeq.length) r.warnings.push('End sequence is empty?');
  return r;
}

/* ══════════════════════════════════════════════════════════════════════
   PARSER — FullControl
   ══════════════════════════════════════════════════════════════════════ */
function parseFullControl(lines) {
  const r = {
    primer: [], toolpath: [], footer: [],
    extruderTemp: 210, bedTemp: 65, fanSpeed: 255,
    hasPrimer: false, warnings: [],
  };
  let st = 'preamble';
  for (const raw of lines) {
    const s = raw.trim();
    if (st === 'preamble') {
      if (PAT_FC_PRIM_S.test(s)) { st = 'primer'; r.hasPrimer = true; r.primer.push(raw.trimEnd()); continue; }
      if (PAT_MOVE.test(s)) { st = 'toolpath'; r.toolpath.push(raw.trimEnd()); continue; }
      const mB = s.match(PAT_TEMP_BED);
      if (mB && parseInt(mB[1], 10) > 0) r.bedTemp = parseInt(mB[1], 10);
      const mH = s.match(PAT_TEMP_HOT);
      if (mH && parseInt(mH[1], 10) > 0) r.extruderTemp = parseInt(mH[1], 10);
      const mF = s.match(PAT_FAN);
      if (mF) r.fanSpeed = parseInt(mF[1], 10);
    } else if (st === 'primer') {
      r.primer.push(raw.trimEnd());
      if (PAT_FC_PRIM_E.test(s)) st = 'between';
    } else if (st === 'between') {
      if (PAT_FC_SEP.test(s) || !s) continue;
      if (PAT_FC_FOOTER.test(s)) { st = 'footer'; r.footer.push(raw.trimEnd()); continue; }
      st = 'toolpath'; r.toolpath.push(raw.trimEnd());
    } else if (st === 'toolpath') {
      if (PAT_FC_FOOTER.test(s)) { st = 'footer'; r.footer.push(raw.trimEnd()); continue; }
      r.toolpath.push(raw.trimEnd());
    } else if (st === 'footer') {
      r.footer.push(raw.trimEnd());
    }
  }
  if (!r.toolpath.length) r.warnings.push('FullControl toolpath is empty.');
  return r;
}

/* ══════════════════════════════════════════════════════════════════════
   CENTERING & BOUNDING BOX
   ══════════════════════════════════════════════════════════════════════ */
function findBoundingBox3D(toolpath) {
  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  let inRel = false, foundXY = false, foundZ = false;

  for (const line of toolpath) {
    const code = line.split(';')[0].trim();
    if (!code) continue;
    const up = code.toUpperCase();
    if (PAT_G90.test(up)) { inRel = false; continue; }
    if (PAT_G91.test(up)) { inRel = true; continue; }
    if (inRel || !PAT_MOVE.test(up)) continue;

    for (const m of code.matchAll(/X([-+]?\d*\.?\d+)/g)) {
      const v = parseFloat(m[1]); minX = Math.min(minX, v); maxX = Math.max(maxX, v); foundXY = true;
    }
    for (const m of code.matchAll(/Y([-+]?\d*\.?\d+)/g)) {
      const v = parseFloat(m[1]); minY = Math.min(minY, v); maxY = Math.max(maxY, v); foundXY = true;
    }
    for (const m of code.matchAll(/Z([-+]?\d*\.?\d+)/g)) {
      const v = parseFloat(m[1]); minZ = Math.min(minZ, v); maxZ = Math.max(maxZ, v); foundZ = true;
    }
  }

  if (!foundXY) return null;
  if (!foundZ) { minZ = 0; maxZ = 0; }
  return { minX, maxX, minY, maxY, minZ, maxZ };
}

function applyCentering(toolpath, bedW, bedH) {
  const ci = {
    applied: false, reason: '',
    minX: 0, maxX: 0, minY: 0, maxY: 0,
    modelW: 0, modelH: 0, offsetX: 0, offsetY: 0,
    bedCx: bedW / 2, bedCy: bedH / 2,
    warnings: [],
  };
  const bbox = findBoundingBox3D(toolpath);
  if (!bbox) {
    ci.reason = 'No XY coordinates were found in the toolpath';
    return { toolpath, centerInfo: ci };
  }

  ci.minX = bbox.minX; ci.maxX = bbox.maxX; ci.minY = bbox.minY; ci.maxY = bbox.maxY;
  ci.modelW = ci.maxX - ci.minX; ci.modelH = ci.maxY - ci.minY;
  const origCx = (ci.minX + ci.maxX) / 2;
  const origCy = (ci.minY + ci.maxY) / 2;
  ci.offsetX = ci.bedCx - origCx;
  ci.offsetY = ci.bedCy - origCy;

  const newMinX = ci.minX + ci.offsetX, newMaxX = ci.maxX + ci.offsetX;
  const newMinY = ci.minY + ci.offsetY, newMaxY = ci.maxY + ci.offsetY;
  if (newMinX < -0.1 || newMaxX > bedW + 0.1) ci.warnings.push(`Model wider than bed.`);
  if (newMinY < -0.1 || newMaxY > bedH + 0.1) ci.warnings.push(`Model deeper than bed.`);

  const ox = ci.offsetX, oy = ci.offsetY;
  const newTp = [];
  let inRel = false;

  for (const line of toolpath) {
    const sc = line.indexOf(';');
    if (sc === 0) { newTp.push(line); continue; }
    const code = sc > 0 ? line.slice(0, sc) : line;
    const comment = sc > 0 ? line.slice(sc) : '';

    const up = code.trim().toUpperCase();
    if (PAT_G90.test(up)) { inRel = false; newTp.push(line); continue; }
    if (PAT_G91.test(up)) { inRel = true; newTp.push(line); continue; }
    if (inRel || !PAT_MOVE.test(up)) { newTp.push(line); continue; }

    let newCode = code.replace(/X([-+]?\d*\.?\d+)/g, (m, num) => `X${(parseFloat(num) + ox).toFixed(4)}`);
    newCode = newCode.replace(/Y([-+]?\d*\.?\d+)/g, (m, num) => `Y${(parseFloat(num) + oy).toFixed(4)}`);
    newTp.push(newCode + comment);
  }

  ci.applied = true;
  return { toolpath: newTp, centerInfo: ci };
}

function centeringHeaderBlock(ci, bedW, bedH) {
  const sx = ci.offsetX >= 0 ? '+' : '';
  const sy = ci.offsetY >= 0 ? '+' : '';
  return [
    '',
    '; ┌───────────────────────────────────────────────────────┐',
    '; │  AUTO-CENTERING — Coordinate Correction Summary       │',
    '; ├───────────────────────────────────────────────────────┤',
    `; │  Bed size        : ${bedW.toFixed(0)} × ${bedH.toFixed(0)} mm                        │`,
    `; │  Bed center      : (${ci.bedCx.toFixed(1)}, ${ci.bedCy.toFixed(1)}) mm                 │`,
    `; │  Original bbox   : X ${ci.minX.toFixed(3)}\u2013${ci.maxX.toFixed(3)}  Y ${ci.minY.toFixed(3)}\u2013${ci.maxY.toFixed(3)} │`,
    `; │  Offset applied  : X${sx}${ci.offsetX.toFixed(4)}  Y${sy}${ci.offsetY.toFixed(4)} mm      │`,
    '; └───────────────────────────────────────────────────────┘',
    '',
  ];
}

/* ══════════════════════════════════════════════════════════════════════
   STL EXPORT
   ══════════════════════════════════════════════════════════════════════ */
function generateBboxSTL(width, depth, height, modelName) {
  const w = Math.max(width, 0.01), d = Math.max(depth, 0.01), h = Math.max(height, 0.01);
  const name = (modelName || 'model').trim().replace(/\s+/g, '_') || 'model';
  const v = [
    [0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0],
    [0, 0, h], [w, 0, h], [w, d, h], [0, d, h],
  ];
  const tris = [
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [3, 6, 2], [3, 7, 6], [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5],
  ];
  function facetNormal(a, b, c) {
    const ax = v[b][0] - v[a][0], ay = v[b][1] - v[a][1], az = v[b][2] - v[a][2];
    const bx = v[c][0] - v[a][0], by = v[c][1] - v[a][1], bz = v[c][2] - v[a][2];
    let nx = ay * bz - az * by, ny = az * bx - ax * bz, nz = ax * by - ay * bx;
    const len = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1;
    return [nx / len, ny / len, nz / len];
  }
  let out = `solid ${name}\n`;
  for (const [a, b, c] of tris) {
    const [nx, ny, nz] = facetNormal(a, b, c);
    out += `  facet normal ${nx.toFixed(6)} ${ny.toFixed(6)} ${nz.toFixed(6)}\n    outer loop\n`;
    for (const idx of [a, b, c]) out += `      vertex ${v[idx][0].toFixed(4)} ${v[idx][1].toFixed(4)} ${v[idx][2].toFixed(4)}\n`;
    out += '    endloop\n  endfacet\n';
  }
  out += `endsolid ${name}\n`;
  return out;
}

/* ══════════════════════════════════════════════════════════════════════
   ASSEMBLER
   ══════════════════════════════════════════════════════════════════════ */
function buildTransition(cr, fc, skipPrimer) {
  const L = [
    '', '; ══════════════════════════════════════════════════════════',
    '; TRANSITION BLOCK — Creality K2 Start → FullControl Toolpath',
    '; ══════════════════════════════════════════════════════════',
    'G1 E1 F2400      ; un-retract 1mm (compensates the Creality retract)',
    'G92 E0           ; reset E counter to 0', ''
  ];
  if (fc.fanSpeed > 0) L.push(`M106 S${fc.fanSpeed}          ; enable fan`, '');
  if (skipPrimer) L.push('; FullControl primer SKIPPED');
  L.push('; ══════════════════════════════════════════════════════════', '');
  return L;
}

function assembleOutput(opts) {
  const { crName, fcName, cr, fc, toolpath, skipPrimer, includeFooter, centerInfo, bedW, bedH } = opts;
  let out = [
    '; ████████████████████████████████████████████████████████████████',
    '; GCode Merger Web v1.0 — Creality K2 + FullControl',
    `; Template     : ${crName}`,
    `; FullControl  : ${fcName}`,
    `; Hotend       : ${cr.extruderTemp}°C  |  Bed: ${cr.bedTemp}°C`,
    '; ████████████████████████████████████████████████████████████████',
    '', '; ╔══════════════════════════════════════════════════════════════╗',
    '; ║  SECTION 1 — CREALITY K2 START SEQUENCE                    ║',
    '; ╚══════════════════════════════════════════════════════════════╝', ''
  ];
  out = out.concat(cr.startSeq, ['']);
  
  if (!skipPrimer && fc.hasPrimer && fc.primer.length) {
    out.push('', '; ─── FullControl Primer Procedure ───', '');
    for (const ln of fc.primer) {
      if (!PAT_FC_PRIM_S.test(ln) && !PAT_FC_PRIM_E.test(ln)) out.push(ln);
    }
    out.push('G92 E0  ; reset E', '');
  }

  out = out.concat(buildTransition(cr, fc, skipPrimer));
  out.push(
    '; ╔══════════════════════════════════════════════════════════════╗',
    '; ║  SECTION 2 — FULLCONTROL TOOLPATH (non-planar)             ║',
    '; ╚══════════════════════════════════════════════════════════════╝', ''
  );
  if (centerInfo && centerInfo.applied) out = out.concat(centeringHeaderBlock(centerInfo, bedW, bedH));
  out = out.concat(toolpath, ['']);
  
  if (includeFooter && fc.footer.length) out = out.concat(['', '; === FullControl Info ==='], fc.footer, ['']);

  out.push(
    '', '; ╔══════════════════════════════════════════════════════════════╗',
    '; ║  SECTION 3 — CREALITY K2 END SEQUENCE                      ║',
    '; ╚══════════════════════════════════════════════════════════════╝', ''
  );
  out = out.concat(cr.endSeq, ['', '; ████ End of Merged G-code — Happy Printing! 🖨 ████']);
  return out;
}

/* ══════════════════════════════════════════════════════════════════════
   UI & PROGRESS INDICATOR
   ══════════════════════════════════════════════════════════════════════ */
const state = { fc: null, cr: null, fcFileName: '', crFileName: '', fcBBox: null };
const els = {};

function cacheEls() {
  const ids = [
    'fc-dropzone', 'fc-input', 'fc-empty', 'fc-loaded', 'fc-filename', 'fc-stats', 'fc-change',
    'cr-dropzone', 'cr-input', 'cr-empty', 'cr-loaded', 'cr-filename', 'cr-stats', 'cr-change',
    'stl-btn', 'stl-note', 'center-toggle', 'bed-width', 'bed-height',
    'opt-primer', 'opt-footer', 'merge-btn', 'merge-status',
    'log-output', 'log-clear', 'help-btn', 'help-overlay', 'help-close', 'toast-container'
  ];
  ids.forEach(id => { els[id.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = document.getElementById(id); });
}

function timeStamp() { const p = n => String(n).padStart(2, '0'); const d = new Date(); return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
function appLog(level, msg) {
  const icons = { info: 'i', success: '✓', warning: '!', error: '✕', head: '▸', center: '◎', stl: '▣' };
  const div = document.createElement('div');
  div.className = `log-line ${level === 'head' ? 'log-head-line' : `log-${level}`}`;
  div.textContent = `[${timeStamp()}]  ${icons[level] || 'i'}  ${msg}`;
  els.logOutput.appendChild(div);
  els.logOutput.scrollTop = els.logOutput.scrollHeight;
}

function showToast(type, title, message) {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<strong>${title}</strong><p>${message}</p><button class="toast-close">&times;</button>`;
  toast.querySelector('button').onclick = () => toast.remove();
  els.toastContainer.appendChild(toast);
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, 9000);
}

function renderStats(dlEl, rows) {
  dlEl.innerHTML = '';
  for (const [lbl, val, cls] of rows) {
    const dt = document.createElement('dt'), dd = document.createElement('dd');
    dt.textContent = lbl; dd.textContent = val;
    if (cls) dd.classList.add(cls);
    dlEl.appendChild(dt); dlEl.appendChild(dd);
  }
}

function baseName(filename) { return (filename || 'model').replace(/\.[^/.]+$/, ''); }

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error || new Error('Error reading file'));
    reader.readAsText(file);
  });
}

function downloadTextFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType || 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/* ── PROGRESS HANDLER ── */
function setStepComplete(stepNum, isComplete) {
  const panel = document.getElementById(`panel-step-${stepNum}`);
  const badge = document.getElementById(`badge-step-${stepNum}`);
  if (!panel || !badge) return;

  if (isComplete) {
    panel.classList.add('panel-complete');
    badge.textContent = '✓';
  } else {
    panel.classList.remove('panel-complete');
    badge.textContent = stepNum;
  }
}

/* ══════════════════════════════════════════════════════════════════════
   EVENT HANDLERS
   ══════════════════════════════════════════════════════════════════════ */
function setupDropzone(zone, input, onFile) {
  zone.onclick = () => input.click();
  zone.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } };
  input.onchange = () => { if (input.files[0]) onFile(input.files[0]); input.value = ''; };
  ['dragenter', 'dragover'].forEach(e => zone.addEventListener(e, ev => { ev.preventDefault(); zone.classList.add('dragover'); }));
  ['dragleave', 'dragend', 'drop'].forEach(e => zone.addEventListener(e, ev => { ev.preventDefault(); zone.classList.remove('dragover'); }));
  zone.addEventListener('drop', ev => { if (ev.dataTransfer.files[0]) onFile(ev.dataTransfer.files[0]); });
}

async function handleFcFile(file) {
  appLog('head', `Reading FullControl file: ${file.name}`);
  
  // Reset downstream steps if user uploads a new file
  setStepComplete(1, false);
  setStepComplete(2, false);
  setStepComplete(4, false);

  try {
    const text = (await readFileAsText(file)).replace(/^\uFEFF/, '');
    const fc = parseFullControl(text.split('\n'));
    state.fc = fc; state.fcFileName = file.name;
    const bbox = findBoundingBox3D(fc.toolpath);
    state.fcBBox = bbox;

    const rows = [['Toolpath', `${fc.toolpath.length} lines`], ['Hotend', `${fc.extruderTemp}°C`]];
    if (bbox) rows.push(['Model size', `${(bbox.maxX - bbox.minX).toFixed(1)} × ${(bbox.maxY - bbox.minY).toFixed(1)} × ${(bbox.maxZ - bbox.minZ).toFixed(1)} mm`, 'mint-text']);
    renderStats(els.fcStats, rows);

    els.fcFilename.textContent = file.name;
    els.fcEmpty.hidden = true; els.fcLoaded.hidden = false;
    
    if (bbox) {
      els.stlBtn.disabled = false;
      els.stlNote.textContent = `Model size: ${(bbox.maxX - bbox.minX).toFixed(1)} × ${(bbox.maxY - bbox.minY).toFixed(1)} mm. Ready to download STL.`;
    }

    setStepComplete(1, true); // Mark Step 1 as complete!

  } catch (err) {
    state.fc = null; els.fcLoaded.hidden = true; els.fcEmpty.hidden = false;
    els.stlBtn.disabled = true; els.stlNote.textContent = 'Load a FullControl file in Step 1 to enable this.';
  }
  updateMergeBtn();
}

async function handleCrFile(file) {
  appLog('head', `Reading Slicer Template: ${file.name}`);
  
  // Reset merge step if template is replaced
  setStepComplete(3, false);
  setStepComplete(4, false);

  try {
    const text = (await readFileAsText(file)).replace(/^\uFEFF/, '');
    state.cr = parseCreality(text.split('\n'));
    state.crFileName = file.name;

    renderStats(els.crStats, [['Start seq', `${state.cr.startSeq.length} lines`], ['Hotend', `${state.cr.extruderTemp}°C`]]);
    els.crFilename.textContent = file.name;
    els.crEmpty.hidden = true; els.crLoaded.hidden = false;

    setStepComplete(3, true); // Mark Step 3 as complete!

  } catch (err) { 
    state.cr = null; els.crLoaded.hidden = true; els.crEmpty.hidden = false; 
  }
  updateMergeBtn();
}

function onGenerateStl() {
  if (!state.fc || !state.fcBBox) return;
  const { minX, maxX, minY, maxY, minZ, maxZ } = state.fcBBox;
  const stem = baseName(state.fcFileName);
  const stlText = generateBboxSTL(maxX - minX, maxY - minY, maxZ - minZ, stem);
  downloadTextFile(`${stem}_placeholder.stl`, stlText, 'model/stl');
  appLog('stl', `STL downloaded: ${stem}_placeholder.stl`);

  setStepComplete(2, true); // Mark Step 2 as complete!
}

function updateMergeBtn() {
  const ready = !!(state.fc && state.cr);
  els.mergeBtn.disabled = !ready;
  els.mergeStatus.textContent = ready ? 'Ready! Click the button above to merge.' : 'Waiting for Step 1 & Step 3 files...';
  els.mergeStatus.className = `merge-status ${ready ? 'ready' : ''}`;
}

function onMerge() {
  if (!state.fc || !state.cr) return;
  setStepComplete(4, false); // Reset before run

  const doCenter = els.centerToggle.checked;
  const bedW = parseFloat(els.bedWidth.value) || 260, bedH = parseFloat(els.bedHeight.value) || 260;
  
  try {
    appLog('head', '════ STARTING MERGE ════');
    let toolpath = state.fc.toolpath, centerInfo = null;
    if (doCenter) {
      const res = applyCentering(toolpath, bedW, bedH);
      toolpath = res.toolpath; centerInfo = res.centerInfo;
      if (centerInfo.applied) appLog('center', `Centered on ${bedW}x${bedH} bed. Offset applied.`);
    }

    const content = assembleOutput({
      crName: state.crFileName, fcName: state.fcFileName,
      cr: state.cr, fc: state.fc, toolpath,
      skipPrimer: !els.optPrimer.checked, includeFooter: els.optFooter.checked,
      centerInfo: doCenter ? centerInfo : null, bedW, bedH,
    }).join('\n') + '\n';

    const filename = `merged_${baseName(state.fcFileName)}.gcode`;
    downloadTextFile(filename, content, 'text/x-gcode');
    
    appLog('success', `Saved: ${filename}`);
    showToast('success', `Downloaded ${filename}`, 'Merge successful. Check your downloads.');
    
    setStepComplete(4, true); // Mark Step 4 as complete!

  } catch (err) { 
    appLog('error', `Merge failed: ${err}`); 
  }
}

/* ══════════════════════════════════════════════════════════════════════
   INIT
   ══════════════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  cacheEls();
  setupDropzone(els.fcDropzone, els.fcInput, handleFcFile);
  setupDropzone(els.crDropzone, els.crInput, handleCrFile);
  
  // Event listeners for "Change file" buttons
  if(els.fcChange) els.fcChange.onclick = (e) => { e.stopPropagation(); els.fcInput.click(); };
  if(els.crChange) els.crChange.onclick = (e) => { e.stopPropagation(); els.crInput.click(); };

  els.stlBtn.onclick = onGenerateStl;
  els.mergeBtn.onclick = onMerge;
  els.logClear.onclick = () => els.logOutput.innerHTML = '';
  
  window.openHelp = () => { els.helpOverlay.hidden = false; document.body.style.overflow = 'hidden'; };
  window.closeHelp = () => { els.helpOverlay.hidden = true; document.body.style.overflow = ''; };
  els.helpBtn.onclick = openHelp;
  els.helpOverlay.onclick = e => { if (e.target === els.helpOverlay) closeHelp(); };
  
  updateMergeBtn();
});