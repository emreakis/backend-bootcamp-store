import { Module } from '@nestjs/common';
import { PaymentsService } from './payments.service';

/**
 * Note what is missing: no controller. Payments has no HTTP surface of its own —
 * it is reachable only through `orders`. In Session 3 that stays true, which is why
 * payments is the service that gets gRPC instead of REST: nothing outside the
 * system ever calls it directly.
 */
@Module({
  providers: [PaymentsService],
  exports: [PaymentsService],
})
export class PaymentsModule {}
