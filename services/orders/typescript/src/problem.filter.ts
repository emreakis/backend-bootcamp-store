/**
 * One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
 *
 * A client that learns this shape once handles every failure this API can produce, and
 * a client written against orders already knows how to read an error from catalog.
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
    let retryAfterSeconds: number | undefined;

    if (exception instanceof DomainError) {
      ({ kind, title, status, detail, retryAfterSeconds } = exception);
    } else if (exception instanceof HttpException && exception.getStatus() === 404) {
      // A path that matches no route. Nest's default body is `{"message": ...}`,
      // which is a second error shape for clients to learn. One envelope, everywhere,
      // including the boring cases.
      status = 404;
      kind = 'order-not-found';
      title = 'Order not found';
      detail = `No order with id '${request.path}'.`;
    } else if (exception instanceof HttpException) {
      status = exception.getStatus();
      kind = 'request-failed';
      title = exception.name;
      detail = exception.message;
    } else {
      // Anything we did not name is a bug, and the caller must not be told to change
      // its request. 500, and the detail stays in our logs — never in a response body,
      // where it becomes a client's problem to parse and an attacker's to read.
      this.logger.error(`unhandled error on ${request.path}`, exception as Error);
      status = 500;
      kind = 'internal-error';
      title = 'Internal server error';
      detail = 'The request could not be completed.';
    }

    response.status(status).setHeader('Content-Type', 'application/problem+json');
    if (retryAfterSeconds !== undefined) {
      // Tells a well-behaved client when to come back, so it backs off instead of
      // joining the stampede that is currently keeping the dependency down.
      response.setHeader('Retry-After', String(retryAfterSeconds));
    }
    response.json({
      type: PROBLEM_BASE + kind,
      title,
      status,
      detail,
      instance: request.path,
    });
  }
}
