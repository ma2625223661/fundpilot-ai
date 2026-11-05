// Spreadsheet export done in the browser: values are the texts the page shows
// (signs, "—" and "待评估" included), never recalculated numbers.

/** RFC 4180 quoting; a leading = + - @ is escaped so spreadsheets do not run it as a formula. */
function cell(value: unknown) {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@]/.test(text) && !/^[+-]?\d/.test(text)) text = "'" + text;
  return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
}

export function toCsv(rows: unknown[][]) {
  return rows.map(row => row.map(cell).join(',')).join('\r\n');
}

/** Save text as a UTF-8 CSV with a byte-order mark, so Excel reads Chinese correctly. */
export function downloadCsv(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Give the browser a moment to start the download before releasing it.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
