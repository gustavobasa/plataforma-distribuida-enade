// RNF01 — Teste de carga da busca com k6 (latência p50/p95/p99 com e sem cache Redis).
// Execução (via Compose): docker compose --profile carga run --rm k6
//
// Cenário "sem_cache": cada requisição usa ?cache=false (consulta sempre o Elasticsearch).
// Cenário "com_cache": mesmas consultas com cache habilitado; uma fase de aquecimento preenche o Redis antes.
// As consultas vêm de um conjunto fixo de termos e filtros (reprodutível).
import http from "k6/http";
import { check } from "k6";
import { Trend, Rate } from "k6/metrics";

const API = __ENV.API_URL || "http://api:8000";
const RPS = Number(__ENV.RPS || 20);
const DURACAO = __ENV.DURACAO || "60s";

const latSem = new Trend("latencia_sem_cache", true);
const latCom = new Trend("latencia_com_cache", true);
const hit = new Rate("cache_hit_rate");

const TERMOS = ["ética", "desigualdade social", "sustentabilidade", "inteligência artificial", "saúde pública",
  "algoritmo", "direitos humanos", "educação inclusiva", "meio ambiente", "democracia", "vacinação",
  "banco de dados", "trabalho", "cultura", "política pública", "violência", "tecnologia", "economia",
  "fome", "saneamento", "acessibilidade", "redes de computadores", "gestão", "comunicação", "racismo",
  "envelhecimento", "energia", "programação", "estatística", "urbanização"];
const FILTROS = ["", "&ano=2023", "&componente=FG", "&tipo=objetiva", "&ano=2022&componente=CE", "&area=Ciências da Saúde"];

export const options = {
  summaryTrendStats: ["avg", "min", "med", "p(50)", "p(95)", "p(99)", "max", "count"],
  scenarios: {
    sem_cache: { executor: "constant-arrival-rate", rate: RPS, timeUnit: "1s", duration: DURACAO,
      preAllocatedVUs: 20, maxVUs: 60, exec: "semCache" },
    aquecimento: { executor: "per-vu-iterations", vus: 1, iterations: 1, startTime: `${parseInt(DURACAO) + 5}s`,
      exec: "aquecer", maxDuration: "120s" },
    com_cache: { executor: "constant-arrival-rate", rate: RPS, timeUnit: "1s", duration: DURACAO,
      startTime: `${parseInt(DURACAO) + 40}s`, preAllocatedVUs: 20, maxVUs: 60, exec: "comCache" },
  },
  thresholds: { "http_req_failed": ["rate<0.01"] },
};

export function setup() {
  const r = http.post(`${API}/api/auth/login`, JSON.stringify({ usuario: "estudante1", senha: __ENV.SENHA }),
    { headers: { "Content-Type": "application/json" } });
  check(r, { "login 200": (x) => x.status === 200 });
  return { token: r.json("token") };
}

function consulta(i) {
  const t = TERMOS[i % TERMOS.length];
  const f = FILTROS[Math.floor(i / TERMOS.length) % FILTROS.length];
  return `q=${encodeURIComponent(t)}${encodeURI(f)}`;
}

const headers = (d) => ({ headers: { Authorization: `Bearer ${d.token}` } });

export function semCache(d) {
  const i = Math.floor(Math.random() * TERMOS.length * FILTROS.length);
  const r = http.get(`${API}/api/busca?${consulta(i)}&cache=false`, headers(d));
  check(r, { "200": (x) => x.status === 200 });
  latSem.add(r.timings.duration);
}

export function aquecer(d) {
  for (let i = 0; i < TERMOS.length * FILTROS.length; i++) {
    const r = http.get(`${API}/api/busca?${consulta(i)}`, headers(d));
    check(r, { "aquecimento 200": (x) => x.status === 200 });
  }
}

export function comCache(d) {
  const i = Math.floor(Math.random() * TERMOS.length * FILTROS.length);
  const r = http.get(`${API}/api/busca?${consulta(i)}`, headers(d));
  check(r, { "200": (x) => x.status === 200 });
  latCom.add(r.timings.duration);
  hit.add(r.headers["X-Cache"] === "HIT");
}
