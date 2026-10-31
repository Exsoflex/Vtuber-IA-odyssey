/* Panel de Niu — fase 3.
 *
 * Dos canales y cada uno para lo suyo:
 *   - sondeo cada segundo para el estado del motor y los chips;
 *   - WebSocket para el chat, porque el texto de Niu llega a trozos y sondeando
 *     se vería a saltos (justo lo que el streaming evita).
 *
 * La interfaz no sabe conversar: manda texto al motor y pinta los mensajes que
 * el servidor le empuja. Toda la lógica de la conversación está en el motor.
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

actualizarVacio();
conectar();
consultar();
setInterval(consultar, 1000);
