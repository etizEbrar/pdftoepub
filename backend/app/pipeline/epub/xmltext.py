"""Text made safe to write into an EPUB's XML, whatever the PDF held.

One place, used for every string the package writes. Two gaps in the standard
library's escape() each failed a whole conversion at validation: it leaves
the double quote alone, so an image's alt text quoting a phrase --
'attention "Scaled Dot-Product Attention"' -- ended its attribute early; and
it passes control characters, which XML forbids outright, so a math font's
bracket pieces (U+0014) in one table cell made the chapter unreadable.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape as _escape

# Everything XML 1.0 does not allow in a document, whatever the escaping.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def xml_text(text: str) -> str:
    """The text without characters no XML document may contain."""
    return _NOT_XML.sub("", text)


def xml_escape(text: str, entities: dict[str, str] | None = None) -> str:
    """Escaped for element content and for a double-quoted attribute alike."""
    return _escape(xml_text(text), {'"': "&quot;", **(entities or {})})
