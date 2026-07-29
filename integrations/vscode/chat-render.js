"use strict";

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInline(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2">$1</a>');
  return html;
}

function splitTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isTableSeparator(line) {
  return /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/.test(line.trim());
}

function renderMarkdown(source) {
  const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim();
      const body = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) { body.push(lines[i]); i += 1; }
      i += 1; // skip closing fence
      blocks.push(`<pre data-lang="${escapeHtml(lang)}"><code>${highlightCode(body.join("\n"), lang)}</code></pre>`);
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quoted = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { quoted.push(lines[i].replace(/^>\s?/, "")); i += 1; }
      blocks.push(`<blockquote>${renderInline(quoted.join(" "))}</blockquote>`);
      continue;
    }
    if (/^\|.*\|$/.test(line) && lines[i + 1] && isTableSeparator(lines[i + 1])) {
      const header = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\|.*\|$/.test(lines[i])) { rows.push(splitTableRow(lines[i])); i += 1; }
      const thead = `<thead><tr>${header.map((cell) => `<th>${renderInline(cell)}</th>`).join("")}</tr></thead>`;
      const tbody = `<tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`).join("")}</tbody>`;
      blocks.push(`<table>${thead}${tbody}</table>`);
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) { items.push(lines[i].replace(/^[-*]\s+/, "")); i += 1; }
      blocks.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) { items.push(lines[i].replace(/^\d+\.\s+/, "")); i += 1; }
      blocks.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
      continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6})\s+/.test(lines[i]) && !/^[-*]\s+/.test(lines[i]) && !/^\d+\.\s+/.test(lines[i]) && !/^>\s?/.test(lines[i])) {
      paragraph.push(lines[i]);
      i += 1;
    }
    blocks.push(`<p>${paragraph.map((paragraphLine) => renderInline(paragraphLine)).join("<br>")}</p>`);
  }
  return blocks.join("");
}

const KEYWORDS = {
  js: ["const", "let", "var", "function", "return", "if", "else", "for", "while", "async", "await", "class", "import", "export", "from", "new", "try", "catch"],
  ts: ["const", "let", "var", "function", "return", "if", "else", "for", "while", "async", "await", "class", "import", "export", "from", "new", "try", "catch", "interface", "type"],
  python: ["def", "return", "if", "elif", "else", "for", "while", "import", "from", "class", "try", "except", "with", "as", "lambda", "async", "await"],
  bash: ["if", "then", "else", "fi", "for", "do", "done", "while", "function", "export", "local"],
  yaml: [],
  json: [],
};
KEYWORDS.javascript = KEYWORDS.js;
KEYWORDS.typescript = KEYWORDS.ts;
KEYWORDS.py = KEYWORDS.python;
KEYWORDS.sh = KEYWORDS.bash;
KEYWORDS.shell = KEYWORDS.bash;

function highlightCode(code, lang) {
  const key = String(lang || "").toLowerCase();
  // Plain-object lookup falls through to Object.prototype for names like
  // "constructor" or "toString" — guard with hasOwn so those hit the
  // unknown-language fallback instead of crashing on a non-array value.
  const keywords = Object.hasOwn(KEYWORDS, key) ? KEYWORDS[key] : undefined;
  if (keywords === undefined) return escapeHtml(code);

  const html = escapeHtml(code);

  // Single pass: match strings, numbers, and keywords with one alternation
  // and wrap each match directly. Strings are tried first per position so
  // their contents (which may contain digits or keyword-looking text) are
  // consumed whole and never re-scanned by the number/keyword branches.
  // No intermediate placeholder text is ever inserted into the string, so
  // there's nothing for later matches to collide with or re-match.
  const kwAlt = keywords.length ? `|(?<kw>\\b(?:${keywords.join("|")})\\b)` : "";
  const pattern = new RegExp(
    `(?<quote>&#0*39;|'|"|&quot;)(?<str>[^'"&]*)\\k<quote>|(?<num>\\b\\d+(?:\\.\\d+)?\\b)${kwAlt}`,
    "g"
  );

  return html.replace(pattern, (match, ...rest) => {
    const groups = rest[rest.length - 1];
    if (groups.quote !== undefined) return `<span class="tok-str">${match}</span>`;
    if (groups.num !== undefined) return `<span class="tok-num">${match}</span>`;
    if (groups.kw !== undefined) return `<span class="tok-kw">${match}</span>`;
    return match;
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderMarkdown, renderInline, escapeHtml, highlightCode };
}
