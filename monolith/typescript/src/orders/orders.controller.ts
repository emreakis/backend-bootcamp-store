import { Body, Controller, Get, HttpCode, Param, Post, Res } from '@nestjs/common';
import type { Response } from 'express';
import { OrdersService, OrderItem } from './orders.service';

@Controller('v1/orders')
export class OrdersController {
  constructor(private readonly orders: OrdersService) {}

  @Post()
  create(@Body() body: { items: OrderItem[] }, @Res({ passthrough: true }) res: Response) {
    const order = this.orders.checkout(body?.items);
    res.status(201).setHeader('Location', `/v1/orders/${order.id}`);
    return order;
  }

  @Get(':id')
  get(@Param('id') id: string) {
    return this.orders.getOrder(id);
  }

  @Post(':id/cancel')
  @HttpCode(200)
  cancel(@Param('id') id: string) {
    return this.orders.cancel(id);
  }
}
