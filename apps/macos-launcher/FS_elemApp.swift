import AppKit
import Foundation
import CoreFoundation
import Darwin

struct ClosureProof {
    let waited: Bool
    let stdoutEOF: Bool
    let stderrEOF: Bool
    let groupGone: Bool
    var complete: Bool { waited && stdoutEOF && stderrEOF && groupGone }
}

enum LauncherEvent {
    case progress(String, Double?)
    case ready(URL)
    case failure(String)
    case stopped
}

enum ProtocolFailure: Error { case invalidFrame }

enum EventDecoder {
    static let frameLimit = 32 * 1024
    static func decode(_ frame: Data) throws -> LauncherEvent {
        guard frame.count <= frameLimit,
              let object = try JSONSerialization.jsonObject(with: frame) as? [String: Any],
              let type = object["type"] as? String else { throw ProtocolFailure.invalidFrame }
        switch type {
        case "progress":
            let message = object["message"] as? String ?? "Подготовка приложения"
            var fraction: Double?
            if let bytes = object["bytes"] as? NSNumber, let total = object["total"] as? NSNumber {
                let b = bytes.doubleValue, t = total.doubleValue
                guard CFGetTypeID(bytes) != CFBooleanGetTypeID(), CFGetTypeID(total) != CFBooleanGetTypeID(),
                      b.isFinite, t.isFinite, b >= 0, t > 0, b <= t,
                      b.rounded() == b, t.rounded() == t else { throw ProtocolFailure.invalidFrame }
                fraction = b / t
            }
            return .progress(String(message.prefix(500)), fraction)
        case "ready":
            guard let text = object["url"] as? String, let url = URL(string: text),
                  url.scheme == "http", url.host == "127.0.0.1",
                  let port = url.port, (1024...65535).contains(port),
                  url.path == "/analysis", url.user == nil, url.password == nil,
                  url.query == nil, url.fragment == nil else { throw ProtocolFailure.invalidFrame }
            return .ready(url)
        case "error":
            return .failure(String((object["message"] as? String ?? "Не удалось запустить приложение").prefix(1000)))
        case "stopped": return .stopped
        default: throw ProtocolFailure.invalidFrame
        }
    }
}

// Generation binding is used by the GUI, not only by its future fixtures.
struct LauncherGate {
    private(set) var generation: UUID?
    private(set) var stopping = false
    private(set) var closed = true
    mutating func begin(_ value: UUID) -> Bool {
        guard closed else { return false }
        generation = value; stopping = false; closed = false
        return true
    }
    mutating func stop() { stopping = true }
    func accepts(_ value: UUID) -> Bool { generation == value && !closed && !stopping }
    mutating func finish(_ value: UUID, proof: ClosureProof) -> Bool {
        guard generation == value, proof.complete else { return false }
        closed = true; stopping = true
        return true
    }
}

// posix_spawn establishes the new group before exec; the retained original
// child, its private pipe and waitpid are never replaced by process-name lookup.
final class ControllerOwner {
    static let streamLimit = 256 * 1024
    let generation = UUID()
    private(set) var pid: pid_t = 0
    private let lock = NSLock()
    private var control: FileHandle?
    private var outHandle: FileHandle?
    private var errHandle: FileHandle?
    private var reaped = false
    private var totalBytes = 0
    private var stopRequested = false
    private var reportedFailure = false
    private var stdoutEOF = false
    private var stderrEOF = false
    private var groupGone = false
    private var waitSucceeded = false
    private var exitStatus: Int32 = -1
    private let drains = DispatchGroup()
    var onEvent: ((UUID, LauncherEvent) -> Void)?
    var onClosed: ((UUID, ClosureProof, Int32) -> Void)?

    private static func pair() throws -> [Int32] {
        var values: [Int32] = [0, 0]
        guard values.withUnsafeMutableBufferPointer({ Darwin.pipe($0.baseAddress!) }) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        for i in 0..<2 {
            let copy = fcntl(values[i], F_DUPFD_CLOEXEC, 3)
            guard copy >= 0 else {
                for fd in values { Darwin.close(fd) }
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
            }
            Darwin.close(values[i]); values[i] = copy
        }
        return values
    }

    func launch(node: URL, appRoot: URL, userRoot: URL) throws {
        var ownedFDs: [Int32] = []
        defer { for fd in ownedFDs { Darwin.close(fd) } }
        let input = try Self.pair(); ownedFDs += input
        let output = try Self.pair(); ownedFDs += output
        let error = try Self.pair(); ownedFDs += error
        var actions: posix_spawn_file_actions_t?
        var attributes: posix_spawnattr_t?
        guard posix_spawn_file_actions_init(&actions) == 0 else { throw ProtocolFailure.invalidFrame }
        defer { posix_spawn_file_actions_destroy(&actions) }
        guard posix_spawnattr_init(&attributes) == 0 else { throw ProtocolFailure.invalidFrame }
        defer { posix_spawnattr_destroy(&attributes) }
        func checked(_ value: Int32) throws {
            if value != 0 { throw NSError(domain: NSPOSIXErrorDomain, code: Int(value)) }
        }
        try checked(posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP)))
        try checked(posix_spawnattr_setpgroup(&attributes, 0))
        try checked(posix_spawn_file_actions_adddup2(&actions, input[0], STDIN_FILENO))
        try checked(posix_spawn_file_actions_adddup2(&actions, output[1], STDOUT_FILENO))
        try checked(posix_spawn_file_actions_adddup2(&actions, error[1], STDERR_FILENO))
        for fd in ownedFDs { try checked(posix_spawn_file_actions_addclose(&actions, fd)) }
        let arguments = [node.path, appRoot.appendingPathComponent("scripts/macos-bundle.mjs").path,
                         "--app-root", appRoot.path, "--user-root", userRoot.path]
        let inherited = ProcessInfo.processInfo.environment
        var environment = ["PATH": node.deletingLastPathComponent().path + ":/usr/bin:/bin",
                           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"]
        for name in ["HOME", "TMPDIR", "LANG", "LC_CTYPE"] {
            if let value = inherited[name] { environment[name] = value }
        }
        var argv = arguments.map { strdup($0) } + [nil]
        var envp = environment.keys.sorted().map { strdup($0 + "=" + environment[$0]!) } + [nil]
        defer { for p in argv { free(p) }; for p in envp { free(p) } }
        let rc = argv.withUnsafeMutableBufferPointer { a in
            envp.withUnsafeMutableBufferPointer { e in
                posix_spawn(&pid, node.path, &actions, &attributes, a.baseAddress!, e.baseAddress!)
            }
        }
        try checked(rc)
        control = FileHandle(fileDescriptor: input[1], closeOnDealloc: true)
        outHandle = FileHandle(fileDescriptor: output[0], closeOnDealloc: true)
        errHandle = FileHandle(fileDescriptor: error[0], closeOnDealloc: true)
        ownedFDs.removeAll { [input[1], output[0], error[0]].contains($0) }
        for (handle, json) in [(outHandle!, true), (errHandle!, false)] {
            drains.enter()
            DispatchQueue.global(qos: .utility).async { self.pump(handle, json: json) }
        }
        DispatchQueue.global(qos: .utility).async { self.retainWait() }
    }

    var retainedRunning: Bool {
        lock.lock(); defer { lock.unlock() }
        return pid > 0 && !reaped
    }

    private func emit(_ event: LauncherEvent) {
        DispatchQueue.main.async { self.onEvent?(self.generation, event) }
    }
    private func fail(_ message: String) {
        lock.lock()
        let first = !reportedFailure
        reportedFailure = true
        lock.unlock()
        if first { emit(.failure(message)); shutdown() }
    }
    private func pump(_ handle: FileHandle, json: Bool) {
        var pending = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        var ended = false
        var discard = false
        defer {
            try? handle.close()
            lock.lock()
            if json { stdoutEOF = ended } else { stderrEOF = ended }
            lock.unlock()
            drains.leave()
        }
        do {
            while true {
                // A short protocol frame must not need to fill a 4096-byte read.
                let readResult: (count: Int, error: Int32) = buffer.withUnsafeMutableBytes { bytes in
                    let count = Darwin.read(handle.fileDescriptor, bytes.baseAddress!, bytes.count)
                    return (count, count < 0 ? errno : 0)
                }
                if readResult.count < 0 {
                    if readResult.error == EINTR { continue }
                    throw NSError(domain: NSPOSIXErrorDomain, code: Int(readResult.error))
                }
                if readResult.count == 0 { ended = true; break }
                let block = Data(buffer.prefix(readResult.count))
                lock.lock()
                if totalBytes <= Self.streamLimit { totalBytes += block.count }
                let exceeds = totalBytes > Self.streamLimit
                let exited = reaped
                lock.unlock()
                if exceeds {
                    pending.removeAll(keepingCapacity: false)
                    discard = true
                    fail("Служба прислала слишком много данных. Завершаем запуск.")
                    continue // Bounded discard, while waiting for physical EOF.
                }
                if !json || discard { continue }
                pending.append(block)
                while let boundary = pending.firstIndex(of: 10) {
                    let frame = Data(pending[..<boundary])
                    pending.removeSubrange(...boundary)
                    if frame.isEmpty { continue }
                    do {
                        let event = try EventDecoder.decode(frame)
                        if !exited { emit(event) }
                    } catch {
                        pending.removeAll(keepingCapacity: false)
                        discard = true
                        fail("Не удалось получить полный ответ службы.")
                        break // Keep reading the pipe; this is not physical EOF.
                    }
                }
                if pending.count > EventDecoder.frameLimit {
                    pending.removeAll(keepingCapacity: false)
                    discard = true
                    fail("Не удалось получить полный ответ службы.")
                }
            }
            if json && !discard && !pending.isEmpty {
                fail("Не удалось получить полный ответ службы.")
            }
        } catch {
            // A failed read is incomplete closure. Only an empty successful read
            // sets ended=true; malformed protocol switches to drain, not close.
            fail("Не удалось получить полный ответ службы.")
        }
    }

    func shutdown() {
        lock.lock()
        guard !stopRequested else { lock.unlock(); return }
        stopRequested = true
        let handle = control; control = nil
        lock.unlock()
        DispatchQueue.global(qos: .utility).async {
            // A writable private pipe is required. DEVNULL is never used.
            try? handle?.write(contentsOf: Data("{\"type\":\"shutdown\"}\n".utf8))
            try? handle?.close()
        }
        // This is a controller upper bound, not a startup/quality claim.
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 30) {
            self.lock.lock(); let alive = !self.reaped; self.lock.unlock()
            if alive {
                self.fail("Завершение службы не подтверждено. Повторный запуск недоступен.")
                Darwin.kill(-self.pid, SIGTERM)
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 3) {
                    self.lock.lock(); let retained = !self.reaped; self.lock.unlock()
                    if retained { Darwin.kill(-self.pid, SIGKILL) }
                }
            }
        }
    }

    private func retainWait() {
        var status: Int32 = 0
        var result: pid_t
        repeat { result = waitpid(pid, &status, 0) } while result < 0 && errno == EINTR
        lock.lock()
        reaped = result == pid; waitSucceeded = result == pid; exitStatus = status
        let remainingControl = control; control = nil
        lock.unlock()
        try? remainingControl?.close()
        if result != pid { fail("Не удалось подтвердить завершение собственного процесса.") }
        // As in the accepted POSIX owner, only the original group is addressed.
        let deadline = DispatchTime.now().uptimeNanoseconds + 6_000_000_000
        func groupExists() -> Bool {
            if Darwin.kill(-pid, 0) == 0 { return true }
            return errno != ESRCH
        }
        if groupExists() {
            Darwin.kill(-pid, SIGTERM)
            let grace = DispatchTime.now().uptimeNanoseconds + 3_000_000_000
            while groupExists() && DispatchTime.now().uptimeNanoseconds < grace {
                Thread.sleep(forTimeInterval: 0.02)
            }
            if groupExists() { Darwin.kill(-pid, SIGKILL) }
        }
        while groupExists() && DispatchTime.now().uptimeNanoseconds < deadline {
            Thread.sleep(forTimeInterval: 0.02)
        }
        lock.lock(); groupGone = !groupExists(); lock.unlock()
        let drainResult = drains.wait(timeout: .now() + 6)
        lock.lock()
        let proof = ClosureProof(waited: waitSucceeded, stdoutEOF: stdoutEOF,
                                 stderrEOF: stderrEOF, groupGone: groupGone)
        lock.unlock()
        if drainResult != .success || !proof.complete {
            fail("Завершение внутренних служб не подтверждено. Повторный запуск недоступен.")
        }
        DispatchQueue.main.async { self.onClosed?(self.generation, proof, status) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private let message = NSTextField(wrappingLabelWithString: "Подготовка FS_elem")
    private let progress = NSProgressIndicator()
    private let openButton = NSButton(title: "Открыть FS_elem", target: nil, action: nil)
    private let retryButton = NSButton(title: "Повторить", target: nil, action: nil)
    private let stopButton = NSButton(title: "Завершить", target: nil, action: nil)
    private var gate = LauncherGate()
    private var owner: ControllerOwner?
    private var readyURL: URL?
    private var firstFailure: String?
    private var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        Darwin.signal(SIGPIPE, SIG_IGN)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 520, height: 300),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "FS_elem"; window.delegate = self; window.center()
        let title = NSTextField(labelWithString: "FS_elem")
        title.font = .systemFont(ofSize: 30, weight: .semibold)
        let detail = NSTextField(wrappingLabelWithString: "Анализ фигурного катания на вашем компьютере")
        detail.textColor = .secondaryLabelColor
        progress.style = .bar; progress.isIndeterminate = true; progress.minValue = 0; progress.maxValue = 1
        progress.startAnimation(nil)
        message.font = .systemFont(ofSize: 14)
        openButton.target = self; openButton.action = #selector(openUI); openButton.isEnabled = false
        retryButton.target = self; retryButton.action = #selector(retry); retryButton.isEnabled = false
        stopButton.target = self; stopButton.action = #selector(stop)
        let buttons = NSStackView(views: [openButton, retryButton, stopButton])
        buttons.orientation = .horizontal; buttons.spacing = 12
        let stack = NSStackView(views: [title, detail, progress, message, buttons])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 28),
            progress.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        start()
    }

    private func start() {
        guard gate.closed else { return }
        firstFailure = nil
        readyURL = nil; openButton.isEnabled = false; retryButton.isEnabled = false
        progress.isIndeterminate = true; progress.startAnimation(nil)
        message.stringValue = "Проверка приложения и подготовка моделей…"
        guard let resources = Bundle.main.resourceURL,
              let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            message.stringValue = "Пакет приложения неполон."; return
        }
        let root = resources.appendingPathComponent("payload", isDirectory: true)
        let user = support.appendingPathComponent("FS_elem", isDirectory: true)
        let node = root.appendingPathComponent(".runtime/bin/node")
        guard FileManager.default.isExecutableFile(atPath: node.path) else {
            message.stringValue = "Внутренняя среда отсутствует. Нужен полный пакет приложения."; return
        }
        let next = ControllerOwner()
        guard gate.begin(next.generation) else { return }
        owner = next
        next.onEvent = { [weak self] id, event in self?.receive(id, event) }
        next.onClosed = { [weak self] id, proof, status in self?.finished(id, proof, status) }
        do { try next.launch(node: node, appRoot: root, userRoot: user) }
        catch {
            // posix_spawn failure means no child was created; do not synthesize
            // closure for any successfully spawned controller.
            _ = gate.finish(next.generation, proof: ClosureProof(waited: true, stdoutEOF: true,
                                                               stderrEOF: true, groupGone: true))
            owner = nil; retryButton.isEnabled = true
            progress.stopAnimation(nil); message.stringValue = "Не удалось запустить внутреннюю службу."
        }
    }
    private func receive(_ id: UUID, _ event: LauncherEvent) {
        guard gate.accepts(id) else { return }
        switch event {
        case .progress(let text, let fraction):
            message.stringValue = text
            progress.isIndeterminate = fraction == nil
            if let value = fraction { progress.doubleValue = value }
        case .ready(let url):
            guard owner?.retainedRunning == true else { return }
            readyURL = url; message.stringValue = "FS_elem готов к работе"
            progress.isIndeterminate = false; progress.doubleValue = 1
            openButton.isEnabled = true
        case .failure(let text):
            if firstFailure == nil { firstFailure = text }
            message.stringValue = firstFailure!; readyURL = nil; openButton.isEnabled = false
            gate.stop(); owner?.shutdown()
        case .stopped:
            // This message is not a wait/EOF/PGID proof.
            message.stringValue = "Завершение работы…"; gate.stop()
        }
    }
    private func finished(_ id: UUID, _ proof: ClosureProof, _ status: Int32) {
        guard gate.generation == id else { return }
        openButton.isEnabled = false; readyURL = nil; progress.stopAnimation(nil)
        guard gate.finish(id, proof: proof) else {
            retryButton.isEnabled = false
            let closureMessage = "Службы ещё не завершены. Повторный запуск недоступен."
            message.stringValue = firstFailure.map { $0 + " " + closureMessage } ?? closureMessage
            if quitting { quitting = false; NSApp.reply(toApplicationShouldTerminate: false) }
            return
        }
        owner = nil; retryButton.isEnabled = true
        if quitting { NSApp.reply(toApplicationShouldTerminate: true) }
        else if let failure = firstFailure { message.stringValue = failure }
        else if status == 0 { message.stringValue = "Работа завершена." }
    }
    @objc private func retry() { start() }
    @objc private func openUI() {
        guard let url = readyURL, !gate.stopping, !gate.closed else { return }
        if !NSWorkspace.shared.open(url) { message.stringValue = "Не удалось открыть браузер." }
    }
    @objc private func stop() {
        gate.stop(); readyURL = nil; openButton.isEnabled = false; retryButton.isEnabled = false
        message.stringValue = "Завершение работы…"; owner?.shutdown()
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if gate.closed { return .terminateNow }
        quitting = true; stop(); return .terminateLater
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
}

#if !FS_ELEM_TESTING
@main
enum FS_elemApplication {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}
#endif
