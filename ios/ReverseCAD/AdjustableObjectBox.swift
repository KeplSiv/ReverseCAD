import SwiftUI
import CoreGraphics
import ReverseCADCore

struct AdjustableObjectBox: View {
    @Binding var box: CGRect
    var editable = true
    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let rect = CGRect(x: box.minX*size.width, y: box.minY*size.height, width: box.width*size.width, height: box.height*size.height)
            ZStack {
                Rectangle().stroke(.white,lineWidth:2)
                    .frame(width:rect.width,height:rect.height).position(x:rect.midX,y:rect.midY)
                    .allowsHitTesting(false)
                if editable {
                    BoxDragHandle(box: $box, corner: .move, size: size)
                        .frame(width: max(44,rect.width-36),height:max(44,rect.height-36)).position(x:rect.midX,y:rect.midY)
                    ForEach(SelectionBoxCorner.corners, id: \.rawValue) { corner in
                        BoxDragHandle(box: $box,corner:corner,size:size)
                            .frame(width:44,height:44)
                            .position(x:(corner.isLeft ? box.minX:box.maxX)*size.width,y:(corner.isTop ? box.minY:box.maxY)*size.height)
                    }
                }
            }
        }
    }
}
private struct BoxDragHandle: View {
    @Binding var box: CGRect
    let corner: SelectionBoxCorner
    let size: CGSize
    @State private var initial: CGRect?
    var body: some View {
        ZStack {
            Color.white.opacity(0.001)
            if corner != .move { Circle().fill(.white).frame(width:15,height:15).shadow(radius:2) }
        }.contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance:0).onChanged { value in
                if initial == nil { initial=box }
                guard let initial,size.width>0,size.height>0 else{return}
                box = SelectionBox.adjust(initial,corner:corner,dx:value.translation.width/size.width,dy:value.translation.height/size.height)
            }.onEnded { _ in initial=nil })
            .accessibilityIdentifier("box_" + corner.rawValue)
            .accessibilityLabel(corner == .move ? "Move selection box" : "Resize \(corner.rawValue) of selection box")
            .accessibilityAdjustableAction { direction in
                let delta: Double = direction == .increment ? 0.025 : -0.025
                box = SelectionBox.adjust(box,corner:corner,dx:delta,dy:delta)
            }
    }
}
