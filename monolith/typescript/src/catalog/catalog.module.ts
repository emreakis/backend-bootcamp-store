import { Module } from '@nestjs/common';
import { CatalogController } from './catalog.controller';
import { CatalogService } from './catalog.service';

/**
 * The module boundary, made explicit.
 *
 * `exports` is the public API of this module. Delete CatalogService from that array
 * and OrdersService stops compiling — Nest will refuse to inject a provider its
 * owning module did not export. That is a boundary a framework can actually
 * enforce, and it is the closest thing a monolith has to a network boundary.
 *
 * In Session 3 this array becomes an OpenAPI document.
 */
@Module({
  controllers: [CatalogController],
  providers: [CatalogService],
  exports: [CatalogService],
})
export class CatalogModule {}
