import random
import ssl
import websockets
import asyncio
import os
import sys
import json
import argparse
import time
from uuid import uuid4

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp

from IPython.display import Javascript as Javascript
from IPython.display import display
from ipywidgets import HTML as widget_HTML
import threading
import traitlets
import socket, errno


class ClickableImageWidget(widget_HTML):
    
    data = traitlets.Any()
    
    def __init__(self, width:int, height:int, encoder:str = 'vp8enc') -> None:
        Gst.init(None)
        self.ws_port = self.get_free_port()
        assert self.ws_port != -1, "cannot find a websocket port, maybe created too many ClickableImageWidget?"
        self.ws_thread = threading.Thread(target=self.ws_loop)
        self.ws_thread.start()
        self.width = width
        self.height = height
        self.encoder = encoder
        self.blank_buff = Gst.Buffer.new_allocate(None, int(width*height*3), None)
        self.pipe = None
        self.webrtc = None
        self.appsrc = None
        self.connected_ws = None
        self.click_callback = None
        self.uuid = str(uuid4()).replace('-','')
        self.js_var_name = f"image_widget_{self.uuid}"
        self.video_class_name = f"stream_widget_{self.uuid}"
        super().__init__(value=f"""<video class="{self.video_class_name}" autoplay playsinline muted style="padding: 0;margin: 0;">Your browser does not support video</video>""")
        
    def get_free_port(self) -> int:
        ret = -1
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        for i in range(1024, 49151):
            try:
                s.bind(("127.0.0.1", i))
            except socket.error as e:
                if e.errno == errno.EADDRINUSE:
                    continue
                else:
                    # something else raised the socket.error exception
                    print(e)
                    continue
            s.close()
            ret = i
            break
        return ret
    
    def ws_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(websockets.serve(self.ws_response, '0.0.0.0', self.ws_port))
        loop.run_forever()
        
    async def ws_response(self, websocket, path):
        if self.connected_ws:
            try:
                await self.connected_ws.send(json.dumps({'type': 'close'}))
            except:
                print("send close signal error, maybe it already closed")
            time.sleep(1)
            self.close_pipeline()
        self.connected_ws = websocket
        self.start_pipeline()
        try:
            async for message in websocket:
#                 print(f"{message} from {websocket}")
                msg = json.loads(message)
                if 'sdp' == msg['type']:
                    sdp = msg['data']
                    assert(sdp['type'] == 'answer')
                    sdp = sdp['sdp']
                    res, sdpmsg = GstSdp.SDPMessage.new()
                    GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
                    answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
                    promise = Gst.Promise.new()
                    self.webrtc.emit('set-remote-description', answer, promise)
                    promise.interrupt()
                elif 'ice' == msg['type']:
                    ice = msg['data']
                    candidate = ice['candidate']
                    sdpmlineindex = ice['sdpMLineIndex']
                    self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)
                elif 'click' == msg['type'] and self.click_callback:
                    event = msg['data']
                    event['eventData']['width'] = self.width
                    event['eventData']['height'] = self.height
                    event['eventData']['naturalWidth'] = self.width
                    event['eventData']['naturalHeight'] = self.height
                    self.click_callback(self, event, [])
        except websockets.exceptions.ConnectionClosedError:
#             print("closed error")
            return
        self.connected_ws = None

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        sdp_offer_msg = json.dumps({'type': 'sdp', 'data': {'type': 'offer', 'sdp': text}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.connected_ws.send(sdp_offer_msg))
        loop.close()
    
    def on_offer_created(self, promise, _, __):
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')
        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        icemsg = json.dumps({'type': 'ice', 'data': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.connected_ws.send(icemsg))
        loop.close()

    def on_incoming_stream(self, _, pad):
        print("recv incoming stream, not gonna process it")
        return

    def start_pipeline(self):
        self.pipe = Gst.parse_launch(f'appsrc name=src emit-signals=True is-live=True max-latency=0 min-latency=0 do-timestamp=True caps=video/x-raw,format=BGR,width={self.width},height={self.height},framerate=0/1 ! videoconvert ! queue ! {self.encoder} ! rtpvp8pay ! queue ! application/x-rtp,media=video,encoding-name=VP8,payload=97 ! webrtcbin name=sendrecv bundle-policy=max-bundle stun-server=stun://stun.l.google.com:19302')
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.send_ice_candidate_message)
        self.webrtc.connect('pad-added', self.on_incoming_stream)
        self.appsrc = self.pipe.get_by_name('src')
        self.appsrc.set_property("format", Gst.Format.TIME)
        self.appsrc.set_property("block", True)  # block push-buffers when queue is full
        self.bus = self.pipe.get_bus()
        self.pipe.set_state(Gst.State.PLAYING)
#         print("starting pipeline")
        self.appsrc.emit("push-buffer", self.blank_buff)
#         print("pipeline started")

    def close_pipeline(self):
        self.pipe.set_state(Gst.State.NULL)
        self.pipe = None
        self.webrtc = None
        
    @traitlets.observe('data')
    def on_value_change(self, change):
        if self.appsrc:
            buffer = Gst.Buffer.new_wrapped(change['new'].tobytes())
            self.appsrc.emit("push-buffer", buffer)
    
    def on_msg(self, callback_func):
        self.click_callback = callback_func
    
    def display(self):
        js_script = Javascript(f'''
                if (typeof html5VideoElement{self.uuid} === "undefined") {{
                    var html5VideoElement{self.uuid} = null;
                    var websocketConnection{self.uuid} = null;
                    var webrtcPeerConnection{self.uuid} = null;
                    var webrtcConfiguration{self.uuid} = null;
                    var reportError{self.uuid} = null;
                    var remoteStream{self.uuid} = null;
                }}

                function onLocalDescription{self.uuid}(desc) {{
                    console.log("Local description: " + JSON.stringify(desc));
                    webrtcPeerConnection{self.uuid}.setLocalDescription(desc).then(function() {{
                        websocketConnection{self.uuid}.send(JSON.stringify({{ type: "sdp", "data": webrtcPeerConnection{self.uuid}.localDescription }}));
                    }}).catch(reportError{self.uuid});
                }}

                function onIncomingSDP{self.uuid}(sdp) {{
                    console.log("Incoming SDP: " + JSON.stringify(sdp));
                    webrtcPeerConnection{self.uuid}.setRemoteDescription(sdp).catch(reportError{self.uuid});
                    webrtcPeerConnection{self.uuid}.createAnswer().then(onLocalDescription{self.uuid}).catch(reportError{self.uuid});
                }}

                function onIncomingICE{self.uuid}(ice) {{
                    let candidate = new RTCIceCandidate(ice);
                    console.log("Incoming ICE: " + JSON.stringify(ice));
                    webrtcPeerConnection{self.uuid}.addIceCandidate(candidate).catch(reportError{self.uuid});
                }}

                function onAddRemoteStream{self.uuid}(event) {{
                    console.log("onAddRemoteStream", event);
                    remoteStream{self.uuid} = event.streams[0];
                    for (let i = 0; i < html5VideoElement{self.uuid}.length; ++i) {{
                        html5VideoElement{self.uuid}[i].srcObject = remoteStream{self.uuid};
                    }}
                }}

                function onIceCandidate{self.uuid}(event) {{
                    if (event.candidate == null){{
                        console.log("ICE candidate null");
                        return;
                    }}

                    console.log("Sending ICE candidate out: " + JSON.stringify(event.candidate));
                    websocketConnection{self.uuid}.send(JSON.stringify({{ "type": "ice", "data": event.candidate }}));
                }}


                function onClose{self.uuid}() {{
                    websocketConnection{self.uuid}.close();
                    console.log(websocketConnection{self.uuid}.readyState)
                    websocketConnection{self.uuid} = null;
                    webrtcPeerConnection{self.uuid}.close();
                    webrtcPeerConnection{self.uuid} = null;
                    console.log("requested to close the stream");
                }}

                function onServerMessage{self.uuid}(event) {{
                    let msg;

                    try {{
                        msg = JSON.parse(event.data);
                    }} catch (e) {{
                        return;
                    }}

                    if (!webrtcPeerConnection{self.uuid}) {{
                        webrtcPeerConnection{self.uuid} = new RTCPeerConnection(webrtcConfiguration{self.uuid});
                        webrtcPeerConnection{self.uuid}.ontrack = onAddRemoteStream{self.uuid};
                        webrtcPeerConnection{self.uuid}.onicecandidate = onIceCandidate{self.uuid};
                        webrtcPeerConnection{self.uuid}.addEventListener('connectionstatechange', event => {{
                            console.log("webrtc state", webrtcPeerConnection{self.uuid}.connectionState);
                        }});
                        webrtcPeerConnection{self.uuid}.oniceconnectionstatechange = (event) => {{
                            console.log("ice state", webrtcPeerConnection{self.uuid}.iceConnectionState);
                        }};
                        webrtcPeerConnection{self.uuid}.onicecandidateerror = (event) => {{console.log(event)}};
                    }}

                    switch (msg.type) {{
                        case "sdp": onIncomingSDP{self.uuid}(msg.data); break;
                        case "ice": onIncomingICE{self.uuid}(msg.data); break;
                        case "close": onClose{self.uuid}(); break;
                        default: break;
                    }}
                }}

                function videoClicked{self.uuid}(event) {{
                    if (websocketConnection{self.uuid} !== null && websocketConnection{self.uuid}.readyState===1) {{
                        let x = event.offsetX;
                        let y = event.offsetY;
                        websocketConnection{self.uuid}.send(JSON.stringify({{
                            "type": "click",
                            "data": {{
                                'event': 'click',
                                'eventData': {{
                                    'altKey': event.altKey,
                                    'ctrlKey': event.ctrlKey,
                                    'shiftKey': event.shiftKey,
                                    'offsetX': x,
                                    'offsetY': y
                                }}
                            }}
                        }}));
                    }} else {{
                        playStream{self.uuid}();
                    }}
                    event.preventDefault();
                }}

                function playStream{self.uuid}() {{
                    if (websocketConnection{self.uuid} === null) {{
                        let l = window.location;
                        let wsUrl = "ws://" + l.hostname + ":{self.ws_port}/webrtc";

                        html5VideoElement{self.uuid} = document.getElementsByClassName("{self.video_class_name}");
                        for (let i = 0; i < html5VideoElement{self.uuid}.length; ++i) {{
                            html5VideoElement{self.uuid}[i].removeEventListener("mousedown", videoClicked{self.uuid}, false);
                            html5VideoElement{self.uuid}[i].addEventListener("mousedown", videoClicked{self.uuid}, false);
                        }}
                        webrtcConfiguration{self.uuid} = {{ 'iceServers': [{{urls: "stun:stun.l.google.com:19302"}}] }};
                        reportError{self.uuid} = function (errmsg) {{ console.error(errmsg); }};

                        websocketConnection{self.uuid} = new WebSocket(wsUrl);
                        websocketConnection{self.uuid}.addEventListener("message", onServerMessage{self.uuid});
                    }} else {{
                        html5VideoElement{self.uuid} = document.getElementsByClassName("{self.video_class_name}");
                        for (let i = 0; i < html5VideoElement{self.uuid}.length; ++i) {{
                            html5VideoElement{self.uuid}[i].srcObject = remoteStream{self.uuid};
                            html5VideoElement{self.uuid}[i].removeEventListener("mousedown", videoClicked{self.uuid}, false);
                            html5VideoElement{self.uuid}[i].addEventListener("mousedown", videoClicked{self.uuid}, false);
                        }}
                    }}
                }}
                playStream{self.uuid}();
        ''', lib='https://webrtc.github.io/adapter/adapter-latest.js')
        display(js_script)
    
    def _ipython_display_(self, **kwargs):
        super()._ipython_display_(**kwargs)
        self.display()
        
    def _repr_pretty_(self, **kwargs):
        super()._repr_pretty_(**kwargs)
        self.display()

    def _repr_html_(self, **kwargs):
        super()._repr_html_(**kwargs)
        self.display()
        
    def _repr_mimebundle_(self, **kwargs):
        super()._repr_mimebundle_(**kwargs)
        self.display()
        
    def _handle_displayed(self, **kwargs):
        super()._handle_displayed(**kwargs)
        self.display()