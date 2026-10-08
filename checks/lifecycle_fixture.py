"""Inert fixture source: only a separately granted lifecycle test runs this."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['tree','child','leaf','sentinel','complete','owner_host'])
    parser.add_argument('directory',type=Path)
    parser.add_argument('--services',type=Path)
    args=parser.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    (args.directory/(args.mode+'.json')).write_text(json.dumps({'pid':os.getpid()}))
    if args.mode=='complete':
        (args.directory/'result.json').write_text('{}')
        (args.directory/'pose.json').write_text('{}')
        return
    if args.mode=='owner_host':
        sys.path.insert(0,str(args.services))
        from process_owner import OwnedProcess
        owner=OwnedProcess.launch([sys.executable,__file__,'tree',str(args.directory)],cwd=args.directory,env=os.environ.copy())
        (args.directory/'gate.json').write_text(json.dumps({'pid':owner.pid}))
        # Parent loss test kills this host without Python cleanup; Job handles are not inherited.
        time.sleep(60)
        owner.stop()
        return
    if args.mode in ('tree','child'):
        mode='child' if args.mode=='tree' else 'leaf'
        child=subprocess.Popen([sys.executable,__file__,mode,str(args.directory)])
        try:time.sleep(60)
        finally:
            child.terminate();child.wait(timeout=3)
    else:time.sleep(60)


if __name__=='__main__':main()
