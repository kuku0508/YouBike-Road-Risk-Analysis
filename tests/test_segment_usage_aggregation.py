import unittest
from src.aggregate_road_segment_usage import coordinate_to_e6, parse_segment_key, segmentize_coordinates, synthetic_aggregate, validate_weights

A=[121.0,25.0];B=[121.1,25.1];C=[121.2,25.2]
class SegmentUsageAggregationTests(unittest.TestCase):
 def route(self,coords,total=10,weekday=7,holiday=3):return {'coordinates':coords,'total':total,'weekday':weekday,'holiday':holiday}
 def test_01_plain_route(self):
  rows,qa,_=synthetic_aggregate([self.route([A,B,C])],2);self.assertEqual(len(rows),2);self.assertEqual(sum(r[4] for r in rows),2)
 def test_02_direction_is_distinct(self):
  rows,_,_=synthetic_aggregate([self.route([A,B]),self.route([B,A])],2);self.assertEqual(len(rows),2);self.assertNotEqual(rows[0][:4],rows[1][:4])
 def test_03_repeated_traversal_and_unique_route(self):
  rows,_,_=synthetic_aggregate([self.route([A,B,C,A,B])],2);ab=next(r for r in rows if r[:4]==(121000000,25000000,121100000,25100000));self.assertEqual(ab[4:],(2,1,20,14,6))
 def test_04_consecutive_duplicate_collapses(self):
  segments,qa=segmentize_coordinates([A,A,B]);self.assertEqual(len(segments),1);self.assertEqual(qa['collapsed_consecutive_duplicate_points'],1);self.assertNotEqual(segments[0][:2],segments[0][2:])
 def test_05_six_decimal_canonicalization(self): self.assertEqual(coordinate_to_e6('121.530430'),121530430)
 def test_06_rounding_induced_collapse(self):
  _,qa=segmentize_coordinates([[121.0000001,25],[121.0000002,25],B]);self.assertEqual(qa['collapsed_consecutive_duplicate_points'],1)
 def test_07_weights_propagate(self):
  rows,_,_=synthetic_aggregate([self.route([A,B])],2);self.assertEqual(rows[0][6],rows[0][7]+rows[0][8])
 def test_08_negative_weight_fails(self):
  with self.assertRaises(ValueError):validate_weights(-1,0,-1)
 def test_09_day_type_mismatch_fails(self):
  with self.assertRaises(ValueError):validate_weights(10,8,3)
 def test_10_route_collapsed_below_two_fails(self):
  with self.assertRaises(ValueError):segmentize_coordinates([A,A])
 def test_11_repeated_weight_multiplies(self):
  rows,_,_=synthetic_aggregate([self.route([A,B,A,B])],2);ab=next(r for r in rows if r[:4]==(121000000,25000000,121100000,25100000));self.assertEqual(ab[6],20)
 def test_12_shared_segment_increments_unique_routes(self):
  rows,_,_=synthetic_aggregate([self.route([A,B]),self.route([A,B])],2);self.assertEqual(rows[0][5],2)
 def test_13_chunk_size_invariance(self):
  routes=[self.route([A,B,C]),self.route([B,A]),self.route([A,A,B])];self.assertEqual(synthetic_aggregate(routes,2),synthetic_aggregate(routes,100))
 def test_14_deterministic_fingerprint(self):
  routes=[self.route([A,B,C]),self.route([B,A])];self.assertEqual(synthetic_aggregate(routes,2)[2],synthetic_aggregate(routes,2)[2])
 def test_15_segment_parser_microdegrees(self): self.assertEqual(parse_segment_key('121.530430,25.062450->121.530431,25.062451'),(121530430,25062450,121530431,25062451))
if __name__=='__main__':unittest.main()
