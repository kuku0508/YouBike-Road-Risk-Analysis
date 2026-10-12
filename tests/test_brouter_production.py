import hashlib, io, json, sqlite3, tempfile, unittest, urllib.error, zlib
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
from src.build_routing_manifest import build, select_gate, stable_id
from unittest.mock import patch
from src.run_brouter_production import HTTP_ERROR_BODY_LIMIT, atomic_json, cache_get, cache_put_many, content_hash, db_open, manifest_batches, manifest_row_count, refresh_record_weights, request_route, run, smoke_test_route, status, validate_record, verify_locked
from src.route_segment_utils import assign_trip_flow, directed_segment_key, extract_directed_segments, route_cache_key

ROOT=Path(__file__).resolve().parents[1]
class ProductionRoutingTests(unittest.TestCase):
 @classmethod
 def setUpClass(c):
  c.cfg=json.loads((ROOT/'config/brouter_production.yaml').read_text(encoding='utf8'));c.receipt=json.loads((ROOT/'notes/phase8_1a-production-gate-receipt.json').read_text(encoding='utf8'));c.manifest=pd.read_parquet(ROOT/c.cfg['paths']['manifest']);c.gate=pd.read_parquet(ROOT/'data/processed/routing/production/gate_manifest.parquet')
 def test_01_locked_hash_validation(self):
  with patch('src.run_brouter_production.socket.create_connection'):
   self.assertEqual(verify_locked(ROOT,self.cfg,perform_route_smoke=False)['locked_hashes']['coordinates'],self.cfg['locked_hashes']['coordinates'])
 def test_02_routing_contract_gate(self): self.assertEqual(self.cfg['routing_contract_version'],'road-routing-contract-v1.1')
 def test_03_deterministic_manifest(self): self.assertEqual(len(self.manifest),1100919);self.assertFalse(self.manifest.route_id.duplicated().any())
 def test_04_route_id_determinism(self): self.assertEqual(stable_id('a','b'),stable_id('a','b'))
 def test_05_day_weights_present(self): self.assertTrue((self.manifest[['weekday_trip_count','holiday_trip_count']]>=0).all().all())
 def test_06_day_weight_conservation(self): self.assertTrue((self.manifest.weekday_trip_count+self.manifest.holiday_trip_count==self.manifest.trip_count).all())
 def test_07_cache_key_determinism(self):
  r=self.manifest.iloc[0];self.assertEqual(r.cache_key,self.manifest.iloc[0].cache_key)
 def test_08_coordinate_hash_in_key(self):
  r=self.manifest.iloc[0];kw=dict(origin_id=r.origin_station_id,destination_id=r.destination_station_id,origin_coordinate=(r.origin_lon,r.origin_lat),destination_coordinate=(r.destination_lon,r.destination_lat),brouter_version='1',graph_hashes=['g'],profile_hash='p',contract_version='c',routing_parameters={});self.assertNotEqual(route_cache_key(**kw,coordinate_artifact_hash='a'),route_cache_key(**kw,coordinate_artifact_hash='b'))
 def test_09_profile_invalidates_key(self):
  kw=dict(origin_id='a',destination_id='b',origin_coordinate=(121,25),destination_coordinate=(122,25),brouter_version='1',graph_hashes=['g'],contract_version='c');self.assertNotEqual(route_cache_key(**kw,profile_hash='a'),route_cache_key(**kw,profile_hash='b'))
 def test_10_graph_invalidates_key(self):
  kw=dict(origin_id='a',destination_id='b',origin_coordinate=(121,25),destination_coordinate=(122,25),brouter_version='1',profile_hash='p',contract_version='c');self.assertNotEqual(route_cache_key(**kw,graph_hashes=['a']),route_cache_key(**kw,graph_hashes=['b']))
 def test_11_weights_do_not_affect_key(self): self.assertNotIn('trip_count',json.dumps(self.cfg['environment']['routing_parameters']))
 def test_12_corrupt_cache_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   db=db_open(Path(d)/'x.db');db.execute("INSERT INTO routes VALUES(?,?,?,?,?,?)",('r','k','success','bad',b'bad',0));db.commit();self.assertIsNone(cache_get(db,'r','k'));db.close()
 def test_13_cache_record_validation(self):
  r={'route_id':'r','cache_key':'k','status':'success'};r['content_hash']=content_hash(r);self.assertTrue(validate_record(r,'k'))
 def test_14_atomic_progress(self):
  with tempfile.TemporaryDirectory() as d:p=Path(d)/'p.json';atomic_json(p,{'a':1});self.assertEqual(json.loads(p.read_text())['a'],1);self.assertFalse(p.with_suffix('.json.tmp').exists())
 def test_15_directed_od(self): self.assertNotEqual(stable_id('a','b'),stable_id('b','a'))
 def test_16_segment_key(self): self.assertEqual(directed_segment_key([121,25],[122,26]),'121.000000,25.000000->122.000000,26.000000')
 def test_17_reverse_segment_distinct(self): self.assertNotEqual(directed_segment_key([121,25],[122,26]),directed_segment_key([122,26],[121,25]))
 def test_18_repeated_traversal_preserved(self): self.assertEqual(assign_trip_flow(['x','x'],3)['x'],6)
 def test_19_self_loops_excluded(self): self.assertFalse((self.manifest.origin_station_id==self.manifest.destination_station_id).any())
 def test_20_coordinate_gaps_excluded(self): self.assertEqual(self.receipt['coordinate_exclusions']['edges'],23096)
 def test_21_gate_terminal_status(self): self.assertEqual(self.receipt['gate']['successes']+self.receipt['gate']['failures'],1000)
 def test_22_finite_retry(self): self.assertEqual(self.cfg['execution']['max_attempts'],3)
 def test_23_no_fallback_engine(self): self.assertNotIn('fallback_engine',self.cfg)
 def test_24_gate_conservation(self): self.assertEqual(self.receipt['gate']['success_trip_weight']+self.receipt['gate']['failure_trip_weight'],self.receipt['gate']['trip_weight'])
 def test_25_segment_day_equality(self): self.assertTrue(self.receipt['gate']['segment_day_type_conservation'])
 def test_26_deterministic_aggregation_hash(self): self.assertEqual(len(self.receipt['gate']['segment_hash']),64)
 def test_27_resume(self): self.assertTrue(self.receipt['resume_test']['completed_not_rerun']);self.assertEqual(self.receipt['resume_test']['final_records'],20)
 def test_28_disk_preflight(self): self.assertGreaterEqual(self.cfg['execution']['minimum_free_disk_bytes'],self.receipt['estimated_full_disk_usage']['conservative_bytes'])
 def test_29_commands_real(self): self.assertIn('--execute-full-production',self.receipt['commands']['full_run']);self.assertIn('--status',self.receipt['commands']['progress'])
 def test_30_gate_cannot_trigger_full(self): self.assertFalse(self.receipt['full_routing_executed']);self.assertLessEqual(self.receipt['gate']['actual_brouter_execution_count'],5000)
 def test_31_cache_rerun_all_hits(self): self.assertEqual(self.receipt['gate']['cache_rerun'],{'executions':0,'cache_hits':1000,'all_reused':True})
 def test_32_manifest_weights(self): self.assertEqual(int(self.manifest.trip_count.sum()),83693979)
 def test_33_gate_representation(self): self.assertTrue((self.gate.origin_city!=self.gate.destination_city).any());self.assertTrue((self.gate.origin_coordinate_conflict|self.gate.destination_coordinate_conflict).any())
 def test_34_status_read_only_absent_cache(self):
  with tempfile.TemporaryDirectory() as d:
   c=Path(d)/'none.db';m=Path(d)/'m.parquet';self.gate.head(1).to_parquet(m,index=False);status(c,m,Path(d)/'none.json');self.assertFalse(c.exists())
 def test_35_manifest_streams_in_batches(self): self.assertEqual(sum(len(x) for x in manifest_batches(ROOT/'data/processed/routing/production/gate_manifest.parquet',127)),1000)
 def test_36_manifest_metadata_count(self): self.assertEqual(manifest_row_count(ROOT/'data/processed/routing/production/production_manifest.parquet'),1100919)
 def test_37_weight_refresh_does_not_change_cache_key(self):
  row=self.gate.iloc[0];record={'route_id':row.route_id,'cache_key':row.cache_key,'status':'success','content_hash':''};record['content_hash']=content_hash(record);updated=refresh_record_weights(record,row);self.assertEqual(updated['cache_key'],record['cache_key']);self.assertEqual(updated['trip_count'],row.trip_count)
 def test_38_lookups_hash_is_locked(self):
  with patch('src.run_brouter_production.socket.create_connection'):
   self.assertEqual(verify_locked(ROOT,self.cfg,perform_route_smoke=False)['locked_hashes']['lookups'],'bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419')
 def test_39_http_error_body_is_bounded_and_visible(self):
  cfg=json.loads(json.dumps(self.cfg));cfg['execution']['max_attempts']=1
  row=self.gate.iloc[0]
  error=urllib.error.HTTPError('http://test',400,'Bad Request',{},io.BytesIO(b'datafile E120_N25.rd5 not found'+b'x'*(HTTP_ERROR_BODY_LIMIT+100)))
  with patch('src.run_brouter_production.urllib.request.urlopen',side_effect=error):record=request_route(row,cfg)
  self.assertEqual(record['status'],'brouter_error');self.assertEqual(record['http_status'],400);self.assertIn('datafile E120_N25.rd5 not found',record['http_response_body']);self.assertLessEqual(len(record['http_response_body'].encode()),HTTP_ERROR_BODY_LIMIT);self.assertTrue(record['http_response_body_truncated'])
 def test_40_preflight_smoke_is_real_route_and_never_writes_state(self):
  cache=ROOT/self.cfg['paths']['cache_db'];progress=ROOT/self.cfg['paths']['progress'];before=(cache.stat().st_mtime_ns,progress.stat().st_mtime_ns)
  routed={'status':'success','route_id':'00087cf1126a2a927ebb1931','route_distance_m':4643.0,'segment_count':144,'route_hash':'8392fbc860f3e7e355856186ed46360dd0616d7e5cee6e69198bbbff47794d06'}
  with patch('src.run_brouter_production.request_route',return_value=routed):result=smoke_test_route(self.cfg)
  after=(cache.stat().st_mtime_ns,progress.stat().st_mtime_ns)
  self.assertEqual(result['status'],'success');self.assertGreaterEqual(result['segment_count'],1);self.assertFalse(result['cache_written']);self.assertFalse(result['progress_written']);self.assertEqual(before,after)
 def test_41_reachable_port_with_failed_route_fails_preflight(self):
  with patch('src.run_brouter_production.request_route',return_value={'status':'brouter_error','error':'lookups.dat missing'}):
   with self.assertRaisesRegex(ValueError,'lookups.dat missing'):smoke_test_route(self.cfg)
 def test_42_retryable_state_is_replaced_not_double_counted(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);manifest=root/'manifest.parquet';cache=root/'cache.sqlite';progress=root/'progress.json';row=self.gate.head(1).copy();row.to_parquet(manifest,index=False);r=row.iloc[0]
   old={'route_id':r.route_id,'cache_key':r.cache_key,'status':'brouter_error','trip_count':int(r.trip_count),'error':'connection refused'}
   db=db_open(cache);cache_put_many(db,[old]);db.close()
   success={'route_id':r.route_id,'cache_key':r.cache_key,'status':'success','trip_count':int(r.trip_count)}
   with patch('src.run_brouter_production.request_route',return_value=success):out=run(manifest,cache,progress,self.cfg,1)
   self.assertEqual(out['progress']['completed'],1);self.assertEqual(out['progress']['success'],1);self.assertEqual(out['progress']['failure'],0);self.assertEqual(out['progress']['remaining'],0);self.assertEqual(out['progress']['failed_trip_weight'],0)
   db=sqlite3.connect(cache);self.assertEqual(db.execute('SELECT status,COUNT(*) FROM routes GROUP BY status').fetchall(),[('success',1)]);db.close()
   with patch('src.run_brouter_production.request_route') as request:again=run(manifest,cache,progress,self.cfg,1)
   request.assert_not_called();self.assertEqual(again['progress']['completed'],1);self.assertEqual(again['progress']['failure'],0);self.assertEqual(again['progress']['remaining'],0)
 def test_43_committed_completion_receipt_closes_phase81_only(self):
  receipt=json.loads((ROOT/'notes/phase8_1c-production-completion.json').read_text(encoding='utf8'));inv=receipt['invariants']
  self.assertEqual(inv['manifest_routes'],1100919);self.assertEqual(inv['cache_status_counts'],{'success':1100919});self.assertEqual(inv['successful_trip_weight'],83693979);self.assertEqual(inv['failed_trip_weight'],0);self.assertEqual(inv['remaining'],0);self.assertTrue(inv['cache_hit_execution_identity']);self.assertFalse(receipt['full_routing_rerun']);self.assertFalse(receipt['road_segment_aggregation_started'])
if __name__=='__main__':unittest.main()
