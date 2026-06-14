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
  }

  async function main() {
    buildLegend();
    const data = await fetch("assets/claimgraph.json").then((r) => r.json());

    const elements = [];
    for (const n of data.nodes) {
      elements.push({ data: {
        id: n.id, label: n.id,
        eff: n.effective_status || n.status, status: n.status, statement: n.statement,
        kind: n.kind, inq: !!n.in_question, weakest_dep: n.weakest_dep,
        effective_status: n.effective_status,
      } });
    }
    const depOut = new Map(), depIn = new Map();
    for (const e of data.edges) {
      elements.push({ data: { id: `${e.source}|${e.relation}|${e.target}`, source: e.source, target: e.target, relation: e.relation } });
      if (DEP.has(e.relation)) {
        (depOut.get(e.source) || depOut.set(e.source, []).get(e.source)).push(e.target);
        (depIn.get(e.target) || depIn.set(e.target, []).get(e.target)).push(e.source);
      }
    }

    const cy = cytoscape({
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
      cy.elements().removeClass("faded hl blast");
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

    window.cy = cy; // exposed for debugging and tooling
  }

  main();
})();
