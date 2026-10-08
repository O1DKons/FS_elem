"""Native release paths and platform guards; no dependency downloads on import."""
from pathlib import Path
import platform
import re
import sys


def platform_id(system=None, machine=None, version=None):
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    if system == 'Darwin':
        version = platform.mac_ver()[0] if version is None else version
        if machine.lower() == 'arm64' and int(version.split('.')[0]) >= 13:
            return 'macos-arm64'
    if system == 'Windows':
        version = str(sys.getwindowsversion().major) if version is None else version
        if machine.lower() in ('amd64', 'x86_64', 'x64') and int(version.split('.')[0]) >= 10:
            return 'windows-x64'
    raise ValueError('Unsupported release host: %s/%s; requires macOS13+ ARM64 or Windows10/11 x64' % (system, machine))


def venv_python(directory, selected):
    parts = ('Scripts', 'python.exe') if selected == 'windows-x64' else ('bin', 'python')
    if selected not in ('windows-x64', 'macos-arm64'):
        raise ValueError('Unsupported runtime profile')
    return Path(directory).joinpath(*parts)


def require_interpreter(probe, selected, expected):
    machine = str(probe.get('machine', '')).lower()
    architecture = machine == 'arm64' if selected == 'macos-arm64' else machine in ('amd64', 'x86_64', 'x64')
    system = 'Darwin' if selected == 'macos-arm64' else 'Windows'
    if selected not in ('macos-arm64', 'windows-x64') or probe.get('system') != system or not architecture or probe.get('bits') != 64 or tuple(probe.get('version', [])[:2]) != tuple(expected):
        raise ValueError('Interpreter does not match native platform, 64-bit architecture or Python version')
    return probe


def require_ready_profile(profile):
    if profile.get('status') != 'ready':
        raise ValueError('Native runtime profile pending verified dependency/FFmpeg metadata; setup is unavailable')
    for name in ('science', 'pose'):
        environment = profile.get('environments', {}).get(name, {})
        if not environment.get('lock') or not re.fullmatch(r'[0-9a-f]{64}', environment.get('lockSha256') or ''):
            raise ValueError('Missing verified native %s lock' % name)
    ffmpeg = profile.get('ffmpeg', {})
    if not re.fullmatch(r'[0-9a-f]{64}', ffmpeg.get('sha256') or '') or not isinstance(ffmpeg.get('sizeBytes'), int) or ffmpeg['sizeBytes'] <= 0:
        raise ValueError('Missing verified native FFmpeg identity')
    return profile
