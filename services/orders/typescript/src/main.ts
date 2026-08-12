/**
 * ORDERS — the orchestrator.
 *
 * REST at the edge, gRPC inside, two databases it cannot join across, and the only
 * service in this system that can be woken up by somebody else's outage.
 *
 * Everything here satisfies contracts/orders.v1.yaml; if this file and that file
 * disagree, this file is wrong.
 */

import 'reflect-metadata';
import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { config } from './config';
import { ProblemFilter } from './problem.filter';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { logger: ['log', 'warn', 'error'] });
  app.useGlobalFilters(new ProblemFilter());

  // 0.0.0.0, not localhost. A process that binds to the loopback interface is
  // unreachable from outside its own container no matter how the network is wired —
  // one of those mistakes that works perfectly on a laptop and fails on every platform.
  await app.listen(config.port, '0.0.0.0');

  new Logger('Bootstrap').log(
    `orders (${config.implementation}) listening on :${config.port}`);
}

bootstrap();
