"""Compare fitted states without hashing unused NumPy structured padding.

This only reads objects. It never modifies a model, trains or scores one.
"""
import hashlib
import struct
import joblib
import numpy as np


def canonical_state(value):
    if isinstance(value, np.ndarray):
        if value.dtype.names:
            return ('structured-array', value.shape, value.dtype.itemsize,
                    tuple((name, value.dtype.fields[name][1], canonical_state(value[name]))
                          for name in value.dtype.names))
        if value.dtype.hasobject:
            return ('object-array', value.shape, value.dtype.str,
                    tuple(canonical_state(x) for x in value.flat))
        if value.dtype.kind == 'V':
            raise TypeError('Unstructured void array has no named semantic fields')
        return ('array', value.shape, value.dtype.str,
                hashlib.sha256(value.tobytes(order='C')).hexdigest())
    if isinstance(value, np.generic):
        return ('numpy-scalar', canonical_state(np.asarray(value)))
    if value is None or type(value) in (bool, int, str):
        return (type(value).__name__, value)
    if type(value) is float:
        return ('float', struct.pack('!d', value).hex())
    if type(value) is complex:
        return ('complex', struct.pack('!dd', value.real, value.imag).hex())
    if type(value) is bytes:
        return ('bytes', len(value), hashlib.sha256(value).hexdigest())
    if type(value) in (tuple, list):
        return (type(value).__name__, tuple(canonical_state(x) for x in value))
    if type(value) is dict:
        return ('dict', tuple((canonical_state(k), canonical_state(v)) for k, v in value.items()))
    cls = type(value)
    name = cls.__module__ + '.' + cls.__qualname__
    if name == 'sklearn.tree._tree.Tree':
        return ('tree', name, canonical_state(value.__getstate__()),
                tuple((key, canonical_state(getattr(value, key)))
                      for key in ('n_features', 'n_classes', 'n_outputs', 'max_depth', 'node_count', 'capacity')))
    if cls.__module__.startswith('sklearn.') and hasattr(value, '__dict__'):
        return ('estimator', name, canonical_state(value.__dict__))
    raise TypeError('Unsupported model-state type: ' + name)


def semantic_hash(value):
    return joblib.hash(canonical_state(value), hash_name='sha1')
