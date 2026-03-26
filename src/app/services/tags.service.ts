import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../environments/environment';
import { Observable, tap } from 'rxjs';

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

  constructor(private http: HttpClient) {}

  getTags(): Observable<TagsResponse> {
    return this.http.get<TagsResponse>(this.tagsApiUrl).pipe(
      tap(data => console.log('TagsService.getTags() called', data))
    );
  }
}
