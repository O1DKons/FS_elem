// SOURCE PREPARATION ONLY. Not compiled or executed.
// Compile in the same module as the two original accepted Swift sources.
// FS_ELEM_TESTING excludes the product @main; main.swift supplies this entry.
import XCTest

let fsElemLauncherContractTests: [(String, (LauncherContractTests) -> () throws -> Void)] = [
    ("testPrivateWritableShutdownHasRetainedWaitAndBothEOF", LauncherContractTests.testPrivateWritableShutdownHasRetainedWaitAndBothEOF),
    ("testMalformedFrameDrainsLaterOutputToPhysicalEOF", LauncherContractTests.testMalformedFrameDrainsLaterOutputToPhysicalEOF),
    ("testOldGenerationCannotEnableBrowserAfterRetry", LauncherContractTests.testOldGenerationCannotEnableBrowserAfterRetry),
    ("testStoppedMessageCannotReplaceWaitAndBothEOF", LauncherContractTests.testStoppedMessageCannotReplaceWaitAndBothEOF),
    ("testRetainedWaitWithoutGroupDisappearanceBlocksRetry", LauncherContractTests.testRetainedWaitWithoutGroupDisappearanceBlocksRetry),
    ("testExternalOrCredentialedURLCannotEnableOpenButton", LauncherContractTests.testExternalOrCredentialedURLCannotEnableOpenButton),
    ("testMalformedProgressAndOversizedFramesFailClosed", LauncherContractTests.testMalformedProgressAndOversizedFramesFailClosed)
]

XCTMain([testCase(fsElemLauncherContractTests)])
