#!/usr/bin/env python3
import json, os, pty, re, select, signal, shutil, subprocess, tempfile, termios, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

HOST=os.environ.get('AUTHD_HOST','127.0.0.1'); PORT=int(os.environ.get('AUTHD_PORT','43117'))
HOME=os.path.expanduser('~'); PROJECT=os.environ.get('PROJECT_DIR', os.path.join(HOME,'project'))
URL_RE=re.compile(r'https?://[^\s\]\)<>"\']+')
ANSI_RE=re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-Z\\-_])')
DEVICE_RE=re.compile(r'\b([A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+)\b', re.I)
LOOP_RE=re.compile(r'https?://(?:localhost|127\.0\.0\.1|\[::1\]|::1):(\d+)(/[^\s\?\]\)<>"\']*)')
SESS={}; LOCK=threading.Lock()

def strip_ansi(s):
    return ANSI_RE.sub('', s)

def redact(s):
    # Keep OAuth state intact in authorization links so browser login URLs remain usable.
    return re.sub(r'([?&](?:code|token|access_token|refresh_token|id_token)=)[^&\s]+', r'\1…', s)

def exists(cmd):
    return subprocess.run(['bash','-lc',f'command -v {cmd}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode==0

def run_status(argv, timeout=5):
    if not exists(argv[0]): return {'ok':False,'detail':'not installed'}
    try:
        p=subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return {'ok':p.returncode==0,'detail':redact(p.stdout.strip() or f'exit {p.returncode}')}
    except Exception as e: return {'ok':False,'detail':str(e)}

def file_status(path): return os.path.exists(os.path.expanduser(path))

def project_subdirs():
    try:
        entries=[]
        for name in sorted(os.listdir(PROJECT)):
            path=os.path.join(PROJECT,name)
            if os.path.isdir(path) and not name.startswith('.'):
                entries.append({'name':name,'git':os.path.isdir(os.path.join(path,'.git'))})
        return entries
    except Exception:
        return []

def safe_project_name(name):
    name=(name or '').strip().strip('/')
    if not name or name in ('.','..') or '/' in name or '\\' in name or name.startswith('.'):
        raise ValueError('destination must be a simple project subdirectory name')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', name):
        raise ValueError('destination may contain only letters, numbers, dots, underscores, and dashes')
    return name

def gh_repo_arg(repo):
    repo=(repo or '').strip()
    if not repo: raise ValueError('repository is required')
    u=urlparse(repo)
    if u.scheme in ('http','https') and u.hostname and u.hostname.lower()=='github.com':
        parts=[x for x in u.path.strip('/').split('/') if x]
        if len(parts) >= 2:
            name=parts[1][:-4] if parts[1].endswith('.git') else parts[1]
            return f'{parts[0]}/{name}'
    return repo

def repo_default_name(repo):
    repo=(repo or '').strip()
    if not repo: raise ValueError('repository is required')
    path=urlparse(repo).path if re.match(r'https?://', repo) else repo
    name=path.rstrip('/').split('/')[-1]
    if name.endswith('.git'): name=name[:-4]
    return safe_project_name(name)

def project_path(name):
    base=os.path.realpath(PROJECT)
    path=os.path.realpath(os.path.join(base, safe_project_name(name)))
    if os.path.commonpath([base, path]) != base:
        raise ValueError('destination escapes project directory')
    return path

def clone_repo(repo, dest=None):
    if not exists('gh'): raise ValueError('gh is not installed')
    os.makedirs(PROJECT, exist_ok=True)
    dest=safe_project_name(dest) if dest else repo_default_name(repo)
    path=project_path(dest)
    if os.path.exists(path): raise ValueError(f'project subdirectory already exists: {dest}')
    p=subprocess.run(['gh','repo','clone',gh_repo_arg(repo),path], cwd=PROJECT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    if p.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        raise ValueError(redact(p.stdout.strip() or f'gh repo clone exited {p.returncode}'))
    return {'ok':True,'name':dest,'path':path,'output':redact(p.stdout.strip())}

def delete_project(name):
    path=project_path(name)
    if not os.path.isdir(path): raise ValueError('project subdirectory does not exist')
    shutil.rmtree(path)
    return {'ok':True,'name':safe_project_name(name)}

def statuses():
    return {
      'github': run_status(['gh','auth','status']) if exists('gh') else {'ok':False,'detail':'gh not installed'},
      'codex': run_status(['codex','login','status']) if exists('codex') else {'ok':file_status('~/.codex/auth.json'),'detail':'auth.json present' if file_status('~/.codex/auth.json') else 'codex not installed'},
      'claude': {'ok': exists('claude') and (bool(os.environ.get('ANTHROPIC_API_KEY')) or bool(os.environ.get('AWS_PROFILE')) or os.path.exists(os.path.expanduser('~/.claude.json'))), 'detail':'env/config detected' if (bool(os.environ.get('ANTHROPIC_API_KEY')) or bool(os.environ.get('AWS_PROFILE')) or os.path.exists(os.path.expanduser('~/.claude.json'))) else ('installed' if exists('claude') else 'not installed')},
      'opencode': {'ok': file_status('~/.local/share/opencode/auth.json'), 'detail':'auth.json present' if file_status('~/.local/share/opencode/auth.json') else ('installed' if exists('opencode') else 'not installed')},
      'hapi': {'ok': run_status(['bash','-lc','pgrep -u $(id -u) -x hapi >/dev/null']).get('ok'), 'detail':'process check'},
      'repo': {'ok': bool(project_subdirs()) or os.path.isdir(os.path.join(PROJECT,'.git')), 'detail': PROJECT, 'projects': project_subdirs()},
    }

COMMANDS={
 ('codex','device'): ['codex','login','--device-auth'], ('codex','browser'): ['codex','login'], ('codex','api_key'): ['bash','-lc','printf \"Paste OpenAI API key, then press Enter: \"; IFS= read -r key; printf \"%s\" \"$key\" | codex login --with-api-key'],
 ('claude','account'): ['claude'], ('opencode','openai_chatgpt'): ['opencode','auth','login','--provider','openai','--method','ChatGPT Plus/Pro'], ('opencode','connect'): ['opencode','auth','login'], ('opencode','interactive'): ['opencode'], ('github','device'): ['gh','auth','login','--web','--hostname','github.com','--git-protocol','https','--skip-ssh-key'],
 ('hapi','start'): ['bash','-lc','hapi hub --no-relay'],
}

INITIAL_STDIN={}

BROWSER_HELPERS={
    'xdg-open', 'open', 'sensible-browser', 'gnome-open', 'kde-open', 'wslview',
    'x-www-browser', 'www-browser', 'firefox', 'google-chrome', 'chromium', 'chromium-browser'
}

def browser_bin_dir(sid):
    return os.path.join(tempfile.gettempdir(), 'harness-authd-browser', sid)

def install_browser_helpers(sid):
    bindir=browser_bin_dir(sid)
    os.makedirs(bindir, exist_ok=True)
    helper=os.path.join(bindir, 'authd-browser-open')
    script=f'''#!/usr/bin/env python3
import json, sys
from urllib.request import Request, urlopen
url = next((a for a in sys.argv[1:] if a.startswith(('http://','https://'))), '')
if url:
    try:
        data=json.dumps({{'url':url}}).encode()
        req=Request('http://{HOST}:{PORT}/api/browser-opened/{sid}', data=data, headers={{'content-type':'application/json'}}, method='POST')
        urlopen(req, timeout=2).read()
    except Exception:
        pass
print(url or 'Browser open requested; no URL argument was provided.')
'''
    with open(helper, 'w') as f:
        f.write(script)
    os.chmod(helper, 0o755)
    for name in BROWSER_HELPERS:
        path=os.path.join(bindir, name)
        try:
            if os.path.lexists(path): os.unlink(path)
            os.symlink(helper, path)
        except OSError:
            pass
    return bindir, helper

def remember_url(s, url):
    if not url or not url.startswith(('http://','https://')):
        return
    url=url.rstrip('.,;:')
    if urlparse(url).hostname in ('localhost','127.0.0.1','::1'):
        return
    if s.get('harness')=='opencode' and 'auth.openai.com/codex/device' in url:
        return
    ru=redact(url)
    if ru and ru not in s['urls']:
        s['urls'].append(ru)

def resize_pty(fd, cols, rows):
    try:
        cols=max(20, min(int(cols), 240)); rows=max(6, min(int(rows), 80))
        termios.tcsetwinsize(fd, (rows, cols))
    except Exception:
        pass

def reader(sid, fd):
    while True:
        try:
            r,_,_=select.select([fd],[],[],0.5)
            if not r:
                with LOCK:
                    if SESS.get(sid,{}).get('dead'): break
                continue
            data=os.read(fd,4096).decode(errors='replace')
            clean=strip_ansi(data)
        except OSError: break
        with LOCK:
            s=SESS.get(sid)
            if not s: break
            s['log']=(s.get('log','')+redact(data))[-20000:]
            for u in URL_RE.findall(clean):
                remember_url(s, u)
            m=DEVICE_RE.search(clean)
            if m: s['device_code']=m.group(1)
            lm=LOOP_RE.search(clean)
            if lm:
                s['state']='waiting_callback'; s['expected_port']=int(lm.group(1)); s['expected_path']=lm.group(2) or '/'
    rc=None
    try:
        _, status=os.waitpid(SESS.get(sid,{}).get('pid',-1), os.WNOHANG)
        if status: rc=os.waitstatus_to_exitcode(status)
    except Exception:
        pass
    with LOCK:
        if sid in SESS:
            SESS[sid]['state']='exited'; SESS[sid]['exit_code']=rc

def start_session(harness, method):
    argv=COMMANDS.get((harness,method))
    if not argv: raise ValueError('unsupported login method')
    if argv[0] != 'bash' and not exists(argv[0]): raise ValueError(f'{argv[0]} is not installed')
    sid=str(uuid.uuid4())[:8]
    bindir, browser_helper = install_browser_helpers(sid)
    pid, fd=pty.fork()
    if pid==0:
        os.environ['TERM']='xterm-256color'
        os.environ.setdefault('NO_COLOR','1')
        os.environ['BROWSER']=browser_helper
        os.environ['PATH']=bindir+os.pathsep+os.environ.get('PATH','')
        os.chdir(PROJECT if os.path.isdir(PROJECT) else HOME)
        os.execvp(argv[0], argv)
    resize_pty(fd, 120, 28)
    with LOCK: SESS[sid]={'id':sid,'harness':harness,'method':method,'pid':pid,'fd':fd,'state':'running','log':'','urls':[],'created':time.time()}
    initial=INITIAL_STDIN.get((harness,method))
    if initial:
        text, delay = initial if isinstance(initial, tuple) else (initial, 0.7)
        threading.Timer(delay, lambda: os.write(fd, text.encode())).start()
    threading.Thread(target=reader,args=(sid,fd),daemon=True).start(); return SESS[sid]

PAGE=r'''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Agent Auth</title><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css"><script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script><style>:root{color-scheme:dark;--bg:#0f172a;--panel:#111827;--text:#e5e7eb;--muted:#9ca3af;--line:#334155;--ok:#34d399;--bad:#fbbf24}*{box-sizing:border-box}body{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;min-height:100vh;background:radial-gradient(circle at top left,#1e3a8a66,transparent 34rem),var(--bg);color:var(--text)}main{width:min(1120px,calc(100% - 2rem));margin:0 auto;padding:1.25rem 0 3rem}h1{font-size:clamp(1.8rem,4vw,3rem);margin:.4rem 0 .2rem}.subtitle{color:var(--muted);margin-top:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.75rem}.card{border:1px solid var(--line);border-radius:16px;padding:1rem;margin:.85rem 0;background:linear-gradient(180deg,#1f2937e6,#111827e6);box-shadow:0 16px 40px #02061733}.status{margin:0}.ok{color:var(--ok)}.bad{color:var(--bad)}small,.hint{color:var(--muted)}button,input{font:inherit;border-radius:10px;border:1px solid #475569}input{padding:.75rem .85rem;background:#0b1220;color:var(--text);min-width:min(100%,28rem)}button{padding:.7rem .9rem;margin:.18rem;background:#2563eb;color:white;border-color:#3b82f6;cursor:pointer}button.secondary{background:#334155;border-color:#475569}button.danger{background:#9f1239;border-color:#be123c}.actions{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem;margin:.75rem 0}.urls a{color:#93c5fd;word-break:break-all}.pill{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:.2rem .55rem;color:var(--muted);background:#0b1220}.term{background:#050608;border:1px solid #243244;border-radius:14px;padding:.35rem;min-height:24rem;overflow:hidden}.xterm{padding:.35rem}.kbd{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.toast{position:fixed;right:1rem;bottom:1rem;background:#172554;border:1px solid #3b82f6;padding:.75rem 1rem;border-radius:12px;color:white}.folded .actions,.folded .hint,.folded .term{display:none}.session-head{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;justify-content:space-between}.repo-row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.35rem 0}.repo-row code{background:#0b1220;border:1px solid var(--line);border-radius:8px;padding:.35rem .5rem}</style><main><h1>Agent Auth Companion</h1><p class=subtitle>Authenticate CLIs from a stable, bidirectional terminal. Inputs are preserved while status refreshes.</p><section><h2>Status</h2><div id=status class=grid></div></section><section><h2>Repositories</h2><div class=card><div class=actions><input id=repoUrl placeholder="https://github.com/Xide/infra or owner/repo" size=48><input id=repoDest placeholder="optional subdir" size=20><button onclick="cloneProject()">Clone with gh</button></div><div id=projects></div></div></section><section><h2>Login</h2><div id=login></div></section><section><h2>Sessions</h2><div id=sessions></div></section></main><div id=toast class=toast hidden></div><script>
const app={sessions:new Map(),terms:new Map(),lastLogs:new Map()};
async function api(p,o={}){let r=await fetch(p,{headers:{'content-type':'application/json'},...o});let j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.error||r.statusText);return j}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(msg){let t=document.getElementById('toast');t.textContent=msg;t.hidden=false;clearTimeout(t._h);t._h=setTimeout(()=>t.hidden=true,3500)}
function renderProjects(st){let ps=st.repo?.projects||[];projects.innerHTML=ps.length?ps.map(p=>`<div class=repo-row><code>${esc(p.name)}</code><small>${p.git?'git repo':'directory'}</small><button class=danger onclick="deleteProject('${esc(p.name)}')">Delete</button></div>`).join(''):'<small>No project subdirectories yet.</small>'}
function loginButtons(){return [['codex','device','Codex device-code'],['codex','browser','Codex browser replay'],['codex','api_key','Codex API key'],['claude','account','Claude terminal'],['opencode','openai_chatgpt','OpenCode OpenAI ChatGPT'],['opencode','connect','OpenCode /connect'],['opencode','interactive','OpenCode interactive'],['github','device','GitHub device login']].map(x=>`<button onclick="start('${x[0]}','${x[1]}')">${x[2]}</button>`).join('')}
async function refreshStatus(){let st=await api('/api/status');renderProjects(st);status.innerHTML=Object.entries(st).map(([k,v])=>`<div class="card status"><b>${esc(k)}</b><br><span class=${v.ok?'ok':'bad'}>${v.ok?'OK':'not ready'}</span><br><small>${esc(v.detail||'')}</small></div>`).join('')}
function needsReplay(s){return s.method==='browser'||s.state==='waiting_callback'}
function sessionHtml(s){let replay=needsReplay(s), ph=s.method==='api_key'?'paste OpenAI API key, then Send stdin':(replay?'paste full callback URL after browser redirects':'type naturally in terminal, or paste code/answer here');return `<div class=card id="sess-${s.id}"><div class=session-head><div class=session-title><b>${esc(s.harness)}/${esc(s.method)}</b> <span class=pill>${esc(s.id)} · ${esc(s.state)}</span></div><button class=secondary onclick="toggleFold('${s.id}')">Fold</button></div><div class=urls>${(s.urls||[]).map(u=>`<a target=_blank rel=noopener href="${esc(u)}">${esc(u)}</a><br>`).join('')}</div>${s.device_code?`<p>Device code: <b class=kbd>${esc(s.device_code)}</b></p>`:''}<div class=actions><input id="in${s.id}" placeholder="${ph}" size=54><button onclick="${replay?'replay':'stdin'}('${s.id}')">${replay?'Replay callback':'Send stdin'}</button><button class=secondary onclick="sendRaw('${s.id}','\r')">Enter</button><button class=secondary onclick="sendRaw('${s.id}','yes\n')">Yes</button><button class=secondary onclick="sendRaw('${s.id}','1\r')">1</button><button class=secondary onclick="sendRaw('${s.id}','\u0003')">Ctrl-C</button><button class=danger onclick="cancel('${s.id}')">Cancel</button></div><div class=hint>Tip: click the terminal and type directly. Use Yes for GitHub prompts, 1/Enter for Claude theme screens, or paste a Codex callback URL above.</div><div class=term data-term="${esc(s.id)}"></div></div>`}
async function refreshSessions(){let ss=await api('/api/sessions'), live=new Set(ss.map(s=>s.id)); for(let s of ss){app.sessions.set(s.id,s); if(!document.getElementById('sess-'+s.id)){sessions.insertAdjacentHTML('beforeend',sessionHtml(s)); openTerm(s)} updateSession(s)} for(let id of [...app.sessions.keys()]) if(!live.has(id)){document.getElementById('sess-'+id)?.remove(); app.sessions.delete(id); app.terms.delete(id); app.lastLogs.delete(id)}}
function openTerm(s){let el=document.querySelector(`[data-term="${s.id}"]`); if(!el)return; if(window.Terminal){let t=new Terminal({convertEol:true,cols:120,rows:24,cursorBlink:true,theme:{background:'#050608',foreground:'#e5e7eb',cursor:'#60a5fa',selectionBackground:'#334155'}}); t.open(el); let buf='',timer=0; t.onData(d=>{buf+=d; if(!timer) timer=setTimeout(()=>{let x=buf; buf=''; timer=0; sendRaw(s.id,x,false)},20)}); app.terms.set(s.id,t)}else{let pre=document.createElement('pre');el.replaceWith(pre);app.terms.set(s.id,{write:x=>pre.textContent+=x,reset:()=>pre.textContent=''})}}
function updateSession(s){let card=document.getElementById('sess-'+s.id); if(card){card.querySelector('.pill').textContent=`${s.id} · ${s.state}`; if(s.state==='exited'&&!card.dataset.foldTimer){card.dataset.foldTimer='1';setTimeout(()=>card.classList.add('folded'),2000)} card.querySelector('.urls').innerHTML=(s.urls||[]).map(u=>`<a target=_blank rel=noopener href="${esc(u)}">${esc(u)}</a><br>`).join('')} let log=s.log||'', prev=app.lastLogs.get(s.id)||'', term=app.terms.get(s.id); if(term&&log!==prev){ if(!log.startsWith(prev)){term.reset?.(); term.write(log)} else term.write(log.slice(prev.length)); app.lastLogs.set(s.id,log)}}
function toggleFold(id){document.getElementById('sess-'+id)?.classList.toggle('folded')}
async function cloneProject(){let repo=repoUrl.value.trim(), dest=repoDest.value.trim(); try{await api('/api/projects/clone',{method:'POST',body:JSON.stringify({repo,dest})}); repoUrl.value=''; repoDest.value=''; toast('Repository cloned'); await refreshStatus()}catch(e){toast(e.message)}}
async function deleteProject(name){if(!confirm(`Delete project/${name}?`))return; try{await api('/api/projects/'+encodeURIComponent(name),{method:'DELETE'}); toast('Project deleted'); await refreshStatus()}catch(e){toast(e.message)}}
async function start(h,m){await api('/api/harness/'+h+'/login/'+m,{method:'POST'});await refreshSessions()}
async function stdin(id){let el=document.getElementById('in'+id), v=el.value; await sendRaw(id,v+'\n'); el.value=''}
async function sendRaw(id,text,notify=true){try{await api('/api/sessions/'+id+'/stdin',{method:'POST',body:JSON.stringify({text})}); if(notify) setTimeout(refreshSessions,150)}catch(e){toast(e.message)}}
async function replay(id){let el=document.getElementById('in'+id); try{await api('/api/sessions/'+id+'/replay-url',{method:'POST',body:JSON.stringify({url:el.value})}); el.value=''; toast('Callback replayed'); setTimeout(refreshSessions,300)}catch(e){toast(e.message)}}
async function cancel(id){await api('/api/sessions/'+id+'/cancel',{method:'POST'}); await refreshSessions()}
login.innerHTML=loginButtons(); async function tickSessions(){try{await refreshSessions()}catch(e){toast(e.message)}} async function tickStatus(){try{await refreshStatus()}catch(e){toast(e.message)}} tickStatus(); tickSessions(); setInterval(tickSessions,750); setInterval(tickStatus,10000);
</script>'''
class H(BaseHTTPRequestHandler):
    def sendj(self,o,code=200):
        b=json.dumps(o).encode(); self.send_response(code); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def body(self): return json.loads(self.rfile.read(int(self.headers.get('content-length','0') or 0)) or b'{}')
    def do_GET(self):
        if self.path=='/healthz': self.send_response(204); self.end_headers(); return
        if self.path=='/api/status': self.sendj(statuses()); return
        if self.path=='/api/projects': self.sendj(project_subdirs()); return
        if self.path=='/api/sessions':
            with LOCK: self.sendj([{k:v for k,v in s.items() if k not in ('fd',)} for s in SESS.values()]); return
        b=PAGE.encode(); self.send_response(200); self.send_header('content-type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(b)
    def do_DELETE(self):
        parts=self.path.strip('/').split('/')
        try:
            if parts[:2]==['api','projects'] and len(parts)==3:
                self.sendj(delete_project(unquote(parts[2]))); return
            self.sendj({'error':'not found'},404)
        except Exception as e: self.sendj({'error':str(e)},400)
    def do_POST(self):
        parts=self.path.strip('/').split('/')
        try:
            if parts[:2]==['api','projects'] and parts[2]=='clone':
                d=self.body(); self.sendj(clone_repo(d.get('repo',''), d.get('dest') or None)); return
            if parts[:2]==['api','harness'] and parts[3]=='login':
                s=start_session(parts[2],parts[4]); self.sendj({k:v for k,v in s.items() if k != 'fd'}); return
            if parts[:2]==['api','browser-opened']:
                d=self.body()
                with LOCK:
                    s=SESS.get(parts[2])
                    if not s: raise ValueError('session not found')
                    remember_url(s, d.get('url',''))
                    s['state']='browser_opened'
                self.sendj({'ok':True}); return
            if parts[:2]==['api','sessions'] and parts[3]=='stdin':
                d=self.body(); s=SESS[parts[2]]; os.write(s['fd'], d.get('text','').encode()); self.sendj({'ok':True}); return
            if parts[:2]==['api','sessions'] and parts[3]=='cancel':
                s=SESS[parts[2]]
                try:
                    os.kill(s['pid'], signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    os.close(s['fd'])
                except OSError:
                    pass
                with LOCK:
                    SESS.pop(parts[2], None)
                self.sendj({'ok':True}); return
            if parts[:2]==['api','sessions'] and parts[3]=='replay-url':
                d=self.body(); s=SESS[parts[2]]; u=urlparse(d.get('url',''))
                if u.hostname not in ('localhost','127.0.0.1','::1'): raise ValueError('only loopback callback URLs are accepted')
                port=int(u.port or 0)
                if not port: raise ValueError('callback URL is missing a loopback port')
                if s.get('state')=='waiting_callback':
                    if port!=s.get('expected_port') or u.path!=s.get('expected_path'):
                        raise ValueError('unexpected callback target')
                elif s.get('method')!='browser':
                    raise ValueError('session is not waiting for a callback')
                q=u.query
                if 'code=' not in q or 'state=' not in q: raise ValueError('missing oauth code/state')
                target=f'http://127.0.0.1:{port}{u.path}?{q}'
                r=urlopen(Request(target,method='GET'), timeout=5); s['state']='callback_replayed'; self.sendj({'ok':True,'status':r.status}); return
            self.sendj({'error':'not found'},404)
        except Exception as e: self.sendj({'error':str(e)},400)

if __name__=='__main__':
    ThreadingHTTPServer((HOST,PORT),H).serve_forever()
