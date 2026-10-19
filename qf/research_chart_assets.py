"""复用锁定SDK静态页面与本机离线协议适配。"""

import json


def chart_html(assets, *, live=None):
    shim = """<script>window.__qfReplay=true;
const OriginalSocket=window.WebSocket;
window.WebSocket=function(url,protocols){
 if(new URL(url,location.href).hostname==='127.0.0.1')
   return protocols?new OriginalSocket(url,protocols):new OriginalSocket(url);
 return Object.assign(new EventTarget(),{readyState:1,send(){},close(){this.readyState=3;}});
};Object.assign(window.WebSocket,{CONNECTING:0,OPEN:1,CLOSING:2,CLOSED:3});
window.__replayRequests={};
(window.webpackJsonp=window.webpackJsonp||[]).push([['qf-replay-wire'],{'qf-replay-wire':function(module,exports,require){
 const p=require('0977').a.prototype,original=p.setChart;
 p.setChart=p.set_chart=function(options){const result=original.call(this,options);
 const request=this.quotesWs.charts[options.chart_id];
 if(request)window.__replayRequests[request.chart_id]={...request};return result;};
}},[['qf-replay-wire','chunk-vendors']]]);</script>
<style>.tq-button-group-durations{display:none!important}
.qf-replay-banner{padding:7px;background:#fff1cd;font:13px Microsoft YaHei}</style>"""
    if live is not None:
        shim = shim.replace('window.__qfReplay=true;',
                            'window.__qfLiveResearch='+json.dumps(live)+';')
    html = (assets / "index.html").read_text("utf-8").replace("<head>", "<head>" + shim)
    html = html.replace(
        "<title>tqsdk-python-web</title>", "<title>离线复盘 · 双均线实验</title>"
    )
    html = html.replace("</body>", '<script src="/replay.js"></script></body>')
    if live is not None:
        html = html.replace('</body>', '<script src="/live.js"></script></body>')
    return html
