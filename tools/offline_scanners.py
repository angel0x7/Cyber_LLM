#!/usr/bin/env python3
"""Real local scanners, clean environment, no model, no dotenv or network access."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tempfile


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime',type=Path,required=True)
    ap.add_argument('--output-dir', type=Path, default=Path('reports/offline/lab3'))
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    runtime=args.runtime.resolve()
    quality=args.output_dir.resolve()
    quality.mkdir(parents=True, exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='llm-sec-student-scanners-'))
    lab=work/'lab3'
    shutil.copytree(root/'labs/lab3', lab,
        ignore=shutil.ignore_patterns('.env', '.venv', '__pycache__', 'reports', 'reference'))
    env={'HOME':str(runtime),'PATH':str(runtime/'bin')+':/usr/bin:/bin',
         'LANG':'C.UTF-8','LLM_OFFLINE':'1','PYTHON_DOTENV_DISABLED':'1',
         'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(root/'tools/offline_guard'),
         'CKV_SKIP_MAPPING':'true','CHECKOV_ENABLE_VERSION_CHECK':'false'}
    results=[]
    for name in ['checkov','semgrep']:
        executable=shutil.which(name,path=env['PATH'])
        if executable!=str(runtime/'bin'/name):
            raise RuntimeError('Scanner must resolve to clean environment: '+name)
        command=[str(runtime/'bin/python'),'-B','scripts/run_'+name+'.py']
        started=time.monotonic()
        proc=subprocess.run(command,cwd=lab,env=env,capture_output=True,text=True,timeout=180)
        (quality/(name+'_scan.log')).write_text(proc.stdout+proc.stderr)
        if proc.returncode:
            raise RuntimeError(name+' wrapper failed; inspect quality log')
        path=lab/'reports'/(name+'.json')
        data=json.loads(path.read_text())
        if name=='checkov':
            reports=data if isinstance(data,list) else [data]
            assert {r['check_type'] for r in reports}=={'terraform','kubernetes','dockerfile'}
            findings=[c for r in reports for c in r['results']['failed_checks']]
            targets=sorted({c['file_path'] for c in findings})
            assert set(targets)=={'/main.tf','/deployment.yaml','/Dockerfile'}
            assert all(r['summary']['parsing_errors']==0 for r in reports)
        else:
            assert not data['errors']
            findings=data['results']
            targets=sorted({str(Path(c['path']).relative_to(lab)) for c in findings})
            assert set(targets)=={'docker/Dockerfile','k8s/deployment.yaml'}
            for finding in findings:
                finding['path']=str(Path(finding['path']).relative_to(lab))
        assert findings, 'Expected meaningful findings on deliberately insecure fixtures'
        (quality/path.name).write_text(json.dumps(data, indent=2)+'\n')
        results.append({'scanner':name,'executable':executable,'command':command,'exit_code':proc.returncode,
                        'seconds':round(time.monotonic()-started,3),'findings':len(findings),'targets':targets,
                        'report':str(quality/path.name),'status':'PASS WITH FIX'})
    result={'status':'PASS WITH FIX','network':'blocked by Python audit guard',
            'gemini_remediation':'NOT RUN','scanners':results}
    (quality/'scanner_results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
