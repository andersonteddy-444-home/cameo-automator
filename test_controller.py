import io, unittest
from unittest.mock import patch
import app

class ControllerTests(unittest.TestCase):
    def setUp(self): self.c=app.app.test_client()
    def post(self,url,data): return self.c.post(url,json=data,headers={'X-Cameo-Token':app.TOKEN})
    def upload(self,svg):
        return self.c.post('/api/upload',data={'file':(io.BytesIO(svg.encode()),'test.svg')},headers={'X-Cameo-Token':app.TOKEN})
    def test_units_and_transform(self):
        r=self.upload('<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="120mm" viewBox="0 0 120 120"><g transform="translate(5 5)"><circle cx="55" cy="55" r="50.8"/></g></svg>')
        self.assertEqual(r.status_code,200,r.json)
        d=r.json
        self.assertAlmostEqual(d['width'],101.6,places=2)
        self.assertAlmostEqual(d['height'],101.6,places=2)
        p=app.placed(dict(id=d['id'],scale=1,left=10,top=10))
        self.assertEqual(max(x for path in p for x,y in path)-min(x for path in p for x,y in path),2032)
        with self.assertRaises(ValueError):app.placed(dict(id=d['id'],scale=4,left=10,top=10))
    def test_reject_bitmap_and_text(self):
        for tag in ['image','text','use','script']:
            self.assertEqual(self.upload(f'<svg xmlns="http://www.w3.org/2000/svg"><{tag}/></svg>').status_code,400)
    def test_no_motion_without_token_or_confirmation(self):
        with patch('app.device') as dev:
            self.assertEqual(self.c.post('/api/travel',json={'x':304,'clear':True}).status_code,403)
            self.assertEqual(self.post('/api/travel',{'x':304,'clear':False}).status_code,400)
            dev.assert_not_called()
    def test_travel_packet_contains_no_tool_commands(self):
        def immediate(fn):
            fn('mock')
            return app.jsonify(accepted=True)
        with patch('app.launch',side_effect=immediate),patch('app.send') as send,patch('app.wait_ready'):
            r=self.post('/api/travel',{'x':304,'speed':10,'clear':True})
            send.assert_called_once_with('mock',['Z6080,6080','!10','M0,6080'])
    def test_invalid_numbers(self):
        for x in [float('nan'),-1,305]:
            self.assertEqual(self.post('/api/travel',{'x':x,'clear':True}).status_code,400)

    def test_simplify_preserves_corners_and_closure(self):
        points=[[0,0],[0,0],[5,0],[10,0],[10,5],[10,10],[0,10],[0,0]]
        self.assertEqual(app.simplify(points),[[0,0],[10,0],[10,10],[0,10],[0,0]])

    def test_completed_travel_returns_to_zero_without_tool_commands(self):
        app.CANCEL.clear()
        app.DESIGNS['job-test']=dict(paths=[[[0,0],[5,0],[10,0],[10,10]]],width=10,height=10)
        def immediate(fn):
            fn('mock')
            return app.jsonify(accepted=True)
        with patch('app.launch',side_effect=immediate),patch('app.send') as send,patch('app.wait_ready'):
            r=self.post('/api/start',dict(id='job-test',mode='travel',ready=True))
            self.assertEqual(r.status_code,200,r.json)
            commands=[cmd for call in send.call_args_list for cmd in call.args[1]]
            self.assertEqual(commands[-1],'M0,0')
            self.assertTrue(all(cmd.startswith(('M','Z','!')) for cmd in commands))

    def test_legacy_test_mode_sends_only_motion_commands(self):
        app.CANCEL.clear()
        app.DESIGNS['job-test']=dict(paths=[[[0,0],[10,0],[10,10]]],width=10,height=10)
        params=dict(id='job-test',mode='tool-free',ready=True)
        def immediate(fn):
            fn('mock')
            return app.jsonify(accepted=True)
        with patch('app.launch',side_effect=immediate),patch('app.send') as send,patch('app.wait_ready'):
            r=self.post('/api/start',dict(params,tool_removed=True))
            self.assertEqual(r.status_code,200,r.json)
            commands=[cmd for call in send.call_args_list for cmd in call.args[1]]
            self.assertTrue(all(cmd.startswith(('M','Z','!')) for cmd in commands))
            self.assertFalse(any(cmd.startswith(('FX','FC','FN')) for cmd in commands))
            self.assertEqual(commands[-1],'M0,0')

if __name__=='__main__':unittest.main()
