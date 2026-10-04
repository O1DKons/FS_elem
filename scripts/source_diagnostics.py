"""Safe scalar source-failure contract. No file, decoder or model access."""
import math

CONDITIONS = ('first_timestamp_unavailable', 'first_timestamp_nonzero',
              'nonfinite_timestamp', 'nonincreasing_timestamp')
MESSAGES = {
    'SOURCE_FRAME_COUNT_MISMATCH': 'Source frame count differs from decoded frames; analysis stopped.',
    'SOURCE_TIMESTAMP_INVALID': 'Source frame timestamps are invalid; analysis stopped.',
}
KEYS = {'schemaVersion', 'stage', 'code', 'declaredFrames', 'decodedFrames',
        'failedTimestampConditions'}


def validate_diagnostics(value):
    if not isinstance(value, dict) or set(value) != KEYS:
        return None
    if type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['stage'] != 'probe':
        return None
    code = value['code']
    if type(code) is not str or code not in MESSAGES:
        return None
    for key in ('declaredFrames', 'decodedFrames'):
        if type(value[key]) is not int or not 0 <= value[key] <= 2**53-1:
            return None
    failed = value['failedTimestampConditions']
    if type(failed) is not list or any(type(c) is not str or c not in CONDITIONS for c in failed):
        return None
    if failed != [c for c in CONDITIONS if c in failed]:
        return None
    mismatch = value['declaredFrames'] != value['decodedFrames']
    if code != ('SOURCE_FRAME_COUNT_MISMATCH' if mismatch else 'SOURCE_TIMESTAMP_INVALID'):
        return None
    if not mismatch and not failed:
        return None
    return {**value, 'failedTimestampConditions': list(failed)}


def public_source_error(value):
    data = validate_diagnostics(value)
    if data is None:
        return None
    return {'code': data['code'], 'message': MESSAGES[data['code']], 'diagnostics': data}


class SourceDiagnosticsError(ValueError):
    def __init__(self, diagnostics):
        error = public_source_error(diagnostics)
        if error is None:
            raise ValueError('Invalid source diagnostic object')
        self.diagnostics = error['diagnostics']
        super().__init__(error['message'])


def require_source_timeline(declared, times):
    failed = []
    if not times:
        failed.append('first_timestamp_unavailable')
    elif times[0] != 0:
        failed.append('first_timestamp_nonzero')
    if not all(math.isfinite(t) for t in times):
        failed.append('nonfinite_timestamp')
    if any(b <= a for a, b in zip(times, times[1:])):
        failed.append('nonincreasing_timestamp')
    if len(times) != declared or failed:
        raise SourceDiagnosticsError(dict(
            schemaVersion=1, stage='probe',
            code='SOURCE_FRAME_COUNT_MISMATCH' if len(times) != declared else 'SOURCE_TIMESTAMP_INVALID',
            declaredFrames=declared, decodedFrames=len(times), failedTimestampConditions=failed))
