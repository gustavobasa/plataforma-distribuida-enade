"use strict";
const $ = (s) => document.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (t) => DOMPurify.sanitize(marked.parse(t || "", { gfm: true }));
let dados = null, pos = 0;

async function carregar() {
  const r = await fetch("/api/validacao/amostra", { credentials: "same-origin" });
  if (r.status === 401) { document.body.innerHTML = '<main><p>Faça login na <a href="/">página inicial</a> como Professor.</p></main>'; return; }
  if (r.status === 403) { document.body.innerHTML = "<main><p>Acesso restrito ao perfil Professor (HTTP 403).</p></main>"; return; }
  dados = await r.json();
  pos = Math.max(0, dados.itens.findIndex((i) => !i.avaliacao));
  if (pos < 0) pos = 0;
  mostrar();
}

function progresso() {
  const n = dados.itens.filter((i) => i.avaliacao).length;
  $("#progresso").textContent = `${n} de ${dados.itens.length} avaliadas · amostra estratificada (semente ${dados.semente}) de ${dados.populacao} questões`;
}

function mostrar() {
  progresso();
  const item = dados.itens[pos], q = item.doc;
  $("#pos").textContent = ` ${pos + 1} / ${dados.itens.length} `;
  if (!q) { $("#extraido").textContent = "Questão não encontrada no índice."; return; }
  const ano = q.ano, pags = q.origem.paginas;
  $("#paginas").innerHTML = pags.map((p) => `<img alt="Página ${p} de ${esc(q.origem.pdf)}" src="/api/validacao/pagina/${ano}/${encodeURIComponent(q.origem.pdf)}/${p}.png">`).join("")
    + (q.origem.gabarito_pdf ? `<details><summary>Gabarito oficial (${esc(q.origem.gabarito_pdf)})</summary><img alt="Gabarito" src="/api/validacao/pagina/${ano}/${encodeURIComponent(q.origem.gabarito_pdf)}/1.png"></details>` : "<p class='erro'>Sem PDF de gabarito associado.</p>");
  const alts = (q.alternativas || []).map((a) => `<p><b>${esc(a.letra)})</b> ${md(a.texto_md || a.texto)}</p>`).join("");
  const figs = (q.midia.figuras || []).filter((f) => f.arquivo).map((f) => `<img src="/api/figuras/${f.arquivo}" alt="figura extraída" style="max-width:100%">`).join("");
  $("#extraido").innerHTML = `
    <div class="bloco"><b>${esc(q.rotulo)}</b> · ${esc(q.curso)} (${esc(q.ano)}) · componente <b>${esc(q.componente)}</b> · ${esc(q.tipo_questao)} · páginas ${esc(pags.join(", "))}
      · gabarito extraído: <b>${esc(q.anulada ? "ANULADA" : (q.gabarito || q.gabarito_status))}</b> · confiança ${esc(q.extracao.confianca)} ${q.extracao.alertas.length ? "· alertas: " + esc(q.extracao.alertas.join(", ")) : ""}</div>
    ${q.texto_base_md ? `<div class="bloco"><small class="sutil">Texto-base</small>${md(q.texto_base_md)}</div>` : ""}
    <div class="bloco"><small class="sutil">Enunciado</small>${md(q.enunciado_md || q.enunciado)}</div>
    ${alts ? `<div class="bloco"><small class="sutil">Alternativas</small>${alts}</div>` : ""}
    ${figs ? `<div class="bloco"><small class="sutil">Figuras recortadas</small>${figs}</div>` : ""}`;
  renderMathInElement($("#extraido"), { delimiters: [{ left: "$", right: "$", display: false }], throwOnError: false });
  const av = item.avaliacao?.criterios || {};
  $("#criterios").innerHTML = Object.entries(dados.criterios).map(([k, desc]) => `
    <div class="crit"><span>${esc(desc)}</span><span class="opcoes">
      ${["ok", "erro", "na"].map((v) => `<label><input type="radio" name="${k}" value="${v}" ${av[k] === v ? "checked" : ""} required> ${v === "ok" ? "Correto" : v === "erro" ? "Incorreto" : "N/A"}</label>`).join("")}
    </span></div>`).join("");
  $("#obs").value = item.avaliacao?.observacao || "";
  $("#salvo").textContent = item.avaliacao ? `avaliada por ${item.avaliacao.avaliador}` : "";
}

$("#form-val").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const crit = {};
  Object.keys(dados.criterios).forEach((k) => (crit[k] = document.querySelector(`input[name="${k}"]:checked`)?.value));
  const item = dados.itens[pos];
  const r = await fetch(`/api/validacao/${item.doc.id}`, { method: "PUT", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ criterios: crit, observacao: $("#obs").value }) });
  if (!r.ok) { $("#salvo").textContent = `Erro ao salvar (HTTP ${r.status})`; return; }
  item.avaliacao = { criterios: crit, observacao: $("#obs").value, avaliador: "você" };
  if (pos < dados.itens.length - 1) pos++;
  mostrar(); window.scrollTo(0, 0);
});
$("#ant").addEventListener("click", () => { if (pos > 0) { pos--; mostrar(); } });
$("#prox").addEventListener("click", () => { if (pos < dados.itens.length - 1) { pos++; mostrar(); } });
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "TEXTAREA") return;
  if (e.key === "ArrowLeft") $("#ant").click();
  if (e.key === "ArrowRight") $("#prox").click();
});
carregar();
