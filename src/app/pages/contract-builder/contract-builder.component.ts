import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ContractBuilderService, ContractSummary } from '../../services/contract-builder.service';
import { ToastService } from '../../services/toast.service';

@Component({
  selector: 'app-contract-builder',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './contract-builder.component.html',
  styleUrl: './contract-builder.component.scss',
})
export class ContractBuilderComponent implements OnInit {

  loading   = signal(false);
  creating  = signal(false);
  contracts = signal<ContractSummary[]>([]);
  newTitle  = signal('');

  constructor(
    private svc:    ContractBuilderService,
    private router: Router,
    private toast:  ToastService,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.svc.listContracts().subscribe({
      next: res => {
        if (res.success && res.data) this.contracts.set(res.data.contracts);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  create(): void {
    const title = this.newTitle().trim();
    if (!title) return;
    this.creating.set(true);
    this.svc.createContract(title).subscribe({
      next: res => {
        this.creating.set(false);
        if (res.success && res.data) {
          this.router.navigate(['/contract-builder', res.data.contract.id]);
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
      },
      error: err => {
        this.creating.set(false);
        const msg = err?.error?.feedback?.message ?? 'Erreur lors de la création.';
        this.toast.showToast({ level: 'error', message: msg });
      },
    });
  }

  open(id: number): void {
    this.router.navigate(['/contract-builder', id]);
  }

  fmtDate(d: string): string {
    return new Date(d).toLocaleDateString('fr-FR');
  }
}
