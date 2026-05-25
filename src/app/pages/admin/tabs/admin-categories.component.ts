import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminService, AdminCategory } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { TagsService } from '../../../services/tags.service';

@Component({
  selector: 'app-admin-categories',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-categories.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminCategoriesComponent implements OnInit {

  loading    = signal(false);
  categories = signal<AdminCategory[]>([]);

  newCatName  = signal('');
  newCatColor = signal('#6b7280');

  // Édition inline d'une catégorie existante
  editingId    = signal<number | null>(null);
  editName     = signal('');
  editColor    = signal('#6b7280');
  editDesc     = signal<string>('');

  // One tag-input field per category (keyed by category id)
  tagInputs: Record<number, string> = {};

  constructor(private adminSvc: AdminService, private toast: ToastService, private TagsService: TagsService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getCategories().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) this.categories.set(res.data.categories);
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement catégories.' });
      },
    });
  }

  createCategory(): void {
    const name = this.newCatName().trim();
    if (!name) return;
    this.adminSvc.createCategory(name, this.newCatColor()).subscribe(({
      next: res => {
        if (res.success) { 
          this.newCatName.set(''); 
          this.load();
          this.TagsService.refreshTags(); }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    }));   // Force refresh du cache de tags pour que les nouvelles catégories soient prises en compte partout
  }

  startEdit(cat: AdminCategory): void {
    this.editingId.set(cat.id);
    this.editName.set(cat.name);
    this.editColor.set(cat.color || '#6b7280');
    this.editDesc.set(cat.description || '');
  }

  cancelEdit(): void { this.editingId.set(null); }

  saveEdit(cat: AdminCategory): void {
    const name = this.editName().trim();
    if (!name) return;
    this.adminSvc.editCategory(cat.id, name, this.editColor(), this.editDesc().trim() || null).subscribe({
      next: res => {
        if (res.success) { this.editingId.set(null); this.load(); this.TagsService.refreshTags(); }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur modification.' }); },
    });
  }

  deleteCategory(cat: AdminCategory): void {
    if (!confirm(`Supprimer la catégorie "${cat.name}" et tous ses tags ?`)) return;
    this.adminSvc.deleteCategory(cat.id).subscribe({
      next: res => { if (res.success) this.load(); this.TagsService.refreshTags(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  tagInput(catId: number): string { return this.tagInputs[catId] ?? ''; }

  setTagInput(catId: number, val: string): void { this.tagInputs[catId] = val; }

  createTag(cat: AdminCategory): void {
    const name = (this.tagInputs[cat.id] ?? '').trim();
    if (!name) return;
    this.adminSvc.createTag(name, cat.id).subscribe({
      next: res => {
        if (res.success) { this.tagInputs[cat.id] = ''; this.load(); this.TagsService.refreshTags(); }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  deleteTag(tagId: number): void {
    this.adminSvc.deleteTag(tagId).subscribe({
      next: res => { if (res.success) this.load(); this.TagsService.refreshTags(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }
}
