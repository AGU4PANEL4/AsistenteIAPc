// =====================================================================
// Metadatos de categoria
// =====================================================================
const CATEGORIAS = {
  temporizadores: { icono: "⏱", nombre: "Temporizadores", color: "var(--acento)" },
  recordatorios:  { icono: "🔔", nombre: "Recordatorios",  color: "var(--amarillo)" },
  alias:          { icono: "🔗", nombre: "Alias",          color: "var(--acento)" },
  macros:         { icono: "▶",  nombre: "Macros",         color: "var(--texto)" },
};

// Paletas
const PALETA_BASE = {
  "--bg": "#0b1a1f", "--bg2": "#10262c", "--borde": "#1c3a3f", "--borde2": "#162c31",
  "--acento": "#2de6c0", "--texto": "#7fb3ad", "--texto-dim": "#3a5a5c",
  "--rojo": "#ff5566", "--verde": "#2de6c0", "--amarillo": "#e6c02d", "--dormido": "#8b9ae8",
};
const PALETA_DORMIDO = {
  "--bg": "#12101f", "--bg2": "#1a1730", "--borde": "#2d2850", "--borde2": "#252040",
  "--acento": "#a78bfa", "--texto": "#9b8ec7", "--texto-dim": "#5a4e7a",
  "--rojo": "#ff6b8a", "--verde": "#a78bfa", "--amarillo": "#c4b5fd", "--dormido": "#a78bfa",
};

// Colores SVG por estado
const COLORES_SVG = {
  inactivo:   { ojo: "#3a5a5c", boca: "#3a5a5c", borde: "#1c3a3f", bg2: "#10262c" },
  escuchando: { ojo: "#2de6c0", boca: "#2de6c0", borde: "#2de6c0", bg2: "#10262c" },
  procesando: { ojo: "#e6c02d", boca: "#e6c02d", borde: "#e6c02d", bg2: "#10262c" },
  hablando:   { ojo: "#2de6c0", boca: "#2de6c0", borde: "#2de6c0", bg2: "#10262c" },
  buscando:   { ojo: "#e6c02d", boca: "#e6c02d", borde: "#e6c02d", bg2: "#10262c" },
  dormido:    { ojo: "#a78bfa", boca: "#a78bfa", borde: "#a78bfa", bg2: "#1a1730" },
};

// Colores motor identitarios (solo en modos normales)
const COLORES_MOTOR = {
  "Groq":   "#2de6c0",
  "Ollama": "#f97316",
  "—":      "#7fb3ad",
};

const TEXTOS_ESTADO = {
  inactivo:   'Inactivo — di "jarvis"',
  escuchando: "Escuchando...",
  procesando: "Procesando...",
  buscando:   "Buscando app...",
  hablando:   "Hablando...",
  dormido:    "Durmiendo...",
};

let catFlotanteActual = null;
let firmasPrevias = {};
let estadoOrbe = { modo: "inactivo", noMolestar: false, orbFase: 0, zFase: 0, parpadeoCuenta: 30, ojosCerrados: false };
let modoAnterior = "inactivo";
let tickActivo = false;

function randInt(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }

function expandirPanel() {
  document.getElementById("panel").classList.remove("colapsando");
  document.getElementById("panel").classList.add("expandido");
}
function colapsarPanel() {
  document.getElementById("panel").classList.remove("expandido");
  document.getElementById("panel").classList.add("colapsando");
  pywebview.api.colapsar().catch(() => {});
}

// ═══════════════════════════════════════════════════════════════════
// PALETA
// ═══════════════════════════════════════════════════════════════════
function aplicarPaleta(paleta) {
  const root = document.documentElement;
  for (const [key, val] of Object.entries(paleta)) root.style.setProperty(key, val);
}
function restaurarPaletaBase() { aplicarPaleta(PALETA_BASE); }
function aplicarPaletaDormido() { aplicarPaleta(PALETA_DORMIDO); }

// ═══════════════════════════════════════════════════════════════════
// ORBE
// ═══════════════════════════════════════════════════════════════════
function actualizarOrbeVisual() {
  const modo = estadoOrbe.modo;
  const c = COLORES_SVG[modo] || COLORES_SVG.inactivo;
  const noMolestar = estadoOrbe.noMolestar;

  // Paleta del panel
  if (modo === "dormido" && modoAnterior !== "dormido") aplicarPaletaDormido();
  else if (modo !== "dormido" && modoAnterior === "dormido") restaurarPaletaBase();
  modoAnterior = modo;

  // Clases
  const circulo = document.getElementById("orbe-circulo");
  const estadoTexto = document.getElementById("orbe-estado-texto");
  const metricas = document.getElementById("metricas");
  if (circulo) circulo.className = "estado-" + modo;
  if (estadoTexto) estadoTexto.className = "estado-" + modo;
  if (metricas) metricas.className = "estado-" + modo;

  // Circulo base
  const base = document.getElementById("orbe-base");
  if (base) { base.setAttribute("fill", c.bg2); base.setAttribute("stroke", c.borde); }

  // Ojos
  const ojoIzq = document.getElementById("ojo-izq");
  const ojoDer = document.getElementById("ojo-der");
  const ojoIzqC = document.getElementById("ojo-izq-cerrado");
  const ojoDerC = document.getElementById("ojo-der-cerrado");

  if (modo === "dormido") {
    if (ojoIzq) ojoIzq.style.display = "none";
    if (ojoDer) ojoDer.style.display = "none";
    if (ojoIzqC) { ojoIzqC.style.display = "block"; ojoIzqC.setAttribute("stroke", c.ojo); }
    if (ojoDerC) { ojoDerC.style.display = "block"; ojoDerC.setAttribute("stroke", c.ojo); }
  } else {
    if (estadoOrbe.ojosCerrados) {
      if (ojoIzq) ojoIzq.style.display = "none";
      if (ojoDer) ojoDer.style.display = "none";
      if (ojoIzqC) { ojoIzqC.style.display = "block"; ojoIzqC.setAttribute("stroke", c.ojo); }
      if (ojoDerC) { ojoDerC.style.display = "block"; ojoDerC.setAttribute("stroke", c.ojo); }
    } else {
      if (ojoIzq) { ojoIzq.style.display = "block"; ojoIzq.setAttribute("fill", c.ojo); }
      if (ojoDer) { ojoDer.style.display = "block"; ojoDer.setAttribute("fill", c.ojo); }
      if (ojoIzqC) ojoIzqC.style.display = "none";
      if (ojoDerC) ojoDerC.style.display = "none";
    }
  }

  // Boca
  const bNeutra = document.getElementById("boca-neutra");
  const bHablando = document.getElementById("boca-hablando");
  const bEscuchando = document.getElementById("boca-escuchando");
  const bDormido = document.getElementById("boca-dormido");

  if (bNeutra) bNeutra.style.display = "none";
  if (bHablando) bHablando.style.display = "none";
  if (bEscuchando) bEscuchando.style.display = "none";
  if (bDormido) { bDormido.style.display = "none"; bDormido.classList.remove("respirando"); }

  if (modo === "hablando") {
    if (bHablando) { bHablando.style.display = "block"; bHablando.setAttribute("stroke", c.boca); }
  } else if (modo === "escuchando") {
    if (bEscuchando) { bEscuchando.style.display = "block"; bEscuchando.setAttribute("fill", c.boca); }
  } else if (modo === "dormido") {
    if (bDormido) { bDormido.style.display = "block"; bDormido.setAttribute("fill", c.boca); bDormido.classList.add("respirando"); }
  } else {
    if (bNeutra) { bNeutra.style.display = "block"; bNeutra.setAttribute("stroke", c.boca); }
  }

  // Z flotantes
  const zFlot = document.getElementById("z-flotantes");
  if (zFlot) zFlot.style.display = modo === "dormido" ? "block" : "none";

  // DND
  const dnd = document.getElementById("dnd-indicador");
  if (dnd) dnd.style.display = noMolestar ? "block" : "none";

  // Texto estado
  if (estadoTexto) estadoTexto.textContent = TEXTOS_ESTADO[modo] || modo;
}

// ═══════════════════════════════════════════════════════════════════
// TICK ORBE
// ═══════════════════════════════════════════════════════════════════
let lastTick = 0;
function tickOrbe(ts) {
  if (!tickActivo) return;
  if (ts - lastTick >= 60) {
    lastTick = ts;
    estadoOrbe.orbFase = (estadoOrbe.orbFase + 0.18) % (2 * Math.PI);
    estadoOrbe.zFase = (estadoOrbe.zFase + 0.03) % (2 * Math.PI);
    if (estadoOrbe.modo !== "dormido") {
      estadoOrbe.parpadeoCuenta -= 1;
      if (estadoOrbe.parpadeoCuenta <= -3) { estadoOrbe.ojosCerrados = false; estadoOrbe.parpadeoCuenta = randInt(30, 90); }
      else if (estadoOrbe.parpadeoCuenta <= 0) estadoOrbe.ojosCerrados = true;
    } else {
      estadoOrbe.ojosCerrados = true;
    }
    actualizarOrbeVisual();
  }
  requestAnimationFrame(tickOrbe);
}
function iniciarTickOrbe() {
  if (tickActivo) return;
  tickActivo = true;
  lastTick = performance.now();
  requestAnimationFrame(tickOrbe);
}

// Mini orbe
function programarParpadeoMini() {
  const ojoI = document.getElementById("mini-ojo-izq");
  const ojoD = document.getElementById("mini-ojo-der");
  if (!ojoI || !ojoD) return;
  ojoI.classList.add("cerrado");
  ojoD.classList.add("cerrado");
  setTimeout(() => {
    ojoI.classList.remove("cerrado");
    ojoD.classList.remove("cerrado");
    setTimeout(programarParpadeoMini, 2000 + Math.random() * 3000);
  }, 140);
}
function actualizarMiniBoca(modo) {
  const boca = document.getElementById("mini-boca");
  if (!boca) return;
  if (modo === "hablando") boca.setAttribute("d", "M 8 16.5 Q 11 20 14 16.5");
  else if (modo === "escuchando") boca.setAttribute("d", "M 10.3 17.3 A 1.7 1.7 0 1 0 13.7 17.3 A 1.7 1.7 0 1 0 10.3 17.3");
  else boca.setAttribute("d", "M 8.5 17.5 L 13.5 17.5");
}

// Arrastre
(function habilitarArrastre() {
  const header = document.getElementById("header");
  if (!header) return;
  let arrastrando = false, x0 = 0, y0 = 0;
  header.addEventListener("mousedown", (e) => {
    if (e.target.closest("button, #mini-orbe")) return;
    arrastrando = true; x0 = e.screenX; y0 = e.screenY;
  });
  window.addEventListener("mousemove", (e) => {
    if (!arrastrando) return;
    const dx = e.screenX - x0, dy = e.screenY - y0;
    x0 = e.screenX; y0 = e.screenY;
    pywebview.api.mover_ventana(dx, dy);
  });
  window.addEventListener("mouseup", () => { arrastrando = false; });
})();

// Categorias
async function abrirCategoria(cat) {
  if (catFlotanteActual === cat) { cerrarFlotante(); return; }
  catFlotanteActual = cat;
  document.querySelectorAll(".cat-card").forEach(c => c.classList.remove("abierta"));
  const catEl = document.getElementById("cat-" + cat);
  if (catEl) catEl.classList.add("abierta");
  const ft = document.getElementById("flotante-titulo");
  if (ft) ft.textContent = CATEGORIAS[cat].icono + "  " + CATEGORIAS[cat].nombre;
  document.getElementById("overlay").classList.add("activo");
  document.getElementById("flotante").classList.add("activo");
  await refrescarListaFlotante();
}
async function refrescarListaFlotante() {
  if (!catFlotanteActual) return;
  const items = await pywebview.api.listar_categoria(catFlotanteActual);
  const cont = document.getElementById("flotante-lista");
  cont.innerHTML = "";
  if (!items.length) { cont.innerHTML = '<div class="hist-vacio">Nada por aca todavia.</div>'; return; }
  for (const it of items) {
    const fila = document.createElement("div");
    fila.className = "fila-item";
    fila.innerHTML = '<div><div class="txt">' + escapeHtml(it.principal) + '</div>' + (it.secundario ? '<div class="sub">' + escapeHtml(it.secundario) + '</div>' : "") + '</div><button title="quitar">×</button>';
    fila.querySelector("button").onclick = async () => { await pywebview.api.eliminar_item(catFlotanteActual, it.clave); await refrescarListaFlotante(); await refrescarCategorias(); };
    cont.appendChild(fila);
  }
}
function cerrarFlotante() {
  catFlotanteActual = null;
  document.querySelectorAll(".cat-card").forEach(c => c.classList.remove("abierta"));
  document.getElementById("overlay").classList.remove("activo");
  document.getElementById("flotante").classList.remove("activo");
}
function escapeHtml(s) { return (s || "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[c]); }

function renderCategoriasBase() {
  const grid = document.getElementById("categorias");
  grid.innerHTML = "";
  for (const cat of Object.keys(CATEGORIAS)) {
    const meta = CATEGORIAS[cat];
    const card = document.createElement("div");
    card.className = "cat-card";
    card.id = "cat-" + cat;
    card.style.setProperty("--cat-color", meta.color);
    card.onclick = () => abrirCategoria(cat);
    card.innerHTML = '<div class="cat-cabecera"><span class="cat-icono">' + meta.icono + '</span><span class="cat-nombre">' + meta.nombre + '</span><span class="cat-conteo" id="conteo-' + cat + '">0</span></div><div class="cat-resumen" id="resumen-' + cat + '">—</div>';
    grid.appendChild(card);
  }
}
async function refrescarCategorias() {
  const resumen = await pywebview.api.resumen_categorias();
  for (const cat of Object.keys(CATEGORIAS)) {
    const datos = resumen[cat] || { conteo: 0, lineas: [] };
    const ce = document.getElementById("conteo-" + cat);
    const re = document.getElementById("resumen-" + cat);
    if (ce) ce.textContent = datos.conteo;
    if (re) re.textContent = datos.lineas.length ? datos.lineas.join("\n") : "—";
    const firma = JSON.stringify(datos);
    if (firmasPrevias[cat] !== undefined && firmasPrevias[cat] !== firma) {
      const card = document.getElementById("cat-" + cat);
      if (card) { card.classList.remove("pulso"); void card.offsetWidth; card.classList.add("pulso"); }
    }
    firmasPrevias[cat] = firma;
  }
  if (catFlotanteActual) refrescarListaFlotante();
}

async function refrescarHistorial() {
  const items = await pywebview.api.historial();
  const cont = document.getElementById("historial-lista");
  if (!items.length) { cont.innerHTML = '<div class="hist-vacio">Todavia no hay comandos.<br>Deci "jarvis" para empezar.</div>'; return; }
  cont.innerHTML = items.slice().reverse().map(h => {
    const ts = escapeHtml(h.ts || ""), cmd = escapeHtml(h.cmd || ""), resp = escapeHtml(h.resp || "");
    let linea = '<div class="hist-item" style="color:var(--acento)">  ' + ts + '  ›  ' + cmd + '</div>';
    if (resp) linea += '<div class="hist-item" style="color:var(--texto);padding-left:14px">      ' + (resp.length > 38 ? resp.slice(0, 38) + "…" : resp) + '</div>';
    return linea;
  }).join("");
}

// ═══════════════════════════════════════════════════════════════════
// ESTADO — motor tematizado segun modo
// ═══════════════════════════════════════════════════════════════════
async function refrescarEstado() {
  let e;
  try { e = await pywebview.api.get_estado(); } catch (err) { return; }

  const modoPrev = estadoOrbe.modo;
  estadoOrbe.modo = e.modo;
  estadoOrbe.noMolestar = e.no_molestar;

  if (e.modo !== modoPrev) actualizarOrbeVisual();

  // Header
  const hm = document.getElementById("header-modo");
  const hs = document.getElementById("header-sub");
  const hmo = document.getElementById("header-motor");
  if (hm) hm.textContent = e.texto_modo;
  if (hs) hs.textContent = e.motor + " · " + e.wake_word;

  // MOTOR TEMATIZADO:
  // - En modo dormido: usa var(--acento) que es morado
  // - En modos normales: usa color identitario del motor
  const esDormido = e.modo === "dormido";
  const colorMotor = esDormido ? getComputedStyle(document.documentElement).getPropertyValue("--acento").trim() : (COLORES_MOTOR[e.motor] || COLORES_MOTOR["—"]);

  if (hmo) {
    hmo.textContent = e.motor;
    hmo.style.color = colorMotor;
    hmo.style.border = "1px solid " + colorMotor;
    hmo.style.boxShadow = "0 0 8px " + hexToRgba(colorMotor, 0.25);
  }

  // Métricas
  const mw = document.getElementById("m-wake");
  const mm = document.getElementById("m-motor");
  const md = document.getElementById("m-dnd");
  if (mw) mw.textContent = e.wake_word;
  if (mm) { mm.textContent = e.motor; mm.style.color = colorMotor; }
  if (md) { md.textContent = e.no_molestar ? "on" : "off"; md.style.color = e.no_molestar ? "var(--rojo)" : "var(--texto)"; }

  actualizarMiniBoca(e.modo);
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
}

// ═══════════════════════════════════════════════════════════════════
// INICIO
// ═══════════════════════════════════════════════════════════════════
async function iniciarLoops() {
  await refrescarEstado();
  await refrescarCategorias();
  await refrescarHistorial();
  actualizarOrbeVisual();
  setInterval(refrescarEstado, 400);
  setInterval(() => { refrescarCategorias(); refrescarHistorial(); }, 1200);
  iniciarTickOrbe();
  programarParpadeoMini();
}

renderCategoriasBase();
if (window.pywebview) iniciarLoops();
else window.addEventListener("pywebviewready", iniciarLoops);