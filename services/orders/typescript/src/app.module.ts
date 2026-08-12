import { Module } from '@nestjs/common';
import { CatalogClient } from './catalog.client';
import { HealthController, OrdersController } from './orders.controller';
import { OrdersRepository } from './orders.repository';
import { OrdersService } from './orders.service';
import { PaymentsClient } from './payments.client';

/**
 * Compare with the monolith's app.module.ts, which imported a CatalogModule, an
 * OrdersModule and a PaymentsModule and made the database `@Global` so all three could
 * share it.
 *
 * Two of those modules are gone. They are not smaller here, or refactored, or
 * simplified — they are in other repositories' worth of process, written in other
 * languages, deployed on their own schedule. What is left in their place is a
 * CatalogClient and a PaymentsClient: two objects that know an address and how to be
 * disappointed.
 *
 * That is the trade in one file. The module boundary became a network boundary, and
 * everything Session 3 teaches is the cost of that sentence.
 */
@Module({
  controllers: [OrdersController, HealthController],
  providers: [OrdersRepository, OrdersService, CatalogClient, PaymentsClient],
})
export class AppModule {}
