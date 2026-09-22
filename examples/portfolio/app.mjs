import { defaults, controls, run } from "./model.mjs";
const meta = await (await fetch("./project.json")).json();
const catalogue = await fetch("./catalogue.json")
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null);
if (catalogue) defaults.catalogue = catalogue;
const $ = (s) => document.querySelector(s),
  input = structuredClone(defaults);
document.title = meta.title + " | working example";
$("#title").textContent = meta.title;
$("#description").textContent = meta.caption;
$("#scope").textContent = meta.boundary;
$("#source").href = `https://github.com/LolStar123/${meta.repo}`;
$("#workflow").textContent = meta.workflow;
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
for (const spec of controls) {
  const label = document.createElement("label");
  label.textContent = spec.label;
  const el = document.createElement(
    spec.type === "select" ? "select" : "input",
  );
  el.id = spec.key;
  if (spec.type === "select")
    for (const v of spec.options) {
      const o = new Option(v, v);
      el.add(o);
    }
  else el.type = spec.type;
  for (const k of ["min", "max", "step"])
    if (spec[k] !== undefined) el[k] = spec[k];
  if (spec.type === "checkbox") el.checked = input[spec.key];
  else el.value = input[spec.key];
  el.addEventListener("input", () => {
    input[spec.key] =
      spec.type === "checkbox"
        ? el.checked
        : spec.type === "number"
          ? Number(el.value)
          : el.value;
    $("#fixture").value = JSON.stringify(input, null, 2);
    render();
  });
  label.append(el);
  $("#controls").append(label);
}
$("#fixture").value = JSON.stringify(input, null, 2);
let result = null;
function plot(r) {
  const ns = "http://www.w3.org/2000/svg",
    svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 720 220");
  svg.setAttribute("role", "img");
  const title = document.createElementNS(ns, "title");
  title.textContent = r.seriesLabel || "Traversable route around blocked cells";
  svg.append(title);
  const draw = (tag, attrs) => {
    const e = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    svg.append(e);
    return e;
  };
  if (r.grid) {
    const g = r.grid,
      s = Math.min(680 / g.width, 195 / g.height),
      ox = 20,
      oy = 12;
    for (const [x, y] of g.blocked)
      draw("rect", {
        x: ox + x * s,
        y: oy + y * s,
        width: s,
        height: s,
        fill: "#a7a18e",
      });
    if (g.path.length)
      draw("polyline", {
        points: g.path
          .map(([x, y]) => `${ox + (x + 0.5) * s},${oy + (y + 0.5) * s}`)
          .join(" "),
        fill: "none",
        stroke: "#536c50",
        "stroke-width": 3,
      });
    for (const [p, color] of [
      [g.start, "#536c50"],
      [g.goal, "#a34d32"],
    ])
      draw("circle", {
        cx: ox + (p[0] + 0.5) * s,
        cy: oy + (p[1] + 0.5) * s,
        r: s * 0.38,
        fill: color,
      });
  } else {
    const vals = r.series,
      lo = Math.min(...vals),
      hi = Math.max(...vals),
      span = hi - lo || 1;
    draw("path", { d: "M48 12 V186 H700", stroke: "#aaa38e", fill: "none" });
    draw("polyline", {
      points: vals
        .map(
          (v, n) =>
            `${48 + (n / (vals.length - 1 || 1)) * 652},${178 - ((v - lo) / span) * 150}`,
        )
        .join(" "),
      fill: "none",
      stroke: "#536c50",
      "stroke-width": 2,
    });
    for (const [y, v] of [
      [26, hi],
      [181, lo],
    ])
      draw("text", {
        x: 44,
        y,
        "text-anchor": "end",
        "font-size": 11,
        fill: "#5c584e",
      }).textContent = v.toFixed(2);
    draw("text", {
      x: 48,
      y: 210,
      "font-size": 12,
      fill: "#5c584e",
    }).textContent = r.seriesLabel;
  }
  return svg;
}
function render() {
  try {
    result = run(input);
    $("#error").textContent = "";
    $("#summary").textContent = result.summary;
    $("#metrics").innerHTML = Object.entries(result.metrics)
      .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
      .join("");
    $("#table").innerHTML =
      "<thead><tr>" +
      result.columns
        .map((c) => '<th scope="col">' + esc(c) + "</th>")
        .join("") +
      "</tr></thead><tbody>" +
      result.rows
        .map(
          (row) =>
            "<tr>" +
            row.map((v) => "<td>" + esc(v) + "</td>").join("") +
            "</tr>",
        )
        .join("") +
      "</tbody>";
    $("#steps").innerHTML = result.steps
      .map((s) => "<li>" + esc(s) + "</li>")
      .join("");
    $("#chart").replaceChildren();
    if (result.series?.length || result.grid) $("#chart").append(plot(result));
    $("#catalogue").textContent = result.extra
      ? JSON.stringify(result.extra, null, 2)
      : "";
    $("#catalogue").hidden = !result.extra;
    window.__example = { input: structuredClone(input), result, ready: true };
  } catch (e) {
    result = null;
    $("#error").textContent = e.message;
    window.__example = { ready: false, error: e.message };
  }
}
$("#apply").onclick = () => {
  try {
    const parsed = JSON.parse($("#fixture").value);
    for (const key of Object.keys(input)) delete input[key];
    Object.assign(input, parsed);
    for (const s of controls) {
      if (s.type === "checkbox") $("#" + s.key).checked = !!input[s.key];
      else $("#" + s.key).value = input[s.key];
    }
    render();
  } catch (e) {
    $("#error").textContent = e.message;
  }
};
$("#reset").onclick = () => {
  location.reload();
};
function download(name, text, type) {
  const u = URL.createObjectURL(new Blob([text], { type })),
    a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
$("#json").onclick = () => {
  if (result)
    download(
      meta.repo + "-result.json",
      JSON.stringify(result.artifact, null, 2),
      "application/json",
    );
};
$("#csv").onclick = () => {
  if (result)
    download(
      meta.repo + "-result.csv",
      [result.columns, ...result.rows]
        .map((row) =>
          row
            .map((v) => '"' + String(v ?? "").replace(/"/g, '""') + '"')
            .join(","),
        )
        .join("\r\n"),
      "text/csv",
    );
};
render();
