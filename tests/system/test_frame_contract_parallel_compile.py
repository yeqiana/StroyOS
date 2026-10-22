from __future__ import annotations
import sys,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'episodes/_system'))
import frame_contract
class FrameParallelTest(unittest.TestCase):
 def test_parallel_workers_are_isolated_before_single_index(self):
  with tempfile.TemporaryDirectory() as raw:
   ep=Path(raw);(ep/'meta').mkdir();(ep/'meta/story-gates.json').write_text('{}'); active=[];peak=[0];guard=threading.Lock()
   old=(frame_contract.frame_count,frame_contract.required,frame_contract.story_dna_trace.build,frame_contract.compile_frame,frame_contract.preimage_authority_snapshot.build,frame_contract.preimage_authority_snapshot.stale,frame_contract.preimage_authority_snapshot.stale_owned,frame_contract.storyos_config.load_config)
   frame_contract.frame_count=lambda _:20;frame_contract.required=lambda _:False;frame_contract.story_dna_trace.build=lambda _:{};frame_contract.preimage_authority_snapshot.build=lambda _,write=True:{'snapshot_id':'s','authority_sha256':{}};frame_contract.preimage_authority_snapshot.stale=lambda *_:False;frame_contract.preimage_authority_snapshot.stale_owned=lambda *_:False;frame_contract.storyos_config.load_config=lambda :{'runtime':{'workers':{'derived':6},'preimage_parallel_enabled':True}}
   def fake(_,n,write_cache=True):
    with guard: active.append(n);peak[0]=max(peak[0],len(active))
    time.sleep(.03)
    with guard: active.remove(n)
    return {'frame':f'{n:02d}','contract_sha256':str(n),'hash_material':{'storyboard_frame_sha256':str(n),'environment_frame_sha256':str(n),'frame_directive_sha256':str(n)}}
   frame_contract.compile_frame=fake
   try: index=frame_contract.compile_all(ep)
   finally: frame_contract.frame_count,frame_contract.required,frame_contract.story_dna_trace.build,frame_contract.compile_frame,frame_contract.preimage_authority_snapshot.build,frame_contract.preimage_authority_snapshot.stale,frame_contract.preimage_authority_snapshot.stale_owned,frame_contract.storyos_config.load_config=old
   self.assertEqual(index['frame_count'],20);self.assertGreater(peak[0],1);self.assertEqual(len({x['frame'] for x in index['frames']}),20)
