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

// Colores motor identitarios
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

// =====================================================================
// ANIMACIONES IDLE — 2 por estado, selección aleatoria
// =====================================================================
const ANIMACIONES_IDLE = {
  inactivo:   ["idle-slow-blink", "idle-look-around"],
  escuchando: ["idle-alert-scan", "idle-focus-nod"],
  procesando: ["idle-think-wave", "idle-look-up"],
  hablando:   ["idle-content-sigh", "idle-happy-bounce"],
  buscando:   ["idle-scan-sweep", "idle-search-pulse"],
  dormido:    ["idle-deep-snore", "idle-drowsy-peek"],
};

const DURACION_ANIMACION = {
  "idle-slow-blink":    2500,
  "idle-look-around":   2200,
  "idle-alert-scan":    1500,
  "idle-focus-nod":     1800,
  "idle-think-wave":    2000,
  "idle-look-up":       2000,
  "idle-content-sigh":  2500,
  "idle-happy-bounce":  1200,
  "idle-scan-sweep":    1500,
  "idle-search-pulse":  2000,
  "idle-deep-snore":    2500,
  "idle-drowsy-peek":   3000,
};

let catFlotanteActual = null;
let firmasPrevias = {};
let estadoOrbe = { modo: "inactivo", noMolestar: false, orbFase: 0, zFase: 0, parpadeoCuenta: 30, ojosCerrados: false, hoverOrbe: false };
let modoAnterior = "inactivo";
let tickActivo = false;
let bocaAnimId = null;
let aliasGruposExpandidos = {};

// Idle animation state
let idleState = {
  ultimaActividad: 0,
  timerId: null,
  animando: false,
  claseActual: null,
};

// Dizzy / mareo state
let dizzyState = {
  activo: false,
  timerRecuperacion: null,
  eraDormido: false,
};

function randInt(min, max) { return Math.floor(Math.random() * (max - min + 1)) + min; }

function expandirPanel() {
  document.getElementById("panel").classList.remove("colapsando");
  document.getElementById("panel").classList.add("expandido");
}
function colapsarPanel() {
  document.getElementById("panel").classList.remove("expandido");
  document.getElementById("panel").classList.add("colapsando");
  pywebview.api.colapsar().catch(function() {});
}

// =====================================================================
// PALETA
// =====================================================================
function aplicarPaleta(paleta) {
  const root = document.documentElement;
  for (const key in paleta) {
    root.style.setProperty(key, paleta[key]);
  }
}
function restaurarPaletaBase() { aplicarPaleta(PALETA_BASE); }
function aplicarPaletaDormido() { aplicarPaleta(PALETA_DORMIDO); }

// =====================================================================
// SISTEMA DE ANIMACIONES IDLE
// =====================================================================

function resetIdleTimer() {
  idleState.ultimaActividad = performance.now();
  if (idleState.timerId) {
    clearTimeout(idleState.timerId);
    idleState.timerId = null;
  }
  if (idleState.animando && idleState.claseActual) {
    const wrap = document.getElementById("orbe-wrap");
    if (wrap) wrap.classList.remove(idleState.claseActual);
    idleState.animando = false;
    idleState.claseActual = null;
  }
  programarProximaIdle();
}

function programarProximaIdle() {
  if (idleState.timerId) clearTimeout(idleState.timerId);
  const delay = randInt(3000, 8000);
  idleState.timerId = setTimeout(ejecutarIdleAleatoria, delay);
}

function ejecutarIdleAleatoria() {
  if (idleState.animando || dizzyState.activo) return;

  const modo = estadoOrbe.modo;
  const anims = ANIMACIONES_IDLE[modo];
  if (!anims || anims.length === 0) {
    programarProximaIdle();
    return;
  }

  const claseAnim = anims[randInt(0, anims.length - 1)];
  const duracion = DURACION_ANIMACION[claseAnim] || 2000;

  const wrap = document.getElementById("orbe-wrap");
  if (!wrap) {
    programarProximaIdle();
    return;
  }

  idleState.animando = true;
  idleState.claseActual = claseAnim;
  wrap.classList.add(claseAnim);

  setTimeout(function() {
    wrap.classList.remove(claseAnim);
    idleState.animando = false;
    idleState.claseActual = null;
    programarProximaIdle();
  }, duracion);
}

// =====================================================================
// SISTEMA DE MAREO / DIZZY (arrastre rápido)
// =====================================================================

function triggerDizzy() {
  if (dizzyState.activo) return; // Ya está mareado

  const wrap = document.getElementById("orbe-wrap");
  if (!wrap) return;

  dizzyState.activo = true;
  dizzyState.eraDormido = estadoOrbe.modo === "dormido";
  dizzyState.modoOriginal = estadoOrbe.modo; // Guardar modo original para colores

  // Aplicar clase de mareo
  wrap.classList.add("dizzy-active");

  // Actualizar colores de las espirales según el modo ORIGINAL (no cambiar paleta)
  const c = COLORES_SVG[dizzyState.modoOriginal] || COLORES_SVG.inactivo;
  const spiralIzq = document.querySelector("#spiral-izq path");
  const spiralDer = document.querySelector("#spiral-der path");
  if (spiralIzq) spiralIzq.setAttribute("stroke", c.ojo);
  if (spiralDer) spiralDer.setAttribute("stroke", c.ojo);

  // Actualizar color de la boca dizzy también
  const bDizzy = document.getElementById("boca-dizzy");
  if (bDizzy) bDizzy.setAttribute("stroke", c.boca);

  // Ocultar Z's durante el mareo (se despertó momentáneamente)
  const zFlot = document.getElementById("z-flotantes");
  if (zFlot) zFlot.style.display = "none";

  // Cancelar cualquier idle animation en curso
  if (idleState.animando && idleState.claseActual) {
    wrap.classList.remove(idleState.claseActual);
    idleState.animando = false;
    idleState.claseActual = null;
  }
  if (idleState.timerId) {
    clearTimeout(idleState.timerId);
    idleState.timerId = null;
  }

  // Estado texto: mareo
  const estadoTexto = document.getElementById("orbe-estado-texto");
  if (estadoTexto) estadoTexto.textContent = "¡Uy!";

  // Después de 2.5s, recuperarse
  dizzyState.timerRecuperacion = setTimeout(function() {
    wrap.classList.remove("dizzy-active");
    dizzyState.activo = false;

    // Restaurar Z's si estaba dormido
    if (dizzyState.eraDormido) {
      const zFlot = document.getElementById("z-flotantes");
      if (zFlot) zFlot.style.display = "block";
    }

    dizzyState.eraDormido = false;
    dizzyState.modoOriginal = null;

    actualizarOrbeVisual();
    programarProximaIdle();
  }, 2500);
}

// =====================================================================
// ORBE VISUAL
// =====================================================================

function actualizarOrbeVisual() {
  const modo = estadoOrbe.modo;
  const c = COLORES_SVG[modo] || COLORES_SVG.inactivo;
  const noMolestar = estadoOrbe.noMolestar;

  if (modo === "dormido" && modoAnterior !== "dormido") aplicarPaletaDormido();
  else if (modo !== "dormido" && modoAnterior === "dormido") restaurarPaletaBase();
  modoAnterior = modo;

  const circulo = document.getElementById("orbe-circulo");
  const estadoTexto = document.getElementById("orbe-estado-texto");
  const metricas = document.getElementById("metricas");
  if (circulo) circulo.className = "estado-" + modo;
  if (estadoTexto && !dizzyState.activo) estadoTexto.className = "estado-" + modo;
  if (metricas) metricas.className = "estado-" + modo;

  const base = document.getElementById("orbe-base");
  if (base) { base.setAttribute("fill", c.bg2); base.setAttribute("stroke", c.borde); }

  // === OJOS ===
  const ojosAbiertos = document.getElementById("ojos-abiertos");
  const ojosCerrados = document.getElementById("ojos-cerrados");
  const ojosDrowsy = document.getElementById("ojos-drowsy");
  const ojosSpiral = document.getElementById("ojos-spiral");
  const pupilaIzq = document.getElementById("pupila-izq");
  const pupilaDer = document.getElementById("pupila-der");
  const cerradoIzq = document.getElementById("cerrado-izq");
  const cerradoDer = document.getElementById("cerrado-der");
  const drowsyIzq = document.getElementById("drowsy-izq");
  const drowsyDer = document.getElementById("drowsy-der");

  const ojosVisibles = !estadoOrbe.ojosCerrados && modo !== "dormido";

  if (ojosAbiertos) ojosAbiertos.style.display = ojosVisibles ? "block" : "none";
  if (ojosCerrados) ojosCerrados.style.display = (modo === "dormido" || estadoOrbe.ojosCerrados) ? "block" : "none";
  if (ojosDrowsy) ojosDrowsy.style.display = "none";
  if (ojosSpiral) ojosSpiral.style.display = "none";

  const colorOjo = c.ojo;
  if (pupilaIzq) pupilaIzq.setAttribute("fill", colorOjo);
  if (pupilaDer) pupilaDer.setAttribute("fill", colorOjo);
  if (cerradoIzq) cerradoIzq.setAttribute("stroke", colorOjo);
  if (cerradoDer) cerradoDer.setAttribute("stroke", colorOjo);
  if (drowsyIzq) drowsyIzq.setAttribute("stroke", colorOjo);
  if (drowsyDer) drowsyDer.setAttribute("stroke", colorOjo);

  const brilloIzq = document.getElementById("brillo-izq");
  const brilloDer = document.getElementById("brillo-der");
  const mostrarBrillo = estadoOrbe.hoverOrbe || modo === "escuchando" || modo === "hablando";
  if (brilloIzq) brilloIzq.style.display = (ojosVisibles && mostrarBrillo) ? "block" : "none";
  if (brilloDer) brilloDer.style.display = (ojosVisibles && mostrarBrillo) ? "block" : "none";

  // === BOCA ===
  const bNeutra = document.getElementById("boca-neutra");
  const bHablando = document.getElementById("boca-hablando");
  const bEscuchando = document.getElementById("boca-escuchando");
  const bDormido = document.getElementById("boca-dormido");
  const bSonrisa = document.getElementById("boca-sonrisa");
  const bDizzy = document.getElementById("boca-dizzy");

  if (bNeutra) bNeutra.style.display = "none";
  if (bHablando) bHablando.style.display = "none";
  if (bEscuchando) bEscuchando.style.display = "none";
  if (bDormido) { bDormido.style.display = "none"; bDormido.classList.remove("respirando"); }
  if (bSonrisa) bSonrisa.style.display = "none";
  if (bDizzy) bDizzy.style.display = "none";

  if (bocaAnimId) cancelAnimationFrame(bocaAnimId);
  bocaAnimId = null;

  if (dizzyState.activo) {
    // MODO MAREO: boca zigzag con color del estado
    if (bDizzy) {
      bDizzy.style.display = "block";
      bDizzy.setAttribute("stroke", c.boca);
    }
  } else if (estadoOrbe.hoverOrbe && modo === "inactivo") {
    if (bSonrisa) { bSonrisa.style.display = "block"; bSonrisa.setAttribute("stroke", c.boca); }
  } else if (modo === "hablando") {
    if (bHablando) { bHablando.style.display = "block"; bHablando.setAttribute("stroke", c.boca); animarBocaHablando(bHablando, c.boca); }
  } else if (modo === "escuchando") {
    if (bEscuchando) { bEscuchando.style.display = "block"; bEscuchando.setAttribute("fill", c.boca); }
  } else if (modo === "dormido") {
    if (bDormido) { bDormido.style.display = "block"; bDormido.setAttribute("fill", c.boca); bDormido.classList.add("respirando"); }
  } else {
    if (bNeutra) { bNeutra.style.display = "block"; bNeutra.setAttribute("stroke", c.boca); animarBocaNeutra(bNeutra, c.boca); }
  }

  const zFlot = document.getElementById("z-flotantes");
  if (zFlot) zFlot.style.display = modo === "dormido" ? "block" : "none";

  const dnd = document.getElementById("dnd-indicador");
  if (dnd) dnd.style.display = noMolestar ? "block" : "none";

  if (estadoTexto && !dizzyState.activo) estadoTexto.textContent = TEXTOS_ESTADO[modo] || modo;
}

// === ANIMACIONES DE BOCA ===

function animarBocaNeutra(pathEl, color) {
  function tick() {
    const t = performance.now() / 1000;
    const curvatura = Math.sin(t * 1.5) * 1.5;
    const yControl = 55 + curvatura;
    pathEl.setAttribute("d", "M 44 55 Q 48 " + yControl.toFixed(1) + " 52 55");
    pathEl.setAttribute("stroke", color);
    bocaAnimId = requestAnimationFrame(tick);
  }
  tick();
}

function animarBocaHablando(pathEl, color) {
  function tick() {
    const t = performance.now() / 1000;
    const amp = (Math.sin(t * 0.7) + 1) / 2;
    const apertura = 3 + amp * 5;
    const ancho = 5 + Math.sin(t * 2.3) * 1.5;
    const yBase = 55;
    const yControl = yBase + apertura;
    pathEl.setAttribute("d", "M " + (48 - ancho).toFixed(1) + " " + (yBase - apertura * 0.3).toFixed(1) + " Q 48 " + yControl.toFixed(1) + " " + (48 + ancho).toFixed(1) + " " + (yBase - apertura * 0.3).toFixed(1));
    pathEl.setAttribute("stroke", color);
    bocaAnimId = requestAnimationFrame(tick);
  }
  tick();
}

// =====================================================================
// TICK ORBE
// =====================================================================

let lastTick = 0;
function tickOrbe(ts) {
  if (!tickActivo) return;
  if (ts - lastTick >= 60) {
    lastTick = ts;
    estadoOrbe.orbFase = (estadoOrbe.orbFase + 0.18) % (2 * Math.PI);
    estadoOrbe.zFase = (estadoOrbe.zFase + 0.03) % (2 * Math.PI);

    if (estadoOrbe.modo !== "dormido" || dizzyState.activo) {
      // Parpadeo normal solo si no está dormido (o si está mareado)
      if (!dizzyState.activo) {
        estadoOrbe.parpadeoCuenta -= 1;
        if (estadoOrbe.parpadeoCuenta <= -3) {
          estadoOrbe.ojosCerrados = false;
          estadoOrbe.parpadeoCuenta = randInt(50, 150);
        } else if (estadoOrbe.parpadeoCuenta <= 0) {
          estadoOrbe.ojosCerrados = true;
        }
      }
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
  setTimeout(function() {
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

// =====================================================================
// ARRASTRE CON DETECCIÓN DE VELOCIDAD (Mareo)
// =====================================================================
(function habilitarArrastre() {
  const header = document.getElementById("header");
  if (!header) return;
  let arrastrando = false, x0 = 0, y0 = 0, ultimoX = 0, ultimoY = 0, ultimoTiempo = 0;
  const UMBRAL_VELOCIDAD = 25; // px por frame = movimiento rápido

  header.addEventListener("mousedown", function(e) {
    if (e.target.closest("button, #mini-orbe")) return;
    arrastrando = true;
    x0 = e.screenX; y0 = e.screenY;
    ultimoX = e.screenX; ultimoY = e.screenY;
    ultimoTiempo = performance.now();
  });

  window.addEventListener("mousemove", function(e) {
    if (!arrastrando) return;

    const ahora = performance.now();
    const dt = ahora - ultimoTiempo;
    const dx = e.screenX - ultimoX;
    const dy = e.screenY - ultimoY;
    const dist = Math.sqrt(dx * dx + dy * dy);

    // Detectar movimiento rápido
    if (dt > 0 && dist / dt * 16 > UMBRAL_VELOCIDAD) {
      triggerDizzy();
    }

    ultimoX = e.screenX;
    ultimoY = e.screenY;
    ultimoTiempo = ahora;

    // Mover ventana
    const dwx = e.screenX - x0;
    const dwy = e.screenY - y0;
    x0 = e.screenX; y0 = e.screenY;
    pywebview.api.mover_ventana(dwx, dwy);
  });

  window.addEventListener("mouseup", function() { arrastrando = false; });
})();

// =====================================================================
// CATEGORIAS
// =====================================================================
async function abrirCategoria(cat) {
  if (catFlotanteActual === cat) { cerrarFlotante(); return; }
  catFlotanteActual = cat;
  document.querySelectorAll(".cat-card").forEach(function(c) { c.classList.remove("abierta"); });
  const catEl = document.getElementById("cat-" + cat);
  if (catEl) catEl.classList.add("abierta");
  const ft = document.getElementById("flotante-titulo");
  if (ft) ft.textContent = CATEGORIAS[cat].icono + "  " + CATEGORIAS[cat].nombre;
  document.getElementById("overlay").classList.add("activo");
  document.getElementById("flotante").classList.add("activo");
  await refrescarListaFlotante();
}

// =====================================================================
// FILA ITEM
// =====================================================================
function crearFilaItem(it, categoria) {
  const fila = document.createElement("div");
  fila.className = "fila-item";
  fila.dataset.clave = it.clave;
  fila.dataset.cat = categoria;

  let html = '<div><div class="txt">' + escapeHtml(it.principal) + '</div>';
  if (it.secundario) html += '<div class="sub">' + escapeHtml(it.secundario) + '</div>';
  html += '</div>';
  html += '<button class="btn-borrar" title="quitar">×</button>';
  fila.innerHTML = html;

  const btn = fila.querySelector(".btn-borrar");

  btn.onclick = function(e) {
    e.stopPropagation();

    if (fila.classList.contains("confirmar-borrado")) {
      fila.classList.remove("confirmar-borrado");
      fila.classList.add("desvaneciendo");

      setTimeout(async function() {
        try {
          await pywebview.api.eliminar_item(categoria, it.clave);
        } catch (err) {}

        const grupoDiv = fila.closest(".alias-grupo");
        if (grupoDiv) {
          const conteoEl = grupoDiv.querySelector(".alias-grupo-conteo");
          const listaEl = grupoDiv.querySelector(".alias-grupo-lista");
          if (conteoEl && listaEl) {
            const nuevasFilas = listaEl.querySelectorAll(".fila-item:not(.desvaneciendo)");
            const nuevoConteo = nuevasFilas.length;
            conteoEl.textContent = nuevoConteo;

            if (nuevoConteo === 0) {
              grupoDiv.style.transition = "opacity 0.3s ease, max-height 0.3s ease";
              grupoDiv.style.opacity = "0";
              grupoDiv.style.maxHeight = "0";
              grupoDiv.style.overflow = "hidden";
              setTimeout(function() {
                grupoDiv.remove();
              }, 300);
            }
          }
        }

        fila.remove();
        refrescarCategorias();
      }, 250);
    } else {
      const cont = document.getElementById("flotante-lista");
      if (cont) {
        cont.querySelectorAll(".confirmar-borrado").forEach(function(otra) {
          otra.classList.remove("confirmar-borrado");
          const otroBtn = otra.querySelector(".btn-borrar");
          if (otroBtn) otroBtn.textContent = "×";
        });
      }

      fila.classList.add("confirmar-borrado");
      btn.textContent = "🗑";
    }
  };

  return fila;
}

// =====================================================================
// LISTA FLOTANTE
// =====================================================================
async function refrescarListaFlotante() {
  if (!catFlotanteActual) return;
  const items = await pywebview.api.listar_categoria(catFlotanteActual);
  const cont = document.getElementById("flotante-lista");
  cont.innerHTML = "";

  if (!items.length) {
    cont.innerHTML = '<div class="hist-vacio">Nada por aca todavia.</div>';
    return;
  }

  if (catFlotanteActual === "alias") {
    renderAliasAgrupados(cont, items);
    return;
  }

  for (const it of items) {
    const fila = crearFilaItem(it, catFlotanteActual);
    cont.appendChild(fila);
  }
}

function renderAliasAgrupados(cont, items) {
  const grupos = {};
  for (const it of items) {
    const app = it.secundario || "Sin app";
    if (!grupos[app]) grupos[app] = [];
    grupos[app].push(it);
  }

  const appsOrdenadas = Object.keys(grupos).sort(function(a, b) { return a.localeCompare(b); });

  for (const app of appsOrdenadas) {
    const aliasList = grupos[app];
    const expandido = aliasGruposExpandidos[app] !== false;

    const grupoDiv = document.createElement("div");
    grupoDiv.className = "alias-grupo";

    const cabecera = document.createElement("div");
    cabecera.className = "alias-grupo-cabecera";
    cabecera.innerHTML = '<span class="alias-grupo-toggle">' + (expandido ? "▼" : "▶") + '</span>' +
      '<span class="alias-grupo-nombre">' + escapeHtml(app) + '</span>' +
      '<span class="alias-grupo-conteo">' + aliasList.length + '</span>';

    const listaDiv = document.createElement("div");
    listaDiv.className = "alias-grupo-lista";
    listaDiv.style.display = expandido ? "block" : "none";

    cabecera.onclick = function() {
      const estaExpandido = listaDiv.style.display !== "none";
      listaDiv.style.display = estaExpandido ? "none" : "block";
      cabecera.querySelector(".alias-grupo-toggle").textContent = estaExpandido ? "▶" : "▼";
      aliasGruposExpandidos[app] = !estaExpandido;
    };

    for (const it of aliasList) {
      const fila = crearFilaItem(it, "alias");
      listaDiv.appendChild(fila);
    }

    grupoDiv.appendChild(cabecera);
    grupoDiv.appendChild(listaDiv);
    cont.appendChild(grupoDiv);
  }
}

function cerrarFlotante() {
  catFlotanteActual = null;
  document.querySelectorAll(".cat-card").forEach(function(c) { c.classList.remove("abierta"); });
  document.getElementById("overlay").classList.remove("activo");
  document.getElementById("flotante").classList.remove("activo");
}
function escapeHtml(s) {
  if (!s) return "";
  var map = {"&":"&amp;","<":"&lt;",">":"&gt;"};
  map['"'] = "&quot;";
  return s.replace(/[&<>"]/g, function(c) {
    return map[c];
  });
}

function renderCategoriasBase() {
  const grid = document.getElementById("categorias");
  grid.innerHTML = "";
  for (const cat in CATEGORIAS) {
    const meta = CATEGORIAS[cat];
    const card = document.createElement("div");
    card.className = "cat-card";
    card.id = "cat-" + cat;
    card.style.setProperty("--cat-color", meta.color);
    card.onclick = function() { abrirCategoria(cat); };
    card.innerHTML = '<div class="cat-cabecera"><span class="cat-icono">' + meta.icono +
      '</span><span class="cat-nombre">' + meta.nombre +
      '</span><span class="cat-conteo" id="conteo-' + cat + '">0</span></div>' +
      '<div class="cat-resumen" id="resumen-' + cat + '">—</div>';
    grid.appendChild(card);
  }
}
async function refrescarCategorias() {
  const resumen = await pywebview.api.resumen_categorias();
  for (const cat in CATEGORIAS) {
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
  if (catFlotanteActual && catFlotanteActual !== "alias") {
    refrescarListaFlotante();
  }
}

async function refrescarHistorial() {
  const items = await pywebview.api.historial();
  const cont = document.getElementById("historial-lista");
  if (!items.length) {
    cont.innerHTML = '<div class="hist-vacio">Todavia no hay comandos.<br>Deci "jarvis" para empezar.</div>';
    return;
  }
  let html = "";
  for (let i = 0; i < items.length; i++) {
    const h = items[i];
    const ts = escapeHtml(h.ts || ""), cmd = escapeHtml(h.cmd || ""), resp = escapeHtml(h.resp || "");
    html += '<div class="hist-item" style="color:var(--acento)">  ' + ts + '  ›  ' + cmd + '</div>';
    if (resp) {
      html += '<div class="hist-item" style="color:var(--texto);padding-left:14px">      ' +
        (resp.length > 38 ? resp.slice(0, 38) + "…" : resp) + '</div>';
    }
  }
  cont.innerHTML = html;
}

// =====================================================================
// ESTADO
// =====================================================================
async function refrescarEstado() {
  let e;
  try { e = await pywebview.api.get_estado(); } catch (err) { return; }

  const modoPrev = estadoOrbe.modo;
  estadoOrbe.modo = e.modo;
  estadoOrbe.noMolestar = e.no_molestar;

  if (e.modo !== modoPrev) {
    actualizarOrbeVisual();
    resetIdleTimer();
  }

  const hm = document.getElementById("header-modo");
  const hs = document.getElementById("header-sub");
  const hmo = document.getElementById("header-motor");
  if (hm) hm.textContent = e.texto_modo;
  if (hs) hs.textContent = e.motor + " · " + e.wake_word;

  const esDormido = e.modo === "dormido";
  const colorMotor = esDormido
    ? getComputedStyle(document.documentElement).getPropertyValue("--acento").trim()
    : (COLORES_MOTOR[e.motor] || COLORES_MOTOR["—"]);

  if (hmo) {
    hmo.textContent = e.motor;
    hmo.style.color = colorMotor;
    hmo.style.border = "1px solid " + colorMotor;
    hmo.style.boxShadow = "0 0 8px " + hexToRgba(colorMotor, 0.25);
  }

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

// =====================================================================
// INICIO
// =====================================================================
async function iniciarLoops() {
  await refrescarEstado();
  await refrescarCategorias();
  await refrescarHistorial();
  actualizarOrbeVisual();
  setInterval(refrescarEstado, 400);
  setInterval(function() { refrescarCategorias(); refrescarHistorial(); }, 1200);
  iniciarTickOrbe();
  programarParpadeoMini();
  iniciarTrackingOrbe();
  resetIdleTimer();
}

// =====================================================================
// TRACKING DEL ORBE
// =====================================================================

function iniciarTrackingOrbe() {
  const orbeWrap = document.getElementById("orbe-wrap");
  const orbeSvg = document.getElementById("orbe-svg");
  if (!orbeWrap || !orbeSvg) return;

  const pupilaIzq = document.getElementById("pupila-izq");
  const pupilaDer = document.getElementById("pupila-der");
  const brilloIzq = document.getElementById("brillo-izq");
  const brilloDer = document.getElementById("brillo-der");

  const baseIzq = { x: 39, y: 45 };
  const baseDer = { x: 57, y: 45 };
  const brilloOffset = { x: 1.2, y: -1.2 };
  const radioMaximo = 2.2;

  orbeWrap.addEventListener("mouseenter", function() {
    if (estadoOrbe.modo === "dormido" && !dizzyState.activo) return;
    estadoOrbe.hoverOrbe = true;
    resetIdleTimer();
    actualizarOrbeVisual();
  });

  orbeWrap.addEventListener("mouseleave", function() {
    estadoOrbe.hoverOrbe = false;
    if (pupilaIzq) {
      pupilaIzq.style.transition = "cx 0.3s ease, cy 0.3s ease";
      pupilaIzq.setAttribute("cx", baseIzq.x);
      pupilaIzq.setAttribute("cy", baseIzq.y);
      setTimeout(function() { if (pupilaIzq) pupilaIzq.style.transition = ""; }, 300);
    }
    if (pupilaDer) {
      pupilaDer.style.transition = "cx 0.3s ease, cy 0.3s ease";
      pupilaDer.setAttribute("cx", baseDer.x);
      pupilaDer.setAttribute("cy", baseDer.y);
      setTimeout(function() { if (pupilaDer) pupilaDer.style.transition = ""; }, 300);
    }
    if (brilloIzq) {
      brilloIzq.setAttribute("cx", baseIzq.x + brilloOffset.x);
      brilloIzq.setAttribute("cy", baseIzq.y + brilloOffset.y);
    }
    if (brilloDer) {
      brilloDer.setAttribute("cx", baseDer.x + brilloOffset.x);
      brilloDer.setAttribute("cy", baseDer.y + brilloOffset.y);
    }
    actualizarOrbeVisual();
  });

  orbeWrap.addEventListener("mousedown", function() {
    if (estadoOrbe.modo === "dormido" && !dizzyState.activo) return;
    resetIdleTimer();
    if (pupilaIzq) pupilaIzq.setAttribute("r", "3.5");
    if (pupilaDer) pupilaDer.setAttribute("r", "3.5");
  });
  orbeWrap.addEventListener("mouseup", function() {
    if (estadoOrbe.modo === "dormido" && !dizzyState.activo) return;
    if (pupilaIzq) pupilaIzq.setAttribute("r", "2.8");
    if (pupilaDer) pupilaDer.setAttribute("r", "2.8");
  });

  orbeWrap.addEventListener("mousemove", function(e) {
    if (!pupilaIzq || !pupilaDer) return;
    if (estadoOrbe.modo === "dormido" && !dizzyState.activo) return;
    if (estadoOrbe.ojosCerrados && !dizzyState.activo) return;

    const rect = orbeSvg.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * 96;
    const my = ((e.clientY - rect.top) / rect.height) * 96;

    function moverPupila(base, pupila, brillo) {
      const dx = mx - base.x;
      const dy = my - base.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const maxDist = 40;
      const factor = Math.min(dist / maxDist, 1);
      const eased = factor * (2 - factor);
      const angulo = Math.atan2(dy, dx);
      const nx = base.x + Math.cos(angulo) * radioMaximo * eased;
      const ny = base.y + Math.sin(angulo) * radioMaximo * eased;
      pupila.setAttribute("cx", nx.toFixed(2));
      pupila.setAttribute("cy", ny.toFixed(2));
      if (brillo) {
        brillo.setAttribute("cx", (nx + brilloOffset.x).toFixed(2));
        brillo.setAttribute("cy", (ny + brilloOffset.y).toFixed(2));
      }
    }

    moverPupila(baseIzq, pupilaIzq, brilloIzq);
    moverPupila(baseDer, pupilaDer, brilloDer);
  });
}

renderCategoriasBase();
if (window.pywebview) iniciarLoops();
else window.addEventListener("pywebviewready", iniciarLoops);