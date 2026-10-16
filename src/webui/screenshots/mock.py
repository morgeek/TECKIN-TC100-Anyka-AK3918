import http.server, threading, json, os, sys, urllib.parse
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','..','www')
HERE=os.path.dirname(os.path.abspath(__file__))
MOCKDIR=os.path.join(HERE,'mock')
unknown=set()
def J(o): return ('application/json', json.dumps(o).encode())
def T(s,ct='text/plain'): return (ct, s.encode())
STATUS={"sysusage":"CPU: 14% RAM: 21844/33280 kB","cpu":14,"ram_used_kb":21844,"ram_total_kb":33280,"ram_percent":65,"sd_used_kb":0,"sd_total_kb":0,"sd_percent":0,"perfprofile":"balanced","lum":"812","awb":"5200","ui_ultralite_mode":0,"web_mode":"full","security_hardening_mode":1,"mqtt_enabled":1,"mqtt_last_pub_ts":0,"mqtt_last_pub_ok":1,"default_password_active":0,"csrf_token":"aabbccdd","update_available":0,"update_latest_version":"n/a","current_version":"2.0.0","wifi_qual":78,"wifi_iface":"wlan0","frigate_live":"","storage":"flash"}
def route(path, q, method):
    cmd=q.get('cmd',[''])[0]
    name=path.rsplit('/',1)[-1]
    f=os.path.join(MOCKDIR,name+'.'+(cmd or 'none'))
    for ext in ('.json','.html','.txt'):
        if os.path.exists(f+ext):
            return ({'.json':'application/json','.html':'text/html','.txt':'text/plain'}[ext], open(f+ext,'rb').read())
    if name=='currentpic.cgi': return ('image/jpeg', open(os.path.join(HERE,'pattern.jpg'),'rb').read())
    if name=='state.cgi' and cmd=='statusline': return J(STATUS)
    if name=='state.cgi' and cmd=='hostname': return T('camera')
    if name=='state.cgi' and cmd=='sysusage': return T(STATUS['sysusage'])
    if name=='state.cgi' and cmd=='perfprofile': return T('balanced')
    if name=='wizard.cgi': return J({"first_boot":False})
    if name=='camcontrols.cgi' and cmd=='panel': return J({"ok":True,"mode":"auto","ir-led":0,"ir-cut":1,"black-white":0,"front-led":1,"red-led":0})
    if name=='action.cgi' and cmd=='get_ptt_vol': return T('80')
    unknown.add(method+' '+path+'?'+urllib.parse.urlencode(q,doseq=True))
    return J({"ok":True})
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s,*a,**k): super().__init__(*a,directory=ROOT,**k)
    def log_message(s,*a): pass
    def handle_cgi(s,method):
        u=urllib.parse.urlparse(s.path); q=urllib.parse.parse_qs(u.query, keep_blank_values=True)
        if method=='POST':
            n=int(s.headers.get('Content-Length') or 0); s.rfile.read(n)
        ct,body=route(u.path,q,method)
        s.send_response(200); s.send_header('Content-Type',ct); s.send_header('Content-Length',str(len(body))); s.end_headers(); s.wfile.write(body)
    def do_GET(s):
        if '/cgi-bin/' in s.path: return s.handle_cgi('GET')
        return super().do_GET()
    def do_POST(s): return s.handle_cgi('POST')
def start(port):
    srv=http.server.ThreadingHTTPServer(('127.0.0.1',port),H); threading.Thread(target=srv.serve_forever,daemon=True).start(); return srv
