import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research_macro_risk as macro
import research_sector_references as refs
from research_evidence_cache import load_record,save_record
from test_research_leader_index import days
from test_research_macro_risk import HTML,URL,NOW


class EvidenceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.reference_path=Path(self.temp.name)/'refs.json'
        self.macro_path=Path(self.temp.name)/'pmi.json'
        p=patch.object(refs,'CACHE_PATH',self.reference_path);p.start();self.addCleanup(p.stop)
        p=patch.object(macro,'CACHE_PATH',self.macro_path);p.start();self.addCleanup(p.stop)

    def evidence(self):
        identity='sector_cloud_computing';r=refs.VERIFIED_REFERENCES[identity]
        quote={'board_id':identity,'code':r['code'],'full_name':r['title'],'name':r['name'],
            'source_id':'sector_reference:'+identity,'history_secid':'official:'+r['provider']+':'+r['code'],
            'as_of':'2026-10-30','data_frequency':'daily','last':100,'change_pct':.1}
        history=[{'date':d,'close':100,'return_pct':.1} for d in days(61)]
        return identity,quote,history

    def test_fresh_reference_cache_avoids_network_but_retains_observation_date(self):
        identity,q,h=self.evidence()
        with patch.object(refs,'_collect_one',return_value=(q,h)) as request:
            first=refs.collect_verified_references(NOW,board_ids=[identity],use_cache=True)
            second=refs.collect_verified_references(NOW,board_ids=[identity],use_cache=True)
        self.assertEqual(request.call_count,1)
        self.assertEqual(first[0],second[0]);self.assertEqual(second[0][0]['as_of'],'2026-10-30')
        self.assertTrue(all(s.get('cache_used') for s in second[1]))

    def test_stale_reference_is_never_republished_when_next_session_closes(self):
        identity,q,h=self.evidence()
        save_record(self.reference_path,identity,{'quote':q,'history':h,'fetched_at':NOW})
        with patch.object(refs,'_collect_one',side_effect=TimeoutError('failure')) as request:
            quotes,sources,_=refs.collect_verified_references('2026-11-02T17:00:00+08:00',board_ids=[identity],use_cache=True)
        self.assertTrue(request.called);self.assertEqual(quotes,[])
        self.assertEqual(sources[0]['status'],'error')

    def test_reference_cache_identity_and_last_close_are_verified(self):
        identity,q,h=self.evidence()
        for bad_quote,bad_history in [(dict(q,code='wrong'),h),(q,h[:-1]),(dict(q,last=99),h)]:
            save_record(self.reference_path,identity,{'quote':bad_quote,'history':bad_history,'fetched_at':NOW})
            self.assertIsNone(refs._cached_one(identity,refs.VERIFIED_REFERENCES[identity],NOW))

    def test_pmi_cache_is_reparsed_and_network_failure_keeps_original_publication(self):
        record={'document':HTML,'url':URL,'fetched_at':'2026-10-31T10:00:00+08:00'}
        save_record(self.macro_path,'nbs_pmi',record)
        with patch.object(macro,'fetch_text',side_effect=TimeoutError('timeout')):
            result,source=macro.collect_macro_risk(NOW,use_cache=True)
        self.assertEqual(result['status'],'ok');self.assertEqual(source['status'],'partial')
        self.assertEqual(result['published_at'],'2026-10-31T09:30:00+08:00')
        self.assertIn('TimeoutError',source['error']);self.assertEqual(source['fetched_at'],record['fetched_at'])

    def test_future_expired_or_corrupt_pmi_cache_is_not_used(self):
        for document,url,fetched in [(HTML,URL,'2026-11-01T00:00:00+08:00'),
            (HTML.replace('2026/10/31','2026/07/31'),URL,'2026-10-31T10:00:00+08:00'),
            (HTML,'https://evil.test/fake','2026-10-31T10:00:00+08:00')]:
            save_record(self.macro_path,'nbs_pmi',{'document':document,'url':url,'fetched_at':fetched})
            with patch.object(macro,'fetch_text',side_effect=TimeoutError('timeout')):
                result,_=macro.collect_macro_risk(NOW,use_cache=True)
            self.assertIsNone(result['risk_score'])

    def test_corrupt_cache_file_is_ignored_and_atomic_save_can_recover(self):
        self.reference_path.write_text('{broken',encoding='utf-8')
        self.assertIsNone(load_record(self.reference_path,'a'))
        save_record(self.reference_path,'a',{'value':1})
        self.assertEqual(load_record(self.reference_path,'a'),{'value':1})


if __name__=='__main__':unittest.main()
