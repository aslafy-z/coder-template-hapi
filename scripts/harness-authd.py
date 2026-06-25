#!/usr/bin/env python3
import html, json, os, pty, re, select, signal, subprocess, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import Request, urlopen

HOST=os.environ.get('AUTHD_HOST','127.0.0.1'); PORT=int(os.environ.get('AUTHD_PORT','43117'))
HOME=os.path.expanduser('~'); PROJECT=os.environ.get('PROJECT_DIR', os.path.join(HOME,'project'))
URL_RE=re.compile(r'https?://[^\s\]\)<>"\']+')
DEVICE_RE=re.compile(r'\b([A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+)\b')
LOOP_RE=re.compile(r'https?://(?:localhost|127\.0\.0\.1|\[::1\]|::1):(\d+)(/[^\s\?\]\)<>"\']*)')
SESS={}; LOCK=threading.Lock()

def redact(s):
    return re.sub(r'([?&](?:code|state|token|access_token|refresh_token|id_token)=)[^&\s]+', r'\1…', s)

def exists(cmd):
    return subprocess.run(['bash','-lc',f'command -v {cmd}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode==0

def run_status(argv, timeout=5):
    if not exists(argv[0]): return {'ok':False,'detail':'not installed'}
    try:
        p=subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return {'ok':p.returncode==0,'detail':redact(p.stdout.strip() or f'exit {p.returncode}')}
    except Exception as e: return {'ok':False,'detail':str(e)}

def file_status(path): return os.path.exists(os.path.expanduser(path))

def statuses():
    return {
      'github': run_status(['gh','auth','status']) if exists('gh') else {'ok':False,'detail':'gh not installed'},
      'codex': run_status(['codex','login','status']) if exists('codex') else {'ok':file_status('~/.codex/auth.json'),'detail':'auth.json present' if file_status('~/.codex/auth.json') else 'codex not installed'},
      'claude': {'ok': exists('claude') and (bool(os.environ.get('ANTHROPIC_API_KEY')) or bool(os.environ.get('AWS_PROFILE')) or os.path.exists(os.path.expanduser('~/.claude.json'))), 'detail':'env/config detected' if (bool(os.environ.get('ANTHROPIC_API_KEY')) or bool(os.environ.get('AWS_PROFILE')) or os.path.exists(os.path.expanduser('~/.claude.json'))) else ('installed' if exists('claude') else 'not installed')},
      'opencode': {'ok': file_status('~/.local/share/opencode/auth.json'), 'detail':'auth.json present' if file_status('~/.local/share/opencode/auth.json') else ('installed' if exists('opencode') else 'not installed')},
      'hapi': {'ok': run_status(['bash','-lc','pgrep -u $(id -u) -x hapi >/dev/null']).get('ok'), 'detail':'process check'},
      'repo': {'ok': os.path.isdir(os.path.join(PROJECT,'.git')), 'detail': PROJECT},
    }

COMMANDS={
 ('codex','device'): ['codex','login','--device-auth'], ('codex','browser'): ['codex','login'], ('codex','api_key'): ['codex','login','--with-api-key'],
 ('claude','account'): ['claude'], ('opencode','connect'): ['opencode'], ('github','device'): ['gh','auth','login','--web'],
 ('hapi','start'): ['bash','-lc','hapi hub --no-relay'],
}

def reader(sid, fd):
    while True:
        try:
            r,_,_=select.select([fd],[],[],0.5)
            if not r:
                with LOCK:
                    if SESS.get(sid,{}).get('dead'): break
                continue
            data=os.read(fd,4096).decode(errors='replace')
        except OSError: break
        with LOCK:
            s=SESS.get(sid)
            if not s: break
            s['log']=(s.get('log','')+redact(data))[-20000:]
            for u in URL_RE.findall(data):
                ru=redact(u); 
                if ru not in s['urls']: s['urls'].append(ru)
            m=DEVICE_RE.search(data)
            if m: s['device_code']=m.group(1)
            lm=LOOP_RE.search(data)
            if lm:
                s['state']='waiting_callback'; s['expected_port']=int(lm.group(1)); s['expected_path']=lm.group(2) or '/'
    with LOCK:
        if sid in SESS: SESS[sid]['state']='exited'

def start_session(harness, method):
    argv=COMMANDS.get((harness,method))
    if not argv: raise ValueError('unsupported login method')
    if argv[0] != 'bash' and not exists(argv[0]): raise ValueError(f'{argv[0]} is not installed')
    sid=str(uuid.uuid4())[:8]; pid, fd=pty.fork()
    if pid==0:
        os.environ['TERM']='xterm-256color'; os.chdir(PROJECT if os.path.isdir(PROJECT) else HOME); os.execvp(argv[0], argv)
    with LOCK: SESS[sid]={'id':sid,'harness':harness,'method':method,'pid':pid,'fd':fd,'state':'running','log':'','urls':[],'created':time.time()}
    threading.Thread(target=reader,args=(sid,fd),daemon=True).start(); return SESS[sid]

PAGE='''<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Agent Auth</title><style>body{font-family:system-ui;margin:1rem;max-width:900px}.card{border:1px solid #ddd;border-radius:12px;padding:1rem;margin:.75rem 0}button,input{font:inherit;padding:.6rem;margin:.2rem}pre{white-space:pre-wrap;background:#111;color:#eee;padding:1rem;border-radius:8px;max-height:18rem;overflow:auto}.ok{color:green}.bad{color:#a60}</style><h1>🔑 Agent Auth Companion</h1><div id=app>Loading…</div><script>
async function api(p,o){let r=await fetch(p,o);return r.json()} async function refresh(){let st=await api('/api/status'), ss=await api('/api/sessions'); app.innerHTML='<h2>Status</h2>'+Object.entries(st).map(([k,v])=>`<div class=card><b>${k}</b>: <span class=${v.ok?'ok':'bad'}>${v.ok?'OK':'not ready'}</span><br><small>${esc(v.detail||'')}</small></div>`).join('')+'<h2>Login</h2>'+btns()+ '<h2>Sessions</h2>'+ss.map(session).join('')} function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))} function btns(){return [['codex','device','Codex device-code'],['codex','browser','Codex browser replay'],['claude','account','Claude PTY / paste-code'],['opencode','connect','OpenCode /connect PTY'],['github','device','GitHub device login']].map(x=>`<button onclick="start('${x[0]}','${x[1]}')">${x[2]}</button>`).join('')} async function start(h,m){await api('/api/harness/'+h+'/login/'+m,{method:'POST'});refresh()} function session(s){return `<div class=card><b>${s.harness}/${s.method}</b> ${s.id} - ${s.state}<br>${(s.urls||[]).map(u=>`<a target=_blank href="${u}">${u}</a><br>`).join('')}${s.device_code?`<p>Device code: <b>${s.device_code}</b></p>`:''}<input id=in${s.id} placeholder="paste code or callback URL" size=45><button onclick="stdin('${s.id}')">Send stdin</button><button onclick="replay('${s.id}')">Replay callback</button><pre>${esc(s.log||'')}</pre></div>`} async function stdin(id){await api('/api/sessions/'+id+'/stdin',{method:'POST',body:JSON.stringify({text:document.getElementById('in'+id).value+'\\n'})});refresh()} async function replay(id){await api('/api/sessions/'+id+'/replay-url',{method:'POST',body:JSON.stringify({url:document.getElementById('in'+id).value})});refresh()} setInterval(refresh,3000);refresh()</script>'''

class H(BaseHTTPRequestHandler):
    def sendj(self,o,code=200):
        b=json.dumps(o).encode(); self.send_response(code); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def body(self): return json.loads(self.rfile.read(int(self.headers.get('content-length','0') or 0)) or b'{}')
    def do_GET(self):
        if self.path=='/healthz': self.send_response(204); self.end_headers(); return
        if self.path=='/api/status': self.sendj(statuses()); return
        if self.path=='/api/sessions':
            with LOCK: self.sendj([{k:v for k,v in s.items() if k not in ('fd',)} for s in SESS.values()]); return
        b=PAGE.encode(); self.send_response(200); self.send_header('content-type','text/html'); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        parts=self.path.strip('/').split('/')
        try:
            if parts[:2]==['api','harness'] and parts[3]=='login':
                s=start_session(parts[2],parts[4]); self.sendj({k:v for k,v in s.items() if k != 'fd'}); return
            if parts[:2]==['api','sessions'] and parts[3]=='stdin':
                d=self.body(); s=SESS[parts[2]]; os.write(s['fd'], d.get('text','').encode()); self.sendj({'ok':True}); return
            if parts[:2]==['api','sessions'] and parts[3]=='replay-url':
                d=self.body(); s=SESS[parts[2]]; u=urlparse(d.get('url',''))
                if s.get('state')!='waiting_callback': raise ValueError('session is not waiting for a callback')
                if u.hostname not in ('localhost','127.0.0.1','::1'): raise ValueError('only loopback callback URLs are accepted')
                if int(u.port or 0)!=s.get('expected_port') or u.path!=s.get('expected_path'): raise ValueError('unexpected callback target')
                q=u.query
                if 'code=' not in q or 'state=' not in q: raise ValueError('missing oauth code/state')
                target=f'http://127.0.0.1:{s["expected_port"]}{u.path}?{q}'
                r=urlopen(Request(target,method='GET'), timeout=5); s['state']='callback_replayed'; self.sendj({'ok':True,'status':r.status}); return
            self.sendj({'error':'not found'},404)
        except Exception as e: self.sendj({'error':str(e)},400)

if __name__=='__main__':
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()
