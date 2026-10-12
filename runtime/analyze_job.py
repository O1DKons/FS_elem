"""Trusted fixed recipe subprocess entry. Inference only; no expert labels or fits."""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys
from pose_export import publish

ROOT=Path(__file__).resolve().parents[1]


def source_sha256(value):
    if not re.fullmatch(r'[0-9a-f]{64}',value):
        raise argparse.ArgumentTypeError('Source SHA-256 must be 64 lowercase hexadecimal characters')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--video',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--source-sha256',type=source_sha256,required=True)
    args=parser.parse_args();recipe=json.loads(args.config.read_text())
    output=args.job/'research-result.json'
    subprocess.run([sys.executable,str(ROOT/'runtime/pipeline/run.py'),str(args.video),
        '--config',str(args.config),'--cache',str(args.job/'cache'),
        '--pose-python',str((args.config.parent/recipe['posePython']).absolute()),'--output',str(output)],check=True)
    print(json.dumps({'stage':'export','currentFrame':None,'totalFrames':None}),flush=True)
    raw=json.loads(output.read_text())
    if raw['sourceSha256']!=args.source_sha256:raise ValueError('Uploaded source identity changed during analysis')
    publish(args.job.name,raw,args.job)


if __name__=='__main__':main()
