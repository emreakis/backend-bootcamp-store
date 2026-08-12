import { Controller, Get, Param, Query } from '@nestjs/common';
import { CatalogService } from './catalog.service';
import { ValidationFailed } from '../errors';

@Controller('v1/products')
export class CatalogController {
  constructor(private readonly catalog: CatalogService) {}

  @Get()
  list(@Query('limit') limit?: string, @Query('cursor') cursor?: string) {
    let parsed = 20;
    if (limit !== undefined) {
      parsed = Number(limit);
      if (!Number.isInteger(parsed) || parsed < 1 || parsed > 100) {
        throw new ValidationFailed('limit must be an integer between 1 and 100.');
      }
    }
    return this.catalog.listProducts(parsed, cursor);
  }

  @Get(':sku')
  get(@Param('sku') sku: string) {
    return this.catalog.getProduct(sku);
  }
}
