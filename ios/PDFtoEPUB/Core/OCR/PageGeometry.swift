import CoreGraphics
import Foundation

/// Mapping Vision's coordinates onto the page the server will see.
///
/// Three conventions meet here and none of them agree:
///
///  * Vision reports normalised rects, 0...1, with the origin at the *bottom*
///    left and y increasing upward.
///  * PDF boxes are in points with the origin at the bottom left of the media
///    box, and a page carries a separate rotation that viewers apply.
///  * The server's `Block.bbox` is in points with the origin at the *top* left
///    of the displayed page, y increasing downward.
///
/// Getting this wrong does not crash anything: it produces a book whose
/// paragraphs are assembled bottom-to-top, or whose headings are found in the
/// footer. So the arithmetic lives here on its own and is tested directly.
enum PageGeometry {

    /// The page size a reader sees, after the page's own rotation is applied.
    ///
    /// Must match the server's `page.rect`, which is also the rotated size — a
    /// 90°-rotated A4 page is 842x595 there, not 595x842.
    static func displayedSize(cropBox: CGRect, rotationDegrees: Int) -> CGSize {
        let quarterTurns = ((rotationDegrees % 360) + 360) % 360
        let swapped = quarterTurns == 90 || quarterTurns == 270
        return CGSize(
            width: swapped ? cropBox.height : cropBox.width,
            height: swapped ? cropBox.width : cropBox.height
        )
    }

    /// Convert one Vision rect into PDF points with a top-left origin.
    ///
    /// The y flip is the whole point: Vision's `minY` is the *bottom* of the
    /// glyph box, so the top edge the server wants is `1 - maxY`.
    static func pdfRect(fromNormalized rect: CGRect, displayed: CGSize) -> [Double] {
        let x0 = Double(rect.minX) * Double(displayed.width)
        let x1 = Double(rect.maxX) * Double(displayed.width)
        let top = (1.0 - Double(rect.maxY)) * Double(displayed.height)
        let bottom = (1.0 - Double(rect.minY)) * Double(displayed.height)
        // Clamped so a box that Vision puts a hair outside the page cannot
        // produce a negative coordinate the server would reject.
        return [
            max(0, min(x0, Double(displayed.width))),
            max(0, min(top, Double(displayed.height))),
            max(0, min(x1, Double(displayed.width))),
            max(0, min(bottom, Double(displayed.height))),
        ]
    }
}
