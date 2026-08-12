import { Controller, Get } from '@nestjs/common';
import { config } from './config';

@Controller()
export class HealthController {
  /**
   * Liveness only — deliberately checks nothing downstream.
   *
   * Session 3 revisits this. A health check that calls its dependencies turns one
   * service's outage into everyone's outage, because the platform starts killing
   * healthy pods for being downstream of a sick one.
   */
  @Get('health')
  health() {
    return { status: 'ok', implementation: config.implementation };
  }
}
