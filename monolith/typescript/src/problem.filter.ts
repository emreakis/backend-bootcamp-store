/**
 * One error envelope, everywhere. RFC 9457 Problem Details.
 *
 * A client that learns this shape once handles every failure this API can produce.
 * Bespoke error bodies per endpoint are how you make consumers write a parser per
 * endpoint.
 *
 * This filter is the single place in the process where a domain outcome becomes a
 * status code — the translation happens once, at the edge, not in every service.
 */

import { ArgumentsHost, Catch, ExceptionFilter, HttpException, Logger } from '@nestjs/common';
import type { Request, Response } from 'express';
import { DomainError } from './errors';

const PROBLEM_BASE = 'https://bootcamp.backendguru.io/problems/';

@Catch()
export class ProblemFilter implements ExceptionFilter {
  private readonly logger = new Logger(ProblemFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const http = host.switchToHttp();
    const request = http.getRequest<Request>();
    const response = http.getResponse<Response>();

    let kind: string;
    let title: string;
    let status: number;
    let detail: string;

    if (exception instanceof DomainError) {
      ({ kind, title, status, detail } = exception);
    } else if (exception instanceof HttpException) {
      // Nest's own errors — a 404 for an unrouted path, say. Still owed our envelope.
      status = exception.getStatus();
      kind = status === 404 ? 'not-found' : 'request-failed';
      title = exception.name;
      detail = exception.message;
    } else {
      // Anything we did not name is a bug, and the caller must not be told to change
      // its request. 500, and the detail stays in our logs.
      this.logger.error(`unhandled error on ${request.path}`, exception as Error);
      status = 500;
      kind = 'internal-error';
      title = 'Internal server error';
      detail = 'The request could not be completed.';
    }

    response
      .status(status)
      .setHeader('Content-Type', 'application/problem+json')
      .json({
        type: PROBLEM_BASE + kind,
        title,
        status,
        detail,
        instance: request.path,
      });
  }
}
