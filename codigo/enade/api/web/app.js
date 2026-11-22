"use strict";
// Interface web da Busca ENADE (RF20). Sem build: JS puro + KaTeX (fórmulas), marked (Markdown),
// DOMPurify (sanitização) e Mermaid (diagramas). Toda autorização é verificada no backend.

const $ = (s, el = document) => el.querySelector(s);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sanitizar = (html, extra = {}) => DOMPurify.sanitize(html, { USE_PROFILES: { html: true }, ...extra });
const ROTULOS = { area: "Área", curso: "Curso", ano: "Ano", componente: "Componente (FG/CE)", tipo: "Tipo de questão", competencia: "Competência", objeto: "Tema / objeto de conhecimento", grau: "Grau" };
const estado = { usuario: null, q: "", pagina: 1, filtros: {}, tax: { competencias: {}, temas: {} }, cursos: {} };

mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });

async function api(caminho, opcoes = {}) {
  const r = await fetch(caminho, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...opcoes });
  if (r.status === 401) { mostrarLogin(); throw new Error("não autenticado"); }
  let corpo = null;
  const tipo = r.headers.get("content-type") || "";
  if (tipo.includes("json")) corpo = await r.json();
  if (!r.ok) { const e = new Error((corpo && corpo.detail) || `HTTP ${r.status}`); e.status = r.status; throw e; }
  return { corpo, r };
}

function mostrarLogin() { $("#app").hidden = true; $("#tela-login").hidden = false; }

async function iniciar() {
  try {
    const { corpo } = await api("/api/auth/eu");
    await entrar(corpo);
  } catch { mostrarLogin(); }
}

async function entrar(u) {
  estado.usuario = u;
  $("#tela-login").hidden = true; $("#app").hidden = false;
  $("#quem").textContent = `${u.nome} · perfil ${u.perfil}`;
  const prof = u.perfil === "professor";
  document.querySelectorAll(".so-professor").forEach((e) => (e.hidden = !prof));
  document.querySelectorAll(".so-estudante").forEach((e) => (e.hidden = prof));
  try {
    const { corpo } = await api("/api/taxonomia");
    corpo.competencias.forEach((c) => (estado.tax.competencias[c.id] = c.nome));
    corpo.temas.forEach((c) => (estado.tax.temas[c.id] = c.nome));
  } catch { /* rótulos ficam com o id */ }
  buscar();
  atualizarContador();
}

$("#form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  $("#erro-login").textContent = "";
  try {
    const { corpo } = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ usuario: f.get("usuario"), senha: f.get("senha") }) });
    ev.target.reset();
    await entrar({ usuario: corpo.usuario, nome: corpo.nome, perfil: corpo.perfil });
  } catch (e) { $("#erro-login").textContent = e.status === 401 ? "Usuário ou senha inválidos." : e.message; }
});

$("#sair").addEventListener("click", async () => { try { await api("/api/auth/logout", { method: "POST" }); } catch {} mostrarLogin(); });

document.querySelectorAll(".aba").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".aba").forEach((x) => x.classList.toggle("ativa", x === b));
  ["busca", "lista", "painel", "operacao"].forEach((n) => ($(`#aba-${n}`).hidden = n !== b.dataset.aba));
  if (b.dataset.aba === "lista") carregarLista();
  if (b.dataset.aba === "painel") carregarPainel();
  if (b.dataset.aba === "operacao") carregarOperacao();
}));

// ------------------------------------------------------------------ busca
function parametros(extra = {}) {
  const p = new URLSearchParams();
  if (estado.q) p.set("q", estado.q);
  for (const [k, vs] of Object.entries(estado.filtros)) vs.forEach((v) => p.append(k, v));
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p;
}

function rotuloFaceta(nome, valor) {
  if (nome === "competencia") return `${valor} – ${estado.tax.competencias[valor] || ""}`;
  if (nome === "objeto") return `${valor} – ${estado.tax.temas[valor] || ""}`;
  if (nome === "curso") return estado.cursos[valor] || valor;
  return valor;
}

async function buscar() {
  const extra = { pagina: estado.pagina, por_pagina: 10 };
  if ($("#colapsar").checked) extra.colapsar = "true";
  if ($("#semcache").checked) extra.cache = "false";
  $("#resumo").textContent = "Buscando…";
  try {
    const { corpo, r } = await api(`/api/busca?${parametros(extra)}`);
    $("#resumo").textContent = `${corpo.total} resultado(s) · página ${corpo.pagina} de ${corpo.paginas} · ES ${corpo.tempo_es_ms} ms · resposta ${r.headers.get("X-Tempo-Resposta-ms")} ms · cache ${r.headers.get("X-Cache")}`;
    renderResultados(corpo);
    renderFacetas(corpo.facetas);
    renderPaginacao(corpo);
  } catch (e) { $("#resumo").textContent = `Erro: ${e.message}`; }
}

function renderResultados(corpo) {
  const ol = $("#resultados");
  ol.replaceChildren();
  for (const q of corpo.itens) {
    estado.cursos[q.curso_slug] = q.curso;
    const li = document.createElement("li");
    const frags = (q.destaques || []).slice(0, 3).map((f) => `<p class="frag">… ${sanitizar(f, { ALLOWED_TAGS: ["mark"] })} …</p>`).join("");
    li.innerHTML = `
      <div class="meta">
        <span class="etq">${esc(q.ano)}</span><span class="etq">${esc(q.curso)}</span><span class="etq">${esc(q.componente)}</span>
        <span class="etq">${esc(q.tipo_questao)}</span>${q.anulada ? '<span class="etq anulada">ANULADA</span>' : ""}
        ${q.cursos_equivalentes ? `<span class="etq">+${esc(q.cursos_equivalentes - 1)} curso(s) com a mesma questão</span>` : ""}
        <span>${esc(q.origem?.pdf)} · p. ${esc((q.origem?.paginas || []).join(", "))}</span>
      </div>
      <strong>${esc(q.rotulo)}</strong>
      ${frags || `<p class="frag">${esc((q.enunciado || "").slice(0, 260))}…</p>`}
      <div class="acoes"><button class="sec" data-ver="${esc(q.id)}">Ver questão</button><button data-add="${esc(q.id)}">Adicionar à lista</button></div>`;
    ol.appendChild(li);
  }
}

function renderFacetas(facetas) {
  const div = $("#facetas");
  div.replaceChildren();
  for (const nome of ["area", "ano", "componente", "tipo", "curso", "competencia", "objeto", "grau"]) {
    const itens = facetas[nome] || [];
    const sel = estado.filtros[nome] || [];
    if (!itens.length && !sel.length) continue;
    const fs = document.createElement("fieldset");
    fs.innerHTML = `<legend>${esc(ROTULOS[nome])}</legend>`;
    const valores = new Map(itens.map((i) => [String(i.valor), i.total]));
    sel.forEach((v) => valores.has(String(v)) || valores.set(String(v), 0));
    for (const [valor, total] of valores) {
      const lab = document.createElement("label");
      lab.className = "linha";
      lab.innerHTML = `<input type="checkbox" ${sel.includes(valor) ? "checked" : ""}> <span>${esc(rotuloFaceta(nome, valor))} <span class="sutil">(${total})</span></span>`;
      lab.querySelector("input").addEventListener("change", (ev) => {
        const atual = new Set(estado.filtros[nome] || []);
        ev.target.checked ? atual.add(valor) : atual.delete(valor);
        estado.filtros[nome] = [...atual];
        estado.pagina = 1; buscar();
      });
      fs.appendChild(lab);
    }
    div.appendChild(fs);
  }
}

function renderPaginacao(corpo) {
  const nav = $("#paginacao");
  nav.replaceChildren();
  const ir = (p, txt, atual = false) => {
    const b = document.createElement("button");
    b.textContent = txt; b.className = atual ? "" : "sec"; b.disabled = atual;
    if (atual) b.setAttribute("aria-current", "page");
    b.addEventListener("click", () => { estado.pagina = p; buscar(); window.scrollTo(0, 0); });
    nav.appendChild(b);
  };
  if (corpo.pagina > 1) ir(corpo.pagina - 1, "‹ Anterior");
  for (let p = Math.max(1, corpo.pagina - 3); p <= Math.min(corpo.paginas, corpo.pagina + 3); p++) ir(p, String(p), p === corpo.pagina);
  if (corpo.pagina < corpo.paginas) ir(corpo.pagina + 1, "Próxima ›");
}

$("#form-busca").addEventListener("submit", (ev) => { ev.preventDefault(); estado.q = $("#q").value.trim(); estado.pagina = 1; buscar(); });
$("#colapsar").addEventListener("change", () => { estado.pagina = 1; buscar(); });
$("#semcache").addEventListener("change", buscar);
$("#limpar-filtros").addEventListener("click", () => { estado.filtros = {}; estado.pagina = 1; buscar(); });

document.addEventListener("click", async (ev) => {
  const ver = ev.target.closest("[data-ver]");
  const add = ev.target.closest("[data-add]");
  const rem = ev.target.closest("[data-rem]");
  if (ver) abrirDetalhe(ver.dataset.ver);
  if (add) {
    try { await api(`/api/carrinho/${encodeURIComponent(add.dataset.add)}`, { method: "POST" }); add.textContent = "Na lista ✓"; atualizarContador(); }
    catch (e) { alert(e.message); }
  }
  if (rem) { await api(`/api/carrinho/${encodeURIComponent(rem.dataset.rem)}`, { method: "DELETE" }); carregarLista(); }
});

// ------------------------------------------------------------------ detalhe (Markdown + LaTeX + Mermaid)
function renderMarkdown(md) {
  const html = sanitizar(marked.parse(md || "", { gfm: true, breaks: false }));
  const div = document.createElement("div");
  div.innerHTML = html;
  return div;
}

async function abrirDetalhe(id) {
  const dlg = $("#detalhe"), corpo = $("#det-corpo");
  corpo.textContent = "Carregando…";
  dlg.showModal();
  try {
    const { corpo: q } = await api(`/api/questoes/${encodeURIComponent(id)}`);
    $("#det-titulo").textContent = `${q.rotulo} — ${q.curso} (${q.ano})`;
    corpo.replaceChildren();
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `<span class="etq">${esc(q.area)}</span><span class="etq">${esc(q.componente)}</span><span class="etq">${esc(q.tipo_questao)}</span>
      ${q.anulada ? '<span class="etq anulada">ANULADA</span>' : ""}<span class="etq">extração: confiança ${esc(q.extracao?.confianca)}</span>`;
    corpo.appendChild(meta);
    if (q.texto_base_md) corpo.appendChild(renderMarkdown(q.texto_base_md));
    for (const f of q.midia?.figuras || []) {
      if (!f.arquivo) continue;
      const img = document.createElement("img");
      img.src = `/api/figuras/${f.arquivo}`; img.alt = `Figura recortada da página ${f.pagina} do PDF original`; img.loading = "lazy";
      corpo.appendChild(img);
    }
    for (const m of q.midia?.mermaid || []) {
      const d = document.createElement("pre"); d.className = "mermaid"; d.textContent = m; corpo.appendChild(d);
    }
    corpo.appendChild(renderMarkdown(q.enunciado_md || esc(q.enunciado)));
    for (const a of q.alternativas || []) {
      const d = document.createElement("div"); d.className = "alt";
      d.innerHTML = `<strong>${esc(a.letra)}</strong>`;
      d.appendChild(renderMarkdown(a.texto_md || a.texto));
      corpo.appendChild(d);
    }
    const orig = document.createElement("p");
    orig.className = "sutil";
    const pag = (q.origem?.paginas || [])[0] || 1;
    orig.innerHTML = `Origem: <a href="${esc(q.origem?.url || "#")}#page=${esc(pag)}" target="_blank" rel="noopener noreferrer">${esc(q.origem?.pdf)}</a>, página(s) ${esc((q.origem?.paginas || []).join(", "))}.
      Competências (inferidas): ${esc((q.competencias_ids || []).join(", ") || "—")} · Temas: ${esc((q.objetos_ids || []).join(", ") || "—")}`;
    corpo.appendChild(orig);
    if (q.midia?.pendencias?.length) {
      const p = document.createElement("p"); p.className = "sutil"; p.textContent = "Observação da extração: " + q.midia.pendencias.join("; "); corpo.appendChild(p);
    }
    const acoes = document.createElement("div"); acoes.className = "acoes";
    acoes.innerHTML = `<button id="btn-gab">Ver gabarito</button><button class="sec" id="btn-eq">Questões equivalentes em outros cursos</button><button class="sec" data-add="${esc(q.id)}">Adicionar à lista</button>`;
    corpo.appendChild(acoes);
    const saida = document.createElement("div"); corpo.appendChild(saida);
    $("#btn-gab").addEventListener("click", async () => {
      try {
        const { corpo: g } = await api(`/api/questoes/${encodeURIComponent(id)}/gabarito`);
        saida.className = "gabarito";
        saida.innerHTML = `<strong>Gabarito:</strong> ${esc(g.anulada ? "ANULADA" : g.gabarito || (q.tipo_questao === "discursiva" ? "discursiva (ver padrão de resposta)" : "indisponível"))} <span class="sutil">(${esc(g.fonte || "")})</span>`;
        if (g.padrao_resposta) { const pr = document.createElement("pre"); pr.textContent = g.padrao_resposta; saida.appendChild(pr); }
      } catch (e) { saida.className = "erro"; saida.textContent = `Acesso negado (HTTP ${e.status}): ${e.message}`; }
    });
    $("#btn-eq").addEventListener("click", async () => {
      const { corpo: eq } = await api(`/api/questoes/${encodeURIComponent(id)}/equivalentes`);
      saida.className = "";
      const mesmos = eq.mesma_questao_em_outros_cursos.map((x) => `<li><a href="#" data-ver="${esc(x.id)}">${esc(x.rotulo)} — ${esc(x.curso)} (${esc(x.ano)})</a></li>`).join("");
      const sem = eq.semelhantes_de_outros_cursos.map((x) => `<li><a href="#" data-ver="${esc(x.id)}">${esc(x.rotulo)} — ${esc(x.curso)} (${esc(x.ano)})</a> <span class="sutil">score ${Number(x._score).toFixed(1)}</span></li>`).join("");
      saida.innerHTML = `<h3>Mesma questão em outros cursos (${eq.mesma_questao_em_outros_cursos.length})</h3><ul>${mesmos || "<li>nenhuma</li>"}</ul>
        <h3>Questões semelhantes de outros cursos</h3><ul>${sem || "<li>nenhuma</li>"}</ul>`;
    });
    renderMathInElement(corpo, { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }], throwOnError: false });
    await mermaid.run({ nodes: corpo.querySelectorAll(".mermaid") });
  } catch (e) { corpo.textContent = `Erro: ${e.message}`; }
}
$("#fechar").addEventListener("click", () => $("#detalhe").close());

// ------------------------------------------------------------------ lista
async function atualizarContador() {
  try { const { corpo } = await api("/api/carrinho"); $("#cont-lista").textContent = corpo.total; } catch {}
}
async function carregarLista() {
  const { corpo } = await api("/api/carrinho");
  $("#cont-lista").textContent = corpo.total;
  $("#ttl-lista").textContent = corpo.ttl_segundos > 0 ? `Expira em ${Math.round(corpo.ttl_segundos / 60)} min sem uso.` : "";
  const ol = $("#itens-lista"); ol.replaceChildren();
  for (const q of corpo.itens) {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${esc(q.rotulo)}</strong> — ${esc(q.curso)} (${esc(q.ano)}) <div class="acoes"><button class="sec" data-ver="${esc(q.id)}">Ver</button><button class="sec" data-rem="${esc(q.id)}">Remover</button></div>`;
    ol.appendChild(li);
  }
}
$("#esvaziar").addEventListener("click", async () => { await api("/api/carrinho", { method: "DELETE" }); carregarLista(); });

// ------------------------------------------------------------------ painel analítico (Professor)
function tabelaSerie(serie, anos, nomes) {
  const max = Math.max(1, ...serie.flatMap((s) => anos.map((a) => s.por_ano[a] || 0)));
  const cab = anos.map((a) => `<th>${esc(a)}</th>`).join("");
  const linhas = serie.map((s) => `<tr><th title="${esc(nomes[s.chave] || "")}">${esc(s.chave)} ${esc((nomes[s.chave] || "").slice(0, 48))}</th>${anos.map((a) => {
    const v = s.por_ano[a] || 0;
    return `<td><div class="barra" style="width:${Math.round((v / max) * 120)}px" aria-hidden="true"></div>${v}</td>`;
  }).join("")}</tr>`).join("");
  return `<table><caption class="sutil">número de questões (eixo: ano da edição)</caption><thead><tr><th>Categoria</th>${cab}</tr></thead><tbody>${linhas}</tbody></table>`;
}
async function carregarPainel() {
  try {
    const { corpo } = await api(`/api/analitico?${parametros()}`);
    $("#graf-competencias").innerHTML = tabelaSerie(corpo.competencias_por_ano, corpo.anos, estado.tax.competencias);
    $("#graf-objetos").innerHTML = tabelaSerie(corpo.objetos_por_ano, corpo.anos, estado.tax.temas);
    const max = Math.max(1, ...corpo.por_curso.map((c) => c.total));
    $("#graf-cursos").innerHTML = `<table><thead><tr><th>Curso</th><th>Questões</th><th>FG</th><th>CE</th><th>Anuladas</th><th>Edições</th></tr></thead><tbody>${corpo.por_curso.map((c) =>
      `<tr><th>${esc(c.curso)}</th><td><div class="barra" style="width:${Math.round((c.total / max) * 160)}px"></div>${c.total}</td><td>${c.componente.FG || 0}</td><td>${c.componente.CE || 0}</td><td>${c.anuladas}</td><td>${esc(c.anos.join(", "))}</td></tr>`).join("")}</tbody></table>`;
  } catch (e) { $("#graf-competencias").textContent = `Erro (HTTP ${e.status}): ${e.message}`; }
}

// ------------------------------------------------------------------ operação
async function carregarOperacao() {
  const mostrar = async (sel, url) => {
    try { const r = await fetch(url, { credentials: "same-origin" }); $(sel).textContent = JSON.stringify(await r.json(), null, 1); }
    catch (e) { $(sel).textContent = e.message; }
  };
  mostrar("#saude", "/health/ready"); mostrar("#cache", "/api/admin/cache"); mostrar("#ingestao", "/api/admin/ingestao");
}
$("#invalidar").addEventListener("click", async () => { await api("/api/admin/cache/invalidar", { method: "POST" }); carregarOperacao(); });

iniciar();
