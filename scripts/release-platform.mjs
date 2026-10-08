import path from 'node:path';

export function profile(os = process.platform, arch = process.arch) {
  if (os === 'darwin' && arch === 'arm64') return { id: 'macos-arm64', pythonParts: ['bin', 'python'], ffmpegName: 'ffmpeg' };
  if (os === 'win32' && arch === 'x64') return { id: 'windows-x64', pythonParts: ['Scripts', 'python.exe'], ffmpegName: 'ffmpeg.exe' };
  throw new Error(`Unsupported release platform: ${os}/${arch}; requires macOS Apple Silicon or Windows x64`);
}

export function prependNodePath(env, node = process.execPath, os = process.platform) {
  const result = { ...env };
  const paths = os === 'win32' ? path.win32 : path.posix;
  const keys = Object.keys(result).filter(key => os === 'win32' ? key.toLowerCase() === 'path' : key === 'PATH');
  const key = keys[0] || 'PATH';
  const previous = result[key] || '';
  for (const duplicate of keys) delete result[duplicate];
  result[key] = [paths.dirname(node), previous].filter(Boolean).join(paths.delimiter);
  return result;
}

export function resolveExecutable(value, root, os = process.platform) {
  if (typeof value !== 'string' || !value || value.includes('\0')) throw new Error('Invalid executable path');
  const paths = os === 'win32' ? path.win32 : path.posix;
  if (paths.isAbsolute(value)) return value;
  return /[\\/]/.test(value) ? paths.resolve(root, value) : value;
}

export function browserCommand(value, os = process.platform) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || !['/', '/analysis'].includes(url.pathname) || url.search || url.hash) {
    throw new Error('Browser URL must be a loopback HTTP application route');
  }
  if (os === 'win32') return ['explorer.exe', [url.href]];
  if (os === 'darwin') return ['/usr/bin/open', [url.href]];
  throw new Error(`Unsupported browser platform: ${os}`);
}

export function releaseRecipeName(selected, ort = 'ort4') {
  if (!['ort4', 'ort2'].includes(ort)) throw new Error('Unsupported ORT profile');
  if (selected === 'windows-x64') {
    if (ort !== 'ort4') throw new Error('Windows release currently supports the CPU4/1 profile only');
    return 'axel-release-ort4-windows-x64-v2.json';
  }
  if (selected === 'macos-arm64') return `axel-release-${ort}-v2.json`;
  throw new Error('Unsupported native release profile');
}

export function requireWindowsRecipe(recipe, native) {
  const p = recipe.platformProvenance;
  if (!p || p.id !== 'windows-x64' || p.status !== 'ready' || native?.status !== 'ready' ||
      [p.scienceLockSha256, p.poseLockSha256, p.ffmpegSha256].some(sha => typeof sha !== 'string' || !/^[0-9a-f]{64}$/.test(sha)) ||
      p.scienceLockSha256 !== native.environments?.science?.lockSha256 ||
      p.poseLockSha256 !== native.environments?.pose?.lockSha256 ||
      p.ffmpegSha256 !== native.ffmpeg?.sha256 || recipe.ffmpeg?.sha256 !== native.ffmpeg?.sha256 ||
      recipe.ortThreads?.intraOpNumThreads !== 4 || recipe.ortThreads?.interOpNumThreads !== 1 ||
      recipe.sciencePython !== '../.runtime/venv-science/Scripts/python.exe' ||
      recipe.posePython !== '../.runtime/venv-pose/Scripts/python.exe' || recipe.ffmpeg?.path !== '../.runtime/bin/ffmpeg.exe' ||
      !p.backendRuntimeHashes || typeof p.backendRuntimeHashes !== 'object' || Array.isArray(p.backendRuntimeHashes) ||
      !Object.keys(p.backendRuntimeHashes).length || Object.entries(p.backendRuntimeHashes).some(([name, sha]) => !/^[0-9a-f]{64}$/.test(sha) || recipe.inputSha256?.[name] !== sha)) {
    throw new Error('Windows recipe pending verified dependencies/FFmpeg/backend provenance');
  }
  return recipe;
}
