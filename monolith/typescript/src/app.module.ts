import { Global, Module } from '@nestjs/common';
import { CatalogModule } from './catalog/catalog.module';
import { Database } from './database';
import { HealthController } from './health.controller';
import { OrdersModule } from './orders/orders.module';
import { PaymentsModule } from './payments/payments.module';

/**
 * The database is @Global because in a monolith there is exactly one, and every
 * module shares it. That single line is the architectural decision this whole
 * bootcamp interrogates: it is what makes the transaction in OrdersService possible,
 * and it is precisely what Session 3 takes away when each service gets its own store.
 */
@Global()
@Module({ providers: [Database], exports: [Database] })
class DatabaseModule {}

@Module({
  imports: [DatabaseModule, CatalogModule, PaymentsModule, OrdersModule],
  controllers: [HealthController],
})
export class AppModule {}
