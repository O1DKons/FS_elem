import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('release_model_state', Path(__file__).resolve().parents[1] / 'scripts/release_model_state.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CanonicalGuards(unittest.TestCase):
    def nodes(self):
        dtype = np.dtype({'names': ['left', 'value'], 'formats': ['i4', 'f8'], 'offsets': [0, 8], 'itemsize': 24})
        a = np.zeros(2, dtype=dtype)
        a['left'] = [1, -1]
        a['value'] = [0.5, 1.0]
        return a

    def test_only_padding_bytes_do_not_change_semantic_hash(self):
        a = self.nodes(); b = a.copy()
        b.view(np.uint8).reshape(-1, 24)[:, 4:8] = 255
        b.view(np.uint8).reshape(-1, 24)[:, 16:24] = 123
        self.assertNotEqual(a.tobytes(), b.tobytes())
        self.assertEqual(module.semantic_hash(a), module.semantic_hash(b))

    def test_named_node_field_change_is_detected(self):
        a = self.nodes(); b = a.copy(); b['left'][0] = 2
        self.assertNotEqual(module.semantic_hash(a), module.semantic_hash(b))

    def test_leaf_numeric_value_change_is_detected(self):
        a = {'nodes': self.nodes(), 'values': np.array([[[0.5, 0.5]]])}
        b = {'nodes': self.nodes(), 'values': np.array([[[0.5, 0.6]]])}
        self.assertNotEqual(module.semantic_hash(a), module.semantic_hash(b))

    def test_object_arrays_hash_values_and_preserve_order(self):
        a = np.array(['axel', {'v': 1}], dtype=object)
        self.assertEqual(module.semantic_hash(a), module.semantic_hash(a.copy()))
        self.assertNotEqual(module.semantic_hash(a), module.semantic_hash(a[::-1]))

    def test_shape_and_dtype_are_significant(self):
        a = np.array([1, 2], dtype='i8')
        self.assertNotEqual(module.semantic_hash(a), module.semantic_hash(a.reshape(1, 2)))
        self.assertNotEqual(module.semantic_hash(a), module.semantic_hash(a.astype('i4')))

    def test_unsupported_type_is_rejected(self):
        with self.assertRaises(TypeError):
            module.semantic_hash(object())


if __name__ == '__main__':
    unittest.main()
