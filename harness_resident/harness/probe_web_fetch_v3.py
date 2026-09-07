"""Run against an existing approved EGRESS registry. Never edits approvals or enables sources."""
import argparse,json
import web_fetch_v3 as web
p=argparse.ArgumentParser();p.add_argument('--egress',required=True);p.add_argument('--lane',default='research');p.add_argument('--query',default='Python documentation');p.add_argument('--url',default='https://docs.python.org/3/');a=p.parse_args()
report={'fetch':web.fetch(a.url,a.lane,egress_path=a.egress),'search':web.search(a.query,a.lane,n=8,egress_path=a.egress)}
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(r['ok'] for r in report.values()) else 1)
