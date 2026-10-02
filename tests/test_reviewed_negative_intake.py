import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'work/safe-reviewed-negative-intake-v1/reviewed.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('reviewed_negative_intake',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
else:module=None


def negative(identifier='n',start=10.0,end=10.5):
    return dict(candidateId=identifier,family='other',sourceSha256='a'*64,
                automaticInterval=dict(start=start,end=end))


class ReviewedNegativeIntakeTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(module,'Safe negative matching is not implemented')

    def test_only_fully_contained_proposal_gets_known_negative_label(self):
        kept,rejected=module.match_negatives([dict(start=10.1,end=10.4),dict(start=10.3,end=10.6)],
                                             [negative()],[], 'a'*64)
        self.assertEqual(len(kept),1)
        self.assertEqual(kept[0]['reviewedNegativeIds'],['n'])
        self.assertEqual(kept[0]['interval'],dict(start=10.1,end=10.4))
        self.assertEqual(len(rejected),1)
        self.assertNotIn('family',rejected[0])

    def test_exact_boundaries_are_allowed_but_context_is_not_declared_negative(self):
        kept,_=module.match_negatives([dict(start=10.0,end=10.5)],[negative()],[], 'a'*64)
        self.assertEqual(kept[0]['labelScope'],'reviewed_candidate_family')
        self.assertFalse(kept[0]['exhaustiveSourceReview'])
        self.assertIsNone(kept[0]['physicalContactTruth'])

    def test_confirmed_positive_overlap_rejects_even_with_negative_window(self):
        kept,rejected=module.match_negatives([dict(start=10.1,end=10.4)],[negative()],
                                             [dict(start=10.35,end=10.8)],'a'*64)
        self.assertEqual(kept,[])
        self.assertEqual(rejected[0]['reason'],'confirmed_positive_overlap')

    def test_source_mismatch_or_nonnegative_input_is_rejected(self):
        for row in [{**negative(),'sourceSha256':'b'*64},{**negative(),'family':'axel'}]:
            with self.subTest(row=row),self.assertRaises(ValueError):
                module.match_negatives([dict(start=10.1,end=10.4)],[row],[],'a'*64)

    def test_duplicate_proposals_are_not_extra_training_events(self):
        kept,rejected=module.match_negatives([dict(start=10.1,end=10.4)]*2,
                                             [negative(),negative('second')],[], 'a'*64)
        self.assertEqual(len(kept),1)
        self.assertEqual(kept[0]['reviewedNegativeIds'],['n','second'])
        self.assertEqual(rejected[0]['reason'],'duplicate_proposal')

    def test_invalid_intervals_cannot_be_silently_used(self):
        for p in [dict(start=True,end=10.4),dict(start=10.4,end=10.1),
                  dict(start=float('nan'),end=10.4),dict(start=-1,end=0)]:
            with self.subTest(p=p),self.assertRaises(ValueError):
                module.match_negatives([p],[negative()],[], 'a'*64)

    def test_native_sparse_source_uses_path_field_and_preserves_absolute_paths(self):
        self.assertTrue(hasattr(module,'source_media'),'Native sparse source path adapter is missing')
        base=Path('/tmp/fs-elem')
        self.assertEqual(module.source_media({'path':'video.mp4'},base),base/'video.mp4')
        self.assertEqual(module.source_media({'path':'/tmp/original.mp4'},base),Path('/tmp/original.mp4'))
        with self.assertRaises(ValueError):module.source_media({'sourcePath':'video.mp4'},base)


class ReviewBindingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(module,'bind_review'),'Candidate review binding is missing')
        self.row={**negative('program-p-candidate-01'),'programId':'program-p'}
        self.prediction=dict(programId='program-p',sourceSha256='a'*64,
            proposals=[dict(proposal=self.row['automaticInterval'],family='axel')])
        self.expert=dict(programId='program-p',labels=[dict(candidate=1,family='other')])
        self.clips=dict(sourceSha256='a'*64,records=[dict(candidate=1,sourceStart=9,sourceEnd=11,
            prediction=self.prediction['proposals'][0])])

    def test_original_prediction_digest_binds_explicit_negative(self):
        proof=module.bind_review(self.row,{**self.expert,'predictionSha256':'b'*64},
                                 self.prediction,'b'*64)
        self.assertEqual(proof['kind'],'prediction_digest')
        self.assertEqual(proof['candidate'],1)

    def test_clip_manifest_digest_also_requires_source_and_same_candidate_interval(self):
        expert={**self.expert,'sourceSha256':'a'*64,'clipsManifestSha256':'c'*64}
        proof=module.bind_review(self.row,expert,self.prediction,'b'*64,self.clips,'c'*64)
        self.assertEqual(proof['kind'],'clips_manifest_digest')
        changed={**self.clips,'records':[{**self.clips['records'][0],
            'prediction':dict(proposal=dict(start=10.1,end=10.4))}]}
        with self.assertRaises(ValueError):
            module.bind_review(self.row,expert,self.prediction,'b'*64,changed,'c'*64)

    def test_missing_recorded_digest_is_quarantined_not_invented(self):
        self.assertIsNone(module.bind_review(self.row,self.expert,self.prediction,'b'*64,
                                            self.clips,'c'*64))

    def test_bound_clip_manifest_is_sufficient_when_prediction_file_is_absent(self):
        expert={**self.expert,'sourceSha256':'a'*64,'clipsManifestSha256':'c'*64}
        proof=module.bind_review(self.row,expert,None,None,self.clips,'c'*64)
        self.assertEqual(proof['kind'],'clips_manifest_digest')
        changed={**self.row,'automaticInterval':dict(start=10,end=10.6)}
        with self.assertRaises(ValueError):module.bind_review(changed,expert,None,None,self.clips,'c'*64)

    def test_missing_original_prediction_cannot_satisfy_prediction_digest_proof(self):
        with self.assertRaises(ValueError):
            module.bind_review(self.row,{**self.expert,'predictionSha256':'b'*64},None,None)

    def test_recorded_wrong_digest_or_source_is_a_hard_failure(self):
        for expert in [{**self.expert,'predictionSha256':'d'*64},
            {**self.expert,'sourceSha256':'d'*64,'clipsManifestSha256':'c'*64}]:
            with self.subTest(expert=expert),self.assertRaises(ValueError):
                module.bind_review(self.row,expert,self.prediction,'b'*64,self.clips,'c'*64)

    def test_changed_proposal_or_duplicate_expert_label_cannot_bind(self):
        expert={**self.expert,'predictionSha256':'b'*64}
        changed={**self.prediction,'proposals':[dict(proposal=dict(start=10,end=10.6))]}
        with self.assertRaises(ValueError):module.bind_review(self.row,expert,changed,'b'*64)
        duplicate={**expert,'labels':self.expert['labels']*2}
        with self.assertRaises(ValueError):module.bind_review(self.row,duplicate,self.prediction,'b'*64)

    def test_positive_label_or_other_program_is_rejected(self):
        for expert in [{**self.expert,'labels':[dict(candidate=1,family='axel')]},
                       {**self.expert,'programId':'program-other'}]:
            with self.subTest(expert=expert),self.assertRaises(ValueError):
                module.bind_review(self.row,{**expert,'predictionSha256':'b'*64},self.prediction,'b'*64)


if __name__=='__main__':unittest.main()
