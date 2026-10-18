import Foundation
import simd

/// Viewpoint coverage around a fixed, depth-selected target. Coverage does not
/// imply that texture, cavities, or small surface features have been recovered.
public struct ScanGuidance {
    public private(set) var covered = Set<Int>()
    private var previousDirection: SIMD3<Float>?
    public init() {}

    public mutating func update(camera: SIMD3<Float>, target: SIMD3<Float>, screenPoint: SIMD2<Float>,
                                sharp: Bool, tracking: Bool, reliableDepth: Bool, accepted: Bool) -> String {
        guard tracking else { return "Hold still. Point back at the object until tracking recovers." }
        guard sharp else { return "Hold still for a sharp photo. Add diffuse light if it stays blurry." }
        guard reliableDepth else { return "Depth is weak. Change your angle slightly and avoid glare." }
        let offset = camera - target, distance = simd_length(offset)
        guard distance.isFinite && distance > 0 else { return "Tap the object to set the scan center." }
        if screenPoint.x < 1.0/3 { return "Aim left to bring the object back into the box." }
        if screenPoint.x > 2.0/3 { return "Aim right to bring the object back into the box." }
        if screenPoint.y < 1.0/3 { return "Aim up to bring the object back into the box." }
        if screenPoint.y > 2.0/3 { return "Aim down to bring the object back into the box." }
        if distance < 0.18 { return "Move back slightly. Keep the small details in focus." }
        if distance > 0.60 { return "Move closer slowly, keeping the whole object in view." }
        let direction = offset / distance
        let azimuth = atan2(direction.x, direction.z)
        let elevation = asin(max(-1, min(1, direction.y)))
        let ring = elevation > 0.35 ? 2 : (elevation < -0.20 ? 0 : 1)
        let sector = min(11, max(0, Int((azimuth + .pi) / (2 * .pi) * 12)))
        if let previousDirection, simd_dot(previousDirection, direction) < cos(Float.pi / 12) {
            self.previousDirection = direction
            return "Move more slowly. Keep most of the previous view visible."
        }
        previousDirection = direction
        if accepted { covered.insert(ring * 12 + sector) }
        let ringCount = covered.filter { $0 / 12 == ring }.count
        if ringCount >= 9 {
            if ring != 2 && covered.filter({ $0 / 12 == 2 }).isEmpty {
                return "If upper surfaces are hidden, add a short higher pass and tilt down. Finish when the visible surfaces are covered."
            }
            if ring != 0 && covered.filter({ $0 / 12 == 0 }).isEmpty {
                return "If lower edges are hidden, add a short lower pass. Keep the object still; no second full circle is needed."
            }
            return "Review small ridges and recesses from several nearby angles. Unseen surfaces remain unknown."
        }
        // Increasing camera azimuth is a rightward orbit when facing the target.
        for step in 1...6 {
            if !covered.contains(ring * 12 + (sector + step) % 12) {
                return "Move right around the object slowly. Keep it centered and overlap each view."
            }
            if !covered.contains(ring * 12 + (sector - step + 12) % 12) {
                return "Move left around the object slowly. Keep it centered and overlap each view."
            }
        }
        return "Change height to see surfaces hidden from this angle."
    }
}
