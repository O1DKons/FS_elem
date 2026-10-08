"""Config-relative assets, explicit progress, and displayed-pixel geometry gate."""
import json
import math
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT/'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0,str(SCRIPTS))
from source_diagnostics import validate_diagnostics

STAGES = ('probe','sparse','flight_family','dense','nominal','export')


def validate_cache_directory(directory, cache_hit):
    if not cache_hit and any(Path(directory).iterdir()):
        raise ValueError('Unfinished/unverified cache; choose a fresh cache root')


def asset_path(config, value):
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).drive or 'work' in value.replace('\\','/').split('/'):
        raise ValueError('Release assets must be config-relative without legacy work paths')
    # Preserve a venv's bin/python symlink: resolving it loses pyvenv.cfg.
    return Path(os.path.abspath(Path(config).absolute().parent/path))


def progress(stage, current_frame=0, total_frames=0):
    if stage not in STAGES or type(current_frame) is not int or type(total_frames) is not int or not 0 <= current_frame <= total_frames:
        raise ValueError('Invalid fixed-runner progress')
    print(json.dumps(dict(stage=stage,currentFrame=current_frame,totalFrames=total_frames)),flush=True)


def run_child(argv, log_path):
    with Path(log_path).open('x') as log:
        with subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0) as process:
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    try:
                        row=json.loads(line)
                    except (ValueError,TypeError):
                        continue
                    if isinstance(row,dict) and row.get('kind')=='analysis_diagnostics':
                        diagnostic=validate_diagnostics(row.get('diagnostics'))
                        # Preserve invalid state without forwarding any untrusted fields.
                        print(json.dumps({'kind':'analysis_diagnostics','diagnostics':diagnostic},allow_nan=False),flush=True)
                    if isinstance(row,dict) and row.get('stage') in STAGES:
                        progress(row['stage'],row['currentFrame'],row['totalFrames'])
                code=process.wait()
            except BaseException:
                process.terminate()
                process.wait(timeout=5)
                raise
        if code:
            raise subprocess.CalledProcessError(code,argv)


def verify_display_geometry(width,height,sizes,rotation,auto):
    if (not sizes or any(size != (width,height) for size in sizes)
            or rotation is None or not math.isfinite(rotation)
            or (rotation % 360 != 0 and auto is not True)):
        raise ValueError('Displayed source geometry/rotation is unverified or incompatible')
    return dict(coordinateSpace='displayed-source-pixels',decoderAutoOriented=bool(auto),
                opencvFfmpegDimensionsAgree=True,overlayRotationRequired=False,
                width=width,height=height,rotationDegrees=rotation)
