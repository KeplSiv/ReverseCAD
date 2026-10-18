import SwiftUI
import CoreGraphics
import ReverseCADCore

struct AdjustableObjectBox: View {
    @Binding var box: CGRect
    var editable = true
    @Namespace private var dragSpace
    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let rect = CGRect(x: box.minX*size.width, y: box.minY*size.height, width: box.width*size.width, height: box.height*size.height)
            ZStack {
                Rectangle().stroke(.white.opacity(0.9), style: StrokeStyle(lineWidth: 2, dash: [18, 8]))
                    .frame(width:rect.width,height:rect.height).position(x:rect.midX,y:rect.midY)
                    .allowsHitTesting(false)
                if editable {
                    BoxDragHandle(box: $box, corner: .move, size: size, dragSpace: dragSpace)
                        .frame(width: max(44,rect.width-36),height:max(44,rect.height-36)).position(x:rect.midX,y:rect.midY)
                    ForEach(SelectionBoxCorner.corners, id: \.rawValue) { corner in
                        BoxDragHandle(box: $box,corner:corner,size:size,dragSpace:dragSpace)
                            .frame(width:44,height:44)
                            .position(x:(corner.isLeft ? box.minX:box.maxX)*size.width,y:(corner.isTop ? box.minY:box.maxY)*size.height)
                    }
                }
            }.frame(width: size.width, height: size.height)
        }
        // Handles move during a drag. Measure finger motion in their stationary
        // container, so updating the box cannot change the gesture's origin.
        .coordinateSpace(name: dragSpace)
    }
}
private struct BoxDragHandle: View {
    @Binding var box: CGRect
    let corner: SelectionBoxCorner
    let size: CGSize
    let dragSpace: Namespace.ID
    @State private var initial: (box: CGRect, size: CGSize)?
    @GestureState private var dragging = false
    var body: some View {
        ZStack {
            Color.white.opacity(0.001)
            if corner != .move { Circle().fill(RepairStyle.accent).frame(width:15,height:15)
                .overlay(Circle().stroke(.white, lineWidth: 1.5)).shadow(color: .black.opacity(0.5), radius: 2) }
        }.contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance:0,coordinateSpace:.named(dragSpace))
                .updating($dragging) { _, active, _ in active = true }
                .onChanged { value in
                    if initial == nil { initial = (box, size) }
                    update(translation: value.translation)
                }
                .onEnded { value in
                    update(translation: value.translation)
                    initial = nil
                })
            // onEnded is not called when the system cancels a gesture.
            .onChange(of: dragging) { _, active in if !active { initial = nil } }
            .accessibilityIdentifier("box_" + corner.rawValue)
            .accessibilityLabel(corner == .move ? "Move selection box" : "Resize \(corner.rawValue) of selection box")
            .accessibilityAdjustableAction { direction in
                let delta: Double = direction == .increment ? 0.025 : -0.025
                box = SelectionBox.adjust(box,corner:corner,dx:delta,dy:delta)
            }
    }
    private func update(translation: CGSize) {
        guard let initial,initial.size.width>0,initial.size.height>0 else{return}
        var transaction = Transaction(animation: nil)
        transaction.disablesAnimations = true
        withTransaction(transaction) {
            box = SelectionBox.adjust(initial.box,corner:corner,dx:translation.width/initial.size.width,dy:translation.height/initial.size.height)
        }
    }
}
