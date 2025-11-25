import { ECSClient, RunTaskCommand } from "@aws-sdk/client-ecs";

const ecsClient = new ECSClient();

// --- CONFIGURACIÓN DE FERIADOS (Copiada de lambda_processor) ---
const feriados = [
    { mes: 1, dia: 1, motivo: "Año nuevo", tipo: "inamovible" },
    { mes: 3, dia: 3, motivo: "Carnaval", tipo: "inamovible" },
    { mes: 3, dia: 4, motivo: "Carnaval", tipo: "inamovible" },
    { mes: 3, dia: 24, motivo: "Día Nacional de la Memoria por la Verdad y la Justicia", tipo: "inamovible" },
    { mes: 4, dia: 2, motivo: "Día del Veterano y de los Caídos en la Guerra de Malvinas", tipo: "inamovible" },
    { mes: 4, dia: 18, motivo: "Viernes Santo", tipo: "inamovible" },
    { mes: 5, dia: 1, motivo: "Día del Trabajador", tipo: "inamovible" },
    { mes: 5, dia: 2, motivo: "Puente turístico no laborable", tipo: "puente" },
    { mes: 5, dia: 25, motivo: "Día de la Revolución de Mayo", tipo: "inamovible" },
    { mes: 6, dia: 16, motivo: "Paso a la Inmortalidad del General Martín Güemes", tipo: "trasladable" },
    { mes: 6, dia: 20, motivo: "Paso a la Inmortalidad del General Manuel Belgrano", tipo: "inamovible" },
    { mes: 7, dia: 9, motivo: "Día de la Independencia", tipo: "inamovible" },
    { mes: 8, dia: 15, motivo: "Puente turístico no laborable", tipo: "puente" },
    { mes: 8, dia: 17, motivo: "Paso a la Inmortalidad del Gral. José de San Martín", tipo: "trasladable" },
    { mes: 10, dia: 10, motivo: "Puente turístico no laborable", tipo: "puente" },
    { mes: 10, dia: 12, motivo: "Día del Respeto a la Diversidad Cultural", tipo: "trasladable" },
    { mes: 11, dia: 21, motivo: "Puente turístico no laborable", tipo: "puente" },
    { mes: 11, dia: 24, motivo: "Día de la Soberanía Nacional", tipo: "trasladable" },
    { mes: 12, dia: 8, motivo: "Día de la Inmaculada Concepción de María", tipo: "inamovible" },
    { mes: 12, dia: 25, motivo: "Navidad", tipo: "inamovible" }
];

const feriadosUSA = [
    { mes: 1, dia: 1, motivo: "New Year's Day", tipo: "Federal" },
    { mes: 1, dia: 20, motivo: "Martin Luther King Jr. Day", tipo: "Federal (Market Holiday)" },
    { mes: 2, dia: 17, motivo: "Washington’s Birthday (Presidents’ Day)", tipo: "Federal (Market Holiday)" },
    { mes: 3, dia: 28, motivo: "Good Friday", tipo: "Religious (Market Holiday)" },
    { mes: 5, dia: 26, motivo: "Memorial Day", tipo: "Federal (Market Holiday)" },
    { mes: 6, dia: 19, motivo: "Juneteenth National Independence Day", tipo: "Federal" },
    { mes: 7, dia: 4, motivo: "Independence Day", tipo: "Federal (Market Holiday)" },
    { mes: 9, dia: 1, motivo: "Labor Day", tipo: "Federal (Market Holiday)" },
    { mes: 11, dia: 27, motivo: "Thanksgiving Day", tipo: "Federal (Market Holiday)" },
    { mes: 12, dia: 25, motivo: "Christmas Day", tipo: "Federal (Market Holiday)" }
];

function getFeriadoAR(fecha) {
    const mes = fecha.getMonth() + 1;
    const dia = fecha.getDate();
    return feriados.find(f => f.dia === dia && f.mes === mes);
}

function getFeriadoUSA(fecha) {
    const mes = fecha.getMonth() + 1;
    const dia = fecha.getDate();
    return feriadosUSA.find(f => f.mes === mes && f.dia === dia);
}

function isHoliday(date) {
    return !!getFeriadoAR(date) || !!getFeriadoUSA(date);
}

export const handler = async (event) => {
    console.log("Scheduler Event Received:", JSON.stringify(event));

    // 1. Obtener hora actual en Argentina
    const now = new Date();
    const timeZone = "America/Argentina/Buenos_Aires";
    const argTimeStr = now.toLocaleString("en-US", { timeZone });
    const argDate = new Date(argTimeStr);

    const hour = argDate.getHours();
    // ISO Weekday: 1 (Mon) - 7 (Sun)
    // JS getDay(): 0 (Sun) - 6 (Sat)
    // Map JS to ISO: 0 -> 7, else same
    const jsDay = argDate.getDay();
    const weekday = jsDay === 0 ? 7 : jsDay;

    const esFeriado = isHoliday(argDate);

    console.log(`Time (ARG): ${argDate.toISOString()}, Hour: ${hour}, Weekday (ISO): ${weekday}, Holiday: ${esFeriado}`);

    // 2. Evaluar Condición
    const cond1 = esFeriado && (hour >= 20 && hour < 21);
    const cond2 = (hour >= 20 && hour < 21) && (weekday > 5);
    const cond3 = !esFeriado && (hour < 20 || hour >= 21) && (weekday <= 5);

    const shouldRun = cond1 || cond2 || cond3;

    console.log(`Conditions: Holiday@20h=${cond1}, Weekend@20h=${cond2}, WeekdayNot20h=${cond3} => SHOULD RUN: ${shouldRun}`);

    if (shouldRun) {
        try {
            const cluster = process.env.ECS_CLUSTER;
            const taskDefinition = process.env.ECS_TASK_DEFINITION;
            const subnets = process.env.ECS_SUBNETS ? process.env.ECS_SUBNETS.split(',') : [];
            const securityGroups = process.env.ECS_SECURITY_GROUPS ? process.env.ECS_SECURITY_GROUPS.split(',') : [];

            if (!cluster || !taskDefinition || subnets.length === 0) {
                throw new Error("Missing ECS configuration (ECS_CLUSTER, ECS_TASK_DEFINITION, ECS_SUBNETS)");
            }

            const command = new RunTaskCommand({
                cluster: cluster,
                taskDefinition: taskDefinition,
                launchType: "FARGATE",
                networkConfiguration: {
                    awsvpcConfiguration: {
                        subnets: subnets,
                        securityGroups: securityGroups,
                        assignPublicIp: "ENABLED"
                    }
                }
            });

            const response = await ecsClient.send(command);
            console.log("ECS Task Started:", response.tasks[0].taskArn);
            return { statusCode: 200, body: "Task started" };

        } catch (error) {
            console.error("Error starting ECS task:", error);
            throw error;
        }
    } else {
        console.log("Condition not met. Skipping execution.");
        return { statusCode: 200, body: "Skipped" };
    }
};
