"""Local-network Cameo 2 controller. All motion requires an explicit browser request."""
import io, math, os, secrets, threading, time
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from defusedxml import ElementTree
from svgelements import SVG, Path as SVGPath, Shape
import usb.core, usb.util

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
STATE = dict(running=False, message='No job running', progress=0)
CANCEL = threading.Event()
DESIGNS = {}
MM_PER_PX = 25.4 / 96

@app.before_request
def guard():
    if request.host.split(':')[0] not in os.environ.get('CAMEO_HOSTS', '127.0.0.1,localhost').split(','):
        return jsonify(error='Use the controller’s local IP address.'), 403
    # Require the unguessable page token for every state-changing operation.
    if request.method == 'POST' and request.headers.get('X-Cameo-Token') != TOKEN:
        return jsonify(error='Reload this page before continuing.'), 403

@app.errorhandler(Exception)
def error(exc):
    from werkzeug.exceptions import HTTPException
    return jsonify(error=str(exc)), exc.code if isinstance(exc, HTTPException) else 400

@app.get('/')
def index():
    return render_template('index.html', token=TOKEN)

def update(**values):
    with STATE_LOCK: STATE.update(values)

def device():
    d = usb.core.find(idVendor=0x0b4d, idProduct=0x112b)
    if d is None: raise ValueError('Cameo 2 is not connected to this Mint computer.')
    if d.is_kernel_driver_active(0):
        d.detach_kernel_driver(0)
    usb.util.claim_interface(d, 0)
    return d

def status(d):
    d.write(1, b'\x1b\x05', timeout=3000)
    raw = bytes(d.read(0x82, 64, timeout=5000)).rstrip(b'\x03')
    if raw not in (b'0', b'1', b'2'): raise ValueError('Unexpected machine response: ' + repr(raw))
    return {b'0':'Ready', b'1':'Moving', b'2':'Unloaded'}[raw]

def wait_ready(d):
    time.sleep(.15)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        s = status(d)
        if s == 'Ready': return
        if s != 'Moving': raise ValueError('Machine reports ' + s)
        time.sleep(.2)
    raise ValueError('Motion timeout. Check the machine before another job.')

def send(d, commands):
    data = ('\x03'.join(commands) + '\x03').encode('ascii')
    if len(data) > 900: raise ValueError('Command packet too large')
    n = d.write(1, data, timeout=5000)
    if n != len(data): raise ValueError('Incomplete USB write')

def number(data, name, default, lo, hi):
    v = float(data.get(name, default))
    if not math.isfinite(v) or not lo <= v <= hi: raise ValueError(f'{name} must be between {lo} and {hi}.')
    return v

@app.get('/api/status')
def get_status():
    with STATE_LOCK: result = dict(STATE)
    if not LOCK.acquire(False): return jsonify(**result, machine='Job in progress')
    d = None
    try:
        d = device()
        result['machine'] = status(d)
    except Exception as exc:
        result['machine'] = 'Unavailable'
        result['detail'] = str(exc)
    finally:
        if d is not None: usb.util.dispose_resources(d)
        LOCK.release()
    return jsonify(result)

@app.post('/api/upload')
def upload():
    f = request.files.get('file')
    if not f: raise ValueError('Choose an SVG file.')
    data = f.read()
    root = ElementTree.fromstring(data)
    for e in root.iter():
        tag = e.tag.split('}')[-1]
        if tag in ('text', 'image', 'use', 'script', 'foreignObject', 'filter', 'clipPath', 'mask', 'pattern'):
            raise ValueError(f'SVG contains {tag}. Convert text and clones to paths, remove bitmap images and effects, then save again.')
        if any(k.split('}')[-1] == 'href' for k in e.attrib):
            raise ValueError('Linked resources are unsupported. Save a self-contained SVG of paths.')
    svg = SVG.parse(io.BytesIO(data), ppi=96)
    paths = []
    total = 0
    for element in svg.elements():
        if not isinstance(element, Shape): continue
        if element.values.get('visibility') == 'hidden' or element.values.get('display') == 'none': continue
        path = SVGPath(element)
        path.reify()
        for subpath in path.as_subpaths():
            sub = SVGPath(subpath)
            length = sub.length(error=1e-3) * MM_PER_PX
            if not math.isfinite(length): raise ValueError('Invalid SVG geometry')
            if length < .01: continue
            n = max(2, math.ceil(length / .3))
            total += n + 1
            if total > 100000: raise ValueError('Design is too complex. Simplify the paths in Inkscape.')
            points = []
            for i in range(n + 1):
                p = sub.point(i / n)
                x, y = float(p.x) * MM_PER_PX, float(p.y) * MM_PER_PX
                if not math.isfinite(x+y): raise ValueError('Invalid SVG coordinate')
                points.append([x,y])
            paths.append(points)
    if not paths: raise ValueError('No drawable paths found.')
    xs = [p[0] for path in paths for p in path]
    ys = [p[1] for path in paths for p in path]
    xmin, ymin, width, height = min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)
    if max(width,height) < .01: raise ValueError('Design has no usable size')
    paths = [[[x-xmin,y-ymin] for x,y in path] for path in paths]
    ident = secrets.token_urlsafe(18)
    if len(DESIGNS) >= 8: DESIGNS.pop(next(iter(DESIGNS)))
    DESIGNS[ident] = dict(paths=paths, width=width, height=height)
    return jsonify(id=ident, width=width, height=height, paths=paths, count=len(paths))

def simplify(points, tolerance=1.5):
    """Ramer–Douglas–Peucker, in 0.05 mm device units (0.075 mm tolerance)."""
    clean=[]
    for point in points:
        if not clean or point != clean[-1]: clean.append(point)
    if len(clean)<3: return clean
    keep={0,len(clean)-1}; stack=[(0,len(clean)-1)]
    while stack:
        first,last=stack.pop()
        ax,ay=clean[first];bx,by=clean[last]
        dx,dy=bx-ax,by-ay;den=dx*dx+dy*dy
        furthest=-1;distance=-1
        for i in range(first+1,last):
            x,y=clean[i]
            t=max(0,min(1,((x-ax)*dx+(y-ay)*dy)/den)) if den else 0
            d=(x-ax-t*dx)**2+(y-ay-t*dy)**2
            if d>distance:distance=d;furthest=i
        if distance>tolerance*tolerance:
            keep.add(furthest);stack.extend([(first,furthest),(furthest,last)])
    return [clean[i] for i in sorted(keep)]

def placed(data):
    design = DESIGNS.get(data.get('id'))
    if not design: raise ValueError('Upload the SVG again.')
    scale = number(data, 'scale', 1, .001, 1000)
    left = number(data, 'left', 10, 0, 304)
    top = number(data, 'top', 10, 0, 304)
    paths = [[[round((x*scale+left)*20),round((y*scale+top)*20)] for x,y in path] for path in design['paths']]
    if any(not (0 <= x <= 6080 and 0 <= y <= 6080) for path in paths for x,y in path):
        raise ValueError('Design exceeds the 304 × 304 mm working area.')
    return [simplify(path) for path in paths]

def launch(work):
    if not LOCK.acquire(False): raise ValueError('A machine operation is already running.')
    CANCEL.clear()
    update(running=True, progress=0, message='Connecting…')
    def run():
        d = None
        try:
            d = device()
            if status(d) != 'Ready': raise ValueError('Load the material and wait for Ready.')
            work(d)
        except Exception as exc: update(message='Stopped: '+str(exc))
        finally:
            if d is not None: usb.util.dispose_resources(d)
            update(running=False)
            LOCK.release()
    threading.Thread(target=run, daemon=True).start()
    return jsonify(accepted=True)

@app.post('/api/travel')
def travel():
    data=request.get_json()
    if data.get('clear') is not True: raise ValueError('Confirm the machine is clear.')
    x=number(data,'x',0,0,304)
    speed=int(number(data,'speed',3,1,10))
    def work(d):
        update(message='Moving carriage…')
        send(d,['Z6080,6080',f'!{speed}',f'M0,{round(x*20)}'])
        wait_ready(d)
        update(message=f'Carriage at {x:g} mm; Ready',progress=100)
    return launch(work)

@app.post('/api/start')
def start():
    data=request.get_json()
    if data.get('ready') is not True: raise ValueError('Confirm tool, material, and placement are ready.')
    paths=placed(data)
    speed=int(number(data,'speed',3,1,10))
    pressure=int(number(data,'pressure',1,1,33))
    passes=int(number(data,'passes',1,1,5))
    mode=data.get('mode')
    if mode not in ('travel','tool-free','pen','cut'): raise ValueError('Choose a job mode.')
    if mode=='tool-free' and data.get('tool_removed') is not True:
        raise ValueError('Remove the blade or pen and confirm the tool holder is empty.')
    def work(d):
        update(message='Running '+mode+' job…')
        # Travel mode never initializes or sends cutter configuration or draw commands.
        if mode in ('travel','tool-free'):
            send(d,['Z6080,6080',f'!{speed}'])
        else:
            d.write(1,b'\x1b\x04',timeout=3000)
            send(d,[f'!{speed}',f'FX{pressure}','FC0' if mode=='pen' else 'FC18','FY0','FN0','TB50,0','\\0,0','Z6080,6080','L0','FE0,0','FF0,0,0'])
        total=sum(len(p) for p in paths)*passes
        done=0
        last=None
        for _ in range(passes):
            for path in paths:
                cmds=[]
                for i,(x,y) in enumerate(path):
                    prefix='M' if i==0 or mode=='travel' else 'D'
                    cmds.append(f'{prefix}{y},{x}')
                batch=[]
                for cmd in cmds:
                    if sum(len(c)+1 for c in batch)+len(cmd)+1>880:
                        if CANCEL.is_set(): break
                        send(d,batch);wait_ready(d)
                        last=batch[-1][1:]
                        done+=len(batch);update(progress=round(100*done/total))
                        batch=[]
                    batch.append(cmd)
                if CANCEL.is_set(): break
                if batch:
                    send(d,batch);wait_ready(d)
                    last=batch[-1][1:]
                    done+=len(batch);update(progress=round(100*done/total))
            if CANCEL.is_set(): break
        # Raise the empty/tool holder at the last transmitted coordinate.
        if mode!='travel' and last:
            send(d,['M'+last]);wait_ready(d)
        if not CANCEL.is_set():
            update(message='Returning to zero…')
            send(d,['M0,0']);wait_ready(d)
        update(message='Cancelled remaining paths; carriage left in place.' if CANCEL.is_set() else 'Job complete; returned to zero; Ready',progress=STATE['progress'] if CANCEL.is_set() else 100)
    return launch(work)

@app.post('/api/cancel')
def cancel():
    CANCEL.set()
    update(message='Cancelling after the current buffered movement finishes…')
    return jsonify(accepted=True)

if __name__=='__main__':
    from waitress import serve
    serve(app, host=os.environ.get('CAMEO_BIND', '127.0.0.1'), port=8091, threads=4)
