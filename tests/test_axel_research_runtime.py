"""Dense cache and nominal visibility guards must survive source/model changes."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
try:
    from run_axel_research import validate_dense, nominal_usable
except ImportError:
    validate_dense=nominal_usable=None
try:
    from run_axel_research import executable_path
except ImportError:
    executable_path=None
try:
    from run_axel_research import validate_cache_manifest
except ImportError:
    validate_cache_manifest=None


class DenseContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(validate_dense,'Fixed-recipe runtime dense validation is missing')
        self.record=dict(sourceSha256='a'*64,fps=50.,frameCount=4,width=640,height=480,timestampsSeconds=[0.,.02,.04,.06])
        self.window=dict(startSeconds=.01,endSeconds=.05,cropStartFrame=0,cropEndFrame=3,
            flightFrames=[1,2],candidateId='source-candidate-01')
        self.recipe=dict(poseSha256='b'*64,detectorSha256='c'*64,worker='worker.py',inputSha256={'worker.py':'d'*64},
            denseGeometry=dict(keypointLayout='coco-wholebody-first23',coordinateSpace='original-source-pixels',
                frameAxis='original-decoded-frame-index',timeAxis='original-source-presentation-seconds',scoreKind='raw-heatmap-peak'))
        self.document=dict(schemaVersion=1,extractorSha256='d'*64,geometry=dict(self.recipe['denseGeometry'],width=640,height=480),sourceSha256='a'*64,fps=50.,frameCount=4,
            poseSha256='b'*64,detectorSha256='c'*64,
            items=[dict(window=self.window,frames={str(i):dict(frameIndex=i,time=t,points=[],scores=[])
                for i,t in enumerate(self.record['timestampsSeconds'])})])

    def test_exact_original_indices_and_times_accepted(self):
        self.assertEqual(validate_dense(self.document,self.record,[self.window],self.recipe),self.document['items'])

    def test_source_model_or_window_mismatch_rejected(self):
        for field in ['sourceSha256','poseSha256','detectorSha256']:
            doc=copy.deepcopy(self.document);doc[field]='d'*64
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_dense(doc,self.record,[self.window],self.recipe)
        doc=copy.deepcopy(self.document);doc['items'][0]['window']['startSeconds']=.005
        with self.assertRaises(ValueError):validate_dense(doc,self.record,[self.window],self.recipe)

    def test_missing_duplicate_window_and_shifted_frame_rejected(self):
        for mode in ['missing','duplicate','shifted','reorderedIndex']:
            doc=copy.deepcopy(self.document)
            if mode=='missing':del doc['items'][0]['frames']['1']
            elif mode=='duplicate':doc['items'].append(copy.deepcopy(doc['items'][0]))
            elif mode=='shifted':doc['items'][0]['frames']['1']['time']=.04
            else:doc['items'][0]['frames']['1']['frameIndex']=2
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                validate_dense(doc,self.record,[self.window],self.recipe)

    def test_malformed_point_confidence_rejected(self):
        doc=copy.deepcopy(self.document);doc['items'][0]['frames']['1'].update(points=[[float('nan'),1]]*23,scores=[.9]*23)
        with self.assertRaises(ValueError):validate_dense(doc,self.record,[self.window],self.recipe)

    def test_nonfinite_timestamp_and_boolean_source_index_rejected(self):
        for changes in [dict(time=float('nan')),dict(frameIndex=True)]:
            doc=copy.deepcopy(self.document);doc['items'][0]['frames']['1'].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                validate_dense(doc,self.record,[self.window],self.recipe)

    def test_foreign_producer_normalized_pixels_and_wrong_layout_rejected(self):
        for mode in ['producer','coordinates','layout','dimensions','schema']:
            doc=copy.deepcopy(self.document)
            if mode=='producer':doc['extractorSha256']='e'*64
            elif mode=='coordinates':doc['geometry']['coordinateSpace']='normalized-or-letterboxed'
            elif mode=='layout':doc['geometry']['keypointLayout']='arbitrary23points'
            elif mode=='dimensions':doc['geometry']['width']=1280
            else:doc['schemaVersion']=True
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                validate_dense(doc,self.record,[self.window],self.recipe)

    def test_empty_or_insufficient_skeleton_cannot_force_a_nominal(self):
        self.assertIsNotNone(nominal_usable,'Nominal visibility guard is missing')
        self.assertFalse(nominal_usable(dict(usableTorsoFrames=0,finiteSpectralFeatures=0)))
        self.assertFalse(nominal_usable(dict(usableTorsoFrames=2,finiteSpectralFeatures=80)))
        self.assertFalse(nominal_usable(dict(usableTorsoFrames=10,finiteSpectralFeatures=0)))
        self.assertTrue(nominal_usable(dict(usableTorsoFrames=10,finiteSpectralFeatures=80)))


class EnvironmentPathTests(unittest.TestCase):
    def test_virtualenv_python_symlink_path_is_preserved(self):
        self.assertIsNotNone(executable_path,'Virtualenv executable path preservation is missing')
        with tempfile.TemporaryDirectory() as temporary:
            system=Path(temporary)/'system-python';system.write_text('fixture')
            venv=Path(temporary)/'venv/bin/python';venv.parent.mkdir(parents=True);venv.symlink_to(system)
            self.assertEqual(executable_path(venv),venv.absolute())
            self.assertNotEqual(executable_path(venv),venv.resolve())


class CacheManifestTests(unittest.TestCase):
    def test_exact_four_artifacts_are_required_before_reuse(self):
        self.assertIsNotNone(validate_cache_manifest,'Mandatory cache artifact set is missing')
        names=['timeline.json','sparse.json','dense-request.json','dense.json']
        receipt=dict(sourceSha256='a'*64,recipeSha256='b'*64,filesSha256={n:'c'*64 for n in names})
        validate_cache_manifest(receipt,'a'*64,'b'*64)
        for values in [{},{n:'c'*64 for n in names[:-1]},dict(receipt['filesSha256'],unexpected='c'*64),
                       dict(receipt['filesSha256'],**{'dense.json':'not-a-digest'})]:
            with self.subTest(values=values),self.assertRaises(ValueError):
                validate_cache_manifest(dict(receipt,filesSha256=values),'a'*64,'b'*64)
        with self.assertRaises(ValueError):validate_cache_manifest(receipt,'d'*64,'b'*64)


if __name__=='__main__':unittest.main()
