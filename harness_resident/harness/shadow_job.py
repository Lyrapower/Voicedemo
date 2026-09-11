"""Read-only briefs -> immutable shadow JSON. No scheduling or external audit ACK claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .option_shadow_ledger import Theta, parse_date, settle_leg


def publish(path, payload):
    """Atomic no-clobber publication; same bytes are idempotent, changed bytes conflict.
    Parent is a trusted runtime-owned directory. Existing files are never truncated.
    """
    path = Path(path)
    body = (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.shadow-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(tmp,path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != body:
                raise FileExistsError('ledger_conflict: existing evidence preserved')
        if hasattr(os,'O_DIRECTORY'):
            dfd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
    finally:
        os.unlink(tmp)
    return hashlib.sha256(body).hexdigest()


def run_briefs(theta, briefs, d, output):
    if not isinstance(briefs, dict) or briefs.get('schema_version') != 1 or not isinstance(briefs.get('legs'),list) or not 1 <= len(briefs['legs']) <= 100:
        raise ValueError('invalid_briefs_schema')
    if any(not isinstance(leg,dict) for leg in briefs['legs']):
        raise ValueError('invalid_leg')
    input_hash=hashlib.sha256(json.dumps(briefs,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    # Reruns fetch again for evidence; immutable publication detects changed data.
    rows=[settle_leg(theta,leg,d) for leg in briefs['legs']]
    payload=dict(schema_version=1,date=d.isoformat(),mode='shadow',input_sha256=input_hash,
                 production_acceptance='NOT YET ACCEPTED', legs=rows,
                 settled=sum(r['status']=='settled' for r in rows),
                 receipt_delivery='PENDING_EXTERNAL_ACK')
    event_id=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    payload['event_id']=event_id
    digest=publish(output,payload)
    return dict(path=str(output),sha256=digest,event_id=event_id,settled=payload['settled'],total=len(rows),
                receipt_delivery=payload['receipt_delivery'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--briefs',required=True)
    parser.add_argument('--date',required=True,help='Explicit market date, YYYY-MM-DD')
    parser.add_argument('--output',required=True)
    parser.add_argument('--theta-port',type=int,default=25503)
    args=parser.parse_args()
    try:
        path=Path(args.briefs)
        if path.stat().st_size > 1_000_000: raise ValueError('briefs_too_large')
        briefs=json.loads(path.read_text(),parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite_json')))
        summary=run_briefs(Theta(base=f'http://127.0.0.1:{args.theta_port}'),briefs,parse_date(args.date),args.output)
        print(json.dumps(summary,ensure_ascii=False))
        return 0 if summary['settled']==summary['total'] else 2
    except (ValueError,OSError) as exc:
        print(json.dumps({'status':'FAILED','error_type':type(exc).__name__}))
        return 1

if __name__=='__main__': raise SystemExit(main())
