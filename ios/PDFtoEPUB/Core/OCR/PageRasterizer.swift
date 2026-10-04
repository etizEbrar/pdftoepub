import CoreGraphics
import Foundation

/// Renders one PDF page to a bitmap for Vision to read.
enum PageRasterizer {

    /// Resolution to rasterize at.
    ///
    /// The server uses 150 dpi with Tesseract, measured: 300 dpi peaked at
    /// 404 MB and read within 1% of the same words. Vision is given a little
    /// more because a phone has the memory for it and recognition quality on
    /// small Turkish diacritics — the dot of an ı, the cedilla of a ş — is the
    /// thing most worth paying for here.
    static let defaultDPI: Double = 200

    /// Greyscale on purpose: scanned book pages carry no colour information
    /// worth recognising, and one channel instead of four is a quarter of the
    /// peak memory on a page that can be 2000x2800.
    static func render(
        page: CGPDFPage, dpi: Double = defaultDPI
    ) -> (image: CGImage, displayed: CGSize)? {
        let cropBox = page.getBoxRect(.cropBox)
        guard cropBox.width > 0, cropBox.height > 0 else { return nil }

        let rotation = page.rotationAngle
        let displayed = PageGeometry.displayedSize(
            cropBox: cropBox, rotationDegrees: Int(rotation)
        )
        let scale = dpi / 72.0
        let pixelWidth = Int((displayed.width * scale).rounded())
        let pixelHeight = Int((displayed.height * scale).rounded())
        guard pixelWidth > 0, pixelHeight > 0 else { return nil }

        guard
            let context = CGContext(
                data: nil,
                width: pixelWidth,
                height: pixelHeight,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: CGColorSpaceCreateDeviceGray(),
                bitmapInfo: CGImageAlphaInfo.none.rawValue
            )
        else { return nil }

        // Scanned pages are mostly paper. Filling white first means a page
        // whose content does not cover its box reads as blank rather than as
        // black, which Vision would otherwise hunt for text in.
        context.setFillColor(gray: 1, alpha: 1)
        context.fill(CGRect(x: 0, y: 0, width: pixelWidth, height: pixelHeight))
        context.scaleBy(x: scale, y: scale)

        // `getDrawingTransform` applies the page's own rotation and fits the
        // crop box to the destination, so the bitmap is upright whatever the
        // page's rotation says — which is what both Vision and the server's
        // rotated `page.rect` assume.
        let destination = CGRect(origin: .zero, size: displayed)
        context.concatenate(
            page.getDrawingTransform(.cropBox, rect: destination, rotate: 0, preserveAspectRatio: true)
        )
        context.drawPDFPage(page)

        guard let image = context.makeImage() else { return nil }
        return (image, displayed)
    }
}
