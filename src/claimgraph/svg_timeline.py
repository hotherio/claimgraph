"""Compact, dependency-free SVG timeline export.

The lean counterpart to the Cytoscape ``export`` viewer: a self-contained HTML figure (a few KB, no
external assets) with a play / slider that animates each claim's status over the commit history. It
auto-lays-out the claim DAG (a layered, topological placement) and reads the per-commit status from the
replay ``frames``, so a refutation, a silent ``sorryAx`` regression, and the resulting blast radius all
show up as the slider moves. This is the format used in the CKC write-ups, produced from the graph
rather than authored by hand.

Public entry point: :func:`render(graph, frames, title=None, hint=None)` -> an HTML string.
"""
from __future__ import annotations

import html
import json
import re
from collections import deque

from .model import DEPENDENCY_RELATIONS, status_key

# status -> a visual class understood by the embedded renderer.
_MC = "math.machine-checked"
_AX = "math.axiomatised"
_OPEN = "math.open"
_PROVED = "math.proved-informal"
_CONJ = "math.conjectured"
_BROKEN = "math.disproved"

_BOX_HW, _BOX_HH = 96, 23  # half-width / half-height of a node box
_COL_W, _ROW_H, _MARGIN = 240, 120, 96


def _dep_pairs(graph) -> list[tuple[str, str]]:
    """(dependent, dependency) pairs: ``source`` rests on ``target`` (Depends-On / Assumes)."""
    return [
        (e.source, e.target)
        for e in graph.edges
        if e.relation in DEPENDENCY_RELATIONS and e.source in graph.nodes and e.target in graph.nodes
    ]


def _layered_layout(node_ids: list[str], deps: list[tuple[str, str]]):
    """Place nodes on a grid in topological order, bounding the aspect ratio for any graph shape.

    A pure layered layout is lopsided for the common shapes (a shallow graph with many independent
    foundations is one tall column; a linear chain is one wide row). A grid in dependency order keeps a
    roughly 1.6:1 figure either way: sources fill the top rows, results the bottom, so edges run mostly
    downward. Returns ``({id: (x, y)}, hero_id, viewbox_w, viewbox_h)``; the hero is the most
    load-bearing final result (a sink with the largest dependency closure).
    """
    deps_of: dict[str, list[str]] = {n: [] for n in node_ids}     # n rests on these
    consumers: dict[str, list[str]] = {n: [] for n in node_ids}   # these rest on n
    for dependent, dependency in deps:
        if dependent in deps_of and dependency in deps_of:
            deps_of[dependent].append(dependency)
            consumers[dependency].append(dependent)

    # longest-path depth (foundations -> 0) via Kahn's algorithm: iterative and O(V+E), so it is safe on
    # the deep dependency chains where a recursive walk would overflow the stack. Nodes in a cycle (which
    # a Depends-On graph should not contain) keep depth 0.
    indeg = {x: len(deps_of.get(x, [])) for x in node_ids}
    depth = {x: 0 for x in node_ids}
    queue = deque(x for x in node_ids if indeg[x] == 0)
    while queue:
        cur = queue.popleft()
        for dependent in consumers.get(cur, []):
            depth[dependent] = max(depth[dependent], depth[cur] + 1)
            indeg[dependent] -= 1
            if indeg[dependent] == 0:
                queue.append(dependent)
    order = sorted(node_ids, key=lambda x: (depth[x], x))  # foundations first, then their dependents

    n = len(order) or 1
    ncols = max(1, round((n * 1.6) ** 0.5))
    pos: dict[str, tuple[float, float]] = {}
    for i, nid in enumerate(order):
        r, c = divmod(i, ncols)
        pos[nid] = (_MARGIN + c * _COL_W, _MARGIN + r * _ROW_H)
    nrows = (n + ncols - 1) // ncols

    def _closure_size(node):
        seen, stack = set(), list(deps_of.get(node, []))
        while stack:
            m = stack.pop()
            if m not in seen:
                seen.add(m)
                stack.extend(deps_of.get(m, []))
        return len(seen)

    sinks = [x for x in node_ids if not consumers.get(x)]
    hero = max(sinks, key=_closure_size) if sinks else None
    if hero is not None and _closure_size(hero) == 0:
        hero = None
    vw = _MARGIN * 2 + (ncols - 1) * _COL_W + _BOX_HW
    vh = _MARGIN * 2 + (nrows - 1) * _ROW_H + _BOX_HH
    return pos, hero, int(vw), int(vh)


def _style_of(entry: dict | None) -> str:
    """Map a node's ``{status, effective_status, in_question}`` snapshot to a visual class."""
    if not entry:
        return "absent"
    s = entry.get("status")
    if s is None:
        return "absent"
    if s == _BROKEN:
        return "ref"
    eff = entry.get("effective_status")
    # blast radius: own status is good, but the dependency closure has degraded (or a dep is broken).
    sound = {_MC, _AX, _PROVED}
    if s in sound and (entry.get("in_question") or (eff is not None and status_key(eff) < status_key(s))):
        return "blast"
    return {
        _CONJ: "conj", _OPEN: "open", _PROVED: "proved", _MC: "checked", _AX: "axiom",
    }.get(s, "open")


# Parse the conventional-commit type badge from a commit subject: the type token (with a trailing `~`)
# plus a breaking `!`, e.g. `axiomatize~`, `refute!`, `formalize`. Returns (label, colour category).
_TYPE_RE = re.compile(r"^\s*([A-Za-z]+~?)(?:\([^)]*\))?(!)?")


def _commit_badge(subject: str | None) -> tuple[str, str]:
    m = _TYPE_RE.match(subject or "")
    if not m:
        return "commit", "other"
    label = m.group(1) + (m.group(2) or "")
    base = m.group(1).rstrip("~").lower()
    if base.startswith("conj"):
        cat = "conj"
    elif base.startswith("axiom"):
        cat = "axiom"
    elif base in ("refute", "retract"):
        cat = "ref"
    elif base in ("formalize", "proof", "prove", "result", "replicate", "experiment", "feat"):
        cat = "form"
    else:
        cat = "other"
    return label, cat


def _downsample(frames: list[dict], cap: int) -> list[dict]:
    """Keep at most ``cap`` evenly-spaced frames, always including the last (final state)."""
    if len(frames) <= cap:
        return frames
    keep = max(1, -(-len(frames) // cap))  # ceil division, so the kept count is bounded by ~cap
    out = [f for i, f in enumerate(frames) if i % keep == 0]
    if out[-1] is not frames[-1]:
        out.append(frames[-1])
    return out


def _steps(frames: list[dict], node_ids: list[str], cap: int) -> list[dict]:
    """One step per (downsampled) frame: the status snapshot plus the commit-log fields (hash, badge)."""
    steps = []
    for k, f in enumerate(_downsample(frames, cap)):
        state = f.get("state") or {}
        snap = {n: _style_of(state.get(n)) for n in node_ids}
        ev = (f.get("event") or "").lower()
        clab, cat = _commit_badge(f.get("subject"))
        steps.append({
            "y": (f.get("date") or "")[:10],
            "hash": ((f.get("hash") or "")[:7] or f"#{k}"),
            "clab": clab, "cat": cat,
            "ref": ev in ("refute", "retract") or cat == "ref",
            "s": f.get("subject") or "",
            "set": snap,
        })
    return steps


# The viewer shell: vanilla JS, inline SVG, no external assets. {DATA} / {TITLE} / {HINT} / {VBOX} /
# {MAX} are filled by render(); the data islands are emitted as JSON the script parses.
_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  .cg-wrap{position:relative;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#2A2927;}
  .cg-legend{display:flex;flex-wrap:wrap;gap:13px;align-items:center;font-size:12px;color:#64748b;margin-bottom:12px;}
  .cg-sw{display:inline-block;width:13px;height:13px;border-radius:3px;vertical-align:-2px;margin-right:5px;border:1px solid rgba(0,0,0,0.15);}
  .cg-controls{display:flex;align-items:center;gap:10px;margin-bottom:6px;}
  .cg-btn{font:600 13px/1 -apple-system,sans-serif;padding:6px 11px;border:1px solid #d7d3ca;background:#f7f5f0;color:#44403c;border-radius:7px;cursor:pointer;}
  .cg-btn:hover{background:#efece5;}
  .cg-slider{flex:1;accent-color:#5b8c6e;}
  .cg-read{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;min-height:22px;margin:4px 0 12px;padding:8px 10px;background:#faf8f4;border:1px solid #ece8df;border-radius:8px;}
  .cg-read.ref{background:#fbf1ef;border-color:#e3bbb4;}
  .cg-year{font-family:"SF Mono",Menlo,monospace;font-size:12px;font-weight:700;color:#57534e;}
  .cg-badge{font-family:"SF Mono",Menlo,monospace;font-size:11px;padding:2px 7px;border-radius:5px;border:1px solid;white-space:nowrap;}
  .b-conj{background:#eef0f3;color:#475569;border-color:#cbd5e1;}
  .b-form{background:#e7f0ea;color:#3f6b51;border-color:#9bc1a8;}
  .b-ref{background:#f6e3e1;color:#8f342d;border-color:#d9a39c;}
  .b-axiom{background:#fbf3e2;color:#92510f;border-color:#d9a86a;}
  .b-other{background:#f1f0ec;color:#6b675f;border-color:#cdc8bd;}
  .cg-subj{font-size:12.5px;color:#44403c;flex:1 1 280px;}
  .cg-svg{width:100%;height:auto;display:block;}
  .cg-svg rect{transition:fill .3s,stroke .3s,opacity .3s;} .cg-svg text{transition:opacity .3s,fill .3s;}
  .cg-edge{fill:none;transition:opacity .3s,stroke .3s;}
  .cg-hint{font-size:12px;color:#94a3b8;margin-top:8px;font-style:italic;}
  .cg-cols{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;}
  .cg-left{flex:1 1 440px;min-width:300px;}
  .cg-log{flex:1 1 340px;min-width:260px;max-height:520px;overflow-y:auto;border:1px solid #ece8df;border-radius:10px;padding:4px;background:#fcfbf8;}
  .cg-row{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:7px;cursor:pointer;border:1px solid transparent;}
  .cg-row:hover{background:#f3f1ec;}
  .cg-row.cur{background:#eef3ec;border-color:#cfe0d3;}
  .cg-dot{width:9px;height:9px;border-radius:50%;border:2px solid #cdc8bd;flex:none;box-sizing:border-box;}
  .cg-hash{font-family:"SF Mono",Menlo,monospace;font-size:11px;color:#94a3b8;flex:none;width:50px;}
  .cg-rb{font-family:"SF Mono",Menlo,monospace;font-size:10.5px;padding:1px 6px;border-radius:5px;border:1px solid;white-space:nowrap;flex:none;}
  .cg-rs{font-size:12px;color:#44403c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
</style></head><body>
<div class="cg-wrap">
  <div class="cg-legend">
    <span><span class="cg-sw" style="background:#f6f5f2;border:1px dashed #cdc8bd"></span>not yet stated</span>
    <span><span class="cg-sw" style="background:#eef0f3;border-color:#94a3b8"></span>conjectured / open</span>
    <span><span class="cg-sw" style="background:#e7f0ea;border-color:#3f6b51"></span>machine-checked</span>
    <span><span class="cg-sw" style="background:#fdf3e2;border:1px dashed #c2722b"></span>blast radius (effective open)</span>
    <span><span class="cg-sw" style="background:#f6e3e1;border-color:#9c3a34"></span>refuted</span>
  </div>
  <div class="cg-controls">
    <button class="cg-btn" id="btnPlay">&#9658; Play</button>
    <button class="cg-btn" id="btnPrev">&#8249;</button>
    <input class="cg-slider" id="slider" type="range" min="0" max="{MAX}" value="{MAX}" step="1">
    <button class="cg-btn" id="btnNext">&#8250;</button>
  </div>
  <div class="cg-cols">
    <div class="cg-left"><svg class="cg-svg" id="g" viewBox="0 0 {VBOX}" preserveAspectRatio="xMidYMid meet"></svg></div>
    <div class="cg-log" id="log" aria-label="Commit history"></div>
  </div>
  <div class="cg-hint">{HINT}</div>
</div>
<script>
var DATA={DATA};
var SVGNS="http://www.w3.org/2000/svg",HW=96,HH=23;
var STYLE={absent:{f:"#f6f5f2",s:"#cdc8bd",o:0.5,d:"4 4",t:""},conj:{f:"#eef0f3",s:"#94a3b8",o:1,d:"",t:"CONJECTURED"},
 open:{f:"#eef0f3",s:"#94a3b8",o:1,d:"",t:"OPEN"},proved:{f:"#eef3ea",s:"#7fae8f",o:1,d:"",t:"PROVED"},
 checked:{f:"#e7f0ea",s:"#3f6b51",o:1,d:"",t:"MACHINE-CHECKED"},axiom:{f:"#fbf3e2",s:"#c2972b",o:1,d:"",t:"AXIOMATISED"},
 blast:{f:"#fdf3e2",s:"#c2722b",o:1,d:"5 3",t:"EFFECTIVE: OPEN"},ref:{f:"#f6e3e1",s:"#9c3a34",o:1,d:"",t:"REFUTED"}};
var TC={conj:"#64748b",open:"#64748b",proved:"#4e7a5e",checked:"#3f6b51",axiom:"#a9791f",blast:"#b5651d",ref:"#a34a43",absent:"#a8a29e"};
var nodes=DATA.nodes,order=DATA.order,edges=DATA.edges,steps=DATA.steps;
var statusAt=steps.map(function(st){return st.set;});
var svg=document.getElementById("g");
function box(cx,cy,ux,uy){var tx=ux===0?1e9:HW/Math.abs(ux),ty=uy===0?1e9:HH/Math.abs(uy),tt=Math.min(tx,ty);return [cx+ux*tt,cy+uy*tt];}
function txt(x,y,s,size,sp,fill){var e=document.createElementNS(SVGNS,"text");e.setAttribute("x",x);e.setAttribute("y",y);
 e.setAttribute("text-anchor","middle");e.setAttribute("font-size",size);e.setAttribute("font-family","'SF Mono',Menlo,monospace");
 if(sp)e.setAttribute("letter-spacing",sp);e.setAttribute("fill",fill);e.textContent=s;svg.appendChild(e);return e;}
var edgeEls=[];
edges.forEach(function(ed){var a=nodes[ed.t],b=nodes[ed.s];  // arrow prereq(t) -> dependent(s)
 var dx=b.x-a.x,dy=b.y-a.y,L=Math.sqrt(dx*dx+dy*dy)||1,ux=dx/L,uy=dy/L;
 var p0=box(a.x,a.y,ux,uy),p1=box(b.x,b.y,-ux,-uy),sx=p0[0],sy=p0[1],ex=p1[0],ey=p1[1];
 var p=document.createElementNS(SVGNS,"path");p.setAttribute("d","M "+sx+" "+sy+" L "+ex+" "+ey);
 p.setAttribute("class","cg-edge");p.setAttribute("stroke","#bdb8ad");p.setAttribute("stroke-width","1.5");svg.appendChild(p);
 var bx=ux*9,by=uy*9,px=-uy*4.5,py=ux*4.5,ah=document.createElementNS(SVGNS,"path");
 ah.setAttribute("d","M "+(ex-bx+px)+" "+(ey-by+py)+" L "+ex+" "+ey+" L "+(ex-bx-px)+" "+(ey-by-py));
 ah.setAttribute("class","cg-edge");ah.setAttribute("stroke","#bdb8ad");ah.setAttribute("stroke-width","1.5");ah.setAttribute("fill","none");svg.appendChild(ah);
 edgeEls.push({d:ed,p:p,ah:ah});});
var nodeEls={};
order.forEach(function(id){var n=nodes[id],r=document.createElementNS(SVGNS,"rect");
 r.setAttribute("x",n.x-HW);r.setAttribute("y",n.y-HH);r.setAttribute("width",HW*2);r.setAttribute("height",HH*2);
 r.setAttribute("rx",9);r.setAttribute("stroke-width",n.hero?2.4:1.4);r.setAttribute("fill","#f6f5f2");r.setAttribute("stroke","#cdc8bd");svg.appendChild(r);
 var tg=txt(n.x,n.y-7,"",8.5,1.3,"#94a3b8"),nm=txt(n.x,n.y+13,n.label,12.5,0,"#2A2927");
 nm.setAttribute("font-weight",n.hero?"700":"500");nodeEls[id]={r:r,tg:tg,nm:nm};});
var CATCOL={conj:"#94a3b8",form:"#5b8c6e",axiom:"#c2972b",ref:"#9c3a34",other:"#cdc8bd"};
var log=document.getElementById("log"),rowEls=[];
steps.forEach(function(sp,idx){var row=document.createElement("div");row.className="cg-row";
 var dot=document.createElement("span");dot.className="cg-dot";dot.style.borderColor=CATCOL[sp.cat]||CATCOL.other;
 var h=document.createElement("span");h.className="cg-hash";h.textContent=sp.hash;
 var b=document.createElement("span");b.className="cg-rb b-"+sp.cat;b.textContent=sp.clab;
 var s=document.createElement("span");s.className="cg-rs";s.textContent=sp.s;s.title=sp.s;
 row.appendChild(dot);row.appendChild(h);row.appendChild(b);row.appendChild(s);
 row.addEventListener("click",function(){stop();set(idx);});log.appendChild(row);rowEls.push(row);});
function render(i){if(!steps.length){return;}var st=statusAt[i];
 order.forEach(function(id){var ne=nodeEls[id],k=st[id]||"absent",y=STYLE[k];
  ne.r.setAttribute("fill",y.f);ne.r.setAttribute("stroke",y.s);ne.r.setAttribute("opacity",y.o);
  if(y.d)ne.r.setAttribute("stroke-dasharray",y.d);else ne.r.removeAttribute("stroke-dasharray");
  ne.tg.textContent=y.t;ne.tg.setAttribute("fill",TC[k]);ne.nm.setAttribute("opacity",k==="absent"?0.5:1);});
 edgeEls.forEach(function(ee){var ss=st[ee.d.s],ts=st[ee.d.t],live=ss!=="absent"&&ts!=="absent";
  var hot=[ss,ts].some(function(z){return z==="ref"||z==="blast";}),col=hot?"#c2722b":"#bdb8ad",op=live?1:0.12;
  if([ss,ts].indexOf("ref")>=0)col="#9c3a34";ee.p.setAttribute("stroke",col);ee.ah.setAttribute("stroke",col);
  ee.p.setAttribute("opacity",op);ee.ah.setAttribute("opacity",op);
  ee.p.setAttribute("stroke-width",hot?2:1.5);ee.ah.setAttribute("stroke-width",hot?2:1.5);});
 rowEls.forEach(function(r,j){if(j===i)r.classList.add("cur");else r.classList.remove("cur");});
 if(rowEls[i])rowEls[i].scrollIntoView({block:"nearest"});}
var slider=document.getElementById("slider"),timer=null;
var bP=document.getElementById("btnPlay"),bPr=document.getElementById("btnPrev"),bN=document.getElementById("btnNext");
function set(i){i=Math.max(0,Math.min(steps.length-1,i));slider.value=i;render(i);}
slider.addEventListener("input",function(){render(parseInt(slider.value,10));});
bPr.addEventListener("click",function(){stop();set(parseInt(slider.value,10)-1);});
bN.addEventListener("click",function(){stop();set(parseInt(slider.value,10)+1);});
function stop(){if(timer){clearInterval(timer);timer=null;bP.textContent="\\u25B6 Play";}}
bP.addEventListener("click",function(){if(timer){stop();return;}if(parseInt(slider.value,10)>=steps.length-1)set(0);
 bP.textContent="\\u275A\\u275A Pause";timer=setInterval(function(){var n=parseInt(slider.value,10)+1;if(n>=steps.length){stop();return;}set(n);},1200);});
render(parseInt(slider.value,10));
</script></body></html>
"""


def render(graph, frames: list[dict], title: str | None = None, hint: str | None = None,
           max_steps: int = 60) -> str:
    """Render a self-contained compact-SVG timeline figure for ``graph`` over its replay ``frames``."""
    node_ids = list(graph.nodes)
    pos, hero, vw, vh = _layered_layout(node_ids, _dep_pairs(graph))
    nodes_js = {}
    for nid in node_ids:
        n = graph.nodes[nid]
        label = (getattr(n, "label", None) or n.id)
        x, y = pos.get(nid, (_MARGIN, _MARGIN))
        nodes_js[nid] = {"label": label[:26], "x": round(x), "y": round(y), "hero": nid == hero}
    edges_js = [{"s": s, "t": t} for (s, t) in _dep_pairs(graph)]
    steps = _steps(frames, node_ids, max_steps)
    data = {"nodes": nodes_js, "order": node_ids, "edges": edges_js, "steps": steps}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    out = _TEMPLATE
    for k, v in {
        "{DATA}": payload,
        "{TITLE}": html.escape(title or "ClaimGraph timeline"),
        "{HINT}": html.escape(hint or "Drag the slider through the commit history; watch each claim's status."),
        "{VBOX}": f"{vw} {vh}",
        "{MAX}": str(max(0, len(steps) - 1)),
    }.items():
        out = out.replace(k, v)
    return out
