"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { renderMarkdown } = require("../chat-render");

test("renderMarkdown escapes raw HTML", () => {
  assert.equal(renderMarkdown("<script>alert(1)</script>"), "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>");
});

test("renderMarkdown renders a heading", () => {
  assert.equal(renderMarkdown("## Title"), "<h2>Title</h2>");
});

test("renderMarkdown renders an unordered list", () => {
  assert.equal(renderMarkdown("- one\n- two"), "<ul><li>one</li><li>two</li></ul>");
});

test("renderMarkdown renders an ordered list", () => {
  assert.equal(renderMarkdown("1. one\n2. two"), "<ol><li>one</li><li>two</li></ol>");
});

test("renderMarkdown renders a link", () => {
  assert.equal(renderMarkdown("[docs](https://example.com)"), '<p><a href="https://example.com">docs</a></p>');
});

test("renderMarkdown rejects a non-http(s) link scheme", () => {
  assert.equal(renderMarkdown("[x](javascript:alert(1))"), "<p>[x](javascript:alert(1))</p>");
});

test("renderMarkdown renders bold and inline code", () => {
  assert.equal(renderMarkdown("**bold** and `code`"), "<p><strong>bold</strong> and <code>code</code></p>");
});

test("renderMarkdown renders a table", () => {
  const input = "| A | B |\n|---|---|\n| 1 | 2 |";
  assert.equal(
    renderMarkdown(input),
    "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
  );
});

test("renderMarkdown renders a blockquote", () => {
  assert.equal(renderMarkdown("> quoted"), "<blockquote>quoted</blockquote>");
});
