// Minimal .xlsx writer: enough of SpreadsheetML for typed, formatted tables.
//
// An .xlsx file is a zip of a few XML parts. This writes them with inline
// strings (no shared-string table), one style per column type, a frozen
// header row, and an uncompressed ("stored") zip -- dashboard exports are
// small, so compression would not buy anything. No dependencies.
//
//   const blob = buildXlsx([{ name, title, subtitle, columns: [{ label, type }], rows: [[...]] }]);
//
// Column types: "text", "int", "money", "pct" (a fraction: 0.153 -> 15.3%),
// "date" (ISO string or Date); a cell given as { v, t } overrides its column's
// type. null / undefined / NaN cells are left empty.
"use strict";

(function (global) {
  // Style indexes into cellXfs below.
  const STYLE = { text: 0, int: 1, money: 2, pct: 3, date: 4, header: 5, title: 6, note: 7 };

  const xml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c])
    // Control characters other than tab/newline are invalid in XML 1.0.
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");

  const colName = (i) => { let s = ""; for (i++; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s; return s; };

  // Excel's serial date: days since 1899-12-30 (UTC).
  const serial = (v) => { const t = (v instanceof Date ? v : new Date(v)).getTime(); return isNaN(t) ? null : t / 86400000 + 25569; };

  function cell(ref, value, type, style) {
    // A { v, t } cell overrides its column's type (mixed-unit columns).
    if (value != null && typeof value === "object" && !(value instanceof Date)) ({ v: value, t: type } = value);
    style ??= STYLE[type] ?? 0;
    if (value == null || (typeof value === "number" && !isFinite(value))) return "";
    if (type === "date") {
      const n = serial(value);
      return n == null ? "" : `<c r="${ref}" s="${style}"><v>${n}</v></c>`;
    }
    if (type === "int" || type === "money" || type === "pct") {
      const n = Number(value);
      return isFinite(n) ? `<c r="${ref}" s="${style}"><v>${n}</v></c>` : "";
    }
    return `<c r="${ref}" t="inlineStr" s="${style}"><is><t xml:space="preserve">${xml(value)}</t></is></c>`;
  }

  function sheetXml({ title, subtitle, columns, rows }) {
    const out = [];
    let r = 0;
    const row = (cells) => { r++; out.push(`<row r="${r}">${cells.join("")}</row>`); };
    row([cell(`A${r + 1}`, title, "text", STYLE.title)]);
    row([cell(`A${r + 1}`, subtitle, "text", STYLE.note)]);
    const headerRow = r + 1;
    row(columns.map((c, i) => cell(`${colName(i)}${headerRow}`, c.label, "text", STYLE.header)));
    for (const values of rows) {
      const n = r + 1;
      row(columns.map((c, i) => cell(`${colName(i)}${n}`, values[i], c.type)));
    }
    // Width from the longest rendered value, within sensible bounds.
    const widths = columns.map((c, i) => {
      const text = (x) => (x != null && typeof x === "object" && !(x instanceof Date) ? x.v : x);
      const longest = rows.reduce((m, v) => Math.max(m, text(v[i]) == null ? 0 : String(text(v[i])).length), c.label.length);
      const floor = { money: 14, date: 17, pct: 9, int: 9, auto: 14 }[c.type] || 8;
      return Math.min(60, Math.max(floor, longest + 2));
    });
    const last = `${colName(columns.length - 1)}${Math.max(headerRow, r)}`;
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<dimension ref="A1:${last}"/>
<sheetViews><sheetView workbookViewId="0"><pane ySplit="${headerRow}" topLeftCell="A${headerRow + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<cols>${widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("")}</cols>
<sheetData>${out.join("")}</sheetData>
${rows.length ? `<autoFilter ref="A${headerRow}:${last}"/>` : ""}
</worksheet>`;
  }

  const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00"/><numFmt numFmtId="165" formatCode="0.0%"/><numFmt numFmtId="166" formatCode="yyyy-mm-dd hh:mm"/></numFmts>
<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font><font><i/><sz val="10"/><color rgb="FF52514E"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF3F2EE"/></patternFill></fill></fills>
<borders count="2"><border/><border><bottom style="thin"><color rgb="FFC3C2B7"/></bottom></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

  // Sheet names: max 31 chars, none of []:*?/\ , unique (case-insensitive).
  function sheetNames(sheets) {
    const used = new Set();
    return sheets.map((s, i) => {
      let base = String(s.name || `Sheet${i + 1}`).replace(/[[\]:*?/\\]/g, " ").trim().slice(0, 31) || `Sheet${i + 1}`;
      let name = base, n = 2;
      while (used.has(name.toLowerCase())) name = `${base.slice(0, 31 - String(n).length - 1)} ${n++}`;
      used.add(name.toLowerCase());
      return name;
    });
  }

  function parts(sheets) {
    const names = sheetNames(sheets);
    const files = {
      "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
${names.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("\n")}
</Types>`,
      "_rels/.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
      "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>${names.map((n, i) => `<sheet name="${xml(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("")}</sheets>
${sheets.some((s) => s.rows.length) ? `<definedNames>${sheets.map((s, i) => s.rows.length
    ? `<definedName name="_xlnm._FilterDatabase" localSheetId="${i}" hidden="1">'${xml(names[i].replace(/'/g, "''"))}'!$A$3:$${colName(s.columns.length - 1)}$${s.rows.length + 3}</definedName>` : "").join("")}</definedNames>` : ""}
</workbook>`,
      "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
${names.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("\n")}
<Relationship Id="rId${names.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
      "xl/styles.xml": STYLES,
    };
    sheets.forEach((s, i) => { files[`xl/worksheets/sheet${i + 1}.xml`] = sheetXml(s); });
    return files;
  }

  // ---- stored (uncompressed) zip
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  const crc32 = (bytes) => { let c = 0xffffffff; for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };

  function zip(files) {
    const enc = new TextEncoder();
    const chunks = [], central = [];
    let offset = 0;
    // DOS date/time for "now" (zip timestamps are local time, 2-second resolution).
    const d = new Date();
    const dosTime = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    const dosDate = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    for (const [name, text] of Object.entries(files)) {
      const nameBytes = enc.encode(name), data = enc.encode(text), crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true); // UTF-8 names
      local.setUint16(8, 0, true); local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
      local.setUint16(26, nameBytes.length, true); local.setUint16(28, 0, true);
      chunks.push(local, nameBytes, data);
      const cd = new DataView(new ArrayBuffer(46));
      cd.setUint32(0, 0x02014b50, true); cd.setUint16(4, 20, true); cd.setUint16(6, 20, true); cd.setUint16(8, 0x0800, true);
      cd.setUint16(10, 0, true); cd.setUint16(12, dosTime, true); cd.setUint16(14, dosDate, true);
      cd.setUint32(16, crc, true); cd.setUint32(20, data.length, true); cd.setUint32(24, data.length, true);
      cd.setUint16(28, nameBytes.length, true); cd.setUint32(42, offset, true);
      central.push(cd, nameBytes);
      offset += 30 + nameBytes.length + data.length;
    }
    const cdSize = central.reduce((s, c) => s + c.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    const count = Object.keys(files).length;
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, count, true); end.setUint16(10, count, true);
    end.setUint32(12, cdSize, true); end.setUint32(16, offset, true);
    return new Blob([...chunks, ...central, end], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }

  global.buildXlsx = (sheets) => zip(parts(sheets));
})(window);
