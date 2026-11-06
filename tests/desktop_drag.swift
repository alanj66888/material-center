import Cocoa
import UniformTypeIdentifiers

@main
struct DragChecks {
    static func main() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("原素材 with spaces.mp4")
        let destination = root.appendingPathComponent("拷贝.mp4")
        let contents = Data((0..<255).map { UInt8($0) })
        try contents.write(to: source)
        let delegate = FileDragView()
        let provider = OriginalFilePromise(fileType: UTType.mpeg4Movie.identifier, delegate: delegate)
        provider.originalURL = source
        provider.userInfo = source
        let board = NSPasteboard.withUniqueName()
        defer { board.releaseGlobally() }
        precondition(board.writeObjects([provider]))
        let urls = board.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL]
        precondition(urls == [source], "系统读取的文件 URL 必须与原文件一致")
        var completed = false
        delegate.filePromiseProvider(provider, writePromiseTo: destination) { error in
            precondition(error == nil)
            completed = true
        }
        precondition(completed)
        let copied = try Data(contentsOf: destination)
        precondition(copied == contents)
        let original = try Data(contentsOf: source)
        precondition(original == contents)
        var rejected = false
        delegate.filePromiseProvider(provider, writePromiseTo: destination) { error in rejected = error != nil }
        precondition(rejected, "不应覆盖目标目录已有文件")
        print("原文件 URL、复制回调、保留原文件及拒绝覆盖检查通过")
    }
}
