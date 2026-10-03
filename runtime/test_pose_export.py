import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


class PoseExportTests(unittest.TestCase):
    def test_dense_wins_actual_pts_and_null_gaps(self):
        import pose_export
        source={'sourceSha256':'a'*64,'width':640,'height':480,'fps':50,'frameCount':3,'duration':.04,'rotationDegrees':0,'timestampsSeconds':[0,.02,.04]}
        points=[[20,30]]*23;scores=[.7]*23
        sparse={'frames':[{'frameIndex':0,'time':0,'points':points,'scores':scores},{'frameIndex':2,'time':.04,'points':[],'scores':[]}]}
        dense={'items':[{'window':{'candidateId':'axel'},'frames':{'0':{'frameIndex':0,'time':0,'points':[[21,31]]*23,'scores':scores}}}]}
        result=pose_export.export_pose('j', source, sparse, dense)
        self.assertEqual(len(result['keypointNames']),23)
        self.assertEqual(result['frames'][0]['density'],'dense')
        self.assertEqual(result['frames'][0]['points'][0]['x'],21)
        self.assertEqual(result['frames'][1]['points'],[None]*23)
        self.assertEqual([f['timeSeconds'] for f in result['frames']],[0,.04])
        sparse['frames'][0]['time']=.01
        with self.assertRaises(ValueError):pose_export.export_pose('j',source,sparse,dense)

    def test_nominal_definition_and_no_private_path(self):
        import pose_export
        raw={'sourceSha256':'a'*64,'sourceMetadata':{'width':640,'height':480,'fps':50,'frameCount':3,'duration':.04},'events':[{'id':'a','family':'axel','start':0,'end':.02,'nominal':'2A','nominalReason':'research_model_proposal'},{'id':'b','family':'other','start':0,'end':.02}], 'models':{'flight':{'path':'/private/secret','sha256':'b'*64}},'recipeSha256':'c'*64}
        result=pose_export.export_result('j',raw)
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['events'][0]['nominalRevolutions'],2.5)
        self.assertIsNone(result['events'][0]['physicalAirborneTurns'])
        self.assertNotIn('/private',str(result))


if __name__=='__main__':unittest.main()
