import OpenAI from "openai";
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { SSMClient, GetParametersCommand } from "@aws-sdk/client-ssm";
import { getArgentinaTime, getFeriadoAR, getFeriadoUSA, TIMEZONE } from "./argentina-time.mjs";

const s3Client = new S3Client();
const ssmClient = new SSMClient();

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
    // Obtener fecha/hora actual en Argentina
    const { hour, day, month, year, weekday, asUTCDate: hoy } = getArgentinaTime();
    const diaSemana = weekday === 7 ? 0 : weekday; // Convertir ISO (7=Dom) a JS (0=Dom)

    // Estado de hoy
    const feriadoAR = getFeriadoAR({ month, day });
    const feriadoUSA = getFeriadoUSA({ month, day });
    const tipoHoy = getTipoDia({ feriadoAR, feriadoUSA, diaSemana, hour });

    // Estado de mañana
    const manana = new Date(hoy);
    manana.setUTCDate(hoy.getUTCDate() + 1);
    const mananaMonth = manana.getUTCMonth() + 1;
    const mananaDay = manana.getUTCDate();
    const diaSemanaManana = manana.getUTCDay();
    const feriadoARManana = getFeriadoAR({ month: mananaMonth, day: mananaDay });
    const feriadoUSAManana = getFeriadoUSA({ month: mananaMonth, day: mananaDay });
    const tipoManana = getTipoDia({ feriadoAR: feriadoARManana, feriadoUSA: feriadoUSAManana, diaSemana: diaSemanaManana, hour: 10 });

    // --- HEADER ---
    const header = `
📅 Fecha actual: ${hoy.toLocaleDateString('es-AR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: TIMEZONE })}
📌 Tipo de día: ${tipoHoy.tipo}${tipoHoy.motivo ? ` (${tipoHoy.motivo}${tipoHoy.tipoFeriado ? ', ' + tipoHoy.tipoFeriado : ''})` : ''}
📅 Estado de mañana: ${manana.toLocaleDateString('es-AR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: TIMEZONE })}
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


async function uploadToGitHub(filename, content, GITHUB_TOKEN) {
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


async function getSecrets() {
    const command = new GetParametersCommand({
        Names: ['/twitter-scraper/GITHUB_TOKEN', '/twitter-scraper/OPENAI_API_KEY'],
        WithDecryption: true
    });
    const { Parameters } = await ssmClient.send(command);
    const secrets = {};
    if (Parameters) {
        Parameters.forEach(p => {
            if (p.Name.endsWith('GITHUB_TOKEN')) secrets.GITHUB_TOKEN = p.Value;
            if (p.Name.endsWith('OPENAI_API_KEY')) secrets.OPENAI_API_KEY = p.Value;
        });
    }
    return secrets;
}

export const handler = async (event) => {
    console.log("Event received:", JSON.stringify(event, null, 2));

    try {
        // 0. Obtener datos de S3 y Secretos
        const { bucket, s3Key } = event.detail;

        const [secrets, items] = await Promise.all([
            getSecrets(),
            fetchFromS3(bucket, s3Key)
        ]);

        const { GITHUB_TOKEN, OPENAI_API_KEY } = secrets;
        console.log(`Loaded ${items.length} items from s3://${bucket}/${s3Key}`);

        // 1. Generar Prompt
        const { prompt, tipo } = generateAnalysisPrompt(items);

        // 2. Llamar a OpenAI
        const client = new OpenAI({ apiKey: OPENAI_API_KEY });
        const res = await client.responses.create({
            model: process.env.OPENAI_MODEL || 'gpt-5-nano',
            input: prompt,
        });

        // 3. Formatear contenido
        const { filename, content } = formatBlogPost(res.output_text, tipo);

        // 4. Subir a GitHub
        const ghResponse = await uploadToGitHub(filename, content, GITHUB_TOKEN);

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
