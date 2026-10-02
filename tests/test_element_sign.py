import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from element_sign import explicit_label,features,evaluate_signs
import numpy as np
class Tests(unittest.TestCase):
 def test_labels(self):
  self.assertEqual(explicit_label(dict(notes='2A<<',rotationAssessment='apparently_short')),'2A<<')
  for text in ['', '2A< or 2A<<','12A','2A<<<']:
   self.assertIsNone(explicit_label(dict(notes=text,rotationAssessment='apparently_short')))
  self.assertIsNone(explicit_label(dict(notes='2A',rotationAssessment='apparently_short')))
 def test_missing_points(self):
  self.assertEqual(features(dict(firstContact=10,frames=[]))[0],0)
  self.assertTrue(np.isnan(features(dict(firstContact=10,frames=[]))[1:]).all())
 def test_grouped_unseen_class(self):
  result=evaluate_signs(np.array([[0.],[1.],[2.],[3.]]),np.array(['2A','2A','2A<','2Aq']),['a','a','b','c'])
  for fold in result['folds']:
   self.assertFalse(set(fold['trainIndices'])&set(fold['testIndices']))
  self.assertNotEqual(result['predictions'][3],'2Aq')

class FlightTests(unittest.TestCase):
 def test_strict_airborne_pairs(self):
  from element_sign import flight_features
  rows=[dict(frameIndex=n,values=[v,v,v]) for n,v in [(10,999),(11,999),(12,2),(13,4),(14,999),(15,999)]]
  self.assertEqual(flight_features(rows,10,14),[3,1,3,1,3,1])
 def test_empty_flight(self):
  from element_sign import flight_features
  self.assertTrue(np.isnan(flight_features([],10,14)).all())
