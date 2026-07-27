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

const { highlightCode } = require("../chat-render");

test("highlightCode wraps a JS keyword", () => {
  assert.equal(highlightCode("const x = 1;", "js"), '<span class="tok-kw">const</span> x = <span class="tok-num">1</span>;');
});

test("highlightCode wraps a Python string", () => {
  assert.equal(highlightCode("x = 'hi'", "python"), "x = <span class=\"tok-str\">'hi'</span>");
});

test("highlightCode falls back to escaped text for unknown languages", () => {
  assert.equal(highlightCode("<tag>", "unknownlang"), "&lt;tag&gt;");
});

test("renderMarkdown renders a fenced code block via highlightCode", () => {
  const out = renderMarkdown("```js\nconst x = 1;\n```");
  assert.equal(out, '<pre data-lang="js"><code><span class="tok-kw">const</span> x = <span class="tok-num">1</span>;</code></pre>');
});

test("highlightCode wraps the class keyword alongside a number without collision", () => {
  assert.equal(
    highlightCode("class Foo { x = 1; }", "js"),
    '<span class="tok-kw">class</span> Foo { x = <span class="tok-num">1</span>; }'
  );
});

test("highlightCode survives a placeholder-shaped literal without corruption or leaking", () => {
  assert.equal(
    highlightCode('const __P_0__ = "hello";', "js"),
    '<span class="tok-kw">const</span> __P_0__ = <span class="tok-str">&quot;hello&quot;</span>;'
  );
  assert.equal(
    highlightCode('x = "__P_1__"; y = 5;', "js"),
    'x = <span class="tok-str">&quot;__P_1__&quot;</span>; y = <span class="tok-num">5</span>;'
  );
});

test("highlightCode falls back to escaped text for an Object.prototype-named fence language", () => {
  assert.equal(highlightCode("foo", "constructor"), "foo");
  assert.equal(highlightCode("<tag>", "constructor"), "&lt;tag&gt;");
});
