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

nav[epub|type~="toc"] ol {
  list-style: none;
  margin-left: 0;
}

nav[epub|type~="toc"] li {
  margin-bottom: 0.5em;
}
"""
