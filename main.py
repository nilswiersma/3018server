# In desperate need of some thread safety
# In desperate need of a lot of input validation

import re
import time 
import json

from pprint import pformat

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, send, emit
from werkzeug.datastructures import ImmutableMultiDict
from markupsafe import escape
from serial import Serial
from serial.tools import list_ports

from threading import Lock

GRBL_STATUS = '?'
GRBL_STOP = '!'
GRBL_RESUME = '~'
GRBL_HOME = '$H'

GCODE_ABS = 'G90'
GCODE_REL = 'G91'
GCODE_MOVE = 'G0'

def find_3018():
    for port in list_ports.comports():
        if port.vid == 0x1a86 and port.pid == 0x7523:
            return port.device
    raise Exception('Cannot find any device with vid = 0x1a86 and pid = 0x7523')

class XYZPosition():
    def __init__(self, x, y, z=0):
        self.x = x
        self.y = y
        self.z = z

    def __str__(self):
        try:
            x = f'{self.x:.3f}'
        except TypeError:
            x = str(self.x)

        try:
            y = f'{self.y:.3f}'
        except TypeError:
            y = str(self.y)

        try:
            z = f'{self.z:.3f}'
        except TypeError:
            z = str(self.z)

        return f'X={x},Y={y},Z={z}'
    
    def __repr__(self):
        return f'<XYZPosition at 0x{id(self):x} [{str(self)}]>'

class Prover():
    STATUS_REGEX = r'<(?P<state>[a-zA-Z]+)\|MPos:(?P<X>-?[0-9]+\.[0-9]{3}),(?P<Y>-?[0-9]+\.[0-9]{3}),(?P<Z>-?[0-9]+\.[0-9]{3})\|(.*?)>'
    
    def __init__(self):
        self.ser = Serial(find_3018(), timeout=60, baudrate=115200)
        self.move_lock = Lock()
        self.serial_lock = Lock()
        self.disk_lock = Lock()

        self.state = None
        self.mpos = None
        self.ref = {'a': None, 'b': None}
        self.hop_z = None

        try:
            self.from_disk()
        except FileNotFoundError:
            pass

        self.idle_timeout = .1
    
    def to_dict(self):
        ret = {}
        ret['hop_z'] = self.hop_z
        a = self.ref.get('a', None)
        b = self.ref.get('b', None)
        ret['ref'] = {'a': a, 'b': b}
        if a:
            ret['ref']['a'] = {
                'x' : a.x,
                'y' : a.y,
                'z' : a.z,
            }
        if b:
            ret['ref']['b'] = {
                'x' : b.x,
                'y' : b.y,
                'z' : b.z,
            }
        return ret

    def from_dict(self, data):
        self.hop_z = data.get('hop_z')
        self.ref['a'] = XYZPosition(**data.get('ref').get('a'))
        self.ref['b'] = XYZPosition(**data.get('ref').get('b'))
    
    def to_disk(self):
        with self.disk_lock:
            with open('static/config.json', 'w') as f:
                json.dump(self.to_dict(), f, indent=4)

    def from_disk(self):
        with self.disk_lock:
            with open('static/config.json', 'r') as f:
                config = json.load(f)
                self.from_dict(config)
    
    def fracpos(self):
        if self.mpos and self.ref['a'] and self.ref['b']:
            return {'x': abs(self.mpos.x - self.ref['a'].x) / abs(self.ref['a'].x - self.ref['b'].x),
                    'y': abs(self.mpos.y - self.ref['b'].y) / abs(self.ref['a'].y - self.ref['b'].y) }

    def rw(self, data):
        if data[:-2] != b'\r\n' and len(data) > 1:
            data += b'\r\n'

        with self.serial_lock: # nice chance for a deadlock!
            self.ser.write(data)
            ret = self.ser.readline()
            while self.ser.in_waiting != 0:
                ret += self.ser.readline()
            
        return ret
    
    def sync(self):
        ret = self.rw(GRBL_STATUS.encode())#, until=b'\r\n')

        m = re.search(Prover.STATUS_REGEX, ret.decode())

        if m:
            status = m.groupdict()
            # app.logger.debug(f'{status=}')
            self.state = status['state']
            self.mpos = XYZPosition(float(status['X']), float(status['Y']), float(status['Z']))
        else:
            app.logger.debug(f'{ret.decode()=}')
            app.logger.debug(f'{m=}')

        return ret
    
    def wait_idle(self):
        while self.state != 'Idle':
            self.sync()
            time.sleep(self.idle_timeout)

    def home(self):
        ret = self.rw(GRBL_HOME.encode())
        # assert ret == b'ok\r\n', f'{ret=}' # TODO check return value
        return ret

    def move(self, x=None, y=None, z=None):
        if not (x or y or z):
            return b''  
        
        cmd = GCODE_MOVE
        if x:
            cmd += f'X{x:.3f}'
        if y:
            cmd += f'Y{y:.3f}'
        if z:
            cmd += f'Z{z:.3f}'

        ret = self.rw(cmd.encode())
        # assert ret == b'ok\r\n', f'{ret=}' # TODO check return value
        return ret

    def move_abs(self, x=None, y=None, z=None):
        self.rw(GCODE_ABS.encode()) # set absolute movement

        if not (x or y or z):
            return b''
        
        return self.move(x, y, z)

    def move_rel(self, x=None, y=None, z=None):
        self.rw(GCODE_REL.encode()) # set relative movement

        if not (x or y or z):
            return b''
        
        return self.move(x, y, z)

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    prover.sync()
    return render_template('index.html', prover=prover.__dict__)


@app.route('/raw_cmd', methods=['GET', 'POST'])
def raw_cmd():
    if request.method == 'GET':
        app.logger.debug(request.args)
        data = request.args
    else:
        app.logger.debug(request.get_json())
        data = ImmutableMultiDict(request.get_json())
    cmd = data.get('cmd')

    ret = prover.rw(cmd.encode())

    if request.method == 'GET':
        return redirect('/')
    else:
        return jsonify(ret.decode())

@app.route('/sync', methods=['GET', 'POST'])
def sync():
    ret = prover.sync()

    if request.method == 'GET':
        return redirect('/')
    else:
        return jsonify(ret.decode())

@app.route('/home', methods=['GET', 'POST'])
def home():
    with prover.move_lock:
        ret = prover.home()
        prover.wait_idle()

    if request.method == 'GET':
        return redirect('/')
    else:
        return jsonify(ret.decode())

@app.route('/move', methods=['GET', 'POST'])
def move():
    if request.method == 'GET':
        app.logger.debug(request.args)
        data = request.args
    else:
        app.logger.debug(request.get_json())
        data = ImmutableMultiDict(request.get_json())

    x = data.get('x', type=float)
    y = data.get('y', type=float)
    z = data.get('z', default=None, type=float)
    rel = data.get('rel', default=False, type=bool)

    # If we don't wait, commands get queued and can be performed in parallel
    nowait = data.get('nowait', default=False, type=bool)

    with prover.move_lock:
        # Sync position
        prover.sync()
        cur_pos = XYZPosition(**prover.mpos.__dict__)
        restore_hop_z = None
        ret = b''

        # Don't move if already at target position
        if not rel and (not x or cur_pos.x == x) and (not y or cur_pos.y == y) and (not z or cur_pos.z == z):
            app.logger.debug(f'skip move {cur_pos=}, {x=} {y=} {z=}')
        else:
            # Check that hop level is higher than current level, otherwise don't hop
            if prover.hop_z and prover.hop_z > cur_pos.z:
                restore_hop_z = cur_pos.z
                ret += prover.move_abs(z=prover.hop_z)
                if not nowait: prover.wait_idle()
            else:
                app.logger.debug(f'skip hop {prover.hop_z=} <= {cur_pos.z=}')
                
            # Move z separately from x and y
            if not rel:
                # Do z first if it's bigger than current z
                # Don't care about pre-hop z in this case anymore
                if z and z > cur_pos.z:
                    app.logger.debug(f'z first {z=} > {cur_pos.z=}')
                    ret += prover.move_abs(z=z)
                    if not nowait: prover.wait_idle()
                    z = None
                    restore_hop_z = None

                ret += prover.move_abs(x=x, y=y)
                if not nowait: prover.wait_idle()

                # Restore pre-hop z if there is no new z provided
                if not z and restore_hop_z:
                    ret += prover.move_abs(z=restore_hop_z)
                    if not nowait: prover.wait_idle()
                else:
                    ret += prover.move_abs(z=z)
                    if not nowait: prover.wait_idle()

            else:
                ret += prover.move_rel(x=x, y=y)
                if not nowait: prover.wait_idle()
                if restore_hop_z:
                    ret += prover.move_abs(z=restore_hop_z)
                    if not nowait: prover.wait_idle()
                ret += prover.move_rel(z=z)
                if not nowait: prover.wait_idle()
            
            # Sync internal position
            prover.sync()
            if not nowait: prover.wait_idle()
    
    if request.method == 'GET':
        return redirect('/')
    else:
        return jsonify(ret.decode())

@app.route('/set_hop', methods=['GET', 'POST'])
def set_hop():
    # app.logger.debug(request.args)
    # z = data.get('z', default=None, type=float)
    prover.hop_z = prover.mpos.z
    
    if request.method == 'GET':
        return redirect('/')
    else:
        return jsonify({})
    
@app.route('/set_ref', methods=['GET', 'POST'])
def set_ref():
    if request.method == 'GET':
        app.logger.debug(request.args)
        data = request.args
    else:
        app.logger.debug(request.get_json())
        data = ImmutableMultiDict(request.get_json())

    set_a = data.get('set_a', default=None, type=bool)
    set_b = data.get('set_b', default=None, type=bool)

    # Sync internal position
    prover.sync()

    if set_a:
        prover.ref['a'] = XYZPosition(**prover.mpos.__dict__)
    elif set_b:
        prover.ref['b'] = XYZPosition(**prover.mpos.__dict__)
    # else:
    #     a_x = data.get('a_x', type=float)
    #     a_y = data.get('a_y', type=float)
    #     a_z = data.get('a_z', type=float)
    #     b_x = data.get('b_x', type=float)
    #     b_y = data.get('b_y', type=float)
    #     b_z = data.get('b_z', type=float)

    #     prover.ref['a'] = XYZPosition(a_x, a_y, a_z)
    #     prover.ref['b'] = XYZPosition(b_x, b_y, b_z)

    if request.method == 'GET':
        return redirect('/')
    else:
        return jsonify({})
    
@app.route('/go_ref', methods=['GET', 'POST'])
def go_ref():
    if request.method == 'GET':
        app.logger.debug(request.args)
        data = request.args
    else:
        app.logger.debug(request.get_json())
        data = ImmutableMultiDict(request.get_json())

    go_a = data.get('a', default=False, type=bool)
    go_b = data.get('b', default=False, type=bool)

    app.logger.debug(f'{go_a=}')
    app.logger.debug(f'{go_b=}')

    if go_a:
        return redirect(url_for('move', **prover.ref['a'].__dict__))
    elif go_b:
        return redirect(url_for('move', **prover.ref['b'].__dict__))

@app.route('/config', methods=['GET', 'POST'])
def config():
    if request.method == 'GET':
        return jsonify(prover.to_dict())
    elif request.method == 'POST':
        data = request.get_json()
        app.logger.debug(data)
        prover.from_dict(data)
        prover.to_disk()
        return {}

# @app.route('/current_pos', methods=['GET'])
# def current_pos():
#     if request.method == 'GET':
#         prover.sync()
#         return jsonify({
#             'fracpos': prover.fracpos(),
#             'mpos': prover.mpos.__dict__,
#         })

@app.route('/test')
def test():
    app.logger.debug(request.args)
    boolean = request.args.get('boolean', default=None, type=bool)
    integer = request.args.get('integer', default=None, type=int)
    app.logger.debug(f'{boolean=}')
    app.logger.debug(f'{integer=}')
    return 'bye'
# @app.route('/move_abs')
# def move_abs():
#     x = request.args.get('x', type=float)
#     y = request.args.get('y', type=float)
#     z = request.args.get('z', default=None, type=float)
#     ret = prover.move_abs(x, y, z)
#     prover.wait_idle()
#     return f'{escape(ret)}'

# @app.route('/move_rel')
# def move_rel():
#     x = request.args.get('x', type=float)
#     y = request.args.get('y', type=float)
#     z = request.args.get('z', default=None, type=float)
#     ret = prover.move_rel(x, y, z)
#     prover.wait_idle()
#     return f'{escape(ret)}'

@socketio.on('disconnect')
def test_disconnect():
    pass
    # print('Client disconnected')

@socketio.event
def pos_req():
    prover.sync()
    emit('pos_resp', {
            'fracpos': prover.fracpos(),
            'mpos': prover.mpos.__dict__,
            'config': prover.to_dict(),
        }, json=True)

if __name__ == '__main__':
    prover = Prover()
    socketio.run(app, debug=True, use_reloader=False)