import { Injectable, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { Observable } from 'rxjs';

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

  constructor(private http: HttpClient ) {}

  getTags(): Observable<TagsResponse> {
    return this.http.get<TagsResponse>(this.tagsApiUrl);
  }

  loadTags(): Observable<TagsResponse> {
    const obs = this.http.get<TagsResponse>(this.tagsApiUrl);
    obs.subscribe({
      next: res => {
        if (res.success) {
          this._tags.set(res.data.tags);
          this._keys.set(res.data.keys);
          this._styles.set(res.data.styles);
        }
      },
    });
    return obs;
  }

  refreshTags() {
    this.loadTags();
  }


}
