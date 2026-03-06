import { ECSClient, RunTaskCommand } from "@aws-sdk/client-ecs";
import { getArgentinaTime, isHoliday } from "./argentina-time.mjs";

const ecsClient = new ECSClient();

export const handler = async (event) => {
    console.log("Scheduler Event Received:", JSON.stringify(event));

    // 1. Obtener hora actual en Argentina
    const { hour, day, month, weekday } = getArgentinaTime();
    const esFeriado = isHoliday({ month, day });

    console.log(`ARG: ${month}/${day} ${hour}h, weekday=${weekday}, holiday=${esFeriado}`);

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
                capacityProviderStrategy: [
                    {
                        capacityProvider: "FARGATE_SPOT",
                        weight: 1
                    }
                ],
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
