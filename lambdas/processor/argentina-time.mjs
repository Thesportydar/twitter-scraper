const TIMEZONE = "America/Argentina/Buenos_Aires";

// --- FERIADOS ARGENTINA ---
const feriadosAR = [
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

// --- FERIADOS USA ---
const feriadosUSA = [
    { mes: 1, dia: 1, motivo: "New Year's Day", tipo: "Federal" },
    { mes: 1, dia: 19, motivo: "Martin Luther King Jr. Day", tipo: "Federal" },
    { mes: 2, dia: 16, motivo: "Washington's Birthday (Presidents' Day)", tipo: "Federal" },
    { mes: 4, dia: 3, motivo: "Good Friday", tipo: "Observance" },
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

/**
 * Obtiene la fecha/hora actual en Argentina usando formatToParts
 * @returns {{ hour: number, day: number, month: number, year: number, weekday: number }}
 *          weekday: 1=Lunes, 7=Domingo (ISO)
 */
export function getArgentinaTime() {
    const now = new Date();
    const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: TIMEZONE,
        year: "numeric",
        month: "numeric",
        day: "numeric",
        hour: "numeric",
        weekday: "short",
        hour12: false
    });
    const p = Object.fromEntries(formatter.formatToParts(now).map(({ type, value }) => [type, value]));

    return {
        hour: parseInt(p.hour, 10),
        day: parseInt(p.day, 10),
        month: parseInt(p.month, 10),
        year: parseInt(p.year, 10),
        weekday: { Sun: 7, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }[p.weekday],
        // Date en UTC con valores de Argentina
        asUTCDate: new Date(Date.UTC(parseInt(p.year), parseInt(p.month) - 1, parseInt(p.day), parseInt(p.hour)))
    };
}

/**
 * Busca feriado argentino para una fecha
 * @param {{ month: number, day: number }} fecha 
 */
export function getFeriadoAR({ month, day }) {
    const feriado = feriadosAR.find(f => f.dia === day && f.mes === month);
    if (!feriado) return null;
    return { motivo: feriado.motivo, tipo: feriado.tipo };
}

/**
 * Busca feriado USA para una fecha
 * @param {{ month: number, day: number }} fecha 
 */
export function getFeriadoUSA({ month, day }) {
    const feriado = feriadosUSA.find(f => f.dia === day && f.mes === month);
    if (!feriado) return null;
    return { motivo: feriado.motivo, tipo: feriado.tipo };
}

/**
 * Verifica si una fecha es feriado (AR o USA)
 * @param {{ month: number, day: number }} fecha 
 */
export function isHoliday({ month, day }) {
    return !!getFeriadoAR({ month, day }) || !!getFeriadoUSA({ month, day });
}

export { TIMEZONE, feriadosAR, feriadosUSA };
