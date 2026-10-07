# FS_elem v0.2.0 installation

Target: macOS 13 or later, Apple Silicon ARM64, Node.js 24 with npm/npx. A local release uses two isolated interpreters: Python 3.12 for science and Python 3.9 for pose. RAM 8 GB is the target, not a verified performance promise. Start processes sequentially; only one analysis runs at a time.

## Commands

Install Node 24 from its official distribution and `uv` from https://docs.astral.sh/uv/getting-started/installation/ . From the downloaded release repository:

```sh
uv python install 3.12 3.9
npm run setup:release -- --science-python "$(uv python find 3.12)" --pose-python "$(uv python find 3.9)"
npm run check:release -- --science-python "$(uv python find 3.12)"
npm run start:release
```

Open http://127.0.0.1:5174/analysis . Keep the terminal open. Ctrl+C stops both services. The v0.2.0 launcher serves the existing compiled interface through the local production worker. FS_elem.command is the Mac entry point; npm run start:release remains the terminal alternative. Installation can build the frontend when preparing a fresh source checkout; the accepted release build is reused for the current local kit.

Alternatively provide already installed ARM64 interpreter paths through `--science-python` and `--pose-python`. Interpreter patch versions may differ from the research environment; the exact installed patch is recorded in acceptance. Public standalone 20251031 provides CPython 3.9.25 and 3.12.12; no Codex runtime is required. uv is an interpreter acquisition option, not an inference dependency.

## Installed files and integrity

The bootstrap writes only project `.runtime/venv-science`, `.runtime/venv-pose`, `.runtime/bin/ffmpeg`, managed setup markers, frontend dependencies/build outputs and missing model assets in `assets/models`. It never reuses existing scientific environments or the global rtmlib checkpoint cache. It installs ARM64 wheel hash locks with normal pip dependency resolution and `pip check`, obtains the two official checkpoint ZIPs, extracts exactly one ONNX byte stream without extracting archive paths, then verifies pinned ONNX size and SHA256 before publishing the file. Archive SHA is not available and is explicitly null; archive size and final checkpoint SHA are distinct.

Science: 8 packages; pose: 13 packages. Torch and plotting packages are unnecessary for the fixed runtime. Both `opencv-python` and `opencv-contrib-python` remain at 5.0.0.93 because rtmlib0.0.15 declares both and this matches historical dependencies. They share the `cv2` namespace; a clean smoke must verify the effective runtime and compare against the selected baseline. This is an explicit compatibility limitation, not permission to change versions.

Three small sanitized joblib artifacts are bundled; their original and public hashes and complete semantic-state equality evidence are in `assets/models/sanitization-release-v1.json`. The two upstream archives total 307,656,936 bytes; extracted ONNX files total 330,721,274 bytes. Allow additional space for Python/Node packages and temporary downloads. FFmpeg 7.1 is copied locally from the pinned imageio-ffmpeg0.6.0 ARM64 wheel; its checksum is verified. No FFmpeg or large ONNX binary is rehosted in GitHub.

`check:release` verifies installed dependencies and assets without inference. It cannot prove model accuracy, end-to-end operation or throughput. A failed check prevents launch. Ports are 5174 (web) and 5175 (analysis), loopback only. Optional `npm run start:release -- --config path.json` accepts the existing web configuration format; default `.runtime/release-web.json` keeps release data separate.

## Repair

A wrong-hash existing asset is preserved and setup stops; move it aside manually after inspection, then rerun setup. An existing unmanaged or interrupted environment is preserved and setup stops. Only after confirming the directory is this release's generated environment, move `.runtime/venv-science` or `.runtime/venv-pose` aside and rerun setup. Do not delete historical environments or caches. If dependencies or frontend lock change, repeat the managed installation in a new clean checkout and acceptance, rather than silently reusing a changed environment.

## Historical baseline clean-install evidence

The following records the accepted baseline installation check, reused for v0.2.0. It is not a fresh v0.2.0 clean installation or a new video-inference run. References to current UI pins and pending full-video acceptance describe that earlier check.

Owner isolated clean installation passed after correcting an omitted shared-source directory: public Node24.19.0, Python3.12.12/3.9.25, both pip checks, checksum-bound FFmpeg/ONNX, frozen pnpm11.19.0 install/build and offline check. Actual /analysis and health returned200, inference readiness true; inert unsupported upload returned415 and shutdown exited0. All16 current UI pins were built. The first failed build and correction are retained in evidence. No video inference ran; independent full-video acceptance and baseline parity remain pending. See installation-verification-v1.json. See `third-party.md` for weight-specific licensing limits and `model-card.md` for research limitations.
