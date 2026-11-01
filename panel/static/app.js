/* Panel de Niu — fases 3 y 4.
 *
 * Dos canales y cada uno para lo suyo:
 *   - sondeo cada segundo para el estado del motor y los chips;
 *   - WebSocket para el chat, porque el texto de Niu llega a trozos y sondeando
 *     se vería a saltos (justo lo que el streaming evita).
 *
 * La interfaz no sabe conversar: manda texto al motor y pinta los mensajes que
 * el servidor le empuja. Toda la lógica de la conversación está en el motor.
 *
 * Los ajustes son otra cosa: el formulario se pinta desde el esquema que manda
 * el servidor (`GET /api/ajustes`), así que añadir un campo se hace en
 * `panel/ajustes.py`, no aquí.
 */

const ETIQUETAS = {
  apagado: "Apagado",
  iniciando: "Iniciando…",
  escuchando: "Escuchando",
  pensando: "Pensando",
  hablando: "Hablando",
};

const ESTADOS_CON_TEXTO = ["escuchando", "pensando", "hablando"];

const botones = {
  iniciar: document.getElementById("btn-iniciar"),
  detener: document.getElementById("btn-detener"),
  voz: document.getElementById("btn-voz"),
  copiar: document.getElementById("btn-copiar"),
  exportar: document.getElementById("btn-exportar"),
  limpiar: document.getElementById("btn-limpiar"),
};

const pastilla = document.getElementById("pastilla");
const pastillaTexto = document.getElementById("pastilla-texto");
const orbita = document.getElementById("orbita");
const aviso = document.getElementById("aviso");

const chat = {
  registro: document.getElementById("chat-registro"),
  vacio: document.getElementById("chat-vacio"),
  form: document.getElementById("chat-form"),
  entrada: document.getElementById("chat-entrada"),
  enviar: document.getElementById("btn-enviar"),
  nota: document.getElementById("chat-nota"),
};

/** id → mensaje del servidor (fuente de verdad para copiar). */
const datosMensajes = new Map();
/** id → nodo del DOM. */
const nodosMensajes = new Map();

let consultando = false;
let motorConTexto = false;
let estadoActual = "apagado";

/* ─── Chat ────────────────────────────────────────────────────────────── */

function resumenMetricas(tiempos) {
  const numero = (valor) => Number(valor) || 0;
  const segundos = (valor) => `${numero(valor).toFixed(2)} s`;
  const hastaSonido = ["stt", "texto", "sintesis", "preparacion"]
    .reduce((total, clave) => total + numero(tiempos[clave]), 0);

  const partes = [`1er sonido ${hastaSonido.toFixed(2)} s`];
  // El STT no existe cuando el mensaje se escribió en el chat: no se inventa
  // un 0,00 s que parezca una medida.
  if ("stt" in tiempos) partes.push(`STT ${segundos(tiempos.stt)}`);
  if ("texto" in tiempos) partes.push(`1ª frase ${segundos(tiempos.texto)}`);
  partes.push(`voz ${segundos(tiempos.voz)}`);
  if (tiempos.partes) {
    const n = Math.round(numero(tiempos.partes));
    partes.push(n === 1 ? "1 parte" : `${n} partes`);
  }
  return partes.join(" · ");
}

function alFinal(forzar = false) {
  const caja = chat.registro;
  const cercaDelFinal =
    caja.scrollHeight - caja.scrollTop - caja.clientHeight < 120;
  if (forzar || cercaDelFinal) caja.scrollTop = caja.scrollHeight;
}

function crearNodo(mensaje) {
  const articulo = document.createElement("article");
  articulo.className = "mensaje";
  articulo.dataset.papel = mensaje.papel;
  articulo.dataset.id = String(mensaje.id);

  const texto = document.createElement("p");
  texto.className = "mensaje-texto";
  articulo.append(texto);

  const meta = document.createElement("p");
  meta.className = "mensaje-meta";
  articulo.append(meta);

  chat.registro.append(articulo);
  nodosMensajes.set(mensaje.id, articulo);
  return articulo;
}

function pintarMensaje(mensaje) {
  const esNuevo = !nodosMensajes.has(mensaje.id);
  const nodo = nodosMensajes.get(mensaje.id) || crearNodo(mensaje);

  datosMensajes.set(mensaje.id, mensaje);
  nodo.dataset.papel = mensaje.papel;
  nodo.dataset.parcial = String(Boolean(mensaje.parcial));

  if (mensaje.interrumpida) nodo.dataset.interrumpida = "true";
  else delete nodo.dataset.interrumpida;

  nodo.querySelector(".mensaje-texto").textContent = mensaje.texto || "";

  const meta = nodo.querySelector(".mensaje-meta");
  meta.replaceChildren();
  if (mensaje.papel !== "sistema") {
    if (mensaje.hora) {
      const hora = document.createElement("span");
      hora.textContent = mensaje.hora.slice(11, 16);
      meta.append(hora);
    }
    if (mensaje.metricas && mensaje.papel === "niu") {
      const metricas = document.createElement("span");
      metricas.className = "mensaje-metricas";
      metricas.textContent = resumenMetricas(mensaje.metricas);
      meta.append(metricas);
    }
  }

  actualizarVacio();
  alFinal(esNuevo || Boolean(mensaje.parcial));
}

function quitarMensaje(id) {
  const nodo = nodosMensajes.get(id);
  if (nodo) nodo.remove();
  nodosMensajes.delete(id);
  datosMensajes.delete(id);
  actualizarVacio();
}

function limpiarVista() {
  for (const nodo of nodosMensajes.values()) nodo.remove();
  nodosMensajes.clear();
  datosMensajes.clear();
  actualizarVacio();
}

function actualizarVacio() {
  const vacio = datosMensajes.size === 0;
  chat.vacio.hidden = !vacio;
  botones.copiar.disabled = vacio;
  botones.exportar.disabled = vacio;
}

/* ─── WebSocket ───────────────────────────────────────────────────────── */

let reintento = 1000;

function conectar() {
  const protocolo = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocolo}://${location.host}/ws`);

  socket.addEventListener("open", () => {
    reintento = 1000;
  });

  socket.addEventListener("message", (evento) => {
    let datos;
    try {
      datos = JSON.parse(evento.data);
    } catch {
      return;       // un mensaje que no es JSON no debe romper el chat
    }

    if (datos.tipo === "historial") {
      limpiarVista();
      (datos.mensajes || []).forEach(pintarMensaje);
      alFinal(true);
      if (datos.archivo) chat.nota.textContent = `Sesión: ${datos.archivo}`;
    } else if (datos.tipo === "mensaje") {
      pintarMensaje(datos.mensaje);
    } else if (datos.tipo === "quitar") {
      quitarMensaje(datos.id);
    }
  });

  socket.addEventListener("close", () => {
    chat.nota.textContent = "Sin conexión con el panel. Reintentando…";
    setTimeout(conectar, reintento);
    reintento = Math.min(reintento * 2, 10000);
  });

  socket.addEventListener("error", () => socket.close());
}

/* ─── Acciones del chat ───────────────────────────────────────────────── */

async function enviarMensaje() {
  const texto = chat.entrada.value.trim();
  if (!texto || !motorConTexto) return;

  chat.enviar.disabled = true;
  try {
    const respuesta = await fetch("/api/mensaje", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto }),
    });
    if (!respuesta.ok) {
      const datos = await respuesta.json().catch(() => ({}));
      throw new Error(datos.detail || `HTTP ${respuesta.status}`);
    }
    chat.entrada.value = "";
  } catch (error) {
    mostrarAviso(`No se pudo enviar el mensaje: ${error.message}`);
  } finally {
    chat.enviar.disabled = !motorConTexto;
    chat.entrada.focus();
  }
}

async function copiarConversacion() {
  const lineas = [...datosMensajes.values()].map((mensaje) => {
    if (mensaje.papel === "usuario") return `Tú: ${mensaje.texto}`;
    if (mensaje.papel === "niu") return `Niu: ${mensaje.texto}`;
    return `(sistema) ${mensaje.texto}`;
  });

  try {
    await navigator.clipboard.writeText(lineas.join("\n"));
    const original = botones.copiar.textContent;
    botones.copiar.textContent = "Copiado";
    setTimeout(() => { botones.copiar.textContent = original; }, 1500);
  } catch {
    mostrarAviso("El navegador no dejó copiar. Selecciona el texto a mano.");
  }
}

async function limpiarConversacion() {
  const seguro = window.confirm(
    "¿Empezar una sesión nueva? La conversación actual queda guardada en sesiones/."
  );
  if (!seguro) return;

  try {
    const respuesta = await fetch("/api/sesion/limpiar", { method: "POST" });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    // El servidor también avisa por WebSocket; el historial que devuelve aquí
    // sirve para que el cambio se vea aunque el socket esté reconectando.
    const datos = await respuesta.json();
    limpiarVista();
    if (datos.archivo) chat.nota.textContent = `Sesión: ${datos.archivo}`;
  } catch (error) {
    mostrarAviso(`No se pudo limpiar: ${error.message}`);
  }
}

function exportarConversacion() {
  const enlace = document.createElement("a");
  enlace.href = "/api/sesion/exportar";
  enlace.download = "";
  document.body.append(enlace);
  enlace.click();
  enlace.remove();
}

/* ─── Ajustes ─────────────────────────────────────────────────────────── */

const ajustes = {
  grupos: document.getElementById("ajustes-grupos"),
  avanzados: document.getElementById("ajustes-avanzados"),
  cajaAvanzados: document.getElementById("ajustes-caja-avanzados"),
  aviso: document.getElementById("ajustes-aviso"),
  guardar: document.getElementById("btn-guardar"),
  restaurar: document.getElementById("btn-restaurar"),
  probar: document.getElementById("btn-probar"),
};

/** Campos tal como los describe el servidor (su orden manda al pintar). */
let camposAjustes = [];
/** Lo que hay guardado en disco: sirve para saber si el formulario cambió. */
let valoresGuardados = {};
/** Campos que el usuario tocó de verdad. */
let camposModificados = new Set();

const LISTAS = {
  voces: "lista-voces",
  entrada: "lista-entrada",
  salida: "lista-salida",
  llm: "lista-modelos",
};

function numeroDe(texto) {
  const numero = Number.parseFloat(String(texto).replace(",", "."));
  return Number.isFinite(numero) ? numero : 0;
}

/** `5` → `+5`, `-5` → `-5`, `0` → `+0` (el formato que espera Edge-TTS). */
function conSigno(numero) {
  const redondeado = Math.round(numero);
  return redondeado >= 0 ? `+${redondeado}` : String(redondeado);
}

/** Lo que vale el control, ya en el formato del ajuste (no del `<input>`). */
function lecturaDe(campo, control) {
  switch (campo.tipo) {
    case "hz":
      return `${conSigno(numeroDe(control.value))}Hz`;
    case "porcentaje":
      return `${conSigno(numeroDe(control.value))}%`;
    case "numero":
      return numeroDe(control.value);
    default:
      return control.value.trim();
  }
}

/** Texto que acompaña al slider: `+5 Hz`, `-8 %`, `0.9 s`. */
function textoDeControl(campo, valor) {
  if (campo.tipo === "hz") return `${conSigno(numeroDe(valor))} Hz`;
  if (campo.tipo === "porcentaje") return `${conSigno(numeroDe(valor))} %`;
  const numero = numeroDe(valor);
  return campo.unidad ? `${numero} ${campo.unidad}` : String(numero);
}

function crearControl(campo, valor) {
  if (campo.tipo === "seleccion") {
    const control = document.createElement("select");
    control.className = "ajustes-control";
    for (const opcion of campo.opciones || []) {
      const item = document.createElement("option");
      item.value = opcion.valor;
      item.textContent = opcion.texto;
      control.append(item);
    }
    control.value = valor;
    return { control, nodo: control };
  }

  if (campo.tipo === "hz" || campo.tipo === "porcentaje") {
    const fila = document.createElement("div");
    fila.className = "ajustes-rango";
    const control = document.createElement("input");
    control.type = "range";
    control.min = campo.minimo;
    control.max = campo.maximo;
    control.step = campo.paso;
    control.value = numeroDe(valor);
    const salida = document.createElement("output");
    salida.textContent = textoDeControl(campo, valor);
    control.addEventListener("input", () => {
      salida.textContent = textoDeControl(campo, control.value);
    });
    fila.append(control, salida);
    return { control, nodo: fila };
  }

  const control = document.createElement("input");
  control.className = "ajustes-control";
  if (campo.tipo === "numero") {
    control.type = "number";
    control.min = campo.minimo;
    control.max = campo.maximo;
    control.step = campo.paso;
  } else {
    control.type = "text";
    control.autocomplete = "off";
    control.spellcheck = false;
    if (campo.fuente && LISTAS[campo.fuente]) control.setAttribute("list", LISTAS[campo.fuente]);
  }
  control.value = valor ?? "";
  return { control, nodo: control };
}

function crearCampo(campo, valor) {
  const caja = document.createElement("div");
  caja.className = "ajustes-campo";

  const id = `aj-${campo.campo}`;
  const etiqueta = document.createElement("label");
  etiqueta.htmlFor = id;

  const nombre = document.createElement("span");
  nombre.className = "ajustes-nombre";
  nombre.textContent = campo.etiqueta;
  if (!campo.en_caliente) {
    const frio = document.createElement("span");
    frio.className = "ajustes-frio";
    frio.textContent = "reinicia";
    frio.title = "Se aplica al reiniciar el motor.";
    nombre.append(frio);
  }
  etiqueta.append(nombre);

  if (campo.tipo === "numero" && campo.unidad) {
    const unidad = document.createElement("span");
    unidad.className = "ajustes-unidad";
    // La unidad decora el campo; el nombre accesible es solo la etiqueta.
    unidad.setAttribute("aria-hidden", "true");
    unidad.textContent = campo.unidad;
    etiqueta.append(unidad);
  }

  const { control, nodo } = crearControl(campo, valor);
  control.id = id;
  control.dataset.campo = campo.campo;
  const marcar = () => {
    camposModificados.add(campo.campo);
    actualizarGuardar();
  };
  control.addEventListener("input", marcar);
  control.addEventListener("change", marcar);

  caja.append(etiqueta, nodo);

  if (campo.nota) {
    const nota = document.createElement("p");
    nota.className = "ajustes-nota";
    nota.textContent = campo.nota;
    caja.append(nota);
  }
  return caja;
}

function crearGrupo(seccion, campos, titulos, destino) {
  const bloque = document.createElement("section");
  bloque.className = "ajustes-grupo";

  const titulo = document.createElement("h3");
  titulo.className = "ajustes-grupo-titulo";
  titulo.textContent = titulos[seccion] || seccion;

  const rejilla = document.createElement("div");
  rejilla.className = "ajustes-campos";
  for (const campo of campos) {
    rejilla.append(crearCampo(campo, valoresGuardados[campo.campo]));
  }

  bloque.append(titulo, rejilla);
  destino.append(bloque);
}

function renderAjustes(datos) {
  camposAjustes = datos.campos || [];
  valoresGuardados = datos.valores || {};
  camposModificados = new Set();
  const titulos = datos.secciones || {};

  ajustes.grupos.replaceChildren();
  ajustes.avanzados.replaceChildren();

  const grupos = new Map();
  for (const campo of camposAjustes) {
    if (!grupos.has(campo.seccion)) grupos.set(campo.seccion, []);
    grupos.get(campo.seccion).push(campo);
  }
  for (const [seccion, campos] of grupos) {
    const destino = seccion === "avanzado" ? ajustes.avanzados : ajustes.grupos;
    crearGrupo(seccion, campos, titulos, destino);
  }
  ajustes.cajaAvanzados.hidden = !grupos.has("avanzado");

  // Sugerencias de voz: vienen en el esquema, no de una petición aparte.
  const campoVoz = camposAjustes.find((campo) => campo.campo === "voz");
  llenarLista("lista-voces", (campoVoz?.sugerencias || []).map((voz) => ({ valor: voz })));

  ajustes.guardar.disabled = true;
  ajustes.restaurar.disabled = false;
}

function lecturas() {
  const valores = {};
  for (const campo of camposAjustes) {
    const control = document.getElementById(`aj-${campo.campo}`);
    if (control) valores[campo.campo] = lecturaDe(campo, control);
  }
  return valores;
}

/**
 * Solo lo que el usuario cambió de verdad.
 *
 * No se comparan valores con lo guardado a propósito: `tono` guardado como ""
 * significa «el del perfil de idioma», pero el slider no puede estar vacío.
 * Comparando, cualquier retoque de otro campo reenviaría `+0Hz` y congelaría el
 * tono del perfil sin que nadie lo pidiera.
 */
function cambiosPendientes() {
  const valores = lecturas();
  const cambios = {};
  for (const campo of camposModificados) {
    if (campo in valores) cambios[campo] = valores[campo];
  }
  return cambios;
}

function actualizarGuardar() {
  ajustes.guardar.disabled = Object.keys(cambiosPendientes()).length === 0;
}

function avisarAjustes(texto, tipo = "info") {
  ajustes.aviso.hidden = !texto;
  ajustes.aviso.textContent = texto || "";
  ajustes.aviso.dataset.tipo = tipo;
}

async function traerAjustes() {
  const respuesta = await fetch("/api/ajustes", { cache: "no-store" });
  if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
  return respuesta.json();
}

async function cargarAjustes() {
  try {
    renderAjustes(await traerAjustes());
  } catch (error) {
    ajustes.grupos.replaceChildren();
    const fallo = document.createElement("p");
    fallo.className = "ajustes-nota";
    fallo.textContent = `No se pudieron cargar los ajustes: ${error.message}`;
    ajustes.grupos.append(fallo);
  }
}

async function guardarAjustes() {
  const cambios = cambiosPendientes();
  if (!Object.keys(cambios).length) return;

  ajustes.guardar.disabled = true;
  ajustes.guardar.textContent = "Guardando…";
  try {
    const respuesta = await fetch("/api/ajustes", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cambios),
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.detail || `HTTP ${respuesta.status}`);

    const lineas = [...(datos.avisos || [])];
    if (datos.requiere_reinicio?.length) {
      lineas.push(`Reinicia el motor para aplicar: ${datos.requiere_reinicio.join(", ")}.`);
    }
    await cargarAjustes();
    avisarAjustes(lineas.length ? lineas.join("\n") : "Ajustes guardados.",
                  lineas.length ? "info" : "ok");
    consultar();
  } catch (error) {
    avisarAjustes(`No se pudieron guardar: ${error.message}`, "error");
  } finally {
    ajustes.guardar.textContent = "Guardar";
    actualizarGuardar();
  }
}

async function restaurarAjustes() {
  const seguro = window.confirm(
    "¿Volver a los valores de fábrica? Se sobrescribe config.json."
  );
  if (!seguro) return;

  try {
    const respuesta = await fetch("/api/ajustes/restablecer", { method: "POST" });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.detail || `HTTP ${respuesta.status}`);

    const lineas = ["Ajustes de fábrica restaurados."];
    if (datos.requiere_reinicio?.length) {
      lineas.push(`Reinicia el motor para aplicar: ${datos.requiere_reinicio.join(", ")}.`);
    }
    await cargarAjustes();
    avisarAjustes(lineas.join("\n"), "ok");
    consultar();
  } catch (error) {
    avisarAjustes(`No se pudo restaurar: ${error.message}`, "error");
  }
}

async function probarVoz() {
  const valores = lecturas();
  ajustes.probar.disabled = true;
  ajustes.probar.textContent = "Probando…";
  try {
    const respuesta = await fetch("/api/ajustes/probar-voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voz: valores.voz || "",
        tono: valores.tono || "",
        velocidad: valores.velocidad || "",
        idioma: valores.idioma || "",
      }),
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.detail || `HTTP ${respuesta.status}`);
    if (!datos.ok) throw new Error(datos.detalle || "No se pudo generar la voz.");

    avisarAjustes(
      `Prueba escuchada: ${datos.voz} · ${datos.tono} · ${datos.velocidad}`,
      "ok"
    );
  } catch (error) {
    avisarAjustes(`La prueba de voz falló: ${error.message}`, "error");
  } finally {
    ajustes.probar.textContent = "Probar voz";
    ajustes.probar.disabled = ["pensando", "hablando"].includes(estadoActual);
  }
}

/* Las sugerencias de dispositivos y modelos se piden aparte: son listas del
 * sistema (y Ollama puede tardar), no parte de los ajustes guardados. */
function llenarLista(id, elementos) {
  const lista = document.getElementById(id);
  if (!lista) return;
  lista.replaceChildren();
  const vistos = new Set();
  for (const elemento of elementos || []) {
    const valor = String(elemento.valor ?? "").trim();
    // sounddevice repite el mismo micro una vez por host API (MME,
    // DirectSound...). Para el ajuste basta el nombre.
    if (!valor || vistos.has(valor)) continue;
    vistos.add(valor);
    const opcion = document.createElement("option");
    opcion.value = valor;
    if (elemento.etiqueta) opcion.label = elemento.etiqueta;
    lista.append(opcion);
  }
}

async function cargarListas() {
  const pedir = async (ruta) => {
    const respuesta = await fetch(ruta, { cache: "no-store" });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    return respuesta.json();
  };

  const [dispositivos, modelos] = await Promise.allSettled([
    pedir("/api/dispositivos"),
    pedir("/api/modelos"),
  ]);

  if (dispositivos.status === "fulfilled") {
    const datos = dispositivos.value;
    llenarLista("lista-entrada", (datos.entrada || [])
      .map((d) => ({ valor: d.nombre, etiqueta: d.host_api })));
    llenarLista("lista-salida", (datos.salida || [])
      .map((d) => ({ valor: d.nombre, etiqueta: d.host_api })));
  }
  if (modelos.status === "fulfilled") {
    llenarLista("lista-modelos", (modelos.value.llm || [])
      .map((modelo) => ({ valor: modelo })));
  }
}

/* ─── Estado del motor ────────────────────────────────────────────────── */

function mostrarAviso(texto) {
  if (!texto) {
    aviso.hidden = true;
    aviso.textContent = "";
    return;
  }
  aviso.hidden = false;
  aviso.textContent = texto;
}

function pintar(datos) {
  const estado = datos.estado || "apagado";
  estadoActual = estado;

  orbita.dataset.estado = estado;
  pastilla.dataset.estado = estado;
  pastillaTexto.textContent = ETIQUETAS[estado] || estado;
  document.title = `${ETIQUETAS[estado] || estado} · Niu`;

  document.getElementById("dato-idioma").textContent = datos.idioma || "—";
  document.getElementById("dato-voz").textContent = datos.voz || "—";
  document.getElementById("dato-tono").textContent = datos.tono || "—";

  botones.iniciar.disabled = estado !== "apagado";
  botones.detener.disabled = estado === "apagado";
  botones.voz.disabled = !["pensando", "hablando"].includes(estado);

  motorConTexto = ESTADOS_CON_TEXTO.includes(estado);
  chat.entrada.disabled = !motorConTexto;
  chat.enviar.disabled = !motorConTexto;
  chat.entrada.placeholder = motorConTexto
    ? "Escribe a Niu…"
    : "Inicia el motor para escribir";

  // La prueba de voz pelearía con la voz de Niu por el mismo stream de audio.
  if (["pensando", "hablando"].includes(estado)) {
    ajustes.probar.disabled = true;
    ajustes.probar.title = "Niu está hablando: espera a que termine.";
  } else {
    ajustes.probar.disabled = false;
    ajustes.probar.title = "Oír la voz con los valores del formulario, sin guardar";
  }

  const chips = datos.chips || {};
  for (const [clave, valor] of Object.entries(chips)) {
    const chip = document.querySelector(`.chip[data-clave="${clave}"]`);
    if (!chip) continue;
    const etiqueta = chip.querySelector(".chip-valor");
    if (clave === "motor") {
      chip.dataset.ok = String(valor !== "apagado");
      etiqueta.textContent = ETIQUETAS[valor] || valor;
    } else {
      chip.dataset.ok = String(Boolean(valor));
      etiqueta.textContent = valor ? "Sí" : "No";
    }
  }

  mostrarAviso(datos.error || "");
  actualizarVacio();
}

async function consultar() {
  if (consultando) return;
  consultando = true;
  try {
    const respuesta = await fetch("/api/estado", { cache: "no-store" });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    pintar(await respuesta.json());
  } catch (error) {
    pastilla.dataset.estado = "apagado";
    orbita.dataset.estado = "apagado";
    pastillaTexto.textContent = "Sin conexión";
    mostrarAviso("No puedo hablar con el panel. Revisa la consola donde lo lanzaste.");
  } finally {
    consultando = false;
  }
}

async function accion(ruta) {
  [botones.iniciar, botones.detener, botones.voz]
    .forEach((boton) => { boton.disabled = true; });
  try {
    const respuesta = await fetch(ruta, { method: "POST" });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    pintar({ ...(await respuesta.json()), chips: {} });
  } catch (error) {
    mostrarAviso(`La acción falló: ${error.message}`);
  } finally {
    consultar();
  }
}

botones.iniciar.addEventListener("click", () => accion("/api/motor/iniciar"));
botones.detener.addEventListener("click", () => accion("/api/motor/detener"));
botones.voz.addEventListener("click", () => accion("/api/motor/detener-voz"));

chat.form.addEventListener("submit", (evento) => {
  evento.preventDefault();
  enviarMensaje();
});
botones.copiar.addEventListener("click", copiarConversacion);
botones.exportar.addEventListener("click", exportarConversacion);
botones.limpiar.addEventListener("click", limpiarConversacion);

ajustes.guardar.addEventListener("click", guardarAjustes);
ajustes.restaurar.addEventListener("click", restaurarAjustes);
ajustes.probar.addEventListener("click", probarVoz);

actualizarVacio();
conectar();
consultar();
cargarAjustes();
cargarListas();
setInterval(consultar, 1000);
