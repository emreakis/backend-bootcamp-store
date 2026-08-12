import { Module } from '@nestjs/common';
import { CatalogModule } from '../catalog/catalog.module';
import { PaymentsModule } from '../payments/payments.module';
import { OrdersController } from './orders.controller';
import { OrdersService } from './orders.service';

/**
 * `imports` is this module's dependency list, and it is the architecture diagram
 * written down. Orders depends on catalog and payments; neither depends on orders,
 * and neither depends on the other.
 *
 * That shape is not an accident — it is what makes the three modules splittable in
 * Session 3. A cycle here (catalog importing orders) would mean two services that
 * cannot be deployed independently, which means they were never two services.
 */
@Module({
  imports: [CatalogModule, PaymentsModule],
  controllers: [OrdersController],
  providers: [OrdersService],
})
export class OrdersModule {}
