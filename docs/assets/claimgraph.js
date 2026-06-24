/* claimgraph viewer: render claimgraph.json with Cytoscape, on the CKC palette.
 * Node fill = effective status; edge style = relation. Click a claim to trace its dependency
 * closure; click a broken claim to light up its blast radius. */
(() => {
  "use strict";

  const STATUS_COLOR = {
    "math.machine-checked": "#a9c39c", "math.axiomatised": "#dcc085", "math.open": "#e4d4ba",
    "math.proved-informal": "#d2cabb", "math.conjectured": "#b9b2d2", "math.disproved": "#9c3a34",
    "sci.replicated": "#a9c39c", "sci.supported": "#abc1d2", "sci.measured": "#c6d6e2",
    "sci.piloted": "#e4d4ba", "sci.hypothesis": "#b9b2d2",
    "sci.not-replicated": "#d3a3ad", "sci.falsified": "#9c3a34",
  };
  const UNSET = "#d2cabb";
  const BROKEN = new Set(["math.disproved", "sci.not-replicated", "sci.falsified"]);
  const DEP = new Set(["Depends-On", "Assumes"]);
  const PROVE = new Set(["Proves", "Closes"]);
  const BREAK = new Set(["Refutes", "Disproves", "Retracts", "Invalidates"]);

  const STATUS_LEGEND = [
    ["math.machine-checked", "machine-checked"], ["math.axiomatised", "axiomatised"],
    ["math.proved-informal", "proved (informal)"], ["math.conjectured", "conjectured"],
    ["sci.supported", "supported / measured"], ["sci.not-replicated", "not replicated"],
    ["math.disproved", "disproved / falsified"],
  ];
  const EDGE_LEGEND = [
    ["#6b7280", "solid", "Depends-On / Assumes"],
    ["#8fae82", "dashed", "Proves / Closes"],
    ["#9c3a34", "dashed", "Refutes / Disproves"],
    ["#dcc085", "dashed", "Supersedes"],
  ];

  // reconcile mode: a node carries three readings (blueprint / history / kernel) + an agreement.
  const AGREEMENT = {
    "consistent": ["#8fae82", "consistent"],
    "kernel-refutes-claim": ["#9c3a34", "kernel refutes claim (validity gap)"],
    "blueprint-incomplete": ["#bd9a55", "blueprint-incomplete (uses an unformalized concept)"],
    "undocumented": ["#bd9a55", "undocumented"],
    "stale-blueprint": ["#5b6b78", "stale blueprint"],
    "paper-only": ["#b6ad9b", "paper only"],
    "ungrounded": ["#7d749e", "ungrounded"],
  };
  // Only a validity gap (kernel refutes a claim) is a hard "red ring" failure. blueprint-incomplete
  // is a coverage warning: the theorem is machine-checked, it just \uses an unformalized concept.
  const GAP = new Set(["kernel-refutes-claim"]);
  let RECONCILE = false;

  const edgeColor = (r) => BREAK.has(r) ? "#9c3a34" : PROVE.has(r) ? "#8fae82" : r === "Supersedes" ? "#dcc085" : "#6b7280";
  const isDashed = (r) => !DEP.has(r);

  function closure(start, adj) {
    const seen = new Set();
    const stack = [...(adj.get(start) || [])];
    while (stack.length) {
      const cur = stack.pop();
      if (seen.has(cur)) continue;
      seen.add(cur);
      (adj.get(cur) || []).forEach((n) => { if (!seen.has(n)) stack.push(n); });
    }
    seen.delete(start);
    return seen;
  }

  function pill(status) {
    const c = STATUS_COLOR[status] || UNSET;
    return `<span class="pill" style="background:${c}33;border-color:${c}">${status || "unset"}</span>`;
  }

  function renderDetail(d) {
    const el = document.getElementById("detail");
    const eff = d.effective_status || d.status;
    const demoted = eff && d.status && eff !== d.status;
    if (RECONCILE) {
      const [c, label] = AGREEMENT[d.agreement] || ["#6b7280", d.agreement || "?"];
      const via = (d.agreement === "blueprint-incomplete" && d.uses_gap) ? ` <span class="muted">uses ${d.uses_gap}</span>` : "";
      el.innerHTML = `
        <h2>${d.id}</h2>
        <div class="kind">${d.kind || "claim"}</div>
        ${d.statement ? `<p class="stmt">${d.statement}</p>` : ""}
        <dl>
          <dt>Blueprint <span class="muted">\\leanok</span></dt><dd>${pill(d.claimed)}</dd>
          <dt>History <span class="muted">commit</span></dt><dd>${pill(d.asserted)}</dd>
          <dt>Kernel <span class="muted">#print axioms</span></dt><dd>${pill(d.kernel)}</dd>
          <dt>Effective <span class="muted">transitive</span></dt><dd>${pill(eff)}${via}</dd>
        </dl>
        <div class="flag" style="background:${c}1f;border-color:${c};color:${GAP.has(d.agreement) ? "#9c3a34" : "#3a3a3a"}">${label}</div>
      `;
      return;
    }
    el.innerHTML = `
      <h2>${d.id}</h2>
      <div class="kind">${d.kind || "claim"}</div>
      ${d.statement ? `<p class="stmt">${d.statement}</p>` : ""}
      <dl>
        <dt>Asserted status</dt><dd>${pill(d.status)}</dd>
        <dt>Effective status</dt><dd>${pill(eff)}${demoted ? ` <span class="muted">← ${d.weakest_dep}</span>` : ""}</dd>
      </dl>
      ${d.in_question ? `<div class="flag">In question: a dependency was refuted or retracted.</div>` : ""}
    `;
  }

  function buildLegend() {
    document.getElementById("status-legend").innerHTML = STATUS_LEGEND
      .map(([s, label]) => `<li><span class="dot" style="background:${STATUS_COLOR[s]}"></span>${label}</li>`)
      .join("");
    document.getElementById("edge-legend").innerHTML = EDGE_LEGEND
      .map(([c, style, label]) => `<li><span class="line" style="border-top-color:${c};border-top-style:${style}"></span>${label}</li>`)
      .join("");
    const al = document.getElementById("agreement-legend");
    if (al && RECONCILE) {
      al.innerHTML = Object.values(AGREEMENT)
        .map(([c, label]) => `<li><span class="dot" style="background:${c}55;border-color:${c}"></span>${label}</li>`)
        .join("");
    }
  }

  let cy = null;
  let loadSeq = 0;
  const INITIAL_DETAIL = (() => { const el = document.getElementById("detail"); return el ? el.innerHTML : ""; })();

  // --- timeline replay state (rebuilt per load) ---
  let TL = null;          // the current data.meta.timeline frames, or null
  let renderFrame = null; // (k) => void; closes over the current cy, set inside load()
  let playTimer = null;
  const parseEdge = (eid) => { const [source, relation, target] = eid.split("|"); return { source, relation, target }; };

  function resetView() {
    if (!cy) return;
    cy.elements().removeClass("faded hl blast refuted");
    cy.fit(cy.elements(), 40);
    const el = document.getElementById("detail");
    if (el && INITIAL_DETAIL) el.innerHTML = INITIAL_DETAIL;
  }

  // Detail panel showing the commit at the current frame (replaced when a node is clicked).
  function renderFrameDetail(f) {
    const el = document.getElementById("detail");
    if (!el) return;
    const when = f.date ? f.date.slice(0, 10) : `commit ${f.i + 1} of ${TL.length}`;
    const ev = f.event ? `<span class="pill" style="background:#9c3a3422;border-color:#9c3a34">${f.event}</span>` : "";
    el.innerHTML = `
      <h2>${when}</h2>
      <div class="kind">${f.type || "commit"}</div>
      <p class="stmt">${f.subject}</p>
      ${ev}${f.focus ? ` <span class="muted">${f.focus}</span>` : ""}
    `;
  }

  function setTransport(f) {
    const range = document.getElementById("tl-range");
    const label = document.getElementById("tl-label");
    if (range) range.value = String(f.i);
    if (label) label.textContent = (f.date ? f.date.slice(0, 10) + "  " : `${f.i + 1}/${TL.length}  `) + f.subject;
  }

  function stopPlay() {
    if (playTimer) { clearInterval(playTimer); playTimer = null; }
    const b = document.getElementById("tl-play");
    if (b) { b.textContent = "▶ Play"; b.setAttribute("aria-pressed", "false"); }
  }

  function play() {
    if (!TL || !renderFrame) return;
    const range = document.getElementById("tl-range");
    let k = Number(range ? range.value : 0);
    if (k >= TL.length - 1) k = -1; // at the end: restart from the beginning
    const b = document.getElementById("tl-play");
    if (b) { b.textContent = "❚❚ Pause"; b.setAttribute("aria-pressed", "true"); }
    playTimer = setInterval(() => {
      k += 1;
      if (k >= TL.length) { stopPlay(); return; }
      renderFrame(k);
    }, 950);
  }

  function initTransport() {
    const bar = document.getElementById("transport");
    stopPlay();
    if (!bar) return;
    if (!TL) { bar.hidden = true; return; }
    bar.hidden = false;
    const range = document.getElementById("tl-range");
    if (range) { range.max = String(TL.length - 1); range.value = String(TL.length - 1); }
    renderFrame(TL.length - 1); // default to the final state: identical to the static view
  }

  async function load(src) {
    const seq = ++loadSeq;
    const data = await fetch(src).then((r) => r.json());
    if (seq !== loadSeq) return; // a newer switch started; drop this stale load
    RECONCILE = (data.meta && (data.meta.sources || []).includes("blueprint")) || data.nodes.some((n) => n.agreement);
    buildLegend();

    const elements = [];
    const nodeIds = new Set(data.nodes.map((n) => n.id));
    for (const n of data.nodes) {
      elements.push({ data: {
        id: n.id, label: n.id,
        eff: n.effective_status || n.status, status: n.status, statement: n.statement,
        kind: n.kind, inq: !!n.in_question, weakest_dep: n.weakest_dep,
        effective_status: n.effective_status,
        claimed: n.claimed, asserted: n.asserted, kernel: n.kernel, agreement: n.agreement || null,
        uses_gap: n.uses_gap || null, blueprint_complete: n.blueprint_complete,
      } });
    }
    const depOut = new Map(), depIn = new Map();
    for (const e of data.edges) {
      if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) {
        console.warn("claimgraph: dropping edge with a missing endpoint", e);
        continue;
      }
      elements.push({ data: { id: `${e.source}|${e.relation}|${e.target}`, source: e.source, target: e.target, relation: e.relation } });
      if (DEP.has(e.relation)) {
        (depOut.get(e.source) || depOut.set(e.source, []).get(e.source)).push(e.target);
        (depIn.get(e.target) || depIn.set(e.target, []).get(e.target)).push(e.source);
      }
    }

    if (cy) cy.destroy();
    cy = cytoscape({
      container: document.getElementById("cy"),
      elements,
      style: [
        { selector: "node", style: {
          "background-color": (e) => STATUS_COLOR[e.data("eff")] || UNSET,
          "label": "data(label)", "font-family": "monospace", "font-size": 10,
          "color": "#1a1a1a", "text-valign": "bottom", "text-margin-y": 5,
          "text-wrap": "wrap", "text-max-width": 120,
          "width": 20, "height": 20, "border-width": 1.4, "border-color": "rgba(0,0,0,.45)",
        } },
        { selector: "node[?inq]", style: { "border-color": "#9c3a34", "border-width": 2, "border-style": "dashed" } },
        { selector: 'node[agreement = "kernel-refutes-claim"]',
          style: { "border-color": "#9c3a34", "border-width": 3.4, "border-style": "double" } },
        { selector: 'node[agreement = "blueprint-incomplete"]',
          style: { "border-color": "#bd9a55", "border-width": 2.6, "border-style": "dashed" } },
        { selector: "edge", style: {
          "width": 1.6, "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": 0.85,
          "line-color": (e) => edgeColor(e.data("relation")),
          "target-arrow-color": (e) => edgeColor(e.data("relation")),
          "line-style": (e) => isDashed(e.data("relation")) ? "dashed" : "solid",
        } },
        { selector: ".faded", style: { "opacity": 0.12 } },
        { selector: "node.hl", style: { "border-color": "#1a1a1a", "border-width": 2.6 } },
        { selector: "edge.hl", style: { "width": 3, "opacity": 1 } },
        { selector: "node.blast", style: { "border-color": "#9c3a34", "border-width": 2.8 } },
        { selector: "edge.blast", style: { "line-color": "#9c3a34", "target-arrow-color": "#9c3a34", "width": 3, "line-style": "solid", "opacity": 1 } },
        // the just-refuted node on a replay frame (its fill is already the disproved red)
        { selector: "node.refuted", style: { "border-color": "#5e1714", "border-width": 4, "border-style": "double" } },
        // timeline replay: a claim not yet present at the current frame is hidden (canvas display).
        { selector: ".hidden", style: { "display": "none" } },
      ],
      layout: { name: "cose", padding: 40, animate: false, fit: true,
        nodeRepulsion: 9000, idealEdgeLength: 95, componentSpacing: 110, gravity: 0.3,
        nodeDimensionsIncludeLabels: true },
    });

    const refit = () => cy.fit(cy.elements(), 40);
    cy.one("layoutstop", refit);
    cy.ready(refit);
    window.addEventListener("resize", refit);

    function reset() {
      cy.elements().removeClass("faded hl blast refuted");
    }

    cy.on("tap", "node", (evt) => {
      const node = evt.target, id = node.id(), d = node.data();
      reset();
      const dep = closure(id, depOut);     // what this claim rests on
      const blast = closure(id, depIn);    // what rests on this claim
      const keep = new Set([id, ...dep, ...blast]);

      cy.nodes().forEach((n) => { if (!keep.has(n.id())) n.addClass("faded"); });
      cy.edges().forEach((e) => { if (!(keep.has(e.source().id()) && keep.has(e.target().id()))) e.addClass("faded"); });

      const depNodes = new Set([id, ...dep]);
      node.addClass("hl");
      dep.forEach((x) => cy.getElementById(x).addClass("hl"));
      cy.edges().forEach((e) => {
        if (DEP.has(e.data("relation")) && depNodes.has(e.source().id()) && depNodes.has(e.target().id())) e.addClass("hl");
      });

      if (BROKEN.has(d.status)) {
        const blastNodes = new Set([id, ...blast]);
        blast.forEach((x) => cy.getElementById(x).removeClass("faded").addClass("blast"));
        cy.edges().forEach((e) => {
          if (DEP.has(e.data("relation")) && blastNodes.has(e.source().id()) && blastNodes.has(e.target().id())) e.removeClass("faded").addClass("blast");
        });
      }
      renderDetail(d);
    });

    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        reset();
        document.getElementById("detail").innerHTML = `<p class="hint">Select a claim to inspect its status and dependencies.</p>`;
      }
    });

    // --- timeline replay: rewind/scrub the history this graph was built from -----------------------
    // The layout already ran once over the full (union) graph, so every claim has its final position.
    // A frame just shows/hides claims and recolours them by their status at that commit; nothing is
    // re-laid-out and the viewport never jumps, so claims "build up" in place.
    TL = (data.meta && Array.isArray(data.meta.timeline) && data.meta.timeline.length > 1)
      ? data.meta.timeline : null;
    renderFrame = (k) => {
      if (!TL) return;
      const f = TL[Math.max(0, Math.min(TL.length - 1, k))];
      reset();
      const present = new Set(f.present), pedges = new Set(f.edges);
      cy.batch(() => {
        cy.nodes().forEach((n) => {
          const id = n.id();
          if (!present.has(id)) { n.addClass("hidden"); return; }
          n.removeClass("hidden");
          const s = f.state[id] || {};
          n.data("eff", s.effective_status || s.status || null);
          n.data("status", s.status || null);
          n.data("inq", !!s.in_question);
        });
        cy.edges().forEach((e) => { e.toggleClass("hidden", !pedges.has(e.id())); });
      });
      cy.style().update(); // re-evaluate the status->colour and [?inq] mappers against the new data
      // A refutation is the moment the final all-green graph forgets: pulse the refuted claim (its
      // fill is already the disproved red) and light the dependents it puts in question at this frame.
      if (f.event === "refuted" && f.focus && present.has(f.focus)) {
        const depIn = new Map();
        f.edges.forEach((eid) => {
          const { source, relation, target } = parseEdge(eid);
          if (DEP.has(relation)) (depIn.get(target) || depIn.set(target, []).get(target)).push(source);
        });
        const focus = cy.getElementById(f.focus);
        focus.addClass("refuted");
        focus.flashClass("hl", 700);
        closure(f.focus, depIn).forEach((x) => {
          if (present.has(x)) cy.getElementById(x).addClass("blast");
        });
      }
      renderFrameDetail(f);
      setTransport(f);
    };
    initTransport();

    window.cy = cy; // exposed for debugging and tooling
  }

  // example switcher: each option's value is a claimgraph.json under assets/
  const LEDE = {
    "assets/claimgraph.json": "The Four Colour Theorem: from Guthrie's 1852 conjecture, through Kempe's refuted proof, to the 1976 computer-assisted proof and Gonthier's 2005 machine-checked Coq formalization.",
    "assets/fermat.json": "Fermat's Last Theorem: centuries of special cases, the modularity route through Frey and Ribet, the gap in Wiles's 1993 proof repaired by Taylor and Wiles, and a Lean formalization still in progress.",
    "assets/kepler.json": "The Kepler conjecture: Hsiang's refuted 1993 attempt, Hales's computer-assisted proof the referees could only certify 99% certain, and the Flyspeck formal proof that made it machine-checked.",
    "assets/fundamental-algebra.json": "The Fundamental Theorem of Algebra: d'Alembert's and Gauss's gapped early proofs, several independent rigorous routes to the same theorem, and a kernel-checked Coq formalization.",
    "assets/prime-number-theorem.json": "The Prime Number Theorem: Chebyshev's bounds, two independent 1896 proofs over the same zeta lemma, the 1949 elementary proof, an Isabelle formalization, and a sharper error term still resting on the open Riemann hypothesis.",
  };
  const INSTRUCTIONS = "Node colour is the <b>effective status</b>, the weakest status in a claim's <code>Depends-On</code>/<code>Assumes</code> closure. Click a claim to trace what it rests on; click a broken claim to highlight the <b>claims it affects</b>.";

  const sel = document.getElementById("example");
  const lede = document.getElementById("ex-lede");
  const setLede = (src) => { if (lede) lede.innerHTML = (LEDE[src] || "") + " " + INSTRUCTIONS; };
  const initial = (sel && sel.value) || window.CG_DATA || "assets/claimgraph.json";
  setLede(initial);
  load(initial);
  if (sel) sel.addEventListener("change", () => { setLede(sel.value); load(sel.value); });

  const resetBtn = document.getElementById("reset-view");
  if (resetBtn) resetBtn.addEventListener("click", resetView);

  // Transport controls are wired once; they call the current load()'s renderFrame via the closure.
  const tlPlay = document.getElementById("tl-play");
  const tlPrev = document.getElementById("tl-prev");
  const tlNext = document.getElementById("tl-next");
  const tlRange = document.getElementById("tl-range");
  const at = () => (tlRange ? Number(tlRange.value) : 0);
  if (tlPlay) tlPlay.addEventListener("click", () => { if (playTimer) stopPlay(); else play(); });
  if (tlPrev) tlPrev.addEventListener("click", () => { stopPlay(); if (renderFrame) renderFrame(at() - 1); });
  if (tlNext) tlNext.addEventListener("click", () => { stopPlay(); if (renderFrame) renderFrame(at() + 1); });
  if (tlRange) tlRange.addEventListener("input", () => { stopPlay(); if (renderFrame) renderFrame(at()); });
})();
