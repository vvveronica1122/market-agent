// Encode numbered JPEG or PNG frames into an H.264 MP4 with AVFoundation (macOS).
// Used by demo/capture.py: swift demo/frames_to_mp4.swift <frames-dir> <out.mp4> <fps> [bitrate]
import AVFoundation
import AppKit

let args = CommandLine.arguments
guard args.count >= 4, let fps = Int32(args[3]) else {
    print("usage: frames_to_mp4 <frames-dir> <out.mp4> <fps> [bitrate]")
    exit(1)
}
let dir = URL(fileURLWithPath: args[1])
let out = URL(fileURLWithPath: args[2])
let bitrate = args.count > 4 ? Int(args[4]) ?? 3_000_000 : 3_000_000
try? FileManager.default.removeItem(at: out)

let files = try FileManager.default.contentsOfDirectory(atPath: dir.path)
    .filter { $0.hasSuffix(".jpg") || $0.hasSuffix(".png") }.sorted()
guard let first = NSImage(contentsOf: dir.appendingPathComponent(files[0])),
      let firstCG = first.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("cannot read first frame"); exit(1)
}
let width = firstCG.width, height = firstCG.height

let writer = try AVAssetWriter(outputURL: out, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: bitrate,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    ],
])
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
])
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

for (i, name) in files.enumerated() {
    autoreleasepool {
        guard let image = NSImage(contentsOf: dir.appendingPathComponent(name)),
              let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil),
              let pool = adaptor.pixelBufferPool else { return }
        var buffer: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer)
        guard let pb = buffer else { return }
        CVPixelBufferLockBaseAddress(pb, [])
        let ctx = CGContext(data: CVPixelBufferGetBaseAddress(pb), width: width, height: height,
                            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(pb),
                            space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue)
        ctx?.draw(cg, in: CGRect(x: 0, y: 0, width: width, height: height))
        CVPixelBufferUnlockBaseAddress(pb, [])
        while !input.isReadyForMoreMediaData { usleep(1000) }
        adaptor.append(pb, withPresentationTime: CMTime(value: CMTimeValue(i), timescale: fps))
    }
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
if writer.status != .completed {
    print("failed: \(String(describing: writer.error))"); exit(1)
}
print("wrote \(files.count) frames, \(width)x\(height) at \(fps) fps -> \(out.path)")
