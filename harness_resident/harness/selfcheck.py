"""Stdlib-only local test runner and optional real, read-only Theta probe."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from .option_shadow_ledger import Theta, ThetaError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--require-theta', action='store_true')
    parser.add_argument('--report', help='New evidence directory (must not already exist)')
    args = parser.parse_args()
    if args.offline and args.require_theta:
        parser.error('--offline conflicts with --require-theta')
    root = Path(__file__).resolve().parent.parent
    out = Path(args.report) if args.report else Path(tempfile.mkdtemp(prefix='prestart_v6_'))
    if args.report:
        out.mkdir(parents=True, exist_ok=False)
    report = {'version': 6, 'at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'package_local_tests', 'production_acceptance': 'NOT YET ACCEPTED'}
    with (out/'unittest.log').open('w') as stream:
        suite = unittest.defaultTestLoader.discover(str(root/'tests'), top_level_dir=str(root))
        r = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report['unit'] = {'run': r.testsRun, 'failures': len(r.failures), 'errors': len(r.errors), 'skipped': len(r.skipped)}
    ok = r.wasSuccessful() and r.testsRun > 0 and not r.skipped
    report['theta'] = {'status': 'not_run:unit_failed' if not ok else 'not_run:offline'}
    if ok and not args.offline:
        try:
            port = int(os.environ.get('THETA_PORT', '25503'))
            if not 1 <= port <= 65535:
                raise ValueError('bad_port')
            th = Theta(base=f'http://127.0.0.1:{port}')
            exps = th.expirations('SPY')
            report['theta'] = {'status': 'read_probe_ok' if exps else 'no_chain',
                               'endpoint': 'option/list/expirations', 'receipts': th.log,
                               'shadow_settlement': 'NOT RUN'}
        except ThetaError as exc:
            report['theta'] = {'status': str(exc), 'shadow_settlement': 'NOT RUN', 'receipts': th.log}
        except ValueError:
            report['theta'] = {'status': 'invalid_THETA_PORT', 'shadow_settlement': 'NOT RUN'}
    code = 1 if not ok or report['theta']['status'] == 'invalid_THETA_PORT' else (2 if args.require_theta and report['theta']['status'] != 'read_probe_ok' else 0)
    report['exit_code'] = code
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(f"PRESTART_v6 unit={'PASS' if ok else 'FAIL'} run={r.testsRun} failed={len(r.failures)+len(r.errors)} "
          f"theta={report['theta']['status']} production=NOT_YET_ACCEPTED report={out/'report.json'}")
    if not ok:
        print((out/'unittest.log').read_text(), file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
