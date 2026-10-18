import Foundation
import SwiftUI
import CoreImage
import ARKit
import ReverseCADCore

struct ObjectSelectionReference: Codable {
    var imagePath = "rgb/selection-reference.jpg"
    var imageSHA256: String
    var rawBox: [Double]
    var detection: JevDetection?
    var box: CGRect { CGRect(x:rawBox[0],y:rawBox[1],width:rawBox[2],height:rawBox[3]) }
    static func load(project: URL, capture: URL) throws -> Self? {
        let url=project.appendingPathComponent("object-selection.json")
        guard FileManager.default.fileExists(atPath:url.path) else{return nil}
        let value=try JSONDecoder().decode(Self.self,from:Data(contentsOf:url))
        guard value.rawBox.count == 4, value.rawBox.allSatisfy(\.isFinite), value.box.minX>=0, value.box.minY>=0,
              value.box.maxX<=1.000001,value.box.maxY<=1.000001,value.box.width>0,value.box.height>0,
              value.detection.map({ SelectionBox.matches($0,selected:value.box) }) ?? true,
              try CaptureIO.sha256(file:CaptureIO.safeURL(directory:capture,path:value.imagePath)) == value.imageSHA256 else {
            throw ServiceFailure(message:"The saved selection no longer matches its reference image. Choose the object again.")
        }
        return value
    }
}

@MainActor final class BoxObjectIdentifier: ObservableObject {
    @Published var running=false
    @Published var message=""
    @Published var failure: String?
    @Published var reference: ObjectSelectionReference?
    private(set) var originalJPEG: Data?
    private var task: Task<Void,Never>?
    private var epoch=UUID()
    private var retryDate=Date.distantPast
    private let clientFactory: () -> JevClient
    private let keyProvider: () throws -> String
    init(clientFactory: @escaping () -> JevClient = { JevClient() },keyProvider: @escaping () throws -> String = { try ReverseCADJevConfiguration.apiKey() }) {
        self.clientFactory=clientFactory;self.keyProvider=keyProvider
    }
    func cancel(clear: Bool = false) {
        epoch=UUID();task?.cancel();task=nil;running=false
        if clear {reference=nil;originalJPEG=nil;failure=nil}
    }
    func identify(jpeg: Data, rawBox: CGRect, description: String) {
        guard !running else{return}
        if Date()<retryDate {failure="Jev reached its request limit. Wait \(Int(ceil(retryDate.timeIntervalSinceNow))) seconds and retry.";return}
        cancel(clear:true);running=true;message="Finding your object…";let ticket=epoch
        task=Task {
            do {
                let data=try CapturedObjectWorkflow.requestImage(jpeg)
                let result=try await clientFactory().identifySavedView(jpeg:data,reference:data,description:description,
                    anchor:CGPoint(x:rawBox.midX,y:rawBox.midY),requestID:UUID(),apiKey:keyProvider(),referenceBox:rawBox)
                try Task.checkCancellation();guard epoch==ticket else{return}
                guard SelectionBox.matches(result,selected:rawBox) else {
                    throw ServiceFailure(message:"The box contains no clear single object. Adjust its edges and try again.")
                }
                originalJPEG=jpeg;reference=ObjectSelectionReference(imageSHA256:CaptureIO.sha256(jpeg),rawBox:[rawBox.minX,rawBox.minY,rawBox.width,rawBox.height],detection:result)
                message="Identified: " + result.category.replacingOccurrences(of:"_",with:" ")
            } catch {
                guard epoch==ticket else{return}
                if !(error is CancellationError) {failure=error.localizedDescription}
                if let jev=error as? JevClientError,case .rateLimited(let delay)=jev {retryDate=Date().addingTimeInterval(delay)}
            }
            if epoch==ticket {running=false;task=nil}
        }
    }
    func save(project: URL,capture: URL) throws {
        guard let reference,let originalJPEG else{throw ServiceFailure(message:"Identify the object inside the box first.")}
        let image=try CaptureIO.safeURL(directory:capture,path:reference.imagePath)
        try FileManager.default.createDirectory(at:image.deletingLastPathComponent(),withIntermediateDirectories:true)
        try originalJPEG.write(to:image,options:.atomic)
        try CaptureIO.atomicWrite(reference,to:project.appendingPathComponent("object-selection.json"))
    }
    static func fullImage(_ frame: ARFrame) throws -> Data {
        guard let data=CIContext().jpegRepresentation(of:CIImage(cvPixelBuffer:frame.capturedImage),colorSpace:CGColorSpaceCreateDeviceRGB(),options:[kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption:0.97]) else {
            throw ServiceFailure(message:"Wait for a clear camera image.")
        }
        return data
    }
}
