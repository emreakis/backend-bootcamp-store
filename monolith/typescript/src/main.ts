/**
 * The HTTP layer. The only place in the process that knows what a status code is.
 *
 * Everything the controllers call is domain logic that would be identical in a CLI
 * tool. That separation is not decoration: in Session 3, catalog and payments grow
 * their own HTTP and gRPC edges, and the module code underneath them barely changes.
 */

import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { Logger } from '@nestjs/common';
import { AppModule } from './app.module';
import { ProblemFilter } from './problem.filter';
import { config } from './config';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { logger: ['log', 'warn', 'error'] });
  app.useGlobalFilters(new ProblemFilter());
  await app.listen(config.port, '0.0.0.0');
  new Logger('Bootstrap').log(
    `store (${config.implementation}) listening on :${config.port}`);
}

bootstrap();
