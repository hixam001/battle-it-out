# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from backend.submission_bundle import bundle as B
from backend.submission_registry import registry as R
from backend.submission_check import trial as T
from backend.match_runner import launcher as L

BOT = b'from strategy import value\nfrom biohelpers import clamp\nanswer = clamp(value(), 0, 10)\ndef turn():\n    pass\n'
FILES = {'bot.py': BOT, 'strategy.py': b'def turn(value):\n    return value\ndef value():\n    return turn(2)\n', 'requirements.json': b'{"biohelpers":"1.0.0"}'}
CAPTAIN = R.Actor('captain', 'participant', frozenset({'ta'}), frozenset({'ta'}), frozenset({'cup'}))

def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return output.getvalue()

class Bundles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = R.Registry(self.root / 'submissions', self.root / 'registry.json')
        self.registry.root.mkdir(exist_ok=True)
    def tearDown(self):
        for path in self.registry.root.glob('*'):
            if path.is_dir(): path.chmod(0o700)
        self.tmp.cleanup()
    def upload(self, files=FILES, key='one'):
        return R.submit_bundle(self.registry, CAPTAIN, 'ta', 'cup', archive(files), idempotency_key=key, deadline_at=time.time()+1000)
    def test_bundle_is_pinned_deterministically_with_curated_bytes(self):
        files = B.unpack(archive(FILES))
        self.assertEqual(files['biohelpers.py'], B.HELPERS)
        self.assertEqual(B.digest(files), B.digest(dict(reversed(list(files.items())))))
        altered = {**files, 'strategy.py': b'def value():\n    return 3\n'}
        self.assertNotEqual(B.digest(files), B.digest(altered))
        self.assertEqual(B.unpack(B.export(files)), files)
    def test_hostile_archives_do_not_write_paths(self):
        cases = [ {**FILES, '../escape.py': b'x=1'}, {**FILES, 'nested/a.py': b'x=1'},
                  {**FILES, 'math.py': b'x=1'}, {'helper.py': b'x=1'},
                  {**FILES, 'requirements.json': b'{"numpy":"latest"}'},
                  {**FILES, 'strategy.py': b'import os\ndef value():\n    return 1'},
                  {**FILES, 'strategy.py': b'from bot import turn\ndef value():\n    return 1'} ]
        for case in cases:
            with self.subTest(case=list(case)), self.assertRaises(B.Invalid): B.unpack(archive(case))
        self.assertFalse((self.root.parent/'escape.py').exists())
    def test_zip_symlinks_duplicates_and_compression_bombs_are_refused(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            member=zipfile.ZipInfo('bot.py');member.external_attr=(0o120777<<16);z.writestr(member,'/etc/passwd')
        with self.assertRaises(B.Invalid):B.unpack(out.getvalue())
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('bot.py',b'def turn(): pass')
            with __import__('warnings').catch_warnings():
                __import__('warnings').simplefilter('ignore');z.writestr('bot.py',b'def turn(): pass')
        with self.assertRaises(B.Invalid):B.unpack(out.getvalue())
        with self.assertRaises(B.Invalid):B.unpack(archive({'bot.py':b'#'+b'x'*(B.MAX_BYTES+1)}))
    def test_snapshot_rejects_changed_dependency_extra_file_and_symlink(self):
        self.upload();folder=self.registry.root/'ta-v1';folder.chmod(0o700)
        for name in ('biohelpers.py','unexpected.txt'):
            if (folder/name).exists():(folder/name).chmod(0o600)
            (folder/name).write_bytes(b'changed')
            with self.assertRaises((B.Invalid,OSError)):B.snapshot(folder)
            if name=='biohelpers.py':(folder/name).write_bytes(B.HELPERS)
            else:(folder/name).unlink()
        (folder/'strategy.py').unlink();(folder/'strategy.py').symlink_to('/etc/passwd')
        with self.assertRaises((B.Invalid,OSError)):B.snapshot(folder)
    def test_idempotent_upload_and_exact_bundle_verdict_activation(self):
        first=self.upload();self.assertEqual(first,self.upload())
        claim=R.claim_check(self.registry,first['id'])
        wrong={'schema':T.SCHEMA,'status':'valid','sha256':hashlib.sha256(BOT).hexdigest(),'reasons':[]}
        with self.assertRaises(R.Conflict):R.record_verdict(self.registry,claim,wrong)
        result=R.record_verdict(self.registry,claim,{**wrong,'sha256':claim.sha256})
        self.assertTrue(result['is_active']);self.assertEqual(result['format'],'python-bundle')
        with self.assertRaises(R.Conflict):self.upload({**FILES,'strategy.py':b'def value():\n    return 4\n'})
    def test_trial_plays_the_complete_exact_snapshot_on_both_sides(self):
        self.upload();folder=self.registry.root/'ta-v1';before=B.snapshot(folder);seen=[]
        def play(root,a,b,map_name):
            candidate=root/(a if a=='candidate' else b)
            seen.append(B.snapshot(candidate))
            return {'outcome':'completed','classification':'normal','ok':True,'winner':'A','reason':'won by score','round':1}
        verdict=T.check_submission(folder,play=play)
        self.assertEqual(verdict['status'],'valid');self.assertEqual(seen,[before,before]);self.assertEqual(verdict['sha256'],B.digest(before))
    def test_helper_changed_before_pin_is_never_used(self):
        first=self.upload();claim=R.claim_check(self.registry,first['id'])
        R.record_verdict(self.registry,claim,{'schema':T.SCHEMA,'status':'valid','sha256':claim.sha256,'reasons':[]})
        R.pin_tournament(self.registry,'cup',['ta'],deadline_at=time.time()-1)
        helper=self.registry.root/'ta-v1/strategy.py';helper.chmod(0o600);helper.write_bytes(b'def value():\n    return 9\n')
        with self.assertRaises(R.Unavailable):R.pinned_folder(self.registry,'cup','ta')
    def test_source_download_checks_scope_and_exports_a_reproducible_bundle(self):
        first=self.upload()
        with self.assertRaises(R.NotFound):R.download_bundle(self.registry,R.Actor('other','participant'),first['id'])
        exported=R.download_bundle(self.registry,CAPTAIN,first['id'])
        self.assertEqual(B.digest(B.unpack(exported)),first['content_hash'])
        with self.assertRaises(R.Conflict):R.download(self.registry,CAPTAIN,first['id'])
    @unittest.skipUnless(os.environ.get('BIO_INTEGRATION')=='1','set BIO_INTEGRATION=1 for a real bundle trial')
    def test_real_engine_checks_native_modules_and_curated_dependency(self):
        self.upload();py=L.resolve_python(None,None,L.load_lock())
        play=T.launcher_play(L.DEFAULT_SCAFFOLD,py,self.root/'out',lock_path=self.root/'host.lock')
        verdict=T.check_submission(self.registry.root/'ta-v1',play=play)
        self.assertEqual(verdict['status'],'valid',verdict['reasons'])
        self.assertEqual(verdict['sha256'],B.digest(B.snapshot(self.registry.root/'ta-v1')))
