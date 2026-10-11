"""Isolated native-gateway verification; never touches installed credentials or ports."""
import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import yaml
from api_accounts import APIAccounts, SERVICES
from backend import Controller

EXE=Path(__file__).resolve().parents[1]/'build/payload/cli-proxy-api.exe'

@unittest.skipUnless(EXE.exists(),'Native Windows gateway is not built on this platform')
class NativeAPIAccountsTests(unittest.TestCase):
    def test_all_five_services_register_isolated_models_and_openai_route(self):
        received=[]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path,body,self.headers.get('Authorization')))
                payload=json.dumps({'id':'demo','object':'chat.completion','created':1,'model':'gpt-route-test',
                    'choices':[{'index':0,'message':{'role':'assistant','content':'verified'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(payload)
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'auth').mkdir()
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                config={'config-version':8,'server':{'host':'127.0.0.1','port':port},
                        'access':{'api-keys':['dummy-client']},'management':{'allow-remote':False,'disable-control-panel':True,'secret-key':'dummy-management'},
                        'oauth':{'auth-dir':str(root/'auth')}}
                (root/'config.yaml').write_text(yaml.safe_dump(config),encoding='utf-8')
                with (root/'native.log').open('wb') as log:
                    process=subprocess.Popen([str(EXE),'-config',str(root/'config.yaml'),'-local-model'],cwd=root,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    try:
                        c=Controller(proxy_dir=root,data_dir=root/'data');c.base=f'http://127.0.0.1:{port}';c.key='dummy-management'
                        for _ in range(100):
                            try:c.request('/auth-files');break
                            except Exception:time.sleep(.1)
                        else:self.fail('Native gateway did not start')
                        manager=APIAccounts(c)
                        native_services=dict(SERVICES)
                        native_services['OpenAI']=('openai-compatibility',f'http://127.0.0.1:{upstream.server_port}/v1','/models')
                        with patch.dict(SERVICES,native_services),patch.object(manager,'discover',return_value=[{'name':'gpt-route-test','display-name':'Demo'}]):
                            for service in SERVICES:manager.add(service,'dummy-'+service)
                        request=urllib.request.Request(c.base+'/v1/models',headers={'Authorization':'Bearer dummy-client'})
                        for _ in range(60):
                            with urllib.request.urlopen(request,timeout=3) as response:
                                ids={m['id'] for m in json.load(response)['data']}
                            if all('api-'+s.lower()+'/gpt-route-test' in ids for s in SERVICES):break
                            time.sleep(.1)
                        else:self.fail('Native gateway lost provider API aliases')
                        self.assertNotIn('gpt-route-test',ids)
                        payload=json.dumps({'model':'api-openai/gpt-route-test','messages':[{'role':'user','content':'test'}]}).encode()
                        request=urllib.request.Request(c.base+'/v1/chat/completions',data=payload,headers={'Authorization':'Bearer dummy-client','Content-Type':'application/json'})
                        with urllib.request.urlopen(request,timeout=8) as response:body=json.load(response)
                        self.assertEqual(body['choices'][0]['message']['content'],'verified')
                        self.assertEqual(received[0][1]['model'],'gpt-route-test')
                        self.assertEqual(received[0][2],'Bearer dummy-OpenAI')
                        for account in manager.accounts():
                            manager.set_paused(account['name'], True)
                        for _ in range(60):
                            paused_request=urllib.request.Request(c.base+'/v1/models',headers={'Authorization':'Bearer dummy-client'})
                            with urllib.request.urlopen(paused_request,timeout=3) as response:
                                paused_ids={m['id'] for m in json.load(response)['data']}
                            if not any(model.startswith('api-') for model in paused_ids):break
                            time.sleep(.1)
                        else:self.fail('Paused API credentials still expose model routes: '+repr(paused_ids))
                        self.assertEqual(len(manager.accounts()),5)
                        for account in manager.accounts():
                            self.assertTrue(account['disabled'])
                            manager.set_paused(account['name'],False)
                        restored_request=urllib.request.Request(c.base+'/v1/models',headers={'Authorization':'Bearer dummy-client'})
                        for _ in range(60):
                            with urllib.request.urlopen(restored_request,timeout=3) as response:
                                restored_ids={m['id'] for m in json.load(response)['data']}
                            if all('api-'+s.lower()+'/gpt-route-test' in restored_ids for s in SERVICES):break
                            time.sleep(.1)
                        else:self.fail('Resumed API credentials did not restore routes: '+repr(restored_ids))
                        rows=manager.accounts();manager.change(rows[0]['name'],3);manager.remove(rows[1]['name'])
                        self.assertEqual(len(manager.accounts()),4)
                    finally:
                        process.terminate();process.wait(timeout=10)
        finally:
            upstream.shutdown();upstream.server_close()
