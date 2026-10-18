import Foundation
import CoreGraphics
import simd

public enum CaptureFraming {
    public static func centerCell(in bounds: CGRect) -> CGRect {
        CGRect(x: bounds.minX + bounds.width / 3, y: bounds.minY + bounds.height / 3,
               width: bounds.width / 3, height: bounds.height / 3)
    }
    public static func rawRegion(rect: CGRect, viewport: CGSize, displayTransform: CGAffineTransform) -> CGRect {
        guard viewport.width > 0, viewport.height > 0 else { return .zero }
        return CGRect(x: rect.minX / viewport.width, y: rect.minY / viewport.height,
                      width: rect.width / viewport.width, height: rect.height / viewport.height)
            .applying(displayTransform.inverted()).intersection(CGRect(x: 0, y: 0, width: 1, height: 1))
    }
}

public enum RepresentativeViews {
    /// First usable centered observation is the identity reference. Farthest-point
    /// sampling adds sharp views with new position/orientation, never time-only samples.
    public static func select(_ frames: [CaptureFrame], maximum: Int = 10) -> [CaptureFrame] {
        let usable = frames.filter { $0.quality.accepted && $0.quality.blurScore >= 8 && $0.trackingState == "normal" }
        guard let reference = usable.first, maximum > 0 else { return [] }
        var chosen = [reference]
        var remaining = usable.dropFirst().filter { $0.segmentID == reference.segmentID }
        while chosen.count < min(10, maximum) && !remaining.isEmpty {
            let ranked = remaining.map { frame in (frame, chosen.map { separation(frame, $0) }.min() ?? 0) }
            guard let best = ranked.max(by: { $0.1 < $1.1 }), best.1 >= 1 else { break }
            chosen.append(best.0); remaining.removeAll { $0.frameID == best.0.frameID }
        }
        return [reference] + chosen.dropFirst().sorted { $0.timestampS < $1.timestampS }
    }
    public static func separation(_ a: CaptureFrame, _ b: CaptureFrame) -> Double {
        let p = zip(a.worldCamera[12...14], b.worldCamera[12...14]).reduce(0) { $0 + pow($1.0 - $1.1, 2) }.squareRoot()
        let dot = zip(a.worldCamera[8...10], b.worldCamera[8...10]).reduce(0) { $0 + $1.0 * $1.1 }
        return max(p / 0.025, min(p / 0.008, acos(min(1, max(-1, dot))) / 0.12))
    }
}

public enum ObjectConsensus {
    /// Every vote already compares the view against the same reference instance.
    /// Category agreement alone cannot establish instance identity.
    public static func confirmed(_ detections: [JevDetection], anchor: CGPoint) -> [Int] {
        guard let reference = detections.first, let box = reference.box,
              anchor.x >= box.left, anchor.x <= box.right, anchor.y >= box.top, anchor.y <= box.bottom else { return [] }
        let matches = detections.indices.filter { detections[$0].box != nil && detections[$0].category == reference.category }
        return matches.count >= 3 && Double(matches.count) / Double(detections.count) >= 0.6 ? matches : []
    }
}
