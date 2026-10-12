# FS_elem 0.2.6 for macOS — offline candidate

Target: macOS 13.0 or later, Apple Silicon. One DMG contains FS_elem.app and an Applications link. Drag the app into Applications. Python, Node.js, FFmpeg, the UI and all five analysis models are inside the app; end-user downloads and manual runtime installation are disabled.

This is an unsigned development candidate until native checks and Apple Developer ID signing/notarization are accepted. It is not yet a consumer Gatekeeper-ready release. Do not disable Gatekeeper or remove quarantine to validate it.

User results and logs live outside the app in Library/Application Support/FS_elem. Replacing the app must preserve them. Packaging does not change algorithms, CPU settings, model weights or recognition-quality claims.
