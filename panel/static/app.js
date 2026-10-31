/* Panel de Niu — fase 2.
 *
 * La interfaz no sabe conversar: pregunta el estado cada segundo y pide
 * arrancar, parar o callar la voz. El motor sigue siendo el único que sabe
 * qué está pasando; aquí solo se pinta.
 */

const ETIQUETAS = {
  apagado: "Apagado",
  iniciando: "Iniciando…",
  escuchando: "Escuchando",
  pensando: "Pensando",
  hablando: "Hablando",
};

const NOMBRES = {
  motor: "Motor",
  ollama: "Ollama",
  vts: "VTube Studio",
  microfono: "Micrófono",
  tts: "TTS",
};

const botones = {
  iniciar: document.getElementById("btn-iniciar"),
  detener: document.getElementById("btn-detener"),
  voz: document.getElementById("btn-voz"),
};

const pastilla = document.getElementById("pastilla");
const pastillaTexto = document.getElementById("pastilla-texto");
const orbita = document.getElementById("orbita");
const aviso = document.getElementById("aviso");

let consultando = false;

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
  Object.values(botones).forEach((boton) => { boton.disabled = true; });
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

consultar();
setInterval(consultar, 1000);
