"""Run against an explicitly started loopback demo server; creates synthetic runs only."""
import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from side_galaxy.client import Client

SERVER = os.environ.get('SG_SERVER', 'http://127.0.0.1:7980')


def cli(*args):
    return json.loads(subprocess.check_output([sys.executable, '-m', 'side_galaxy.cli', '--server', SERVER, *args], text=True))


async def protocol():
    for writes in (False, True):
        params = StdioServerParameters(command=sys.executable, args=['-m','side_galaxy.cli','--server',SERVER,'mcp'] + (['--allow-writes'] if writes else []), env={**os.environ, 'SG_SERVER':SERVER})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert ('run_experiment' in names) == writes
                assert ('upload_artifact' in names) == writes
                assert {'list_artifacts', 'get_output'} <= names
                assert not (await session.call_tool('list_boards')).isError
                if writes:
                    with tempfile.TemporaryDirectory() as root:
                        package = Path(root) / 'example.zip'
                        cli('pack', 'examples/hello-workload', '--output', str(package))
                        upload = await session.call_tool('upload_artifact', {'bundle_base64': base64.b64encode(package.read_bytes()).decode()})
                        assert not upload.isError, upload
                        artifact = json.loads(upload.content[0].text)
                    plan={'boards':['pi5-edge'],'duration_seconds':1,'template':'workload','artifact_sha256':artifact['sha256'],'interference_cpus':[]}
                    check = await session.call_tool('preflight', {'plan':plan})
                    assert not check.isError
                    started = await session.call_tool('run_experiment', {'plan':plan,'idempotency_key':'mcp-'+str(uuid.uuid4())})
                    assert not started.isError, started
                    batch = json.loads(started.content[0].text)
                    for _ in range(40):
                        result = await session.call_tool('get_batch', {'batch_id':batch['id']})
                        data = json.loads(result.content[0].text)
                        if all(r['state']=='succeeded' for r in data['runs']): break
                        await asyncio.sleep(.2)
                    assert all(r['state']=='succeeded' for r in data['runs']), data
    print('MCP stdio: initialize, tools/list, read-only policy, preflight, submit, results OK')


def remote_agent():
    client = Client(SERVER)
    record = client.request('POST','/api/boards',{'name':'REMOTE - SIMULATOR','board_profile':'pi5','system_profile':'simulator'})
    with tempfile.TemporaryDirectory() as root:
        config = Path(root)/'agent.json'
        config.write_text(json.dumps({**record,'server':SERVER,'board_profile':'pi5','system_profile':'simulator'}))
        config.chmod(0o600)
        process = subprocess.Popen([sys.executable,'-m','side_galaxy.cli','agent','--config',str(config),'--state-dir',root+'/state'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            for _ in range(40):
                if any(b['id']==record['board_id'] and b['status']=='ready' for b in cli('boards')): break
                time.sleep(.2)
            package = Path(root) / 'example.zip'
            cli('pack', 'examples/hello-workload', '--output', str(package))
            artifact = cli('artifact-upload', str(package))
            assert any(item['sha256'] == artifact['sha256'] for item in cli('artifacts'))
            plan={'boards':[record['board_id']],'duration_seconds':1,'template':'workload','artifact_sha256':artifact['sha256'],'interference_cpus':[],'arguments':['--label','transport-check'],'environment':{'GALAXY_MESSAGE':'API to agent'}}
            assert client.request('POST','/api/preflight',plan)['valid']
            batch=client.request('POST','/api/batches',plan,'agent-'+str(uuid.uuid4()))
            for _ in range(40):
                final=client.request('GET','/api/batches/'+batch['id'])
                if final['runs'][0]['state']=='succeeded': break
                time.sleep(.2)
            assert final['runs'][0]['state']=='succeeded', final
            assert final['runs'][0]['result']['code_executed'] is False
            assert final['runs'][0]['result']['artifact_sha256'] == artifact['sha256']
        finally:
            process.terminate()
            process.wait(timeout=20)
            process.stderr.close()
    client.http.close()
    print('Independent agent: enroll, heartbeat, claim, execute, result, shutdown OK')


if __name__=='__main__':
    assert len(cli('boards'))>=3
    assert cli('preflight','examples/pi-contention.json')['valid']
    asyncio.run(protocol())
    remote_agent()
    print('CLI JSON and HTTP control plane OK')
