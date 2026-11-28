# SPDX-License-Identifier: AGPL-3.0-only
import concurrent.futures
import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from backend.match_runner import launcher as L

@unittest.skipUnless(os.environ.get('BIO_INTEGRATION')=='1','set BIO_INTEGRATION=1 for native live-board transport')
class LiveEngine(unittest.TestCase):
    def test_private_snapshot_changes_during_a_real_game_without_changing_the_engine_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'live/board.json';py=L.resolve_python(None,None,L.load_lock())
            args=(L.DEFAULT_SCAFFOLD,py,L.DEFAULT_SCAFFOLD/'src','examplefuncsplayer_py','examplefuncsplayer_py','DefaultSmall')
            baseline=L.run_match(*args,root/'baseline',120,True,True,cgroup=False)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(L.run_match,*args,root/'live-match',120,True,True,cgroup=False,live_path=path)
                active_rounds=[]
                while not future.done():
                    if path.exists():
                        data=json.loads(path.read_text())
                        if not data['finished']:active_rounds.append(data['round'])
                        with socket.socket() as probe:
                            self.assertNotEqual(probe.connect_ex(('127.0.0.1',6175)),0,'raw engine WebSocket must not listen')
                    time.sleep(.02)
                result=future.result()
            if result['classification'] != 'normal':
                log = Path(result['logs']['server']).read_text(errors='replace')
                self.fail(f"Live game failed: {result}\nServer log tail:\n{log[-2400:]}")
            self.assertEqual((baseline['round'],baseline['reason']),(result['round'],result['reason']))
            self.assertGreater(len(set(active_rounds)),1,'observed actual board changes before game completion')
            board=json.loads(path.read_text());self.assertTrue(board['finished']);self.assertEqual(board['round'],result['round'])
            self.assertEqual(set(board),{'width','height','round','updated_at','finished','robots','walls','dirt','cheese','teams'})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            for robot in board['robots']:
                self.assertEqual(set(robot),{'id','x','y','team','kind','health','cheese','dir'})
                self.assertTrue(all(isinstance(v,int) for v in robot.values()))
