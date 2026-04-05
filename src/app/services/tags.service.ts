import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { Observable } from 'rxjs';
import { AdminCategoriesComponent } from '../pages/admin/tabs/admin-categories.component';

export interface Tag {
  id:       number;
  name:     string;
  category: { name: string; color: string };  // objet unique (pas un tableau)
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

  private tagsApiUrl = `${environment.apiUrl}/filters/tags/all`;

  private _tags = signal<Tag[]>([]);
  private _keys = signal<string[]>([]);
  private _styles = signal<string[]>([])

  tags = this._tags.asReadonly();
  keys = this._keys.asReadonly();
  styles = this._styles.asReadonly();

  constructor(private http: HttpClient ) {}

  getTags(): Observable<TagsResponse> {
    return this.http.get<TagsResponse>(this.tagsApiUrl);
  }

  loadTags() {
    this.http.get<TagsResponse>(this.tagsApiUrl).subscribe({
      next: res => {
        if (res.success) {
          this._tags.set(res.data.tags);
          this._keys.set(res.data.keys);
          this._styles.set(res.data.styles);
          console.log('tags, keys and styles loaded. loadtags() called in tags.service.ts')
        }
      }
    })
  }

  refreshTags() {
    this.loadTags();
  }


}
