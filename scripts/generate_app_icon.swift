#!/usr/bin/env swift
// Reproducible, code-native Reverse CAD icon. Run from the repository root:
//   swift scripts/generate_app_icon.swift
// Every PNG is opaque RGB; iOS applies its own mask at presentation time.
import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let output = URL(fileURLWithPath: "ios/ReverseCAD/Assets.xcassets", isDirectory: true)
let icons = output.appendingPathComponent("AppIcon.appiconset", isDirectory: true)
try FileManager.default.createDirectory(at: icons, withIntermediateDirectories: true)
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!

func color(_ hex: UInt32) -> CGColor {
    CGColor(colorSpace: colorSpace, components: [
        CGFloat((hex >> 16) & 255) / 255,
        CGFloat((hex >> 8) & 255) / 255,
        CGFloat(hex & 255) / 255, 1
    ])!
}

func polygon(_ context: CGContext, _ points: [(CGFloat, CGFloat)], _ fill: UInt32) {
    context.beginPath()
    context.move(to: CGPoint(x: points[0].0, y: points[0].1))
    for point in points.dropFirst() { context.addLine(to: CGPoint(x: point.0, y: point.1)) }
    context.closePath()
    context.setFillColor(color(fill))
    context.fillPath()
}

func render(pixels: Int, name: String) throws {
    let context = CGContext(data: nil, width: pixels, height: pixels, bitsPerComponent: 8,
                            bytesPerRow: pixels * 4, space: colorSpace,
                            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
    context.interpolationQuality = .high
    context.setShouldAntialias(true)
    context.translateBy(x: 0, y: CGFloat(pixels))
    context.scaleBy(x: CGFloat(pixels) / 1024, y: -CGFloat(pixels) / 1024)

    let background = CGGradient(colorsSpace: colorSpace,
                                colors: [color(0x142C48), color(0x071321)] as CFArray,
                                locations: [0, 1])!
    context.drawLinearGradient(background, start: CGPoint(x: 180, y: 0),
                               end: CGPoint(x: 800, y: 1024),
                               options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])

    // A measured isometric object, with the repaired rail clearly distinguished.
    // The slight separation at each plane preserves legibility at small sizes.
    polygon(context, [(512, 206), (788, 366), (512, 526), (236, 366)], 0x77CCF4)
    polygon(context, [(236, 374), (508, 532), (508, 846), (236, 688)], 0x288BCE)
    polygon(context, [(516, 532), (788, 374), (788, 688), (516, 846)], 0x145783)

    // Subtle planar facets suggest a reconstructed surface without visual noise.
    polygon(context, [(236, 374), (508, 532), (508, 690)], 0x3199D8)
    polygon(context, [(516, 690), (788, 532), (788, 688), (516, 846)], 0x1A6696)

    // A fitted orange corner replacement extends across the top edge and down.
    // A navy seating gap keeps replacement geometry distinct from observed blue.
    polygon(context, [(500, 193), (801, 367), (801, 583), (719, 631),
                      (719, 422), (418, 248)], 0x091B2D)
    polygon(context, [(512, 206), (788, 366), (728, 401), (452, 241)], 0xFFBA68)
    polygon(context, [(728, 401), (788, 366), (788, 576), (728, 611)], 0xFF843C)
    polygon(context, [(452, 241), (728, 401), (728, 424), (452, 264)], 0xED742F)

    let image = context.makeImage()!
    let destination = CGImageDestinationCreateWithURL(
        icons.appendingPathComponent(name) as CFURL,
        UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw NSError(domain: "ReverseCADIcon", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "Could not write \(name)"])
    }
}

struct IconSlot {
    let idiom: String
    let points: Double
    let scales: [Int]
}
let slots: [IconSlot] = [
    .init(idiom: "iphone", points: 20, scales: [2, 3]),
    .init(idiom: "iphone", points: 29, scales: [2, 3]),
    .init(idiom: "iphone", points: 40, scales: [2, 3]),
    .init(idiom: "iphone", points: 60, scales: [2, 3]),
    .init(idiom: "ipad", points: 20, scales: [1, 2]),
    .init(idiom: "ipad", points: 29, scales: [1, 2]),
    .init(idiom: "ipad", points: 40, scales: [1, 2]),
    .init(idiom: "ipad", points: 76, scales: [1, 2]),
    .init(idiom: "ipad", points: 83.5, scales: [2]),
    .init(idiom: "ios-marketing", points: 1024, scales: [1])
]
var images: [[String: String]] = []
var generated = Set<Int>()
for slot in slots {
    let side = slot.points.rounded() == slot.points ? String(Int(slot.points)) : String(slot.points)
    for scale in slot.scales {
        let pixels = Int(slot.points * Double(scale))
        let name = "AppIcon-\(pixels).png"
        if generated.insert(pixels).inserted { try render(pixels: pixels, name: name) }
        images.append(["idiom": slot.idiom, "size": "\(side)x\(side)",
                       "scale": "\(scale)x", "filename": name])
    }
}
let info: [String: Any] = ["author": "xcode", "version": 1]
try JSONSerialization.data(withJSONObject: ["images": images, "info": info], options: [.prettyPrinted, .sortedKeys])
    .write(to: icons.appendingPathComponent("Contents.json"))
try JSONSerialization.data(withJSONObject: ["info": info], options: [.prettyPrinted, .sortedKeys])
    .write(to: output.appendingPathComponent("Contents.json"))
print("Generated \(generated.count) opaque RGB PNGs for \(images.count) app icon slots.")
