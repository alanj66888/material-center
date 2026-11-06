import Cocoa
import WebKit
import UniformTypeIdentifiers

final class LibraryWindow: NSWindow {
    var armedURL: URL?
    var downEvent: NSEvent?
    var dragFile: ((URL, NSEvent) -> Void)?
    var regions: [(URL, NSRect)] = []
    var exclusions: [NSRect] = []
    override func sendEvent(_ event: NSEvent) {
        if event.type == .leftMouseDown {
            downEvent = event
            let point = event.locationInWindow
            armedURL = exclusions.contains(where: { $0.contains(point) }) ? nil : regions.first(where: { $0.1.contains(point) })?.0
        }
        if event.type == .leftMouseDragged, let down = downEvent, let url = armedURL,
           hypot(event.locationInWindow.x-down.locationInWindow.x, event.locationInWindow.y-down.locationInWindow.y) > 5 {
            downEvent = nil; armedURL = nil
            dragFile?(url, down)
            return
        }
        if event.type == .leftMouseUp { downEvent = nil; armedURL = nil }
        super.sendEvent(event)
    }
}

final class OriginalFilePromise: NSFilePromiseProvider {
    var originalURL: URL!
    override func writableTypes(for pasteboard: NSPasteboard) -> [NSPasteboard.PasteboardType] {
        return super.writableTypes(for: pasteboard) + [.fileURL]
    }
    override func pasteboardPropertyList(forType type: NSPasteboard.PasteboardType) -> Any? {
        if type == .fileURL { return originalURL.absoluteString }
        return super.pasteboardPropertyList(forType: type)
    }
}

final class FileDragView: NSView, NSDraggingSource, NSFilePromiseProviderDelegate {
    var fileURL: URL? { didSet { needsDisplay = true } }
    var report: ((String) -> Void)?
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var intrinsicContentSize: NSSize { NSSize(width: 220, height: 36) }
    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 3, dy: 4)
        (fileURL == nil ? NSColor.windowBackgroundColor : NSColor.controlAccentColor.withAlphaComponent(0.18)).setFill()
        NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6).fill()
        let text = fileURL == nil ? "选中素材后可拖出原文件" : "↗ 拖出原文件（拷贝 / 导入）"
        (text as NSString).draw(in: rect.insetBy(dx: 12, dy: 6), withAttributes: [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: fileURL == nil ? NSColor.secondaryLabelColor : NSColor.labelColor])
    }
    override func mouseDown(with event: NSEvent) {
        guard let url = fileURL else { return }
        startDrag(url, event: event)
    }
    func startDrag(_ url: URL, event: NSEvent, from sourceView: NSView? = nil) {
        guard FileManager.default.isReadableFile(atPath: url.path) else { report?("文件无法读取，请检查硬盘连接"); NSSound.beep(); return }
        let view = sourceView ?? self
        let provider = OriginalFilePromise(fileType: UTType(filenameExtension: url.pathExtension)?.identifier ?? UTType.data.identifier, delegate: self)
        provider.originalURL = url
        provider.userInfo = url
        let item = NSDraggingItem(pasteboardWriter: provider)
        let icon = NSWorkspace.shared.icon(forFile: url.path)
        let point = view.convert(event.locationInWindow, from: nil)
        item.setDraggingFrame(NSRect(x: point.x-24, y: point.y-24, width: 48, height: 48), contents: icon)
        report?("正在拖出：" + url.lastPathComponent)
        let session = view.beginDraggingSession(with: [item], event: event, source: self)
        session.animatesToStartingPositionsOnCancelOrFail = true
    }
    func filePromiseProvider(_ filePromiseProvider: NSFilePromiseProvider, fileNameForType fileType: String) -> String {
        return (filePromiseProvider.userInfo as! URL).lastPathComponent
    }
    func filePromiseProvider(_ filePromiseProvider: NSFilePromiseProvider, writePromiseTo url: URL, completionHandler: @escaping (Error?) -> Void) {
        guard let source = filePromiseProvider.userInfo as? URL else {
            completionHandler(NSError(domain: NSCocoaErrorDomain, code: NSFileReadUnknownError)); return
        }
        do {
            try FileManager.default.copyItem(at: source, to: url)
            logDrag("copied \(source.lastPathComponent) to \(url.path)")
            DispatchQueue.main.async { self.report?("拷贝完成：" + source.lastPathComponent) }
            completionHandler(nil)
        } catch {
            DispatchQueue.main.async { self.report?("拷贝失败：" + error.localizedDescription) }
            completionHandler(error)
        }
    }
    func operationQueue(for filePromiseProvider: NSFilePromiseProvider) -> OperationQueue { OperationQueue() }
    func draggingSession(_ session: NSDraggingSession, sourceOperationMaskFor context: NSDraggingContext) -> NSDragOperation { .copy }
    func logDrag(_ text: String) {
        guard ProcessInfo.processInfo.environment["SUCAIYU_DRAG_DEBUG"] == "1", let directory = ProcessInfo.processInfo.environment["SUCAIYU_DATA_DIR"] else { return }
        let path = URL(fileURLWithPath: directory).appendingPathComponent("drag-diagnostics.log")
        if !FileManager.default.fileExists(atPath: path.path) { FileManager.default.createFile(atPath: path.path, contents: nil) }
        if let handle = try? FileHandle(forWritingTo: path) { handle.seekToEndOfFile(); handle.write((text+"\n").data(using: .utf8)!); try? handle.close() }
    }
    func draggingSession(_ session: NSDraggingSession, willBeginAt screenPoint: NSPoint) {
        logDrag("begin \(screenPoint) window \(String(describing: window?.frame)) screen \(String(describing: window?.screen?.frame))")
    }
    func draggingSession(_ session: NSDraggingSession, endedAt screenPoint: NSPoint, operation: NSDragOperation) {
        report?(operation.isEmpty ? "目标未接收文件（或已取消拖放）" : "目标已接收文件")
        logDrag("end \(screenPoint) operation \(operation.rawValue) types \(session.draggingPasteboard.types?.map { $0.rawValue } ?? [])")
    }
    func ignoreModifierKeys(for session: NSDraggingSession) -> Bool { true }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
    var window: LibraryWindow!
    var webView: WKWebView!
    let dragView = FileDragView()
    let filename = NSTextField(labelWithString: "本地素材库")
    var project: URL!
    var dataURL: URL!
    var readyURL: URL!
    var homeURL = URL(string: "http://127.0.0.1:8765/")!
    var serverProcess: Process?
    var attempts = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        project = Bundle.main.object(forInfoDictionaryKey: "LibraryProjectPath").flatMap { $0 as? String }.map { URL(fileURLWithPath: $0) }
        dataURL = ProcessInfo.processInfo.environment["SUCAIYU_DATA_DIR"].map { URL(fileURLWithPath: $0) } ?? (Bundle.main.object(forInfoDictionaryKey: "LibraryTestDataPath") as? String).map { URL(fileURLWithPath: $0) } ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("素材屿")
        do { try FileManager.default.createDirectory(at: dataURL, withIntermediateDirectories: true) }
        catch { showError("无法创建资料库目录：" + error.localizedDescription); NSApp.terminate(nil); return }
        readyURL = dataURL.appendingPathComponent("session-" + UUID().uuidString + ".json")
        window = LibraryWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 850), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = Bundle.main.object(forInfoDictionaryKey: "LibraryTestMode") as? Bool == true ? "素材中心 · 功能测试（独立资料库）" : "素材中心 · 本地素材库"
        window.minSize = NSSize(width: 800, height: 600)
        let controller = WKUserContentController()
        controller.add(self, name: "selectedFile")
        controller.add(self, name: "chooseFolder")
        controller.add(self, name: "appearance")
        controller.addUserScript(WKUserScript(source: """
        window.desktopLibrary={platform:'darwin',chooseFolder:()=>new Promise(resolve=>{const id=crypto.randomUUID();const listener=e=>{if(e.detail.id===id){window.removeEventListener('native-folder',listener);resolve({path:e.detail.path})}};window.addEventListener('native-folder',listener);window.webkit.messageHandlers.chooseFolder.postMessage({id})})};
        """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let config = WKWebViewConfiguration()
        config.userContentController = controller
        config.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window.dragFile = { [weak self] url, event in
            guard let self = self else { return }
            self.dragView.startDrag(url, event: event, from: self.webView)
        }
        dragView.report = { [weak self] text in self?.filename.stringValue = text }
        let container = NSView()
        // Retain the drag source object; thumbnail drag regions no longer need a visible bar.
        webView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: container.topAnchor), webView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: container.leadingAnchor), webView.trailingAnchor.constraint(equalTo: container.trailingAnchor)
        ])
        window.contentView = container
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        buildMenu()
        if startServer() { connect() }
    }
    func buildMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "退出素材中心", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let edit = NSMenu(title: "编辑"); editItem.submenu = edit
        for (title, action, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        NSApp.mainMenu = menu
    }
    func connect() {
        attempts += 1
        if let data = try? Data(contentsOf: readyURL),
           let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           payload["app"] as? String == "sucaiyu", let address = payload["url"] as? String,
           let url = URL(string: address), url.host == "127.0.0.1" {
            homeURL = url
            webView.load(URLRequest(url: homeURL))
            return
        }
        if serverProcess?.isRunning != true { showError("本地服务已退出，请查看资料库目录中的 desktop.log。"); return }
        if attempts < 600 { DispatchQueue.main.asyncAfter(deadline: .now()+0.2) { self.connect() } }
        else { showError("本地服务启动超时，请退出后重新打开。") }
    }
    @discardableResult func startServer() -> Bool {
        let process = Process()
        let bundled = Bundle.main.resourceURL!.appendingPathComponent("backend/LibraryServer")
        var arguments: [String] = []
        if FileManager.default.isExecutableFile(atPath: bundled.path) {
            process.executableURL = bundled
        } else {
            let paths = ["/Library/Frameworks/Python.framework/Versions/3.11/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
            guard let python = paths.first(where: { FileManager.default.isExecutableFile(atPath: $0) }), let project = project else { showError("应用文件不完整，请重新解压安装包。"); return false }
            process.executableURL = URL(fileURLWithPath: python)
            arguments = [project.appendingPathComponent("server.py").path]
        }
        process.arguments = arguments + ["--no-browser", "--port", "8766", "--fallback-port", "--ready-file", readyURL.path]
        var environment = ProcessInfo.processInfo.environment
        environment["SUCAIYU_DATA_DIR"] = dataURL.path
        if let libraries = Bundle.main.object(forInfoDictionaryKey: "LibraryMediaLibs") as? String { environment["SUCAIYU_MEDIA_LIBS"] = libraries }
        if Bundle.main.object(forInfoDictionaryKey: "LibraryTestMode") as? Bool == true { environment["SUCAIYU_TEST_MODE"] = "1" }
        process.environment = environment
        let logURL = dataURL.appendingPathComponent("desktop.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        let log = try? FileHandle(forWritingTo: logURL); log?.seekToEndOfFile()
        process.standardOutput = log; process.standardError = log
        do { try process.run(); serverProcess = process; return true }
        catch { showError(error.localizedDescription); return false }
    }
    func applicationWillTerminate(_ notification: Notification) {
        if serverProcess?.isRunning == true { serverProcess?.terminate() }
        if let readyURL = readyURL { try? FileManager.default.removeItem(at: readyURL) }
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let page = message.frameInfo.request.url,
              page.scheme == "http", page.host == "127.0.0.1", page.port == homeURL.port,
              let body = message.body as? [String: Any] else { return }
        if message.name == "appearance" {
            let theme = body["theme"] as? String ?? "system"
            NSApp.appearance = theme == "light" ? NSAppearance(named: .aqua) : theme == "dark" ? NSAppearance(named: .darkAqua) : nil
            let icon = body["icon"] as? String ?? "original"
            let names = ["original":"app-icon.png", "light":"icon-light.png", "dark":"icon-dark.png"]
            if let name = names[icon] {
                let bases = [project?.appendingPathComponent("web"), Bundle.main.resourceURL?.appendingPathComponent("backend/web"), Bundle.main.resourceURL?.appendingPathComponent("backend/_internal/web")].compactMap { $0 }
                if let image = bases.compactMap({ NSImage(contentsOf: $0.appendingPathComponent(name)) }).first { NSApp.applicationIconImage = image }
            }
            return
        }
        if message.name == "chooseFolder", let id = body["id"] as? String {
            let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.allowsMultipleSelection = false
            panel.prompt = "连接素材文件夹"
            panel.beginSheetModal(for: window) { result in
                let payload = ["id": id, "path": result == .OK ? (panel.url?.path ?? "") : ""]
                if let data = try? JSONSerialization.data(withJSONObject: payload), let json = String(data: data, encoding: .utf8) {
                    self.webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('native-folder',{detail:" + json + "}))", completionHandler: nil)
                }
            }
            return
        }
        if body["action"] as? String == "regions" {
            func rect(_ item: [String: Any]) -> NSRect? {
                guard let x = item["x"] as? Double, let y = item["y"] as? Double,
                      let width = item["width"] as? Double, let height = item["height"] as? Double,
                      x.isFinite, y.isFinite, width.isFinite, height.isFinite, width > 0, height > 0 else { return nil }
                return webView.convert(NSRect(x: x, y: y, width: width, height: height), to: nil)
            }
            window.regions = (body["items"] as? [[String: Any]] ?? []).compactMap { item in
                guard let path = item["path"] as? String, let area = rect(item) else { return nil }
                return (URL(fileURLWithPath: path).standardizedFileURL, area)
            }
            window.exclusions = (body["exclude"] as? [[String: Any]] ?? []).compactMap { rect($0) }
            return
        }
        guard let path = body["path"] as? String else { return }
        if path.isEmpty { dragView.fileURL = nil; filename.stringValue = "本地素材库"; filename.toolTip = nil; return }
        let url = URL(fileURLWithPath: path).standardizedFileURL
        var directory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &directory), !directory.boolValue else { return }
        dragView.fileURL = url
        filename.stringValue = url.lastPathComponent
        filename.toolTip = url.path
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "http", url.host == "127.0.0.1", url.port == homeURL.port { decisionHandler(.allow) }
        else { decisionHandler(.cancel) }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard frame.isMainFrame else { completionHandler(false); return }
        let alert = NSAlert(); alert.messageText = "素材中心"; alert.informativeText = message; alert.alertStyle = .warning
        alert.addButton(withTitle: "确认"); alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = "素材中心"; alert.informativeText = message
        alert.addButton(withTitle: "确定"); alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func showError(_ message: String) { let alert = NSAlert(); alert.messageText = "素材中心"; alert.informativeText = message; alert.runModal() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
#if !DRAG_TEST
@main
struct SucaiyuApplication {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}
#endif
