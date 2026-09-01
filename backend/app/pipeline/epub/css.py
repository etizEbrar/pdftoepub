DEFAULT_STYLESHEET = """\
@charset "utf-8";

html, body {
  margin: 0;
  padding: 0;
}

body {
  font-family: serif;
  line-height: 1.5;
  margin: 0 5%;
}

h1, h2, h3, h4 {
  font-family: sans-serif;
  line-height: 1.2;
  margin-top: 1.4em;
  margin-bottom: 0.6em;
  page-break-after: avoid;
}

h1 { font-size: 1.6em; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.15em; }
h4 { font-size: 1.05em; }

p {
  margin: 0 0 1em 0;
  text-align: justify;
  orphans: 2;
  widows: 2;
}

blockquote {
  margin: 1em 1.5em;
  font-style: italic;
}

ul, ol {
  margin: 0 0 1em 1.5em;
  padding: 0;
}

li {
  margin-bottom: 0.4em;
}

figure {
  margin: 1.5em 0;
  text-align: center;
}

figure img {
  max-width: 100%;
  height: auto;
}

figcaption {
  font-size: 0.85em;
  font-style: italic;
  margin-top: 0.5em;
}

sup {
  font-size: 0.7em;
  line-height: 0;
}

a.noteref {
  text-decoration: none;
  font-weight: bold;
}

aside[epub|type~="footnote"] {
  font-size: 0.9em;
  margin: 0.8em 0;
  padding-left: 0.5em;
  border-left: 2px solid #ccc;
}

/* A note-shaped block that nothing in the text refers to. Set like a note, but
   an ordinary paragraph, so a reading system that hides unopened footnotes
   cannot make it unreachable. */
p.note-unlinked {
  font-size: 0.9em;
  margin: 0.8em 0;
  padding-left: 0.5em;
  border-left: 2px solid #ddd;
  text-indent: 0;
}

nav[epub|type~="toc"] ol {
  list-style: none;
  margin-left: 0;
}

nav[epub|type~="toc"] li {
  margin-bottom: 0.5em;
}

/* Poetry. Line breaks are real <br/> elements and indentation is a relative
   em step, so the text still reflows when the reader changes font size. */
p.verse {
  margin: 1em 0;
  text-align: left;
  text-indent: 0;
  white-space: normal;
}

p.verse span {
  display: inline-block;
}

p.verse .indent-1 { margin-left: 1.5em; }
p.verse .indent-2 { margin-left: 3em; }
p.verse .indent-3 { margin-left: 4.5em; }
p.verse .indent-4 { margin-left: 6em; }

/* Tables: keep them readable on narrow screens without fixed pixel widths. */
table {
  border-collapse: collapse;
  margin: 1em 0;
  max-width: 100%;
  font-size: 0.9em;
}

th, td {
  border: 1px solid #999;
  padding: 0.35em 0.5em;
  text-align: left;
  vertical-align: top;
}

th {
  background: #eee;
  font-weight: bold;
}

caption {
  caption-side: top;
  font-size: 0.85em;
  font-style: italic;
  margin-bottom: 0.4em;
  text-align: left;
}

hr.scene-break {
  border: none;
  border-top: 1px solid currentColor;
  opacity: 0.35;
  width: 30%;
  margin: 1.6em auto;
}

div.equation {
  margin: 1em 0;
  text-align: center;
}

/* A source region preserved verbatim because reconstruction wasn't safe. */
figure.preserved-region {
  margin: 1.2em 0;
  text-align: center;
  page-break-inside: avoid;
}

figure.preserved-region img {
  max-width: 100%;
  height: auto;
}

a.noteback {
  text-decoration: none;
}

aside[epub|type~="endnote"] {
  font-size: 0.9em;
  margin: 0.8em 0;
  padding-left: 0.5em;
  border-left: 2px solid #ccc;
}

/* RTL: mirror the padding/border side so notes and quotes read correctly. */
[dir="rtl"] blockquote {
  margin: 1em 1.5em;
}

[dir="rtl"] aside[epub|type~="footnote"],
[dir="rtl"] aside[epub|type~="endnote"] {
  padding-left: 0;
  padding-right: 0.5em;
  border-left: none;
  border-right: 2px solid #ccc;
}

[dir="rtl"] th,
[dir="rtl"] td,
[dir="rtl"] caption,
[dir="rtl"] p.verse {
  text-align: right;
}

[dir="rtl"] p.verse .indent-1 { margin-left: 0; margin-right: 1.5em; }
[dir="rtl"] p.verse .indent-2 { margin-left: 0; margin-right: 3em; }
[dir="rtl"] p.verse .indent-3 { margin-left: 0; margin-right: 4.5em; }
[dir="rtl"] p.verse .indent-4 { margin-left: 0; margin-right: 6em; }

[dir="rtl"] ul, [dir="rtl"] ol {
  margin-left: 0;
  margin-right: 1.5em;
}
"""
