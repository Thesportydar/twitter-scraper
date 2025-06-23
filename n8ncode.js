// --- CONFIGURACIÓN ---
const feriadosUSA = [
  { mes: 1, dia: 1, motivo: "New Year's Day", tipo: "Federal" },
  { mes: 1, dia: 20, motivo: "Martin Luther King Jr. Day", tipo: "Federal (Market Holiday)" },
  { mes: 2, dia: 17, motivo: "Washington’s Birthday (Presidents’ Day)", tipo: "Federal (Market Holiday)" },
  { mes: 3, dia: 28, motivo: "Good Friday", tipo: "Religious (Market Holiday)" }, // No es federal, pero sí cierre de mercado
  { mes: 5, dia: 26, motivo: "Memorial Day", tipo: "Federal (Market Holiday)" },
  { mes: 6, dia: 19, motivo: "Juneteenth National Independence Day", tipo: "Federal" },
  { mes: 7, dia: 4, motivo: "Independence Day", tipo: "Federal (Market Holiday)" },
  { mes: 9, dia: 1, motivo: "Labor Day", tipo: "Federal (Market Holiday)" },
  { mes: 11, dia: 27, motivo: "Thanksgiving Day", tipo: "Federal (Market Holiday)" },
  { mes: 12, dia: 25, motivo: "Christmas Day", tipo: "Federal (Market Holiday)" }
];

// --- FUNCIONES AUXILIARES ---
async function getFeriadoAR(fecha) {
  const year = fecha.getFullYear();
  const url = `https://nolaborables.com.ar/api/v2/feriados/${year}?formato=mensual`;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const feriados = await res.json();
    const mes = fecha.getMonth() + 1;
    const dia = fecha.getDate();
    const feriadosMes = feriados[mes] || [];
    const feriado = feriadosMes.find(f => f.dia === dia);
    return feriado || null;
  } catch (e) {
    return null;
  }
}

function getFeriadoUSA(fecha) {
  const mes = fecha.getMonth() + 1;
  const dia = fecha.getDate();
  return feriadosUSA.find(f => f.mes === mes && f.dia === dia) || null;
}

function getTipoDia({ feriadoAR, feriadoUSA, diaSemana, hour }) {
  let tipo = [];
  let motivos = [];
  let tiposFeriado = [];

  if (feriadoAR) {
    tipo.push("Feriado Argentina");
    motivos.push(feriadoAR.motivo);
    tiposFeriado.push(feriadoAR.tipo);
  }
  if (feriadoUSA) {
    tipo.push("Feriado USA");
    motivos.push(feriadoUSA.motivo);
    tiposFeriado.push(feriadoUSA.tipo);
  }
  if (tipo.length === 0) {
    if (diaSemana === 0 || diaSemana === 6) {
      tipo.push("Fin de semana");
    } else {
      tipo.push(hour < 11 ? "Pre-Market" : (hour < 13 ? "Intra-Day" : "Post-Market"));
    }
  }
  return {
    tipo: tipo.join(" y "),
    motivo: motivos.length ? motivos.join(" y ") : undefined,
    tipoFeriado: tiposFeriado.length ? tiposFeriado.join(" y ") : undefined,
    esFeriado: tipo.some(t => t.includes("Feriado"))
  };
}

// --- LÓGICA PRINCIPAL ---
const hoy = new Date();
const hour = hoy.getHours();
const diaSemana = hoy.getDay(); // 0=Domingo, 6=Sábado

// Estado de hoy
const feriadoAR = await getFeriadoAR(hoy);
const feriadoUSA = getFeriadoUSA(hoy);
const tipoHoy = getTipoDia({ feriadoAR, feriadoUSA, diaSemana, hour });

// Estado de mañana
const manana = new Date(hoy);
manana.setDate(hoy.getDate() + 1);
const feriadoARManana = await getFeriadoAR(manana);
const feriadoUSAManana = getFeriadoUSA(manana);
const diaSemanaManana = manana.getDay();
const tipoManana = getTipoDia({ feriadoAR: feriadoARManana, feriadoUSA: feriadoUSAManana, diaSemana: diaSemanaManana, hour: 10 }); // hour=10 para Pre-Market

// --- HEADER ---
const header = `
📅 Fecha actual: ${hoy.toLocaleDateString('es-AR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
📌 Tipo de día: ${tipoHoy.tipo}${tipoHoy.motivo ? ` (${tipoHoy.motivo}${tipoHoy.tipoFeriado ? ', ' + tipoHoy.tipoFeriado : ''})` : ''}
📅 Estado de mañana: ${manana.toLocaleDateString('es-AR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
📌 Tipo de día mañana: ${tipoManana.tipo}${tipoManana.motivo ? ` (${tipoManana.motivo}${tipoManana.tipoFeriado ? ', ' + tipoManana.tipoFeriado : ''})` : ''}
`;

const footer = `
📌 INSTRUCCIONES ADICIONALES:
- No hagas suposiciones que no estén respaldadas por el contenido de los tweets.
- Ignorá información irrelevante o redundante; enfocate en lo que aporta valor al análisis.
- Recordá que el objetivo es ayudar a un inversor real a tomar decisiones en un entorno volátil y de corto plazo.
- Si un tweet está marcado como [Contiene imagen/s], puede haber información importante en la imagen que no está en el texto.
- Si está marcado como [RETWEET por @usuario], tené en cuenta que @usuario está amplificando un mensaje de otro autor.
- Tweets vagos o ambiguos (especialmente si dependen de imágenes o capturas) deben ser ignorados o señalados como fuera de contexto.
`;

// --- TWEETS ---
const tweets = items.map((item, i) => {
  const autorOriginal = item.json.url.match(/x\.com\/(.*?)\//)?.[1] || "desconocido";
  const fecha = new Date(item.json.date).toLocaleString("es-AR", { timeZone: "America/Argentina/Buenos_Aires" });
  const tieneImagen = item.json.has_image ? " - [Contiene imagen/s]" : "";
  const prefijo = item.json.is_retweet ? ` - [RETWEET por @${item.json.user || "desconocido"}] ` : "";

  return `Tweet de @${autorOriginal} #${i + 1} - Publicado el ${fecha}${tieneImagen}${prefijo}\n${item.json.content.replace(/\n/g, ' ')}`;
}).join('\n\n');

let prompt = '';

if (tipoHoy.tipo.includes('Feriado') || tipoHoy.tipo.includes('Fin de semana')) {
    prompt = `
⚠️ Hoy es un día no hábil para los mercados argentinos o estadounidenses (feriado o fin de semana). Aun así, tu rol como analista de research de una reconocida ALyC argentina sigue siendo clave: tu tarea es analizar los siguientes tweets y elaborar un informe que permita anticipar el clima con el que podría abrir el mercado el próximo día hábil.

${header}

Tu reporte debe seguir este formato ESTRICTAMENTE:

**PANORAMA DEL DÍA SIN MERCADO 🌐**
Un párrafo breve que mencione el motivo por el cual hoy no hay operaciones (feriado nacional, fin de semana, feriado USA) y qué tipo de noticias, rumores o datos están circulando y podrían influir en la apertura del próximo día hábil.

**LO QUE SE HABLA HOY EN EL MERCADO INFORMAL 💬**
Seleccioná de 3 a 5 tweets relevantes. Para cada uno:
- Mencioná al autor con el formato: "**Comenta @usuario:**"
- Parafraseá el contenido o citá la parte más relevante del tweet.

**ADELANTO PARA EL PRÓXIMO DÍA HÁBIL 📈**
En formato de bullet points:
- **Clima general esperado:** ¿Qué se percibe en redes sobre lo que puede pasar el lunes?
- **Eventos clave en agenda:** ¿Qué datos, reuniones o noticias están previstos para el próximo día hábil?
- **Activos a observar:** ¿Se mencionan en los tweets bonos, acciones o el dólar informal? ¿Qué expectativas hay?

**REFLEXIONES DEL ANALISTA 🧠**
- ¿Qué sensación deja el día?
- ¿Qué debería monitorear un inversor entre hoy y el lunes?
- ¿Cuál es tu hipótesis más razonable sobre cómo podría arrancar la semana?

Evitá inventar información que no esté en los tweets.
Enfocate en lo que puede incidir en la próxima apertura.
Sos un analista de verdad, tu trabajo puede cambiar decisiones.

${footer}

---
TWEETS A ANALIZAR:
${tweets}
    
`;
}
else if (tipoHoy.tipo === 'Pre-Market') {
  prompt = `
Eres un analista de research de una reconocida ALyC argentina. Tu tarea es analizar los siguientes tweets, que fueron publicados desde el cierre de ayer hasta ahora, y generar un reporte "pre-mercado" para un inversor. El objetivo es anticipar el clima de la apertura.

${header}

El reporte debe tener el siguiente formato OBLIGATORIAMENTE:

**PULSO PRE-MERCADO 📈**
Un párrafo corto (2-3 líneas) que resuma el sentimiento general, las noticias clave (políticas, económicas, internacionales) y las expectativas para la apertura de la bolsa y el dólar.

**TWEETS CLAVE DE LA MAÑANA 💬**
Selecciona los 3 a 5 tweets más importantes. Para cada uno:
-   Menciona al autor: "**Según @usuario:**"
-   Cita o parafrasea de cerca el contenido del tweet.
-   Ejemplo: "**Según @FulanitoFinanzas:** 'El dato de inflación de USA puede pegarle a los bonos en la apertura. Atentos al CCL.'"

**APRECIACIONES DEL ANALISTA ☕**
Aquí es donde aportas tu valor. En formato de bullet points, responde a estas preguntas basándote en los tweets y tu conocimiento:
-   **Clima General:** ¿El ambiente es optimista, pesimista o de espera? ¿Por qué?
-   **Posibles Drivers:** ¿Qué activos o noticias podrían ser los protagonistas de la rueda de hoy?
-   **A qué estar atento:** ¿Hay algún dato, evento o declaración programada para hoy que sea crucial?
-   **Hipótesis del Día:** ¿Cuál es tu hipótesis inicial? (Ej: "Espero una apertura alcista para el Merval impulsada por el buen humor externo, pero con un CCL presionado al alza por rumores políticos.")

Sé riguroso, directo y enfócate en información que ayude a tomar decisiones. No inventes datos que no estén en los tweets proporcionados.

${footer}

---
TWEETS A ANALIZAR:
${tweets}
`
} else if (tipoHoy.tipo === 'Intra-Day') {
  prompt = `
Eres un analista de research de una reconocida ALyC argentina. Son las 12:00 PM y el mercado ya está operando. Tu tarea es analizar los siguientes tweets, que reflejan lo que está pasando AHORA, y generar un reporte de "media rueda".

${header}

El reporte debe tener el siguiente formato OBLIGATORIAMENTE:

**PULSO DE MEDIA RUEDA 📊**
Un párrafo corto (2-3 líneas) resumiendo la tendencia principal del mercado hasta ahora. ¿Se cumplieron las expectativas de la mañana? ¿Hay sorpresas?

**LO QUE ESTÁ SONANDO AHORA 📢**
Selecciona los 3 a 5 tweets más relevantes de la última hora. Para cada uno:
-   Menciona al autor: "**Informa @usuario:**"
-   Cita o parafrasea de cerca el contenido del tweet, enfocándote en la inmediatez.
-   Ejemplo: "**Informa @TraderSincero:** 'El BCRA está vendiendo dólares para frenar la suba. El MEP ya reaccionó y perforó los $1100.'"

**APRECIACIONES DEL ANALISTA ⚙️**
En formato de bullet points, responde a estas preguntas:
-   **Confirmación o Sorpresa:** ¿La dinámica del mercado confirma la hipótesis de la mañana o la descarta por completo? ¿Qué cambió?
-   **Tendencias Clave:** ¿Qué sectores o activos están liderando las subas o bajas? ¿Hay mucho volumen?
-   **El Dato del Momento:** ¿Cuál es el tema central de conversación ahora mismo? (Ej: Una medida del gobierno, el movimiento de un bono específico, un rumor fuerte).
-   **Recomendación Táctica:** Basado en lo visto, ¿sugieres mantener la calma, tomar ganancias, buscar oportunidades o esperar al cierre? Justifica brevemente.

Sé conciso, rápido y relevante. Estás informando en medio del fragor del mercado.

${footer}

---
TWEETS A ANALIZAR:
${tweets}    
`;
} else {
  prompt = `
Eres un analista de research de una reconocida ALyC argentina. La rueda ya cerró. Tu tarea es analizar los tweets del día y generar un reporte de "cierre de mercado" que sirva como balance y preparación para mañana.

${header}

El reporte debe tener el siguiente formato OBLIGATORIAMENTE:

**EL BALANCE DEL DÍA 📝**
Un párrafo (3-4 líneas) que cuente la historia de la rueda de hoy. ¿Cómo empezó, cómo terminó y cuál fue el principal factor que la movió?

**LAS VOCES DEL CIERRE 🗣️**
Selecciona los 3 a 5 tweets más importantes que resuman el día o den una perspectiva para mañana. Para cada uno:
-   Menciona al autor: "**Analiza @usuario:**"
-   Cita o parafrasea el análisis o conclusión del tweet.
-   Ejemplo: "**Analiza @ElContadorCripto:** 'Jornada de toma de ganancias en el Merval, pero los bonos en dólares siguen firmes. La clave fue la baja del riesgo país.'"

**APRECIACIONES DEL ANALISTA 🍷**
En formato de bullet points, haz una reflexión profunda sobre la jornada:
-   **La Conclusión Principal:** ¿Cuál es el aprendizaje o la conclusión más importante del día de hoy?
-   **Ganadores y Perdedores:** ¿Qué estrategias o activos funcionaron bien y cuáles sufrieron?
-   **Señales para Mañana:** ¿Hay alguna señal en el cierre de hoy (ej. volumen, cotizaciones after-market, noticias de último momento) que nos dé una pista para la apertura de mañana?
-   **Visión Actualizada:** ¿Cómo modifica el día de hoy tu visión general del mercado a corto plazo?

Elabora un análisis sereno y fundamentado, extrayendo las lecciones del día.

${footer}

---
TWEETS A ANALIZAR:
${tweets}    
`;
}

return [{ json: { prompt } }];