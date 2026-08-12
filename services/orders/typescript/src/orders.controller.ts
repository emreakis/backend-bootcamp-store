import { Body, Controller, Get, Headers, HttpCode, Param, Post, Res } from '@nestjs/common';
import type { Response } from 'express';
import { config } from './config';
import type { CreateOrderRequest, Order } from './model';
import { OrdersService } from './orders.service';

@Controller('v1/orders')
export class OrdersController {
  constructor(private readonly orders: OrdersService) {}

  @Post()
  async create(
    @Body() body: CreateOrderRequest,
    @Headers('idempotency-key') idempotencyKey: string | undefined,
    @Res({ passthrough: true }) response: Response,
  ): Promise<Order> {
    const order = await this.orders.checkout(body?.items, idempotencyKey);
    response.status(201).setHeader('Location', `/v1/orders/${order.id}`);
    return order;
  }

  @Get(':id')
  get(@Param('id') id: string): Promise<Order> {
    return this.orders.getOrder(id);
  }

  @Post(':id/cancel')
  @HttpCode(200)
  cancel(@Param('id') id: string): Promise<Order> {
    return this.orders.cancel(id);
  }
}

@Controller()
export class HealthController {
  /**
   * Liveness only, and here that matters more than anywhere else in the system.
   *
   * Orders has dependencies, so the temptation to check them is real. Give in to it
   * and a payments outage makes orders report unhealthy, and the platform starts
   * restarting orders pods — removing capacity from a service that was working, during
   * an incident, because we told it to.
   *
   * Orders is not sick when payments is down. It is degraded. That distinction belongs
   * in metrics and alerts, not in the endpoint an orchestrator uses to decide whether
   * to kill you.
   */
  @Get('health')
  health() {
    return { status: 'ok', implementation: config.implementation };
  }
}
