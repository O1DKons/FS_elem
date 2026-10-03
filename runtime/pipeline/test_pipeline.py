"""Portable runtime contracts tested on synthetic data only."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import sys
import subprocess
from contextlib import redirect_stdout

import numpy as np
import support
import temporal
import selection
import windows
import pose_models
import sparse
import run


class PortabilityTests(unittest.TestCase):
    def test_fresh_cache_admission_occurs_before_probe_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            support.validate_cache_directory(directory,False)
            (directory/'partial.json').write_text('{}')
            with self.assertRaises(ValueError):
                support.validate_cache_directory(directory,False)
            support.validate_cache_directory(directory,True)

    def test_child_progress_is_forwarded_and_all_logs_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            log=Path(temporary)/'child.log'
            output=io.StringIO()
            script='import json; print("synthetic diagnostic"); print(json.dumps({"stage":"sparse","currentFrame":2,"totalFrames":3}))'
            with redirect_stdout(output):
                support.run_child([sys.executable,'-c',script],log)
            self.assertEqual(json.loads(output.getvalue()),dict(stage='sparse',currentFrame=2,totalFrames=3))
            self.assertIn('synthetic diagnostic',log.read_text())

    def test_dense_validation_does_not_report_nominal_before_nominal_stage(self):
        record=dict(width=10,height=10,sourceSha256='synthetic',fps=50,frameCount=10)
        recipe=dict(worker='w',inputSha256={'w':'extractor'},denseGeometry={},poseSha256='pose',detectorSha256='detector')
        document=dict(schemaVersion=1,extractorSha256='extractor',geometry=dict(width=10,height=10),
                      sourceSha256='synthetic',fps=50,frameCount=10,poseSha256='pose',detectorSha256='detector',items=[])
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run.validate_dense(document,record,[],recipe),[])
        self.assertEqual(output.getvalue(),'')

    def test_assets_resolve_from_relocated_config_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            relocated = Path(temporary).resolve()/'copy'
            config = relocated/'configs/release.json'
            self.assertEqual(support.asset_path(config, '../assets/models/pose.onnx'),
                             relocated/'assets/models/pose.onnx')

    def test_venv_python_path_preserves_environment_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            target=root/'base-python';target.write_text('synthetic executable marker')
            executable=root/'.runtime/venv-pose/bin/python';executable.parent.mkdir(parents=True)
            executable.symlink_to(target)
            self.assertEqual(support.asset_path(root/'configs/release.json','../.runtime/venv-pose/bin/python'), executable)

    def test_absolute_or_legacy_asset_dependencies_are_rejected(self):
        for value in ('/old/checkpoints/pose.onnx', 'C:\\old\\pose.onnx', 'C:old.onnx', '../work/model.joblib'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                support.asset_path(Path('/portable/configs/release.json'), value)

    def test_stdout_progress_is_single_line_json(self):
        output = io.StringIO()
        with redirect_stdout(output):
            support.progress('dense', 50, 100)
        self.assertEqual(json.loads(output.getvalue()),
                         dict(stage='dense', currentFrame=50, totalFrames=100))
        self.assertEqual(output.getvalue().count('\n'), 1)

    def test_geometry_refuses_dimension_disagreement_or_unverified_rotation(self):
        for sizes, rotation, auto in [([(1920,1080)],90,True), ([(1080,1920)],90,None)]:
            with self.subTest(rotation=rotation,auto=auto), self.assertRaises(ValueError):
                support.verify_display_geometry(1080,1920,sizes,rotation,auto)

    def test_verified_rotated_geometry_requires_no_overlay_rotation(self):
        value = support.verify_display_geometry(1080,1920,[(1080,1920)]*3,90,True)
        self.assertIsNotNone(value)
        self.assertEqual(value['coordinateSpace'], 'displayed-source-pixels')
        self.assertFalse(value['overlayRotationRequired'])

    def test_raw_sparse_points_and_heatmap_peaks_survive_normalization(self):
        points = [[50.,40.]]*23
        scores = [1.4]*23
        row = sparse.pose_fields(points,scores,100,80)
        self.assertIsNotNone(row)
        self.assertEqual(row['rawPoints'], points)
        self.assertEqual(row['rawScores'], scores)
        self.assertEqual(row['landmarks'][0]['x'], .5)
        self.assertEqual(row['landmarks'][0]['confidence'], 1.)

    def test_offline_temporal_context_retains_existing_offset_order(self):
        value = temporal.context_features(np.arange(5.)[:,None],np.arange(5)*.12,np.ones(5,bool))
        self.assertIsNotNone(value)
        np.testing.assert_array_equal(value[2], [0.,1.,2.,3.,4.])

    def test_decoder_keeps_strict_threshold_and_midpoint_boundaries(self):
        value = selection.decode(np.arange(5)*.12,np.array([.2,.3,.31,.7,.2]),np.ones(5,bool),.48,.3)
        self.assertEqual(len(value), 1)
        self.assertAlmostEqual(value[0]['start'], .18)
        self.assertAlmostEqual(value[0]['end'], .42)
        self.assertAlmostEqual(value[0]['peakTime'], .36)

    def test_window_uses_actual_pts_strict_flight_and_complete_context(self):
        value = windows.dense_window([i*.02 for i in range(10)],.08,.14)
        self.assertIsNotNone(value)
        self.assertEqual(value['flightFrames'], [5,6])
        self.assertEqual((value['cropStartFrame'],value['cropEndFrame']), (0,9))

    def test_nominal_preserves_duration_and_eighty_spectral_features(self):
        frames={}
        for i in range(32):
            points=np.zeros((23,2));points[5]=[-5,10];points[6]=[5,10]
            points[11]=[-5-np.sin(i/4),0];points[12]=[5+np.sin(i/4),0]
            frames[str(i)]=dict(points=points.tolist(),scores=[1.]*23)
        value,quality=windows.nominal_features(dict(frames=frames),dict(flightFrames=list(range(32)),startSeconds=1.,endSeconds=1.64))
        self.assertEqual(value.shape,(81,))
        self.assertAlmostEqual(value[0],.64)
        self.assertEqual(quality,dict(flightFrames=32,usableTorsoFrames=32,finiteSpectralFeatures=80))

    def test_tracking_keeps_previous_overlap_without_person_switch(self):
        previous = [0,0,10,10]
        self.assertEqual(pose_models.track_box([[100,100,200,200],[1,1,11,11]], previous),
                         [1.,1.,11.,11.])


if __name__ == '__main__':
    unittest.main()
