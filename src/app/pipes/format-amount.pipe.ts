import { Pipe, PipeTransform } from '@angular/core';

/** Montant en euros : {{ 12.5 | formatAmount }} → "12.50 €". Pipe pur, mémoïsé. */
@Pipe({ name: 'formatAmount', standalone: true })
export class FormatAmountPipe implements PipeTransform {
  transform(n: number | null | undefined): string {
    if (n === null || n === undefined) return '—';
    return n.toFixed(2) + ' €';
  }
}
