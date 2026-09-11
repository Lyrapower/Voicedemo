"""Synthetic cases from the reported envelope shape; NOT captured production bodies."""
import hashlib
import json
import unittest
from harness.option_shadow_ledger import Theta, ThetaError, settle_leg
from tests.test_option_shadow_ledger import fake, LEG, D, row

ROWS=[{'symbol':'SPY','expiration':'2026-09-11'}]

class EnvelopeTests(unittest.TestCase):
    def theta(self,payload):
        return Theta(opener=lambda _:json.dumps(payload))
    def test_flat_still_supported(self):
        t=self.theta(ROWS)
        self.assertEqual(t.expirations('SPY'),['2026-09-11'])
        self.assertEqual(t.log[-1]['response_shape'],'flat_array')
    def test_reported_envelope_shape(self):
        t=self.theta({'response':ROWS})
        self.assertEqual(t.expirations('SPY'),['2026-09-11'])
        self.assertEqual(t.log[-1]['response_shape'],'response_envelope')
        self.assertEqual(t.log[-1]['row_count'],1)
    def test_hash_is_original_bytes(self):
        raw=' { "response" : [ { "symbol":"SPY", "expiration":"2026-09-11" } ] }\n'
        t=Theta(opener=lambda _:raw)
        t.expirations('SPY')
        self.assertEqual(t.log[-1]['sha256'],hashlib.sha256(raw.encode()).hexdigest())
    def test_empty_response_is_no_rows(self):
        self.assertEqual(self.theta({'response':[]}).expirations('SPY'),[])
    def test_bad_envelopes(self):
        for p in ({'response':None},{'response':{}},{'response':'[]'},{'response':[1]},
                  {'response':[[1]]},{'data':ROWS},{'response':{'response':ROWS}},
                  {'response':ROWS,'unexpected':True},{'response':ROWS,'header':[]}):
            with self.subTest(p=p),self.assertRaisesRegex(ThetaError,'schema_error'):
                self.theta(p).expirations('SPY')
    def test_upstream_errors_with_rows_fail(self):
        for field,value in [('error','bad'),('error_type','BAD_REQUEST'),('errors',['bad']),('status','failed')]:
            for nested in (True,False):
                p={'response':ROWS}
                if nested:p['header']={field:value}
                else:p[field]=value
                with self.subTest(field=field,nested=nested),self.assertRaisesRegex(ThetaError,'upstream_error'):
                    self.theta(p).expirations('SPY')
    def test_error_contents_not_copied_to_receipt(self):
        t=self.theta({'response':ROWS,'error':'secret_fixture_value'})
        with self.assertRaises(ThetaError):t.expirations('SPY')
        self.assertNotIn('secret_fixture_value',json.dumps(t.log))
    def test_empty_error_header(self):
        t=self.theta({'response':ROWS,'header':{'error_type':None,'error_msg':'','next_page':None},'status':'ok'})
        self.assertEqual(t.expirations('SPY'),['2026-09-11'])
    def test_pagination_not_silently_dropped(self):
        for p in ({'response':ROWS,'next_page':'cursor'}, {'response':ROWS,'header':{'next_page':'http://other'}}):
            with self.assertRaisesRegex(ThetaError,'pagination_not_supported'):self.theta(p).expirations('SPY')
    def test_duplicate_keys_rejected(self):
        raw='{"response":[],"response":[]}'
        with self.assertRaisesRegex(ThetaError,'schema_error'):Theta(opener=lambda _:raw).expirations('SPY')
    def test_nan_rejected_in_envelope(self):
        with self.assertRaisesRegex(ThetaError,'schema_error'):Theta(opener=lambda _:'{"response":[{"expiration":NaN}]}').expirations('SPY')
    def test_bad_expiration_row_not_no_chain(self):
        for row_ in ({'expiration':'2026-09-11'},{'symbol':'QQQ','expiration':'2026-09-11'},{'symbol':'SPY'}):
            with self.assertRaisesRegex(ThetaError,'schema_error'):self.theta({'response':[row_]}).expirations('SPY')
    def test_shadow_all_three_endpoints_enveloped(self):
        fixture=fake()
        wrapped=Theta(opener=lambda u:json.dumps({'response':json.loads(fixture.open(u))}))
        r=settle_leg(wrapped,LEG,D)
        self.assertEqual(r['status'],'settled')
        self.assertEqual(r['net'],28.7)
        self.assertEqual(len(r['data_receipts']),4)
        self.assertTrue(all(e['response_shape']=='response_envelope' for e in r['data_receipts']))
    def test_envelope_does_not_bypass_contract_gate(self):
        leg=dict(LEG);del leg['strike']
        t=self.theta({'response':ROWS})
        self.assertEqual(settle_leg(t,leg,D)['status'],'unsettled:contract_not_selected')
        self.assertEqual(t.log,[])
    def test_envelope_does_not_bypass_quote_validation(self):
        bad=row('09:45:00.000',2,1)
        fixture=fake(entry=[bad])
        t=Theta(opener=lambda u:json.dumps({'response':json.loads(fixture.open(u))}))
        self.assertEqual(settle_leg(t,LEG,D)['status'],'unsettled:no_valid_quote')
