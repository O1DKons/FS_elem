import sys, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_type_model import fit_classifier, score_classifier, grouped_folds, metrics, validate_clip_duration

class VideoTypeTests(unittest.TestCase):
    def test_fold_groups_disjoint_and_complete(self):
        groups=['1','1','2','3','4','5','6']
        folds=grouped_folds(groups)
        self.assertEqual(sorted(i for _,te in folds for i in te),list(range(len(groups))))
        for tr,te in folds:
            self.assertFalse(set(groups[i] for i in tr)&set(groups[i] for i in te))
    def test_classifier_uses_training_classes_only(self):
        x=np.array([[1.,0.],[.9,.1],[0.,1.],[.1,.9]])
        for method in ['ridge','centroid']:
            model=fit_classifier(x,np.array(['1A','1A','other','other']),method)
            self.assertEqual(model['classes'].tolist(),['1A','other'])
            p=model['classes'][score_classifier(model,x).argmax(axis=1)]
            self.assertEqual(p.tolist(),['1A','1A','other','other'])
    def test_binary_metrics_count_false_axels(self):
        result=metrics(['1A','other','2A'],['1A','2A','other'])
        self.assertEqual(result['axel_precision'],.5)
        self.assertEqual(result['axel_recall'],.5)

    def test_short_clip_limits(self):
        validate_clip_duration(60,3600)
        with self.assertRaises(ValueError): validate_clip_duration(60.1)
        with self.assertRaises(ValueError): validate_clip_duration(0,3601)
