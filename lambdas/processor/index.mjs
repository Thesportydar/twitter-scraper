import OpenAI from "openai";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";

const s3Client = new S3Client();

/* const feriados = fetch(`https://api.argentinadatos.com/v1/feriados/${(new Date()).getFullYear()}`)
  .then(res => res.json())
  .then(data => data.map(f => {
    const date = new Date(f.fecha + 'T00:00:00-03:00');
    return { mes: date.getMonth() + 1, dia: date.getDate(), motivo: f.nombre, tipo: "inamovible" };
  })); */

const feriados = [
    { mes: 1, dia: 1, motivo: "Año nuevo", tipo: "inamovible" },
    { mes: 2, dia: 16, motivo: "Carnaval", tipo: "inamovible" },
    { mes: 2, dia: 17, motivo: "Carnaval", tipo: "inamovible" },
    { mes: 3, dia: 23, motivo: "Día no laborable con fines turísticos", tipo: "puente" },
    { mes: 3, dia: 24, motivo: "Día Nacional de la Memoria por la Verdad y la Justicia", tipo: "inamovible" },
    { mes: 4, dia: 2, motivo: "Día del Veterano y de los Caídos en la Guerra de Malvinas", tipo: "inamovible" },
    { mes: 4, dia: 3, motivo: "Viernes Santo", tipo: "inamovible" },
    { mes: 5, dia: 1, motivo: "Día del Trabajador", tipo: "inamovible" },
    { mes: 5, dia: 25, motivo: "Día de la Revolución de Mayo", tipo: "inamovible" },
    { mes: 6, dia: 15, motivo: "Paso a la Inmortalidad del General Martín Güemes", tipo: "trasladable" },
    { mes: 6, dia: 20, motivo: "Paso a la Inmortalidad del General Manuel Belgrano", tipo: "inamovible" },
    { mes: 7, dia: 9, motivo: "Día de la Independencia", tipo: "inamovible" },
    { mes: 7, dia: 10, motivo: "Puente turístico no laborable", tipo: "puente" },
    { mes: 8, dia: 17, motivo: "Paso a la Inmortalidad del Gral. José de San Martín", tipo: "trasladable" },
    { mes: 10, dia: 12, motivo: "Día de la Raza", tipo: "trasladable" },
    { mes: 11, dia: 23, motivo: "Día de la Soberanía Nacional", tipo: "trasladable" },
    { mes: 12, dia: 7, motivo: "Puente turístico no laborable", tipo: "puente" },
    { mes: 12, dia: 8, motivo: "Día de la Inmaculada Concepción de María", tipo: "inamovible" },
    { mes: 12, dia: 25, motivo: "Navidad", tipo: "inamovible" },
    { mes: 12, dia: 31, motivo: "Fin de Año", tipo: "inamovible" }
];

// --- CONFIGURACIÓN ---
const feriadosUSA = [
    { mes: 1, dia: 1, motivo: "New Year's Day", tipo: "Federal" },
    { mes: 1, dia: 19, motivo: "Martin Luther King Jr. Day", tipo: "Federal" },
    { mes: 2, dia: 16, motivo: "Washington's Birthday (Presidents' Day)", tipo: "Federal" },
    { mes: 3, dia: 3, motivo: "Good Friday", tipo: "Observance" },
    { mes: 5, dia: 25, motivo: "Memorial Day", tipo: "Federal" },
    { mes: 6, dia: 19, motivo: "Juneteenth National Independence Day", tipo: "Federal" },
    { mes: 7, dia: 3, motivo: "Independence Day (Observed)", tipo: "Federal" },
    { mes: 7, dia: 4, motivo: "Independence Day", tipo: "Federal" },
    { mes: 9, dia: 7, motivo: "Labor Day", tipo: "Federal" },
    { mes: 10, dia: 12, motivo: "Columbus Day", tipo: "Federal" },
    { mes: 11, dia: 11, motivo: "Veterans Day", tipo: "Federal" },
    { mes: 11, dia: 26, motivo: "Thanksgiving Day", tipo: "Federal" },
    { mes: 12, dia: 25, motivo: "Christmas Day", tipo: "Federal" }
];

// --- FUNCIONES AUXILIARES ---
function getFeriadoAR(fecha) {
    const year = fecha.getYear();
    const mes = fecha.getMonth() + 1;
    const dia = fecha.getDate();
    const feriadoObj = feriados.find(f => f.dia === dia && f.mes === mes);
    if (feriadoObj) {
        const feriado = feriadoObj;
        return {
            motivo: feriado.motivo,
            fecha: `${dia}/${mes}/${year}`,
            info: feriado.info,
            tipo: feriado.tipo,
            //id: feriado.id
        };
    } else {
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
            tipo.push(hour < 11 ? "Pre-Mercado" : (hour < 16 ? "Media-Rueda" : "Post-Mercado"));
        }
    }
    return {
        tipo: tipo.join(" y "),
        motivo: motivos.length ? motivos.join(" y ") : undefined,
        tipoFeriado: tiposFeriado.length ? tiposFeriado.join(" y ") : undefined,
        esFeriado: tipo.some(t => t.includes("Feriado"))
    };
}
function generateAnalysisPrompt(items) {

    // --- LÓGICA PRINCIPAL ---
    const now = new Date();
    // Crear un objeto Date que represente la hora en Argentina (para extraer hora y día correctamente en entorno UTC)
    const argTimeStr = now.toLocaleString("en-US", { timeZone: "America/Argentina/Buenos_Aires" });
    const hoy = new Date(argTimeStr);

    const hour = hoy.getHours();
    const diaSemana = hoy.getDay(); // 0=Domingo, 6=Sábado

    // Estado de hoy
    const feriadoAR = getFeriadoAR(hoy);
    const feriadoUSA = getFeriadoUSA(hoy);
    const tipoHoy = getTipoDia({ feriadoAR, feriadoUSA, diaSemana, hour });

    // Estado de mañana
    const manana = new Date(hoy);
    manana.setDate(hoy.getDate() + 1);
    const feriadoARManana = getFeriadoAR(manana);
    const feriadoUSAManana = getFeriadoUSA(manana);
    const diaSemanaManana = manana.getDay();
    const tipoManana = getTipoDia({ feriadoAR: feriadoARManana, feriadoUSA: feriadoUSAManana, diaSemana: diaSemanaManana, hour: 10 }); // hour=10 para Pre-Market

    // --- HEADER ---
    const header = `
📅 Fecha actual: ${hoy.toLocaleDateString('es-AR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
📌 Tipo de día: ${tipoHoy.tipo}${tipoHoy.motivo ? ` (${tipoHoy.motivo}${tipoHoy.tipoFeriado ? ', ' + tipoHoy.tipoFeriado : ''})` : ''}
📅 Estado de mañana: ${manana.toLocaleDateString('es-AR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
📌 Tipo de día mañana: ${tipoManana.tipo}${tipoManana.motivo ? ` (${tipoManana.motivo}${tipoManana.tipoManana ? ', ' + tipoManana.tipoFeriado : ''})` : ''}
`;

    const footer = `
📌 INSTRUCCIONES ADICIONALES:
- No hagas suposiciones que no estén respaldadas por el contenido de los tweets.
- Ignorá información irrelevante o redundante; enfocate en lo que aporta valor al análisis.
- Recordá que el objetivo es ayudar a un inversor real a tomar decisiones en un entorno volátil y de corto plazo.
- Si un tweet está marcado como [Contiene imagen/s], puede haber información importante en la imagen que no está en el texto.
- Si está marcado como [RETWEET por @usuario], tené en cuenta que @usuario está amplificando un mensaje de otro autor.
- Tweets vagos o ambiguos (especialmente si dependen de imágenes o capturas) deben ser ignorados o señalados como fuera de contexto.
- No incluyas frases de ofrecimiento, disponibilidad, ni cierres tipo "quedo a disposición", "consultame", "espero tus comentarios", etc. Limítate al análisis solicitado.
`;

    // --- TWEETS ---
    const tweets = items.map((item, i) => {
        const autorOriginal = item.url.match(/x\.com\/(.*?)\//)?.[1] || "desconocido";
        const fecha = new Date(item.date).toLocaleString("es-AR", { timeZone: "America/Argentina/Buenos_Aires" });
        const tieneImagen = item.has_image ? " - [Contiene imagen/s]" : "";
        const prefijo = item.is_retweet ? ` - [RETWEET por @${item.user || "desconocido"}] ` : "";

        return `Tweet de @${autorOriginal} #${i + 1} - Publicado el ${fecha}${tieneImagen}${prefijo}\n${item.content.replace(/\n/g, ' ')}`;
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
    else if (tipoHoy.tipo === 'Pre-Mercado') {
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
    } else if (tipoHoy.tipo === 'Media-Rueda') {
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

    return { prompt, "tipo": tipoHoy.tipo }
}


function formatBlogPost(contenido, tipo) {
    const fecha = new Date();
    const timeZone = 'America/Argentina/Buenos_Aires';

    // Fecha ISO YYYY-MM-DD en Argentina
    const fechaISO = fecha.toLocaleDateString('en-CA', { timeZone });

    // Día de la semana capitalizado en español
    const dia = fecha.toLocaleDateString('es-AR', { weekday: 'long', timeZone });
    const diaCapitalizado = dia.charAt(0).toUpperCase() + dia.slice(1);

    // PubDate con hora, formato inglés (Jul 4 2025 10:00)
    const hora = fecha.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone });
    const pubDateDate = fecha.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        timeZone
    });
    const pubDate = `${pubDateDate} ${hora}`;

    // Fecha legible para descripción
    const fechaLegible = fecha.toLocaleDateString('es-AR', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric',
        timeZone
    });

    const descMap = {
        'Pre-Mercado': `Análisis generado por IA antes de la apertura, con los tweets clave del ecosistema financiero argentino. (${fechaLegible})`,
        'Media-Rueda': `Lectura rápida de media jornada con IA: qué se comenta en Twitter financiero y cómo reacciona el mercado. (${fechaLegible})`,
        'Post-Mercado': `Cierre del día bursátil según la IA y Twitter. Ganadores, perdedores y señales para mañana. (${fechaLegible})`,
        'Feriado': `Hoy no operó el mercado. La IA resume lo más relevante del día en Twitter económico y financiero. (${fechaLegible})`,
    };

    const heroMap = {
        'Pre-Mercado': '../../assets/hero-pre.webp',
        'Media-Rueda': '../../assets/hero-intra.webp',
        'Post-Mercado': '../../assets/hero-post.webp',
        'Feriado': '../../assets/hero-feriado.webp',
    };

    const frontmatter = `---
title: '${diaCapitalizado}: ${tipo}'
description: '${descMap[tipo] || 'Resumen del día financiero generado por IA.'}'
pubDate: '${pubDate}'
heroImage: '${heroMap[tipo] || '../../assets/hero-feriado.webp'}'
---`;

    return {
        filename: `${fechaISO}-${tipo.replace(/\s/g, '-').toLowerCase()}.md`,
        content: `${frontmatter}\n\n${contenido}`
    }
};


async function uploadToGitHub(filename, content) {
    const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
    const OWNER = process.env.GITHUB_OWNER;
    const REPO = process.env.GITHUB_REPO;
    const PATH = 'frontend/src/content/blog';

    const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${PATH}/${filename}`;

    const body = {
        message: `upload ${filename}`,
        content: Buffer.from(content).toString('base64'),
        branch: 'main'
    };

    const response = await fetch(url, {
        method: 'PUT',
        headers: {
            'Authorization': `Bearer ${GITHUB_TOKEN}`,
            'Content-Type': 'application/json',
            'User-Agent': 'Lambda-Report-Generator'
        },
        body: JSON.stringify(body)
    });

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`GitHub API Error: ${response.status} ${response.statusText} - ${errorText}`);
    }

    return await response.json();
}


async function fetchFromS3(bucket, key) {
    if (!bucket || !key) {
        throw new Error("Missing bucket or s3Key");
    }
    const getCommand = new GetObjectCommand({
        Bucket: bucket,
        Key: key
    });
    const s3Response = await s3Client.send(getCommand);
    const s3Body = await s3Response.Body.transformToString();
    return JSON.parse(s3Body);
}


export const handler = async (event) => {
    console.log("Event received:", JSON.stringify(event, null, 2));

    try {
        // 0. Obtener datos de S3
        const { bucket, s3Key } = event.detail;
        const items = await fetchFromS3(bucket, s3Key);
        console.log(`Loaded ${items.length} items from s3://${bucket}/${s3Key}`);

        // 1. Generar Prompt
        const { prompt, tipo } = generateAnalysisPrompt(items);

        // 2. Llamar a OpenAI
        const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
        const res = await client.responses.create({
            model: "gpt-5-nano",
            input: prompt,
        });

        // 3. Formatear contenido
        const { filename, content } = formatBlogPost(res.output_text, tipo);

        // 4. Subir a GitHub
        const ghResponse = await uploadToGitHub(filename, content);

        return {
            statusCode: 200,
            body: JSON.stringify({ message: 'Report generated and pushed to GitHub', url: ghResponse.content.html_url }),
        };

    } catch (error) {
        console.error("Error in handler:", error);
        return {
            statusCode: 500,
            body: JSON.stringify({ error: error.message }),
        };
    }
};