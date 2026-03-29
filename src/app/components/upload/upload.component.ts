import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { UploadService, UploadTrackData } from '../../services/upload.service';
import { TagsService } from '../../services/tags.service';

interface Tag {
  id: number;
  name: string;
  category: string;
}

@Component({
  selector: 'app-upload',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './upload.component.html',
  styleUrls: ['./upload.component.scss']
})
export class UploadComponent implements OnInit {
  uploadForm: FormGroup;
  loading = false;
  uploadSuccess = false;
  uploadError: string | null = null;


  // Options pour les selects
  availableKeys: string[] = [];
  availableStyles: string[] = [];
  availableTags: Tag[] = [];

  // Fichiers sélectionnés
  selectedFiles: { [key: string]: File | null } = {
    mp3: null,
    wav: null,
    image: null,
    stems: null
  };

  constructor(
    private fb: FormBuilder,
    private uploadService: UploadService,
    private tagsService: TagsService
  ) {
    this.uploadForm = this.fb.group({
      title: ['', [Validators.required, Validators.minLength(1), Validators.maxLength(100)]],
      bpm: ['', [Validators.required, Validators.min(60), Validators.max(200)]],
      key: ['', Validators.required],
      style: ['', Validators.required],
      price_mp3: [9.99, [Validators.required, Validators.min(0)]],
      price_wav: [19.99, [Validators.required, Validators.min(0)]],
      price_stems: [49.99, [Validators.required, Validators.min(0)]],
      sacem_percentage_composer: [50, [Validators.required, Validators.min(0), Validators.max(85)]],
      selectedTags: [[]]
    });



  }

  ngOnInit() {
    this.loadUploadOptions();
  }

  loadUploadOptions() {
    this.uploadService.getUploadOptions().subscribe({
      next: (response) => {
        if (response.success) {
          this.availableKeys = response.keys;
          this.availableStyles = response.styles;
          this.availableTags = response.tags;
        }
      },
      error: (err) => {
        console.error('Erreur chargement options:', err);
      }
    });
  }

  onFileSelected(event: Event, fileType: string) {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files[0]) {
      this.selectedFiles[fileType] = input.files[0];
    }
  }

  onSubmit() {
    if (this.uploadForm.invalid) {
      this.markFormGroupTouched();
      return;
    }

    if (!this.selectedFiles['mp3']) {
      this.uploadError = 'Le fichier MP3 est obligatoire';
      return;
    }

    this.loading = true;
    this.uploadError = null;
    this.uploadSuccess = false;

    const formValue = this.uploadForm.value;

    const uploadData: UploadTrackData = {
      title: formValue.title,
      bpm: formValue.bpm,
      key: formValue.key,
      style: formValue.style,
      price_mp3: formValue.price_mp3,
      price_wav: formValue.price_wav,
      price_stems: formValue.price_stems,
      sacem_percentage_composer: formValue.sacem_percentage_composer,
      tag_ids: formValue.selectedTags.join(','),
      file_mp3: this.selectedFiles['mp3']!,
      file_wav: this.selectedFiles['wav'] || undefined,
      file_image: this.selectedFiles['image'] || undefined,
      file_stems: this.selectedFiles['stems'] || undefined
    };

    this.uploadService.uploadTrack(uploadData).subscribe({
      next: (response) => {
        this.loading = false;
        if (response.success) {
          this.uploadSuccess = true;
          this.uploadForm.reset();
          this.selectedFiles = { mp3: null, wav: null, image: null, stems: null };
        } else {
          this.uploadError = response.error || 'Erreur lors de l\'upload';
        }
      },
      error: (err) => {
        this.loading = false;
        console.error('Erreur upload:', err);
        this.uploadError = 'Erreur de connexion avec le serveur';
      }
    });
  }

  private markFormGroupTouched() {
    Object.keys(this.uploadForm.controls).forEach(key => {
      const control = this.uploadForm.get(key);
      control?.markAsTouched();
    });
  }

  isFieldInvalid(fieldName: string): boolean {
    const field = this.uploadForm.get(fieldName);
    return !!(field && field.invalid && field.touched);
  }

  onTagChange(event: Event, tagId: number) {
    const checkbox = event.target as HTMLInputElement;
    const selectedTags = this.uploadForm.get('selectedTags')?.value || [];



    if (checkbox.checked) {
      if (!selectedTags.includes(tagId)) {
        selectedTags.push(tagId);
      }
    } else {
      const index = selectedTags.indexOf(tagId);
      if (index > -1) {
        selectedTags.splice(index, 1);
      }
    }

    this.uploadForm.get('selectedTags')?.setValue(selectedTags);
  }

  getFieldError(fieldName: string): string | null {
    const control = this.uploadForm.get(fieldName);
    if (!control || !control.errors) return null;

    if (control.errors['required']) {
      return 'Ce champ est requis';
    }
    if (control.errors['min']) {
      return `Valeur minimale: ${control.errors['min'].min}`;
    }
    if (control.errors['max']) {
      return `Valeur maximale: ${control.errors['max'].max}`;
    }
    if (control.errors['minlength']) {
      return `Longueur minimale: ${control.errors['minlength'].requiredLength}`;
    }
    if (control.errors['maxlength']) {
      return `Longueur maximale: ${control.errors['maxlength'].requiredLength}`;
    }

    return null; // aucun autre message d’erreur
  }
}