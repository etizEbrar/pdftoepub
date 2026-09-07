#!/usr/bin/env python3
"""Generate site/ from the Markdown in docs/.

The published pages and the repository documentation must not drift: the
privacy policy a user reads is a statement about how the software behaves, and
an out-of-date copy of it is worse than none. docs/ is the source; site/ is
generated, and regenerating is the only supported way to change it.

    python3 scripts/build-site.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

STYLE = """<style>
:root{--ink:#1a2a4f;--muted:#5b6478;--bg:#fbfbfa;--card:#fff;--line:#e6e8ee}
@media (prefers-color-scheme:dark){:root{--ink:#e8ecf5;--muted:#a2abbd;--bg:#12151c;--card:#1a1e27;--line:#2a303c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:44rem;margin:0 auto;padding:3rem 1.25rem}
h1{font-size:2rem;margin:0 0 .25rem;line-height:1.2}
h2{margin:2.5rem 0 .5rem;font-size:1.15rem}
.sub{color:var(--muted);margin:0 0 2rem}
nav a{display:inline-block;margin-right:1rem;color:var(--ink)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1.25rem;margin:1rem 0}
blockquote{border-left:3px solid var(--line);margin:1rem 0;padding:.25rem 0 .25rem 1rem;color:var(--muted)}
code{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:.1rem .3rem;font-size:.9em}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid var(--line);padding:.4rem .6rem;text-align:left;font-size:.95em}
footer{margin-top:3rem;color:var(--muted);font-size:.9rem;border-top:1px solid var(--line);padding-top:1rem}
</style>"""


def render_markdown(body: str) -> str:
    """A deliberately small Markdown subset — headings, lists, quotes, tables.

    Enough for these two documents and nothing more, so there is no dependency
    to keep current for a two-page site.
    """
    # The "before publishing" note is guidance for whoever edits the repo, not
    # something a reader of the published page should see.
    body = re.sub(r"^> \*\*Before publishing:\*\*.*?(?=\n\n)", "", body, flags=re.S | re.M)

    out: list[str] = []
    in_list = in_table = False
    for raw in body.split("\n"):
        line = raw.rstrip()

        if line.startswith("|") and set(line) <= set("|-: "):
            continue  # table separator row
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            out.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False

        if line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(line[2:])}</li>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if line:
                out.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")

    content = "\n".join(out)
    content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
    content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
    # [text](url) written by the author, un-escaped back into a real link.
    content = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2).replace("privacy-policy.md", "privacy.html").replace("privacy.md", "privacy.html").replace("support.md", "support.html")}">{m.group(1)}</a>',
        content,
    )
    return content


def page(title: str, source: Path, out: Path) -> None:
    out.write_text(
        f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — PDF to EPUB</title>
{STYLE}</head><body><div class="wrap">
<nav><a href="./">← PDF to EPUB</a></nav>
{render_markdown(source.read_text(encoding="utf-8"))}
<footer><p><a href="./">Home</a> · <a href="privacy.html">Privacy</a> · <a href="support.html">Support</a></p></footer>
</div></body></html>
""",
        encoding="utf-8",
    )
    print(f"  wrote {out.relative_to(ROOT)}")


def index(owner: str) -> None:
    (SITE / "index.html").write_text(
        f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDF to EPUB</title>
{STYLE}</head><body><div class="wrap">
<h1>PDF to EPUB</h1>
<p class="sub">Turn PDF books into reflowable EPUB3 ebooks.</p>
<nav><a href="privacy.html">Privacy Policy</a><a href="support.html">Support</a></nav>
<div class="card">
<h2>What it does</h2>
<p>PDF to EPUB rebuilds a PDF as a real ebook: text reflows to your screen,
chapters appear in the table of contents, and footnotes become tappable links.
It reads scanned books with OCR and keeps tables, formulas, poetry and
right-to-left text intact.</p>
</div>
<div class="card">
<h2>How your documents are handled</h2>
<p>Your PDF is sent to the conversion server only to produce your EPUB, and is
deleted as soon as the app has the result. There are no accounts, no tracking,
no ads, and <strong>no AI service</strong> is involved in the conversion — it is
deterministic software running on the server.</p>
<p>Details: <a href="privacy.html">Privacy Policy</a>.</p>
</div>
<footer><p>© <span id="y"></span> {html.escape(owner)} ·
<a href="privacy.html">Privacy</a> · <a href="support.html">Support</a></p></footer>
<script>document.getElementById('y').textContent=new Date().getFullYear()</script>
</div></body></html>
""",
        encoding="utf-8",
    )
    print("  wrote site/index.html")


if __name__ == "__main__":
    SITE.mkdir(exist_ok=True)
    index("Safiye Ebrar Etiz")
    page("Privacy Policy", ROOT / "docs/privacy-policy.md", SITE / "privacy.html")
    page("Support", ROOT / "docs/support.md", SITE / "support.html")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print("  wrote site/.nojekyll")
