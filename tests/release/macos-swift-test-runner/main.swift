// Genuine Apple XCTest execution; the seven fixture bodies are unchanged.
import XCTest
import Foundation
import Darwin
import Dispatch

let expectedNames: Set<String> = [
    "testPrivateWritableShutdownHasRetainedWaitAndBothEOF",
    "testMalformedFrameDrainsLaterOutputToPhysicalEOF",
    "testOldGenerationCannotEnableBrowserAfterRetry",
    "testStoppedMessageCannotReplaceWaitAndBothEOF",
    "testRetainedWaitWithoutGroupDisappearanceBlocksRetry",
    "testExternalOrCredentialedURLCannotEnableOpenButton",
    "testMalformedProgressAndOversizedFramesFailClosed",
]
final class RunObserver: NSObject, XCTestObservation {
    var completed = Set<String>()
    var invalid = false
    func testCaseDidFinish(_ testCase: XCTestCase) {
        let matched = expectedNames.filter { testCase.name.contains($0) }
        guard testCase is LauncherContractTests, matched.count == 1,
              let name = matched.first, let run = testCase.testRun,
              run.executionCount == 1, run.failureCount == 0, run.skipCount == 0, run.hasSucceeded,
              completed.insert(name).inserted else {
            invalid = true
            return
        }
        print("Test Case '\(testCase.name)' passed")
    }
}
let suiteTask = DispatchWorkItem {
    let observer = RunObserver()
    XCTestObservationCenter.shared.addTestObserver(observer)
    let suite = XCTestSuite(forTestCaseClass: LauncherContractTests.self)
    suite.run()
    XCTestObservationCenter.shared.removeTestObserver(observer)
    guard let run = suite.testRun else { exit(1) }
    print("Executed \(run.executionCount) tests, with \(run.failureCount) failures")
    guard expectedNames.count == 7, run.executionCount == 7,
          run.failureCount == 0, run.skipCount == 0, run.hasSucceeded,
          !observer.invalid, observer.completed == expectedNames else { exit(1) }
    exit(0)
}
DispatchQueue.global(qos: .userInitiated).async(execute: suiteTask)
dispatchMain()
