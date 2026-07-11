import { Pipe, PipeTransform } from '@angular/core';

/**
 * Formatage de dates fr-FR partagé (remplace les formatDate/fmtDate dupliqués
 * dans les composants). Pipe pur : mémoïsé par valeur d'entrée, contrairement
 * à un appel de méthode ré-exécuté à chaque cycle de change detection.
 *
 *   {{ iso | formatDate }}             → 10/07/2026
 *   {{ iso | formatDate:'long' }}      → 10 juillet 2026
 *   {{ iso | formatDate:'monthYear' }} → juillet 2026
 *   {{ iso | formatDate:'time' }}      → 22:41
 */
@Pipe({ name: 'formatDate', standalone: true })
export class FormatDatePipe implements PipeTransform {
  transform(iso: string | null | undefined, mode: 'date' | 'long' | 'monthYear' | 'time' = 'date'): string {
    if (!iso) return '—';
    const d = new Date(iso);
    switch (mode) {
      case 'time':      return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
      case 'monthYear': return d.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
      case 'long':      return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
      default:          return d.toLocaleDateString('fr-FR');
    }
  }
}
