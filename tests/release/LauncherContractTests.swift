// UNEXECUTED. Future macOS-only fixture compilation with -D FS_ELEM_TESTING;
// link this test with the UI-owned source. No Node/runtime/model invocation.
import XCTest
import Foundation
import Darwin

final class LauncherContractTests: XCTestCase {
    @objc func testPrivateWritableShutdownHasRetainedWaitAndBothEOF() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder.appendingPathComponent("scripts"),
                                               withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        // Inert shell controller: no Node, models, network or production service.
        let script = "printf '{\"type\":\"progress\",\"message\":\"fixture\"}\\n'\nIFS= read -r control\n[ \"$control\" = '{\"type\":\"shutdown\"}' ] || exit 2\n"
        try script.write(to: folder.appendingPathComponent("scripts/macos-bundle.mjs"),
                         atomically: true, encoding: .utf8)
        let owner = ControllerOwner()
        let completion = expectation(description: "retained wait and pipe EOF")
        owner.onEvent = { _, event in
            if case .progress = event {
                XCTAssertGreaterThan(owner.pid, 0)
                XCTAssertEqual(Darwin.getpgid(owner.pid), owner.pid)
                owner.shutdown()
            }
        }
        owner.onClosed = { _, proof, status in
            XCTAssertTrue(proof.complete); XCTAssertEqual(status, 0)
            completion.fulfill()
        }
        try owner.launch(node: URL(fileURLWithPath: "/bin/sh"), appRoot: folder, userRoot: folder)
        wait(for: [completion], timeout: 15)
    }

    @objc func testMalformedFrameDrainsLaterOutputToPhysicalEOF() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: folder.appendingPathComponent("scripts"),
                                               withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        // Remain live until the protocol failure requests shutdown. Then emit a
        // tempting ready frame: it must be discarded, followed by real pipe EOF.
        let script = "printf '{malformed}\\n'\nIFS= read -r control\n[ \"$control\" = '{\"type\":\"shutdown\"}' ] || exit 2\nprintf '{\"type\":\"ready\",\"url\":\"http://127.0.0.1:5174/analysis\"}\\n'\n"
        try script.write(to: folder.appendingPathComponent("scripts/macos-bundle.mjs"),
                         atomically: true, encoding: .utf8)
        let owner = ControllerOwner()
        let completion = expectation(description: "malformed frame then actual EOF")
        var failures = 0
        owner.onEvent = { _, event in
            switch event {
            case .failure: failures += 1
            case .ready: XCTFail("Readiness after protocol failure")
            default: break
            }
        }
        owner.onClosed = { _, proof, status in
            XCTAssertEqual(failures, 1)
            XCTAssertTrue(proof.waited); XCTAssertTrue(proof.stdoutEOF)
            XCTAssertTrue(proof.stderrEOF); XCTAssertTrue(proof.groupGone)
            XCTAssertEqual(status, 0) // Successful cleanup cannot erase failure.
            completion.fulfill()
        }
        try owner.launch(node: URL(fileURLWithPath: "/bin/sh"), appRoot: folder, userRoot: folder)
        wait(for: [completion], timeout: 15)
    }

    @objc func testOldGenerationCannotEnableBrowserAfterRetry() {
        var gate = LauncherGate()
        let old = UUID(), current = UUID()
        XCTAssertTrue(gate.begin(old))
        XCTAssertTrue(gate.finish(old, proof: ClosureProof(waited: true, stdoutEOF: true,
                                                        stderrEOF: true, groupGone: true)))
        XCTAssertTrue(gate.begin(current))
        XCTAssertFalse(gate.accepts(old))
        XCTAssertTrue(gate.accepts(current))
    }
    @objc func testStoppedMessageCannotReplaceWaitAndBothEOF() {
        var gate = LauncherGate(); let id = UUID()
        XCTAssertTrue(gate.begin(id)); gate.stop()
        XCTAssertFalse(gate.finish(id, proof: ClosureProof(waited: true, stdoutEOF: true,
                                                         stderrEOF: false, groupGone: true)))
        XCTAssertFalse(gate.begin(UUID()))
        XCTAssertFalse(gate.accepts(id))
    }
    @objc func testRetainedWaitWithoutGroupDisappearanceBlocksRetry() {
        var gate = LauncherGate(); let id = UUID(); XCTAssertTrue(gate.begin(id))
        XCTAssertFalse(gate.finish(id, proof: ClosureProof(waited: true, stdoutEOF: true,
                                                         stderrEOF: true, groupGone: false)))
        XCTAssertFalse(gate.closed)
    }
    @objc func testExternalOrCredentialedURLCannotEnableOpenButton() {
        for url in ["https://127.0.0.1:5174/analysis", "http://example.com:5174/analysis",
                    "http://user@127.0.0.1:5174/analysis", "http://127.0.0.1:5174/analysis?x=1",
                    "http://127.0.0.1:5174/other"] {
            let bytes = try! JSONSerialization.data(withJSONObject: ["type": "ready", "url": url])
            XCTAssertThrowsError(try EventDecoder.decode(bytes))
        }
    }
    @objc func testMalformedProgressAndOversizedFramesFailClosed() {
        let bytes = try! JSONSerialization.data(withJSONObject: ["type": "progress", "bytes": 101, "total": 100])
        XCTAssertThrowsError(try EventDecoder.decode(bytes))
        XCTAssertThrowsError(try EventDecoder.decode(Data(repeating: 32, count: EventDecoder.frameLimit + 1)))
    }
}
