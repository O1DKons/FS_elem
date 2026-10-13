#!/usr/bin/env python3
"""Root-bound fully offline macOS development assembly; never fetch/build/sign.

Unsigned development preparation is not distribution or Gatekeeper acceptance.
Exact new recipe/entry/Source/artifact bindings fail closed before output creation.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
from urllib.parse import urlsplit

VERSION = '0.2.6'
PLATFORM = 'macos-arm64'
METADATA = 'macOS-bundle.json'
DERIVED_RECIPE = 'configs/axel-release-ort4-macos-app.json'
MODEL_MANIFEST = 'assets/models/manifest-offline-macos-v026.json'
SIGNING_POLICY = 'UNSIGNED_DEVELOPMENT_PREPARATION_ONLY'
PYTHON_VERSIONS = {'science': '3.12.15', 'pose': '3.9.20'}
ARTIFACT_SHA = {'node': '23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53',
                'science': '233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f',
                'pose': 'e7551a119bded40bfc268c850110b6a5af1d5fdd63842a56569477490d20e0a6'}
DESKTOP_ENTRY = 'scripts/start-macos-desktop.mjs'
RUNTIME_PATHS = {'node': '.runtime/bin/node',
                 'science': '.runtime/venv-science/bin/python',
                 'pose': '.runtime/venv-pose/bin/python'}


class PreparationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise PreparationError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path, limit=16 * 1024 * 1024):
    with Path(path).open('rb') as stream:
        body = stream.read(limit + 1)
    require(len(body) <= limit, 'Metadata exceeds bound')
    return json.loads(body)


def relative_name(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'Invalid relative path')
    p = Path(name)
    require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == name,
            'Noncanonical relative path')
    return p


def regular(root, name):
    p = root / relative_name(name)
    # No interpreter link or hidden ancestor escape is accepted.
    require(p.resolve().is_relative_to(root.resolve()) and not p.is_symlink(),
            'Linked or escaped component')
    require(stat.S_ISREG(p.lstat().st_mode), 'Missing regular component')
    return p


def known_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def validate_inputs(inputs):
    require(inputs.get('schemaVersion') == 1 and inputs.get('packageVersion') == VERSION
            and inputs.get('platformId') == PLATFORM and inputs.get('minimumMacOS') == '13'
            and inputs.get('offline') is True, 'Wrong offline version/platform/minimum OS')
    identifier = inputs.get('bundleIdentifier')
    require(isinstance(identifier, str) and re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', identifier),
            'Root bundle identifier unresolved')
    for name, path in RUNTIME_PATHS.items():
        item = inputs.get('runtimes', {}).get(name, {})
        require(item.get('path') == path and item.get('sha256') == ARTIFACT_SHA[name]
                and type(item.get('bytes')) is int and item['bytes'] > 0,
                'Exact runtime artifact binding unresolved: ' + name)
        require(isinstance(item.get('url'), str) and item['url'].startswith('https://')
                and isinstance(item.get('licenseEvidence'), str) and bool(item['licenseEvidence']),
                'Runtime provenance/license evidence unresolved: ' + name)
        if name == 'node':
            require(item.get('major') == 22 and item.get('version') == '22.23.3', 'Node22 version differs')
        else:
            require(item.get('version') == PYTHON_VERSIONS[name]
                    and item.get('pythonMinor') == ('3.12' if name == 'science' else '3.9'),
                    'Exact standalone Python version differs')
    require(inputs.get('pythonVersions') == PYTHON_VERSIONS, 'Python version metadata differs')
    profile = inputs.get('nativeProfile', {})
    require(isinstance(profile.get('value'), dict) and known_sha(profile.get('sha256'))
            and hashlib.sha256(json.dumps(profile['value'], sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=True).encode()).hexdigest() == profile['sha256'],
            'Exact unchanged Main historical Source profile binding unresolved')
    launcher = inputs.get('launcher', {})
    require(known_sha(launcher.get('sha256')) and type(launcher.get('bytes')) is int
            and launcher['bytes'] > 0, 'Compiled launcher pin unresolved')
    require(known_sha(inputs.get('stagingReceipt', {}).get('sha256')), 'Closed-staging receipt pin unresolved')
    policy = inputs.get('signing', {})
    require(policy.get('policyKind') == SIGNING_POLICY and policy.get('readyForRelease') is False,
            'Only explicit Root unsigned development preparation admitted')
    require(inputs.get('assetReferencePolicy') == 'config-relative-posix-with-explicit-origin-validation'
            and inputs.get('recipeConsumerCompatibility') is True, 'Root recipe compatibility unresolved')
    return inputs


def rows(root):
    result = []
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Symlink requires an explicitly accepted relocatable staging')
        require(path.is_dir() or path.is_file(), 'Special file is forbidden')
        if path.is_file():
            result.append({'path': path.relative_to(root).as_posix(),
                           'bytes': path.stat().st_size, 'sha256': digest(path)})
    names = [r['path'].casefold() for r in result]
    require(len(names) == len(set(names)), 'Case-colliding component names')
    return result


def validate_staging(runtime, receipt, inputs):
    require(receipt.get('schemaVersion') == 1 and receipt.get('platformId') == PLATFORM
            and receipt.get('packageVersion') == VERSION and receipt.get('offline') is True
            and receipt.get('signingPolicyKind') == SIGNING_POLICY,
            'Staging has no exact offline development identity')
    expected = receipt.get('files')
    require(isinstance(expected, list) and expected, 'Missing staging inventory')
    names = []
    for row in expected:
        relative_name(row.get('path'))
        require(type(row.get('bytes')) is int and row['bytes'] >= 0 and known_sha(row.get('sha256')),
                'Invalid staging identity')
        names.append(row['path'])
    require(len(names) == len(set(n.casefold() for n in names)), 'Duplicate staging path')
    require(sorted(rows(runtime), key=lambda r: r['path']) == sorted(expected, key=lambda r: r['path']),
            'Staged runtime differs from accepted receipt')
    require(receipt.get('artifactSha256') == {n: inputs['runtimes'][n]['sha256'] for n in RUNTIME_PATHS},
            'Staging receipt is not bound to accepted artifacts')
    for name, rel in RUNTIME_PATHS.items():
        item = regular(runtime, str(Path(rel).relative_to('.runtime')))
        require(os.access(item, os.X_OK), 'Internal executable is not runnable')
        require(regular(runtime, inputs['runtimes'][name]['licenseEvidence']).stat().st_size > 0,
                'Runtime license evidence missing')
    return expected


def copy_regular_tree(source, destination):
    require(not source.is_symlink() and source.is_dir(), 'Source tree must be a regular directory')
    for row in rows(source):
        p = regular(source, row['path'])
        target = destination / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.exists(), 'Copy collision')
        shutil.copy2(p, target)
        require(target.stat().st_size == row['bytes'] and digest(target) == row['sha256'],
                'Copied component changed')



def checked_copy_launcher(source, destination, expected):
    shutil.copy2(source, destination)
    state = destination.lstat()
    require(stat.S_ISREG(state.st_mode) and not destination.is_symlink()
            and os.access(destination, os.X_OK)
            and state.st_size == expected['bytes']
            and digest(destination) == expected['sha256'],
            'Copied launcher differs from Root binding')


def validate_recipe_binding(source, path, expected_sha):
    require(path is not None and known_sha(expected_sha), 'Root new recipe binding unresolved')
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536
            and digest(path) == expected_sha, 'Root recipe descriptor differs')
    spec = read_json(path, 65536)
    require(spec.get('status') == 'source-accepted', 'Root recipe binding not Source accepted')
    for field in ('parent', 'derived', 'modelManifest'):
        row = spec.get(field, {})
        require(known_sha(row.get('sha256')) and type(row.get('bytes')) is int,
                'Root recipe/manifest pin unresolved')
        p = regular(source, row['path'])
        require(p.stat().st_size == row['bytes'] and digest(p) == row['sha256'], 'Pinned metadata differs')
    require(spec['parent']['path'] == 'configs/axel-release-offline-macos-arm64-parent-v026.json'
            and spec['derived']['path'] == DERIVED_RECIPE and spec['modelManifest']['path'] == MODEL_MANIFEST,
            'Root recipe/manifest location differs')
    original = read_json(regular(source, spec['parent']['path']))
    derived = read_json(regular(source, spec['derived']['path']))
    expected = copy.deepcopy(original)
    updates = spec.get('sourceUpdates')
    require(isinstance(updates, list) and 1 <= len(updates) <= 512, 'Source update closure unresolved')
    seen = set()
    for row in updates:
        name = relative_name(row['path']).as_posix()
        require(name.startswith(('runtime/', 'services/', 'scripts/')) and 'work' not in Path(name).parts,
                'Invalid Source update origin')
        require(row.get('key') == '../' + name and name not in seen
                and known_sha(row.get('sha256')) and type(row.get('bytes')) is int,
                'Invalid or duplicate Source update')
        seen.add(name)
        p = regular(source, name)
        require(p.stat().st_size == row['bytes'] and digest(p) == row['sha256'], 'New Source lineage differs')
        key = row['key']
        present = [key in original['inputSha256'],
                   key in original['backendSourceProvenance']['runtimeHashes'],
                   key in original['backendSourceProvenance']['runtimeBytes']]
        addition = name in {'scripts/macos-first-run.py', 'scripts/macos-bundle.mjs', DESKTOP_ENTRY}
        require(all(present) or (addition and not any(present)),
                'Only existing Source rebind or exact absent Main3 addition is permitted')
        expected['inputSha256'][key] = row['sha256']
        expected['backendSourceProvenance']['runtimeHashes'][key] = row['sha256']
        expected['backendSourceProvenance']['runtimeBytes'][key] = row['bytes']
    require(isinstance(spec.get('packagingProvenance'), dict), 'Root packaging provenance unresolved')
    expected['packagingProvenance'] = spec['packagingProvenance']
    require(expected == derived, 'Scientific/model/threshold/sampling tree changed outside Root bindings')
    require(derived.get('ortThreads') == {'intraOpNumThreads': 4, 'interOpNumThreads': 1},
            'Scientific CPU policy changed')
    return spec


def validate_offline_models(source, models_root, manifest):
    assets = manifest.get('models', [])
    require(len(assets) == 5 and {a['id'] for a in assets}
            == {'flight', 'family', 'nominal', 'yolox', 'rtmw'}, 'Exact five-model closure missing')
    root = Path(models_root)
    receipt = read_json(regular(root, 'offline-models.json'), 65536)
    records = receipt.get('models', [])
    require(len(records) == 2 and {r['id'] for r in records} == {'yolox', 'rtmw'},
            'Build-host acquisition receipt incomplete')
    for asset in assets:
        origin = root if asset.get('url') else source
        p = regular(origin, asset['path'])
        require(p.stat().st_size == asset['sizeBytes'] and digest(p) == asset['sha256'],
                'Offline model differs: ' + asset['id'])
        require(regular(source, asset['licenseEvidence']).stat().st_size > 0, 'Model evidence missing')
        if asset.get('url'):
            r = next(r for r in records if r['id'] == asset['id'])
            require(all(r.get(k) == asset.get(k) for k in ('path', 'sizeBytes', 'sha256', 'url',
                    'licenseEvidence', 'checkpointLicenseStatus'))
                    and r.get('archiveBytes') == asset['downloadSizeBytes']
                    and known_sha(r.get('archiveSha256'))
                    and isinstance(r.get('archiveMember'), str)
                    and r['archiveMember'].lower().endswith('.onnx'), 'Model/member receipt differs')
            relative_name(r['archiveMember'])
    return receipt


def validate_entry_descriptor(source, descriptor_path, descriptor_sha256):
    require(descriptor_path is not None and known_sha(descriptor_sha256),
            'Root Source-accepted desktop entry descriptor is unresolved')
    descriptor_path = Path(descriptor_path)
    require(not descriptor_path.is_symlink() and descriptor_path.is_file()
            and descriptor_path.stat().st_size <= 65536, 'Invalid desktop descriptor file')
    with descriptor_path.open('rb') as stream:
        body = stream.read(65537)
    require(len(body) <= 65536 and hashlib.sha256(body).hexdigest() == descriptor_sha256,
            'Root desktop descriptor pin changed')
    spec = json.loads(body)
    require(type(spec) is dict and spec.get('status') == 'source-accepted'
            and spec.get('entry') == DESKTOP_ENTRY and spec.get('packageVersion') == VERSION
            and spec.get('nodeMajor') == 22 and spec.get('offline') is True,
            'Desktop descriptor is not accepted for the new Mac entry')
    require(type(spec.get('entryBytes')) is int and spec['entryBytes'] > 0
            and known_sha(spec.get('sourceSha256')), 'Desktop entry identity is unresolved')
    require(spec.get('argv') == []
            and spec.get('recipeEnvironmentVariable') == 'FS_ELEM_MAC_RECIPE'
            and spec.get('userRootEnvironmentVariable') == 'FS_ELEM_MAC_USER_ROOT'
            and spec.get('webConfigEnvironmentVariable') == 'FS_ELEM_MAC_WEB_CONFIG'
            and spec.get('readyEventType') == 'ready',
            'Desktop entry argv/environment/event binding differs')
    require(spec.get('control') == {'wire': 'JSONL', 'shutdown': {'type': 'shutdown'}, 'eof': 'shutdown'}
            and spec.get('healthRequirements') == {'status': 'ready', 'inferenceAvailable': True,
                                                  'activeJobId': None},
            'Desktop entry control/health binding differs')
    entry = regular(source, DESKTOP_ENTRY)
    require(entry.stat().st_size == spec['entryBytes'] and digest(entry) == spec['sourceSha256'],
            'Desktop entry differs from Root Source identity')
    template_name = spec.get('webConfigSourcePath')
    require(known_sha(spec.get('webConfigSourceSha256')), 'Immutable web template pin is unresolved')
    template_path = regular(source, template_name)
    require(digest(template_path) == spec['webConfigSourceSha256'], 'Immutable web template differs')
    template = read_json(template_path, limit=65536)
    require(template.get('host') == '127.0.0.1'
            and all(type(template.get(k)) is int and 1024 <= template[k] <= 65535
                    for k in ('port', 'analysisPort'))
            and template['port'] != template['analysisPort'],
            'Immutable web template loopback ports are invalid')
    for field, route in [('healthUrl', '/api/analysis/health'), ('uiUrl', '/analysis')]:
        value = spec.get(field)
        require(isinstance(value, str), 'Desktop URL binding is unresolved')
        url = urlsplit(value)
        require(url.scheme == 'http' and url.hostname == '127.0.0.1'
                and url.port == template['port'] and url.path == route
                and url.username is None and url.password is None and not url.query and not url.fragment,
                'Desktop health/UI URL differs from the immutable web template')
    return spec


def assemble(source, runtime, launcher, inputs_path, staging_receipt, output,
             desktop_entry_descriptor, desktop_entry_descriptor_sha256,
             recipe_binding, recipe_binding_sha256, models_root):
    source, runtime, output = Path(source), Path(runtime), Path(output)
    inputs = validate_inputs(read_json(inputs_path))
    binding = validate_recipe_binding(source, recipe_binding, recipe_binding_sha256)
    desktop = validate_entry_descriptor(source, desktop_entry_descriptor, desktop_entry_descriptor_sha256)
    require(not output.exists() and not output.is_symlink() and output.name.endswith('.app'),
            'Output must be a new .app')
    require(not any(output.resolve().is_relative_to(p.resolve()) for p in (source, runtime, Path(models_root))),
            'Output cannot nest inside inputs')
    require(not output.parent.is_symlink(), 'Output parent is a symlink')
    require(digest(staging_receipt) == inputs['stagingReceipt']['sha256'], 'Staging receipt changed')
    runtime_rows = validate_staging(runtime, read_json(staging_receipt), inputs)
    require(not launcher.is_symlink() and launcher.is_file()
            and launcher.stat().st_size == inputs['launcher']['bytes']
            and digest(launcher) == inputs['launcher']['sha256']
            and os.access(launcher, os.X_OK), 'Compiled launcher differs')
    manifest = read_json(regular(source, MODEL_MANIFEST))
    # This is the exact Main historical Source declaration, not new native acceptance.
    native = inputs['nativeProfile']['value']
    require(read_json(regular(source, 'package.json')).get('version') == VERSION, 'Root candidate version differs')
    model_receipt = validate_offline_models(source, models_root, manifest)
    contents = output / 'Contents'
    payload = contents / 'Resources/payload'
    payload.mkdir(parents=True, exist_ok=False)
    for name in ('scripts', 'services/analysis', 'runtime', 'server', 'shared', 'configs',
                 'apps/web/dist', 'apps/web/node_modules', 'docs/release'):
        copy_regular_tree(source / name, payload / name)
    shutil.copy2(regular(source, 'package.json'), payload / 'package.json')
    for asset in manifest['models']:
        origin = Path(models_root) if asset.get('url') else source
        p = regular(origin, asset['path'])
        target = payload / asset['path']; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        require(target.stat().st_size == asset['sizeBytes'] and digest(target) == asset['sha256'],
                'Copied offline model differs')
    target_manifest = payload / MODEL_MANIFEST
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(regular(source, MODEL_MANIFEST), target_manifest)
    for field in ('parent', 'derived', 'modelManifest'):
        row = binding[field]
        require(regular(payload, row['path']).stat().st_size == row['bytes']
                and digest(regular(payload, row['path'])) == row['sha256'], 'Copied Root metadata differs')
    for row in binding['sourceUpdates']:
        require(regular(payload, row['path']).stat().st_size == row['bytes']
                and digest(regular(payload, row['path'])) == row['sha256'], 'Copied Source differs')
    # Retain the exact raw Root descriptor bytes; embedded JSON alone is not its hash.
    binding_target = payload / 'configs/mac-recipe-binding.json'
    shutil.copy2(Path(recipe_binding), binding_target)
    require(digest(binding_target) == recipe_binding_sha256, 'Copied raw Root descriptor differs')
    copy_regular_tree(runtime, payload / '.runtime')
    (payload / '.runtime/offline-models-receipt.json').write_text(json.dumps(model_receipt, indent=2) + '\n')
    plist = plistlib.loads(regular(source, 'packaging/macos/Info.plist').read_bytes())
    require(plist.get('CFBundleShortVersionString') == VERSION and plist.get('CFBundleVersion') == VERSION,
            'Candidate plist version differs')
    plist['CFBundleIdentifier'] = inputs['bundleIdentifier']
    (contents / 'Info.plist').write_bytes(plistlib.dumps(plist, sort_keys=True))
    binary = contents / 'MacOS/FS_elem'; binary.parent.mkdir(parents=True)
    checked_copy_launcher(launcher, binary, inputs['launcher'])
    copied_entry = regular(payload, DESKTOP_ENTRY)
    copied_template = regular(payload, desktop['webConfigSourcePath'])
    require(copied_entry.stat().st_size == desktop['entryBytes']
            and digest(copied_entry) == desktop['sourceSha256']
            and digest(copied_template) == desktop['webConfigSourceSha256'],
            'Copied entry/template differs from exact Root binding')
    native_sha = hashlib.sha256(json.dumps(native, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=True).encode()).hexdigest()
    metadata = {'schemaVersion': 1, 'packageVersion': VERSION, 'platformId': PLATFORM,
                'minimumMacOS': '13', 'offline': True, 'nativeProfileSha256': native_sha,
                'interpreters': {n: RUNTIME_PATHS[n] for n in ('science', 'pose')},
                'pythonVersions': PYTHON_VERSIONS,
                'node': {'path': RUNTIME_PATHS['node'], 'major': 22, 'version': '22.23.3'},
                'files': rows(payload), 'modelManifestPath': MODEL_MANIFEST,
                'recipePath': DERIVED_RECIPE, 'originalRecipePath': binding['parent']['path'],
                'originalRecipeSha256': binding['parent']['sha256'],
                'recipeBinding': binding, 'recipeBindingPath': 'configs/mac-recipe-binding.json',
                'recipeBindingSha256': recipe_binding_sha256,
                'desktopServerContract': desktop,
                'desktopEntryDescriptorSha256': desktop_entry_descriptor_sha256,
                'stagingReceiptSha256': inputs['stagingReceipt']['sha256'],
                'signingPolicyKind': SIGNING_POLICY, 'readyForRelease': False,
                'signingQualification': 'Unsigned development only; no Gatekeeper/notarization/release acceptance'}
    (payload / METADATA).write_text(json.dumps(metadata, indent=2) + '\n')
    require(rows(runtime) == runtime_rows, 'Runtime changed during assembly')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--staging-receipt', type=Path, required=True)
    parser.add_argument('--app-output', type=Path, required=True)
    parser.add_argument('--desktop-entry-descriptor', type=Path, required=True)
    parser.add_argument('--desktop-entry-descriptor-sha256', required=True)
    parser.add_argument('--recipe-binding', type=Path, required=True)
    parser.add_argument('--recipe-binding-sha256', required=True)
    parser.add_argument('--models-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        assemble(args.source_root, args.runtime_root, args.launcher, args.inputs,
                 args.staging_receipt, args.app_output,
                 args.desktop_entry_descriptor, args.desktop_entry_descriptor_sha256,
                 args.recipe_binding, args.recipe_binding_sha256, args.models_root)
        print(json.dumps({'status': 'assembled-not-native-accepted', 'app': str(args.app_output)}))
    except (PreparationError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'failed-closed', 'message': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
