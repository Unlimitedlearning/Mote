"""网页界面：左侧会话列表，右侧对话区。零第三方资源，Markdown 渲染内置。"""

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mote · 思维顾问</title>
<style>
:root{
  --bg:#fff; --side:#f7f8fa; --text:#1f2329; --muted:#8a9099; --line:#e8eaee;
  --accent:#2f6fed; --hover:#eceef2; --user:#eaf1ff; --code:#f5f6f8;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:var(--text);background:var(--bg)}
body{display:flex;overflow:hidden}
button,input,textarea{font:inherit}
button{cursor:pointer}
aside{width:264px;flex:0 0 264px;background:var(--side);border-right:1px solid var(--line);display:flex;flex-direction:column;transition:width .18s,flex-basis .18s;overflow:hidden}
aside.collapsed{width:0;flex-basis:0;border:0}
.brand{height:56px;display:flex;align-items:center;gap:10px;padding:0 14px}
.logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,#4f7cff,#7a5cff);color:#fff;display:grid;place-items:center;font-weight:700;font-size:15px}
.brand b{font-size:16px;letter-spacing:.2px;flex:1}
.icon-btn{border:0;background:transparent;color:var(--muted);width:30px;height:30px;border-radius:7px;font-size:17px}
.icon-btn:hover{background:var(--hover);color:var(--text)}
.new-chat{margin:4px 12px 10px;padding:10px;border:1px solid var(--line);background:#fff;border-radius:10px;color:var(--text);text-align:left;display:flex;align-items:center;gap:8px}
.new-chat:hover{border-color:#c9d6f5;background:#f8faff}
.new-chat span{color:var(--accent);font-size:18px;line-height:1}
.search{margin:0 12px 8px;position:relative}
.search input{width:100%;padding:7px 10px 7px 28px;border:1px solid transparent;border-radius:8px;background:#eceef2;outline:0;font-size:13px}
.search input:focus{background:#fff;border-color:#c9d6f5}
.search::before{content:"⌕";position:absolute;left:9px;top:5px;color:var(--muted);font-size:16px}
.hits{display:none;padding:0 8px 6px;max-height:44vh;overflow-y:auto}
.hits .hd{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);padding:6px 4px}
.hits .hempty{font-size:12px;color:var(--muted);padding:4px 4px 8px}
.hit{display:block;width:100%;text-align:left;border:1px solid var(--line);background:#fff;border-radius:9px;padding:7px 9px;margin:4px 0;color:var(--text)}
.hit:hover{border-color:#c9d6f5;background:#f8faff}
.hit .ht{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hit .hs{font-size:11.5px;color:#5b6270;margin-top:2px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word}
.hit mark{background:#fff0b0;color:inherit;border-radius:2px;padding:0 1px}
.hit .hm{font-size:10.5px;color:var(--muted);margin-top:3px}
.sessions{flex:1;overflow-y:auto;padding:2px 8px 12px}
.group{font-size:11px;color:var(--muted);padding:10px 8px 4px;letter-spacing:.4px}
.session-row{position:relative}
.session{display:block;width:100%;text-align:left;border:0;background:transparent;border-radius:8px;padding:8px 30px 8px 9px;margin:1px 0;color:var(--text)}
.session:hover{background:var(--hover)}
.session.active{background:#e7efff}
.session .t{font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.session .m{font-size:11px;color:var(--muted);margin-top:1px}
.more{position:absolute;right:5px;top:8px;width:22px;height:22px;border:0;border-radius:5px;background:transparent;color:var(--muted);font-size:14px;line-height:1;opacity:0}
.session-row:hover .more,.session-row.open .more{opacity:1}
.more:hover{background:#fff;color:var(--text)}
.menu{display:none;position:absolute;right:5px;top:33px;z-index:8;min-width:118px;padding:4px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 18px #00000018}
.session-row.open .menu{display:block}
.menu button{display:block;width:100%;text-align:left;border:0;background:transparent;border-radius:5px;padding:6px 8px;font-size:12px;color:var(--text)}
.menu button:hover{background:var(--hover)}
.menu button.danger{color:#d93026}
.rename-input{width:100%;font-size:13px;padding:3px 5px;border:1px solid var(--accent);border-radius:5px;outline:0}
.side-foot{padding:10px 14px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);display:flex;align-items:center;gap:8px}
.side-foot span{flex:1}
.side-foot .foot-link{border:0;background:transparent;color:var(--muted);font-size:11px;padding:1px 0;text-decoration:underline}
.side-foot .foot-link:hover{color:var(--accent)}
main{flex:1;min-width:0;display:flex;flex-direction:column;background:#fff;position:relative}
.topbar{height:56px;flex:0 0 56px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px;padding:0 18px}
.topbar .title{font-weight:600;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.topbar .model{font-size:12px;color:var(--muted);white-space:nowrap}
.scroll{flex:1;overflow-y:auto;scroll-behavior:smooth}
.thread{max-width:820px;margin:0 auto;padding:20px 20px 40px}
.load-more{display:block;margin:6px auto 14px;padding:6px 14px;border:1px solid var(--line);background:#fff;color:var(--muted);border-radius:999px;font-size:12px}
.load-more:hover{border-color:#c9d6f5;background:#f8faff;color:var(--text)}
.msg{display:flex;gap:12px;margin:24px 0}
.msg.user{flex-direction:row-reverse}
.avatar{width:30px;height:30px;flex:0 0 30px;border-radius:9px;display:grid;place-items:center;font-size:12px;font-weight:600}
.avatar.u{background:#e8eaee;color:#5b6270}
.avatar.m{background:linear-gradient(135deg,#4f7cff,#7a5cff);color:#fff}
.bubble{max-width:86%;min-width:0}
.msg.user .bubble{background:var(--user);padding:10px 14px;border-radius:14px 14px 4px 14px;white-space:pre-wrap;word-break:break-word}
.msg.assistant .bubble{padding-top:3px}
.md>*:first-child{margin-top:0}
.md>*:last-child{margin-bottom:0}
.md p{margin:0 0 10px}
.md h1,.md h2,.md h3,.md h4,.md h5,.md h6{margin:18px 0 8px;line-height:1.35}
.md h1{font-size:20px}.md h2{font-size:18px}.md h3{font-size:16px}
.md ul,.md ol{margin:6px 0 10px;padding-left:22px}
.md li{margin:3px 0}
.md blockquote{margin:10px 0;padding:6px 12px;border-left:3px solid #c9d6f5;background:#f7f9ff;color:#4b5563}
.md hr{border:0;border-top:1px solid var(--line);margin:16px 0}
.md a{color:var(--accent);text-decoration:none}
.md a:hover{text-decoration:underline}
.md :not(pre)>code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.md pre{background:#1f2430;color:#e8eaf0;border-radius:10px;overflow:hidden;margin:12px 0}
.md pre .head{display:flex;justify-content:space-between;align-items:center;padding:5px 12px;background:#262c3a;font-size:11px;color:#aab0bd}
.md pre .head button{border:0;background:transparent;color:#c8cdd8;font-size:11px;padding:2px 6px;border-radius:4px}
.md pre .head button:hover{background:#394052}
.md pre code{display:block;padding:12px 14px;overflow:auto;font-size:12.5px;line-height:1.55;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre}
.md .table-wrap{overflow:auto;margin:10px 0}
.md table{border-collapse:collapse;width:100%;font-size:13px}
.md th,.md td{border:1px solid var(--line);padding:6px 10px;text-align:left}
.md th{background:#f7f8fa}
.lens-row{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.lens-chip{font-size:11px;color:#4b657f;background:#eef3fb;border:1px solid #dce7f7;border-radius:20px;padding:1px 8px}
.thinking{display:inline-flex;align-items:center;gap:8px;color:#526072;font-size:13px}
.spin{width:13px;height:13px;border:2px solid #d7e0f5;border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.secs{color:var(--muted);font-variant-numeric:tabular-nums}
.think{margin:0 0 10px;border:1px solid var(--line);border-radius:10px;background:#fafbfc;overflow:hidden}
.think>summary{cursor:pointer;padding:7px 12px;color:var(--muted);font-size:12px;list-style:none;display:flex;align-items:center;gap:7px}
.think>summary::-webkit-details-marker{display:none}
.think>summary::before{content:"▸";font-size:10px;transition:transform .15s}
.think[open]>summary::before{transform:rotate(90deg)}
.think .body{padding:9px 12px;max-height:320px;overflow:auto;word-break:break-word;color:#5b6270;font-size:12.5px;line-height:1.6;border-top:1px solid var(--line)}
.think .body.md h1,.think .body.md h2,.think .body.md h3,.think .body.md h4,.think .body.md h5,.think .body.md h6{font-size:13px;margin:10px 0 6px}
.think .body.md p{margin:0 0 8px}
.think .body.md ul,.think .body.md ol{margin:4px 0 8px;padding-left:20px}
.think .body.md blockquote{margin:8px 0;padding:5px 10px;background:#f3f5f9}
.think .body.md pre{margin:8px 0}
.think .body.md :not(pre)>code{background:#eceff4;border:1px solid #e0e4ea}
.think .body.md hr{margin:10px 0}
.topbar .status{font-size:12px;color:var(--accent)}
.top-btn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:4px 10px;color:var(--text);font-size:12px;white-space:nowrap}
.top-btn:hover{border-color:#c9d6f5;background:#f8faff}
/* 对话内查找：占用顶栏下方一条，不遮正文 */
.findbar{display:none;flex:0 0 auto;align-items:center;gap:5px;padding:7px 18px;border-bottom:1px solid var(--line);background:#fbfcfe}
.findbar.show{display:flex}
.findbar .fhint{flex:1;font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.findbar input{width:190px;border:1px solid #dcdfe6;background:#fff;border-radius:7px;padding:4px 9px;outline:0;font-size:12.5px}
.findbar input:focus{border-color:#a9c4fb}
.findbar input.none{color:#b3261e;background:#fdf5f4;border-color:#f3c6c2}
.findbar .fc{font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums;min-width:56px;text-align:center}
.findbar button{border:0;background:transparent;color:#5b6270;width:24px;height:24px;border-radius:6px;font-size:13px;line-height:1;padding:0}
.findbar button:hover{background:var(--hover);color:var(--text)}
mark.find{background:#ffe58a;color:inherit;border-radius:2px;padding:0 1px}
mark.find.on{background:#ffb020;box-shadow:0 0 0 2px #ffb02040}
.msg.user .bubble{position:relative}
.msg-actions{display:flex;justify-content:flex-end;margin-top:2px}
.msg-more{border:0;background:transparent;color:var(--muted);border-radius:5px;padding:0 5px;font-size:14px;line-height:1.2;opacity:.65}
.msg-more:hover{background:#fff;opacity:1}
.msg-menu{display:none;position:absolute;right:0;bottom:-4px;transform:translateY(100%);z-index:9;min-width:148px;padding:4px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 8px 22px #0000001f;white-space:nowrap}
.msg-menu.open{display:block}
.msg-menu button{display:block;width:100%;text-align:left;border:0;background:transparent;border-radius:5px;padding:6px 8px;font-size:12px;color:var(--text)}
.msg-menu button:hover{background:var(--hover)}
.msg-menu button.danger{color:#d93026}
#note{position:fixed;left:50%;bottom:30px;transform:translate(-50%,8px);max-width:min(520px,86vw);background:#1f2329e8;color:#fff;font-size:13px;line-height:1.5;padding:9px 15px;border-radius:9px;box-shadow:0 8px 24px #00000026;opacity:0;pointer-events:none;transition:opacity .18s,transform .18s;z-index:60;text-align:center}
#note.show{opacity:1;transform:translate(-50%,0)}
.modal{display:none;position:fixed;inset:0;z-index:30;background:#00000055;align-items:center;justify-content:center;padding:20px}
.modal.show{display:flex}
.dialog{width:min(560px,100%);max-height:min(86vh,820px);background:#fff;border-radius:14px;box-shadow:0 18px 60px #00000033;display:flex;flex-direction:column;overflow:hidden}
.dialog .head{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--line)}
.dialog .head b{flex:1}
.dialog .body{padding:16px 18px;overflow:auto}
.dialog .foot{padding:12px 18px;border-top:1px solid var(--line);display:flex;justify-content:flex-end;gap:8px}
.dialog>.head button,.dialog>.foot button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 13px;color:var(--text);font-size:13px}
.dialog>.foot button.primary{border-color:var(--accent);background:var(--accent);color:#fff}
/* 设置面板：分组表单，key 只回显首尾几位 */
#setModal .dialog{width:min(620px,100%)}
.set-group{border:1px solid var(--line);border-radius:11px;padding:13px 14px;margin-bottom:12px}
.set-title{font-size:13px;font-weight:600}
.set-sub{font-size:12px;color:var(--muted);margin:3px 0 9px;line-height:1.55}
.set-row{display:flex;align-items:center;gap:10px;margin-top:8px}
.set-row label{flex:0 0 66px;font-size:12px;color:var(--muted)}
.set-row input{flex:1;min-width:0;border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;color:var(--text);background:#fff}
.set-row input:focus{outline:none;border-color:#c9d6f5;box-shadow:0 0 0 3px #eef3ff}
.set-check{display:flex;align-items:flex-start;gap:8px;margin-top:11px;font-size:12.5px;cursor:pointer;line-height:1.5}
.set-check input{margin:2px 0 0}
.set-check small{display:block;color:var(--muted);font-size:11.5px;margin-top:2px;line-height:1.5}
.set-pick{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.set-pick button{border:1px solid var(--line);background:#fff;border-radius:9px;padding:9px 11px;text-align:left;color:var(--text);font-size:12.5px;line-height:1.5}
.set-pick button b{display:block;font-size:13px;margin-bottom:2px}
.set-pick button small{display:block;color:var(--muted);font-size:11.5px}
.set-pick button:hover{border-color:#c9d6f5;background:#f8faff}
.set-pick button.active{border-color:#a9c4fb;background:#f3f7ff}
.set-pick button.active b{color:var(--accent)}
.set-pick button:disabled{opacity:.5;cursor:default;background:#fff;border-color:var(--line)}
.set-warn{font-size:11.5px;color:#a8681a;line-height:1.55;margin:8px 0 0}
.set-hint{font-size:11.5px;color:var(--muted);line-height:1.6;margin:2px 0 0;word-break:break-all}
#setTest{font-size:12px;margin-right:auto;align-self:center;color:var(--muted);line-height:1.45;max-width:56%}
#setTest.ok{color:#2f8f5b}
#setTest.bad{color:#d93026}
#treeModal .dialog{width:min(1080px,96vw)}
#treeModal .body{overflow:auto;padding:14px 16px 18px}
#treeBox{display:flex;flex-direction:column;align-items:flex-start;gap:20px}
/* 自上而下的树：由 JS 算出坐标后画在 SVG 上，不再依赖伪元素拼接连线 */
.tree-map{width:max-content}
.tree-map.narrow{margin:0 auto}
.tree-map svg{display:block;overflow:visible}
.tm-edge{fill:none;stroke:#c9cfda;stroke-width:1;stroke-linecap:round}
.tm-edge.main{stroke:#2fa36b;stroke-width:1.4}
.tm-edge.on{stroke:#a8c0f2;stroke-width:1.4}
.tm-node{cursor:pointer}
.tm-node .dot{fill:#ccd1da}
.tm-node:hover .dot{fill:#a8b0bb}
.tm-node .halo{fill:#d6e2ff}
.tm-node.on .dot{fill:#5b8bf0}
.tm-node.on:hover .dot{fill:var(--accent)}
.tm-node.cur .dot{fill:var(--accent)}
/* 主分支：不在当前链路上时是绿色；与当前链路重合时保留蓝底、加一圈绿色描边 */
.tm-node.main .dot{fill:#2fa36b}
.tm-node.main.on .dot{fill:#5b8bf0;stroke:#2fa36b;stroke-width:1.6}
.tree-legend{display:flex;align-items:center;gap:12px;margin-right:auto;font-size:11px;color:var(--muted);flex-wrap:wrap}
.tree-legend span{display:inline-flex;align-items:center;gap:5px}
.tree-legend i{display:inline-block;width:9px;height:9px;border-radius:50%;background:#ccd1da}
.tree-legend i.path{background:#5b8bf0}
.tree-legend i.main{background:#2fa36b}
.tree-legend i.cur{background:var(--accent);box-shadow:0 0 0 2px #d6e2ff}
.tree-stat{font-size:11px;color:var(--muted);font-weight:400;margin-left:auto}
.branch-nav{display:inline-flex;align-items:center;gap:3px;border:1px solid var(--line);border-radius:14px;padding:1px 4px;background:#fafbfc}
.branch-nav button{border:0;background:transparent;color:var(--muted);width:22px;height:22px;border-radius:50%;font-size:14px;line-height:1}
.branch-nav button:hover{background:var(--hover);color:var(--text)}
.branch-nav .count{font-size:11px;color:var(--muted);min-width:30px;text-align:center;font-variant-numeric:tabular-nums}
.q-foot{display:flex;align-items:center;gap:8px;margin-top:7px;min-height:22px}
.q-foot .msg-actions{margin-left:auto;margin-top:0}
.q-hit{animation:qhit 1.1s ease-out}
@keyframes qhit{0%{background:#e7efff}100%{background:transparent}}
.edit-text{width:100%;min-height:110px;max-height:240px;resize:vertical;border:1px solid #dcdfe6;border-radius:9px;padding:9px 11px;outline:0;font:inherit}
.edit-text:focus{border-color:#a9c4fb}
.empty{max-width:640px;margin:12vh auto 0;text-align:center}
.empty .big{width:48px;height:48px;margin:0 auto 14px;border-radius:14px;background:linear-gradient(135deg,#4f7cff,#7a5cff);color:#fff;display:grid;place-items:center;font-size:22px;font-weight:700}
.empty h2{font-size:20px;margin:0 0 6px}
.empty p{color:var(--muted);margin:0 0 22px}
.suggest{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.suggest button{border:1px solid var(--line);background:#fff;border-radius:10px;padding:12px;text-align:left;color:var(--text);font-size:13px}
.suggest button:hover{border-color:#c9d6f5;background:#f8faff}
.to-latest{position:absolute;right:24px;bottom:132px;border:1px solid var(--line);background:#fff;border-radius:20px;padding:6px 13px;font-size:12px;color:var(--text);box-shadow:0 4px 16px #00000012;opacity:0;pointer-events:none;transition:opacity .15s}
.to-latest.show{opacity:1;pointer-events:auto}
.composer{flex:0 0 auto;padding:10px max(20px,calc((100% - 820px)/2)) 14px;border-top:1px solid var(--line);background:#fff}
.box{border:1px solid #dcdfe6;border-radius:14px;padding:8px 8px 8px 14px;display:flex;align-items:flex-end;gap:8px;box-shadow:0 2px 10px #00000006}
.box:focus-within{border-color:#a9c4fb}
textarea{flex:1;border:0;outline:0;resize:none;max-height:160px;min-height:26px;line-height:1.6;padding:4px 0;background:transparent}
.send{border:0;width:32px;height:32px;border-radius:9px;background:var(--accent);color:#fff;font-size:15px;line-height:1}
.send:disabled{background:#b8c6e4;cursor:default}.send.stop{background:#3b3f46}.send.stop:hover{background:#2f3339}.ans-tools{display:flex;align-items:center;gap:4px;margin-top:8px;opacity:0;transition:opacity .15s}.msg:hover .ans-tools,.ans-tools.busy{opacity:1}.ans-tools button{border:1px solid transparent;background:transparent;color:var(--muted);border-radius:6px;padding:2px 7px;font-size:11px;line-height:1.6}.ans-tools button:hover{background:var(--hover);color:var(--text)}.failed{color:#b3261e}.err-box{border:1px solid #f3c6c2;background:#fdf5f4;border-radius:9px;padding:9px 11px}.err-box .row{display:flex;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap}.err-box button{border:1px solid var(--accent);background:#fff;color:var(--accent);border-radius:14px;padding:2px 11px;font-size:12px}.stop-note{font-size:11px;color:var(--muted);margin-top:6px}
.hint{display:flex;align-items:center;justify-content:center;gap:12px;color:var(--muted);font-size:11px;margin-top:6px}
@media(max-width:760px){
 aside{position:absolute;z-index:20;height:100%;box-shadow:6px 0 20px #00000012}
 .suggest{grid-template-columns:1fr}
 .thread{padding:14px 14px 30px}
 .findbar{padding:7px 12px}
 .findbar .fhint{display:none}
 .findbar input{width:auto;flex:1;min-width:0}
}
</style>
</head>
<body>
<aside id="side">
 <div class="brand"><div class="logo">M</div><b>Mote</b><button class="icon-btn" id="hide" title="收起侧栏">‹</button></div>
 <button class="new-chat" id="new"><span>＋</span>新建对话</button>
 <div class="search"><input id="search" placeholder="搜索对话或聊天内容"></div>
 <div class="hits" id="hits"></div>
 <div class="sessions" id="sessions"></div>
 <div class="side-foot"><span>本地思维顾问 · 对话留在本机</span><button type="button" class="foot-link" id="backup" title="导出全部会话为 JSON">备份</button></div>
</aside>
<main>
 <div class="topbar">
  <button class="icon-btn" id="toggle" title="展开/收起侧栏">☰</button>
  <div class="title" id="topTitle">新对话</div>
  <span class="status" id="status"></span>
  <button class="top-btn" id="findBtn" title="在当前对话里查找（Ctrl+F）">⌕ 查找</button>
  <button class="top-btn" id="branchBtn" title="查看当前对话的分支树">⑂ 分支树</button>
  <button class="top-btn" id="setBtn" title="设置模型与 API Key">⚙ 设置</button>
  <div class="model" id="model"></div>
 </div>
 <div class="findbar" id="findbar">
  <span class="fhint">只查当前对话 · 打完按 Enter 定位 · ↑↓ 翻看 · Esc 关闭</span>
  <input id="findInput" type="text" spellcheck="false" placeholder="查找内容，回车定位">
  <span class="fc" id="findCount">0/0</span>
  <button type="button" id="findPrev" title="上一处（Shift+Enter）">↑</button>
  <button type="button" id="findNext" title="下一处（Enter）">↓</button>
  <button type="button" id="findClose" title="关闭（Esc）">✕</button>
 </div>
 <div class="scroll" id="scroll"><div class="thread" id="thread"></div></div>
 <button class="to-latest" id="toLatest">↓ 跳到最新</button>
 <div class="composer">
  <div class="box"><textarea id="q" rows="1" placeholder="给 Mote 发消息…（Enter 发送，Shift+Enter 换行）"></textarea><button class="send" id="send" title="发送">➤</button></div>
  <div class="hint">
   <span>回答由模型生成，仅作判断参考，请自行核实</span>
  </div>
 </div>
</main>
<div class="modal" id="treeModal">
 <div class="dialog">
  <div class="head"><b>对话分支树</b><span class="tree-stat" id="treeStat"></span><button type="button" data-close="treeModal">关闭</button></div>
  <div class="body" id="treeBox"></div>
  <div class="foot"><div class="tree-legend"><span><i></i>其他分支</span><span><i class="main"></i>主分支</span><span><i class="path"></i>当前分支</span><span><i class="cur"></i>当前位置</span></div><button type="button" data-close="treeModal">完成</button></div>
 </div>
</div>
<div class="modal" id="editModal">
 <div class="dialog">
  <div class="head"><b>编辑问题并另开分支</b><button type="button" data-close="editModal">取消</button></div>
  <div class="body"><textarea class="edit-text" id="editText"></textarea></div>
  <div class="foot"><button type="button" data-close="editModal">取消</button><button type="button" class="primary" id="editSubmit">发送并分叉</button></div>
 </div>
</div>
<div class="modal" id="setModal">
 <div class="dialog">
  <div class="head"><b>设置</b><button type="button" data-close="setModal">关闭</button></div>
  <div class="body">
   <div class="set-group">
    <div class="set-title">问答方式</div>
    <div class="set-sub">每条消息怎么走：先用本地模型判断、压缩，还是直接交给云端。</div>
    <div class="set-pick" id="setMode">
     <button type="button" data-mode="hybrid"><b>本地处理 → API</b><small>本地模型先判断难易、压缩上下文，简单问题不调用云端。</small></button>
     <button type="button" data-mode="direct"><b>直接云端</b><small>跳过本地处理，每条消息都直接调用云端模型。</small></button>
    </div>
    <p class="set-warn" id="setModeWarn"></p>
   </div>
   <div class="set-group">
    <div class="set-title">云端模型 · 负责回答</div>
    <div class="set-sub">填任意 OpenAI 兼容接口：DeepSeek、通义、Kimi、OpenRouter 都可以。</div>
    <div class="set-row"><label for="setCloudUrl">接口地址</label><input id="setCloudUrl" type="text" spellcheck="false" placeholder="https://api.deepseek.com/v1"></div>
    <div class="set-row"><label for="setCloudModel">模型名</label><input id="setCloudModel" type="text" spellcheck="false" placeholder="deepseek-chat"></div>
    <div class="set-row"><label for="setCloudKey">API Key</label><input id="setCloudKey" type="password" spellcheck="false" autocomplete="off" placeholder="sk-…"></div>
    <label class="set-check"><input type="checkbox" id="setCloudThink"><span>显示思考过程<small>请求里开启 thinking；关掉更快更省，但回答上方不会有「思考过程」。</small></span></label>
   </div>
   <div class="set-group">
    <div class="set-title">本地模型 · 负责路由与压缩</div>
    <div class="set-sub">需要本机 Ollama（或兼容端点）；没有的话把上面的问答方式改成「直接云端」。</div>
    <div class="set-row"><label for="setLocalUrl">接口地址</label><input id="setLocalUrl" type="text" spellcheck="false" placeholder="http://localhost:11434/v1"></div>
    <div class="set-row"><label for="setLocalModel">模型名</label><input id="setLocalModel" type="text" spellcheck="false" placeholder="qwen3.5:4b"></div>
   </div>
   <p class="set-hint" id="setHint"></p>
  </div>
  <div class="foot"><span id="setTest"></span><button type="button" id="setTestBtn">测试连接</button><button type="button" class="primary" id="setSave">保存</button></div>
 </div>
</div>
<div id="note"></div>
<script>
const $=id=>document.getElementById(id);
const state={sessions:[],current:null,messages:[],names:{},tree:null,busy:false,seq:0,editNode:null,settingsMode:'hybrid',ctrl:null,retry:null,hits:[],hitTotal:0,hitSeq:0,searchTimer:null,win:40,treePos:null,settings:null,find:{open:false,q:'',hits:[],cur:-1,scroll:false,dirty:false,painted:false}};

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function inline(src){
  let s=esc(src), codes=[];
  s=s.replace(/`([^`\n]+)`/g,(m,c)=>{codes.push('<code>'+c+'</code>');return '__CD'+(codes.length-1)+'__';});
  s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  s=s.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
  s=s.replace(/~~([^~]+)~~/g,'<del>$1</del>');
  s=s.replace(/\[([^\]]+)\]\(([^)]+)\)/g,(m,t,u)=>{
    const url=u.trim();
    if(!/^(https?:\/\/|mailto:|#)/i.test(url))return m;
    return '<a href="'+esc(url)+'" target="_blank" rel="noopener">'+t+'</a>';
  });
  return s.replace(/__CD(\d+)__/g,(m,i)=>codes[Number(i)]||m);
}

function md(src){
  const lines=String(src||'').replace(/\r\n?/g,'\n').split('\n');
  const out=[]; let para=[]; let i=0;
  const flush=()=>{if(para.length){out.push('<p>'+inline(para.join('\n')).replace(/\n/g,'<br>')+'</p>');para=[];}};
  const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
  while(i<lines.length){
    const line=lines[i];
    if(/^\s*```/.test(line)){
      flush();
      const lang=line.trim().slice(3).trim(); const buf=[]; i++;
      while(i<lines.length&&!/^\s*```/.test(lines[i])){buf.push(lines[i]);i++;}
      i++;
      out.push('<pre><span class="head"><span>'+esc(lang||'text')+'</span><button type="button" class="copy">复制</button></span><code>'+esc(buf.join('\n'))+'</code></pre>');
      continue;
    }
    if(/^\s*$/.test(line)){flush();i++;continue;}
    const h=line.match(/^\s*(#{1,6})\s+(.*)$/);
    if(h){flush();out.push('<h'+h[1].length+'>'+inline(h[2])+'</h'+h[1].length+'>');i++;continue;}
    if(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)){flush();out.push('<hr>');i++;continue;}
    if(line.indexOf('|')>=0&&i+1<lines.length&&/^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$/.test(lines[i+1])){
      flush();
      const head=cells(lines[i]); i+=2; const rows=[];
      while(i<lines.length&&lines[i].trim()&&lines[i].indexOf('|')>=0){rows.push(cells(lines[i]));i++;}
      out.push('<div class="table-wrap"><table><thead><tr>'+head.map(x=>'<th>'+inline(x)+'</th>').join('')+
        '</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+inline(x)+'</td>').join('')+'</tr>').join('')+
        '</tbody></table></div>');
      continue;
    }
    if(/^\s*>\s?/.test(line)){
      flush(); const buf=[];
      while(i<lines.length&&/^\s*>\s?/.test(lines[i])){buf.push(lines[i].replace(/^\s*>\s?/,''));i++;}
      out.push('<blockquote>'+inline(buf.join('\n')).replace(/\n/g,'<br>')+'</blockquote>');continue;
    }
    const li=line.match(/^\s*([-*+]|\d+\.)\s+(.*)$/);
    if(li){
      flush(); const ordered=/^\d+\./.test(li[1]), items=[];
      while(i<lines.length){
        const m=lines[i].match(/^\s*([-*+]|\d+\.)\s+(.*)$/);
        if(!m||/^\d+\./.test(m[1])!==ordered)break;
        items.push('<li>'+inline(m[2])+'</li>');i++;
      }
      out.push('<'+(ordered?'ol':'ul')+'>'+items.join('')+'</'+(ordered?'ol':'ul')+'>');continue;
    }
    para.push(line);i++;
  }
  flush();return out.join('');
}

function scrollBottom(force){
  const el=$('scroll');
  if(force||el.scrollHeight-el.scrollTop-el.clientHeight<180)el.scrollTop=el.scrollHeight;
}

function thinkBlock(text,open,label,node){
  const d=document.createElement('details');d.className='think';if(open)d.open=true;
  const s=document.createElement('summary');s.textContent=label;
  // 推理原文常带小标题、列表和代码：按 Markdown 渲染，而不是原样贴文本
  const b=document.createElement('div');b.className='body md';b.innerHTML=text?md(text):'';
  if(!text&&node&&state.current){
    d.addEventListener('toggle',async()=>{
      if(!d.open||b.dataset.loaded)return;
      const sid=state.current;
      b.dataset.loaded='1';b.textContent='读取中…';
      try{
        const r=await fetch('/sessions/'+encodeURIComponent(sid)+'/thinking/'+encodeURIComponent(node));
        const data=await r.json();
        if(!r.ok||data.error)throw new Error(data.error||'读取失败');
        b.innerHTML=md(data.text||'');
        const m=state.messages.find(x=>x.role==='assistant'&&x.node===node);
        if(m){m.thinking=data.text||'';m.thinking_chars=(data.text||'').length;}
        s.textContent='思考过程（'+(data.chars||0)+' 字）';
      }catch(err){
        b.dataset.loaded='';b.textContent='思考内容读取失败：'+err.message;
      }
    });
  }
  d.appendChild(s);d.appendChild(b);return d;
}
function paintPendingInto(bubble,m){
  bubble.innerHTML='';
  if(m.thinking)bubble.appendChild(thinkBlock(m.thinking,true,'思考中 · '+m.thinking.length+' 字'));
  if(m.text){
    const body=document.createElement('div');body.className='md';body.innerHTML=md(m.text);
    bubble.appendChild(body);
  }else{
    const t=document.createElement('div');t.className='thinking';
    t.innerHTML='<span class="spin"></span>思考中<span class="secs"></span>';
    t.querySelector('.secs').textContent=((Date.now()-(m.started||Date.now()))/1000).toFixed(0)+'s';
    bubble.appendChild(t);
  }
}
function paintPending(){
  const idx=state.messages.findIndex(m=>m.pending);if(idx<0)return;
  const start=winStart();
  const row=$('thread').children[idx-start+(start>0?1:0)];if(!row)return;
  const bubble=row.querySelector('.bubble');if(!bubble)return;
  const old=bubble.querySelector('.think');
  paintPendingInto(bubble,state.messages[idx]);
  if(old&&old.open){const next=bubble.querySelector('.think');if(next)next.open=true;}
}

// 窗口默认取末尾 win 条；查找跳转会临时指定 [winFrom, winEnd) 这一小段，
// 否则上千轮的导入会话里定位一句话要把整段历史重绘一遍
function winStart(){return state.winFrom!=null?state.winFrom:Math.max(0,state.messages.length-state.win);}
function winEnd(){return state.winEnd!=null?Math.min(state.winEnd,state.messages.length):state.messages.length;}
function resetWin(){state.win=40;state.winFrom=null;state.winEnd=null;}
function branchIndex(){
  const nodes=(state.tree&&state.tree.nodes)||[];
  const groups={};
  nodes.forEach(n=>{const p=n.parent||null;(groups[p]=groups[p]||[]).push(n.id);});
  const map={};
  Object.keys(groups).forEach(p=>{
    const ids=groups[p];if(ids.length<2)return;
    ids.forEach((id,i)=>{map[id]={ids,at:i};});
  });
  return map;
}
function branchNavFor(node,index){
  const hit=index&&index[node];if(!hit)return null;
  const ids=hit.ids, at=hit.at;
  const el=document.createElement('div');el.className='branch-nav';
  el.dataset.prev=ids[(at-1+ids.length)%ids.length];
  el.dataset.next=ids[(at+1)%ids.length];
  el.innerHTML='<button type="button" data-act="prev" title="上一个分支">‹</button>'+
    '<span class="count">'+(at+1)+'/'+ids.length+'</span>'+
    '<button type="button" data-act="next" title="下一个分支">›</button>';
  return el;
}
function renderMessages(keep){
  const scroll=$('scroll'), prevTop=scroll.scrollTop, prevHeight=scroll.scrollHeight;
  const box=$('thread'); box.innerHTML='';state.find.painted=false;
  if(!state.messages.length){
    const e=document.createElement('div'); e.className='empty';
    e.innerHTML='<div class="big">M</div><h2>带一个问题来</h2><p>我会挑几个思维镜头，给你判断建议。任务清单由你自己管。</p>'+
      '<div class="suggest">'+
      ['<button>手里有个还没做完的项目，该不该现在换工作？','<button>这个方案看起来不错，怎么找它的隐患？','<button>两个 offer 差别很大，怎么判断哪个更适合我？','<button>团队一直加班，问题到底出在哪里？'].map(s=>s+'</button>').join('')+'</div>';
    box.appendChild(e);
    e.querySelectorAll('.suggest button').forEach(b=>b.onclick=()=>{$('q').value=b.textContent;$('q').focus();});
    $('toLatest').classList.remove('show');return;
  }
  const start=winStart(), end=winEnd(), index=branchIndex();
  let lastAnswer=-1;
  state.messages.forEach((m,i)=>{if(m.role==='assistant'&&m.node)lastAnswer=i;});
  if(start>0){
    const more=document.createElement('button');more.type='button';more.className='load-more';
    more.textContent='加载更早的 '+start+' 条';
    more.onclick=()=>{
      if(state.winFrom!=null)state.winFrom=Math.max(0,start-150);
      else state.win+=150;
      renderMessages(true);
    };
    box.appendChild(more);
  }
  state.messages.slice(start,end).forEach((m,offset)=>{
    const i=start+offset;
    const row=document.createElement('div');row.className='msg '+(m.role==='user'?'user':'assistant');
    const av=document.createElement('div');av.className='avatar '+(m.role==='user'?'u':'m');av.textContent=m.role==='user'?'你':'M';
    const bubble=document.createElement('div');bubble.className='bubble';
    if(m.role==='user'){
      bubble.textContent=m.text;
      if(m.node){
        const foot=document.createElement('div');foot.className='q-foot';
        const nav=branchNavFor(m.node,index);if(nav)foot.appendChild(nav);
        const actions=document.createElement('div');actions.className='msg-actions';
        actions.innerHTML='<button type="button" class="msg-more" data-node="'+esc(m.node)+'" title="管理这条问答">···</button>';
        const menu=document.createElement('div');menu.className='msg-menu';menu.dataset.node=esc(m.node);
        menu.innerHTML='<button type="button" data-act="main">'+mainLabel()+'</button>'+
          '<button type="button" data-act="edit">编辑并另开分支</button>'+
          '<button type="button" class="danger" data-act="delete">删除问题与回复</button>';
        actions.appendChild(menu);foot.appendChild(actions);
        bubble.appendChild(foot);
      }
    }
    else if(m.pending){paintPendingInto(bubble,m);}
    else if(m.error){
      const box=document.createElement('div');box.className='err-box';
      const t=document.createElement('div');t.className='failed';t.textContent='生成失败：'+m.error;
      box.appendChild(t);
      const row=document.createElement('div');row.className='row';
      const again=document.createElement('button');again.type='button';again.className='retry';again.textContent='重试';
      row.appendChild(again);box.appendChild(row);bubble.appendChild(box);
    }
    else{
      if(m.thinking)bubble.appendChild(thinkBlock(m.thinking,false,'思考过程（'+m.thinking.length+' 字）',m.node));
      else if(m.thinking_chars)bubble.appendChild(thinkBlock('',false,'思考过程（'+m.thinking_chars+' 字）',m.node));
      const body=document.createElement('div');body.className='md';body.innerHTML=md(m.text);bubble.appendChild(body);
      if(m.stopped){
        const note=document.createElement('div');note.className='stop-note';note.textContent='已停止生成';
        bubble.appendChild(note);
      }
      const chips=[];
      if(m.route==='local')chips.push('本地 · '+(m.model||'qwen'));
      else if(m.mode==='direct'||m.route==='direct')chips.push('云端直连 · '+(m.model||m.worker||''));
      else if(m.route==='cloud')chips.push('云端 · '+(m.model||m.worker||''));
      else if(m.model)chips.push(m.model);
      if(m.saved_chars)chips.push('省 '+m.saved_chars+' 字上下文');
      (m.lenses||[]).forEach(k=>chips.push(state.names[k]||k));
      if(chips.length){
        const row2=document.createElement('div');row2.className='lens-row';
        chips.forEach(label=>{const c=document.createElement('span');c.className='lens-chip';c.textContent=label;row2.appendChild(c);});
        bubble.appendChild(row2);
      }
      if(i===lastAnswer&&m.node){
        const tools=document.createElement('div');tools.className='ans-tools';
        const regen=document.createElement('button');regen.type='button';
        regen.className='regen';regen.dataset.node=m.node;regen.textContent='重新生成';
        tools.appendChild(regen);bubble.appendChild(tools);
      }
    }
    if(m.role==='user'&&m.node)row.dataset.node=m.node;
    else if(m.role==='assistant'&&m.node)row.dataset.ansnode=m.node;
    row.appendChild(av);row.appendChild(bubble);box.appendChild(row);
  });
  if(end<state.messages.length){
    const rest=state.messages.length-end;
    const more=document.createElement('button');more.type='button';more.className='load-more';
    more.textContent='加载更新的 '+Math.min(150,rest)+' 条';
    more.onclick=()=>{state.winEnd=Math.min(state.messages.length,end+150);renderMessages(true);};
    box.appendChild(more);
  }
  if(keep)scroll.scrollTop=prevTop+(scroll.scrollHeight-prevHeight);
  else scroll.scrollTop=scroll.scrollHeight;
  $('toLatest').classList.remove('show');
  if(state.find.open&&!state.find.dirty&&state.find.q)paintFind();
}

function groupOf(s){
  const d=new Date(String(s.date||'').replace(' ','T'));const t=new Date();t.setHours(0,0,0,0);
  if(d>=t)return '今天';
  const y=new Date(t);y.setDate(y.getDate()-1);
  if(d>=y)return '昨天';
  if(d>=new Date(t.getTime()-6*86400000))return '近 7 天';
  return '更早';
}
function closeMenus(){document.querySelectorAll('.session-row.open').forEach(r=>r.classList.remove('open'));}
function renderSessions(){
  const q=$('search').value.trim().toLowerCase(), box=$('sessions');box.innerHTML='';
  const rows=state.sessions.filter(s=>!q||((s.title||'')+' '+(s.preview||'')+' '+s.id).toLowerCase().includes(q));
  if(!rows.length){box.innerHTML=q?'':'<div class="group">还没有历史对话</div>';return;}
  let last='';
  rows.forEach(s=>{
    const g=groupOf(s);
    if(g!==last){const h=document.createElement('div');h.className='group';h.textContent=g;box.appendChild(h);last=g;}
    const wrap=document.createElement('div');wrap.className='session-row';wrap.dataset.id=s.id;
    const b=document.createElement('button');b.className='session'+(s.id===state.current?' active':'');
    b.dataset.id=s.id;
    b.innerHTML='<div class="t">'+esc(s.title||'新对话')+'</div><div class="m">'+esc((s.date||'').replace('T',' ').slice(5,16))+' · '+s.turns+' 轮</div>';
    const more=document.createElement('button');more.className='more';more.dataset.id=s.id;
    more.textContent='···';more.title='管理对话';
    const menu=document.createElement('div');menu.className='menu';
    menu.innerHTML='<button type="button" data-act="rename" data-id="'+s.id+'">重命名</button>'+
                   '<button type="button" data-act="export-md" data-id="'+s.id+'">导出 Markdown</button>'+
                   '<button type="button" data-act="export-json" data-id="'+s.id+'">导出 JSON</button>'+
                   '<button type="button" class="danger" data-act="delete" data-id="'+s.id+'">删除</button>';
    wrap.appendChild(b);wrap.appendChild(more);wrap.appendChild(menu);box.appendChild(wrap);
  });
}
function hitMarkup(h){
  const snippet=esc(h.snippet||'').replace(/\u0001/g,'<mark>').replace(/\u0002/g,'</mark>');
  return '<div class="ht">'+esc(h.title||'新对话')+'</div>'+
    '<div class="hs">'+snippet+'</div>'+
    '<div class="hm">'+(h.role==='user'?'你':'AI')+' · 第 '+esc(String(h.turn||'-'))+' 轮 · '+
    esc((h.ts||'').replace('T',' ').slice(5,16))+'</div>';
}
function renderHits(){
  const q=$('search').value.trim(), box=$('hits');
  if(!q){box.innerHTML='';box.style.display='none';return;}
  box.style.display='block';
  const head='<div class="hd"><span>聊天内容</span><span>'+(state.hitTotal?state.hitTotal+' 条':'')+'</span></div>';
  if(!state.hits.length){box.innerHTML=head+'<div class="hempty">没有匹配的消息</div>';return;}
  box.innerHTML=head+state.hits.map(h=>'<button type="button" class="hit" data-session="'+esc(h.session)+'" data-node="'+esc(h.node||'')+'" data-role="'+esc(h.role||'')+'">'+hitMarkup(h)+'</button>').join('');
}
async function runSearch(q){
  const seq=++state.hitSeq;
  try{
    const r=await fetch('/search?q='+encodeURIComponent(q)+'&limit=30');
    const d=await r.json();
    if(seq!==state.hitSeq)return;
    if(!r.ok||d.error)throw new Error(d.error||'搜索失败');
    state.hits=d.results||[];state.hitTotal=d.total||0;renderHits();
  }catch(err){
    if(seq!==state.hitSeq)return;
    state.hits=[];state.hitTotal=0;renderHits();
  }
}
function onSearchInput(){
  renderSessions();
  const q=$('search').value.trim();
  clearTimeout(state.searchTimer);++state.hitSeq;
  if(!q){state.hits=[];state.hitTotal=0;renderHits();return;}
  state.searchTimer=setTimeout(()=>runSearch(q),260);
}
async function openHit(sid,node,role){
  if(state.busy||!sid)return;
  if(state.current!==sid)await select(sid,true);
  if(node)await jumpToNode(node,role);
}
function download(url){
  const a=document.createElement('a');a.href=url;a.download='';
  document.body.appendChild(a);a.click();a.remove();
}
async function saveRename(id,title){
  const t=String(title||'').trim();
  if(!t){renderSessions();return;}
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(id)+'/title',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t})});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'重命名失败');
    const s=state.sessions.find(x=>x.id===id);if(s)s.title=d.title;
  }catch(err){alert('重命名失败：'+err.message);}
  renderSessions();setTitle();
}
function beginRename(id){
  const row=document.querySelector('.session-row[data-id="'+id+'"]');
  const t=row&&row.querySelector('.t');if(!t)return;
  const item=state.sessions.find(s=>s.id===id);
  const input=document.createElement('input');input.className='rename-input';
  input.value=item?(item.title||''):t.textContent;
  t.replaceWith(input);input.focus();input.select();
  let done=false;
  const finish=save=>{
    if(done)return;done=true;
    if(save)saveRename(id,input.value);else renderSessions();
  };
  input.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();finish(true);}
    else if(e.key==='Escape'){e.preventDefault();finish(false);}
    e.stopPropagation();
  });
  input.addEventListener('blur',()=>finish(true));
  input.addEventListener('click',e=>e.stopPropagation());
}
async function deleteSession(id){
  if(!confirm('确定删除这个对话？删除后无法恢复。'))return;
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(id),{method:'DELETE'});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'删除失败');
    await loadSessions();
    if(state.current===id)newChat(false);
  }catch(err){alert('删除失败：'+err.message);}
}
function setTitle(){
  const row=state.sessions.find(s=>s.id===state.current);
  const first=state.messages.find(m=>m.role==='user');
  $('topTitle').textContent=(row&&row.title)||(first&&first.text.slice(0,28))||'新对话';
}
function setHash(id){
  const next=id?'#/c/'+encodeURIComponent(id):'#new';
  if(location.hash!==next)history.pushState(null,'',next);
}
function readHash(){
  const h=decodeURIComponent(location.hash||'');
  return h.startsWith('#/c/')?h.slice(4):null;
}
async function loadSessions(){
  const r=await fetch('/sessions');const d=await r.json();
  state.sessions=d.sessions||[];renderSessions();setTitle();
}
async function select(id,push){
  if(push)setHash(id);
  closeFind();
  state.current=id;state.messages=[];state.tree=null;resetWin();const seq=++state.seq;
  renderSessions();setTitle();renderMessages();
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(id)+'/messages');
    const d=await r.json();
    if(seq!==state.seq)return;
    if(!r.ok)throw new Error(d.error||'读取失败');
    state.messages=d.messages||[];state.tree=d.tree||null;renderMessages();setTitle();
  }catch(err){state.messages=[{role:'assistant',text:'读取历史失败：'+err.message}];renderMessages();}
}
function newChat(push){
  ++state.seq;if(push)setHash(null);
  closeFind();
  state.current=null;state.messages=[];state.tree=null;resetWin();renderSessions();setTitle();renderMessages();$('q').focus();
}
function openFromHash(){
  const id=readHash();
  if(!id)return newChat(false);
  if(state.sessions.some(s=>s.id===id))return select(id,false);
  select(id,false);
}
function closeModal(id){$(id).classList.remove('show');}
async function loadTree(){
  if(!state.current){state.tree=null;return null;}
  try{
    const tip=tipNode();
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/tree'+
      (tip?'?node='+encodeURIComponent(tip):''));
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'读取分支失败');
    state.tree=d.tree||null;return state.tree;
  }catch(err){alert('读取分支失败：'+err.message);return null;}
}
function renderTree(){
  const nodes=(state.tree&&state.tree.nodes)||[];
  const by={};nodes.forEach(n=>{by[n.id]=n;});
  const box=$('treeBox'), stat=$('treeStat');
  if(!nodes.length){
    box.innerHTML='<div class="group">还没有问答</div>';
    if(stat)stat.textContent='';
    state.treePos=null;
    return;
  }
  // 主链居中：兄弟里把当前分支摆到中间，其余左右交替，主干才不会一直歪向一侧
  const order=(kids,depth)=>{
    if(kids.length<2)return kids;
    const at=kids.findIndex(k=>k.in_path);
    if(at<0)return kids;
    const rest=kids.slice(), pick=rest.splice(at,1)[0];
    // 只有一个兄弟分支时按层左右交替，连续几层才不会全挂在同一侧
    if(rest.length===1)return depth%2 ? [pick].concat(rest) : rest.concat([pick]);
    const left=[], right=[];
    rest.forEach((k,i)=>(i%2?right:left).push(k));
    return left.concat([pick],right);
  };
  const ROOT=42, PAD=20;
  const mainSet=new Set((state.tree&&state.tree.main_path)||[]);
  const roots=nodes.filter(n=>!n.parent||!by[n.parent]);
  const seen=new Set();
  // 先量深度与叶子数：深链大会话按可用空间压缩层距与列距，否则会画成上万像素的长条
  let depthMax=0, leafCount=0;
  const probe=(n,d)=>{
    if(seen.has(n.id))return;
    seen.add(n.id);
    if(d>depthMax)depthMax=d;
    const kids=(n.children||[]).filter(id=>by[id]).filter(k=>!seen.has(k));
    if(!kids.length){leafCount++;return;}
    kids.forEach(id=>probe(by[id],d+1));
  };
  roots.forEach(r=>probe(r,0));
  nodes.forEach(n=>{if(!seen.has(n.id))probe(n,0);});
  const LV=Math.min(34,Math.max(13,Math.round(5200/Math.max(depthMax,1))));
  const GAP=Math.min(26,Math.max(11,Math.round(4000/Math.max(leafCount,1))));
  const HIT=Math.min(11,Math.max(5.5,GAP/2));
  const DR=GAP<14?4:4.5;
  const pos={};seen.clear();
  let cursor=PAD;
  // 后序定横坐标：叶子按顺序占位，父节点落在首末子中点，单链自然成为一条竖线
  const place=(n,depth)=>{
    if(seen.has(n.id))return null;
    seen.add(n.id);
    const kids=order((n.children||[]).map(id=>by[id]).filter(k=>k&&!seen.has(k.id)),depth);
    let x=cursor;
    if(kids.length){
      const xs=kids.map(k=>place(k,depth+1)).filter(v=>v!==null);
      if(xs.length)x=(xs[0]+xs[xs.length-1])/2;
      else cursor+=GAP;
    }else{
      cursor+=GAP;
    }
    pos[n.id]={x:x,y:PAD+depth*LV};
    return x;
  };
  roots.forEach((r,i)=>{if(i)cursor+=ROOT;place(r,0);});
  // parent 已失效的孤立节点也要画出来，否则整段分支会凭空消失
  nodes.forEach(n=>{if(!seen.has(n.id)){cursor+=ROOT;place(n,0);}});

  const f=v=>Math.round(v*10)/10;
  const width=Math.ceil(cursor+PAD), height=PAD*2+depthMax*LV+12;
  const edges=[], dots=[];
  // 只画点与连线：根在上，子节点向下展开，正文只进 title 提示
  nodes.forEach(n=>{
    const p=pos[n.id]; if(!p)return;
    (n.children||[]).forEach(id=>{
      const c=pos[id], kid=by[id]; if(!c)return;
      const px=f(p.x), py=f(p.y), cx=f(c.x), cy=f(c.y);
      let d;
      if(Math.abs(cx-px)<1){
        d='M'+px+' '+py+'L'+cx+' '+cy;
      }else{
        const my=f((p.y+c.y)/2), dir=cx>px?1:-1;
        const r=Math.max(0,Math.min(6,Math.abs(cx-px)/2,my-py,cy-my));
        d=r<0.6
          ? 'M'+px+' '+py+'L'+px+' '+my+'L'+cx+' '+my+'L'+cx+' '+cy
          : 'M'+px+' '+py+'L'+px+' '+(my-r)+'Q'+px+' '+my+' '+(px+dir*r)+' '+my+
            'L'+(cx-dir*r)+' '+my+'Q'+cx+' '+my+' '+cx+' '+(my+r)+'L'+cx+' '+cy;
      }
      const on=!!(n.in_path&&kid&&kid.in_path);
      const onMain=mainSet.has(n.id)&&mainSet.has(id);
      edges.push('<path class="tm-edge'+(on?' on':(onMain?' main':''))+'" d="'+d+'"/>');
    });
  });
  nodes.forEach(n=>{
    const p=pos[n.id]; if(!p)return;
    const r=n.active?DR+2:((n.children||[]).length>1?DR+1:DR);
    const x=f(p.x), y=f(p.y);
    const label=esc(String(n.text||'（空问题）').replace(/\s+/g,' ').slice(0,80));
    dots.push('<g class="tm-node'+(n.in_path?' on':'')+(n.active?' cur':'')+(mainSet.has(n.id)?' main':'')+'" data-node="'+esc(n.id)+'">'+
      '<title>'+label+'</title>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+HIT+'" fill="transparent"/>'+
      (n.active?'<circle class="halo" cx="'+x+'" cy="'+y+'" r="'+(DR+4)+'"/>':'')+
      '<circle class="dot" cx="'+x+'" cy="'+y+'" r="'+r+'"/>'+
      '</g>');
  });
  box.innerHTML='<div class="tree-map"><svg xmlns="http://www.w3.org/2000/svg" width="'+width+'" height="'+height+
    '" viewBox="0 0 '+width+' '+height+'" role="img" aria-label="对话分支树">'+
    edges.join('')+dots.join('')+'</svg></div>';
  // 窄树居中，宽树左对齐（居中会让溢出部分滚不到）
  box.firstChild.classList.toggle('narrow', width<box.clientWidth-8);
  const act=nodes.find(n=>n.active);
  state.treePos=(act&&pos[act.id])?pos[act.id]:null;
  const forks=nodes.filter(n=>(n.children||[]).length>1).length;
  if(stat)stat.textContent='共 '+nodes.length+' 个问题'+(forks?' · '+forks+' 处分叉':'');
}
async function openTree(){
  if(state.busy)return;
  if(!state.current){alert('当前还没有对话');return;}
  await loadTree();
  // 大会话有一千多个节点，先把弹窗和提示画出来，再渲染整棵树，避免点击后没有反馈
  $('treeBox').innerHTML='<div class="group">正在画分支…</div>';
  $('treeModal').classList.add('show');
  await new Promise(r=>requestAnimationFrame(()=>r()));
  renderTree();
  const box=$('treeBox'), at=state.treePos;
  if(at){
    box.scrollLeft=Math.max(0,at.x-box.clientWidth/2);
    box.scrollTop=Math.max(0,at.y-box.clientHeight/2);
  }
}

function revealNode(node,role){
  const pick=wanted=>{
    for(let i=state.messages.length-1;i>=0;i--){
      const m=state.messages[i];
      if(m.node===node&&m.role===wanted)return i;
    }
    return -1;
  };
  let idx=pick(role==='assistant'?'assistant':'user');
  if(idx<0)idx=pick('user');
  if(idx<0)idx=pick('assistant');
  if(idx<0)return;
  const fromEnd=state.messages.length-idx;
  state.winFrom=null;state.winEnd=null;
  if(fromEnd>state.win)state.win=fromEnd+20;
}
// 界面当前显示的那条链的末端：跳转、删除、提问都以它为准，主分支不参与
function tipNode(){
  for(let i=state.messages.length-1;i>=0;i--){
    const m=state.messages[i];
    if(m.role==='user'&&m.node)return m.node;
  }
  return null;
}
// 主分支标记落在当前这条链路上时，菜单项变成「取消主分支」
function pinnedHere(){
  const t=state.tree||{};
  return !!(t.main&&(t.path||[]).indexOf(t.main)>=0);
}
function mainLabel(){return pinnedHere()?'取消主分支':'设为主分支';}
let noteTimer=null;
function note(text){
  const el=$('note');if(!el)return;
  el.textContent=text;el.classList.add('show');
  clearTimeout(noteTimer);
  noteTimer=setTimeout(()=>el.classList.remove('show'),2400);
}
async function setMain(node){
  if(state.busy||!state.current)return;
  const tree=state.tree||{};
  // 已在这条链上就取消；否则钉到这条链的末端——游标只记分叉点，只有末端能唯一确定一条链
  const off=pinnedHere();
  const target=off?null:(tree.active||node);
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/main',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({node:target,tip:tipNode()})});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'设置失败');
    if(d.tree)state.tree=d.tree;
    renderMessages(true);
    note(off?'已取消主分支，打开这个对话跟随最近的分支'
           :'已设为主分支，以后打开这个对话默认停在这条链路');
  }catch(err){alert('设置主分支失败：'+err.message);}
}
// ── 设置：端点、模型与 API Key 在页面里改，保存后写入 config.json 并立即生效
function settingsProfile(name,data){
  const d=data||state.settings||{};
  return (d.profiles||[]).find(p=>p&&p.name===name)||null;
}
function setGroupEnabled(name,on){
  const map={cloud:['setCloudUrl','setCloudModel','setCloudKey','setCloudThink'],
             local:['setLocalUrl','setLocalModel']};
  (map[name]||[]).forEach(id=>{const el=$(id);if(el)el.disabled=!on;});
}
function paintSettingsMode(data){
  const local=settingsProfile('local',data);
  if(!local&&state.settingsMode==='hybrid')state.settingsMode='direct';
  document.querySelectorAll('#setMode button').forEach(b=>{
    b.classList.toggle('active',b.dataset.mode===state.settingsMode);
    if(b.dataset.mode==='hybrid')b.disabled=!local;
  });
  $('setModeWarn').textContent=local?''
    :'配置里没有 local 端点，暂时只能用「直接云端」；想用本地前置需要在 config.json 里补上 local。';
}
function fillSettings(d){
  const cloud=settingsProfile('cloud',d), local=settingsProfile('local',d);
  $('setCloudUrl').value=cloud?cloud.base_url:'';
  $('setCloudModel').value=cloud?cloud.model:'';
  $('setCloudKey').value='';
  $('setCloudKey').placeholder=!cloud?'（配置里没有 cloud 端点）'
    :cloud.has_key?('已保存（'+cloud.key_hint+'），留空不修改')
    :cloud.key_env?('未设置：可填 sk-… 或设置环境变量 '+cloud.key_env):'sk-…';
  $('setCloudThink').checked=!!(cloud&&cloud.thinking);
  $('setLocalUrl').value=local?local.base_url:'';
  $('setLocalModel').value=local?local.model:'';
  state.settingsMode=(d.hybrid&&d.hybrid.enabled)?'hybrid':'direct';
  setGroupEnabled('cloud',!!cloud);
  setGroupEnabled('local',!!local);
  paintSettingsMode(d);
  $('setHint').textContent=d.config_path
    ?'保存后写入 '+d.config_path+'，下一条消息生效。API Key 只存在本机。':'';
  const t=$('setTest');t.textContent='';t.className='';
}
async function openSettings(){
  try{
    const r=await fetch('/settings');
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'读取失败');
    state.settings=d;
    fillSettings(d);
    $('setModal').classList.add('show');
  }catch(err){alert('读取设置失败：'+err.message);}
}
async function saveSettings(){
  const profiles={};
  const cloud=settingsProfile('cloud'), local=settingsProfile('local');
  if(cloud){
    profiles.cloud={base_url:$('setCloudUrl').value.trim(),
                    model:$('setCloudModel').value.trim(),
                    thinking:$('setCloudThink').checked};
    // 留空表示不改：后端也按「空值不覆盖」处理，避免误清已保存的 key
    const key=$('setCloudKey').value.trim();
    if(key)profiles.cloud.api_key=key;
  }
  if(local){
    profiles.local={base_url:$('setLocalUrl').value.trim(),
                    model:$('setLocalModel').value.trim()};
  }
  const body={profiles:profiles};
  if(state.settings)body.hybrid={enabled:state.settingsMode==='hybrid'};
  const tip=$('setTest');tip.className='';tip.textContent='正在保存…';
  $('setSave').disabled=true;
  try{
    const r=await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'保存失败');
    state.settings=d;
    closeModal('setModal');
    note('已保存，下一条消息按新配置生效');
    await refreshHealth();
  }catch(err){tip.className='bad';tip.textContent='保存失败：'+err.message;}
  finally{$('setSave').disabled=false;}
}
async function testSettings(){
  const tip=$('setTest');tip.className='';tip.textContent='测试中…';
  const body={profile:'cloud',
              base_url:$('setCloudUrl').value.trim(),
              model:$('setCloudModel').value.trim(),
              api_key:$('setCloudKey').value.trim(),
              thinking:$('setCloudThink').checked};
  try{
    const r=await fetch('/settings/test',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||'测试失败');
    if(!d.ok)throw new Error(d.error||'连接失败');
    tip.className='ok';
    tip.textContent='连接成功 · '+d.model+' · '+d.ms+'ms'+
      (d.thinking_chars?' · 思考 '+d.thinking_chars+' 字':'');
  }catch(err){tip.className='bad';tip.textContent='连接失败：'+err.message;}
}
async function jumpToNode(node,role){
  if(state.busy||!state.current||!node)return;
  const seq=++state.seq;
  try{
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/cursor',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({node})});
    const d=await r.json();
    if(seq!==state.seq)return;
    if(!r.ok||d.error)throw new Error(d.error||'切换失败');
    state.messages=d.messages||[];state.tree=d.tree||state.tree;
    syncFind();
    closeModal('treeModal');revealNode(node,role);renderMessages(true);setTitle();
    focusQuestion(node,role);
  }catch(err){alert('切换分支失败：'+err.message);}
}
function focusQuestion(node,role){
  const box=$('thread');
  const user=box.querySelector('.msg.user[data-node="'+node+'"]');
  const answer=box.querySelector('.msg.assistant[data-ansnode="'+node+'"]');
  const row=(role==='assistant'?answer:user)||user||answer;
  if(!row)return;
  const target=row.querySelector('.bubble')||row;
  row.scrollIntoView({block:'center'});
  target.classList.add('q-hit');
  setTimeout(()=>target.classList.remove('q-hit'),1200);
}
// ── 对话内查找：数据先算命中，界面只负责标黄与滚动；窗口外的命中在跳转时扩窗
function findHits(q){
  const needle=q.toLowerCase(), out=[];
  if(!needle)return out;
  state.messages.forEach((m,i)=>{
    const text=String(m.text||'');if(!text)return;
    const low=text.toLowerCase();let at=low.indexOf(needle);
    while(at>=0){out.push({i:i,at:at});at=low.indexOf(needle,at+needle.length);}
  });
  return out;
}
function clearFindMarks(){
  $('thread').querySelectorAll('mark.find').forEach(mk=>{
    const p=mk.parentNode;if(!p)return;
    p.replaceChild(document.createTextNode(mk.textContent),mk);p.normalize();
  });
}
function markIn(root,needle){
  if(!needle)return;
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,null);
  const nodes=[];let node;
  while((node=walker.nextNode())){
    const text=node.nodeValue;if(!text||!text.trim())continue;
    const el=node.parentElement;
    if(el&&el.closest('button,mark,textarea,script,style,.q-foot'))continue;
    if(text.toLowerCase().indexOf(needle)>=0)nodes.push(node);
  }
  nodes.forEach(node=>{
    const text=node.nodeValue,low=text.toLowerCase(),frag=document.createDocumentFragment();
    let at=0,hit;
    while((hit=low.indexOf(needle,at))>=0){
      if(hit>at)frag.appendChild(document.createTextNode(text.slice(at,hit)));
      const mk=document.createElement('mark');mk.className='find';
      mk.textContent=text.slice(hit,hit+needle.length);
      frag.appendChild(mk);at=hit+needle.length;
    }
    if(at<text.length)frag.appendChild(document.createTextNode(text.slice(at)));
    if(node.parentNode)node.parentNode.replaceChild(frag,node);
  });
}
function paintFind(){
  const f=state.find, hits=f.hits, thread=$('thread');
  clearFindMarks();
  $('findCount').textContent=(hits.length?f.cur+1:0)+'/'+hits.length;
  $('findInput').classList.toggle('none',!f.dirty&&!!f.q&&!hits.length);
  if(!f.q||!hits.length)return;
  const needle=f.q.toLowerCase(), start=winStart(), end=winEnd(), rows=thread.children, off=start>0?1:0;
  // 只标窗口内的行：命中总数按数据算，不必为了显示把整段历史塞进 DOM
  state.messages.slice(start,end).forEach((m,i)=>{
    if(m.pending)return;
    if(String(m.text||'').toLowerCase().indexOf(needle)<0)return;
    const row=rows[i+off];if(!row)return;
    const bubble=row.querySelector('.bubble');if(bubble)markIn(bubble,needle);
  });
  const cur=hits[Math.max(f.cur,0)];
  const row=rows[cur.i-start+off];if(!row)return;
  let k=0;
  for(let j=0;j<f.cur;j++)if(hits[j].i===cur.i)k++;
  const marks=row.querySelectorAll('mark.find');
  const mk=marks[k]||marks[marks.length-1];
  if(!mk)return;
  mk.classList.add('on');
  f.painted=true;
  // 只有主动换命中时才滚动，重新渲染（加载更早/更新）不该把视野拽回来
  if(f.scroll){f.scroll=false;mk.scrollIntoView({block:'center'});}
}
// 命中已在窗口内且已铺好标黄时，翻下一处只挪 .on 与视野，不重铺上千个 mark
function paintFindMove(){
  const f=state.find,h=f.hits[f.cur];if(!h)return false;
  const start=winStart(),rows=$('thread').children,off=start>0?1:0;
  const row=rows[h.i-start+off];if(!row)return false;
  let k=0;
  for(let j=0;j<f.cur;j++)if(f.hits[j].i===h.i)k++;
  const marks=row.querySelectorAll('mark.find');
  const mk=marks[k]||marks[marks.length-1];
  if(!mk)return false;
  const prev=$('thread').querySelector('mark.find.on');if(prev)prev.classList.remove('on');
  mk.classList.add('on');
  $('findCount').textContent=(f.cur+1)+'/'+f.hits.length;
  mk.scrollIntoView({block:'center'});
  return true;
}
// 当前命中不在窗口里就把窗口挪到它前后几十条，别为了看一眼重绘整段历史
function jumpFindCur(){
  const f=state.find,h=f.hits[f.cur];
  if(!h)return;
  const start=winStart(), end=winEnd();
  f.scroll=true;
  if(h.i<start||h.i>=end){
    state.winFrom=Math.max(0,h.i-4);
    state.winEnd=Math.min(state.messages.length,h.i+40);
    renderMessages(true);
  }else paintFind();
}
// 切换分支、删除问答后消息换了，命中表跟着重算，序号越界就归零
function syncFind(){
  const f=state.find;
  if(!f.open||f.dirty||!f.q)return;
  f.hits=findHits(f.q);
  if(f.cur>=f.hits.length)f.cur=f.hits.length?0:-1;
}
// 打字阶段只标记「还没查」，不跳也不标黄，避免边打边跳
function markFindDirty(){
  const f=state.find;
  f.dirty=true;f.hits=[];f.cur=-1;f.painted=false;
  clearFindMarks();
  $('findCount').textContent='0/0';
  $('findInput').classList.remove('none');
}
// step 正负表示相对当前命中前后翻；查询词变了就先定位到离视野最近的一条
function findNav(step){
  const f=state.find, q=$('findInput').value.trim();
  if(!q){
    f.q='';f.dirty=false;f.hits=[];f.cur=-1;f.painted=false;
    clearFindMarks();$('findCount').textContent='0/0';
    $('findInput').classList.remove('none');return;
  }
  if(f.dirty||q!==f.q){
    f.q=q;f.hits=findHits(q);f.dirty=false;f.cur=-1;
    if(!f.hits.length){paintFind();return;}
    // 从离当前视图最近的一条开始，往上翻更符合「刚说过什么」的直觉
    const end=winEnd();
    let pick=f.hits.length-1;
    while(pick>0&&f.hits[pick].i>=end)pick--;
    f.cur=pick;
    jumpFindCur();return;
  }
  if(!step||!f.hits.length)return;
  const n=f.hits.length;
  f.cur=((f.cur<0?0:f.cur)+step+n)%n;
  if(f.painted&&paintFindMove())return;
  jumpFindCur();
}
function openFind(){
  state.find.open=true;$('findbar').classList.add('show');
  const input=$('findInput');
  // 选中一段文字再按 Ctrl+F，直接拿它当查询词
  const sel=String((window.getSelection&&window.getSelection().toString())||'').trim();
  if(sel&&sel.length<=60&&sel.indexOf('\n')<0&&!input.value){input.value=sel;markFindDirty();}
  input.focus();input.select();
}
function closeFind(){
  const f=state.find;
  f.open=false;f.q='';f.hits=[];f.cur=-1;f.scroll=false;f.dirty=false;f.painted=false;
  $('findbar').classList.remove('show');
  $('findInput').value='';$('findInput').classList.remove('none');
  $('findCount').textContent='0/0';
  clearFindMarks();
}
function beginEdit(node){
  const m=state.messages.find(x=>x.role==='user'&&x.node===node);
  if(!m){alert('找不到这条问题');return;}
  state.editNode=node;$('editText').value=m.text;$('editModal').classList.add('show');$('editText').focus();
}
async function submitEdit(){
  const text=$('editText').value.trim(), fork=state.editNode;
  if(!text||!fork)return;
  closeModal('editModal');state.editNode=null;
  await send(text,{fork});
}
async function deleteTurn(node){
  if(state.busy)return;
  if(!confirm('删除这条问题、AI 回复及其下游分支？此操作不可恢复。'))return;
  const seq=++state.seq;
  try{
    const tip=tipNode();
    const r=await fetch('/sessions/'+encodeURIComponent(state.current)+'/nodes/'+encodeURIComponent(node)+
      (tip?'?tip='+encodeURIComponent(tip):''),{method:'DELETE'});
    const d=await r.json();
    if(seq!==state.seq)return;
    if(!r.ok||d.error)throw new Error(d.error||'删除失败');
    state.messages=d.messages||[];state.tree=d.tree||null;syncFind();
    await loadSessions();await loadTree();renderMessages();setTitle();
  }catch(err){alert('删除失败：'+err.message);}
}
async function ensureSession(){
  if(state.current)return state.current;
  const r=await fetch('/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const d=await r.json();
  if(!r.ok||d.error)throw new Error(d.error||'建会话失败');
  state.current=d.session;setHash(state.current);await loadSessions();return state.current;
}
function autoGrow(){const el=$('q');el.style.height='auto';el.style.height=Math.min(el.scrollHeight,160)+'px';}
function setSendState(busy){
  const b=$('send');
  b.disabled=false;
  b.classList.toggle('stop',busy);
  b.textContent=busy?'■':'➤';
  b.title=busy?'停止生成':'发送（Enter）';
}
async function stopGenerating(){
  const sid=state.current;
  if(!sid)return;
  $('status').textContent='正在停止…';
  try{
    await fetch('/sessions/'+encodeURIComponent(sid)+'/stop',
      {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  }catch(e){}
  if(state.ctrl)state.ctrl.abort();
}
async function settleStop(sid,pending,text){
  const partial=pending.text||'';
  for(let i=0;i<10;i++){
    await new Promise(r=>setTimeout(r,400));
    try{
      const r=await fetch('/sessions/'+encodeURIComponent(sid)+'/messages');
      const d=await r.json();
      if(!r.ok||!d.messages)continue;
      const msgs=d.messages||[];
      let lastUser=-1;msgs.forEach((m,idx)=>{if(m.role==='user')lastUser=idx;});
      const answered=lastUser>=0&&msgs.slice(lastUser+1).some(m=>m.role==='assistant');
      const sameQ=lastUser>=0&&(msgs[lastUser].text||'').trim()===text.trim();
      if(answered||!sameQ){
        // 已落盘，或本轮节点已被服务端清掉：以服务端为准
        state.messages=msgs;await loadTree();renderMessages(false);scrollBottom(true);return;
      }
    }catch(e){}
  }
  // 服务端迟迟未落盘：本地保留已生成文本，节点信息等下次进会话再同步
  const i=state.messages.indexOf(pending);
  if(i>=0)state.messages.splice(i,1);
  if(partial){
    state.messages.push({role:'assistant',text:partial,stopped:true});
  }else{
    let at=-1;
    state.messages.forEach((x,idx)=>{if(x.role==='user'&&(x.text||'').trim()===text.trim())at=idx;});
    if(at>=0)state.messages.splice(at,1);
  }
  renderMessages(false);
}
async function send(override,opts){
  if(state.busy)return;
  opts=opts||{};
  const text=String(override==null?$('q').value:override).trim();
  if(!text)return;
  if(override==null){$('q').value='';autoGrow();}
  state.messages=state.messages.filter(m=>!m.error);state.retry=null;
  state.busy=true;setSendState(true);
  const ctrl=new AbortController();state.ctrl=ctrl;
  $('status').textContent='思考中…';
  const started=Date.now();
  const pending={role:'assistant',text:'',thinking:'',pending:true,started};
  const userMsg={role:'user',text};
  if(opts.fork){
    const at=state.messages.findIndex(m=>m.role==='user'&&m.node===opts.fork);
    if(at>=0)state.messages=state.messages.slice(0,at);
  }else if(opts.parent){
    const at=state.messages.findIndex(m=>m.role==='user'&&m.node===opts.parent);
    if(at>=0)state.messages=state.messages.slice(0,at+1);
  }
  state.messages.push(userMsg);state.messages.push(pending);
  state.winFrom=null;state.winEnd=null;renderMessages(false);
  const tick=setInterval(()=>{
    const el=$('thread').querySelector('.thinking .secs');
    if(el)el.textContent=((Date.now()-started)/1000).toFixed(0)+'s';
  },1000);
  let sid=state.current;
  // 视图里显示的是哪条链，就把新问题接到哪条链上；主分支只决定打开时落在哪，不改变追加位置
  const tip=tipNode()||((state.tree&&state.tree.active)||null);
  try{
    sid=await ensureSession();
    const body={message:text,session:sid};
    if(opts.fork)body.fork=opts.fork;
    else if(opts.parent)body.parent=opts.parent;
    else if(tip)body.parent=tip;
    const r=await fetch('/inbox/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:ctrl.signal});
    if(!r.ok){let d={};try{d=await r.json();}catch(e){}
      throw new Error(d.error||('HTTP '+r.status));}
    if(!r.body)throw new Error('浏览器不支持流式读取');
    const reader=r.body.getReader(), decoder=new TextDecoder();
    let buffer='', final=null, failed=null;
    const handle=(event,data)=>{
      if(event==='delta'){pending.text+=data.delta||'';paintPending();scrollBottom(false);}
      else if(event==='thinking'){pending.thinking+=data.delta||'';paintPending();}
      else if(event==='preprocess'){$('status').textContent=data.route==='local'?'本地处理…':'云端处理…';}
      else if(event==='tool_start'){$('status').textContent='调用 '+(data.name||'工具')+'…';}
      else if(event==='done')final=data;
      else if(event==='error')failed=data.error||'生成失败';
    };
    while(true){
      const chunk=await reader.read();
      if(chunk.done)break;
      buffer+=decoder.decode(chunk.value,{stream:true});
      let at;
      while((at=buffer.indexOf('\n\n'))>=0){
        const block=buffer.slice(0,at);buffer=buffer.slice(at+2);
        let event='',data='';
        block.split('\n').forEach(line=>{
          if(line.startsWith('event:'))event=line.slice(6).trim();
          else if(line.startsWith('data:'))data+=line.slice(5).trim();
        });
        if(!event||!data)continue;
        try{handle(event,JSON.parse(data));}catch(e){}
      }
    }
    if(failed)throw new Error(failed);
    if(!final)throw new Error('流式响应提前结束');
    const index=state.messages.indexOf(pending);
    if(index>=0)state.messages.splice(index,1);
    if(final.node){userMsg.node=final.node;userMsg.parent=final.parent||opts.parent||null;}
    state.messages.push({role:'assistant',text:final.reply||'',lenses:final.lenses||[],
                         route:final.route,worker:final.worker,model:final.model,
                         thinking:final.thinking||'',saved_chars:final.saved_chars||0,
                         node:final.node||null,parent:final.parent||opts.parent||null,
                         mode:final.mode,stopped:!!final.stopped});
    await loadSessions();await loadTree();renderMessages(false);scrollBottom(true);
  }catch(err){
    const index=state.messages.indexOf(pending);
    if(index>=0)state.messages.splice(index,1);
    if(err&&err.name==='AbortError'){
      await settleStop(sid,pending,text);
    }else{
      const at=state.messages.indexOf(userMsg);
      if(at>=0)state.messages.splice(at,1);
      state.retry={text,opts};
      state.messages.push({role:'assistant',error:(err&&err.message)||String(err)});
      renderMessages(false);
    }
  }finally{
    clearInterval(tick);$('status').textContent='';
    state.busy=false;state.ctrl=null;setSendState(false);$('q').focus();
  }
}

$('send').onclick=()=>{if(state.busy)return stopGenerating();send();};
function regenerate(node){
  if(state.busy)return;
  const at=state.messages.findIndex(m=>m.role==='user'&&m.node===node);
  if(at<0){alert('找不到这条问题');return;}
  send(state.messages[at].text,{fork:node});
}
function retryLast(){
  if(state.busy||!state.retry)return;
  const last=state.retry;
  state.messages=state.messages.filter(m=>!m.error);
  send(last.text,last.opts);
}
$('findBtn').onclick=openFind;
$('findClose').onclick=()=>{closeFind();$('q').focus();};
$('findPrev').onclick=()=>findNav(-1);
$('findNext').onclick=()=>findNav(1);
$('findInput').addEventListener('input',markFindDirty);
$('findInput').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();findNav(e.shiftKey?-1:1);}
  else if(e.key==='ArrowDown'){e.preventDefault();findNav(1);}
  else if(e.key==='ArrowUp'){e.preventDefault();findNav(-1);}
  else if(e.key==='Escape'){e.preventDefault();closeFind();$('q').focus();}
  e.stopPropagation();
});
$('branchBtn').onclick=openTree;
$('treeBox').onclick=e=>{
  const b=e.target.closest('[data-node]');
  if(b&&b.dataset.node)jumpToNode(b.dataset.node);
};
$('editSubmit').onclick=submitEdit;
$('new').onclick=()=>newChat(true);
$('hide').onclick=()=>$('side').classList.add('collapsed');
$('toggle').onclick=()=>$('side').classList.toggle('collapsed');
$('search').oninput=onSearchInput;
$('search').addEventListener('keydown',e=>{
  if(e.key!=='Enter')return;
  e.preventDefault();
  const first=state.hits[0];
  if(first)openHit(first.session,first.node,first.role);
});
$('hits').onclick=e=>{
  const hit=e.target.closest('.hit');if(!hit)return;
  openHit(hit.dataset.session,hit.dataset.node,hit.dataset.role);
};
$('backup').onclick=()=>download('/export');
$('setMode').onclick=e=>{
  const b=e.target.closest('button[data-mode]');if(!b||b.disabled)return;
  state.settingsMode=b.dataset.mode;paintSettingsMode();
};
$('sessions').onclick=e=>{
  const action=e.target.closest('.menu button');
  if(action){
    e.stopPropagation();closeMenus();
    const act=action.dataset.act, id=action.dataset.id;
    if(act==='rename')beginRename(id);
    else if(act==='export-md')download('/sessions/'+encodeURIComponent(id)+'/export?format=md');
    else if(act==='export-json')download('/sessions/'+encodeURIComponent(id)+'/export?format=json');
    else deleteSession(id);
    return;
  }
  const more=e.target.closest('.more');
  if(more){
    e.stopPropagation();
    const row=more.closest('.session-row'), open=row.classList.contains('open');
    closeMenus();if(!open)row.classList.add('open');
    return;
  }
  const b=e.target.closest('.session');
  if(b){closeMenus();select(b.dataset.id,true);}
};
document.addEventListener('click',e=>{
  if(!e.target.closest('.session-row'))closeMenus();
  if(!e.target.closest('.msg-menu')&&!e.target.classList.contains('msg-more'))
    document.querySelectorAll('.msg-menu.open').forEach(m=>m.classList.remove('open'));
  const close=e.target.closest('[data-close]');
  if(close)closeModal(close.dataset.close);
});
$('q').addEventListener('input',autoGrow);
$('q').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send();}});
$('scroll').addEventListener('scroll',()=>{
  const el=$('scroll');
  $('toLatest').classList.toggle('show',el.scrollHeight-el.scrollTop-el.clientHeight>180);
});
$('toLatest').onclick=()=>scrollBottom(true);
$('setBtn').onclick=openSettings;
$('setSave').onclick=saveSettings;
$('setTestBtn').onclick=testSettings;
$('thread').addEventListener('click',e=>{
  const regen=e.target.closest('.regen');
  if(regen){e.stopPropagation();regenerate(regen.dataset.node);return;}
  const again=e.target.closest('.retry');
  if(again){e.stopPropagation();retryLast();return;}
  const nav=e.target.closest('.branch-nav button');
  if(nav){
    e.stopPropagation();
    const holder=nav.closest('.branch-nav');
    jumpToNode(nav.dataset.act==='prev'?holder.dataset.prev:holder.dataset.next);
    return;
  }
  const action=e.target.closest('.msg-menu button');
  if(action){
    e.stopPropagation();
    const node=action.closest('.msg-menu').dataset.node;
    document.querySelectorAll('.msg-menu.open').forEach(m=>m.classList.remove('open'));
    if(action.dataset.act==='edit')beginEdit(node);
    else if(action.dataset.act==='main')setMain(node);
    else deleteTurn(node);
    return;
  }
  const more=e.target.closest('.msg-more');
  if(more){
    e.stopPropagation();
    const menu=more.parentElement.querySelector('.msg-menu');
    const open=menu.classList.contains('open');
    document.querySelectorAll('.msg-menu.open').forEach(m=>m.classList.remove('open'));
    if(!open)menu.classList.add('open');
    return;
  }
  if(!e.target.classList.contains('copy'))return;
  const code=e.target.closest('pre').querySelector('code').innerText;
  navigator.clipboard.writeText(code).then(()=>{
    e.target.textContent='已复制';setTimeout(()=>{e.target.textContent='复制';},1400);
  }).catch(()=>{e.target.textContent='复制失败';});
});
window.addEventListener('popstate',openFromHash);
// Ctrl+F 只在对话已打开时接管，其余情况仍交给浏览器
document.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!e.shiftKey&&e.key.toLowerCase()==='f'){
    if(!state.current||!state.messages.length||document.querySelector('.modal.show'))return;
    e.preventDefault();openFind();return;
  }
  if(e.key==='Escape'&&state.find.open&&!document.querySelector('.modal.show'))closeFind();
},true);

function applyHealth(health){
  if(!health)return;
  if(health.profile)$('model').textContent=(health.hybrid?'本地路由 → ':'')+(health.profile.model||'');
}
async function refreshHealth(){
  applyHealth(await fetch('/health').then(r=>r.json()).catch(()=>null));
}

(async()=>{
  const healthP=fetch('/health').then(r=>r.json()).catch(()=>null);
  const namesP=fetch('/lens-names').then(r=>r.json()).catch(()=>null);
  const id=readHash();
  // 会话列表与历史同时开始拉取，健康检查和镜头名不挡首屏
  const chatP=id?select(id,false):Promise.resolve(newChat(false));
  const listP=loadSessions();
  const [health,names]=await Promise.all([healthP,namesP]);
  applyHealth(health);
  // 新用户第一次打开：端点还没配好，直接把设置面板弹出来
  if(health&&health.needs_setup)openSettings();
  if(names){
    state.names=names.names||{};
    if(state.messages.some(m=>(m.lenses||[]).length))renderMessages(true);
  }
  await Promise.all([listP,chatP]);
})();
</script>
</body>
</html>
"""
