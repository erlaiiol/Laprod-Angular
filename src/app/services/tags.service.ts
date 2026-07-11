import { Injectable, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { Observable, shareReplay, tap } from 'rxjs';

export interface Tag {
  id:       number;
  name:     string;
  category: { name: string; color: string; description: string | null };
}

// Correspond au JSON retourné par get_all_tags() → /filters/tags/all
// Le même appel renvoie désormais tags + gammes + styles (un seul fetch)
export interface TagsResponse {
  success: boolean;
  data: {
    tags:    Tag[];
    keys:    string[];   // gammes distinctes issues des tracks approuvés
    styles:  string[];   // styles distincts  issues des tracks approuvés
  };
}

@Injectable({
  providedIn: 'root',
})
export class TagsService {

  private tagsApiUrl = `${environment.apiUrl}/api/filters/tags/all`;

  private _tags = signal<Tag[]>([]);
  private _keys = signal<string[]>([]);
  private _styles = signal<string[]>([])

  tags    = this._tags.asReadonly();
  keys    = this._keys.asReadonly();
  styles  = this._styles.asReadonly();

  // Catégories uniques avec description, dans l'ordre d'apparition
  categories = computed(() => {
    const seen = new Set<string>();
    const result: { name: string; color: string; description: string | null }[] = [];
    for (const tag of this._tags()) {
      if (!seen.has(tag.category.name)) {
        seen.add(tag.category.name);
        result.push(tag.category);
      }
    }
    return result;
  });

  // Données quasi statiques : une requête partagée entre tous les abonnés
  // (shareReplay) et réutilisée pendant TTL_MS avant re-fetch.
  private cache$: Observable<TagsResponse> | null = null;
  private fetchedAt = 0;
  private static readonly TTL_MS = 5 * 60_000;

  constructor(private http: HttpClient ) {}

  /**
   * Source unique pour /filters/tags/all : les signals tags/keys/styles sont
   * alimentés en interne, tous les abonnés partagent la même requête HTTP.
   */
  ensureLoaded(): Observable<TagsResponse> {
    if (!this.cache$ || Date.now() - this.fetchedAt > TagsService.TTL_MS) {
      this.fetchedAt = Date.now();
      this.cache$ = this.http.get<TagsResponse>(this.tagsApiUrl).pipe(
        tap({
          next: res => {
            if (res.success) {
              this._tags.set(res.data.tags);
              this._keys.set(res.data.keys);
              this._styles.set(res.data.styles);
            }
          },
          // Ne pas rester bloqué sur un cache en erreur : le prochain appel re-fetche.
          error: () => { this.cache$ = null; },
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.cache$;
  }

  invalidate(): void {
    this.cache$ = null;
  }

  /** @deprecated Alias de compatibilité — préférer ensureLoaded(). */
  getTags(): Observable<TagsResponse> {
    return this.ensureLoaded();
  }

  /** @deprecated Alias de compatibilité — préférer ensureLoaded(). */
  loadTags(): Observable<TagsResponse> {
    return this.ensureLoaded();
  }

  refreshTags(): void {
    this.invalidate();
    this.ensureLoaded().subscribe({ error: () => {} });
  }
}
