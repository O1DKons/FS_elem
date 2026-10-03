# Third-party components and upstream model terms

Public dependency metadata is recorded in `dependency-licenses-v1.json`; each installed wheel retains its bundled license notices. This inventory does not replace the full wheel notices.

| Component | Verified code terms / source | Weight or binary qualification |
|---|---|---|
| MMPose / RTMW | Apache-2.0: https://github.com/open-mmlab/mmpose/blob/main/LICENSE | Checkpoint-specific redistribution license was not explicitly established. Download from the official OpenMMLab URL; do not relabel the weights Apache solely from code terms. |
| MMDetection / YOLOX | Apache-2.0: https://github.com/open-mmlab/mmdetection/blob/main/LICENSE and https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE | HumanArt checkpoint-specific terms remain unverified. |
| rtmlib | Apache-2.0: https://github.com/Tau-J/rtmlib/blob/main/LICENSE | Version0.0.15 declares both OpenCV distributions; see installation compatibility note. |
| HumanArt data | https://github.com/IDEA-Research/HumanArt#dataset-download | README requests noncommercial authorization and prohibits private sharing. Dataset terms are not a proven checkpoint license; no dataset is distributed here. |
| imageio-ffmpeg wrapper | BSD-2-Clause: https://github.com/imageio/imageio-ffmpeg | Applies to Python wrapper, not the nested executable. |
| FFmpeg7.1 ARM64 executable | Local pinned executable `-L`: GPL-2.0-or-later; https://ffmpeg.org/legal.html | Build enables GPL and libx264/libx265. Installer obtains upstream wheel and copies executable only locally; no executable redistribution by this repository. Preserve notices and source obligations if separately redistributing a binary. |
| CPython / python-build-standalone | PSF-2.0 / build scripts MPL-2.0; https://github.com/astral-sh/python-build-standalone | Preserve each embedded library's notices from the interpreter archive. |

The official RTMW download is the RTMW-l 384x288 distilled checkpoint despite the `x-l` filename. The manifest distinguishes official ZIP archive sizes from extracted ONNX hashes. No original video, dataset, global checkpoint cache or private research protocol belongs in the public release.

Outstanding distribution issue: checkpoint-specific upstream rights were not explicitly verified in this audit; project-owned fitted model rights have not been assigned a new license here. This permits an honest research installation test, not a claim of unrestricted commercial redistribution. Publishing owner should retain this qualification and avoid rehosting upstream weights until terms are resolved.
