"""Trusted stdlib gate. No producer starts before the owning API releases stdin."""
import subprocess
import sys

TOKEN='FS_ELEM_OWNED_START_V1\n'


def main():
    # Only this bounded private pipe controls startup; EOF or any other token refuses it.
    line=sys.stdin.buffer.readline(128)
    # Text-mode stdin from a Windows Popen can translate LF to CRLF.
    if line not in (TOKEN.encode('ascii'),TOKEN.replace('\n','\r\n').encode('ascii')):
        return 126
    command=sys.argv[1:]
    if not command:
        return 126
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL)
    try:
        return process.wait()
    except BaseException:
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=3)
        raise


if __name__=='__main__':raise SystemExit(main())
